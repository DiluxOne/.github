"""#798: the release lane's own pull request changes only CHANGELOG.md, which the
review floors to `risk:high`, and the auto-merge decision never merges a
high-risk pull request. The lane must merge its release pull request itself,
never queue it with `gh pr merge --auto` and wait for a merge that cannot come.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_release_lane_merges_its_own_pull_request_without_waiting_for_auto_merge():
    source = (ROOT / "scripts" / "release-lane.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    merges = [line for line in code.splitlines() if re.search(r'"gh",\s*"pr",\s*"merge"', line)]
    assert not any("--auto" in line for line in merges), (
        "release() asks for `gh pr merge --auto`, which never merges a risk:high pull request "
        "(CHANGELOG.md is a high-risk path): the lane waits 60 minutes and releases nothing"
    )
