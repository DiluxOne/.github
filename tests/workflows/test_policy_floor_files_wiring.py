"""The policy floor's file list (#768): claude-review.yml's "Policy floor
(deterministic)" step lists the files through scripts/pr-files.py, which
waits for a files API that lags behind a new pull request, and a list it
still cannot read reaches the review as a high floor, never a failed job."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def review_steps():
    wf = yaml.safe_load((ROOT / ".github/workflows/claude-review.yml").read_text(encoding="utf-8"))
    return wf["jobs"]["review"]["steps"]


def policy_step():
    return next(s for s in review_steps() if s.get("name") == "Policy floor (deterministic)")


def new_path(run):
    """The step's script where pr-files.py is there: up to its `else`."""
    start = run.index("if [ -f .dx-central/scripts/pr-files.py ]; then")
    return run[start:run.index("\nelse\n", start)]


def test_an_unlistable_change_is_a_high_floor_not_a_failed_job():
    """C3: with pr-files.py the step no longer exits on an empty or partial
    list; policy.py's reason for an empty one reaches the summary's
    `Policy floor` line."""
    step = policy_step()
    run = step["run"]
    branch = new_path(run)
    assert 'CHANGED_FILES="$(python3 .dx-central/scripts/pr-files.py)"' in branch
    assert "exit 1" not in branch and "LISTED" not in branch
    assert run.rstrip().endswith("python3 .dx-central/scripts/policy.py")
    assert step["env"]["HEAD"] == "${{ github.event.pull_request.head.sha }}"
    assert "no changed files could be listed" in (ROOT / "scripts/policy.py").read_text(encoding="utf-8")
    summary = [s for s in review_steps() if "Policy floor: $FLOOR ($REASONS)" in s.get("run", "")]
    assert summary, "no step prints the floor's reasons"
    for s in summary:
        assert s["env"]["REASONS"] == "${{ steps.policy.outputs.reasons }}"
        assert s["env"]["FLOOR"] == "${{ steps.policy.outputs.floor }}"


def test_the_bound_is_data_not_the_workflow():
    """C4: the bound is `files-wait` in the organisation's default policy,
    which the step hands the script; the step itself has no retry count or
    sleep."""
    import re
    default = yaml.safe_load((ROOT / "policy/review-policy.default.yml").read_text(encoding="utf-8"))
    assert set(default["files-wait"]) == {"reads", "seconds"}
    step = policy_step()
    assert step["env"]["DEFAULT_POLICY"] == ".dx-central/policy/review-policy.default.yml"
    run = step["run"]
    assert "sleep" not in run and not re.search(r"\bseq\b|\bfor\b|\bwhile\b|\buntil\b", run)
    assert "files-wait" in (ROOT / "scripts/pr-files.py").read_text(encoding="utf-8")
