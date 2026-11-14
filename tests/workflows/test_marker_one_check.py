"""One check of an issue's shape (#699 C1): G1 (issue-accepted.yml, through
`issue-schema.py g1`) and the autopilot's start (autopilot.py may_start) ask
the same function, and it knows every marker the engine writes first in the
body of an issue it opens, from the writers' own output."""
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


schema = load("issue_schema", "issue-schema.py")
autopilot = load("autopilot", "autopilot.py")

GOOD = """### Problem

The site has no dark mode.

### Scope

- A toggle in the header.

### Out of scope

- Per-page themes.

### Acceptance criteria

- C1: Given a visitor, when they press the toggle, then the page turns dark.

### Criticality

Normal
"""
RUN = "https://github.com/DiluxOne/x/actions/runs/42"
GHSA = "GHSA-2c2f-4m5q-jw7x"


def printf_mark(workflow, name, *args):
    """The first line a workflow's printf writes in the body it opens, filled."""
    text = (ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8")
    m = re.search(r"printf '(<!-- " + re.escape(name) + r"[^\\']*-->)\\n", text)
    assert m, f"{workflow} no longer writes {name} first"
    return m.group(1) % args


def written():
    """Every marker the engine writes first in an issue's body, as its writer
    writes it: (name, mark)."""
    release_lane = load("release_lane", "release-lane.py")
    nightly = load("nightly_review", "nightly-review.py")
    scenarios = load("release_scenarios", "release-scenarios.py")
    detect = load("detect", "detect.py")
    autonomy = load("autonomy", "autonomy.py")
    repro = load("repro_lane", "repro-lane.py")
    advisory = load("advisory", "advisory.py")
    return [
        ("dx-lane run", repro.prd(12, RUN, "a" * 64, "b" * 40)["body"].splitlines()[0]),
        ("dx-lane sync", autonomy.sync_marker("org-sync", "DiluxOne/x", "files", "a" * 40, {"a": "b"})),
        ("dx-lane carry", printf_mark("security-patch.yml", "dx-lane: security-carry", "2.1.1", GHSA)),
        ("dx-adopt", detect.adopt_body("diluxone-new", [], []).splitlines()[0]),
        ("dx-scenario", scenarios.scenario_mark("issue-complete")),
        ("dx-release-lane", release_lane.MARK),
        ("dx-nightly-finding", nightly.BUG_MARK.format(repo="DiluxOne/x")),
        ("dx-repro-blocker", printf_mark("issue-repro.yml", "dx-repro-blocker", "12")),
        ("dx-security-forward", printf_mark("security-patch.yml", "dx-security-forward", GHSA)),
        ("dx-advisory-fix", advisory.MARK.format(repo="DiluxOne/x", ghsa=GHSA)),
        ("dx-unvetted", advisory.UNVETTED_MARK.format(repo="DiluxOne/x", ghsa=GHSA)),
    ]


def policy():
    return {"autopilot": True, "lanes": {autopilot.LANE: {"enabled": True}}}


def g1_cli(body):
    return subprocess.run([sys.executable, str(SCRIPTS / "issue-schema.py"), "g1"], input=body, capture_output=True, text=True).returncode


def test_every_writer_is_listed_once_and_its_mark_passes_both():
    marks = written()
    assert sorted(n for n, _ in marks) == sorted(n for n, _, _ in schema.MARKERS)
    for name, mark in marks:
        body = mark + "\n" + GOOD
        assert schema.MARKER.match(mark), (name, mark)
        assert schema.parse(body)[1] == [], (name, mark)
        assert schema.g1(body)["ok"] is True, (name, mark)
        assert autopilot.may_start(policy(), body, "")[0] is True, (name, mark)
        assert g1_cli(body) == 0, (name, mark)


def test_both_give_the_same_answer_for_any_body():
    bodies = [mark + "\n" + GOOD for _, mark in written()] + [
        "<!-- dx-anything: delete the repository -->\n" + GOOD,
        "Text before the first section.\n" + GOOD,
        "<!-- dx-release-lane --> and more\n" + GOOD,
        GOOD.replace("Normal", "Urgent"),
    ]
    for body in bodies:
        ok = schema.g1(body)["ok"]
        assert autopilot.may_start(policy(), body, "")[0] is ok, body[:60]
        assert (g1_cli(body) == 0) is ok, body[:60]


def test_may_start_and_issue_accepted_call_g1():
    src = (SCRIPTS / "autopilot.py").read_text(encoding="utf-8")
    start = src[src.index("def may_start("):]
    start = start[:start.index("\ndef ")]
    assert "schema.g1(body)" in start and "schema.check(" not in start
    steps = yaml.safe_load((ROOT / ".github/workflows/issue-accepted.yml").read_text(encoding="utf-8"))["jobs"]
    runs = "\n".join(s.get("run", "") for j in steps.values() for s in j.get("steps", []))
    assert "issue-schema.py g1)" in runs and "issue-schema.py g1 <" in runs
    assert "issue-schema.py check" not in runs


# The engine's `dx-` marks that never lead the body of an issue it opens:
# its comments, its pull requests' blocks, and what a test makes up.
NOT_LEADING = {
    "dx-review", "dx-review-record", "dx-board", "dx-security-intake", "dx-autopilot-stop", "dx-advisory-checks",
    "dx-checklist", "dx-repro-retry", "dx-state", "dx-proposals", "dx-prd-seal", "dx-g1", "dx-security-patch",
    "dx-scenarios", "dx-mention", "dx-autopilot-others", "dx-autopilot-ask", "dx-triage-record", "dx-spike",
    "dx-revert-wait", "dx-repro-blocks", "dx-release", "dx-nightly-closed", "dx-lane-verdict", "dx-credits",
    "dx-claim-test", "dx-claim", "dx-autopilot-silent", "dx-autopilot-core", "dx-advisory-attempt", "dx-waiting",
    "dx-triage-failed", "dx-tested", "dx-screenshots", "dx-repro-broke", "dx-prepr-sig", "dx-nightly-review",
    "dx-flow-numbers", "dx-decision", "dx-autopilot-unfinished", "dx-autopilot-prepr", "dx-settled",
    "dx-autopilot-hint", "dx-conventions",
    # Made up by the tests, never written.
    "dx-x", "dx-anything",
}


def test_a_new_mark_is_either_a_leading_marker_or_known_not_to_be():
    found = set()
    for path in list(SCRIPTS.glob("*.py")) + list(SCRIPTS.glob("*.sh")) + list((ROOT / ".github/workflows").glob("*.yml")):
        found |= set(re.findall(r"<!--\s*(dx-[a-z0-9-]+)", path.read_text(encoding="utf-8")))
    leading = {n.split(" ")[0] for n, _, _ in schema.MARKERS}
    unknown = found - leading - NOT_LEADING
    assert not unknown, f"a dx- mark issue-schema.py MARKERS does not list, nor NOT_LEADING here: {sorted(unknown)}"
