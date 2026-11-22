"""#928 C1: an autopilot round whose criteria are all ticked and whose
`make pre-pr` passed at the pull request's head ends with the pull request
ready for review, with no person marking it: `autopilot.py end` takes the
`ready` verdict (`end_ready`) and marks it ready through the same path as
`finish ready`. When that path refuses, the end says why on the pull request
and keeps today's verdict, so no round ends green and silent. Runs `end`
with gh stood in and the fixture boards (RECEIPTS_FIXTURE)."""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from steps import outputs  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HEAD = "a" * 40
TICKED = """## 🎯 Acceptance criteria

<!-- dx-checklist -->
- [x] **C1** Given a thing, when it runs, then it works.
  Test: tests/test_x.py
<!-- /dx-checklist -->

## 🙌 Credits

<!-- dx-credits -->
<!-- /dx-credits -->

## 🧪 How I tested it

<!-- dx-tested -->
_The autopilot fills this in when it marks the pull request ready._
"""


def autopilot():
    spec = importlib.util.spec_from_file_location("autopilot_end_ready", ROOT / "scripts/autopilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class World:
    """Issue #7 of o/r and its autopilot draft #8, every box ticked, in a
    continue run (2 of 5): gh stood in, logging what is written."""

    def __init__(self, tmp_path, monkeypatch, body=TICKED, passed_at=HEAD, head=HEAD):
        self.fx = tmp_path / "fx"
        self.fx.mkdir()
        self.calls, self.state = [], {"body": body, "draft": True}
        for k, v in (("RECEIPTS_FIXTURE", str(self.fx)), ("GITHUB_REPOSITORY", "o/r"), ("DX_BOT_APP", "dilux-bot"),
                     ("DX_BOT_LOGIN", "dilux-bot[bot]"), ("NUMBER", "7"), ("PR", "8"), ("MODE", "continue"),
                     ("RUNS", "1"), ("RUN_URL", "https://github.com/o/r/actions/runs/1"), ("RUNNER_TEMP", str(tmp_path)),
                     ("PREPR_PASSED", passed_at), ("GITHUB_OUTPUT", str(tmp_path / "out.txt"))):
            monkeypatch.setenv(k, v)
        for k in ("DX_IO", "REPO_AUTONOMY", "PREPR", "WHY", "HELD", "CORE", "FAILED", "REFUSED", "WORK_LOG", "BRANCH",
                  "HEAD_BEFORE", "STARTED", "WORK_RESULT", "AGENT_OUTCOME", "WORK_OUTCOME"):
            monkeypatch.delenv(k, raising=False)
        self.ap = ap = autopilot()
        ap.set_board("o/r", 8, "pr", runs=[{"n": 1, "free": False}, {"n": 2, "free": False}])

        def fake_gh(*args, input_text=None):
            a = [str(x) for x in args]
            self.calls.append(" ".join(a))
            if a[:2] == ["pr", "view"] and "comments" in a:
                return json.dumps({"comments": []})
            if a[:2] == ["issue", "view"]:
                return json.dumps({"body": "", "labels": [{"name": "accepted"}], "comments": []})
            if a[:2] == ["pr", "view"]:
                return json.dumps({"body": self.state["body"], "isDraft": self.state["draft"], "headRefOid": head})
            if a[:2] == ["pr", "edit"] and "--body-file" in a:
                self.state["body"] = input_text
            if a[:2] == ["pr", "ready"]:
                self.state["draft"] = "--undo" in a
            return ""

        monkeypatch.setattr(ap, "gh", fake_gh)
        monkeypatch.setattr(ap, "refresh_board", lambda repo, number: None)
        monkeypatch.setattr(ap, "review_push", lambda repo, pr, call=None: self.calls.append("review-push") or "b" * 40)
        self.tmp = tmp_path

    def end(self):
        return self.ap.main(["end"])

    def verdict(self):
        out = self.tmp / "out.txt"
        found = outputs(out.read_text(encoding="utf-8")) if out.exists() else {}
        return [found["verdict"]] if "verdict" in found else []


def test_c1_a_green_round_with_every_box_ticked_ends_ready(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.end()
    assert any(c.startswith("pr ready 8") and "--undo" not in c for c in w.calls), w.calls
    assert w.state["draft"] is False
    # The ready push starts the review, as `finish ready`'s does.
    assert "review-push" in w.calls
    assert w.verdict() == ["ready"]
    # No continue, no needs-human: nobody has to move it.
    assert not any("autopilot:continue" in c or "needs-human" in c for c in w.calls), w.calls
    # The end wrote "How I tested it" from the run, as the agent left none.
    tested = re.search(r"<!-- dx-tested -->\n(.*)", w.state["body"], re.S).group(1)
    assert "https://github.com/o/r/actions/runs/1" in tested and "fills this in" not in tested, tested


def test_c1_the_rule_is_pure_and_bounded():
    ap = autopilot()
    end_ready = getattr(ap, "end_ready", None)
    assert callable(end_ready), "autopilot.py has no end_ready"
    assert end_ready("continue", "8", True, False, False, 3, 3, True) is True
    assert end_ready("start", "8", True, False, False, 3, 3, True) is True
    # Not every box, `make pre-pr` not passed at the head, stopped, asked,
    # already ready, no pull request, or a fix round: not this rule's.
    assert end_ready("continue", "8", True, False, False, 2, 3, True) is False
    assert end_ready("continue", "8", True, False, False, 3, 3, False) is False
    assert end_ready("continue", "8", True, True, False, 3, 3, True) is False
    assert end_ready("continue", "8", True, False, True, 3, 3, True) is False
    assert end_ready("continue", "8", False, False, False, 3, 3, True) is False
    assert end_ready("continue", "", True, False, False, 3, 3, True) is False
    assert end_ready("continue", "8", True, False, False, 0, 0, True) is False
    assert end_ready("fix", "8", True, False, False, 3, 3, True) is False
    # end_verdict takes it before the continue and the silent rules.
    assert ap.end_verdict("continue", "8", True, False, 3, 3, False, 2, 5, prepr_passed=True) == "ready"
    assert ap.end_verdict("continue", "8", True, False, 3, 3, False, 2, 5, nudged=True, prepr_passed=True) == "ready"
    assert ap.end_verdict("continue", "8", True, False, 3, 3, False, 2, 5) == "continue"


def test_c1_a_pass_at_another_head_does_not_mark_it_ready(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, passed_at="c" * 40)
    w.end()
    assert not any(c.startswith("pr ready 8") for c in w.calls)
    assert w.verdict() == ["continue"]


def signed_again(tmp_path):
    """A repository where the work job's head (`local`) and the head the
    push left on GitHub (`pushed`, the same commit made again through the
    API so GitHub signs it) differ in SHA and share a tree, and a third
    commit (`other`) whose tree differs."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}

    def g(*a, **extra):
        return subprocess.run(["git", "-C", str(repo), "-c", "user.name=a", "-c", "user.email=a@x", *a], check=True,
                              capture_output=True, text=True, env=dict(env, **extra)).stdout.strip()
    g("init", "-q")
    (repo / "f").write_text("one\n")
    g("add", "f")
    g("commit", "-qm", "work", GIT_AUTHOR_DATE="2026-01-01T00:00:00Z", GIT_COMMITTER_DATE="2026-01-01T00:00:00Z")
    local = g("rev-parse", "HEAD")
    pushed = g("commit-tree", "-m", "work", "HEAD^{tree}", GIT_COMMITTER_DATE="2026-01-02T00:00:00Z")
    (repo / "f").write_text("two\n")
    g("commit", "-qam", "other")
    return repo, local, pushed, g("rev-parse", "HEAD")


def test_c1_a_round_that_pushed_still_ends_ready(tmp_path, monkeypatch):
    # The push makes the commits again through the API (api-commit.py), so
    # the pull request's head is a new SHA with the tree `make pre-pr`
    # passed at: the end compares trees, not SHAs.
    repo, local, pushed, _ = signed_again(tmp_path)
    assert local != pushed
    monkeypatch.chdir(repo)
    w = World(tmp_path, monkeypatch, passed_at=local, head=pushed)
    w.end()
    assert w.state["draft"] is False, w.calls
    assert w.verdict() == ["ready"]


def test_c1_the_same_tree_rule(tmp_path):
    ap = autopilot()
    repo, local, pushed, other = signed_again(tmp_path)
    assert ap.same_tree(local, pushed, cwd=repo) is True
    assert ap.same_tree(local, local, cwd=repo) is True
    assert ap.same_tree(local, other, cwd=repo) is False
    # A head this clone does not have, or none: not passed there.
    assert ap.same_tree(local, "c" * 40, cwd=repo) is False
    assert ap.same_tree("", pushed, cwd=repo) is False


def test_c1_a_refused_ready_says_why_and_keeps_todays_verdict(tmp_path, monkeypatch):
    no_credits = TICKED.replace("<!-- dx-credits -->\n<!-- /dx-credits -->\n", "")
    w = World(tmp_path, monkeypatch, body=no_credits)
    w.end()
    assert w.state["draft"] is True
    said = [c for c in w.calls if c.startswith("pr comment 8")]
    assert said and "not ready" in " ".join(said).lower(), w.calls
    assert w.verdict() == ["continue"]
    assert any("autopilot:continue" in c for c in w.calls)


def test_c1_the_end_step_reads_where_make_pre_pr_passed():
    jobs = yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))["jobs"]
    end = next(s for s in jobs["apply"]["steps"] if s.get("id") == "end")
    passed = end["env"].get("PREPR_PASSED", "")
    assert "needs.work.outputs.head" in passed and "needs.verify.outputs.verdict" in passed, passed
    assert "needs.work.outputs.checked" in passed, passed
    assert "checked" in jobs["work"]["outputs"]
