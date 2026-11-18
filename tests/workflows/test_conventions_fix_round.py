"""A failed conventions check on an autopilot pull request gets the
autopilot's fix round, which corrects the title or the commits (#699 C3).
conventions.sh writes its errors, by what they are about, to ERRORS_FILE;
conventions.yml keeps them as the `conventions-errors` artifact; the fix
round reads them into its inputs and its prompt says how to fix each: the
title through `autopilot.py title`, applied after the agent ends once
`conventions.sh --title` passes it, and a commit's header by rewording the
branch's own commits, pushed with a lease and only with the same tree."""
import importlib.util
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONVENTIONS = ROOT / "scripts" / "conventions.sh"


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


autopilot = load("autopilot_c3", "autopilot.py")


def wf(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def test_the_fix_round_runs_on_a_failed_conventions_check():
    for name, job in (("org-pull-request.yml", "autopilot-fix"), ("pull-request.yml", "autopilot-fix")):
        j = wf(name)["jobs"][job]
        cond = " ".join(str(j["if"]).split())
        assert "conventions" in j["needs"], name
        assert "needs.conventions.result == 'failure'" in cond, name
        assert "github.event.action != 'edited'" in cond and "vars.DX_BOT_LOGIN" in cond, name
        assert j["with"]["mode"] == "fix", name


def git(cwd, *args):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_conventions_writes_its_errors_by_what_they_are_about(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "-c", "user.name=a", "-c", "user.email=a@b", "commit", "-q", "--allow-empty", "-m", "chore: base")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "-c", "user.name=a", "-c", "user.email=a@b", "commit", "-q", "--allow-empty", "-m", "Fixed the thing")
    head = git(repo, "rev-parse", "HEAD")
    errors = tmp_path / "errors.tsv"
    env = dict(os.environ, BRANCH="fix/1-a-thing", TITLE="Fix the thing.", BASE=base, HEAD_REF=head, SECTIONS="",
               ERRORS_FILE=str(errors), REVIEW_BOT="dilux-bot[bot]")
    out = subprocess.run(["bash", str(CONVENTIONS)], cwd=repo, env=env, capture_output=True, text=True)
    assert out.returncode == 1, out.stdout + out.stderr
    kinds = [line.split("\t", 1)[0] for line in errors.read_text(encoding="utf-8").splitlines()]
    assert kinds == ["title", "commit"], kinds


def test_conventions_checks_a_title_alone():
    ok = subprocess.run(["bash", str(CONVENTIONS), "--title", "fix(autopilot): a thing"], capture_output=True, text=True)
    bad = subprocess.run(["bash", str(CONVENTIONS), "--title", "Fix a thing."], capture_output=True, text=True)
    assert (ok.returncode, bad.returncode) == (0, 1)


def test_the_conventions_job_keeps_its_errors():
    steps = wf("conventions.yml")["jobs"]["conventions"]["steps"]
    check = next(s for s in steps if s.get("name") == "Check branch, title and commits")
    assert check["env"]["ERRORS_FILE"]
    keep = next(s for s in steps if "upload-artifact" in str(s.get("uses", "")))
    assert keep["with"]["name"] == "conventions-errors" and "failure()" in str(keep["if"])


def test_the_fix_round_reads_them_and_says_how_to_fix_each():
    text = (ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8")
    assert "name: conventions-errors" in text
    note = autopilot.conventions_note("title\tThe pull request title is not a Conventional Commit header\ncommit\tCommit abc1234 is not one\n")
    assert "title \"<the new title>\"" in note and "reword" in note and "the same tree" in note
    prompt = autopilot.prompt_fix("o/r", "8", 1, 3, checks=True, conventions="title\tx\n")
    assert autopilot.CONVENTIONS_LOG in prompt and "title" in prompt
    assert "title" in autopilot.INTENTS
    # The helper checks the title as conventions.sh does, then leaves it in
    # the outbox; the apply checks it again before it edits the pull request.
    assert autopilot.title_ok("fix(autopilot): a thing") and not autopilot.title_ok("Fix a thing.")
    src = (ROOT / "scripts/autopilot.py").read_text(encoding="utf-8")
    apply = src[src.index("def _apply_intents("):]
    apply = apply[:apply.index("\ndef ")]
    assert 'kind == "title"' in apply and "--title" in apply and '"pr", "edit"' in apply


def test_a_reworded_branch_goes_with_a_lease_and_the_same_tree():
    text = (ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8")
    step = text[text.index("- name: The agent's commits and intents"):]
    step = step[:step.index("autopilot.py apply .dx-out/outbox.jsonl")]
    assert "REWORD" in step and 'git diff --quiet "origin/$BRANCH" "$new"' in step
    assert "api-commit.py push \"$BRANCH\" --force" in step and "lease" in step
