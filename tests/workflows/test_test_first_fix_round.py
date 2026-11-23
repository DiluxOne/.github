"""A failed "test-first / Test first" on an autopilot pull request gets the
autopilot's fix round (#972), as a failed conventions, review or security
gate job does: the round reads the failed jobs' log, which carries the
check's own summary (the table of each test at the base and at the head,
then its message), and its prompt says how a test-first failure is fixed.
Every lookup goes through getattr, so that at the base, where none of it
exists, each test fails on an assertion (#845)."""
import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


autopilot = load("autopilot_972", "autopilot.py")

# What test-first.py run prints before it fails, as `gh run view --log-failed` gives it.
SUMMARY = """| test | base | head |
|---|---|---|
| tests/workflows/test_docs_check.py | broken | passed |

::error::A test that fails before the change is missing: tests/workflows/test_docs_check.py breaks there without failing an assertion"""

JOBS = [
    {"id": 1, "name": "test-first / Test first (plan)", "conclusion": "success", "html_url": "https://x/1"},
    {"id": 2, "name": "test-first / Test first (the tests, no secrets)", "conclusion": "failure", "html_url": "https://x/2"},
    {"id": 3, "name": "test-first / Test first", "conclusion": "failure", "html_url": "https://x/3"},
    {"id": 4, "name": "my-own / Lint", "conclusion": "failure", "html_url": "https://x/4"},
]


def test_the_round_selects_the_failed_test_first_jobs():
    failed = autopilot.checks_failed(JOBS, [], "head")
    assert [j["name"] for j in failed] == ["test-first / Test first (the tests, no secrets)", "test-first / Test first"]


def test_the_round_reads_the_check_summary():
    failed = autopilot.checks_failed(JOBS, [], "head")
    assert failed, "no test-first job selected"
    text = autopilot.checks_log_text(8, [(j, SUMMARY) for j in failed])
    assert "## test-first / Test first (https://x/3)" in text
    assert "| tests/workflows/test_docs_check.py | broken | passed |" in text and "A test that fails before the change is missing" in text


def test_the_fix_prompt_carries_the_test_first_note():
    note = getattr(autopilot, "test_first_note", None)
    assert callable(note), "autopilot.test_first_note is missing"
    failed = autopilot.checks_failed(JOBS, [], "head")
    text = autopilot.checks_log_text(8, [(j, SUMMARY) for j in failed])
    said = note(text)
    assert "broken" in said and "assertion" in said and "Never weaken or delete" in said
    assert note(autopilot.checks_log_text(8, [({"name": "conventions / Conventions"}, "x")])) == ""
    prompt = autopilot.prompt_fix("o/r", "8", 1, 3, checks=True, failed=text)
    assert said in prompt
    assert said not in autopilot.prompt_fix("o/r", "8", 1, 3, checks=True)


def test_autopilot_fix_starts_on_a_failed_test_first():
    for path in (".github/workflows/pull-request.yml", ".github/workflows/org-pull-request.yml", "workflow-templates/test-pull-request.yml"):
        job = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))["jobs"]["autopilot-fix"]
        cond = " ".join(str(job["if"]).split())
        assert "test-first" in job["needs"], path
        assert "needs.test-first.result == 'failure'" in cond, path
        assert job["with"]["mode"] == "fix", path
