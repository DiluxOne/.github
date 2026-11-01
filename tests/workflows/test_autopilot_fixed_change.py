"""In the test repository the autopilot calls no model (#563,
kinds/engine-test/pack.yml `autopilot: fixed-change`): prep says so and
queues the fixed Spec, the spec and work jobs skip the model's steps there,
the work writes the fixed change instead, and each job's outcome is the one
of the step that ran."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def workflow():
    return yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))


def step(wf, job, step_id):
    return next(s for s in wf["jobs"][job]["steps"] if s.get("id") == step_id)


def test_prep_says_whether_the_change_is_fixed_and_queues_its_spec():
    wf = workflow()
    assert wf["jobs"]["prep"]["outputs"]["fixed"] == "${{ steps.task.outputs.fixed }}"
    run = step(wf, "prep", "task")["run"]
    assert "autopilot.py fixed)" in run and 'echo "fixed=true" >> "$GITHUB_OUTPUT"' in run
    assert "autopilot.py fixed spec" in run


def test_the_model_steps_are_skipped_for_the_fixed_change():
    wf = workflow()
    for job, step_id in (("spec", "spec"), ("work", "work")):
        assert step(wf, job, step_id)["if"] == "needs.prep.outputs.fixed != 'true'", job


def test_the_work_writes_the_fixed_change_instead():
    fixed = step(workflow(), "work", "fixed")
    assert fixed["if"] == "needs.prep.outputs.fixed == 'true'"
    assert fixed["run"].strip() == "python3 .dx-central/scripts/autopilot.py fixed work"
    assert {"DX_IO", "DX_BASE", "NUMBER", "MODE"} <= set(fixed["env"])
    names = [s.get("id") for s in workflow()["jobs"]["work"]["steps"]]
    assert names.index("task") < names.index("fixed") < names.index("work")


def test_each_job_reports_the_outcome_of_the_step_that_ran():
    wf = workflow()
    assert "needs.prep.outputs.fixed == 'true' && 'success'" in wf["jobs"]["spec"]["outputs"]["outcome"]
    assert "needs.prep.outputs.fixed == 'true' && steps.fixed.outcome || steps.work.outcome" in wf["jobs"]["work"]["outputs"]["outcome"]
