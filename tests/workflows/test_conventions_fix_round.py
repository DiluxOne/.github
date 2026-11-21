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
from unittest import mock

import yaml

try:
    import steps  # tests/workflows/steps.py: it runs a workflow's step with stubs
except ModuleNotFoundError:  # Test first's base has no steps.py (#845): there each call to it fails an assertion
    steps = mock.Mock(**{f"{n}.side_effect": AssertionError("tests/workflows/steps.py is missing") for n in ("evaluate", "run", "step", "workflow")})
run, step = steps.run, steps.step

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
    kinds = [kind for kind, _ in (line.split("\t", 1) for line in errors.read_text(encoding="utf-8").splitlines())]
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


def test_the_apply_sets_a_title_that_passes_and_refuses_one_that_does_not(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(autopilot, "gh", lambda *args, **kw: calls.append(list(args)) or "")
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    failed = autopilot._apply_intents([{"kind": "title", "text": "Fix a thing."}], "o/r", 7, 8)
    assert failed == 1 and calls == [] and not output.exists()
    autopilot._apply_intents([{"kind": "title", "text": "fix(autopilot): a thing"}], "o/r", 7, 8)
    assert calls == [["pr", "edit", "8", "--repo", "o/r", "--title", "fix(autopilot): a thing"]]
    assert "retitled=true" in output.read_text()


# The engine's scripts the apply step calls, as stand-ins: each records its
# argv and answers from FAKE_<SCRIPT>_<SUBCOMMAND> (stdout) and
# FAKE_<SCRIPT>_<SUBCOMMAND>_RC (exit code).
FAKE = """import json, os, sys
name, args = os.path.basename(sys.argv[0]), sys.argv[1:]
with open(os.environ["DX_CALLS"], "a") as f:
    f.write(json.dumps([name] + args) + "\\n")
key = "FAKE_" + "".join(c if c.isalnum() else "_" for c in name[:-3] + "_" + (args[0] if args else "")).upper()
sys.stdout.write(os.environ.get(key, ""))
sys.exit(int(os.environ.get(key + "_RC", "0")))
"""


def reworded(tmp_path, same_tree=True, reword_ok="true", lease_holds=True):
    """The apply step's run with a branch the agent reworded: (ran, the
    base the branch forks from main at)."""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    ident = ["-c", "user.name=a", "-c", "user.email=a@b"]
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(work))
    git(work, *ident, "commit", "-q", "--allow-empty", "-m", "chore: base")
    base = git(work, "rev-parse", "HEAD")
    git(work, "push", "-q", "origin", "main")
    git(work, "checkout", "-q", "-b", "fix/1-a")
    (work / "a.txt").write_text("a\n")
    git(work, "add", "a.txt")
    git(work, *ident, "commit", "-q", "-m", "Fixed a")
    git(work, "push", "-q", "origin", "fix/1-a")
    git(work, "fetch", "-q", "origin")
    there = git(work, "rev-parse", "HEAD")
    git(work, *ident, "commit", "-q", "--amend", "-m", "fix: a")
    if not same_tree:
        (work / "a.txt").write_text("b\n")
        git(work, "add", "a.txt")
        git(work, *ident, "commit", "-q", "--amend", "-m", "fix: a")
    (work / ".dx-out").mkdir()
    git(work, "bundle", "create", "-q", ".dx-out/work.bundle", "HEAD")
    git(work, "checkout", "-q", "--detach", there)
    files = {f".dx-central/scripts/{n}": FAKE for n in ("autopilot.py", "api-commit.py")}
    # A central autopilot.py that knows `describe` (#924), so the step runs it.
    files[".dx-central/scripts/autopilot.py"] = FAKE + "\n\ndef describe_body():\n    pass\n"
    sha = there if lease_holds else "f" * 40
    env = {"BRANCH": "fix/1-a", "DEFAULT": "main", "ENGINE": "false", "PR": "8", "NUMBER": "1", "REWORD_OK": reword_ok,
           "DX_BOT_LOGIN": "dilux-bot[bot]", "DX_BOT_ID": "1", "FAKE_AUTOPILOT_READY_GOES_RC": "0"}
    ran = run(step("autopilot.yml", "applied", job="apply"), tmp_path, env=env, files=files, central=False,
              stubs={"gh": f"echo {sha}"})
    return ran, base


def test_a_reworded_branch_with_the_same_tree_goes_with_a_lease(tmp_path):
    ran, base = reworded(tmp_path)
    assert ran.code == 0, ran.stdout + ran.stderr
    assert ["api-commit.py", "push", "fix/1-a", "--force", "--onto", base] in ran.calls
    assert ["gh", "api", "repos/o/r/branches/fix/1-a", "--jq", ".commit.sha"] in ran.calls
    # #924: the description is rewritten before the reworded history is
    # pushed, so the review that push starts reads the new one.
    describe = ["autopilot.py", "apply", ".dx-out/outbox.jsonl", "+describe"]
    push = ["api-commit.py", "push", "fix/1-a", "--force", "--onto", base]
    assert ran.calls.count(describe) == 1, ran.calls
    assert ran.calls.index(describe) < ran.calls.index(push)


def test_a_reworded_branch_with_another_tree_is_not_pushed(tmp_path):
    ran, _ = reworded(tmp_path, same_tree=False)
    assert ran.code == 1 and "do not build on fix/1-a" in ran.stdout
    assert not ran.of("api-commit.py")


def test_a_rewrite_outside_a_conventions_fix_round_is_not_pushed(tmp_path):
    ran, _ = reworded(tmp_path, reword_ok="false")
    assert ran.code == 1 and not ran.of("api-commit.py")


def test_a_branch_that_moved_on_github_is_not_written_over(tmp_path):
    ran, _ = reworded(tmp_path, lease_holds=False)
    assert ran.code == 1 and "the lease does not hold" in ran.stdout
    assert not ran.of("api-commit.py")
    # #927: a lost lease pushes nothing, so the description is not
    # rewritten either: the gh read of the branch comes before the edit.
    assert ["autopilot.py", "apply", ".dx-out/outbox.jsonl", "+describe"] not in ran.calls, ran.calls


def test_a_round_that_only_retitles_ends_ready_and_the_test_repository_answers_it():
    """#699 C7: the release scenario `conventions-fix` plays it: the fixed
    change sets the draft's own title (prep's `fixed title`), and the end
    rule takes the title it set for the round's work, not a silent end."""
    steps = {s.get("id") or s.get("name"): s for s in wf("autopilot.yml")["jobs"]["apply"]["steps"]}
    assert steps["end"]["env"]["RETITLED"] == "${{ steps.applied.outputs.retitled }}"
    prep = "\n".join(str(s.get("run") or "") for s in wf("autopilot.yml")["jobs"]["prep"]["steps"])
    assert "autopilot.py fixed title" in prep
    source = (ROOT / "scripts" / "autopilot.py").read_text(encoding="utf-8")
    assert 'fh.write("retitled=true\\n")' in source
    assert 'pushed = pushed or (mode == "fix" and os.environ.get("RETITLED") == "true")' in source
    assert autopilot.end_verdict("fix", "8", False, False, 1, 1, False, 1, 3, pushed=True) == "ready"
