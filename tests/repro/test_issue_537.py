"""#537: the autopilot's work job token can read pull requests.

`make pre-pr` runs next-version.py in the work job, which lists the closed
pull requests with the job's own token: it needs `pull-requests: read`, and
the permission has to reach the job through every workflow that calls it.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def test_the_work_job_reads_pull_requests_and_writes_nothing():
    work = load(".github/workflows/autopilot.yml")["jobs"]["work"]

    assert work["permissions"] == {"contents": "read", "pull-requests": "read"}


def test_the_permission_reaches_the_work_job_through_every_caller():
    autopilot_job = load(".github/workflows/issue-triage.yml")["jobs"]["autopilot"]
    assert autopilot_job["permissions"].get("pull-requests") == "read", "issue-triage.yml's autopilot job"

    triage_caller = load("workflow-templates/issues.yml")["jobs"]["triage"]
    assert triage_caller["permissions"].get("pull-requests") == "read", "the issues.yml template's triage job"
