"""#641: waiting.py reads each pull request's statusCheckRollup (commit
statuses), so the App tokens that run it must ask statuses: read: the
update's in waiting-update.yml, and the view's, which waiting-digest.yml
rewrites since #1004."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_the_update_and_view_tokens_may_read_commit_statuses():
    for path, name in ((".github/workflows/waiting-update.yml", "update"), (".github/workflows/waiting-digest.yml", "digest")):
        wf = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))
        steps = wf["jobs"][name]["steps"]
        token = next(s for s in steps if s.get("id") == "bot")
        assert token["with"].get("permission-statuses") == "read", name
