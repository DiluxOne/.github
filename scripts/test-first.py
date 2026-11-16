#!/usr/bin/env python3
"""The "Test first" check (#734, rules/test-first.md): a `fix` or `feat`
pull request carries a test that fails at its base and passes at its head.

The rule is held by this check and by the review. The check runs on every
pull request of every repository (.github/workflows/test-first.yml): it
reads what the pull request's title says it is, which files it adds or
changes, and where the repository's tests are and how they run, and runs
each test it adds or changes twice, at the base (the base's tree with the
head's test file in its own place) and at the head.

Where the tests are is data, never written here: the repository's
`test-first:` declaration, from its kind's pack (kinds/<kind>/pack.yml),
then the organisation's repos.yml (under its name), then its own
.github/review-policy.yml, each over the one before (`setup` replaced,
`tests` and `not-tests` added to), read from the BASE commit, so a pull
request cannot exempt itself:

  setup      commands run at the BASE's checkout, with the network, before
             any test is in place (the repository's own dev tools; never
             the head's manifests, whose install scripts would run outside
             any sandbox in the job that gives the verdict)
  tests      [{paths: [globs], way: <name>}]: a file under one of `paths`
             is a test, run by the reproduction way `way` of the same
             declaration's `repro:` (scripts/repro-ways.py): its sandbox,
             or its `setup`, `run`, `junit`, `assertion`, `teardown` and
             `minutes`, through scripts/repro-sandbox.sh or
             scripts/repro-run.sh, no network, no secret
  not-tests  [globs]: never a test, whatever `tests` says (release
             scenarios, fixtures, expected outputs)

The verdict:
  - a pull request whose type is neither `fix` nor `feat` (`docs`, `style`,
    `ci`, `chore`, `refactor`, ...) passes, running nothing, and says why;
  - a `fix` or `feat` one in a repository that declares no `test-first:`
    fails, saying how to declare it;
  - one that adds or changes no test fails: a test that fails before the
    change is missing;
  - every test must pass at the head;
  - `fix`: one test at least fails at the base on an assertion
    (`reproduced`), else the test does not show the bug;
  - `feat`: one test at least fails or breaks at the base, else the test
    that fails before the change is missing;
  - a test that could not run (`limit`: setup or time) fails the check as
    "could not run", never passes it.

  test-first.py plan     TITLE, BASE, HEAD, DIR (the checkout with both
                         commits), CENTRAL (the organisation's checkout),
                         REPO, NUMBER (the pull request's), DECLARATION_AT_BASE
                         (1: read kinds/ and repos.yml at BASE in DIR too,
                         the organisation's own repository): result=pass|
                         fail|run, type, message, tests (JSON), setup
                         (JSON), to $GITHUB_OUTPUT too; exit 1 on fail
  test-first.py run      TESTS (plan's JSON), TYPE, BASE, HEAD, DIR,
                         CENTRAL: each test at the base and at the head,
                         then the verdict; exit 1 when it fails
  test-first.py verdict  TYPE, RESULTS (JSON [{test, base, head}]): the
                         verdict alone; exit 1 when it fails
  test-first.py --test   self-test

The message goes to the job summary ($GITHUB_STEP_SUMMARY) too.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import repos_conf  # noqa: E402

# The types whose pull request alters behaviour the check tests.
TESTED = ("fix", "feat")
KEY = "test-first"
KEYS = {"setup", "tests", "not-tests"}
# A pull request with more tests than this is asked to split (Spec: threats).
MAX_TESTS = 20
# What a test's path may hold: it reaches a shell through the scripts.
SAFE_PATH = re.compile(r"[A-Za-z0-9_@+.-]+(?:/[A-Za-z0-9_@+.-]+)*")
OUTCOMES = ("reproduced", "passed", "broken", "limit")
HOW = (f"declare `{KEY}:` in the repository's .github/review-policy.yml (or in its kind's pack, kinds/<kind>/pack.yml in "
       "DiluxOne/.github, or under its name in repos.yml): `tests`, a list of `{paths: [globs], way: <a way of its `repro:`>}`, "
       "`not-tests`, the globs that are never a test (fixtures, expected outputs), and `setup`, the commands that install its "
       "dev tools; scripts/test-first.py says what each key means")


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ways_mod = _load("repro_ways", "repro-ways.py")


def pr_type(title):
    """The Conventional Commit type of TITLE, and whether it has a `!`;
    ("", False) when it is none."""
    m = re.match(r"^([a-z]+)(?:\([^)]*\))?(!)?: ", title or "")
    return (m.group(1), bool(m.group(2))) if m else ("", False)


def merged(*layers):
    """The `test-first:` of the layers (pack, repos.yml's, the repository's),
    each over the one before: `setup` replaced, `tests` and `not-tests`
    added to. None when no layer declares one."""
    out = None
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        out = out or {"setup": [], "tests": [], "not-tests": []}
        if "setup" in layer:
            setup = layer["setup"]
            out["setup"] = [setup] if isinstance(setup, str) else list(setup or [])
        out["tests"] += list(layer.get("tests") or [])
        out["not-tests"] += list(layer.get("not-tests") or [])
        out["unknown"] = sorted(set(out.get("unknown", [])) | (set(layer) - KEYS))
    return out


def problems(decl, ways):
    """What is wrong with a merged declaration, against the reproduction
    ways of the same declaration (WAYS, by name); empty when it is right."""
    out = []
    if decl.get("unknown"):
        out.append(f"{KEY}: unknown keys {decl['unknown']}")
    if not all(isinstance(s, str) and s for s in decl["setup"]):
        out.append(f"{KEY}.setup: a list of commands")
    if not decl["tests"]:
        out.append(f"{KEY}.tests: at least one `{{paths: [globs], way: <name>}}`")
    for i, entry in enumerate(decl["tests"]):
        if not isinstance(entry, dict) or set(entry) - {"paths", "way"}:
            out.append(f"{KEY}.tests[{i}]: `paths` and `way`, nothing else")
            continue
        paths = entry.get("paths")
        if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p and not p.startswith("/") for p in paths):
            out.append(f"{KEY}.tests[{i}].paths: a list of relative globs")
        if entry.get("way") not in ways:
            out.append(f"{KEY}.tests[{i}].way: '{entry.get('way')}' is no way of its `repro:` ({', '.join(ways) or 'none'})")
    if not all(isinstance(g, str) and g for g in decl["not-tests"]):
        out.append(f"{KEY}.not-tests: a list of globs")
    return out


def read(path):
    return ways_mod.read(path)


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)


def at(root, ref, path, dest):
    """The file PATH as committed at REF, written to DEST; False when REF
    has none."""
    got = subprocess.run(["git", "-C", root, "show", f"{ref}:{path}"], capture_output=True)
    if got.returncode != 0:
        return False
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(got.stdout)
    return True


def declaration(root, central, name, base, at_base=False):
    """(kind, merged test-first or None, merged repro conf) of repository
    NAME, from BASE: its own policy at BASE, and, with AT_BASE, the kinds/
    and repos.yml of BASE too (the organisation's own repository, whose
    pull request could change them); otherwise CENTRAL's."""
    with tempfile.TemporaryDirectory() as tmp:
        policy_file = os.path.join(tmp, "policy.yml")
        policy = read(policy_file) if at(root, base, ".github/review-policy.yml", policy_file) else {}
        where = central
        if at_base:
            where = os.path.join(tmp, "central")
            os.makedirs(os.path.join(where, "kinds"))
            listed = git(root, "ls-tree", "-r", "--name-only", base, "--", "kinds", "repos.yml").stdout.split()
            for path in listed:
                if path == "repos.yml" or path.endswith("/pack.yml"):
                    at(root, base, path, os.path.join(where, path))
        conf = read(os.path.join(where, "repos.yml"))
        kind, pack = ways_mod.pack_of(os.path.join(where, "kinds"), conf, name, policy)
        org = repos_conf.value(conf, name, KEY)
        decl = merged(pack.get(KEY), org, policy.get(KEY))
        repro = ways_mod.merged(pack, policy, ways_mod.org_repro(conf, name))
    return kind, decl, repro


