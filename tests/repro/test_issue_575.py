"""#575: a delegated lane's sub-issue that has no seal (its repository ran
nothing when dilux-bot opened it) is sealed by the may-it-run step, not sent
back to a maintainer to be accepted again."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def jobs():
    return yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))["jobs"]


def may_it_run_script():
    return next(step["run"] for step in jobs()["prep"]["steps"] if step.get("id") == "may")


def test_an_unsealed_delegated_sub_issue_is_sealed_instead_of_sent_back_to_a_person():
    script = may_it_run_script()
    verify = script.index("receipts.py verify-prd")
    refusal = script.index("the issue's PRD is not the one sealed when it was accepted")
    between = script[verify:refusal]
    assert "unsealed" in between and "delegated" in between
    # #763: the seal job seals it, in the receipts queue, before anything
    # else starts; what prep read is what it seals.
    assert "seal=prd" in between and "seal-sha=" in between
    seal = next(step["run"] for step in jobs()["seal"]["steps"] if "receipts.py seal-prd" in step.get("run", ""))
    assert seal.index('"$SEAL_SHA"') < seal.index("receipts.py seal-prd") < seal.index("receipts.py verify-prd")
    assert 'ACCEPTED_BY="policy (lane delegated)"' in seal
    assert "needs.prep.outputs.seal == 'prd'" in jobs()["seal"]["if"]
