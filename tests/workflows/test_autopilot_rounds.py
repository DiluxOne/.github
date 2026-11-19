"""The autopilot's fix rounds (#507): the policy allows five, and the gate in
the "may" step runs rounds 4 and 5 and hands round 6 to a person. Runs the
whole "may" step as the runner does (tests/workflows/steps.py) on a fix
round, with gh stood in and the engine's helpers answering "go on", the
policy's number read from policy/autonomy.yml."""
import json
from pathlib import Path

import pytest
import yaml

from steps import run, step

ROOT = Path(__file__).resolve().parents[2]

# The engine's helpers the step calls, stood in: each records its call,
# then answers ANSWERS[subcommand] (stdout, exit code), or runs the real
# script for a subcommand in REAL.
HELPER = """import json, os, sys
with open(os.environ["DX_CALLS"], "a") as f:
    f.write(json.dumps([os.path.basename(__file__), *sys.argv[1:]]) + "\\n")
sub = sys.argv[1] if len(sys.argv) > 1 else ""
if sub in {real!r}:
    os.execv(sys.executable, [sys.executable, {path!r}, *sys.argv[1:]])
out, code = {answers!r}.get(sub, ("", 0))
if out:
    print(out)
sys.exit(code)
"""


def helper(name, answers, real=()):
    return HELPER.format(real=set(real), path=str(ROOT / "scripts" / name), answers=answers)


def rounds():
    return yaml.safe_load((ROOT / "policy/autonomy.yml").read_text(encoding="utf-8"))["autopilot-rounds"]


def gate(tmp_path, round_):
    files = {
        # #741: no check of the pipeline failed (a review round), and the
        # comment at the cap is autopilot.py's own. #820: no newer run
        # superseded this one.
        ".dx-central/scripts/autopilot.py": helper("autopilot.py", {"lane": ("human-issue", 0), "checks-failed": ("", 1),
                                                                     "superseded": ("no newer run", 1)}, real=("rounds-spent",)),
        ".dx-central/scripts/receipts.py": helper("receipts.py", {"verify-prd": ("match", 0)}),
        ".dx-central/scripts/autonomy.py": helper("autonomy.py", {"policy": (json.dumps({"autopilot-rounds": rounds()}), 0)}),
    }
    gh = 'case "$*" in "pr view"*"--json labels"*) echo false ;; esac\n'
    ran = run(step("autopilot.yml", "may", job="prep"), tmp_path, central=False, files=files, stubs={"gh": gh},
              env={"MODE": "fix", "AS": "fix", "ISSUE": "7", "PR": "9", "ROUND": str(round_), "QUEUE": "false",
                   "RUN_HEAD": "", "DX_AUTOPILOT": ""})
    assert ran.code == 0, ran.stdout + ran.stderr
    return ran


def needs_human(ran):
    return ["pr", "edit", "9", "--repo", "o/r", "--add-label", "needs-human"] in ran.of("gh")


def test_the_policy_allows_five_rounds():
    assert rounds() == 5


@pytest.mark.parametrize("round_", [4, 5])
def test_a_fourth_and_a_fifth_round_run(tmp_path, round_):
    ran = gate(tmp_path, round_)
    assert ["policy"] in ran.of("autonomy.py")
    assert ran.output["go"] == "true"
    assert not needs_human(ran)
    assert not [c for c in ran.of("gh") if "comment" in c]


def test_no_sixth_round(tmp_path):
    ran = gate(tmp_path, 6)
    assert ran.output["go"] == "false"
    assert needs_human(ran)
    pr_comment = [c for c in ran.of("gh") if c[:3] == ["pr", "comment", "9"]]
    assert len(pr_comment) == 1 and "spent its 5 rounds" in pr_comment[0][-1]
