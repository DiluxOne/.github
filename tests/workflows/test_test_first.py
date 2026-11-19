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


def test_845_c1_a_feat_whose_only_new_test_errors_at_the_base_does_not_count_as_failing_first(fresh):
    base = fresh.commit({".github/review-policy.yml": POLICY, "src/__init__.py": ""}, "chore: base")
    # The module is new: at the base the test's import fails (ImportError), no assertion ran.
    head = fresh.commit({"src/calc.py": FIXED, "tests/unit/test_calc.py": TEST}, "feat: add adds")
    ok, message, plan, results = check(fresh, "feat: add adds", base, head)
    assert plan["result"] == "run", plan["message"]
    assert results == [{"test": "tests/unit/test_calc.py", "base": "broken", "head": "passed"}]
    assert not ok, message
    assert message.startswith("A test that fails before the change is missing: `tests/unit/test_calc.py`")
    # What to do about it: assert on what the feature does, so the base fails an assertion.
    assert "breaks there without failing an assertion" in message
    assert "asserts on what it runs" in message


def test_845_c1_a_feat_whose_test_fails_an_assertion_at_the_base_still_passes():
    ok, message = TF.verdict("feat", [{"test": "tests/unit/test_x.py", "base": "reproduced", "head": "passed"}])
    assert ok and message == "Test first: `tests/unit/test_x.py` fails at the base and passes at the head."


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


@pytest.mark.parametrize("edited", ["tests/release/scenarios.yml", "tests/unit/fixtures/test_input.py", "tests/unit/expected/test_out.py"])
def test_c4_a_fix_that_only_edits_a_scenario_a_fixture_or_an_expected_output_fails_as_c2(fresh, edited):
    base = fresh.commit({".github/review-policy.yml": POLICY, "src/__init__.py": "", "src/calc.py": BUGGY}, "chore: base")
    head = fresh.commit({"src/calc.py": FIXED, edited: "scenarios: []\n"}, "fix: add adds")
    ok, message, plan, results = check(fresh, "fix: add adds", base, head)
    assert not ok and plan["result"] == "fail" and results == []
    assert message.startswith("A test that fails before the change is missing: ")


@pytest.mark.parametrize("edited", ["tests/release/scenarios.yml", "tests/workflows/fixtures/thing/test_x.py", "scripts/fixtures/x/test_y.py",
                                    "tests/examples/test_logic.py", "evals/cases/test_case.py"])
def test_c4_this_repositorys_declaration_never_counts_a_scenario_or_a_fixture(fresh, edited):
    # This repository's own `test-first:` (#779: a fix that edited
    # tests/release/scenarios.yml alone).
    policy = (ROOT / ".github" / "review-policy.yml").read_text(encoding="utf-8")
    base = fresh.commit({".github/review-policy.yml": policy, "scripts/x.py": "A = 1\n"}, "chore: base")
    head = fresh.commit({"scripts/x.py": "A = 2\n", edited: "x\n"}, "fix: x")
    ok, message, plan, _ = check(fresh, "fix: x", base, head)
    assert not ok and plan["result"] == "fail"
    assert message.startswith("A test that fails before the change is missing: ")
    assert "never a test" in message


def test_c4_beside_a_real_test_a_fixture_is_not_run(fresh):
    base = fresh.commit({".github/review-policy.yml": POLICY, "src/__init__.py": "", "src/calc.py": BUGGY}, "chore: base")
    head = fresh.commit({"src/calc.py": FIXED, "tests/unit/test_calc.py": TEST, "tests/unit/fixtures/test_data.py": "x\n"}, "fix: add adds")
    plan = TF.plan(str(fresh.path), str(ROOT), "fix: add adds", base, head, "none-such", 7)
    assert [t["test"] for t in plan["tests"]] == ["tests/unit/test_calc.py"]


