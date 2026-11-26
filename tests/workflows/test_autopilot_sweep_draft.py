"""#563 C13: an autopilot pull request only behind main, a draft too, is
brought up to date by a step with no model: autopilot-sweep.yml's
update-branch, which labels no run."""
import json
from pathlib import Path

import pytest
import yaml

import steps

ROOT = Path(__file__).resolve().parents[2]


def sweep_run():
    return steps.step("autopilot-sweep.yml", "Bring each one in step", job="sweep")["run"]


def test_the_sweep_reads_drafts_too_and_leaves_the_choice_to_autopilot_py():
    run = sweep_run()
    # Every open autopilot pull request, drafts included: no filter on
    # isDraft in the shell; autopilot.py sweep says `update` for one only
    # behind.
    assert "gh search prs" in run and "--draft" not in run
    assert "isDraft" in run and "select(.isDraft" not in run
    assert "python3 .dx-central/scripts/autopilot.py sweep" in run


def sweep(tmp_path, draft=True):
    """Runs the sweep's step on one autopilot pull request only behind main
    (#5, closing #7), with gh stood in and autopilot.py's real `sweep`."""
    pr = {"number": 5, "isDraft": draft, "mergeStateStatus": "BEHIND", "labels": [{"name": "autopilot"}],
          "headRefOid": "abc123", "author": {"login": "dilux-bot[bot]"}, "closingIssuesReferences": [{"number": 7}]}
    gh = ('case "$*" in\n'
          '  "search prs"*) echo "o/r 5" ;;\n'
          f"  \"pr view 5\"*) echo '{json.dumps(pr)}' ;;\n"
          "  \"issue view 7\"*) echo '[\"accepted\"]' ;;\n"
          '  "api -X GET search/issues"*) echo 0 ;;\n'
          "esac\n")
    s = steps.step("autopilot-sweep.yml", "Bring each one in step", job="sweep")
    ran = steps.run(s, tmp_path, stubs={"gh": gh, "claude": "exit 1", "sleep": ""}, env={"REPO": "o/r", "OWNER": "o"})
    assert ran.code == 0, ran.stdout + ran.stderr
    return ran


@pytest.mark.parametrize("draft", [True, False])
def test_update_is_github_s_update_branch_with_no_model_and_no_run(tmp_path, draft):
    ran = sweep(tmp_path, draft)
    calls = ran.of("gh")
    assert ["api", "-X", "PUT", "repos/o/r/pulls/5/update-branch", "-f", "expected_head_sha=abc123"] in calls
    # No model and no run: nothing starts the autopilot, nothing labels a
    # run, the issue's board is not touched.
    assert not ran.of("claude")
    assert not [c for c in calls if c[:2] in (["issue", "edit"], ["pr", "edit"], ["label", "create"])]
    for word in ("autopilot:continue", "autopilot:run-", "autopilot:free-", "claude", "anthropic"):
        assert not [c for c in calls if word in " ".join(c).lower()], word
    assert "catchup" not in json.dumps(ran.calls)
    assert "o/r#5: update:" in ran.stdout
