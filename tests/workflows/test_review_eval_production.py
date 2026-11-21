"""The review's evaluation plays production's review (#930 C1): each case is
reviewed with claude-review.yml's own review prompt, args, tools and schema,
on a brief for the case's pull request in full mode, then verified with the
verify step's prompt and args, and the verified output is scored."""
import importlib.util
import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "claude-review.yml"

FAKE = r'''#!/usr/bin/env python3
import json, os, shutil, sys
log = os.environ["FAKE_LOG"]
n = len([f for f in os.listdir(log) if f.startswith("call-")])
args = sys.argv[1:]
with open(os.path.join(log, f"call-{n}.json"), "w") as fh:
    json.dump({"args": args, "cwd": os.getcwd(), "gh_token": "GH_TOKEN" in os.environ}, fh)
if os.path.exists(".dx-central/brief.md"):
    shutil.copy(".dx-central/brief.md", os.path.join(log, f"brief-{n}.md"))
diffs = []
for top, _, files in os.walk(".dx-central/diff"):
    diffs += [os.path.join(top, f) for f in files]
with open(os.path.join(log, f"diffs-{n}.json"), "w") as fh:
    json.dump(diffs, fh)
schema = args[args.index("--json-schema") + 1]
if '"verdicts"' in schema:
    out = {"verdicts": [{"i": 0, "real": os.environ.get("FAKE_REAL", "true") == "true", "why": "a.py:3"}]}
else:
    out = {"risk": "low", "complexity": "low", "blocking": True, "type": "fix", "description_matches": True, "summary": "s",
           "findings": [{"severity": "major", "file": "a.py", "line": 3, "title": "t", "detail": "d"}], "lessons": [], "resolved_threads": []}
print(json.dumps({"structured_output": out}))
'''


