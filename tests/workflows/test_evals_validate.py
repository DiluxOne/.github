"""The evaluation's cases measure the task (#840): `evals.py validate` holds
every case of evals/spec/ and evals/autopilot/ to passing on its merged fix,
failing on an assertion at its base, and asserting none of the fix's own
literals (C1); the autopilot's replay runs the production's loop, work then
review and fix rounds, and a baseline is written only from a run of valid,
replayed cases (C2)."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SETS = ("spec", "autopilot")


def evals():
    spec = importlib.util.spec_from_file_location("evals_validate", ROOT / "scripts" / "evals.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def kind(problem):
    """The check a problem names: its first word (merge, base, literal, facts)."""
    return re.match(r"[a-z]+", problem).group(0)


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
    assert [kind(p) for p in problems] == [check], problems


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
    assert [kind(p) for p in check_case("spec", other, {"added": ""})] == ["merge"]
    # A file the case asserts that is a literal the fix's lines carry.
    leak = spec_case(["header.php", "assets/dark.css"], body(SPEC))
    added = has(mod, "added_lines")('diff --git a/x b/x\n+++ b/x\n+PATH = "assets/dark.css is where the new theme lives now"\n', [])
    problems = check_case("spec", {**leak, "files": ["assets/dark.css is where the new theme lives now"]}, {"added": added})
    assert "literal" in [kind(p) for p in problems], problems


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


def test_c1_a_set_that_fails_validate_gets_no_score_nor_results():
    import yaml
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "evals.yml").read_text(encoding="utf-8"))
    ev = wf["jobs"]["eval"]
    needs = ev["needs"] if isinstance(ev["needs"], list) else [ev["needs"]]
    assert "validate" in needs, "the score does not wait on validate"
    steps = ev["steps"]
    # The first thing the job does past the checkout: fail, with no score,
    # when validate ran and did not pass.
    guard = next((i for i, s in enumerate(steps) if "needs.validate.result" in str(s.get("if", ""))
                  and "exit 1" in s.get("run", "")), None)
    assert guard is not None, "no step stops the score when validate failed"
    later = steps[guard + 1:]
    assert any("evals.py score" in s.get("run", "") for s in later), "the score runs before the guard"
    # Nothing after it runs once it failed: no step forces itself with always() past an invalid set.
    for s in later:
        cond = str(s.get("if", ""))
        assert "always()" not in cond or "needs.validate.result == 'success'" in cond, s.get("name")


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
    monkeypatch.setattr(mod, "load_cases", lambda step, root=None: [])
    monkeypatch.setattr(mod, "facts_of", lambda step, c, work: facts() if c["merge"] in valid else facts(base="passed"))
    got = mod.collect("autopilot", 6)
    assert [c["merge"] for c in got] == ["m2", "m4"]
    assert [c["merge"] for c in mod.collect("autopilot", 1)] == ["m2"]


# C2: the autopilot's replay is the production's loop, and its baseline
# comes from a run of valid, replayed cases.

def loop(monkeypatch, tmp_path, blocking_rounds, review_fails=False):
    """replay_autopilot with the model, the review and the tests faked:
    what it asked, in order, and the head the tests were graded on."""
    import subprocess
    mod = evals()
    has(mod, "review_round")
    tree = tmp_path / "tree"
    tree.mkdir()
    subprocess.run(["git", "init", "-q", str(tree)], check=True)
    base = mod.commit_all(str(tree), "the base")
    monkeypatch.setattr(mod, "checkout", lambda case, work: (str(tree), base))
    asked, reviews = [], []

    def ask(prompt, args, cwd, step, root=None):
        asked.append((prompt, args))
        (tree / f"f{len(asked)}.txt").write_text("x")
        return {"result": "ok"}
    monkeypatch.setattr(mod, "ask", ask)

    def review(tree_, base_, title, body_file):
        reviews.append(title)
        n = len(reviews)
        return None if review_fails else (n <= blocking_rounds, f"- [ ] **major** `a.py:1`: point {n}")
    monkeypatch.setattr(mod, "review_round", review)
    monkeypatch.setattr(mod, "clone_of", lambda case, work, *refs: str(tmp_path))
    graded = []
    monkeypatch.setattr(mod, "merged_tests", lambda tree_, case, clone, head, out: graded.append(head) or {t: "passed" for t in case["tests"]})
    case = {**AUTO, "title": "feat: a thing", "body": body(SPEC)}
    got = mod.replay_autopilot(case, str(tmp_path))
    head = mod.git(str(tree), "rev-parse", "HEAD").stdout.strip()
    return mod, asked, reviews, graded, head, got, tree


def test_c2_the_replay_runs_the_work_then_the_review_and_its_fix_rounds(monkeypatch, tmp_path):
    mod, asked, reviews, graded, head, got, tree = loop(monkeypatch, tmp_path, 1)
    has(mod, "review_round")
    # The work, then its review blocks and one fix round runs (#941: one round).
    assert len(asked) == 2 and len(reviews) == 1
    assert "draft pull request" in asked[0][0] and "The review of pull request" in asked[1][0] and "round 1 of 1" in asked[1][0]
    # The fix rounds' arguments are the workflow's, in mode fix.
    assert asked[0][1] == mod.autopilot_args("work", "20") and asked[1][1] == mod.autopilot_args("work", "10")
    # The fix round reads the review's findings where the production's prompt says.
    assert "point 1" in (tree / ".dx-io" / "review.md").read_text(encoding="utf-8")
    # The production's draft: its branch, and its title and body for the review.
    assert mod.git(str(tree), "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "feat/1-a-thing"
    assert reviews == ["feat: a thing"] and "Closes #1" in (tree / ".dx-io" / "pr.md").read_text(encoding="utf-8")
    # Graded on the final tree.
    assert graded == [head] and got == {"tests/workflows/test_a.py": "passed"}


def test_c2_the_rounds_stop_at_the_replays_limit(monkeypatch, tmp_path):
    # #941: one fix round in the replay, not the production's five.
    import yaml
    rounds = yaml.safe_load((ROOT / "policy" / "autonomy.yml").read_text(encoding="utf-8"))["autopilot-rounds"]
    mod, asked, reviews, graded, head, got, tree = loop(monkeypatch, tmp_path, 99)
    has(mod, "max_rounds")
    assert mod.max_rounds() == rounds
    assert mod.eval_rounds() == 1
    assert len(asked) == 2 and "round 1 of 1" in asked[-1][0]
    assert graded == [head]


def test_c2_a_review_that_cannot_run_leaves_the_case_not_replayed(monkeypatch, tmp_path):
    mod, asked, reviews, graded, head, got, tree = loop(monkeypatch, tmp_path, 0, review_fails=True)
    assert len(asked) == 1 and len(reviews) == 1
    assert got is None and graded == []


MODEL_KEYS = {"ANTHROPIC_API_KEY": "sk-planted-test", "CLAUDE_CODE_OAUTH_TOKEN": "oauth-planted-test"}


def planted_tree(tmp_path):
    """An agent's tree as it could leave it: a commit, and a hook and a
    config of its own in its .git, each of which would run with the key."""
    import subprocess
    tree = tmp_path / "tree"
    tree.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(tree), *a], check=True, capture_output=True)
    run("init", "-q")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base")
    base = subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    (tree / "a.py").write_text("x = 1\n")
    leak = tmp_path / "leak"
    hook = tree / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\nenv > {leak}\n")
    hook.chmod(0o755)
    run("config", "planted.key", "agent")
    return tree, base, leak


def test_c2_the_trees_git_runs_without_the_model_key_and_its_hooks(monkeypatch, tmp_path):
    import subprocess
    mod = evals()
    for k, v in MODEL_KEYS.items():
        monkeypatch.setenv(k, v)
    tree, _, leak = planted_tree(tmp_path)
    envs, real = [], subprocess.run

    def spy(argv, *a, **kw):
        if argv and argv[0] == "git":
            envs.append(kw.get("env"))
        return real(argv, *a, **kw)
    monkeypatch.setattr(mod.subprocess, "run", spy)
    head = mod.commit_all(str(tree), "chore: what the agent left")
    assert head, "no commit"
    assert not leak.exists(), "the tree's own pre-commit hook ran"
    assert envs, "evals.py ran no git"
    for env in envs:
        assert env is not None, "git ran with the whole environment, the model key in it"
        assert not set(MODEL_KEYS) & set(env), "the model key is in git's environment"
        assert env.get("GIT_CONFIG_NOSYSTEM") == "1" and env.get("GIT_CONFIG_GLOBAL") == mod.os.devnull


def test_c2_the_review_round_reads_a_clone_without_the_trees_hooks_and_config(monkeypatch, tmp_path):
    mod = evals()
    has(mod, "review_round")
    for k, v in MODEL_KEYS.items():
        monkeypatch.setenv(k, v)
    tree, base, leak = planted_tree(tmp_path)
    mod.commit_all(str(tree), "chore: what the agent left")
    # A stand-in for local-review.sh: what it sees of git, and its findings where it keeps them.
    root = tmp_path / "root"
    (root / "scripts").mkdir(parents=True)
    seen = tmp_path / "seen"
    (root / "scripts" / "local-review.sh").write_text(
        "#!/bin/bash\n"
        f"{{ pwd; git config --list; echo hooks=$(git config core.hooksPath); }} > {seen}\n"
        "state=$(git rev-parse --git-dir)/dx-review; mkdir -p \"$state\"; echo '- none' > \"$state/findings.md\"\n")
    body = tmp_path / "pr.md"
    body.write_text("body\n")
    got = mod.review_round(str(tree), base, "feat: x", str(body), root=str(root))
    assert got == (False, "- none\n"), got
    text = seen.read_text()
    assert text.splitlines()[0] != str(tree), "the review ran in the tree the agent left"
    assert "planted.key" not in text, "the review's git read the tree's own config"
    assert "hooks=/dev/null" in text, "the review's git keeps hooks on"
    assert not leak.exists()


def test_c2_an_autopilot_job_has_the_time_of_its_rounds():
    mod = evals()
    has(mod, "max_rounds")
    minutes = {x["minutes"] for x in mod.matrix(["autopilot"])}
    assert minutes == {mod.job_minutes("autopilot")}
    assert mod.job_minutes("autopilot") > mod.STEPS["autopilot"]["minutes"] * 2 and mod.job_minutes("autopilot") <= 360


def write_results(tmp_path, results):
    f = tmp_path / "results.json"
    f.write_text(json.dumps(results), encoding="utf-8")
    return str(f)


def baseline_env(monkeypatch, tmp_path, bad):
    mod = evals()
    (tmp_path / "evals" / "autopilot").mkdir(parents=True)
    monkeypatch.setattr(mod, "EVALS", str(tmp_path / "evals"))
    cases = [AUTO, {**AUTO, "id": "o/r#3:autopilot"}]
    monkeypatch.setattr(mod, "load_cases", lambda step, root=None: cases)
    monkeypatch.setattr(mod, "validate", lambda step, cs, work: bad)
    return mod, tmp_path / "evals" / "autopilot" / "baseline.json"


def test_c2_the_baseline_refuses_a_set_with_an_invalid_case(monkeypatch, tmp_path, capsys):
    mod, path = baseline_env(monkeypatch, tmp_path, [("o/r#3:autopilot", "base: every test passes at its base")])
    res = write_results(tmp_path, [{"id": "o/r#1:autopilot", "expect": "passed", "ok": True}, {"id": "o/r#3:autopilot", "expect": "passed", "ok": False}])
    assert mod.main(["baseline", "autopilot", res]) == 1
    assert not path.exists()
    assert "o/r#3:autopilot" in capsys.readouterr().err


def test_c2_the_baseline_refuses_a_run_that_left_a_case_out(monkeypatch, tmp_path):
    mod, path = baseline_env(monkeypatch, tmp_path, [])
    res = write_results(tmp_path, [{"id": "o/r#1:autopilot", "expect": "passed", "ok": True}])
    assert mod.main(["baseline", "autopilot", res]) == 1
    assert not path.exists()
    unrun = write_results(tmp_path, [{"id": "o/r#1:autopilot", "expect": "passed", "ok": True}, {"id": "o/r#3:autopilot", "expect": "passed", "ok": None}])
    assert mod.main(["baseline", "autopilot", unrun]) == 1
    assert not path.exists()


def test_c2_the_baseline_is_written_from_a_run_of_valid_replayed_cases(monkeypatch, tmp_path):
    mod, path = baseline_env(monkeypatch, tmp_path, [])
    has(mod, "max_rounds")
    res = write_results(tmp_path, [{"id": "o/r#1:autopilot", "expect": "passed", "ok": True}, {"id": "o/r#3:autopilot", "expect": "passed", "ok": False}])
    assert mod.main(["baseline", "autopilot", res]) == 0
    assert json.loads(path.read_text(encoding="utf-8")) == {"passed": 1, "cases": 2, "unrun": 0}


def test_c2_the_docs_say_the_replay_and_the_baseline():
    text = (ROOT / "docs" / "testing-and-quality.md").read_text(encoding="utf-8")
    assert "autopilot-rounds" in text and "local-review.sh" in text
    assert "every case valid" in text


def test_c1_collect_keeps_the_sets_valid_cases_first(monkeypatch):
    # The maintainer's answer on #840: collect keeps the set's valid cases
    # first, then fills up to N from the history, never a case twice.
    mod = evals()
    has(mod, "rewritten")
    commits = [{"sha": f"m{i}", "parent": f"p{i}", "subject": f"feat: thing {i} (#{100 + i})", "body": f"Closes #{i}.",
                "files": ["scripts/x.py", "tests/workflows/test_a.py"]} for i in range(1, 5)]
    monkeypatch.setattr(mod, "git_commits", lambda root: commits)
    pinned = []
    monkeypatch.setattr(mod, "pin_issue", lambda c: pinned.append(c["id"]) or {**c, "title": "t", "body": "b"})
    monkeypatch.setattr(mod, "preload", lambda: None)
    hist = {c["merge"]: c for c in mod.cases_from_commits("autopilot", "DiluxOne/.github", commits, 10)}
    kept = {**hist["m3"], "title": "pinned", "body": "as merged"}
    dropped = {**AUTO, "id": "o/r#9:autopilot", "merge": "m9"}
    monkeypatch.setattr(mod, "load_cases", lambda step, root=None: [dropped, kept])
    valid = {"m1", "m3", "m4"}
    monkeypatch.setattr(mod, "facts_of", lambda step, c, work: facts() if c["merge"] in valid else facts(base="passed"))
    got = mod.collect("autopilot", 3)
    # The set's valid case first, as pinned; then the history's, m3 not twice.
    assert [c["merge"] for c in got] == ["m3", "m1", "m4"]
    assert (got[0]["title"], got[0]["body"]) == ("pinned", "as merged") and kept["id"] not in pinned
    assert [c["merge"] for c in mod.collect("autopilot", 1)] == ["m3"]


def workflow():
    import yaml
    text = (ROOT / ".github" / "workflows" / "evals.yml").read_text(encoding="utf-8")
    return text, yaml.safe_load(text)


def test_c1_evals_yml_collects_a_new_set_by_hand_and_pushes_nothing():
    text, wf = workflow()
    on = wf.get("on", wf.get(True))
    inputs = on["workflow_dispatch"]["inputs"]
    assert "step" in inputs and inputs.get("mode", {}).get("options") == ["eval", "collect"]
    assert inputs["mode"].get("default") == "eval"
    jobs = wf["jobs"]
    assert "collect" in jobs, "evals.yml has no collect job"
    collect = jobs["collect"]
    assert "inputs.mode == 'collect'" in collect["if"] and "workflow_dispatch" in collect["if"]
    run = "\n".join(s.get("run", "") for s in collect["steps"])
    # Six valid cases, the floor; with the job's read token alone.
    assert 'evals.py collect "$STEP" 6' in run
    assert any(s.get("env", {}).get("GH_TOKEN") == "${{ github.token }}" for s in collect["steps"])
    assert wf["permissions"] == {"contents": "read"}
    assert all(j.get("permissions", {}).get("contents", "read") == "read" for j in jobs.values())
    # It pushes nothing, and the checkout keeps no credential.
    assert "git push" not in text and "gh pr" not in text and "gh api" not in text
    assert all(s.get("with", {}).get("persist-credentials") is False for j in jobs.values() for s in j["steps"] if "actions/checkout@" in s.get("uses", ""))
    # The new set is the one validated and replayed, case by case.
    for name in ("validate", "replay", "eval"):
        assert "collect" in jobs[name]["needs"], name
    assert "needs.collect.outputs.cases" in str(jobs["replay"]["strategy"]["matrix"])
    for name in ("validate", "replay", "eval"):
        assert any("download-artifact" in s.get("uses", "") and s.get("if") == "needs.collect.result == 'success'"
                   for s in jobs[name]["steps"]), name
    # One artifact: the new cases only, the whole cases.json, the run's results; no score against the old baseline.
    ev = jobs["eval"]["steps"]
    score = next(s for s in ev if "evals.py score" in s.get("run", ""))
    assert score.get("if") == "needs.collect.result != 'success'"
    keep = [s for s in ev if "upload-artifact" in s.get("uses", "") and s.get("if") == "needs.collect.result == 'success'"]
    assert len(keep) == 1
    path = keep[0]["with"]["path"]
    assert all(f in path for f in ("new-cases.json", "cases.json", "results.json"))
