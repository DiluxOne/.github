"""A round that ends ready reaches the branch in one push (#820): the
outbox's ticks are applied against the agent's commits not yet pushed, the
pull request is marked ready, and then the agent's commits and the empty
`chore: ready for review` commit go in a single push, which starts the one
review run; the pipeline's review skips the `ready_for_review` event of an
autopilot pull request. Runs apply_outbox with gh and api-commit.py stood
in, on a real git repository."""
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
BRANCH = "fix/7-thing"
REPO = "o/r"
BODY = """## 🎯 Acceptance criteria

<!-- dx-checklist -->
- [ ] **C1** Given a thing, when it runs, then it works.
  Test: tests/test_x.py
<!-- /dx-checklist -->

## 🙌 Credits

<!-- dx-credits -->
<!-- /dx-credits -->

## 🧪 How I tested it

<!-- dx-tested -->
_The autopilot fills this in when it marks the pull request ready._
"""


def load_autopilot():
    spec = importlib.util.spec_from_file_location("autopilot_under_test", ROOT / "scripts" / "autopilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def world(tmp_path, monkeypatch):
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", BRANCH, str(work)], check=True)
    for k, v in (("user.name", "bot"), ("user.email", "bot@example.com"), ("commit.gpgsign", "false")):
        git(work, "config", k, v)
    git(work, "remote", "add", "origin", str(origin))
    git(work, "commit", "-q", "--allow-empty", "-m", "chore(autopilot): start on #7")
    git(work, "push", "-q", "origin", BRANCH)
    git(work, "fetch", "-q", "origin")
    (work / "x.txt").write_text("x\n")
    git(work, "add", "x.txt")
    git(work, "commit", "-q", "-m", "fix: the thing (C1)")
    agent_head = git(work, "rev-parse", "HEAD")

    ap = load_autopilot()
    events, state = [], {"body": BODY}

    def remote_subjects():
        return git(work, "log", "--format=%s", f"origin/{BRANCH}")

    def fake_gh(*args, input_text=None):
        a = list(args)
        if a[:2] == ["pr", "view"] and "body" in a:
            return json.dumps({"body": state["body"]})
        if a[:2] == ["pr", "view"]:
            return json.dumps({"headRefOid": git(work, "rev-parse", f"origin/{BRANCH}"), "headRefName": BRANCH})
        if a[:2] == ["pr", "edit"] and "--body-file" in a:
            state["body"] = input_text
            events.append("edit")
            return ""
        if a[:2] == ["pr", "ready"]:
            events.append("ready-undo" if "--undo" in a else "ready")
            return ""
        if a[:2] == ["issue", "view"]:
            return json.dumps({"body": "", "labels": []})
        if a[:1] == ["api"] and a[1].endswith(f"/pulls/9/commits"):
            if "--jq" in a and "message" in a[a.index("--jq") + 1]:
                return remote_subjects() + "\n"
            return git(work, "log", "--format=%H", f"origin/{BRANCH}") + "\n"
        if a[:2] == ["api", f"repos/{REPO}/issues/7/comments"]:
            return "[]"
        if a[:1] == ["api"] and "-X" in a:
            events.append("api-write " + " ".join(a[1:4]))
            return "{}"
        raise RuntimeError("not stood in: gh " + " ".join(a))

    def fake_push(branch):
        # api-commit.py, stood in: the branch on GitHub moves to HEAD.
        events.append("push")
        state.setdefault("pushes", []).append(git(work, "log", "--format=%s", f"origin/{branch}..HEAD").splitlines())
        git(work, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
        git(work, "fetch", "-q", "origin")
        return 0

    monkeypatch.setattr(ap, "gh", fake_gh)
    monkeypatch.setattr(ap, "api_push", fake_push, raising=False)
    monkeypatch.setattr(ap, "refresh_board", lambda *a, **k: None)
    monkeypatch.setattr(ap.time, "sleep", lambda *_: None)
    # receipts.py, run by `finish ready`, finds no gh to call.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text("#!/bin/sh\nexit 1\n")
    (bin_dir / "gh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    for k in ("PREPR", "REPRO_TEST", "REPRO_SHA", "DX_IO"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("BRANCH", BRANCH)
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("PR", "9")
    monkeypatch.setenv("NUMBER", "7")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.chdir(work)
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text("".join(json.dumps(i) + "\n" for i in (
        {"kind": "tick", "id": "C1"}, {"kind": "credits", "text": "none"}, {"kind": "ready", "text": "Ran the tests."})))
    return {"ap": ap, "events": events, "state": state, "work": work, "outbox": outbox, "agent_head": agent_head}


def test_c2_ready_comes_first_then_one_push_with_the_ready_commit(world):
    ap, events, state, work = world["ap"], world["events"], world["state"], world["work"]
    failed = ap.apply_outbox(str(world["outbox"]), REPO, "7", "9")
    assert failed == 0
    assert "- [x] **C1**" in state["body"]
    assert "Ran the tests." in state["body"]
    assert events.count("push") == 1
    assert "ready" in events and events.index("ready") < events.index("push")
    assert "ready-undo" not in events
    # No commit made through the API besides the one push.
    assert not [e for e in events if e.startswith("api-write")]
    # The push's head is the ready commit, on top of the agent's commits.
    assert state["pushes"] == [["chore: ready for review", "fix: the thing (C1)"]]
    assert git(work, "log", "-1", "--format=%s", f"origin/{BRANCH}") == "chore: ready for review"
    assert git(work, "rev-parse", f"origin/{BRANCH}~1") == world["agent_head"]
    assert git(work, "diff", "--stat", f"origin/{BRANCH}~1", f"origin/{BRANCH}") == ""


def test_c2_the_workflow_leaves_that_push_to_the_ready(world):
    ap = world["ap"]
    assert ap.main(["ready-goes", str(world["outbox"])]) == 0
    os.environ["PREPR"] = "fail"
    try:
        assert ap.main(["ready-goes", str(world["outbox"])]) == 1
    finally:
        del os.environ["PREPR"]
    step = next(s for s in yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))["jobs"]["apply"]["steps"]
                if s.get("id") == "applied")
    run = step["run"]
    assert "autopilot.py ready-goes .dx-out/outbox.jsonl" in run
    assert run.index("autopilot.py ready-goes") < run.index("autopilot.py push")


REVIEW_SKIP = ("!(github.event.action == 'ready_for_review' && contains(github.event.pull_request.labels.*.name, 'autopilot') "
               "&& github.event.pull_request.user.login == vars.DX_BOT_LOGIN)")


@pytest.mark.parametrize("path", [".github/workflows/pull-request.yml", ".github/workflows/org-pull-request.yml",
                                  "workflow-templates/test-pull-request.yml"])
def test_c2_the_review_skips_an_autopilot_pull_request_marked_ready(path):
    review = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))["jobs"]["review"]
    assert REVIEW_SKIP in str(review.get("if", ""))


