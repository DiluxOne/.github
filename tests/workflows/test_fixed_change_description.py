"""#887: release scenario `bug-by-person-merges` fails in its `expect`
(state CLOSED). The review of the test repository's fixed change (one
marker file per criterion, kinds/engine-test/pack.yml `fixed-change.file`,
written with no model) judged it as a real fix and set
`description_matches` false, so G7 (`autopilot.py decide`) never merged it.
A pull request whose only changed files are its fixed change's files
matches its description by construction: G7 does not hold it on the
review's `description_matches`. Any other changed file, or any other
repository, still needs the description to match."""
import importlib.util
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCENARIO, NUMBER, SHA = "bug-by-person-merges", 12, "abc1234"
PIPELINE = "pipeline"


def load():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("autopilot_887", ROOT / "scripts" / "autopilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ap = load()


def lines(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return str(path)


def evidence(tmp_path, repo=None):
    """The decide step's files, as auto-merge.yml writes them for the test
    repository: the head's required check green, the base's rules, the
    head's runs, and its review policy at the base (none)."""
    checks = [{"name": PIPELINE, "status": "completed", "conclusion": "success", "id": 1, "started_at": "2026-11-19T00:00:00Z",
               "check_suite": {"id": 40}}]
    rules = [{"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": PIPELINE}]}}]
    runs = [{"path": ".github/workflows/pull-request.yml", "check_suite_id": 40}]
    (tmp_path / "policy.yml").write_text("", encoding="utf-8")
    env = {"HEAD_CHECKS": lines(tmp_path / "head-checks", checks), "REQUIRED_CHECKS": lines(tmp_path / "required-checks", rules),
           "HEAD_RUNS": lines(tmp_path / "head-runs", runs), "TEST_FIRST_POLICY": str(tmp_path / "policy.yml"),
           "TITLE": "fix: a reader saw a misspelt word one morning", "HEAD": SHA}
    repo = repo or f"{ap.org.ORG}/{ap.org.test_repo(ap.org.load())}"
    return ap.check_evidence(env, repo)


def fixed_body():
    bodies = yaml.safe_load((ROOT / "tests/release/scenarios.yml").read_text(encoding="utf-8"))["bodies"]
    pattern = ap.fixed_file(ap.org.load(), f"{ap.org.ORG}/{ap.org.test_repo(ap.org.load())}")
    assert pattern, "the test repository has a fixed change"
    return bodies[SCENARIO] + "\n" + ap.fixed_spec(pattern, NUMBER, ["C1"], SCENARIO), ap.fixed_path(pattern, NUMBER, "C1", SCENARIO)


def decide(ev, body, files, description_ok="false"):
    policy = ap.autonomy.merge(ap.autonomy.load(str(ROOT / "policy" / "autonomy.yml")), {})
    return ap.decide(policy, body, "low", "low", "false", description_ok, files, files, "", ap.BOT, ap.LANE,
                     issue_type="Bug", criteria_verdict={"C1": True}, widening=[], **ev)


def test_the_fixed_changes_pull_request_merges_though_the_review_says_the_description_does_not_match(tmp_path):
    body, path = fixed_body()
    merges, why = decide(evidence(tmp_path), body, [path])
    assert merges, why
    assert "by construction" in why


def test_another_changed_file_still_needs_the_description_to_match(tmp_path):
    body, path = fixed_body()
    merges, why = decide(evidence(tmp_path), body, [path, "README.md"])
    assert not merges and why == "the description does not match the code"


def test_no_changed_files_still_needs_the_description_to_match(tmp_path):
    body, _ = fixed_body()
    merges, why = decide(evidence(tmp_path), body, [])
    assert not merges and why == "the description does not match the code"


def test_elsewhere_the_same_file_still_needs_the_description_to_match(tmp_path):
    body, path = fixed_body()
    merges, why = decide(evidence(tmp_path, repo=f"{ap.org.ORG}/plugin"), body, [path])
    assert not merges and why == "the description does not match the code"


def test_a_matching_description_keeps_the_usual_reason(tmp_path):
    body, path = fixed_body()
    merges, why = decide(evidence(tmp_path), body, [path], "true")
    assert merges and "by construction" not in why
