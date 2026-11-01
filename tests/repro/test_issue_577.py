"""#577: the autopilot's start check must count only open pull requests that
GitHub lists as closing the issue, never a text search (`linked:issue N`
matches any open pull request linked to some issue that mentions N)."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def may_it_start_run():
    wf = yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))
    return next(s for s in wf["jobs"]["prep"]["steps"] if s.get("id") == "may")["run"]


def test_a_start_counts_only_pull_requests_that_close_the_issue_not_a_text_search():
    run = may_it_start_run()
    check = run[run.index("open_prs="):run.index("nothing to start")]
    assert "--search" not in check and "linked:issue" not in check
    assert "closedByPullRequestsReferences" in check or "closingIssuesReferences" in check
