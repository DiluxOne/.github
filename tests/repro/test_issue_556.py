"""#556: `autopilot:continue` on a ready autopilot pull request that conflicts
with main must reach the step that merges main into its branch, so the step
that decides what a continue runs (`autopilot.py next-step`, #561, which
folds in `continue-as`) has to be told whether the pull request conflicts. It reads the workflow as YAML and never
runs it.
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def step(name):
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "autopilot.yml").read_text(encoding="utf-8"))
    return next(s for s in wf["jobs"]["prep"]["steps"] if s.get("name") == name)


def test_a_continue_on_a_ready_pull_request_that_conflicts_with_main_is_told_of_the_conflict():
    run = step("What to work on")["run"]
    assert re.search(r"mergeStateStatus|mergeable", run), "the step never reads whether the pull request conflicts with main"
    assert "autopilot.py next-step" in run, "the step does not ask next-step what a continue runs"
    state = run.split("autopilot.py next-step")[0].rsplit("jq -n", 1)[-1]
    assert re.search(r"\bmerge: \(\$merge\b", state) and '--arg merge "$merge_state"' in state, \
        "next-step is given the draft flag, head and review record, but not the merge state"
