"""#633: the board's comment on a pull request is answered with HTTP 403 because
the `update` job's App token asks `pull-requests: read`; a comment on a pull
request needs `pull-requests: write`."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_the_boards_app_token_can_write_to_pull_requests():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "waiting-update.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["update"]["steps"]
    token = next(step for step in steps if step.get("id") == "bot")
    assert token["with"].get("permission-pull-requests") == "write"
