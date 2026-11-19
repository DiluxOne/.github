"""The required tests check leaves the suite room (#852): the Scripts
(self-tests) job's timeout is at least 15 minutes, so the check is never
cancelled by its own timeout as the suite grows."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/pull-request.yml"
JOB_NAME = "Scripts (self-tests)"
FLOOR = 15


def scripts_job():
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")).get("jobs") or {}
    matches = [job for job in jobs.values() if isinstance(job, dict) and job.get("name") == JOB_NAME]
    assert len(matches) == 1, f"{WORKFLOW.name} has {len(matches)} jobs named {JOB_NAME!r}, expected one"
    return matches[0]


def test_scripts_job_sets_its_timeout():
    assert "timeout-minutes" in scripts_job(), f"{JOB_NAME} sets no timeout-minutes"


def test_scripts_job_timeout_leaves_room():
    timeout = scripts_job().get("timeout-minutes")
    assert isinstance(timeout, int) and not isinstance(timeout, bool), f"{JOB_NAME} timeout-minutes is {timeout!r}, not a number"
    assert timeout >= FLOOR, f"{JOB_NAME} timeout-minutes is {timeout}, below {FLOOR}"