def test_c2_a_ready_refused_still_pushes_the_agents_commits_once(world):
    # No Credits block: `finish ready` refuses, and the commits go anyway.
    ap, events, state, work = world["ap"], world["events"], world["state"], world["work"]
    world["outbox"].write_text("".join(json.dumps(i) + "\n" for i in (
        {"kind": "tick", "id": "C1"}, {"kind": "ready", "text": "Ran the tests."})))
    state["body"] = BODY.replace("<!-- dx-credits -->\n<!-- /dx-credits -->\n", "")
    assert ap.apply_outbox(str(world["outbox"]), REPO, "7", "9") == 1
    assert "ready" not in events
    assert state["pushes"] == [["fix: the thing (C1)"]]
    assert git(work, "rev-parse", f"origin/{BRANCH}") == git(work, "rev-parse", "HEAD")


def test_c2_a_failed_push_undoes_the_ready_and_leaves_no_ready_commit(world, monkeypatch):
    ap, events, state, work = world["ap"], world["events"], world["state"], world["work"]
    tries = []

    def failing_push(branch):
        tries.append(git(work, "log", "-1", "--format=%s"))
        return 1

    monkeypatch.setattr(ap, "api_push", failing_push)
    assert ap.apply_outbox(str(world["outbox"]), REPO, "7", "9") == 1
    assert events.index("ready") < events.index("ready-undo")
    # The ready's push carried the ready commit; the retry after it, not.
    assert tries == ["chore: ready for review", "fix: the thing (C1)"]
    assert git(work, "log", "-1", "--format=%s") == "fix: the thing (C1)"