def declared(conf, name, policy, kinds_dir):
    """Whether repository NAME declares a `test-first:` (its kind's pack,
    repos.yml `conf`, its own policy): what the daily drift check lists
    when it does not (scripts/sync-repos.py)."""
    _, pack = ways_mod.pack_of(kinds_dir, conf, name, policy or {})
    return merged(pack.get(KEY), repos_conf.value(conf, name, KEY), (policy or {}).get(KEY)) is not None


def changed(root, base, head):
    """The files the pull request adds or modifies, BASE...HEAD; a rename is
    a file added."""
    out = git(root, "diff", "--name-only", "--no-renames", "--diff-filter=AM", f"{base}...{head}")
    if out.returncode != 0:
        raise RuntimeError(f"git diff {base}...{head}: {out.stderr.strip()[:200]}")
    return [p for p in out.stdout.splitlines() if p]


def glob_match(path, pattern):
    return ways_mod.glob_match(path, pattern)


def tests_of(decl, paths):
    """[(path, way)] of PATHS that are tests: under a `tests` entry's paths
    and none of `not-tests`; the first entry that matches gives the way."""
    out = []
    for path in paths:
        if any(glob_match(path, g) for g in decl["not-tests"]):
            continue
        for entry in decl["tests"]:
            if any(glob_match(path, g) for g in entry["paths"]):
                out.append((path, entry["way"]))
                break
    return out


