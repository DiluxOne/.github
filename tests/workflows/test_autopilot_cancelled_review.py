"""A review cancelled by a newer run of the same pull request (#820) is not a
failed review: the fix gate of the "may" step waits for the newer run's
review (go=false, no `needs-human`, no comment), while a review that failed
on its own at the current head, with no newer run, starts its round or
stops at the cap as before (C3). Runs the step's own fix gate with gh stood
in and autopilot.py's real `superseded` reading it."""
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BRANCH = "fix/7-thing"


def may_step():
    jobs = yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))["jobs"]
    return next(s for s in jobs["prep"]["steps"] if s.get("id") == "may")


def fix_gate_script():
    run = may_step()["run"]
    return "set -euo pipefail\n" + run[run.index('if [ "$MODE" = fix ]; then'):]


def gate(tmp_path, *, review, run_head, pr_head, runs, round_=2):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    log.write_text("")
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "pr.json").write_text(json.dumps({"headRefOid": pr_head, "headRefName": BRANCH}))
    (data / "jobs.json").write_text(json.dumps([{"jobs": [
        {"name": "conventions", "conclusion": "success"}, {"name": "review / Review", "conclusion": review}]}]))
    (data / "run.json").write_text(json.dumps({"id": 5, "workflow_id": 77, "head_branch": BRANCH, "head_sha": run_head, "event": "pull_request"}))
    (data / "runs.json").write_text(json.dumps({"workflow_runs": [{"id": i, "workflow_id": 77, "event": "pull_request"} for i in runs]}))
    policy = json.dumps({"autopilot-rounds": 5})
    (bin_dir / "python3").write_text(
        "#!/bin/bash\n"
        f'echo "python3 $*" >> "{log}"\n'
        f"case \"$2\" in policy) echo '{policy}' ;;\n"
        "  checks-failed) exit 0 ;;\n"
        f"  superseded|rounds-spent) exec {sys.executable} {ROOT / 'scripts/autopilot.py'} \"$2\" ;;\nesac\n")
    (bin_dir / "gh").write_text(
        "#!/bin/bash\n"
        f'echo "gh $*" >> "{log}"\n'
        'case "$*" in\n'
        f'  "pr view"*) cat "{data}/pr.json" ;;\n'
        f'  "api repos/o/r/actions/runs/5/jobs"*) cat "{data}/jobs.json" ;;\n'
        f'  "api repos/o/r/actions/runs/5") cat "{data}/run.json" ;;\n'
        f'  "api repos/o/r/actions/workflows/77/runs"*) cat "{data}/runs.json" ;;\n'
        '  api*) exit 1 ;;\n'
        "esac\n")
    for f in ("python3", "gh"):
        (bin_dir / f).chmod(0o755)
    out = tmp_path / "out"
    out.write_text("")
    env = {k: v for k, v in os.environ.items() if k not in ("REPO_AUTONOMY", "ORG_AUTONOMY", "DX_AUTOPILOT")}
    env.update(PATH=f"{bin_dir}:{os.environ['PATH']}", GITHUB_OUTPUT=str(out), GITHUB_REPOSITORY="o/r", GITHUB_RUN_ID="5",
               MODE="fix", ISSUE="7", PR="9", ROUND=str(round_), QUEUE="false", RUN_HEAD=run_head, OPEN_TO_CLAIM="open")
    done = subprocess.run(["bash", "-c", fix_gate_script()], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return log.read_text(), out.read_text(), done.stdout


def test_the_step_knows_the_head_its_run_checked():
    assert may_step()["env"].get("RUN_HEAD") == "${{ github.event.pull_request.head.sha }}"


def test_c1_a_review_cancelled_by_a_newer_run_waits_for_it(tmp_path):
    calls, out, said = gate(tmp_path, review="cancelled", run_head="aaa", pr_head="bbb", runs=[6, 5])
    assert out == "go=false\n"
    assert "autopilot.py superseded" in calls
    assert "needs-human" not in calls
    assert "gh pr comment" not in calls and "gh issue comment" not in calls and "gh pr edit" not in calls
    assert "waits for the newer run's review" in said


def test_c1_even_at_the_cap_a_superseded_run_counts_no_round(tmp_path):
    calls, out, _ = gate(tmp_path, review="cancelled", run_head="aaa", pr_head="bbb", runs=[6, 5], round_=6)
    assert out == "go=false\n"
    assert "needs-human" not in calls and "gh pr comment" not in calls


def test_c1_a_cancelled_review_at_the_same_head_waits_for_the_newer_run(tmp_path):
    calls, out, _ = gate(tmp_path, review="cancelled", run_head="aaa", pr_head="aaa", runs=[6, 5])
    assert out == "go=false\n"
    assert "needs-human" not in calls


def test_c3_a_review_that_failed_on_its_own_starts_its_round(tmp_path):
    calls, out, _ = gate(tmp_path, review="failure", run_head="aaa", pr_head="aaa", runs=[5])
    assert out == "go=true\n"
    assert "needs-human" not in calls


def test_c3_a_review_that_failed_on_its_own_stops_at_the_cap(tmp_path):
    calls, out, _ = gate(tmp_path, review="failure", run_head="aaa", pr_head="aaa", runs=[5], round_=6)
    assert out == "go=false\n"
    assert "gh pr edit 9 --repo o/r --add-label needs-human" in calls
    assert "spent its 5 rounds" in calls


def test_c3_a_cancelled_review_with_no_newer_run_goes_on(tmp_path):
    calls, out, _ = gate(tmp_path, review="cancelled", run_head="aaa", pr_head="aaa", runs=[5])
    assert out == "go=true\n"
