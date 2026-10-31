"""The autopilot's bug gate in its workflow (#377): `may-start` exiting 2
is a bug in a repository with no way to reproduce one, said on the issue;
any other refusal is not. Runs the step's own script with python3 and gh
stood in."""
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def may_start_script():
    jobs = yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))["jobs"]
    return next(s["run"] for s in jobs["prep"]["steps"] if s.get("name") == "May it start")


def run(tmp_path, mode, rc):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    (bin_dir / "python3").write_text(
        "#!/bin/bash\n"
        f'echo "python3 $* ISSUE_TYPE=$ISSUE_TYPE" >> "{log}"\n'
        'case "$2" in lane) echo human-issue ;; may-start) echo "it declares no way"; exit "$STUB_RC" ;; esac\n')
    (bin_dir / "gh").write_text(f'#!/bin/bash\necho "gh $*" >> "{log}"\n[ "$1" = api ] && echo Bug\nexit 0\n')
    for f in ("python3", "gh"):
        (bin_dir / f).chmod(0o755)
    out = tmp_path / "out"
    out.write_text("")
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", RUNNER_TEMP=str(tmp_path), GITHUB_OUTPUT=str(out),
               GITHUB_REPOSITORY="o/r", MODE=mode, AS=mode, ISSUE="7", PR="", ROUND="1", RUNS="1", STUB_RC=str(rc))
    done = subprocess.run(["bash", "-c", may_start_script()], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return log.read_text(), out.read_text()


def test_exit_2_says_on_the_issue_which_way_to_declare(tmp_path):
    calls, out = run(tmp_path, "start", 2)
    assert "gh issue comment 7 --repo o/r --body it declares no way" in calls
    assert "ISSUE_TYPE=Bug" in calls
    assert "go=false" in out


def test_another_refusal_comments_nothing(tmp_path):
    calls, out = run(tmp_path, "start", 1)
    assert "issue comment" not in calls
    assert "go=false" in out


def test_a_run_that_continues_reads_no_issue_type(tmp_path):
    calls, _ = run(tmp_path, "continue", 1)
    assert "gh api repos/o/r/issues/7" not in calls
    assert "may-start ISSUE_TYPE=\n" in calls