def spec_of(way, path, number, central, kind):
    """The way, filled for the test at PATH, as scripts/repro-run.sh takes
    it: its `test` is PATH; `{n}` the pull request's number. No `case` (it
    names a reproduction's test, not this one), no `theme`, no `fixed`."""
    def fill(v):
        if isinstance(v, str):
            return ways_mod.fill(v, number, central, kind, path)
        if isinstance(v, list):
            return [fill(x) for x in v]
        return v
    spec = {k: fill(v) for k, v in way.items() if k in ("setup", "run", "junit", "assertion", "teardown", "minutes")}
    spec["test"] = path
    return spec


def missing_message(kind_of_pr, decl):
    where = ", ".join(f"`{g}`" for e in decl["tests"] for g in e["paths"])
    never = ", ".join(f"`{g}`" for g in decl["not-tests"])
    return (f"A test that fails before the change is missing: this {kind_of_pr} pull request adds or changes no test "
            f"under {where}" + (f" ({never} are never a test: a release scenario, a fixture or an expected output proves nothing)" if never else "") +
            ". Write the test first, see it fail on the code as it was, then change the code (rules/test-first.md).")


def plan(root, central, title, base, head, name, number, at_base=False):
    """What the check does for the pull request: {result: pass|fail|run,
    type, message, tests: [{test, way, sandbox, spec}], setup: [commands]}."""
    kind_of_pr, bang = pr_type(title)
    out = {"result": "pass", "type": kind_of_pr, "message": "", "tests": [], "setup": []}
    if kind_of_pr not in TESTED:
        said = f"`{kind_of_pr}`" if kind_of_pr else "untyped"
        out["message"] = (f"Test first: a {said} pull request alters no behaviour the check tests: no test is run "
                          "(only `fix` and `feat` pull requests carry a test that fails before the change).")
        return out
    kind, decl, repro = declaration(root, central, name, base, at_base)
    out["result"] = "fail"
    if decl is None:
        out["message"] = (f"Test first: this repository declares no `{KEY}:`, so the check cannot tell its tests from its other "
                          f"files, and a {kind_of_pr} pull request needs a test that fails before the change; to {HOW}.")
        return out
    bad = problems(decl, repro["ways"])
    if bad:
        out["message"] = f"Test first: the repository's `{KEY}:` is not valid ({'; '.join(bad)}); to fix it, {HOW}."
        return out
    tests = tests_of(decl, changed(root, base, head))
    if not tests:
        out["message"] = missing_message(kind_of_pr, decl)
        return out
    unsafe = [p for p, _ in tests if not SAFE_PATH.fullmatch(p) or ".." in p.split("/")]
    if unsafe:
        out["message"] = f"Test first: a test's path holds characters the check does not run: {', '.join(repr(p) for p in unsafe[:5])}; rename it."
        return out
    if len(tests) > MAX_TESTS:
        out["message"] = (f"Test first: this pull request adds or changes {len(tests)} tests, more than the {MAX_TESTS} the check "
                          "runs at the base and at the head: split it.")
        return out
    for path, way_name in tests:
        way = repro["ways"][way_name]
        out["tests"].append({"test": path, "way": way_name, "sandbox": str(way.get("sandbox") or ""),
                             "spec": spec_of(way, path, number, central, kind)})
    out["setup"] = decl["setup"]
    out["result"] = "run"
    out["message"] = "Test first: " + ", ".join(f"`{t['test']}` ({t['way']})" for t in out["tests"]) + " run at the base and at the head."
    return out


