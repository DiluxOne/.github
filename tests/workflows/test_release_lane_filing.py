"""#843 C2: a scenario that failed twice is filed with its class (engine,
harness or infrastructure): only an engine failure is a bug (Type Bug, the
`bugfix-reproduced` lane's mark, its body first the lane's mark, which the
triage takes as a bug), a harness or an infrastructure failure a Task, each
in the issue schema's sections; and a scenario that already has an open
report gets a comment on it instead of a new issue. scripts/release-lane.py's
decide and act, with a fake gh; the rows' classes from
scripts/release-scenarios.py's play_group and merge."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lane = load("release_lane_c2", "scripts/release-lane.py")
scen = load("release_scenarios_c2", "scripts/release-scenarios.py")
schema = load("issue_schema_c2", "scripts/issue-schema.py")

RUN = "https://github.com/O/.github/actions/runs/7"
NXT = {"last": "7.10.0", "next": "7.10.1", "bump": "patch", "pending": True}
PLAN = dict(lane.plan(NXT, ["fix(autopilot): a stuck draft goes on (#600)"]), sha="p1")
FAILED = [
    {"id": "spec-to-draft", "ok": False, "why": ["no label autopilot"], "run": "https://github.com/o/t/actions/runs/1", "class": "engine", "attempts": 2},
    {"id": "bug-reproduced", "ok": False, "why": ["fixture greeting is missing"], "run": "", "class": "harness", "attempts": 2},
    {"id": "fork-pull", "ok": False, "why": ["gh pr view rate limited or failing at GitHub until the scenario's time ran out"], "run": "", "class": "infrastructure", "attempts": 2},
    {"id": "old-row", "ok": False, "why": ["no comment"], "run": ""},
]
SCENARIO = "<!-- dx-lane-scenario: {} -->"


def filings():
    d = lane.decide(PLAN, FAILED, RUN)
    assert d["do"] == "bug"
    got = d.get("filings") or []
    assert [f.get("scenario") for f in got] == ["spec-to-draft", "bug-reproduced", "fork-pull", "old-row"]
    return {f["scenario"]: f for f in got}


def test_each_failure_is_filed_with_its_class_and_only_the_engine_is_a_bug():
    f = filings()
    assert [f[s].get("class") for s in f] == ["engine", "harness", "infrastructure", "engine"]
    assert [f[s].get("type") for s in f] == ["Bug", "Task", "Task", "Bug"]
    assert f["spec-to-draft"]["title"] == "fix: release scenario spec-to-draft fails"
    assert f["bug-reproduced"]["title"] == "test: release scenario bug-reproduced fails in the harness"
    assert f["fork-pull"]["title"] == "ci: release scenario fork-pull fails on infrastructure"
    for sid, one in f.items():
        body = one["body"]
        assert f"Class: {one['class']}" in body
        assert lane.MARK in body and SCENARIO.format(sid) in body
        assert body.index(lane.MARK) < body.index(SCENARIO.format(sid))
        assert schema.g1(body)["ok"], (sid, schema.g1(body))
        bug = one["class"] == "engine"
        # The bugfix-reproduced lane's mark, and the lane's own first (the
        # triage's bug), on an engine failure alone.
        assert ("<!-- dx-lane: bugfix-reproduced run:" in body) is bug
        assert body.startswith(lane.MARK) is bug
        assert ("Reproduced by:" in body) is bug


class Fake:
    def __init__(self, open_issues):
        self.calls, self.open = [], open_issues

    def __call__(self, *argv, input=None):
        self.calls.append(argv)
        if "issues?state=open" in " ".join(argv):
            return json.dumps([self.open])
        if argv[:3] == ("gh", "api", "repos/O/.github/issues"):
            return "https://github.com/O/.github/issues/99\n"
        return ""


def test_an_open_report_of_the_same_scenario_gets_a_comment_instead_of_a_new_issue():
    report = {"number": 41, "title": "fix: release scenario spec-to-draft fails",
              "body": lane.MARK + "\n" + SCENARIO.format("spec-to-draft") + "\n### What happened?\n"}
    other = {"number": 42, "title": "fix: something else", "body": "no mark\n" + SCENARIO.format("bug-reproduced")}
    fake = Fake([report, other])
    d = lane.act(PLAN, FAILED, "O/.github", run=fake, lane_run=RUN)
    assert d["do"] == "bug"
    comments = [c for c in fake.calls if c[:3] == ("gh", "issue", "comment")]
    assert [c[3] for c in comments] == ["41"]
    said = " ".join(comments[0])
    assert "v7.10.1" in said and "Class: engine" in said and "no label autopilot" in said and RUN in said
    opened = [c for c in fake.calls if c[:3] == ("gh", "api", "repos/O/.github/issues")]
    titles = [next(a for a in c if a.startswith("title=")) for c in opened]
    assert titles == ["title=test: release scenario bug-reproduced fails in the harness",
                      "title=ci: release scenario fork-pull fails on infrastructure",
                      "title=fix: release scenario old-row fails"]
    assert ["type=Task" in c for c in opened] == [True, True, False]
    assert ["type=Bug" in c for c in opened] == [False, False, True]
    # Nothing tagged, nothing moved.
    assert [c for c in fake.calls if c[:1] == ("git",) or c[:2] in (("gh", "release"), ("gh", "pr"))] == []


def test_a_release_closes_the_open_reports_of_the_new_form():
    reports = [{"number": 41, "title": "fix: release scenario spec-to-draft fails", "body": lane.MARK + "\n" + SCENARIO.format("spec-to-draft") + "\n"},
               {"number": 43, "title": "test: release scenario b fails in the harness", "body": "### What happened?\n\n" + lane.MARK + "\n" + SCENARIO.format("b") + "\n"},
               {"number": 44, "title": "ci: release scenario c fails on infrastructure", "body": "### What happened?\n\n" + lane.MARK + "\n" + SCENARIO.format("c") + "\n"},
               {"number": 45, "title": "ci: release scenario d fails on infrastructure", "body": "no mark\n"},
               {"number": 46, "title": "fix: release candidate v7.9.0 fails scenario a", "body": lane.MARK + "\n"}]
    assert lane.stale_reports(reports, "v7.10.1") == [41, 43, 44, 46]


def test_the_rows_say_their_class_where_they_are_made():
    gs = [{"id": "s1", "scenarios": ["s1"]}, {"id": "s2", "scenarios": ["s2"]}]
    rows = scen.merge(gs, {"move": [], "back": [], "s1": None, "s2": []}, {"move": "success", "play": "cancelled", "back": "success"}, RUN, 30, 20)
    by = {r["id"]: r.get("class") for r in rows}
    assert by == {"s1": "infrastructure", "s2": "harness", "play": "infrastructure"}
    rows = scen.merge(gs, {"move": None, "back": [{"id": "callers", "ok": False, "why": ["not back"], "run": ""}], "s1": [], "s2": []},
                      {"move": "failure", "play": "success", "back": "success"}, RUN)
    by = {r["id"]: r.get("class") for r in rows if r["id"] in ("move", "callers")}
    assert by == {"move": "harness", "callers": "harness"}
    rows = scen.play_group({"scenarios": []}, "nope", "o/t", "v7-next")
    assert rows[0].get("class") == "harness"
