"""#804, C1: what the policy decided in a person's place is on the receipts,
never a label. auto-merge.yml writes a merge decision (scripts/receipts.py
merge-decision) where it once added `merged-by:policy`, before it enables
auto-merge, and withdraws one in force before it decides again."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
POLICY_LABELS = ("accepted-by:policy", "merged-by:policy")


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def step(job, name):
    return next(s for s in job["steps"] if s.get("name") == name)


def code(script):
    """The script without its comments."""
    return "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))


DECIDING = {
    "An autopilot pull request": "policy/autonomy.yml#lanes.$LANE.merge",
    "A revert pull request (G8)": "policy/autonomy.yml#lanes.platform.merge",
    "A release pull request": "policy/autonomy.yml#lanes.release.merge",
    "A sync run's pull request": "policy/autonomy.yml#lanes.$lane.merge",
}


def test_auto_merge_sets_no_policy_label():
    text = code((ROOT / ".github/workflows/auto-merge.yml").read_text(encoding="utf-8"))
    for label in POLICY_LABELS:
        assert label not in text, label


def test_each_policy_merge_is_decided_on_the_receipts_before_auto_merge():
    job = workflow("auto-merge.yml")["jobs"]["decide"]
    for name, rule in DECIDING.items():
        run = code(step(job, name)["run"])
        withdraw = run.index("DECIDED=withdrawn")
        assert "receipts.py\" merge-decision" in run[withdraw:].splitlines()[0], name
        # A withdrawal that fails stops the step: never a decision left in force.
        assert "exit 1" in run[withdraw:].splitlines()[1], name
        decide = run.index("DECIDED=policy")
        line = run[decide:].splitlines()[0]
        assert f'RULE="{rule}"' in line and "merge-decision" in line, (name, line)
        assert "|| true" not in line, name
        enable = run.index("--auto ")
        off = run.index("--disable-auto")
        assert off < withdraw < decide < enable, name
        # Every early "a person merges" exit comes after the withdrawal.
        for m in re.finditer(r'person "|A human merges this one', run):
            assert m.start() > withdraw, (name, m.group())
