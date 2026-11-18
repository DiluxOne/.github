"""One check of an issue's shape for G1 and the autopilot's start (#699 C1):
every mark the engine writes first in an issue's body is listed in one place
(scripts/issue-schema.py LEADING_MARKS, printed by `issue-schema.py markers`),
each writer's own constant passes it, and G1 (issue-accepted.yml) and the
autopilot's start (autopilot.py may_start) both call `issue-schema.py g1`, so
the two cannot give different answers again (#698)."""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


schema = load("issue_schema_c1", "issue-schema.py")

GOOD = ("### Problem\n\nIt breaks.\n\n### Scope\n\n- Fix it.\n\n### Out of scope\n\nNothing.\n\n"
        "### Acceptance criteria\n\nC1: Given a, when b, then c.\n\n### Criticality\n\nNormal\n")


def written_marks():
    """What each writer writes first in a body, from its own code."""
    release = load("release_lane_c1", "release-lane.py")
    nightly = load("nightly_review_c1", "nightly-review.py")
    scenarios = load("release_scenarios_c1", "release-scenarios.py")
    detect = load("detect_c1", "detect.py")
    autonomy = load("autonomy_c1", "autonomy.py")
    repro = load("repro_lane_c1", "repro-lane.py")
    lane_run = f"<!-- dx-lane: {repro.LANE} run: https://github.com/O/r/actions/runs/9 -->"
    return {
        "dx-release-lane": release.MARK,
        "dx-nightly-finding": nightly.BUG_MARK.format(repo="O/r"),
        "dx-scenario": scenarios.scenario_mark("edit-starts"),
        "dx-adopt": detect.adopt_body("diluxone-new", [], {}).split("\n", 1)[0],
        "dx-lane sync": autonomy.sync_marker("org-sync", "O/r", "callers", "a" * 40, {"f": "x"}),
        "dx-lane run": lane_run,
    }


def test_the_marks_are_listed_in_one_place():
    out = subprocess.run([sys.executable, str(SCRIPTS / "issue-schema.py"), "markers"], capture_output=True, text=True, check=True).stdout
    names = [m["name"] for m in json.loads(out)]
    assert sorted(names) == sorted(written_marks())
    # MARKER is built from that list, not written beside it.
    assert [m[0] for m in schema.LEADING_MARKS] == names


def test_every_writers_mark_passes_g1_and_the_start_alike():
    autopilot = load("autopilot_c1", "autopilot.py")
    policy = {"autopilot": True, "lanes": {autopilot.LANE: {"enabled": True}}}
    for name, mark in written_marks().items():
        body = mark + "\n" + GOOD
        assert schema.parse(body)[1] == [], name
        g1 = schema.g1(body)
        assert g1 == {"ok": True, "errors": []}, (name, g1)
        assert autopilot.may_start(policy, body, "on")[0] is True, name
    # A mark nobody writes fails both, with the same reason.
    fake = "<!-- dx-anything: run it -->\n" + GOOD
    g1 = schema.g1(fake)
    ok, why = autopilot.may_start(policy, fake, "on")
    assert g1["ok"] is False and ok is False and g1["errors"][0] in why


def test_a_new_body_leading_mark_fails_until_listed():
    """A `<!-- dx-… -->` mark written right before a section heading, in any
    script or workflow, is one the list knows."""
    names = {m[0].split()[0] for m in schema.LEADING_MARKS}
    lead = re.compile(r"<!-- (dx-[a-z-]+)[^\n>]*-->(?:\\n|\n)###")
    found = set()
    for path in list(SCRIPTS.glob("*.py")) + list((ROOT / ".github/workflows").glob("*.yml")):
        for m in lead.finditer(path.read_text(encoding="utf-8")):
            # The self-tests' fakes, and the review's comment on a pull
            # request, which is no issue's body.
            if m.group(1) not in ("dx-anything", "dx-x", "dx-review"):
                found.add((path.name, m.group(1)))
    assert found and all(name in names for _, name in found), sorted(f for f in found if f[1] not in names)


def test_g1_and_the_start_call_the_same_function():
    accepted = (ROOT / ".github/workflows/issue-accepted.yml").read_text(encoding="utf-8")
    assert "issue-schema.py check)" not in accepted and "issue-schema.py check <" not in accepted
    assert accepted.count("issue-schema.py g1)") + accepted.count("issue-schema.py g1 <") >= 2
    autopilot = (SCRIPTS / "autopilot.py").read_text(encoding="utf-8")
    start = autopilot[autopilot.index("def may_start("):]
    start = start[:start.index("\ndef ")]
    assert "schema.g1(body)" in start and "schema.check(" not in start
