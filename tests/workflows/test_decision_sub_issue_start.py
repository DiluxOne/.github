"""An accepted decision's sub-issue starts the autopilot (#415): the start on
`opened` is only for an issue dilux-bot opens with no label, never a
reproduced bug's lane issue, and a start that finds no lane asks once more."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def triage_start():
    job = yaml.safe_load((ROOT / ".github/workflows/issue-triage.yml").read_text(encoding="utf-8"))["jobs"]["autopilot"]
    return " ".join(str(job["if"]).split()), job["with"]["mode"]


def test_the_start_on_opened_is_dilux_bots_unlabelled_issue():
    cond, _ = triage_start()
    # The last alternative of the condition is the start on `opened`.
    opened = cond[cond.index("(github.event.action == 'opened'"):]
    assert "github.event.sender.login == (vars.DX_BOT_LOGIN || 'dilux-bot[bot]')" in opened
    assert "toJSON(github.event.issue.labels) == '[]'" in opened
    assert "!startsWith(github.event.issue.title, 'The bug reproduced from ')" in opened


def test_an_opened_issue_starts_and_a_continue_is_review_replys_alone():
    # #564: `/continue` from a writer is review-reply.yml's (one run, never
    # two); the triage only starts, and never on a label.
    cond, mode = triage_start()
    assert mode == "start"
    assert "continue" not in cond


def test_a_start_that_finds_no_lane_asks_once_more():
    text = (ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8")
    step = text[text.index("A decision's sub-issue starts when it opens"):]
    step = step[:step.index('echo "go=false"')]
    assert step.count("autopilot.py lane") == 2 and '"$AS" != start' in step and "sleep" in step
