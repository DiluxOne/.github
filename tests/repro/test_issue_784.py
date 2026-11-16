"""Issue #784: the release lane's scenarios leave the autopilot's pull requests open.

A scenario's issue is accepted and the autopilot opens its pull request
(`Closes #<issue>`, no `dx-scenario` mark in its body). `play` cleans up what it
made, but only its issues and the pull requests it opened itself, and `clear`
finds only bodies that carry the mark, so the autopilot's pull request, which
changes scenarios/core-one-at-a-time/ (the test repository's core), stays open.
The next run's `core-one-at-a-time` then waits on it (`autopilot:core-wait`,
"waits for #1233") and its pull request never says Closes. Nothing runs: `play`
gets a recording fake in place of `gh`.
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = "o/t"


def scenarios():
    spec = importlib.util.spec_from_file_location("release_scenarios", ROOT / "scripts" / "release-scenarios.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_autopilots_pull_request_of_a_scenarios_issue_is_closed_when_the_scenario_ends():
    mod = scenarios()
    calls, state = [], {"open": True}
    pull = {"number": 9, "state": "OPEN", "labels": [{"name": "autopilot"}], "comments": [], "title": "feat: x",
            "headRefName": "feat/5-x", "headRefOid": "", "author": {"login": "dilux-bot"},
            "files": [{"path": "scenarios/x/5.md"}], "closingIssuesReferences": [{"number": 5}],
            "body": "## 💡 Why\n\nCloses #5. The autopilot works it here in the open.\n"}

    def fake(*argv, input=None, **kw):
        argv = [str(a) for a in argv]
        calls.append(argv)
        head = argv[:2]
        if head == ["issue", "create"]:
            return f"https://github.com/{REPO}/issues/5\n"
        if head == ["issue", "view"]:
            return json.dumps({"labels": [], "comments": [], "state": "OPEN", "body": "",
                               "closedByPullRequestsReferences": [{"number": 9, "url": f"https://github.com/{REPO}/pull/9"}]})
        if head == ["pr", "view"]:
            return json.dumps(pull)
        if head == ["pr", "list"]:
            return json.dumps([dict(pull, state="OPEN")] if state["open"] else [])
        if head in (["pr", "close"], ["pr", "edit"]) and "9" in argv or (argv[:1] == ["api"] and "pulls/9" in " ".join(argv)):
            state["open"] = False
        if head == ["run", "list"] or head == ["issue", "list"]:
            return "[]"
        return ""

    s = {"id": "x", "minutes": 1, "opens": {"issue": {"title": "feat: x", "body": "b"}}, "expect": {}}
    row = mod.play(s, REPO, "v7-next", {"b": "### Problem\n\nx\n"}, run=fake, sleep=lambda _: None, run_id="1-1")

    assert row["ok"], row
    assert not state["open"], "the autopilot's pull request #9 of the scenario's issue #5 is still open after the scenario"
