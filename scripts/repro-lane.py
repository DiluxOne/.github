#!/usr/bin/env python3
"""The `bugfix-reproduced` lane (#84): a bug the reproduction confirmed with
a failing test, handed to the autopilot without a person accepting it.

When issue-repro.yml reproduces a report, dilux-bot opens an issue of its
own for the fix (the lane's issue): its PRD is written here, from fixed text
and the reproduction's facts, never from the report's words, so nothing an
outsider wrote reaches the autopilot as its specification. The failing test
is the specification. The PRD names it, its SHA-256 and the branch that holds
it; the autopilot keeps it out of its working tree and runs it only in the
sandbox, and gate G7 merges only a pull request that carries it byte for
byte. A unit test runs in scripts/repro-sandbox.sh. A test of any other way
(#397: a browser test, a pytest, any command that writes a JUnit report,
scripts/repro-ways.py) runs the way it was written, through
scripts/repro-run.sh: the PRD carries that way too (its name, its setup,
command and report, the theme the report named), sealed with the rest, so
the autopilot and G7 run the test exactly as the reproduction did.

  repro-lane.py prd        the lane issue's title and body (JSON), from
                           REPORT (the report's number), RUN_URL (the
                           reproduction's run), SHA256 (the test's), BASE
                           (the commit it failed on); for a test of a way
                           that is a command, WAY (its name), SPEC (the way,
                           JSON from repro-ways.py resolve), NOUN (what its
                           test is called) and THEME (a slug, or empty)
  repro-lane.py evidence   the reproduction named in BODY's PRD (JSON:
                           report, test, sha256, branch; and, for a way that
                           is a command, way, spec and theme); exit 1 when
                           it names none
  repro-lane.py --test     self-test

Environment: BODY (a file holding the issue's body) for evidence.
"""
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LANE = "bugfix-reproduced"
AI_LINE = "🤖 AI-generated · Claude Opus 5.5 (Anthropic)"


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


schema = _load("issue_schema", "issue-schema.py")

# The one line of the PRD's Problem that names the evidence. The test's path
# and the branch both carry the report's number, and must agree.
EVIDENCE = re.compile(r"^Reproduction test: `(tests/Unit/Repro/Issue([1-9][0-9]{0,6})Test\.php)`, "
                      r"SHA-256 `([0-9a-f]{64})`, on the branch `(test/repro-issue-([1-9][0-9]{0,6}))`")


# A way that is a command (#397): the line after the evidence that says how
# its test runs, the way's JSON on one line. Only the keys scripts/repro-run.sh
# reads; no backtick, so the line cannot be cut short.
WAY_LINE = re.compile(r"^Reproduction way: `([a-z][a-z0-9-]{0,39})`(?:, with the theme `([a-z0-9][a-z0-9-]{0,59})`)?, "
                      r"run by scripts/repro-run\.sh as `(\{[^`]*\})`\.$")
COMMAND_EVIDENCE = re.compile(r"^Reproduction test: `([A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*)`, "
                              r"SHA-256 `([0-9a-f]{64})`, on the branch `(test/repro-issue-([1-9][0-9]{0,6}))`\.$")
SPEC_KEYS = {"setup", "theme", "run", "junit", "teardown", "minutes", "test", "case", "assertion"}


