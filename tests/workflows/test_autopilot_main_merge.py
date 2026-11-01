"""The autopilot brings main into its branch (#549, #550): the wiring no
script's --test can see, read from the workflow's file."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
JOBS = yaml.safe_load((ROOT / ".github" / "workflows" / "autopilot.yml").read_text(encoding="utf-8"))["jobs"]


def step(job, sid):
    return next(s for s in JOBS[job]["steps"] if s.get("id") == sid)


def test_the_work_merges_main_before_the_agent_and_aborts_on_a_conflict():
    run = step("work", "task")["run"]
    names = [s.get("id") for s in JOBS["work"]["steps"]]
    assert names.index("task") < names.index("work")
    assert 'git merge -q --no-edit "origin/$DEFAULT"' in run
    assert "git merge --abort" in run and "::warning::" in run


def test_start_is_recorded_before_the_merge_and_base_after():
    run = step("work", "task")["run"]
    merge = run.index("git merge -q")
    assert run.index('echo "start=') < merge < run.index('echo "base=')


def test_a_reproduced_bugs_draft_starts_at_main_and_checks_the_test_on_top():
    s = step("draft", "draft")
    run = s["run"]
    block = run[run.index('if [ "$LANE" = bugfix-reproduced ]'):run.index("elif adopt=")]
    assert s["env"]["DEFAULT"] == "${{ needs.prep.outputs.default }}"
    assert 'git checkout -q -b "$branch" "origin/$DEFAULT"' in block
    assert block.index("git cherry-pick") < block.index('"HEAD:$REPRO_TEST"')
    assert "git cherry-pick --abort" in block and "why=" in block
    assert 'onto="origin/$DEFAULT"' in block


def test_the_workflows_guard_reads_only_the_agents_own_commits():
    run = next(s for s in JOBS["apply"]["steps"] if s.get("id") == "applied")["run"]
    assert 'git log --first-parent --no-merges --no-renames --format= --name-only "origin/$BRANCH..$new"' in run
    assert 'git diff --name-only "origin/$BRANCH" "$new"' not in run
