"""#842 C2: when G7 decides, a criterion whose Spec names a test is met only
when that test file is in the pull request and the required check that
runs it concluded success at the head.

Which check runs a test is the `test-first:` declaration's data: an entry
of `tests` may name its `check:`; one that names none is run by "test-first
/ Test first", for a `fix` or `feat` pull request only."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
FLOWS = ROOT / ".github" / "workflows"
SCRIPTS = "Scripts (self-tests)"
TEST_FIRST = "test-first / Test first"
REQUIRED = [SCRIPTS, TEST_FIRST]
SHA = "abc1234"


def load(name):
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ap = load("autopilot")

PRD = """### Problem

The gate passes red.

### Scope

- The gate.

### Out of scope

- Nothing.

### Acceptance criteria

- C1: Given a red check, when it is ready, then it cannot merge.

### Criticality

Normal
"""
SPEC = PRD + """
### Spec: approach

A ruleset.

### Spec: files

- scripts/x.py

### Spec: tests

- C1 → tests/workflows/test_gate.py
"""
TEST = "tests/workflows/test_gate.py"
HEAD = {"scripts/x.py", TEST}
DECL = {"setup": [], "not-tests": ["tests/**/fixtures/**"],
        "tests": [{"paths": ["tests/workflows/test_*.py"], "way": "python", "check": SCRIPTS},
                  {"paths": ["tests/unit/test_*.py"], "way": "python"}]}


def evidence(checks, required=REQUIRED, decl=DECL, pr_type="fix", head=HEAD, changed=HEAD, body=SPEC):
    return ap.criteria_evidence(body, set(head), set(changed), checks=checks, required=required, decl=decl, pr_type=pr_type)


def test_met_when_the_test_is_in_the_pull_request_and_its_required_check_succeeded():
    assert evidence({SCRIPTS: "success"}) == []


@pytest.mark.parametrize("conclusion", ["failure", "pending", "skipped", "neutral", "cancelled", "timed_out", "action_required", None])
def test_not_met_when_its_check_did_not_succeed(conclusion):
    assert evidence({SCRIPTS: conclusion}) == ["C1"]


def test_not_met_when_its_check_did_not_run_at_the_head():
    assert evidence({TEST_FIRST: "success"}) == ["C1"]
    assert evidence({}) == ["C1"]


def test_not_met_when_the_check_that_runs_it_is_not_required():
    assert evidence({SCRIPTS: "success"}, required=[TEST_FIRST]) == ["C1"]
    assert evidence({SCRIPTS: "success"}, required=[]) == ["C1"]


def test_not_met_when_the_test_is_not_in_the_pull_request():
    assert evidence({SCRIPTS: "success"}, changed={"scripts/x.py"}) == ["C1"]
    assert evidence({SCRIPTS: "success"}, head={"scripts/x.py"}, changed={"scripts/x.py"}) == ["C1"]


UNIT = SPEC.replace(TEST, "tests/unit/test_gate.py")
UNIT_HEAD = {"scripts/x.py", "tests/unit/test_gate.py"}


@pytest.mark.parametrize("kind", ["fix", "feat"])
def test_an_entry_with_no_check_is_run_by_test_first_for_a_fix_or_a_feature(kind):
    assert evidence({TEST_FIRST: "success"}, pr_type=kind, head=UNIT_HEAD, changed=UNIT_HEAD, body=UNIT) == []
    assert evidence({TEST_FIRST: "failure", SCRIPTS: "success"}, pr_type=kind, head=UNIT_HEAD, changed=UNIT_HEAD, body=UNIT) == ["C1"]


@pytest.mark.parametrize("kind", ["chore", "refactor", "docs", ""])
def test_an_entry_with_no_check_proves_nothing_for_another_type(kind):
    assert evidence({TEST_FIRST: "success", SCRIPTS: "success"}, pr_type=kind, head=UNIT_HEAD, changed=UNIT_HEAD, body=UNIT) == ["C1"]


def test_a_test_in_no_entry_or_among_the_not_tests_proves_nothing():
    other = SPEC.replace(TEST, "tests/other/test_gate.py")
    files = {"scripts/x.py", "tests/other/test_gate.py"}
    assert evidence({SCRIPTS: "success", TEST_FIRST: "success"}, pr_type="chore", head=files, changed=files, body=other) == ["C1"]
    fixture = SPEC.replace(TEST, "tests/workflows/fixtures/test_gate.py")
    files = {"scripts/x.py", "tests/workflows/fixtures/test_gate.py"}
    assert evidence({SCRIPTS: "success", TEST_FIRST: "success"}, head=files, changed=files, body=fixture) == ["C1"]


def test_no_declaration_proves_nothing():
    assert evidence({SCRIPTS: "success", TEST_FIRST: "success"}, decl=None) == ["C1"]


# G7: the decision, and the reason it gives.

POLICY = {"autopilot": True, "lanes": {ap.LANE: {"enabled": True, "merge": {"max-risk": "high", "max-complexity": "high"}}}}


def decide(checks, required=REQUIRED):
    return ap.decide(POLICY, SPEC, "low", "low", "false", "true", sorted(HEAD), sorted(HEAD), "",
                     head_checks=checks, required_checks=required, decl=DECL, pr_type="fix", head_sha=SHA)


def test_g7_merges_only_on_the_check_that_passed_and_says_which_one_did_not():
    assert decide({SCRIPTS: "success"})[0] is True
    ok, why = decide({SCRIPTS: None})
    assert ok is False and f"C1: `{SCRIPTS}` is pending at {SHA}" in why
    ok, why = decide({SCRIPTS: "failure"})
    assert ok is False and f"C1: `{SCRIPTS}` concluded failure at {SHA}" in why
    ok, why = decide({SCRIPTS: "success"}, required=[TEST_FIRST])
    assert ok is False and f"C1: `{SCRIPTS}` is not a required check" in why


def test_the_latest_run_of_each_check_at_the_head_counts():
    rows = [{"name": SCRIPTS, "status": "completed", "conclusion": "failure", "id": 1, "started_at": "2026-01-01T00:00:00Z"},
            {"name": SCRIPTS, "status": "completed", "conclusion": "success", "id": 2, "started_at": "2026-01-01T01:00:00Z"},
            {"name": TEST_FIRST, "status": "in_progress", "conclusion": None, "id": 3, "started_at": "2026-01-01T01:00:00Z"}]
    assert ap.head_checks(rows) == {SCRIPTS: "success", TEST_FIRST: "pending"}


def test_the_required_checks_are_the_rules_contexts_and_the_jobs_of_a_required_workflow():
    rules = [{"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": SCRIPTS}]}},
             {"type": "workflows", "parameters": {"workflows": [{"path": ".github/workflows/org-pull-request.yml", "ref": "refs/tags/v7"}]}},
             {"type": "deletion"}]
    runs = [{"path": ".github/workflows/org-pull-request.yml", "check_suite_id": 40},
            {"path": ".github/workflows/other.yml", "check_suite_id": 41}]
    rows = [{"name": TEST_FIRST, "check_suite": {"id": 40}}, {"name": "lint", "check_suite": {"id": 41}}]
    assert ap.required_of(rules, runs, rows) == sorted([SCRIPTS, TEST_FIRST])
    assert ap.required_of([], runs, rows) == []


# The data: the declaration's `check:` and the wiring of G7's reads.

def test_this_repository_says_its_self_tests_run_its_workflow_tests():
    policy = yaml.safe_load((ROOT / ".github/review-policy.yml").read_text(encoding="utf-8"))
    entry = next(e for e in policy["test-first"]["tests"] if "tests/workflows/test_*.py" in e["paths"])
    assert entry.get("check") == SCRIPTS
    tf = load("test-first")
    decl = tf.merged(policy["test-first"])
    assert tf.problems(decl, {"python": {}}) == []
    bad = tf.merged({"tests": [{"paths": ["t/*.py"], "way": "python", "check": ""}]})
    assert tf.problems(bad, {"python": {}}) == ["test-first.tests[0].check: the name of the required check that runs these tests"]
    assert ap.check_of(decl, "tests/workflows/test_gate.py", "chore") == SCRIPTS


def step_env(name):
    steps = yaml.safe_load((FLOWS / "auto-merge.yml").read_text(encoding="utf-8"))["jobs"]["decide"]["steps"]
    return next(s for s in steps if s.get("name") == name)


def test_g7_reads_the_heads_checks_and_the_bases_required_ones():
    wf = yaml.safe_load((FLOWS / "auto-merge.yml").read_text(encoding="utf-8"))
    assert wf["jobs"]["decide"]["permissions"]["checks"] == "read"
    run = step_env("An autopilot pull request")["run"]
    assert "commits/$HEAD/check-runs" in run and "rules/branches/" in run
    assert "HEAD_CHECKS=" in run and "REQUIRED_CHECKS=" in run


@pytest.mark.parametrize("name", ["pull-request.yml", "org-pull-request.yml", "pull-request-edited.yml"])
def test_the_decision_waits_for_test_first_and_may_read_the_checks(name):
    job = yaml.safe_load((FLOWS / name).read_text(encoding="utf-8"))["jobs"]["auto-merge"]
    needs = job["needs"] if isinstance(job["needs"], list) else [job["needs"]]
    assert "test-first" in needs and "review" in needs
    assert job["permissions"]["checks"] == "read"


def test_the_template_is_job_for_job_with_the_pipeline():
    job = yaml.safe_load((ROOT / "workflow-templates/test-pull-request.yml").read_text(encoding="utf-8"))["jobs"]["auto-merge"]
    assert "test-first" in job["needs"] and job["permissions"]["checks"] == "read"
