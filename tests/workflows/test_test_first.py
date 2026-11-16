"""The "Test first" check (#734, .github/workflows/test-first.yml,
scripts/test-first.py): a `fix` or `feat` pull request carries a test that
fails at its base and passes at its head; the check reads where tests are
and how they run from the repository's declaration (its kind's pack), and
runs each through the reproduction's sandboxes.

Each case builds a repository in `tmp_path` with real commits at a base and
a head, and drives `plan` and `run` as the workflow does."""
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TF = load("test-first")

# Where pytest is, for the command the fixture's way runs with no environment.
PYTEST_HOME = str(Path(pytest.__file__).resolve().parents[1])

POLICY = f"""repro:
  ways:
    py:
      layer: logic
      test: tests/repro/test_issue_{{n}}.py
      run: PYTHONPATH={PYTEST_HOME}:. PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider --rootdir=. -o junit_family=xunit1 --junitxml=build/j.xml {{test}}
      junit: build/j.xml
      minutes: 2
test-first:
  setup: []
  tests:
    - paths: ["tests/**/test_*.py"]
      way: py
  not-tests: ["tests/release/**", "tests/**/fixtures/**", "tests/**/expected/**"]
"""

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
TEST = ("import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parents[2]))\n"
        "from src.calc import add\n\n\ndef test_add_adds():\n    assert add(1, 2) == 3\n")


class Repo:
    def __init__(self, path):
        self.path = path
        self.git("init", "-q", ".")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.path, check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, files, message):
        for name, text in files.items():
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        self.git("add", "-A")
        self.git("-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-c", "user.name=t", "-c", "user.email=t@t",
                 "commit", "-qm", message)
        return self.git("rev-parse", "HEAD")


def make(tmp_path):
    (tmp_path / "repo").mkdir()
    return Repo(tmp_path / "repo")


def check(r, title, base, head, number=7):
    """plan, then run when it says so: (passed, message, plan, results)."""
    p = TF.plan(str(r.path), str(ROOT), title, base, head, "none-such", number)
    if p["result"] != "run":
        return p["result"] == "pass", p["message"], p, []
    ok, message, results = TF.run(str(r.path), str(ROOT), p["tests"], p["type"], base, head)
    return ok, message, p, results


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("DX_REPRO_UNCONFINED", "1")
    monkeypatch.setenv("REPO", "Acme/none-such")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return make(tmp_path)


@pytest.mark.parametrize("kind", ["fix", "feat"])
def test_c1_a_test_failing_at_the_base_and_passing_at_the_head_passes_and_is_named(fresh, kind):
    base = fresh.commit({".github/review-policy.yml": POLICY, "src/__init__.py": "", "src/calc.py": BUGGY}, "chore: base")
    head = fresh.commit({"src/calc.py": FIXED, "tests/unit/test_calc.py": TEST}, f"{kind}: add adds")
    ok, message, plan, results = check(fresh, f"{kind}: add adds", base, head)
    assert plan["result"] == "run", plan["message"]
    assert results == [{"test": "tests/unit/test_calc.py", "base": "reproduced", "head": "passed"}]
    assert ok, message
    assert message == "Test first: `tests/unit/test_calc.py` fails at the base and passes at the head."


def test_c1_the_cli_writes_the_verdict_to_the_job_summary(fresh, tmp_path, monkeypatch):
    base = fresh.commit({".github/review-policy.yml": POLICY, "src/__init__.py": "", "src/calc.py": BUGGY}, "chore: base")
    head = fresh.commit({"src/calc.py": FIXED, "tests/unit/test_calc.py": TEST}, "fix: add adds")
    summary = tmp_path / "summary.md"
    env = {**os.environ, "DIR": str(fresh.path), "CENTRAL": str(ROOT), "TITLE": "fix: add adds", "BASE": base, "HEAD": head,
           "NUMBER": "7", "GITHUB_STEP_SUMMARY": str(summary)}
    planned = subprocess.run(["python3", str(ROOT / "scripts" / "test-first.py"), "plan"], env=env, capture_output=True, text=True)
    assert planned.returncode == 0, planned.stdout + planned.stderr
    tests = next(line[len("tests="):] for line in planned.stdout.splitlines() if line.startswith("tests="))
    ran = subprocess.run(["python3", str(ROOT / "scripts" / "test-first.py"), "run"], env={**env, "TESTS": tests, "TYPE": "fix"},
                         capture_output=True, text=True)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    said = summary.read_text(encoding="utf-8")
    assert "`tests/unit/test_calc.py` fails at the base and passes at the head" in said
    assert "| `tests/unit/test_calc.py` | reproduced | passed |" in said


