"""#928 C3: a failed check of the repository's own (one no fix round runs
again) whose job log shows a transient GitHub error (HTTP 5xx, a timeout)
is run again once, before anyone is mentioned: `waiting.py update` reads the
failed job's log, and on its first attempt runs it again, and the board
says the checks are running, mentioning nobody. A second attempt, a log
that is not transient, or a rerun the API refuses mentions the maintainer
as today. Runs `update` on the fixture pull request with gh stood in."""
import copy
import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REPO = "DiluxOne/diluxone-users-wordpress"
JOB = 44946869504
LOG_504 = "2026-11-21T20:40:01Z Run gh api graphql ...\n2026-11-21T20:40:31Z gh: HTTP 504: We couldn't respond to your request in time.\n##[error]Process completed with exit code 1.\n"
LOG_TEST = "FAILED tests/test_users.py::test_login - AssertionError: assert 401 == 200\n##[error]Process completed with exit code 1.\n"


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def own_check_failed():
    fx = json.loads((ROOT / "scripts/fixtures/waiting.json").read_text(encoding="utf-8"))
    pr = copy.deepcopy(next(p for p in fx["prs"] if p["title"] == "the autopilot's, only the repository's own check failed"))
    pr.pop("want", None)
    pr["state"] = "OPEN"
    pr["__typename"] = "PullRequest"
    for c in pr["commits"]["nodes"][-1]["commit"]["statusCheckRollup"]["contexts"]["nodes"]:
        c["databaseId"] = JOB if c["conclusion"] == "FAILURE" else JOB + 1
    return pr


def run_update(monkeypatch, log=LOG_504, attempt=1, refuse=False):
    waiting = load("waiting_c3_928", "waiting.py")
    calls = []

    def fake_gh(*args):
        a = [str(x) for x in args]
        calls.append(" ".join(a))
        if a[:2] == ["api", f"repos/{REPO}/actions/jobs/{JOB}/logs"]:
            return log
        if a[:2] == ["api", f"repos/{REPO}/actions/jobs/{JOB}"]:
            return json.dumps({"id": JOB, "run_id": 1, "run_attempt": attempt, "conclusion": "failure"})
        if a[:4] == ["api", "-X", "POST", f"repos/{REPO}/actions/jobs/{JOB}/rerun"]:
            if refuse:
                raise RuntimeError("gh: Resource not accessible by integration (HTTP 403)")
            return ""
        raise AssertionError(f"unexpected gh call: {a}")

    monkeypatch.setattr(waiting, "gh", fake_gh)
    put = []
    waits = waiting.update(REPO, 18, ["boss"], read=own_check_failed, put=lambda repo, number, item, w: put.append(w))
    return waiting, waits, calls


def reruns(calls):
    return [c for c in calls if c.startswith("api -X POST") and c.endswith(f"/actions/jobs/{JOB}/rerun")]


def test_c3_a_check_that_failed_on_http_504_runs_again_and_nobody_is_mentioned(monkeypatch):
    waiting, waits, calls = run_update(monkeypatch)
    assert len(reruns(calls)) == 1, calls
    assert waits["role"] == waiting.CHECKS, waits
    assert "who" not in waits
    assert "checks running" in waits["what"]


def test_c3_only_once_a_second_failure_mentions_the_maintainer(monkeypatch):
    waiting, waits, calls = run_update(monkeypatch, attempt=2)
    assert reruns(calls) == []
    assert waits["role"] == waiting.MAINTAINER and waits["who"] == ["boss"]


def test_c3_a_failure_that_is_not_transient_mentions_the_maintainer(monkeypatch):
    waiting, waits, calls = run_update(monkeypatch, log=LOG_TEST)
    assert reruns(calls) == []
    assert waits["role"] == waiting.MAINTAINER and waits["who"] == ["boss"]


def test_c3_a_rerun_the_api_refuses_falls_back_to_the_maintainer(monkeypatch):
    waiting, waits, calls = run_update(monkeypatch, refuse=True)
    assert len(reruns(calls)) == 1
    assert waits["role"] == waiting.MAINTAINER and waits["who"] == ["boss"]


def test_c3_the_rules_are_pure():
    waiting = load("waiting_c3_928_pure", "waiting.py")
    transient = getattr(waiting, "transient", None)
    rerun_plan = getattr(waiting, "rerun_plan", None)
    assert callable(transient) and callable(rerun_plan), "waiting.py has no transient or rerun_plan"
    for log in ("gh: HTTP 504", "HTTP 500: Internal Server Error", "gh: HTTP 502", "HTTP 503 Service Unavailable", "the operation timed out",
                "Error: timeout awaiting response", "connect ETIMEDOUT 140.82.112.6:443", "read: connection reset by peer"):
        assert transient(log), log
    for log in (LOG_TEST, "gh: HTTP 404: Not Found", "HTTP 422", "", None):
        assert not transient(log), log
    assert rerun_plan([(1, LOG_504)], {1: 1}) == [1]
    assert rerun_plan([(1, LOG_504)], {1: 2}) == []
    assert rerun_plan([(1, LOG_TEST)], {1: 1}) == []
    # Every failed check of its own transient on its first attempt, or none.
    assert rerun_plan([(1, LOG_504), (2, LOG_TEST)], {1: 1, 2: 1}) == []
    assert rerun_plan([(1, LOG_504), (2, LOG_504)], {1: 1}) == []
    assert rerun_plan([], {}) == []


def test_c3_the_query_reads_the_jobs_id_and_the_token_may_run_it_again():
    waiting = load("waiting_c3_928_wiring", "waiting.py")
    assert "... on CheckRun { name conclusion status databaseId }" in waiting.FIELDS
    steps = yaml.safe_load((ROOT / ".github/workflows/waiting-update.yml").read_text(encoding="utf-8"))
    token = next(s for s in steps["jobs"]["update"]["steps"] if "create-github-app-token" in str(s.get("uses")))
    assert token["with"].get("permission-actions") == "write", token
