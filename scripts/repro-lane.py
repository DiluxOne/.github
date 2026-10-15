#!/usr/bin/env python3
"""The `bugfix-reproduced` lane (#84): a bug the reproduction confirmed with
a failing test, handed to the autopilot without a person accepting it.

When issue-repro.yml reproduces a report, dilux-bot opens an issue of its
own for the fix (the lane's issue): its PRD is written here, from fixed text
and the reproduction's facts, never from the report's words, so nothing an
outsider wrote reaches the autopilot as its specification. The failing test
is the specification. The PRD names it, its SHA-256 and the branch that holds
it; the autopilot keeps it out of its working tree and runs it only in the
sandbox (scripts/repro-sandbox.sh), and gate G7 merges only a pull request
that carries it byte for byte.

  repro-lane.py prd        the lane issue's title and body (JSON), from
                           REPORT (the report's number), RUN_URL (the
                           reproduction's run), SHA256 (the test's), BASE
                           (the commit it failed on)
  repro-lane.py evidence   the reproduction named in BODY's PRD (JSON:
                           report, test, sha256, branch); exit 1 when it
                           names none
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


def test_path(report):
    return f"tests/Unit/Repro/Issue{report}Test.php"


def branch(report):
    return f"test/repro-issue-{report}"


def prd(report, run_url, sha256, base):
    """The lane issue: a title and a body that passes G1. Every value is
    checked: a number, a run URL, two hashes; nothing else goes in."""
    if not re.fullmatch(r"[1-9][0-9]{0,6}", str(report)):
        raise ValueError(f"not an issue number: {report!r}")
    if not re.fullmatch(r"https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/actions/runs/\d+", run_url or ""):
        raise ValueError(f"not a workflow run URL: {run_url!r}")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        raise ValueError("not a SHA-256")
    if not re.fullmatch(r"[0-9a-f]{40}", base or ""):
        raise ValueError("not a commit")
    test = test_path(report)
    body = f"""<!-- dx-lane: {LANE} run: {run_url} -->
### Problem

The report in #{report} describes a defect, and the reproduction confirmed it: a unit test written from the report fails on the default branch at `{base}` ({run_url}).

Reproduction test: `{test}`, SHA-256 `{sha256}`, on the branch `{branch(report)}`.

The test is the specification: it asserts what the report expected. It was written from an outsider's text, so it runs only in the reproduction's sandbox (no network, no environment, no secrets), never in the autopilot's working tree.

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
    """{report, test, sha256, branch} from the PRD's Problem, or None. Read
    from the PRD only (the part a seal covers), never from the report."""
    problem = dict(schema.parse(body)[0]).get("Problem", "")
    for line in problem.split("\n"):
        m = EVIDENCE.match(line.strip())
        if m and m.group(2) == m.group(5):
            return {"report": int(m.group(2)), "test": m.group(1), "sha256": m.group(3), "branch": m.group(4)}
    return None


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
        check("wiring: a hand-off that fails says so on the report", "failure()" in steps["The hand-off failed"]["if"], True)
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
            print(json.dumps(prd(os.environ.get("REPORT", ""), os.environ.get("RUN_URL", ""), os.environ.get("SHA256", ""), os.environ.get("BASE", ""))))
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
