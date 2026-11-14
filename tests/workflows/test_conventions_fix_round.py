"""A failed conventions check on an autopilot pull request gets the
autopilot's fix round (#699 C3), as any failed check does: the check keeps
its errors, the round reads them, the agent corrects the title (through
`autopilot.py title`) or rewords its own commits, and the apply job pushes a
reword only when nothing but the messages changed. A second identical
failure stops it."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def load():
    spec = importlib.util.spec_from_file_location("autopilot", SCRIPTS / "autopilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ap = load()


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def cond(job):
    return " ".join(str(job["if"]).split())


def test_the_fix_round_runs_on_a_failed_conventions_check_everywhere():
    for name in ("org-pull-request.yml", "pull-request.yml"):
        job = workflow(name)["jobs"]["autopilot-fix"]
        assert job["needs"] == ["conventions", "review"], name
        c = cond(job)
        assert "(needs.review.outputs.blocking == 'true' || needs.conventions.result == 'failure')" in c, name
        # Not on an edit, not on a fork, only dilux-bot's autopilot pull request.
        for piece in ("github.event.action != 'edited'", "github.event.pull_request.head.repo.full_name == github.repository",
                      "github.event.pull_request.user.login == vars.DX_BOT_LOGIN", "contains(github.event.pull_request.labels.*.name, 'autopilot')"):
            assert piece in c, (name, piece)
        assert job["with"]["mode"] == "fix"


def test_the_check_keeps_its_errors_for_the_round():
    steps = workflow("conventions.yml")["jobs"]["conventions"]["steps"]
    check = next(s for s in steps if s.get("name") == "Check branch, title and commits")
    assert check["env"]["CONVENTIONS_OUT"] == "${{ runner.temp }}/conventions.txt"
    keep = next(s for s in steps if s.get("name") == "Keep the errors for the autopilot")
    assert keep["with"]["name"] == "dx-conventions" and keep["if"].startswith("failure()")
    assert "vars.DX_BOT_LOGIN" in keep["if"] and keep["uses"].startswith("actions/upload-artifact@")


def test_the_round_reads_them_and_asks_for_the_title_or_the_headers():
    prep = workflow("autopilot.yml")["jobs"]["prep"]
    steps = prep["steps"]
    dl = next(s for s in steps if (s.get("with") or {}).get("name") == "dx-conventions")
    assert dl["continue-on-error"] is True and "inputs.mode == 'fix'" in dl["if"]
    may = next(s for s in steps if s.get("id") == "may")["run"]
    assert "autopilot.py conventions-round" in may and "autopilot.py conventions-comment" in may and "--add-label needs-human" in may
    assert prep["outputs"]["conventions"] == "${{ steps.may.outputs.conventions }}"
    task = next(s for s in steps if s.get("name") == "The agent's task")
    assert task["env"]["CONVENTIONS_ROUND"] == "${{ steps.may.outputs.conventions }}" and "conventions.md" in task["run"]
    prompt = ap.prompt_fix("o/r", 9, 1, 3, conventions=True)
    assert "autopilot.py title" in prompt and "reword" in prompt and ".dx-io/conventions.md" in prompt
    assert "Never change a file" in prompt


def test_a_second_identical_failure_stops_it():
    errors = "The pull request title is not a Conventional Commit header: \"x\"\n"
    go, sig, _ = ap.conventions_round(errors, [])
    assert go is True and len(sig) == 16
    mine = [{"user": {"login": ap.BOT_LOGINS[1]}, "body": ap.conventions_comment(sig, errors)}]
    assert ap.conventions_round(errors, mine)[0] is False
    # Someone else's comment counts for nothing; other errors are another round.
    assert ap.conventions_round(errors, [{"user": {"login": "mallory"}, "body": mine[0]["body"]}])[0] is True
    assert ap.conventions_round("Commit abc is 120 characters\n", mine)[0] is True
    # No error of the check's own (another of its jobs failed): no round.
    assert ap.conventions_round("", [])[0] is False
    stopped = ap.conventions_comment(sig, errors, stopped=True)
    assert "needs-human" in stopped and "a hint in words, brings it back" in stopped


def test_the_title_helper_checks_it_and_the_apply_sets_it():
    with tempfile.TemporaryDirectory() as io:
        env = dict(os.environ, DX_IO=io, PR="9", GITHUB_REPOSITORY="o/r")
        run = lambda t: subprocess.run([sys.executable, str(SCRIPTS / "autopilot.py"), "title", t], env=env, capture_output=True, text=True)
        assert run("Fixed things.").returncode == 1
        assert run("fix(autopilot): a title that passes").returncode == 0
        lines = [json.loads(l) for l in open(os.path.join(io, "outbox.jsonl"), encoding="utf-8")]
        assert lines == [{"kind": "title", "text": "fix(autopilot): a title that passes"}]
    assert ap.valid_intent({"kind": "title", "text": "x" * 201}) is None
    assert "title" in ap.AGENT_COMMANDS


def test_only_a_reword_goes_over_the_branch():
    with tempfile.TemporaryDirectory() as d:
        git = lambda *a: subprocess.run(["git", *a], cwd=d, capture_output=True, text=True, check=True).stdout.strip()
        git("init", "-q")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        git("config", "commit.gpgsign", "false")
        git("commit", "-q", "--allow-empty", "-m", "chore: base")
        base = git("rev-parse", "HEAD")
        Path(d, "a").write_text("a\n")
        git("add", "a")
        git("commit", "-q", "-m", "Fixed a")
        old = git("rev-parse", "HEAD")
        git("commit", "-q", "--amend", "-m", "fix: a")
        new = git("rev-parse", "HEAD")
        assert ap.reworded(base, old, new, cwd=d)[0] is True
        Path(d, "a").write_text("b\n")
        git("commit", "-q", "-am", "fix: a", "--amend")
        assert ap.reworded(base, old, git("rev-parse", "HEAD"), cwd=d)[0] is False
    text = (ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8")
    apply = text[text.index("A conventions fix round (#699 C3) may reword"):]
    apply = apply[:apply.index("autopilot.py apply .dx-out/outbox.jsonl")]
    assert '[ "$CONVENTIONS_ROUND" = true ]' in apply and "autopilot.py reworded" in apply
    assert "moved on GitHub" in apply and 'api-commit.py push "$BRANCH" --onto "$base" --force' in apply


def test_conventions_sh_checks_one_header():
    run = lambda h: subprocess.run(["bash", str(SCRIPTS / "conventions.sh"), "--header", h], capture_output=True, text=True).returncode
    assert (run("fix(autopilot): a thing"), run("fix: a thing."), run("Fixed")) == (0, 1, 1)