def way_spec(spec, report):
    """The way's JSON, checked: a command way scripts/repro-run.sh can run
    (`run`, `junit`, its `test` carrying the report's number), only the keys
    it reads, nothing that would end the PRD's line. ValueError otherwise."""
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except ValueError:
            raise ValueError("the way is not JSON")
    if not isinstance(spec, dict):
        raise ValueError("the way is not an object")
    unknown = set(spec) - SPEC_KEYS
    if unknown:
        raise ValueError(f"the way has keys scripts/repro-run.sh does not read: {sorted(unknown)}")
    for key in ("run", "junit", "test"):
        if not isinstance(spec.get(key), str) or not spec[key].strip():
            raise ValueError(f"the way has no `{key}`")
    test = spec["test"]
    if not re.fullmatch(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*", test) or ".." in test.split("/") or test.startswith(".github/"):
        raise ValueError(f"not a reproduction test's path: {test!r}")
    if not re.search(rf"(^|[^0-9]){report}([^0-9]|$)", test):
        raise ValueError(f"the test {test!r} does not carry the report's number")
    line = json.dumps(spec, separators=(",", ":"), sort_keys=True)
    if "`" in line:
        raise ValueError("the way's JSON holds a backtick")
    return spec


def test_path(report):
    return f"tests/Unit/Repro/Issue{report}Test.php"


def branch(report):
    return f"test/repro-issue-{report}"


def prd(report, run_url, sha256, base, way="", spec=None, noun="", theme=""):
    """The lane issue: a title and a body that passes G1. Every value is
    checked: a number, a run URL, two hashes; for a way that is a command
    (#397), its name, its JSON (way_spec), what its test is called and a
    theme's slug; nothing else goes in. Without a way, a unit test's PRD,
    exactly as it was before #397."""
    if not re.fullmatch(r"[1-9][0-9]{0,6}", str(report)):
        raise ValueError(f"not an issue number: {report!r}")
    if not re.fullmatch(r"https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/actions/runs/\d+", run_url or ""):
        raise ValueError(f"not a workflow run URL: {run_url!r}")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        raise ValueError("not a SHA-256")
    if not re.fullmatch(r"[0-9a-f]{40}", base or ""):
        raise ValueError("not a commit")
    if spec:
        spec = way_spec(spec, report)
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", way or ""):
            raise ValueError(f"not a way's name: {way!r}")
        if theme and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,59}", theme):
            raise ValueError(f"not a theme's slug: {theme!r}")
        noun = noun if re.fullmatch(r"[A-Za-z][A-Za-z -]{0,39}", noun or "") else "test"
        test = spec["test"]
        themed = f", with the theme `{theme}`" if theme else ""
        what = f"a {noun} written from the report"
        how = (f"Reproduction way: `{way}`{themed}, run by scripts/repro-run.sh as "
               f"`{json.dumps(spec, separators=(',', ':'), sort_keys=True)}`.\n\n")
        where = ("it runs only the way it was written, in the reproduction's sandbox (scripts/repro-run.sh: the way's setup "
                 "before the test is in the tree, then the test alone as a user of its own, with no environment, no secrets "
                 "and no network but the machine's), never in the autopilot's working tree")
    else:
        test = test_path(report)
        what, how = "a unit test written from the report", ""
        where = "it runs only in the reproduction's sandbox (no network, no environment, no secrets), never in the autopilot's working tree"
    body = f"""<!-- dx-lane: {LANE} run: {run_url} -->
### Problem

The report in #{report} describes a defect, and the reproduction confirmed it: {what} fails on the default branch at `{base}` ({run_url}).

Reproduction test: `{test}`, SHA-256 `{sha256}`, on the branch `{branch(report)}`.

{how}The test is the specification: it asserts what the report expected. It was written from an outsider's text, so {where}.

### Scope

- Fix the defect the reproduction test exercises, in the code it exercises.
- Add the reproduction test to the default branch, exactly as written.

### Out of scope

- Changing, moving, skipping or deleting the reproduction test: it is the evidence, and gate G7 checks its SHA-256.
- Any other behaviour the report mentions that the test does not exercise: a new issue.

### Acceptance criteria

- C1: Given the reproduction test {test} exactly as written, when it runs on the fix, then it passes, where it failed on {base[:12]}.

### Criticality

Normal

{AI_LINE}
"""
    return {"title": f"The bug reproduced from #{report}", "body": body}