@pytest.mark.parametrize("kind", ["docs", "style", "ci", "chore", "refactor", "test"])
def test_c5_a_pull_request_of_another_type_passes_without_running_tests_and_says_why(fresh, monkeypatch, kind):
    base = fresh.commit({".github/review-policy.yml": POLICY, "src/__init__.py": "", "src/calc.py": BUGGY}, "chore: base")
    head = fresh.commit({"README.md": "words\n", "tests/unit/test_calc.py": TEST}, f"{kind}: words")

    def never(*args, **kwargs):
        raise AssertionError("a test ran")
    monkeypatch.setattr(TF, "run_one", never)
    monkeypatch.setattr(TF, "declaration", never)
    ok, message, plan, results = check(fresh, f"{kind}: words", base, head)
    assert ok and plan["result"] == "pass" and plan["tests"] == [] and results == []
    assert message == (f"Test first: a `{kind}` pull request alters no behaviour the check tests: no test is run "
                       "(only `fix` and `feat` pull requests carry a test that fails before the change).")


def test_c5_the_workflow_runs_the_tests_only_when_the_plan_says_so():
    import yaml
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "test-first.yml").read_text(encoding="utf-8"))
    assert wf["jobs"]["run"]["needs"] == "plan"
    assert wf["jobs"]["run"]["if"] == "needs.plan.outputs.result == 'run'"
    # The plan writes its message to the job summary, the pass's included.
    assert "GITHUB_STEP_SUMMARY" in (ROOT / "scripts" / "test-first.py").read_text(encoding="utf-8")


def test_c5_the_cli_passes_a_docs_pull_request_with_its_reason_in_the_summary(fresh, tmp_path):
    base = fresh.commit({".github/review-policy.yml": POLICY, "src/__init__.py": "", "src/calc.py": BUGGY}, "chore: base")
    head = fresh.commit({"README.md": "words\n"}, "docs: words")
    summary = tmp_path / "summary.md"
    env = {**os.environ, "DIR": str(fresh.path), "CENTRAL": str(ROOT), "TITLE": "docs: words", "BASE": base, "HEAD": head,
           "GITHUB_STEP_SUMMARY": str(summary)}
    planned = subprocess.run(["python3", str(ROOT / "scripts" / "test-first.py"), "plan"], env=env, capture_output=True, text=True)
    assert planned.returncode == 0 and "result=pass" in planned.stdout.splitlines()
    assert "a `docs` pull request alters no behaviour the check tests: no test is run" in summary.read_text(encoding="utf-8")


KINDS = sorted(p.name for p in (ROOT / "kinds").iterdir() if (p / "pack.yml").is_file())
TOOLS = ("php", "pytest", "playwright", "composer", "npm", "npx", "node", "wp-env", "jest", "vitest", "dotnet", "cargo", "go test")


@pytest.mark.parametrize("name", ["scripts/test-first.py", ".github/workflows/test-first.yml"])
def test_c6_nothing_specific_to_a_kind_in_the_script_or_the_workflow(name):
    import re
    text = (ROOT / name).read_text(encoding="utf-8").lower()
    for kind in KINDS:
        assert kind not in text, (name, kind)
    assert not re.search(r"kinds/[a-z0-9]", text), name
    for tool in TOOLS:
        assert not re.search(rf"(?<![a-z-]){re.escape(tool)}(?![a-z-])", text), (name, tool)


@pytest.mark.parametrize("kind", KINDS)
def test_c6_every_pack_declares_its_tests_by_a_way_of_its_own_repro(kind):
    ways = load("repro-ways")
    pack = ways.read(str(ROOT / "kinds" / kind / "pack.yml"))
    decl = TF.merged(pack.get("test-first"))
    assert decl is not None, kind
    assert TF.problems(decl, ways.merged(pack, {})["ways"]) == [], kind


def test_c6_this_repository_declares_its_tests_too():
    ways = load("repro-ways")
    policy = ways.read(str(ROOT / ".github" / "review-policy.yml"))
    decl = TF.merged(policy.get("test-first"))
    assert decl is not None
    assert TF.problems(decl, ways.merged({}, policy)["ways"]) == []
    assert TF.tests_of(decl, ["tests/repro/test_issue_734.py", "tests/workflows/test_test_first.py", "tests/release/scenarios.yml"]) == [
        ("tests/repro/test_issue_734.py", "python"), ("tests/workflows/test_test_first.py", "python")]


