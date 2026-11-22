"""#946: an issue a release scenario opened in the test repository is
triaged with no model; anywhere else, the model triages as before.

scripts/fixed-triage.py decides it from the issue's `dx-scenario` mark and
tests/release/scenarios.yml; issue-triage.yml skips "Classify" on its `hit`
and gives its answer to the verdict and to the act step."""
import importlib.util

import yaml

from steps import ROOT

SCENARIOS = str(ROOT / "tests" / "release" / "scenarios.yml")


def mod():
    path = ROOT / "scripts" / "fixed-triage.py"
    assert path.exists(), "no scripts/fixed-triage.py"
    spec = importlib.util.spec_from_file_location("fixed_triage", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_c1_a_scenarios_issue_gets_no_model():
    m = mod()
    env = {"FIXED": "scenarios/{scenario}/{n}.test.md", "SCENARIOS": SCENARIOS, "REPLY": "Thanks!"}
    hit, ans = m.decide(dict(env, TITLE="fix: the greeting says helo", BODY="<!-- dx-scenario: bug-reproduced -->\nx"))
    assert hit is True and ans["category"] == "bug_unconfirmed" and ans["layer"] == "logic"
    hit, ans = m.decide(dict(env, TITLE="feat: a greeting", BODY="<!-- dx-scenario: issue-complete -->\nx"))
    assert hit is True and ans["category"] == "enhancement"


def test_c2_no_mark_or_outside_the_test_repository_keeps_the_model():
    m = mod()
    env = {"FIXED": "scenarios/{scenario}/{n}.test.md", "SCENARIOS": SCENARIOS}
    assert m.decide(dict(env, TITLE="feat: x", BODY="a person's issue")) == (False, None)
    assert m.decide(dict(env, FIXED="", TITLE="feat: x", BODY="<!-- dx-scenario: issue-complete -->")) == (False, None)


def test_c1_classify_skips_on_a_fixed_answer_and_the_verdict_reads_it():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "issue-triage.yml").read_text(encoding="utf-8"))
    steps = {s.get("id"): s for s in wf["jobs"]["triage"]["steps"] if s.get("id")}
    assert "fixedtri" in steps, "no fixed triage step"
    assert "steps.fixedtri.outputs.hit != 'true'" in steps["claude"]["if"]
    assert "steps.fixedtri.outputs.answer" in steps["verdict"]["env"]["OUT"]
    order = [s.get("id") for s in wf["jobs"]["triage"]["steps"]]
    assert order.index("fixedtri") < order.index("claude")
