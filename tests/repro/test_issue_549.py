"""#549: the autopilot brings main into its branch (workflow wiring)."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
JOBS = yaml.safe_load((ROOT / ".github" / "workflows" / "autopilot.yml").read_text(encoding="utf-8"))["jobs"]

MERGE = re.compile(r"\bgit\b[^\n]*\bmerge\b(?!-)")


def test_the_work_merges_main_into_the_working_tree_before_the_agent_runs():
    steps = JOBS["work"]["steps"]
    agent = next(i for i, s in enumerate(steps) if s.get("id") == "work")
    before = "\n".join(s.get("run", "") for s in steps[:agent])
    assert MERGE.search(before), "no step merges main before Claude works"


def test_a_reproduced_bugs_draft_starts_from_current_main_with_the_test_on_top():
    step = next(s for s in JOBS["draft"]["steps"] if s.get("id") == "draft")
    run = step["run"]
    start = run.index('if [ "$LANE" = bugfix-reproduced ]')
    block = run[start:run.index("elif adopt=", start)]
    assert re.search(r"cherry-pick|rebase|\bmerge\b", block), "the branch starts at the reproduction's old base"
