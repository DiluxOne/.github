"""#427: a reproduced bug keeps `awaiting-acceptance`, and G1 puts it back on
every edit. Written from the report as the reproduction's writer would (#376).
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def code(step):
    """A step's script without its comment lines."""
    return "\n".join(l for l in step.get("run", "").splitlines() if not l.lstrip().startswith("#"))


def test_a_report_the_reproduction_confirms_loses_awaiting_acceptance_when_handed_to_the_lane():
    steps = {s.get("id"): s for s in workflow("issue-repro.yml")["jobs"]["report"]["steps"] if s.get("id")}
    text = code(steps["report"]) + "\n" + code(steps["lane"])
    assert "awaiting-acceptance" in text


def test_g1_leaves_a_bug_confirmed_report_alone_on_open_and_edit():
    job = workflow("issue-accepted.yml")["jobs"]["ready"]
    wiring = job["if"] + "\n".join(str(s.get("if", "")) + code(s) for s in job["steps"])
    # Since #564 the reproduction's outcome is the board's state, `repro`
    # confirmed, not the bug:confirmed label.
    assert "receipts.py state get repro" in wiring and "confirmed" in wiring
