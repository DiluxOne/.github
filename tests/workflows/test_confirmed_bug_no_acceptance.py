"""A bug the reproduction confirmed waits for no acceptance (#427): the
reproduction that hands a report to its lane takes `awaiting-acceptance` and
`incomplete` off it, and G1 leaves alone a `bug:confirmed` report that carries
neither; with the lane closed, the report keeps waiting for a maintainer."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_g1_leaves_a_confirmed_report_alone_on_open_and_edit():
    job = yaml.safe_load((ROOT / ".github/workflows/issue-accepted.yml").read_text(encoding="utf-8"))["jobs"]["ready"]
    cond = " ".join(str(job["if"]).split())
    # The second alternative of the condition is the check before the decision.
    before = cond[cond.index("((github.event.action == 'opened'"):]
    # Only a report handed to its lane: confirmed, and neither label left on.
    assert ("!(contains(github.event.issue.labels.*.name, 'bug:confirmed') && "
            "!contains(github.event.issue.labels.*.name, 'awaiting-acceptance') && "
            "!contains(github.event.issue.labels.*.name, 'incomplete'))") in before
    # An acceptance is still checked, confirmed or not.
    accepted = cond[:cond.index("((github.event.action == 'opened'")]
    assert "bug:confirmed" not in accepted


def test_the_reproduction_takes_the_waiting_labels_off_when_it_confirms():
    text = (ROOT / ".github/workflows/issue-repro.yml").read_text(encoding="utf-8")
    start = text.index('--add-label bug:confirmed --remove-label bug:unconfirmed')
    lane = text.index('if [ "$LANE_OPEN" = yes ]', start)
    # Not before the lane is known to be open: with it closed, the report
    # still waits for a maintainer.
    assert "awaiting-acceptance" not in text[start:lane]
    handoff = text[lane:text.index("handoff=true", lane)]
    assert "for l in awaiting-acceptance incomplete" in handoff and '--remove-label "$l"' in handoff
