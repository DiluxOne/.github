"""The reproduction in a private repository (#393): a job that reads issues
with github.token grants `issues`, and a broken reproduction says so."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
READS_ISSUES = re.compile(r"gh issue (view|list)|gh api \S*issues|repos/\S*/issues")


def jobs():
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        for name, job in (yaml.safe_load(path.read_text(encoding="utf-8")).get("jobs") or {}).items():
            yield path.name, name, job


def reads_issues_with_github_token(step):
    """A line that reads issues and does not set a token of its own
    (`GH_TOKEN="$ISSUES_TOKEN" gh issue list`), in a step whose GH_TOKEN is
    github.token."""
    env = step.get("env") or {}
    if "github.token" not in str(env.get("GH_TOKEN", "")):
        return False
    return any(READS_ISSUES.search(line) and "GH_TOKEN=" not in line for line in str(step.get("run", "")).splitlines())


def test_a_job_reading_issues_with_github_token_grants_issues():
    missing = [
        f"{wf} {name}"
        for wf, name, job in jobs()
        if "uses" not in job
        and isinstance(job.get("permissions"), dict)
        and "issues" not in job["permissions"]
        and any(reads_issues_with_github_token(s) for s in job.get("steps") or [])
    ]
    assert not missing, f"reads issues with github.token, no issues permission: {missing}"


def test_the_reproduction_job_can_read_the_issue():
    job = yaml.safe_load((ROOT / ".github/workflows/issue-repro.yml").read_text(encoding="utf-8"))["jobs"]["write"]
    assert job["permissions"].get("issues") in ("read", "write")


def test_a_broken_reproduction_says_so_on_the_issue():
    steps = yaml.safe_load((ROOT / ".github/workflows/issue-repro.yml").read_text(encoding="utf-8"))["jobs"]["write"]["steps"]
    broke = next(s for s in steps if s.get("name") == "The reproduction broke")
    assert broke["if"] == "failure() && steps.cap.outputs.run == 'true'"
    assert "--add-label needs-human" in broke["run"] and "gh issue comment" in broke["run"]
    assert steps[-1] is broke, "it must be the job's last step, so any step before it that fails reaches it"
    token = next(s for s in steps if s.get("id") == "broke")
    assert token["if"] == broke["if"] and token["with"]["permission-issues"] == "write"
    assert "steps.broke.outputs.token" in broke["env"]["GH_TOKEN"], "a token that may write the issue, made when it broke"


def test_a_line_with_a_token_of_its_own_is_not_github_token():
    step = {"env": {"GH_TOKEN": "${{ github.token }}"}, "run": 'held=$(GH_TOKEN="$ISSUES_TOKEN" gh issue list --label security)'}
    assert not reads_issues_with_github_token(step)
    step["run"] = 'gh issue view "$NUMBER" --json comments'
    assert reads_issues_with_github_token(step)
