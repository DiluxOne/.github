"""#641: waiting.py reads each pull request's statusCheckRollup (commit
statuses), so both App tokens of waiting-update.yml must ask statuses: read."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_the_update_and_view_tokens_may_read_commit_statuses():
    wf = yaml.safe_load((ROOT / ".github/workflows/waiting-update.yml").read_text(encoding="utf-8"))
    for name in ("update", "view"):
        steps = wf["jobs"][name]["steps"]
        token = next(s for s in steps if s.get("id") == "bot")
        assert token["with"].get("permission-statuses") == "read", name