def mod():
    spec = importlib.util.spec_from_file_location("review_eval", ROOT / "scripts" / "review-eval.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def steps():
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    found = {}
    for job in wf["jobs"].values():
        for s in job.get("steps") or []:
            if s.get("id") in ("claude", "verify"):
                found[s["id"]] = s["with"]
    return found


def git(d, *a):
    return subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    remote = tmp_path / "git" / "o" / "r"
    remote.mkdir(parents=True)
    git(remote, "init", "-q", "-b", "main")
    git(remote, "config", "user.email", "t@t")
    git(remote, "config", "user.name", "t")
    (remote / "a.py").write_text("one\ntwo\nthree\nfour\n")
    git(remote, "add", "-A")
    git(remote, "commit", "-q", "-m", "chore: base")
    base = git(remote, "rev-parse", "HEAD")
    (remote / "a.py").write_text("one\ntwo\nTHREE\nfour\n")
    git(remote, "commit", "-q", "-am", "fix: three")
    head = git(remote, "rev-parse", "HEAD")
    fake = tmp_path / "claude"
    fake.write_text(FAKE)
    fake.chmod(0o755)
    log = tmp_path / "log"
    log.mkdir()
    monkeypatch.setenv("DX_EVAL_GIT", str(tmp_path / "git"))
    monkeypatch.setenv("DX_EVAL_CLAUDE", str(fake))
    monkeypatch.setenv("FAKE_LOG", str(log))
    # No GitHub here: the closing issue's criteria are none.
    monkeypatch.setenv("GH_TOKEN", "")
    case = {"id": "o/r#7:flag", "repo": "o/r", "pr": 7, "title": "fix: three", "base": base, "head": head,
            "expect": "flag", "path": "a.py", "line": 3, "hunk": [1, 4], "fix": head, "fixed": [[3, 3]]}
    return case, log, tmp_path


def calls(log):
    out = []
    n = 0
    while (log / f"call-{n}.json").exists():
        out.append(json.loads((log / f"call-{n}.json").read_text()))
        n += 1
    return out


def flag(args, name):
    return args[args.index(name) + 1]


def test_a_case_is_played_with_production_review_then_verified(scratch):
    case, log, tmp = scratch
    m = mod()
    ok = m.run_case(case, str(ROOT), str(tmp / "work"))
    got = calls(log)
    assert len(got) == 2, f"a review and a verification, got {len(got)} calls"
    review, verify = got[0]["args"], got[1]["args"]
    want = steps()
    # The review: claude-review.yml's own prompt, filled for the case.
    prompt = flag(review, "-p")
    assert prompt.startswith("You are the code reviewer for o/r, pull request #7."), prompt[:120]
    assert "${{" not in prompt
    assert prompt.strip() == want["claude"]["prompt"].replace("${{ github.repository }}", "o/r").replace("${{ github.event.pull_request.number }}", "7").strip()
    assert flag(review, "--allowedTools") == "Read,Glob,Grep"
    assert flag(review, "--json-schema") == shlex.split(want["claude"]["claude_args"])[shlex.split(want["claude"]["claude_args"]).index("--json-schema") + 1]
    assert flag(review, "--max-turns") == "60"
    assert float(flag(review, "--max-budget-usd")) > 0
    assert flag(review, "--permission-mode") == "dontAsk"
    assert "Bash(git diff:*)" not in " ".join(review)
    # The brief: for the case's pull request, in full mode, with the diffs.
    brief = (log / "brief-0.md").read_text()
    assert "pull request #7" in brief
    assert "a change before its pull request" not in brief
    assert "+THREE" in brief
    assert json.loads((log / "diffs-0.json").read_text()) == [".dx-central/diff/a.py.diff"], "the per-file diffs are in DIFF_DIR"
    # The verification: the verify step's args, review-verify.py's prompt.
    assert flag(verify, "-p").startswith("You verify a code review's findings.")
    assert flag(verify, "--max-budget-usd") == "2"
    assert flag(verify, "--allowedTools") == "Read,Glob,Grep"
    assert '"verdicts"' in flag(verify, "--json-schema")
    # The model never gets the GitHub token.
    assert not got[0]["gh_token"] and not got[1]["gh_token"]
    assert ok is True


def test_a_policy_that_fails_reviews_nothing(scratch, monkeypatch):
    case, log, tmp = scratch
    m = mod()
    assert hasattr(m, "policy_of"), "review-eval.py computes no policy for a case"
    monkeypatch.setattr(m, "policy_of", lambda *a: None)
    assert m.run_case(case, str(ROOT), str(tmp / "work")) is None
    assert calls(log) == []


def test_the_verified_output_is_scored(scratch, monkeypatch):
    case, log, tmp = scratch
    monkeypatch.setenv("FAKE_REAL", "false")
    m = mod()
    ok = m.run_case(case, str(ROOT), str(tmp / "work"))
    assert len(calls(log)) == 2
    # The verifier rejected the only major: the case is not found.
    assert ok is False


def test_an_unknown_expression_fails_by_name(tmp_path):
    m = mod()
    assert hasattr(m, "fill"), "review-eval.py has no fill()"
    with pytest.raises(ValueError, match=r"secrets\.SOMETHING"):
        m.fill("x ${{ secrets.SOMETHING }} y", {"github.repository": "o/r"})
    assert m.fill("for ${{ github.repository }}", {"github.repository": "o/r"}) == "for o/r"


def test_run_refuses_a_workflow_with_an_unknown_expression(tmp_path):
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for job in wf["jobs"].values():
        for s in job.get("steps") or []:
            if s.get("id") == "claude":
                s["with"]["prompt"] += "\n${{ secrets.SOMETHING }}\n"
    path = tmp_path / "claude-review.yml"
    path.write_text(yaml.safe_dump(wf))
    env = {**os.environ, "DX_EVAL_REVIEW_WORKFLOW": str(path)}
    out = subprocess.run(["python3", str(ROOT / "scripts" / "review-eval.py"), "run", "--play", "1"], capture_output=True, text=True, env=env)
    assert out.returncode == 1
    assert "secrets.SOMETHING" in out.stderr


def test_a_case_out_of_time_is_not_reviewed(scratch, monkeypatch):
    case, log, tmp = scratch
    m = mod()
    # A play of 20 cases fits the job's 350 minutes: a case has 15 between
    # its review and its verification, and none left reviews nothing.
    assert getattr(m, "CASE_SECONDS", None) == 900
    monkeypatch.setattr(m, "CASE_SECONDS", 0)
    assert m.run_case(case, str(ROOT), str(tmp / "work")) is None
    assert calls(log) == []
