"""#934 C1: the sweep does not update an autopilot draft only behind main
while its issue's autopilot run is in progress. Merging main into the branch
under the run makes the run's apply step refuse the agent's commits, so the
whole round is lost: the sweep leaves the draft for the next pass instead.
It asks `autopilot.py runs-busy` (claim.py's detection of the runs whose prep
job is named for the issue) only on an `update`, and a read that fails counts
as busy: skipping one pass costs nothing, losing a round costs a run."""
import json
from pathlib import Path

import pytest
import yaml

import steps

ROOT = Path(__file__).resolve().parents[2]

PR = {"number": 5, "isDraft": True, "mergeStateStatus": "BEHIND", "labels": [{"name": "autopilot"}],
      "headRefOid": "abc123", "author": {"login": "dilux-bot[bot]"}, "closingIssuesReferences": [{"number": 7}]}


def sweep(tmp_path, runs):
    """The sweep's step on #5 (a draft only behind main, closing #7), with gh
    stood in: RUNS is the body of `gh run list` / `gh run view`."""
    gh = ('case "$*" in\n'
          '  "search prs"*) echo "o/r 5" ;;\n'
          f"  \"pr view 5\"*) echo '{json.dumps(PR)}' ;;\n"
          "  \"issue view 7\"*) echo '[\"accepted\"]' ;;\n"
          '  "api -X GET search/issues"*) echo 0 ;;\n'
          f"{runs}"
          "esac\n")
    s = steps.step("autopilot-sweep.yml", "Bring each one in step", job="sweep")
    ran = steps.run(s, tmp_path, stubs={"gh": gh, "claude": "exit 1", "sleep": ""}, env={"REPO": "o/r", "OWNER": "o"})
    assert ran.code == 0, ran.stdout + ran.stderr
    return ran


def updated(ran):
    return [c for c in ran.of("gh") if any("update-branch" in a for a in c)]


BUSY = ('  "run list --repo o/r --status in_progress"*) echo 4242 ;;\n'
        '  "run list"*) ;;\n'
        "  \"run view 4242\"*) printf '%s\\n' 'Autopilot (continue) · may it run · #7' 'Autopilot (continue) · the agent' ;;\n")


def test_a_draft_whose_issue_has_a_run_in_progress_is_left(tmp_path):
    ran = sweep(tmp_path, BUSY)
    assert not updated(ran), ran.stdout
    assert "o/r#5: left for the next pass: its issue's autopilot run 4242 is in progress" in ran.stdout


def test_a_queued_run_counts_too(tmp_path):
    queued = ('  "run list --repo o/r --status queued"*) echo 77 ;;\n'
              '  "run list"*) ;;\n'
              "  \"run view 77\"*) echo 'Autopilot (start) · may it run · #7' ;;\n")
    ran = sweep(tmp_path, queued)
    assert not updated(ran), ran.stdout
    assert "autopilot run 77 is in progress" in ran.stdout


def test_another_issue_s_run_does_not_hold_it(tmp_path):
    other = ('  "run list --repo o/r --status in_progress"*) echo 9 ;;\n'
             '  "run list"*) ;;\n'
             "  \"run view 9\"*) echo 'Autopilot (continue) · may it run · #70' ;;\n")
    ran = sweep(tmp_path, other)
    assert ["api", "-X", "PUT", "repos/o/r/pulls/5/update-branch", "-f", "expected_head_sha=abc123"] in ran.of("gh")


def test_a_read_that_fails_counts_as_busy(tmp_path):
    ran = sweep(tmp_path, '  "run list"*) echo boom >&2; exit 1 ;;\n')
    assert not updated(ran), ran.stdout
    assert "o/r#5: left for the next pass" in ran.stdout


def test_no_run_no_hold(tmp_path):
    ran = sweep(tmp_path, '  "run list"*) ;;\n')
    assert ["api", "-X", "PUT", "repos/o/r/pulls/5/update-branch", "-f", "expected_head_sha=abc123"] in ran.of("gh")


def test_the_runs_are_read_only_on_an_update(tmp_path):
    # Not in step with main: the sweep says nothing, and lists no runs.
    s = steps.step("autopilot-sweep.yml", "Bring each one in step", job="sweep")
    clean = dict(PR, mergeStateStatus="CLEAN")
    gh = ('case "$*" in\n'
          '  "search prs"*) echo "o/r 5" ;;\n'
          f"  \"pr view 5\"*) echo '{json.dumps(clean)}' ;;\n"
          "  \"issue view 7\"*) echo '[\"accepted\"]' ;;\n"
          '  "api -X GET search/issues"*) echo 0 ;;\n'
          "esac\n")
    ran = steps.run(s, tmp_path, stubs={"gh": gh, "sleep": ""}, env={"REPO": "o/r", "OWNER": "o"})
    assert ran.code == 0, ran.stdout + ran.stderr
    assert not [c for c in ran.of("gh") if c[:1] == ["run"]]


def test_the_token_may_list_runs():
    wf = yaml.safe_load((ROOT / ".github/workflows/autopilot-sweep.yml").read_text(encoding="utf-8"))
    token = next(s for s in wf["jobs"]["sweep"]["steps"] if s.get("id") == "bot")
    assert token["with"].get("permission-actions") == "read"