@pytest.mark.parametrize("kind", ["fix", "feat", "fix!", "feat!"])
def test_c2_a_fix_or_feat_with_no_added_or_changed_test_fails_saying_the_test_is_missing(fresh, kind):
    base = fresh.commit({".github/review-policy.yml": POLICY, "src/__init__.py": "", "src/calc.py": BUGGY}, "chore: base")
    head = fresh.commit({"src/calc.py": FIXED, "README.md": "adds\n"}, f"{kind}: add adds")
    ok, message, plan, results = check(fresh, f"{kind}: add adds", base, head)
    assert not ok and plan["result"] == "fail"
    assert results == [] and plan["tests"] == []
    assert message.startswith("A test that fails before the change is missing: ")
    # Where tests go, so the author knows what to write.
    assert "`tests/**/test_*.py`" in message


def test_c2_a_deleted_test_is_no_test(fresh):
    base = fresh.commit({".github/review-policy.yml": POLICY, "src/__init__.py": "", "src/calc.py": BUGGY, "tests/unit/test_calc.py": TEST},
                        "chore: base")
    fresh.git("rm", "-q", "tests/unit/test_calc.py")
    head = fresh.commit({"src/calc.py": FIXED}, "fix: add adds")
    ok, message, _, _ = check(fresh, "fix: add adds", base, head)
    assert not ok and message.startswith("A test that fails before the change is missing: ")


def test_c2_the_cli_fails_the_plan_with_the_message(fresh):
    base = fresh.commit({".github/review-policy.yml": POLICY, "src/__init__.py": "", "src/calc.py": BUGGY}, "chore: base")
    head = fresh.commit({"src/calc.py": FIXED}, "feat: add adds")
    env = {**os.environ, "DIR": str(fresh.path), "CENTRAL": str(ROOT), "TITLE": "feat: add adds", "BASE": base, "HEAD": head}
    planned = subprocess.run(["python3", str(ROOT / "scripts" / "test-first.py"), "plan"], env=env, capture_output=True, text=True)
    assert planned.returncode == 1
    assert "result=fail" in planned.stdout.splitlines()
    assert "::error::A test that fails before the change is missing: " in planned.stdout


def test_c2_a_feat_whose_test_passes_at_the_base_fails_as_missing():
    ok, message = TF.verdict("feat", [{"test": "tests/unit/test_x.py", "base": "passed", "head": "passed"}])
    assert not ok and message.startswith("A test that fails before the change is missing: ")


def test_c3_a_fix_whose_added_test_also_passes_at_the_base_fails_saying_it_does_not_show_the_bug(fresh):
    base = fresh.commit({".github/review-policy.yml": POLICY, "src/__init__.py": "", "src/calc.py": BUGGY}, "chore: base")
    # A test of what the bug does not touch: it passes before the fix too.
    beside = TEST.replace("assert add(1, 2) == 3", "assert add(0, 0) == 0")
    head = fresh.commit({"src/calc.py": FIXED, "tests/unit/test_calc.py": beside}, "fix: add adds")
    ok, message, plan, results = check(fresh, "fix: add adds", base, head)
    assert plan["result"] == "run"
    assert results == [{"test": "tests/unit/test_calc.py", "base": "passed", "head": "passed"}]
    assert not ok
    assert message.startswith("The test does not show the bug: `tests/unit/test_calc.py` also passes at the base")


def test_c3_a_fix_whose_test_only_breaks_at_the_base_is_named_the_same_way(fresh):
    base = fresh.commit({".github/review-policy.yml": POLICY, "src/__init__.py": "", "src/calc.py": BUGGY}, "chore: base")
    # It imports what the fix adds: at the base it breaks, it fails no assertion.
    breaks = TEST.replace("from src.calc import add", "from src.calc import add, ADDS")
    head = fresh.commit({"src/calc.py": FIXED + "ADDS = True\n", "tests/unit/test_calc.py": breaks}, "fix: add adds")
    ok, message, _, results = check(fresh, "fix: add adds", base, head)
    assert results == [{"test": "tests/unit/test_calc.py", "base": "broken", "head": "passed"}]
    assert not ok and message.startswith("The test does not show the bug: `tests/unit/test_calc.py`")


def test_c3_a_test_that_fails_at_the_head_fails_the_check_naming_it(fresh):
    base = fresh.commit({".github/review-policy.yml": POLICY, "src/__init__.py": "", "src/calc.py": BUGGY}, "chore: base")
    head = fresh.commit({"tests/unit/test_calc.py": TEST}, "fix: add adds")
    ok, message, _, results = check(fresh, "fix: add adds", base, head)
    assert results == [{"test": "tests/unit/test_calc.py", "base": "reproduced", "head": "reproduced"}]
    assert not ok and "`tests/unit/test_calc.py` does not pass at the head" in message


def test_c3_a_test_that_could_not_run_never_passes():
    ok, message = TF.verdict("fix", [{"test": "t.py", "base": "limit", "head": "passed"}])
    assert not ok and "could not run" in message
