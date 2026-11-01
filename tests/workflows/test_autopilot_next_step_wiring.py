"""What a continue runs is next-step's one answer (#561 C1): prep's "What to
work on" step gathers the pull request's state from GitHub and runs what
`autopilot.py next-step` returns. Runs the step, extracted from the workflow,
with gh stood in and the real next-step, as test_autopilot_continue_start.py
does, and checks the triggers reach it."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))
JOBS = WF["jobs"]
LEFT = "<!-- dx-checklist -->\n- [x] **C1** a\n- [ ] **C2** b\n<!-- /dx-checklist -->\n"
DONE = LEFT.replace("[ ] **C2", "[x] **C2")


def step(job, key):
    return next(s for s in JOBS[job]["steps"] if s.get("id") == key or s.get("name") == key)


def blocking(sha):
    return {"sha": sha, "blocking": True, "findings": [{"severity": "major", "file": "a", "title": "t"}]}


def what(tmp_path, draft, merge, body=LEFT, record=None):
    """The step's outputs, the gh calls it made and its log, for a continue
    on #7 whose open autopilot pull request is #9."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    log.write_text("")
    (tmp_path / "pr-body.in").write_text(body)
    comment = json.dumps([{"user": {"login": "dilux-bot[bot]"}, "body": f"<!-- dx-review -->\n<!-- dx-review-record {json.dumps(record)} -->"}]) if record else "[]"
    (tmp_path / "comments.in").write_text(comment)
    (bin_dir / "gh").write_text(
        "#!/bin/bash\n"
        f'echo "gh $*" >> "{log}"\n'
        'case "$*" in\n'
        "  *closedByPullRequestsReferences*) echo 9 ;;\n"
        "  *state,labels*) echo true ;;\n"
        "  *'--json author'*) echo dilux-bot ;;\n"
        "  *headRefName*) echo feat/7-x ;;\n"
        "  *'--json labels'*) echo autopilot,autopilot:run-1 ;;\n"
        f"  *isDraft,headRefOid*) echo '{str(draft).lower()} h {merge}' ;;\n"
        f"  *'/comments'*) cat \"{tmp_path / 'comments.in'}\" ;;\n"
        f"  *'pr view 9'*'--json body'*) cat \"{tmp_path / 'pr-body.in'}\" ;;\n"
        "  *'--json body'*) echo '## PRD' ;;\n"
        "  *autonomy.yml*) exit 1 ;;\n"
        "esac\n")
    # The real next-step; the run's number stood in.
    (bin_dir / "python3").write_text(
        "#!/bin/bash\n"
        f'echo "python3 $*" >> "{log}"\n'
        f'case "$2" in next-run) echo 2 ;; next-step) exec "{sys.executable}" "{ROOT / "scripts/autopilot.py"}" next-step ;; esac\n')
    for f in ("gh", "python3"):
        (bin_dir / f).chmod(0o755)
    out = tmp_path / "out"
    out.write_text("")
    temp = tmp_path / "temp"
    temp.mkdir()
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", GITHUB_OUTPUT=str(out), RUNNER_TEMP=str(temp),
               GITHUB_REPOSITORY="o/r", DX_BOT_APP="dilux-bot", DX_BOT_LOGIN="dilux-bot[bot]",
               MODE="continue", ISSUE="7", PR="")
    done = subprocess.run(["bash", "-c", step("prep", "what")["run"]], env=env, capture_output=True, text=True,
                          timeout=60, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines())
    return outputs, log.read_text(), done.stdout + done.stderr


@pytest.mark.parametrize("draft,merge,body,record,mode", [
    (True, "CLEAN", LEFT, None, "continue"),            # criteria left: the work
    (True, "DIRTY", LEFT, None, "continue"),            # the work merges main first
    (True, "CLEAN", DONE, None, "continue"),            # the checks and the finish
    (False, "DIRTY", DONE, None, "fix"),                # #556: a fix round merges main
    (False, "CLEAN", DONE, blocking("h"), "fix"),       # #504: the review blocks at its head
    (False, "CLEAN", DONE, blocking("old"), "continue"),  # a review of an older head
])
def test_c1_a_continue_runs_what_next_step_returns(tmp_path, draft, merge, body, record, mode):
    out, calls, _ = what(tmp_path, draft, merge, body, record)
    assert out["go"] == "true"
    assert out["mode"] == mode
    assert "python3 .dx-central/scripts/autopilot.py next-step" in calls
    assert "continue-as" not in calls
    assert "update-branch" not in calls


def test_c1_a_ready_pull_request_only_behind_main_is_brought_in_step_by_the_bot(tmp_path):
    out, calls, said = what(tmp_path, False, "BEHIND", DONE)
    assert out.get("go") == "false"
    assert "mode" not in out
    assert "gh api -X PUT repos/o/r/pulls/9/update-branch -f expected_head_sha=h" in calls
    assert "behind main: the bot merges main into it" in said


def test_c1_the_next_step_command_reads_a_state_and_returns_one_action():
    state = {"issue": {"labels": ["accepted"]}, "lane": "human-issue", "pr": None}
    done = subprocess.run([sys.executable, str(ROOT / "scripts/autopilot.py"), "next-step"], input=json.dumps(state),
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0
    assert json.loads(done.stdout)["action"] == "spec"
    assert done.stderr.startswith("Next step: spec: ")
    bad = subprocess.run([sys.executable, str(ROOT / "scripts/autopilot.py"), "next-step"], input="{",
                         capture_output=True, text=True, timeout=60)
    assert bad.returncode == 64


def test_c1_every_trigger_reaches_prep():
    """A person's answer, a review's verdict, the queue's `dequeued` and the
    manual override all call autopilot.yml, whose prep asks next-step."""
    text = lambda n: (ROOT / ".github/workflows" / n).read_text(encoding="utf-8")
    # A review's verdict and the queue's `dequeued`.
    assert "uses: DiluxOne/.github/.github/workflows/autopilot.yml@" in text("org-pull-request.yml")
    assert "dequeued" in text("org-pull-request.yml")
    assert "uses: ./.github/workflows/autopilot.yml" in text("pull-request.yml")
    # A person's answer: the bot continues it, through issue-triage.yml.
    assert '--add-label "autopilot:continue"' in text("review-reply.yml")
    triage = yaml.safe_load(text("issue-triage.yml"))["jobs"]
    job = next(j for j in triage.values() if str(j.get("uses", "")).startswith("DiluxOne/.github/.github/workflows/autopilot.yml@"))
    assert "autopilot:continue" in job["if"] and "'continue'" in job["with"]["mode"]
    assert "autopilot.py next-step" in step("prep", "what")["run"]
