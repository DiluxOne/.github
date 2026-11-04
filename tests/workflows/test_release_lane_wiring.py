"""The release lane's wiring (#644): the callers tokens read the test
repository's checks and the workflow runs behind them, and a failed scenario
reaches the job that opens its bug instead of stopping the lane."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def jobs():
    wf = yaml.safe_load((ROOT / ".github/workflows/release-lane.yml").read_text(encoding="utf-8"))
    return wf["jobs"]


def test_the_callers_tokens_may_read_the_checks_workflow_runs():
    tokens = [s for s in jobs()["scenarios"]["steps"] if "create-github-app-token" in s.get("uses", "")]
    assert [t["id"] for t in tokens] == ["app", "back"]
    for t in tokens:
        w = t["with"]
        assert w["permission-checks"] == "read"
        assert w["permission-statuses"] == "read"
        assert w["permission-actions"] == "read"
