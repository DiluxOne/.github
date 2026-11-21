"""The evaluation's cases measure the task (#840): `evals.py validate` holds
every case of evals/spec/ and evals/autopilot/ to passing on its merged fix,
failing on an assertion at its base, and asserting none of the fix's own
literals (C1); the autopilot's replay runs the production's loop, work then
review and fix rounds, and a baseline is written only from a run of valid,
replayed cases (C2)."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SETS = ("spec", "autopilot")


def evals():
    spec = importlib.util.spec_from_file_location("evals_validate", ROOT / "scripts" / "evals.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def has(mod, name):
    """A function the change adds, asserted before a test calls it, so the
    base fails on an assertion, not an AttributeError."""
    assert hasattr(mod, name), f"evals.py has no {name}"
    return getattr(mod, name)


LONG = "the autopilot answers every review thread in words"  # 50 characters
DIFF = f"""diff --git a/scripts/a.py b/scripts/a.py
--- a/scripts/a.py
+++ b/scripts/a.py
@@ -1,2 +1,3 @@
 x = 1
+MESSAGE = "{LONG}"
-OLD = "a literal the fix removed, long enough to count"
diff --git a/docs/a.md b/docs/a.md
--- a/docs/a.md
+++ b/docs/a.md
@@ -1 +1,2 @@
+The bot now says: a sentence that a test should never copy.
diff --git a/tests/workflows/test_a.py b/tests/workflows/test_a.py
--- a/tests/workflows/test_a.py
+++ b/tests/workflows/test_a.py
@@ -0,0 +1 @@
+assert "a literal only the test itself adds, long" in out
"""

AUTO = {"id": "o/r#1:autopilot", "repo": "o/r", "issue": 1, "base": "b", "merge": "m", "tests": ["tests/workflows/test_a.py"], "expect": "passed"}


def facts(merge="passed", base="reproduced", test_text='assert run() == 0\n', diff=DIFF):
    return {"merge": {"tests/workflows/test_a.py": merge}, "base": {"tests/workflows/test_a.py": base},
            "added": has(evals(), "added_lines")(diff, AUTO["tests"]), "tests_text": {"tests/workflows/test_a.py": test_text}}


# C1: what makes a case valid.

def test_c1_added_lines_are_the_fixs_own_lines_but_the_cases_tests():
    added = has(evals(), "added_lines")(DIFF, AUTO["tests"])
    assert LONG in added and "a sentence that a test should never copy" in added
    assert "a literal the fix removed" not in added
    assert "only the test itself adds" not in added


def test_c1_literals_are_quoted_strings_of_30_characters_or_more():
    lit = has(evals(), "literals")
    got = lit(f"x = '{LONG}'\ny = \"short one\"\nz = \"{'a' * 29}\"\nw = \"{'b' * 30}\"\n")
    assert got == {LONG, "b" * 30}
    assert getattr(evals(), "LITERAL", None) == 30


def test_c1_a_valid_autopilot_case_has_no_problem():
    assert has(evals(), "check_case")("autopilot", AUTO, facts()) == []
    # A long literal the test only opens or builds (a path, a fixture) asserts nothing.
    opened = f'text = open("{LONG}").read()\nassert run(text) == 0\n'
    assert evals().check_case("autopilot", AUTO, facts(test_text=opened)) == []


@pytest.mark.parametrize("kw, check", [
    ({"merge": "reproduced"}, "merge"),
    ({"merge": "limit"}, "merge"),
    ({"base": "passed"}, "base"),
    ({"base": "broken"}, "base"),
    ({"base": "limit"}, "base"),
    ({"test_text": f'assert "{LONG}" in out\n'}, "literal"),
    ({"test_text": 'assert "a sentence that a test should never copy" in doc\n'}, "literal"),
])
def test_c1_an_invalid_autopilot_case_fails_the_check_it_breaks(kw, check):
    problems = has(evals(), "check_case")("autopilot", AUTO, facts(**kw))
    assert [p.split(":", 1)[0] for p in problems] == [check], problems


def spec_case(files, body):
    return {"id": "o/r#2:spec", "repo": "o/r", "issue": 2, "base": "b", "merge": "m", "type": "Bug", "files": files, "body": body, "expect": "named"}


PRD = ("### Problem\n\nNo dark mode.\n\n### Scope\n\n- A toggle.\n\n### Out of scope\n\n- Themes.\n\n### Acceptance criteria\n\n"
       "- C1: Given a visitor, when they press the toggle, then the page turns dark.\n\n### Criticality\n\nNormal\n\n")
SPEC = "### Spec: approach\n\nA class.\n\n### Spec: files\n\n- header.php\n- assets/dark.css\n\n### Spec: tests\n\n- C1 → tests/e2e/toggle.spec.ts\n"


def body(spec):
    return f"<!-- dx-prd -->\n{PRD}<!-- /dx-prd -->\n\n<!-- dx-spec -->\n{spec}<!-- /dx-spec -->\n"


def test_c1_a_spec_case_passes_on_its_merged_spec_and_fails_on_the_prd_alone():
    mod = evals()
    check_case = has(mod, "check_case")
    good = spec_case(["header.php", "assets/dark.css"], body(SPEC))
    assert check_case("spec", good, {"added": ""}) == []
    # The issue's real Spec names other files than the merge changed: no pass on its fix.
    other = spec_case(["a.php", "b.php", "c.php"], body(SPEC))
    assert [p.split(":", 1)[0] for p in check_case("spec", other, {"added": ""})] == ["merge"]
    # A file the case asserts that is a literal the fix's lines carry.
    leak = spec_case(["header.php", "assets/dark.css"], body(SPEC))
    added = has(mod, "added_lines")('diff --git a/x b/x\n+++ b/x\n+PATH = "assets/dark.css is where the new theme lives now"\n', [])
    problems = check_case("spec", {**leak, "files": ["assets/dark.css is where the new theme lives now"]}, {"added": added})
    assert "literal" in [p.split(":", 1)[0] for p in problems], problems


def test_c1_validate_names_each_invalid_case_and_exits_1(monkeypatch, capsys):
    mod = evals()
    has(mod, "validate")
    cases = [AUTO, {**AUTO, "id": "o/r#3:autopilot"}]
    got = {"o/r#1:autopilot": facts(), "o/r#3:autopilot": facts(base="passed")}
    monkeypatch.setattr(mod, "facts_of", lambda step, case, work: got[case["id"]])
    monkeypatch.setattr(mod, "load_cases", lambda step, root=None: cases)
    assert mod.validate("autopilot", cases, "/nonexistent") == [("o/r#3:autopilot", mod.check_case("autopilot", cases[1], got["o/r#3:autopilot"])[0])]
    assert mod.main(["validate", "autopilot"]) == 1
    err = capsys.readouterr()
    assert "o/r#3:autopilot: base" in err.out + err.err and "o/r#1:autopilot" not in (err.out + err.err).replace("o/r#1:autopilot: valid", "")
    got["o/r#3:autopilot"] = facts()
    assert mod.main(["validate", "autopilot"]) == 0


def test_c1_a_case_whose_facts_cannot_be_had_is_invalid_by_name(monkeypatch):
    mod = evals()
    has(mod, "validate")
    monkeypatch.setattr(mod, "facts_of", lambda step, case, work: None)
    assert [i for i, _ in mod.validate("autopilot", [AUTO], "/nonexistent")] == [AUTO["id"]]


@pytest.mark.parametrize("step", SETS)
def test_c1_every_case_carries_its_base_and_merge(step):
    cases = json.loads((ROOT / "evals" / step / "cases.json").read_text(encoding="utf-8"))
    assert all(c.get("base") and c.get("merge") for c in cases), [c["id"] for c in cases if not c.get("merge")]
    assert "merge" in evals().STEPS[step]["fields"]


def test_c1_evals_yml_validates_before_the_sets():
    import yaml
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "evals.yml").read_text(encoding="utf-8"))
    jobs = wf["jobs"]
    assert "validate" in jobs, list(jobs)
    assert "evals.py validate" in json.dumps(jobs["validate"])
    needs = jobs["replay"]["needs"]
    assert "validate" in (needs if isinstance(needs, list) else [needs])


def test_c1_the_docs_state_the_rule():
    text = (ROOT / "docs" / "testing-and-quality.md").read_text(encoding="utf-8")
    assert "evals.py validate" in text
    assert "fails on an assertion at its base" in text


def test_c1_a_case_is_rewritten_to_its_valid_tests_or_left_out():
    mod = evals()
    rewritten = has(mod, "rewritten")
    two = {**AUTO, "tests": ["tests/workflows/test_a.py", "tests/workflows/test_b.py"]}
    f = facts()
    f["merge"]["tests/workflows/test_b.py"], f["base"]["tests/workflows/test_b.py"] = "passed", "broken"
    f["tests_text"]["tests/workflows/test_b.py"] = ""
    assert rewritten("autopilot", two, f)["tests"] == ["tests/workflows/test_a.py"]
    assert rewritten("autopilot", AUTO, facts(base="broken")) is None
    assert rewritten("autopilot", AUTO, facts(test_text=f'assert "{LONG}" in out\n')) is None


def test_c1_collect_keeps_only_the_valid_cases(monkeypatch):
    mod = evals()
    has(mod, "rewritten")
    commits = [{"sha": f"m{i}", "parent": f"p{i}", "subject": f"feat: thing {i} (#{100 + i})", "body": f"Closes #{i}.",
                "files": ["scripts/x.py", "tests/workflows/test_a.py"]} for i in range(1, 5)]
    monkeypatch.setattr(mod, "git_commits", lambda root: commits)
    monkeypatch.setattr(mod, "pin_issue", lambda c: {**c, "title": "t", "body": "b"})
    monkeypatch.setattr(mod, "preload", lambda: None)
    valid = {"m2", "m4"}
    monkeypatch.setattr(mod, "facts_of", lambda step, c, work: facts() if c["merge"] in valid else facts(base="passed"))
    got = mod.collect("autopilot", 6)
    assert [c["merge"] for c in got] == ["m2", "m4"]
    assert [c["merge"] for c in mod.collect("autopilot", 1)] == ["m2"]
