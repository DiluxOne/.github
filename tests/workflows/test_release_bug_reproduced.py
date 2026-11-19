"""A bug the release lane opens is accepted by policy as reproduced, its run
being the reproduction (#699 C6). Its body names the lane's run first (the
`dx-lane: bugfix-reproduced run:` mark, after `dx-release-lane`) and its
Problem says `Reproduced by: <run> scenario <id>`, the second evidence form
scripts/repro-lane.py reads; policy/autonomy.yml's `bugfix-reproduced`
origin lists the release lane, so the lane accepts it; issue-repro.yml
tries no reproduction of it (no `could-not-reproduce`), labels it, records
the lane's decision, seals it and starts the autopilot, as for a confirmed
bug. With no test to check, a person merges its fix."""
import importlib.util
from pathlib import Path

import yaml

from steps import sections

ROOT = Path(__file__).resolve().parents[2]
RUN = "https://github.com/DiluxOne/.github/actions/runs/77"


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


release = load("release_lane_c6", "release-lane.py")
repro = load("repro_lane_c6", "repro-lane.py")
schema = load("issue_schema_c6", "issue-schema.py")
autopilot = load("autopilot_c6", "autopilot.py")
autonomy = load("autonomy_c6", "autonomy.py")


def bug():
    plan = {"release": True, "version": "v7.20.0", "major": "v7"}
    return release.decide(plan, [{"id": "edit-starts", "ok": False, "why": ["no start"], "run": "https://x/1"}], RUN)


def test_the_lanes_bug_names_its_run_as_the_reproduction():
    d = bug()
    body = d["body"]
    assert body.startswith(release.MARK + "\n")
    # The mark comes before the first heading: it heads the body.
    assert f"<!-- dx-lane: {repro.LANE} run: {RUN} -->" in sections(body)[""].splitlines()
    assert schema.g1(body)["ok"], schema.g1(body)
    ev = repro.scenario_evidence(body)
    assert ev == {"run": RUN, "scenario": "edit-starts"}
    # The test-based form is unchanged; the scenario form is no test.
    assert repro.evidence(body) is None
    m = autonomy.MARKER.search(body)
    assert m and m.group(1) == repro.LANE and m.group(2) == RUN


def test_the_lane_accepts_it_from_the_release_lane():
    pol = yaml.safe_load((ROOT / "policy/autonomy.yml").read_text(encoding="utf-8"))
    origin = pol["lanes"]["bugfix-reproduced"]["origin"]["workflows"]
    assert "issue-repro.yml" in origin and "release-lane.yml" in origin


def test_the_autopilot_starts_it_and_a_person_merges_it():
    body = bug()["body"]
    policy = {"autopilot": True, "lanes": {repro.LANE: {"enabled": True}}}
    assert autopilot.may_start(policy, body, "on", repro.LANE)[0] is True
    # finish ready needs no reproduction test for it.
    assert autopilot.repro_needed(body, [f"lane:{repro.LANE}"], "match") == ("", "")
    ok, why = autopilot.decide({"autopilot": True, "lanes": {repro.LANE: {"enabled": True, "merge": {"max-risk": "medium", "max-complexity": "medium"}}}},
                               body, "low", "low", "false", "true", ["policy/autonomy.yml"], ["policy/autonomy.yml"], "on", lane_name=repro.LANE)
    assert ok is False and "person merges" in why


def test_issue_repro_accepts_it_with_no_attempt():
    wf = yaml.safe_load((ROOT / ".github/workflows/issue-repro.yml").read_text(encoding="utf-8"))["jobs"]
    write_if = " ".join(str(wf["write"]["if"]).split())
    assert "Reproduced by: https://github.com/" in write_if and "!(" in write_if
    job = wf["release-bug"]
    cond = " ".join(str(job["if"]).split())
    assert "startsWith(github.event.issue.body, '<!-- dx-release-lane')" in cond and "vars.DX_BOT_LOGIN" in cond
    run = "\n".join(s.get("run", "") for s in job["steps"])
    for piece in ("repro-lane.py scenario", "--add-label lane:bugfix-reproduced", "autonomy.py lane-accept", "receipts.py lane-decision", "receipts.py seal-prd"):
        assert piece in run, piece
    start = wf["release-autopilot"]
    assert start["needs"] == "release-bug" and start["with"]["mode"] == "start"
    triage = yaml.safe_load((ROOT / ".github/workflows/issue-triage.yml").read_text(encoding="utf-8"))["jobs"]["nightly"]
    assert "Reproduced by: https://github.com/" in " ".join(str(triage["if"]).split())


def test_the_draft_of_a_scenario_bug_has_no_reproduction_branch():
    text = (ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8")
    assert 'if [ "$LANE" = bugfix-reproduced ] && [ -n "$REPRO_BRANCH" ]; then' in text
