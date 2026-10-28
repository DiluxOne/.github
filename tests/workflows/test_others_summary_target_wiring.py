"""#487: the "what others said" summary goes to the pull request whose own
dilux-bot comment opens with the autopilot's question marker, never to the
last pull request that closes the issue, nor to one where someone else wrote
or quoted the marker."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def run():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "review-reply.yml").read_text(encoding="utf-8"))
    step = next(s for s in wf["jobs"]["others"]["steps"] if s.get("name") == "What others said since the question")
    return step["run"]


def test_the_target_is_the_pull_request_holding_dilux_bots_question():
    text = run()
    assert 'startswith("<!-- dx-autopilot-ask -->")' in text
    assert "env.DX_BOT_LOGIN" in text


def test_the_last_pull_request_closing_the_issue_is_no_longer_the_target():
    assert "| last // empty" not in run()
