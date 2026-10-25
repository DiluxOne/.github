"""A bug the reproduction confirmed waits for no acceptance (#427): the
reproduction takes `awaiting-acceptance` and `incomplete` off the report, and
G1 leaves a `bug:confirmed` report alone when it is opened or edited."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_g1_leaves_a_confirmed_report_alone_on_open_and_edit():
    job = yaml.safe_load((ROOT / ".github/workflows/issue-accepted.yml").read_text(encoding="utf-8"))["jobs"]["ready"]
    cond = " ".join(str(job["if"]).split())
    # The second alternative of the condition is the check before the decision.
    before = cond[cond.index("((github.event.action == 'opened'"):]
    assert "!contains(github.event.issue.labels.*.name, 'bug:confirmed')" in before
    # An acceptance is still checked, confirmed or not.
    accepted = cond[:cond.index("((github.event.action == 'opened'")]
    assert "bug:confirmed" not in accepted


def test_the_reproduction_takes_the_waiting_labels_off_when_it_confirms():
    text = (ROOT / ".github/workflows/issue-repro.yml").read_text(encoding="utf-8")
    start = text.index('--add-label bug:confirmed --remove-label bug:unconfirmed')
    after = text[start:text.index('if [ "$LANE_OPEN" = yes ]', start)]
    assert "for l in awaiting-acceptance incomplete" in after and '--remove-label "$l"' in after
