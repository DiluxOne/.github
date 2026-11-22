"""#943: a release scenario that does not test the review gets a fixed
answer in the test repository, with no model; one that tests it keeps the
model's review.

scripts/fixed-review.py decides it from the pull request's issue and
tests/release/scenarios.yml; claude-review.yml skips the model on its
`hit` and gives its answer to the verdict."""

import yaml

from steps import ROOT

ISSUE = ("<!-- dx-scenario: {sid} -->\n### Problem\n\nx\n\n### Acceptance criteria\n\n"
         "- C1: Given a, when b, then c.\n\n### Criticality\n\nNormal\n")


def test_c1_a_scenario_that_does_not_test_the_review_gets_no_model():
    import importlib.util
    spec = importlib.util.spec_from_file_location("fixed_review", ROOT / "scripts" / "fixed-review.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def read(*args):
        if args[1].endswith("pulls/7"):
            return {"body": "Closes #5"}
        return {"body": ISSUE.format(sid="claim-and-release")}

    env = {"FIXED": "scenarios/{scenario}/{n}.test.md", "REPO": "o/t", "PR": "7", "TITLE": "feat: a greeting",
           "FLOOR": "low", "SCENARIOS": str(ROOT / "tests" / "release" / "scenarios.yml")}
    hit, ans = mod.decide(env, read)
    assert hit is True
    assert ans["risk"] == "low" and ans["blocking"] is False and ans["findings"] == []
    assert [c["id"] for c in ans["criteria"]] == ["C1"]


def test_c2_a_scenario_that_tests_the_review_keeps_the_model():
    scen = yaml.safe_load((ROOT / "tests" / "release" / "scenarios.yml").read_text(encoding="utf-8"))["scenarios"]
    keep = {s["id"] for s in scen if s.get("review") == "model"}
    assert {"review-changes-asked", "review-replied", "settled-rerun", "low-risk-merges",
            "high-risk-waits", "merge-queue", "fork-without-secrets", "conventions-fix"} <= keep


def test_c1_the_model_step_skips_on_a_fixed_answer_and_the_verdict_reads_it():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "claude-review.yml").read_text(encoding="utf-8"))
    steps = {s.get("id"): s for s in wf["jobs"]["review"]["steps"] if s.get("id")}
    assert "steps.fixedrev.outputs.hit != 'true'" in steps["claude"]["if"]
    assert "steps.fixedrev.outputs.answer" in steps["verdict"]["env"]["OUT"]
    assert "steps.fixedrev.outputs.hit == 'true'" in steps["verify-task"]["if"]
    order = [s.get("id") for s in wf["jobs"]["review"]["steps"]]
    assert order.index("fixedrev") < order.index("claude")
