"""The autopilot brings main into its branch (#549, #550, #561): the wiring
no script's --test can see, read from the workflow's file."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FLOWS = ROOT / ".github" / "workflows"
JOBS = yaml.safe_load((FLOWS / "autopilot.yml").read_text(encoding="utf-8"))["jobs"]


def step(job, sid):
    return next(s for s in JOBS[job]["steps"] if s.get("id") == sid)


def test_the_work_merges_main_before_the_agent_and_leaves_a_conflict_to_it():
    run = step("work", "task")["run"]
    names = [s.get("id") for s in JOBS["work"]["steps"]]
    assert names.index("task") < names.index("work")
    assert 'git merge -q --no-edit "origin/$DEFAULT"' in run
    # #561 C2: a conflict no longer leaves the branch as it is: the agent
    # merges main and resolves it, its prompt says so, before the prompt
    # goes out (a fix round's prompt already asks for it).
    assert "goes on from the branch as it is" not in run
    note = run.index('autopilot.py conflict-note "$DEFAULT" >> .dx-io/prompt.md')
    assert run.index("git merge --abort") < note < run.index("cat .dx-io/prompt.md")
    assert 'grep -q "Main does not merge cleanly" .dx-io/prompt.md' in run


def test_a_merge_into_main_sweeps_the_autopilot_pull_requests_with_no_persons_label():
    pipeline = yaml.safe_load((FLOWS / "pull-request.yml").read_text(encoding="utf-8"))
    on = pipeline.get("on", pipeline.get(True))
    assert on["push"]["branches"] == ["main"]
    job = pipeline["jobs"]["autopilot-sweep"]
    assert job["uses"] == "./.github/workflows/autopilot-sweep.yml"
    assert "github.event_name == 'push'" in job["if"] and job["with"]["repo"] == "${{ github.repository }}"
    sweep = yaml.safe_load((FLOWS / "autopilot-sweep.yml").read_text(encoding="utf-8"))
    on = sweep.get("on", sweep.get(True))
    assert {"schedule", "workflow_call", "workflow_dispatch"} <= set(on)
    run = sweep["jobs"]["sweep"]["steps"][-1]["run"]
    # next-step's own answer decides, through autopilot.py sweep; the bot
    # acts on it: update-branch for one behind, its own continue for one
    # in conflict, which the run's fix round merges and resolves.
    assert "python3 scripts/autopilot.py sweep" in run
    assert 'gh api -X PUT "repos/$repo/pulls/$n/update-branch"' in run
    assert 'gh issue edit "$issue" --repo "$repo" --add-label "autopilot:continue"' in run
    assert "mergeStateStatus" in run and "UNKNOWN" in run


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