def verdict(kind_of_pr, results):
    """(passed, message) from each test's outcome at the base and at the
    head ({test, base, head}, each one of OUTCOMES)."""
    def names(rs):
        return ", ".join(f"`{r['test']}`" for r in rs)
    if not results:
        return False, "A test that fails before the change is missing: no test ran."
    limited = [r for r in results if "limit" in (r["base"], r["head"]) or r["base"] not in OUTCOMES or r["head"] not in OUTCOMES]
    if limited:
        return False, (f"Test first: {names(limited)} could not run (its setup failed or it took longer than its way's minutes): "
                       "the check has no verdict, and no verdict never passes it. Run it again once the environment is fixed.")
    failing = [r for r in results if r["head"] != "passed"]
    if failing:
        return False, f"Test first: {names(failing)} does not pass at the head ({', '.join(r['head'] for r in failing)}): the change must make every test it carries pass."
    if kind_of_pr == "fix":
        proving = [r for r in results if r["base"] == "reproduced"]
        if not proving:
            return False, (f"The test does not show the bug: {names(results)} also passes at the base, or breaks there without "
                           "failing an assertion. A fix's test fails on the code as it was, on an assertion of what the bug breaks, "
                           "and passes with the fix.")
    else:
        proving = [r for r in results if r["base"] in ("reproduced", "broken")]
        if not proving:
            return False, (f"A test that fails before the change is missing: {names(results)} also passes at the base, so it "
                           "tests nothing the feature adds.")
    return True, f"Test first: {names(proving)} fails at the base and passes at the head."


def outcome_of(text):
    found = re.findall(r"^outcome=([a-z]+)$", text or "", re.M)
    return found[-1] if found else ""


def run_one(root, central, test, ref, test_ref, out_dir):
    """The outcome of TEST (plan's entry) as committed at TEST_REF, run
    against REF's tree, through the way's sandbox or command."""
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_OUTPUT"}
    env["TEST_REF"] = test_ref
    if test["sandbox"]:
        cmd = ["bash", os.path.join(central, "scripts", "repro-sandbox.sh"), "run-ref", ref, test["test"]]
    else:
        env["SPEC"] = json.dumps(test["spec"], separators=(",", ":"))
        env.pop("THEME", None)
        cmd = ["bash", os.path.join(central, "scripts", "repro-run.sh"), "run-ref", ref, test["test"], out_dir]
    got = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True)
    sys.stderr.write(got.stdout[-4000:] + got.stderr[-2000:])
    found = outcome_of(got.stdout)
    return found if found in OUTCOMES else "limit"


def run(root, central, tests, kind_of_pr, base, head):
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, test in enumerate(tests):
            if not SAFE_PATH.fullmatch(test["test"]) or ".." in test["test"].split("/"):
                raise ValueError(f"not a test path: {test['test']!r}")
            at_base = run_one(root, central, test, base, head, os.path.join(tmp, f"{i}-base"))
            at_head = run_one(root, central, test, head, head, os.path.join(tmp, f"{i}-head"))
            results.append({"test": test["test"], "base": at_base, "head": at_head})
    ok, message = verdict(kind_of_pr, results)
    return ok, message, results


