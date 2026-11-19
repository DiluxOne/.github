"""#834: release scenario `bug-by-person-merges` ends OPEN. A person's Bug is
worked by the test repository's fixed change (kinds/engine-test/pack.yml),
which writes one file per criterion under scenarios/<scenario>/; G7
(autopilot.py decide) then finds "no test at the head" for it (G6), because
that file is not a test, so the autopilot's pull request never merges and the
issue it closes stays open. The fixed change's own pull request must merge by
policy when the issue is a plain, Normal Bug and the review is clean.
"""
import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def autopilot():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("autopilot_834", ROOT / "scripts" / "autopilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_fixed_changes_pull_request_for_a_persons_bug_merges_by_policy():
    ap = autopilot()
    bodies = yaml.safe_load((ROOT / "tests/release/scenarios.yml").read_text(encoding="utf-8"))["bodies"]
    pack = yaml.safe_load((ROOT / "kinds/engine-test/pack.yml").read_text(encoding="utf-8"))
    pattern = pack["fixed-change"]["file"]
    scenario, number = "bug-by-person-merges", 12
    prd = bodies["bug-not-reproduced"]
    path = ap.fixed_path(pattern, number, "C1", scenario)
    body = prd + "\n" + ap.fixed_spec(pattern, number, ["C1"], scenario)
    policy = ap.autonomy.merge(ap.autonomy.load(str(ROOT / "policy" / "autonomy.yml")), {})

    merges, why = ap.decide(policy, body, "low", "low", "false", "true", [path], [path], "", ap.BOT, ap.LANE,
                            issue_type="Bug", criteria_verdict={"C1": True})

    assert merges, f"the fixed change's pull request for a person's Bug does not merge by policy: {why}"
