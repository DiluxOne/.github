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
    assert "github.event.sender.login == vars.DX_BOT_LOGIN" in opened
    assert "toJSON(github.event.issue.labels) == '[]'" in opened
    assert "!startsWith(github.event.issue.title, 'The bug reproduced from ')" in opened


def test_an_opened_issue_starts_and_only_autopilot_continue_continues():
    _, mode = triage_start()
    assert mode == "${{ github.event.label.name == 'autopilot:continue' && 'continue' || 'start' }}"


def test_a_start_that_finds_no_lane_asks_once_more():
    text = (ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8")
    step = text[text.index("A decision's sub-issue starts when it opens"):]
    step = step[:step.index('echo "go=false"')]
    assert step.count("autopilot.py lane") == 2 and '"$AS" != start' in step and "sleep" in step