@pytest.mark.parametrize("kind, files, want", [
    ("wordpress-plugin", ["tests/Unit/Fields/FieldsTest.php", "tests/e2e/specs/login.spec.ts", "tests/Unit/fixtures/DataTest.php", "includes/a.php"],
     [("tests/Unit/Fields/FieldsTest.php", "unit", True), ("tests/e2e/specs/login.spec.ts", "browser", False)]),
    ("ai-agent-plugin", ["tests/hooks/test_guard.py", "tests/fixtures/test_in.py", "hooks/guard.py"], [("tests/hooks/test_guard.py", "unit", False)]),
    ("engine-test", ["tests/repro/test_issue_9.py", "scenarios/queue/9.md"], [("tests/repro/test_issue_9.py", "fixed", False)]),
])
def test_c6_a_repository_of_a_kind_gets_its_test_paths_and_ways_from_its_pack(fresh, kind, files, want):
    ways = load("repro-ways")
    pack = ways.read(str(ROOT / "kinds" / kind / "pack.yml"))
    base = fresh.commit({".github/review-policy.yml": f"kind: {kind}\n"}, "chore: base")
    head = fresh.commit({f: "x\n" for f in files}, "fix: a")
    plan = TF.plan(str(fresh.path), str(ROOT), "fix: a", base, head, "none-such", 7)
    assert plan["result"] == "run", plan["message"]
    assert [(t["test"], t["way"], bool(t["sandbox"])) for t in plan["tests"]] == want
    for t in plan["tests"]:
        way = ways.merged(pack, {})["ways"][t["way"]]
        # The way's own command, filled for this test: nothing the check adds.
        if not t["sandbox"]:
            assert t["spec"]["run"] == way["run"].replace("{test}", t["test"]).replace("{n}", "7")
            assert t["spec"]["test"] == t["test"]
    assert plan["setup"] == (pack["test-first"].get("setup") or [])


def test_c6_a_repository_adds_its_own_test_paths_over_its_packs(fresh):
    own = "kind: ai-agent-plugin\ntest-first:\n  tests:\n    - paths: ['spec/**/*_test.py']\n      way: unit\n"
    base = fresh.commit({".github/review-policy.yml": own}, "chore: base")
    head = fresh.commit({"spec/a_test.py": "x\n", "tests/test_b.py": "x\n"}, "feat: a")
    plan = TF.plan(str(fresh.path), str(ROOT), "feat: a", base, head, "none-such", 7)
    assert [t["test"] for t in plan["tests"]] == ["spec/a_test.py", "tests/test_b.py"]


def test_c6_a_way_of_no_repro_is_said(fresh):
    bad = "repro: {ways: {}}\ntest-first:\n  tests:\n    - paths: ['tests/**']\n      way: nope\n"
    base = fresh.commit({".github/review-policy.yml": bad}, "chore: base")
    head = fresh.commit({"tests/test_b.py": "x\n"}, "fix: a")
    plan = TF.plan(str(fresh.path), str(ROOT), "fix: a", base, head, "none-such", 7)
    assert plan["result"] == "fail" and "is no way of its `repro:`" in plan["message"]


def test_c6_b1_a_fix_in_a_repository_with_no_declaration_fails_saying_how_to_declare_one(fresh):
    base = fresh.commit({".github/review-policy.yml": "high-risk: []\n"}, "chore: base")
    head = fresh.commit({"tests/test_b.py": "x\n"}, "fix: a")
    plan = TF.plan(str(fresh.path), str(ROOT), "fix: a", base, head, "none-such", 7)
    assert plan["result"] == "fail"
    assert "declares no `test-first:`" in plan["message"] and "`tests`" in plan["message"] and "`not-tests`" in plan["message"]