def evidence(body):
    """{report, test, sha256, branch} from the PRD's Problem, or None; and,
    for a way that is a command (#397), its way, spec and theme. Read from
    the PRD only (the part a seal covers), never from the report."""
    problem = dict(schema.parse(body)[0]).get("Problem", "")
    lines = [line.strip() for line in problem.split("\n")]
    for line in lines:
        m = EVIDENCE.match(line)
        if m and m.group(2) == m.group(5):
            return {"report": int(m.group(2)), "test": m.group(1), "sha256": m.group(3), "branch": m.group(4)}
    # A command way's test (#397): its path is the way's own, so it counts
    # only with exactly one way's line, whose `test` it is, and the branch
    # of the same report.
    ways = [m for m in (WAY_LINE.match(line) for line in lines) if m]
    tests = [m for m in (COMMAND_EVIDENCE.match(line) for line in lines) if m]
    if len(ways) != 1 or len(tests) != 1:
        return None
    m, w = tests[0], ways[0]
    report = int(m.group(4))
    try:
        spec = way_spec(w.group(3), report)
    except ValueError:
        return None
    if spec["test"] != m.group(1):
        return None
    return {"report": report, "test": m.group(1), "sha256": m.group(2), "branch": m.group(3),
            "way": w.group(1), "spec": spec, "theme": w.group(2) or ""}


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        if got == want:
            print(f"ok   {name}")
        else:
            print(f"FAIL {name}: got {got!r}, want {want!r}")
            failed = 1

    run = "https://github.com/DiluxOne/x/actions/runs/42"
    sha, base = "a" * 64, "b" * 40
    p = prd(12, run, sha, base)
    result = schema.check(p["body"])
    check("the lane issue's PRD passes G1", (result["ok"], result["errors"]), (True, []))
    check("it has one criterion, the reproduction test", result["criteria"], ["C1"])
    check("its title carries no text from the report", p["title"], "The bug reproduced from #12")
    check("it names the lane's run in the organisation's marker", p["body"].splitlines()[0], f"<!-- dx-lane: {LANE} run: {run} -->")
    check("the evidence reads back", evidence(p["body"]), {"report": 12, "test": "tests/Unit/Repro/Issue12Test.php", "sha256": sha, "branch": "test/repro-issue-12"})
    check("the sealed part holds the evidence (a seal covers the hash)", sha in schema.part_text(p["body"], "prd"), True)
    check("C1 names the test, so the Spec's line for it is that path", "tests/Unit/Repro/Issue12Test.php" in p["body"].split("### Acceptance criteria", 1)[1], True)
    check("no evidence in a person's issue", evidence("### Problem\n\nIt breaks.\n"), None)
    check("no evidence when the test and the branch disagree", evidence(p["body"].replace("test/repro-issue-12", "test/repro-issue-13")), None)
    check("no evidence outside the Problem", evidence("### Scope\n\n" + "Reproduction test: `tests/Unit/Repro/Issue12Test.php`, SHA-256 `" + sha + "`, on the branch `test/repro-issue-12`."), None)
    check("no evidence for a path outside tests/Unit/Repro", evidence(p["body"].replace("tests/Unit/Repro/Issue12Test.php", "src/Issue12Test.php")), None)
    # #397: a test of another way, with the way it runs in.
    spec = {"setup": ["npm ci"], "run": "npx playwright test {test}", "junit": "build/j.xml", "minutes": 20, "test": "tests/e2e/repro/issue-12.spec.ts"}
    w = prd(12, run, sha, base, "browser", spec, "browser test", "astra")
    wr = schema.check(w["body"])
    check("#397 C1 another way's PRD passes G1, with the one criterion", (wr["ok"], wr["criteria"]), (True, ["C1"]))
    check("#397 C1 its evidence reads back the test, the way and the theme",
          evidence(w["body"]), {"report": 12, "test": "tests/e2e/repro/issue-12.spec.ts", "sha256": sha, "branch": "test/repro-issue-12", "way": "browser", "spec": spec, "theme": "astra"})
    check("#397 C1 the way is in the sealed part (a seal covers how the test runs)", '"run":"npx playwright test {test}"' in schema.part_text(w["body"], "prd"), True)
    check("#397 C1 it says what its test is, never a unit test", ("a browser test written from the report" in w["body"], "unit test" in w["body"]), (True, False))
    check("#397 C3 a unit test's PRD carries no way, and its evidence is what it was", ("Reproduction way:" in p["body"], sorted(evidence(p["body"])), "repro-sandbox" in p["body"]), (False, ["branch", "report", "sha256", "test"], False))
    check("#397 the way's test must be the evidence's", evidence(w["body"].replace("`tests/e2e/repro/issue-12.spec.ts`, SHA", "`tests/e2e/repro/issue-13.spec.ts`, SHA")), None)
    check("#397 no evidence for a way's test without the way's line", evidence(w["body"].replace("Reproduction way:", "Way:")), None)
    check("#397 no evidence with two ways' lines", evidence(w["body"].replace("### Scope", w["body"].split("\n\n")[3] + "\n\n### Scope")), None)
    for bad, args in (("a way with no run", ("browser", {**spec, "run": ""})), ("a way with keys repro-run.sh does not read", ("browser", {**spec, "env": "x"})),
                      ("a test outside the tree", ("browser", {**spec, "test": "../issue-12.spec.ts"})), ("a test under .github", ("browser", {**spec, "test": ".github/workflows/issue-12.yml"})),
                      ("a test of another report", ("browser", {**spec, "test": "tests/e2e/repro/issue-123.spec.ts"})),
                      ("a backtick that would cut the line", ("browser", {**spec, "run": "echo `id` {test}"})), ("a way's name that is not one", ("Browser!", spec))):
        try:
            prd(12, run, sha, base, *args)
            got = "accepted"
        except ValueError:
            got = "refused"
        check(f"#397 refuses {bad}", got, "refused")
    try:
        prd(12, run, sha, base, "browser", spec, "browser test", "x; rm -rf /")
        got = "accepted"
    except ValueError:
        got = "refused"
    check("#397 refuses a theme that is not a slug", got, "refused")
    autonomy = _load("autonomy", "autonomy.py")
    pol = autonomy.merge(autonomy.load(os.path.join(HERE, "..", "policy", "autonomy.yml")), {})
    opened = {"author": {"login": "dilux-bot"}, "body": p["body"], "labels": {"nodes": [{"name": "lane:" + LANE}]},
              "timelineItems": {"nodes": [{"__typename": "LabeledEvent", "label": {"name": "lane:" + LANE}, "actor": {"__typename": "Bot", "login": "dilux-bot"}}]}}
    caller = {"id": 42, "path": ".github/workflows/issues.yml", "referenced_workflows": [{"path": "DiluxOne/.github/.github/workflows/issue-repro.yml@refs/tags/v5"}]}
    check("the issue it writes, opened by dilux-bot from a reproduction's run, is one the lane accepts", autonomy.lane_accepts(pol, opened, caller, "DiluxOne/x", "")[0], True)
    # The workflows' wiring, read as data (PyYAML; the scripts job has it).
    try:
        import yaml
    except ImportError:
        yaml = None
        print("skip the workflows' wiring: PyYAML is not installed here; the scripts job reads them")
    if yaml:
        wf = lambda name: yaml.safe_load(open(os.path.join(HERE, "..", ".github", "workflows", name), encoding="utf-8"))
        repro_wf, merge_wf = wf("issue-repro.yml"), wf("auto-merge.yml")
        jobs = repro_wf["jobs"]
        steps = {s.get("id") or s.get("name"): s for s in jobs["report"]["steps"]}
        check("wiring: the run job runs the test in the shared sandbox", any("repro-sandbox.sh run " in (s.get("run") or "") for s in jobs["run"]["steps"]), True)
        check("wiring: the report asks whether the lane is open before handing anything over", "lane-open bugfix-reproduced" in steps["open"]["run"], True)
        check("wiring: a failed read of the lane's open issues pushes nothing (fails closed)", ("if ! held=$(" in steps["report"]["run"], "exit 1" in steps["report"]["run"].split("if ! held=$(", 1)[1].split("\nfi\n", 1)[0]), (True, True))
        check("wiring: the lane's issue is accepted only by lane-accept, then sealed", ("autonomy.py lane-accept" in steps["lane"]["run"], steps["lane"]["run"].index("lane-accept") < steps["lane"]["run"].index("seal-prd")), (True, True))
        check("wiring: the report hands the accepted issue to the autopilot job", jobs["report"]["outputs"]["lane-issue"], "${{ steps.lane.outputs.issue }}")
        ap = jobs["autopilot"]
        check("wiring: the autopilot job starts only on that issue, in mode start", (ap["needs"], "lane-issue" in ap["if"], ap["with"]["mode"], ap["uses"].split("@")[0]), ("report", True, "start", "DiluxOne/.github/.github/workflows/autopilot.yml"))
        failed_step = steps["The hand-off failed"]
        check("wiring: a hand-off that fails says so on the report, and closes the lane issue it opened",
              ("failure()" in failed_step["if"], "steps.lane.outputs.created" in failed_step["env"]["CREATED"], 'gh issue close "$CREATED"' in failed_step["run"],
               steps["lane"]["run"].index('echo "created=') < steps["lane"]["run"].index("lane-accept")), (True, True, True, True))
        rc = {s.get("id") or s.get("name"): s for s in wf("issue-accepted.yml")["jobs"]["receipt"]["steps"]}
        close = rc["Close the report it came from"]
        check("wiring (#271): a merged fix closes its report, read from the sealed PRD, only on the App's lane issue",
              ("steps.receipt.outputs.pr != ''" in close["if"], "vars.DX_BOT_LOGIN" in close["if"], "repro-lane.py evidence" in close["run"], "checkout -q FETCH_HEAD" in rc["central"]["run"]), (True, True, True, True))
        decide_run = next(s["run"] for s in merge_wf["jobs"]["decide"]["steps"] if s.get("id") == "autopilot")
        check("wiring: G7 gets the lane from GitHub and the test's SHA-256 at the head", ("autopilot.py\" lane" in decide_run, "REPRO_SHA256=$(gh api" in decide_run), (True, True))
    for bad, args in (("a number", ("12; rm", run, sha, base)), ("a run URL", (12, "https://evil.example/actions/runs/1", sha, base)),
                      ("a SHA-256", (12, run, "z" * 64, base)), ("a commit", (12, run, sha, "main"))):
        try:
            prd(*args)
            got = "accepted"
        except ValueError:
            got = "refused"
        check(f"refuses anything that is not {bad}", got, "refused")
    if not failed:
        print("all tests passed")
    return failed


def main(argv):
    if argv[:1] == ["--test"]:
        return self_test()
    if argv[:1] == ["prd"]:
        try:
            print(json.dumps(prd(os.environ.get("REPORT", ""), os.environ.get("RUN_URL", ""), os.environ.get("SHA256", ""), os.environ.get("BASE", ""),
                                 os.environ.get("WAY", ""), os.environ.get("SPEC", "") or None, os.environ.get("NOUN", ""), os.environ.get("THEME", ""))))
        except ValueError as err:
            print(err, file=sys.stderr)
            return 1
        return 0
    if argv[:1] == ["evidence"]:
        with open(os.environ["BODY"], encoding="utf-8") as fh:
            ev = evidence(fh.read())
        if not ev:
            print("the PRD names no reproduction test", file=sys.stderr)
            return 1
        print(json.dumps(ev))
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
