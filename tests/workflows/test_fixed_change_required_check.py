"""#860: release scenario `bug-by-person-merges` fails since #842. In the test
repository the autopilot's fixed change (kinds/engine-test/pack.yml
`fixed-change.file`) writes one file per criterion, scenarios/<scenario>/<n>.test.md,
which is the criterion's only test; the same pack lists `scenarios/**` among
its `not-tests`, so no required check runs it, and G7 (`autopilot.py decide`,
with `check_evidence` as the `decide` command passes it) never merges the
person's Normal Bug. That file is met by being written and changed by the
pull request, with no required check asked of it; any other test still needs
its required check green."""
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
    spec = importlib.util.spec_from_file_location("autopilot_860", ROOT / "scripts" / "autopilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ap = load()


def lines(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return str(path)


def evidence(tmp_path, title="fix: something failed once, accepted", repo=None):
    """The decide step's files, as auto-merge.yml writes them for the test
    repository: the head's required check green, the base's rules, the
    head's runs, and its review policy at the base (none)."""
    checks = [{"name": PIPELINE, "status": "completed", "conclusion": "success", "id": 1, "started_at": "2026-11-19T00:00:00Z",
               "check_suite": {"id": 40}}]
    rules = [{"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": PIPELINE}]}}]
    runs = [{"path": ".github/workflows/pull-request.yml", "check_suite_id": 40}]
    (tmp_path / "policy.yml").write_text("", encoding="utf-8")
    env = {"HEAD_CHECKS": lines(tmp_path / "head-checks", checks), "REQUIRED_CHECKS": lines(tmp_path / "required-checks", rules),
           "HEAD_RUNS": lines(tmp_path / "head-runs", runs), "TEST_FIRST_POLICY": str(tmp_path / "policy.yml"), "TITLE": title, "HEAD": SHA}
    repo = repo or f"{ap.org.ORG}/{ap.org.test_repo(ap.org.load())}"
    return ap.check_evidence(env, repo)


def fixed_body():
    bodies = yaml.safe_load((ROOT / "tests/release/scenarios.yml").read_text(encoding="utf-8"))["bodies"]
    pattern = ap.fixed_file(ap.org.load(), f"{ap.org.ORG}/{ap.org.test_repo(ap.org.load())}")
    assert pattern, "the test repository has a fixed change"
    return bodies["bug-not-reproduced"] + "\n" + ap.fixed_spec(pattern, NUMBER, ["C1"], SCENARIO), ap.fixed_path(pattern, NUMBER, "C1", SCENARIO)


def decide(ev, body, files):
    policy = ap.autonomy.merge(ap.autonomy.load(str(ROOT / "policy" / "autonomy.yml")), {})
    return ap.decide(policy, body, "low", "low", "false", "true", files, files, "", ap.BOT, ap.LANE,
                     issue_type="Bug", criteria_verdict={"C1": True}, widening=[], **ev)


def test_the_fixed_changes_pull_request_for_a_persons_bug_merges_by_policy(tmp_path):
    body, path = fixed_body()
    merges, why = decide(evidence(tmp_path), body, [path])
    assert merges, why
    assert "fixed change" in why


def test_the_fixed_file_must_still_be_in_the_pull_request(tmp_path):
    body, path = fixed_body()
    merges, why = decide(evidence(tmp_path), body, ["scenarios/other.md"])
    assert not merges and "no test at the head for C1" in why


def test_another_test_in_the_test_repository_still_needs_its_required_check(tmp_path):
    body, path = fixed_body()
    other = "tests/repro/test_issue_12.py"
    body = body.replace(f"C1 → {path}", f"C1 → {other}")
    merges, why = decide(evidence(tmp_path), body, [other])
    assert not merges and "C1:" in why and "(G6)" in why


def test_elsewhere_the_same_file_needs_a_required_check(tmp_path):
    body, path = fixed_body()
    merges, why = decide(evidence(tmp_path, repo=f"{ap.org.ORG}/plugin"), body, [path])
    assert not merges and f"no required check runs `{path}`" in why
