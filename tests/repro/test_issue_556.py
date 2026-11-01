"""#556: `autopilot:continue` on a ready autopilot pull request that conflicts
with main must reach the step that merges main into its branch, so the step
that decides what a continue runs (`autopilot.py continue-as`) has to be told
whether the pull request conflicts. It reads the workflow as YAML and never
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
    line = next(l for l in run.splitlines() if "autopilot.py continue-as" in l)
    assert re.search(r"(?i)\b\w*(merge|dirty|conflict)\w*=", line), \
        "continue-as is given the draft flag, head and review record, but not the merge state"
