"""#537: the autopilot's work job can read the pull requests `make pre-pr` needs.

`make pre-pr` runs next-version.py in the work job, which lists the merged
pull requests' labels. The work job's token reads the repository and nothing
more, and no caller grants it more (#585: a called job gets no more than its
caller grants, and the adopted callers grant none). So the jobs that hold the
key and write what the agent reads, `prep` and `draft`, save the pull
requests into `.dx-io/pulls.json`, and the work reads them there through
`DX_PULLS`, which next-version.py reads instead of GitHub.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def step(job, name):
    return next(st for st in job["steps"] if st.get("name") == name)


def test_the_work_job_reads_the_pull_requests_the_keyed_jobs_saved_and_writes_nothing():
    jobs = load(".github/workflows/autopilot.yml")["jobs"]

    assert jobs["work"]["permissions"] == {"contents": "read"}
    agent = next(st for st in jobs["work"]["steps"] if "claude-code-action" in str(st.get("uses", "")))
    assert agent["env"]["DX_PULLS"] == "${{ github.workspace }}/.dx-io/pulls.json"
    for job, name in (("prep", "The agent's task"), ("draft", "The work's task")):
        assert 'next-version.py --repo "$GITHUB_REPOSITORY"' in step(jobs[job], name)["run"], job
        assert '--save-pulls "$DX_IO/pulls.json"' in step(jobs[job], name)["run"], job


def test_next_version_reads_the_merged_pull_requests_labels_from_dx_pulls(tmp_path):
    saved = {"repo": "o/r", "base": "main", "pulls": [
        {"number": 7, "merged_at": "2026-01-02T00:00:00Z", "merge_commit_sha": "a", "labels": ["type:feat"]},
        {"number": 8, "merged_at": None, "merge_commit_sha": "b", "labels": ["type:breaking"]},
    ]}
    (tmp_path / "pulls.json").write_text(json.dumps(saved), encoding="utf-8")
    # A `gh` that answers the tags and the comparison, and fails on any
    # pull request: the token of the work job cannot read them.
    gh = tmp_path / "bin" / "gh"
    gh.parent.mkdir()
    gh.write_text(
        "#!/bin/sh\n"
        'case "$2" in\n'
        '  repos/o/r/tags) echo \'[[{"name": "1.0.0"}]]\' ;;\n'
        '  repos/o/r/compare/*) echo \'{"ahead_by": 2, "commits": [{"sha": "a"}, {"sha": "x"}], '
        '"base_commit": {"commit": {"committer": {"date": "2026-01-01T00:00:00Z"}}}}\' ;;\n'
        '  *) echo "no pull requests for this token" >&2; exit 1 ;;\n'
        "esac\n",
        encoding="utf-8")
    gh.chmod(0o755)
    env = dict(os.environ, PATH="%s%s%s" % (gh.parent, os.pathsep, os.environ.get("PATH", "")), DX_PULLS=str(tmp_path / "pulls.json"))

    out = subprocess.run([sys.executable, str(ROOT / "scripts/next-version.py"), "--repo", "o/r", "--base", "main", "--json"],
                         env=env, capture_output=True, text=True)

    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["next"] == "1.1.0"


def test_no_caller_of_the_autopilot_grants_it_more_than_it_reads():
    autopilot_job = load(".github/workflows/issue-triage.yml")["jobs"]["autopilot"]
    assert autopilot_job["permissions"] == {"contents": "read"}, "issue-triage.yml's autopilot job"

    triage_caller = load("workflow-templates/issues.yml")["jobs"]["triage"]
    assert triage_caller["permissions"] == {"contents": "read", "issues": "write"}, "the issues.yml template's triage job"
