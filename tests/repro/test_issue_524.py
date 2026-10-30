"""#524: the `auto-merge` job of pull-request.yml decides with main's scripts.

The `review` and `assignee` jobs pass `central-ref: main` to the reusable
workflow they call; `auto-merge.yml` reads `inputs.central-ref || job.workflow_sha`,
so without the input it runs the pull request's own scripts and policy.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_the_auto_merge_job_reads_the_engine_from_main_like_the_review_does():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "pull-request.yml").read_text(encoding="utf-8"))
    jobs = wf["jobs"]

    assert jobs["review"]["with"]["central-ref"] == "main"
    assert jobs["auto-merge"]["uses"] == "./.github/workflows/auto-merge.yml"
    assert jobs["auto-merge"]["with"].get("central-ref") == "main", "the auto-merge job passes no central-ref: main"
