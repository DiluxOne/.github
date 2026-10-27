"""The autopilot's agent runs nothing in the background (#482): a run ends
when the agent stops and nothing tells it a background task finished, so
both of its steps leave out Monitor and background runs, and the work step
lets a command (`make pre-pr`) run as long as the step does."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def agent_step(job, step_id):
    wf = yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))
    return next(s for s in wf["jobs"][job]["steps"] if s.get("id") == step_id)


def test_no_monitor_and_no_background_runs_in_either_agent_step():
    for job, step_id in (("spec", "spec"), ("work", "work")):
        step = agent_step(job, step_id)
        assert step["env"]["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] == "1", job
        assert '--disallowedTools "Monitor"' in step["with"]["claude_args"], job


def test_a_command_in_the_work_may_run_as_long_as_the_step():
    step = agent_step("work", "work")
    assert int(step["env"]["BASH_MAX_TIMEOUT_MS"]) >= int(step["timeout-minutes"]) * 60_000
