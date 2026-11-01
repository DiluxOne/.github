"""#585: v7.9.0 asked the callers for a permission they do not grant.

A reusable workflow's job gets no more than its caller grants. The `triage`
job of the callers adopted repositories already have (the ones
`sync-repos.py callers` wrote before v7.9.0, docs/migrating.md) grants
`contents: read` and `issues: write`, so no job of `issue-triage.yml`, nested
calls included, may ask for more within `v7`, or the `Issues` run ends in
`startup_failure`.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
LEVEL = {"none": 0, "read": 1, "write": 2}
GRANTED_BY_THE_ADOPTED_TRIAGE_CALLER = {"contents": "read", "issues": "write"}


def load(path):
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def test_no_job_of_issue_triage_asks_for_more_than_the_adopted_triage_caller_grants():
    workflow = load(".github/workflows/issue-triage.yml")
    asked_too_much = []
    for name, job in workflow["jobs"].items():
        asked = job.get("permissions", workflow.get("permissions")) or {}
        for permission, level in asked.items():
            granted = GRANTED_BY_THE_ADOPTED_TRIAGE_CALLER.get(permission, "none")
            if LEVEL[level] > LEVEL[granted]:
                asked_too_much.append(f"issue-triage.yml job `{name}` asks {permission}: {level}")
    assert not asked_too_much, asked_too_much
