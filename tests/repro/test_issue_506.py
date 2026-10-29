"""#506: a major the pull request introduced does not start the fix round.

The review's `blocking` output is decided by the findings, not by the model's
boolean: the rule lives in `scripts/review-count.py` (a `blocking` subcommand)
and the `verdict` step of the `review` job calls it. Today the step only turns
the model's `blocking` off (when `serious` is 0), never on.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_the_review_blocking_output_is_decided_by_the_findings_through_review_count_blocking():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "claude-review.yml").read_text(encoding="utf-8"))
    step = next(s for s in wf["jobs"]["review"]["steps"] if s.get("id") == "verdict")

    assert "review-count.py blocking" in step["run"], "the step does not ask review-count.py for `blocking`"
