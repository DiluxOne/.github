"""`autopilot:continue` on an issue no open autopilot pull request closes
starts its next phase, as the first run does (#535); with one open, it
resumes it as before. Runs prep's "What to work on" step, extracted from the
workflow, with gh and python3 stood in (as test_autopilot_rounds.py does),
and checks the jobs that follow key on the mode prep decided."""
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))
JOBS = WF["jobs"]

PRD = "## PRD\n\n### Problem\n\nx\n"
SPEC = "\n### Spec: approach\n\ny\n"


def step(job, key):
    return next(s for s in JOBS[job]["steps"] if s.get("id") == key or s.get("name") == key)


def what(tmp_path, body, open_pr=None):
    """The step's outputs and the gh calls it made, for an issue (#7) whose
    closing pull request, when given, is an open `autopilot` one."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    log.write_text("")
    (tmp_path / "body.md.in").write_text(body)
    (bin_dir / "gh").write_text(
        "#!/bin/bash\n"
        f'echo "gh $*" >> "{log}"\n'
        'case "$*" in\n'
        f"  *closedByPullRequestsReferences*) echo '{open_pr or ''}' ;;\n"
        "  *state,labels*) echo true ;;\n"
        "  *'--json author'*) echo dilux-bot ;;\n"
        "  *headRefName*) echo feat/7-x ;;\n"
        "  *'--json labels'*) echo autopilot,autopilot:run-1 ;;\n"
        "  *isDraft,headRefOid*) echo 'true abc' ;;\n"
        "  *'/comments'*) echo '[]' ;;\n"
        f"  *'--json body'*) cat \"{tmp_path / 'body.md.in'}\" ;;\n"
        "  *review-policy.yml*) echo 'gh: Not Found (HTTP 404)' >&2; exit 1 ;;\n"
        "  *autonomy.yml*) exit 1 ;;\n"
        "esac\n")
    (bin_dir / "python3").write_text(
        "#!/bin/bash\n"
        f'echo "python3 $*" >> "{log}"\n'
        'case "$2" in next-run) echo 2 ;; continue-as) echo continue ;; esac\n')
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
    return outputs, log.read_text()


# --- C1: no open autopilot pull request: the continue starts it ----------

@pytest.mark.parametrize("body,spec", [(PRD, None), (PRD + SPEC, "present")])
def test_c1_a_continue_with_no_pull_request_starts(tmp_path, body, spec):
    out, calls = what(tmp_path, body)
    assert out["go"] == "true"
    assert out["mode"] == "start"
    assert out["runs"] == "1"
    assert out["issue"] == "7"
    assert "pr" not in out and "branch" not in out
    assert out.get("spec") == spec
    assert "--remove-label autopilot:answered" in calls
    # The start reads the repository's way to reproduce a bug (#377).
    assert "review-policy.yml" in calls


def test_c1_the_jobs_key_on_the_mode_prep_decided():
    text = (ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8")
    assert "inputs.mode == 'start'" not in text and "inputs.mode != 'start'" not in text
    assert "needs.prep.outputs.mode == 'start'" in JOBS["spec"]["if"]
    assert "needs.prep.outputs.spec != 'present'" in JOBS["spec"]["if"]
    assert "needs.prep.outputs.mode == 'start'" in JOBS["draft"]["if"]
    assert "needs.prep.outputs.mode != 'start'" in JOBS["work"]["if"]
    assert JOBS["prep"]["outputs"]["spec"] == "${{ steps.what.outputs.spec }}"
    assert "steps.what.outputs.mode != 'start'" in step("prep", "Count the round or the run")["if"]
    assert "steps.what.outputs.mode == 'start'" in step("prep", "Hand it to the agent")["with"]["name"]
    spec_out = next(s for s in JOBS["apply"]["steps"] if s.get("with", {}).get("name") == "autopilot-out-spec")
    assert spec_out["if"] == "needs.prep.outputs.mode == 'start'"


def test_c1_the_draft_opens_from_a_spec_already_on_the_issue():
    cond = step("draft", "draft")["if"]
    assert "needs.spec.outputs.outcome == 'success'" in cond
    assert "needs.prep.outputs.spec == 'present' && needs.spec.result == 'skipped'" in cond
    # A skipped Spec is never "Writing the Spec did not finish".
    end = step("apply", "end")["env"]["SPEC_OUTCOME"]
    assert end.startswith("${{ needs.prep.outputs.spec != 'present' &&") and end.endswith("|| '' }}")


def test_c1_may_it_start_runs_the_starts_gates_on_what_prep_decided():
    may = step("prep", "may")
    assert may["env"]["AS"] == "${{ steps.what.outputs.mode }}"
    run = may["run"]
    # The lane's retry, the Bug's Type, and no open pull request linked.
    assert '{ [ "$AS" != start ] || ! { sleep 20;' in run
    assert 'if [ "$AS" = start ]; then\n  ISSUE_TYPE=$(gh api' in run
    assert 'if [ "$AS" = start ]; then\n  open_prs=$(gh pr list --repo "$GITHUB_REPOSITORY" --state open --search "linked:issue $ISSUE"' in run
    # A continue's own cap is not asked of a start.
    assert 'if [ "$MODE" = continue ] && [ "$AS" != start ]; then' in run


# --- C2: an open autopilot pull request: the continue resumes it ---------

@pytest.mark.parametrize("body", [PRD + SPEC, PRD])
def test_c2_a_continue_with_an_open_pull_request_resumes_it(tmp_path, body):
    out, calls = what(tmp_path, body, open_pr="9")
    assert out["go"] == "true"
    assert out["mode"] == "continue"
    assert out["pr"] == "9"
    assert out["branch"] == "feat/7-x"
    assert out["runs"] == "2"
    assert "spec" not in out
    # The answer's label stays for the Count step, which frees the run (#479).
    assert "autopilot:answered" not in calls
    assert "review-policy.yml" not in calls


def test_c2_a_continue_keeps_its_own_path():
    # Counted as a run by the mode it was called with (#504), its cap
    # asked, and the work run on its pull request with no Spec nor draft.
    count = step("prep", "Count the round or the run")
    assert count["env"]["MODE"] == "${{ inputs.mode }}"
    assert 'AS="$AS" python3 .dx-central/scripts/autopilot.py may-continue' in step("prep", "may")["run"]
    assert "needs.prep.outputs.mode != 'start' || needs.draft.outputs.pr != ''" in JOBS["work"]["if"]
    assert step("prep", "Hand it to the agent")["with"]["name"].endswith("&& 'spec' || 'work' }}")
