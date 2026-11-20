"""#894: release scenario `bug-by-person-merges` fails again after #887.
G7 (`autopilot.py decide`) no longer asks `description_matches` of a pull
request of the test repository's fixed change alone, but G6 then stops it:
the review set C1 `met: false` because the only test is a marker with no
assertion, which is what the fixed change writes (one marker file per
criterion, kinds/engine-test/pack.yml `fixed-change.file`, written with no
model). A pull request whose only changed files are its fixed change's
files has its criteria met by construction: G7 does not hold it on the
review's criteria verdict. Any other changed file, any other repository,
or no files still needs the review to find every criterion met."""
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
    spec = importlib.util.spec_from_file_location("autopilot_894", ROOT / "scripts" / "autopilot.py")
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
    checks = [{"name": PIPELINE, "status": "completed", "conclusion": "success", "id": 1, "started_at": "2026-11-20T00:00:00Z",
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


def decide(ev, body, files, verdict):
    policy = ap.autonomy.merge(ap.autonomy.load(str(ROOT / "policy" / "autonomy.yml")), {})
    return ap.decide(policy, body, "low", "low", "false", "true", files, files, "", ap.BOT, ap.LANE,
                     issue_type="Bug", criteria_verdict=verdict, widening=[], **ev)


def test_the_fixed_changes_pull_request_merges_though_the_review_finds_no_criterion_met(tmp_path):
    body, path = fixed_body()
    merges, why = decide(evidence(tmp_path), body, [path], {"C1": False})
    assert merges, why
    assert "criteria met by construction" in why


def test_the_fixed_changes_pull_request_merges_with_no_verdict_from_the_review(tmp_path):
    body, path = fixed_body()
    merges, why = decide(evidence(tmp_path), body, [path], None)
    assert merges, why
    assert "criteria met by construction" in why


def test_another_changed_file_still_needs_the_reviews_verdict(tmp_path):
    body, path = fixed_body()
    merges, why = decide(evidence(tmp_path), body, [path, "README.md"], {"C1": False})
    assert not merges and why == "the review does not find C1 met (G6)"


def test_no_changed_files_still_needs_the_reviews_verdict(tmp_path):
    body, _ = fixed_body()
    merges, why = decide(evidence(tmp_path), body, [], {"C1": False})
    assert not merges and why == "the review does not find C1 met (G6)"


def test_elsewhere_the_same_file_still_needs_the_reviews_verdict(tmp_path):
    body, path = fixed_body()
    merges, why = decide(evidence(tmp_path, repo=f"{ap.org.ORG}/plugin"), body, [path], {"C1": False})
    assert not merges and why == "the review does not find C1 met (G6)"


def test_a_review_that_finds_it_met_keeps_the_usual_reason(tmp_path):
    body, path = fixed_body()
    merges, why = decide(evidence(tmp_path), body, [path], {"C1": True})
    assert merges and "by construction" not in why
