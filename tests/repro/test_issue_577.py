"""#577: the autopilot's start check must count only open pull requests that
GitHub lists as closing the issue, never a text search (`linked:issue N`
matches any open pull request linked to some issue that mentions N)."""
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# A stub logs its name and arguments: a call ends with \x1e, its fields with \x1f.
LOG = 'printf \'%s\\x1f\' "$(basename "$0")" "$@" >> "$CALLS"; printf \'\\x1e\' >> "$CALLS"\n'


def may_it_start_step():
    wf = yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))
    return next(s for s in wf["jobs"]["prep"]["steps"] if s.get("id") == "may")


def stub(bin_dir, name, body):
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + LOG + body + "\n", encoding="utf-8")
    path.chmod(0o755)


def start(tmp_path, closing):
    """The may-it-start step on a start of an accepted, sealed issue that
    CLOSING open pull requests close (GitHub's link); a text search would
    find one more."""
    script = may_it_start_step()["run"]
    bin_dir, work, temp = tmp_path / "bin", tmp_path / "work", tmp_path / "temp"
    for d in (bin_dir, work, temp):
        d.mkdir(parents=True)
    (work / ".dx-central").symlink_to(ROOT)
    stub(bin_dir, "gh", f"""case "$*" in
  *"closedByPullRequestsReferences"*|*"closingIssuesReferences"*) echo {closing} ;;
  *"--search"*|*"linked:issue"*) echo {closing + 1} ;;
  "api repos/o/r/issues/"*) echo Feature ;;
esac""")
    stub(bin_dir, "python3", """case "$*" in
  *"autopilot.py lane"*) echo human-issue ;;
  *"receipts.py state get"*) echo null ;;
  *"receipts.py verify-prd"*) echo match ;;
esac""")
    stub(bin_dir, "sleep", "")
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "CALLS": str(tmp_path / "calls"),
           "GITHUB_REPOSITORY": "o/r", "GITHUB_OUTPUT": str(tmp_path / "out"), "RUNNER_TEMP": str(temp),
           "MODE": "start", "AS": "start", "ISSUE": "7", "PR": ""}
    done = subprocess.run(["bash", "-c", script], env=env, cwd=work, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    calls = [c.split("\x1f")[:-1] for c in (tmp_path / "calls").read_text(encoding="utf-8").split("\x1e")[:-1]]
    return calls, (tmp_path / "out").read_text(encoding="utf-8").splitlines()


def test_a_start_counts_only_pull_requests_that_close_the_issue_not_a_text_search(tmp_path):
    calls, out = start(tmp_path / "none", 0)
    gh = [" ".join(c[1:]) for c in calls if c[0] == "gh"]
    assert not any("--search" in c or "linked:issue" in c for c in gh), "the start counts pull requests by a text search"
    assert any("closedByPullRequestsReferences" in c or "closingIssuesReferences" in c for c in gh), \
        "the start does not count the pull requests GitHub lists as closing the issue"
    assert "go=true" in out, "a pull request that only mentions the issue stops the start"
    calls, out = start(tmp_path / "one", 1)
    assert "go=false" in out, "a pull request that closes the issue does not stop the start"
