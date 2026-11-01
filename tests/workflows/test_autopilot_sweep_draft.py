"""#563 C13: an autopilot pull request only behind main, a draft too, is
brought up to date by a step with no model: autopilot-sweep.yml's
update-branch, which labels no run."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def sweep_run():
    wf = yaml.safe_load((ROOT / ".github/workflows/autopilot-sweep.yml").read_text(encoding="utf-8"))
    return wf["jobs"]["sweep"]["steps"][-1]["run"]


def test_the_sweep_reads_drafts_too_and_leaves_the_choice_to_autopilot_py():
    run = sweep_run()
    # Every open autopilot pull request, drafts included: no filter on
    # isDraft in the shell; autopilot.py sweep says `update` for one only
    # behind.
    assert "gh search prs" in run and "--draft" not in run
    assert "isDraft" in run and "select(.isDraft" not in run
    assert "python3 scripts/autopilot.py sweep" in run


def test_update_is_github_s_update_branch_with_no_model_and_no_run():
    run = sweep_run()
    update = run[run.index("update)"):run.index("continue)")]
    assert 'gh api -X PUT "repos/$repo/pulls/$n/update-branch"' in update
    # No model and no run: nothing starts the autopilot, nothing labels a run.
    for word in ("autopilot:continue", "autopilot:run-", "autopilot:free-", "claude", "anthropic"):
        assert word not in update.lower(), word