def summary(message, results=()):
    lines = ["### Test first", "", message, ""]
    if results:
        lines += ["| Test | At the base | At the head |", "| --- | --- | --- |"]
        lines += [f"| `{r['test']}` | {r['base']} | {r['head']} |" for r in results]
        lines.append("")
    text = "\n".join(lines)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return text


def emit(pairs):
    ways_mod.emit(pairs)


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        ok = got == want
        failed += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f": got {got!r}, want {want!r}"))

    central = os.path.dirname(HERE)
    check("the type of a title", [pr_type(t) for t in ("fix: a", "feat(x)!: b", "docs: c", "nonsense")],
          [("fix", False), ("feat", True), ("docs", False), ("", False)])
    decl = merged({"setup": ["a"], "tests": [{"paths": ["tests/**/test_*.py"], "way": "unit"}], "not-tests": ["tests/fixtures/**"]},
                  None, {"tests": [{"paths": ["spec/*.py"], "way": "unit"}], "not-tests": ["tests/release/**"]})
    check("the layers merge: setup replaced, tests and not-tests added", (decl["setup"], len(decl["tests"]), decl["not-tests"]),
          (["a"], 2, ["tests/fixtures/**", "tests/release/**"]))
    check("no layer is no declaration", merged(None, None, {}.get(KEY)), None)
    check("a valid declaration has no problem", problems(decl, {"unit": {}}), [])
    check("a way of no repro: is a problem", problems(decl, {}) != [], True)
    check("C4: a scenario, a fixture or an expected output is never a test",
          tests_of(decl, ["tests/fixtures/test_x.py", "tests/release/test_s.py", "tests/a/test_b.py", "src/x.py"]),
          [("tests/a/test_b.py", "unit")])
    ok, msg = verdict("fix", [{"test": "t.py", "base": "reproduced", "head": "passed"}])
    check("C1: a test failing at the base and passing at the head passes, named", (ok, "`t.py` fails at the base and passes at the head" in msg), (True, True))
    ok, msg = verdict("fix", [{"test": "t.py", "base": "passed", "head": "passed"}])
    check("C3: a fix's test that passes at the base fails: it does not show the bug", (ok, msg.startswith("The test does not show the bug: `t.py`")), (False, True))
    ok, msg = verdict("fix", [{"test": "t.py", "base": "broken", "head": "passed"}])
    check("C3: one that only breaks at the base is named the same way", (ok, msg.startswith("The test does not show the bug")), (False, True))
    ok, msg = verdict("feat", [{"test": "t.py", "base": "broken", "head": "passed"}])
    check("a feat's test that breaks at the base (the code is new) passes", ok, True)
    ok, msg = verdict("feat", [{"test": "t.py", "base": "passed", "head": "passed"}])
    check("a feat's test that passes at the base fails as a missing test", (ok, msg.startswith("A test that fails before the change is missing")), (False, True))
    ok, msg = verdict("fix", [{"test": "t.py", "base": "reproduced", "head": "reproduced"}])
    check("a test that fails at the head fails, named", (ok, "`t.py` does not pass at the head" in msg), (False, True))
    ok, msg = verdict("fix", [{"test": "t.py", "base": "limit", "head": "passed"}])
    check("a test that could not run never passes", (ok, "could not run" in msg), (False, True))

    with tempfile.TemporaryDirectory() as d:
        def sh(*args, cwd=d):
            subprocess.run(args, cwd=cwd, check=True, capture_output=True)

        def commit(files, msg):
            for path, text in files.items():
                os.makedirs(os.path.join(d, os.path.dirname(path)) or d, exist_ok=True)
                with open(os.path.join(d, path), "w") as fh:
                    fh.write(text)
            sh("git", "add", "-A")
            sh("git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)
            return git(d, "rev-parse", "HEAD").stdout.strip()
        sh("git", "init", "-q", ".")
        policy = ("repro:\n  ways:\n    py:\n      layer: logic\n      test: tests/repro/test_issue_{n}.py\n      run: python3 {test}\n      junit: build/j.xml\n"
                  "test-first:\n  tests:\n    - paths: ['tests/**/test_*.py']\n      way: py\n  not-tests: ['tests/fixtures/**']\n")
        base = commit({".github/review-policy.yml": policy, "src/a.txt": "old\n"}, "chore: base")
        head = commit({"src/a.txt": "new\n", "tests/fixtures/test_f.py": "x"}, "fix: only a fixture")
        os.environ["REPO"] = "Acme/none-such"
        p = plan(d, central, "fix: only a fixture", base, head, "none-such", 1)
        check("C2/C4: a fix with only a fixture fails: the test is missing", (p["result"], p["message"].startswith("A test that fails before the change is missing")), ("fail", True))
        p = plan(d, central, "docs: words", base, head, "none-such", 1)
        check("C5: a docs pull request passes and says why, running nothing", (p["result"], "alters no behaviour" in p["message"], p["tests"]), ("pass", True, []))
        head2 = commit({"tests/unit/test_a.py": "x"}, "fix: with a test")
        p = plan(d, central, "fix: with a test", base, head2, "none-such", 7)
        check("C1: a fix with a test runs it, with its way's command filled", (p["result"], [t["test"] for t in p["tests"]], p["tests"][0]["spec"]["run"] if p["tests"] else ""),
              ("run", ["tests/unit/test_a.py"], "python3 tests/unit/test_a.py"))
        # The declaration is read at the base: a pull request widening
        # `not-tests` does not exempt itself.
        head3 = commit({".github/review-policy.yml": policy.replace("tests/fixtures/**", "tests/**")}, "fix: exempt")
        p = plan(d, central, "fix: exempt", base, head3, "none-such", 7)
        check("the declaration is the base's, never the pull request's", p["result"], "run")
        base4 = commit({".github/review-policy.yml": "high-risk: []\n"}, "chore: no declaration")
        head4 = commit({"tests/unit/test_b.py": "x"}, "fix: b")
        p = plan(d, central, "fix: b", base4, head4, "none-such", 7)
        check("B1: a fix in a repository that declares no test-first fails, saying how", (p["result"], f"declares no `{KEY}:`" in p["message"], "review-policy.yml" in p["message"]), ("fail", True, True))
    print("all tests passed" if not failed else f"{failed} failed")
    return 1 if failed else 0


def main():
    args = sys.argv[1:]
    root = os.environ.get("DIR") or "."
    central = os.environ.get("CENTRAL") or os.path.dirname(HERE)
    if args == ["--test"]:
        return self_test()
    if args == ["plan"]:
        name = (os.environ.get("REPO") or os.environ.get("GITHUB_REPOSITORY") or "").split("/")[-1]
        p = plan(root, central, os.environ.get("TITLE") or "", os.environ.get("BASE") or "HEAD^1", os.environ.get("HEAD") or "HEAD",
                 name, os.environ.get("NUMBER") or "0", os.environ.get("DECLARATION_AT_BASE") == "1")
        summary(p["message"])
        emit({"result": p["result"], "type": p["type"], "message": p["message"],
              "tests": json.dumps(p["tests"], separators=(",", ":")), "setup": json.dumps(p["setup"], separators=(",", ":"))})
        if p["result"] == "fail":
            print(f"::error::{p['message']}")
            return 1
        return 0
    if args == ["run"]:
        tests = json.loads(os.environ.get("TESTS") or "[]")
        ok, message, results = run(root, central, tests, os.environ.get("TYPE") or "", os.environ.get("BASE") or "HEAD^1", os.environ.get("HEAD") or "HEAD")
        print(summary(message, results))
        if not ok:
            print(f"::error::{message}")
        return 0 if ok else 1
    if args == ["verdict"]:
        ok, message = verdict(os.environ.get("TYPE") or "", json.loads(os.environ.get("RESULTS") or "[]"))
        print(message)
        return 0 if ok else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
