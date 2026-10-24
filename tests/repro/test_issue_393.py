"""Issue #393: the reproduction's `write` job reads the issue with `github.token`,
which in a private repository needs `issues: read`."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def test_the_write_job_grants_issues_to_the_token_that_reads_the_issue():
    write = workflow("issue-repro.yml")["jobs"]["write"]
    brief = next(step for step in write["steps"] if step.get("name") == "Brief")
    assert brief["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert "gh issue view" in brief["run"]
    assert write["permissions"].get("issues") in ("read", "write")
