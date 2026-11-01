"""A bug the reproduction confirmed waits for no acceptance (#427): the
reproduction that hands a report to its lane takes `awaiting-acceptance` and
`incomplete` off it, and G1 leaves alone a report whose board's state says
`repro: confirmed` (#564) that carries neither; with the lane closed, the report keeps waiting for a maintainer."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_g1_leaves_a_confirmed_report_alone_on_open_and_edit():
    job = yaml.safe_load((ROOT / ".github/workflows/issue-accepted.yml").read_text(encoding="utf-8"))["jobs"]["ready"]
    cond = " ".join(str(job["if"]).split())
    # #564: no label says the reproduction confirmed it; the board's state
    # does, read in a step, never in the job's condition.
    assert "bug:confirmed" not in cond
    steps = {s.get("id"): s for s in job["steps"]}
    handed = steps["handed"]
    # Only on an open or an edit, and only a report handed to its lane:
    # confirmed, and neither label left on.
    assert "github.event.action != 'labeled'" in handed["if"]
    assert "!contains(github.event.issue.labels.*.name, 'awaiting-acceptance')" in handed["if"]
    assert "!contains(github.event.issue.labels.*.name, 'incomplete')" in handed["if"]
    run = handed["run"]
    assert "receipts.py state get repro" in run and "receipts.py state get tampered" in run
    assert '[ "$repro" = confirmed ] && [ -z "$tampered" ]' in run
    # The check is what it skips; an acceptance is still checked.
    assert steps["check"]["if"] == "steps.handed.outputs.skip != 'true'"
    names = [s.get("id") for s in job["steps"]]
    assert names.index("handed") < names.index("check")


def test_the_acceptance_no_longer_removes_needs_triage():
    text = (ROOT / ".github/workflows/issue-accepted.yml").read_text(encoding="utf-8")
    assert "needs-triage" not in text


def test_the_reproduction_takes_the_waiting_labels_off_when_it_confirms():
    text = (ROOT / ".github/workflows/issue-repro.yml").read_text(encoding="utf-8")
    # #564: the board's state says it is confirmed, no label.
    start = text.index('state set repro=confirmed')
    lane = text.index('if [ "$LANE_OPEN" = yes ]', start)
    # Not before the lane is known to be open: with it closed, the report
    # still waits for a maintainer.
    assert "awaiting-acceptance" not in text[start:lane]
    handoff = text[lane:text.index("handoff=true", lane)]
    assert "for l in awaiting-acceptance incomplete" in handoff and '--remove-label "$l"' in handoff