def test_c6_policy_self_test_holds_every_pack_to_a_declaration():
    text = (ROOT / "scripts" / "policy.py").read_text(encoding="utf-8")
    assert "test-first" in text
    got = subprocess.run(["python3", str(ROOT / "scripts" / "policy.py"), "--test"], capture_output=True, text=True)
    assert got.returncode == 0, got.stdout[-2000:]
    for kind in KINDS:
        assert f"ok   pack {kind}: it declares its tests (test-first)" in got.stdout


@pytest.mark.parametrize("doc", ["rules/test-first.md", "docs/testing-and-quality.md", "docs/model.md"])
def test_c7_each_document_says_the_check_enforces_test_first_and_the_review_checks_it_too(doc):
    text = (ROOT / doc).read_text(encoding="utf-8")
    said = " ".join(line for line in text.splitlines() if '"Test first" check' in line)
    assert said, doc
    assert "enforced by the \"Test first\" check" in said, doc
    assert "the review checks it too" in said or "which the review checks too" in said, doc


def test_c7_the_rule_is_held_by_the_review_and_the_check():
    head, _ = load("rules").header((ROOT / "rules" / "test-first.md").read_text(encoding="utf-8"))
    assert head["enforced_by"] == ["review", {"check": "test-first"}]
    got = subprocess.run(["python3", str(ROOT / "scripts" / "rules.py"), "check"], capture_output=True, text=True)
    assert got.returncode == 0, got.stdout + got.stderr


def test_c7_the_testing_document_says_what_each_message_means_and_how_to_declare():
    text = (ROOT / "docs" / "testing-and-quality.md").read_text(encoding="utf-8")
    for said in ("A test that fails before the change is missing", "The test does not show the bug", "alters no behaviour the check tests",
                 "could not run", "fails at the base and passes at the head", "test-first:", "not-tests:", "way:"):
        assert said in text, said


def test_c6_the_browser_way_runs_every_spec_its_pack_declares_as_a_test():
    # The pack maps tests/e2e/**/*.spec.ts to the browser way, whose
    # Playwright configuration must then find any of them, not only a
    # reproduction's tests/e2e/repro/issue-<n>.spec.ts.
    import re
    ways = load("repro-ways")
    pack = ways.read(str(ROOT / "kinds" / "wordpress-plugin" / "pack.yml"))
    globs = [g for e in pack["test-first"]["tests"] if e["way"] == "browser" for g in e["paths"]]
    config = (ROOT / "kinds" / "wordpress-plugin" / "playwright.dx-repro.config.ts").read_text(encoding="utf-8")
    test_dir = re.search(r"const E2E = '\./([^']+)'", config).group(1)
    match = re.search(r"testMatch: /(.+)/,", config).group(1)
    for spec in ("tests/e2e/specs/login.spec.ts", "tests/e2e/repro/issue-69.spec.ts"):
        assert any(TF.glob_match(spec, g) for g in globs), spec
        assert spec.startswith(test_dir + "/") and re.search(match, spec), spec


def test_the_setup_runs_on_the_bases_checkout_never_the_heads():
    """Review of #791: an installer runs its manifest's scripts, so the
    head's setup would run unconfined in the job that gives the verdict,
    free to forge it. The setup step checks the base out before anything
    of the declaration's runs, and the tests read both commits from git."""
    import yaml
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "test-first.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["run"]["steps"]
    setup = [s for s in steps if "SETUP" in (s.get("env") or {})]
    assert len(setup) == 1
    step = setup[0]
    assert step["env"]["BASE"] == "${{ needs.plan.outputs.base }}"
    script = step["run"]
    assert script.index('git checkout --quiet --detach "$BASE"') < script.index('bash -c "$cmd"')
    # Nothing checks the head out again before the verdict.
    after = steps[steps.index(step) + 1:]
    assert not any("git checkout" in (s.get("run") or "") for s in after)
    assert not any((s.get("with") or {}).get("ref") in ("${{ needs.plan.outputs.head }}",) for s in after)
    # The checkout before the setup is the merge commit with its base: no
    # step before the setup runs anything.
    assert all("run" not in s for s in steps[:steps.index(step)])
