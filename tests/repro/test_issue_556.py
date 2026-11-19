"""#556: `autopilot:continue` on a ready autopilot pull request that conflicts
with main must reach the step that merges main into its branch, so the step
that decides what a continue runs (`autopilot.py next-step`, #561, which
folds in `continue-as`) has to be told whether the pull request conflicts.
It runs the step with stubs and reads the state it hands next-step.
"""
import json
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# A stub logs its name and arguments: a call ends with \x1e, its fields with \x1f.
LOG = 'printf \'%s\\x1f\' "$(basename "$0")" "$@" >> "$CALLS"; printf \'\\x1e\' >> "$CALLS"\n'


def step(name):
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "autopilot.yml").read_text(encoding="utf-8"))
    return next(s for s in wf["jobs"]["prep"]["steps"] if s.get("name") == name)


def stub(bin_dir, name, body):
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + LOG + body + "\n", encoding="utf-8")
    path.chmod(0o755)


def test_a_continue_on_a_ready_pull_request_that_conflicts_with_main_is_told_of_the_conflict(tmp_path):
    script = step("What to work on")["run"]
    bin_dir, work, temp = tmp_path / "bin", tmp_path / "work", tmp_path / "temp"
    for d in (bin_dir, work, temp):
        d.mkdir()
    (work / ".dx-central").symlink_to(ROOT)
    stub(bin_dir, "gh", """case "$*" in
  *"--json closedByPullRequestsReferences"*) echo 12 ;;
  *"--json state,labels"*) echo true ;;
  *"--json author"*) echo "$DX_BOT_LOGIN" ;;
  *"--json headRefName"*) echo autopilot/5 ;;
  *"--json labels"*) echo autopilot ;;
  *"--json isDraft,headRefOid,mergeStateStatus"*) echo "false abc123 DIRTY" ;;
  "api repos/o/r/issues/12/comments"*) echo '[]' ;;
  *"--json body"*) echo "the body" ;;
  "api repos/o/r/contents/"*) exit 1 ;;
esac""")
    # next-step's input is kept; its answer is a fix round, as it gives for a conflict.
    stub(bin_dir, "python3", """case "$*" in
  *"autopilot.py next-step"*) cat > "$NEXT_STEP"; echo '{"as": "fix", "why": "it conflicts with main"}' ;;
  *"autopilot.py next-run"*) echo runs=2 ;;
esac""")
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "CALLS": str(tmp_path / "calls"), "NEXT_STEP": str(tmp_path / "state.json"),
           "GITHUB_REPOSITORY": "o/r", "GITHUB_OUTPUT": str(tmp_path / "out"), "RUNNER_TEMP": str(temp),
           "DX_BOT_APP": "dilux-bot", "DX_BOT_LOGIN": "dilux-bot[bot]", "MODE": "continue", "ISSUE": "5", "PR": ""}
    done = subprocess.run(["bash", "-c", script], env=env, cwd=work, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    calls = [c.split("\x1f")[:-1] for c in (tmp_path / "calls").read_text(encoding="utf-8").split("\x1e")[:-1]]
    assert any(c[0] == "gh" and "isDraft,headRefOid,mergeStateStatus" in c for c in calls), \
        "the step never reads whether the pull request conflicts with main"
    assert any(c[0] == "python3" and "next-step" in c for c in calls), "the step does not ask next-step what a continue runs"
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["pr"].get("merge") == "dirty", \
        "next-step is given the draft flag, head and review record, but not the merge state"
    out = (tmp_path / "out").read_text(encoding="utf-8").splitlines()
    assert "mode=fix" in out and "conflicts=true" in out
