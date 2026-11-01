"""#575: a delegated lane's sub-issue that has no seal (its repository ran
nothing when dilux-bot opened it) is sealed by the may-it-run step, not sent
back to a maintainer to be accepted again."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def may_it_run_script():
    wf = yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))
    scripts = [
        step["run"]
        for job in wf["jobs"].values()
        for step in job.get("steps", [])
        if "receipts.py verify-prd" in step.get("run", "")
    ]
    assert len(scripts) == 1
    return scripts[0]


def test_an_unsealed_delegated_sub_issue_is_sealed_instead_of_sent_back_to_a_person():
    script = may_it_run_script()
    verify = script.index("receipts.py verify-prd")
    refusal = script.index("the issue's PRD is not the one sealed when it was accepted")
    between = script[verify:refusal]
    assert "unsealed" in between and "delegated" in between
    assert "receipts.py seal-prd" in between
