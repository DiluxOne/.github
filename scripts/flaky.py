#!/usr/bin/env python3
"""The flaky tests of an E2E run (#479): a test that failed and then passed
on its retry, read from Playwright's JSON report.

plugin-tests-wp.yml runs a suite whose command is Playwright's own with one
retry and the JSON reporter beside the list one (scripts/e2e-run.sh,
FLAKY_REPORT). Playwright then passes a run whose only failures passed on
their retry (`flaky`): the pull request stays in the merge queue. This
script reports each of those with its spec and line, as a warning on that
line of the check and in the job's summary, so the repository's agent fixes
it; the weekly numbers count them (scripts/flow-numbers.py).

  flaky.py list REPORT      one JSON line per flaky test: {"spec", "line",
                            "title"}, the spec relative to the checkout
  flaky.py annotate REPORT  a `::warning file=…,line=…::` line per flaky
                            test, and the list in $GITHUB_STEP_SUMMARY when
                            set; nothing for a report that is missing or
                            not JSON (a run that never started)
  flaky.py --test           self-test

Exit 0 always but for usage: a flaky test is reported, never a failure.
"""
import json
import os
import sys


def tests_of(suite):
    """(spec, test) for every test under a suite, its nested suites too."""
    for spec in suite.get("specs") or []:
        for test in spec.get("tests") or []:
            yield spec, test
    for child in suite.get("suites") or []:
        yield from tests_of(child)


def flaky(report, cwd="."):
    """The flaky tests of a Playwright JSON report (dict), in its order, each
    once: {"spec", "line", "title"}."""
    root = (report.get("config") or {}).get("rootDir") or ""
    out, seen = [], set()
    for suite in report.get("suites") or []:
        for spec, test in tests_of(suite):
            if test.get("status") != "flaky":
                continue
            path = os.path.join(root, str(spec.get("file") or "")) if root else str(spec.get("file") or "")
            if os.path.isabs(path):
                path = os.path.relpath(path, os.path.abspath(cwd))
            entry = {"spec": path.replace(os.sep, "/"), "line": int(spec.get("line") or 1), "title": str(spec.get("title") or "")}
            key = (entry["spec"], entry["line"], entry["title"])
            if key not in seen:
                seen.add(key)
                out.append(entry)
    return out


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def clean(text):
    """Text safe inside a workflow command: no newline, no `::`."""
    return " ".join(str(text).split()).replace("::", ": :").replace("%", "%25")


def annotations(found):
    return [f"::warning file={clean(f['spec'])},line={f['line']},title=Flaky test::{clean(f['title'])} failed, then passed on its retry: "
            f"fix it, it does not stop the merge queue (DiluxOne/.github#479)" for f in found]


def summary(found):
    if not found:
        return ""
    lines = ["### Flaky tests", "", "They failed, then passed on their retry, so the run passed (#479). Fix them:", ""]
    lines += [f"- `{f['spec']}:{f['line']}` {f['title']}" for f in found]
    return "\n".join(lines) + "\n"


def self_test():
    import tempfile
    fails = []

    def check(name, got, want):
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        if got != want:
            fails.append(name)

    with tempfile.TemporaryDirectory() as d:
        report = {"config": {"rootDir": os.path.join(d, "tests", "e2e")}, "suites": [
            {"file": "a.spec.ts", "specs": [
                {"title": "logs in", "file": "a.spec.ts", "line": 12, "tests": [{"status": "flaky"}]},
                {"title": "logs out", "file": "a.spec.ts", "line": 30, "tests": [{"status": "expected"}]}],
             "suites": [{"specs": [{"title": "nested", "file": "a.spec.ts", "line": 44, "tests": [{"status": "flaky"}, {"status": "flaky"}]}]}]},
            {"file": "b.spec.ts", "specs": [{"title": "breaks", "file": "b.spec.ts", "line": 3, "tests": [{"status": "unexpected"}]}]}]}
        got = flaky(report, d)
        check("a flaky test, nested ones too, each once, with its spec relative to the checkout and its line",
              got, [{"spec": "tests/e2e/a.spec.ts", "line": 12, "title": "logs in"}, {"spec": "tests/e2e/a.spec.ts", "line": 44, "title": "nested"}])
        check("one that passed, or failed on its retry too, is not flaky", [f["title"] for f in got if f["title"] in ("logs out", "breaks")], [])
        check("a warning on the spec's line", annotations(got)[0].startswith("::warning file=tests/e2e/a.spec.ts,line=12,title=Flaky test::logs in failed"), True)
        check("a title cannot end the command or add another", annotations([{"spec": "x", "line": 1, "title": "a\n::error::b"}])[0].count("::"), 2)
        check("the summary names spec:line", "`tests/e2e/a.spec.ts:12` logs in" in summary(got), True)
        check("none, no summary", summary([]), "")
        check("a report with no rootDir keeps the file as it is", flaky({"suites": [{"specs": [{"file": "c.spec.ts", "line": 2, "title": "t", "tests": [{"status": "flaky"}]}]}]}),
              [{"spec": "c.spec.ts", "line": 2, "title": "t"}])
        path = os.path.join(d, "r.json")
        with open(path, "w") as fh:
            fh.write("not json")
        check("a report that is not JSON, or missing, is none", (load(path), load(os.path.join(d, "none.json"))), (None, None))
    print("all tests passed" if not fails else f"{len(fails)} failed")
    return 1 if fails else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if len(argv) == 2 and argv[0] in ("list", "annotate"):
        report = load(argv[1])
        found = flaky(report) if report else []
        if argv[0] == "list":
            for f in found:
                print(json.dumps(f))
            return 0
        for line in annotations(found):
            print(line)
        text = summary(found)
        if text and os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
                fh.write(text)
        print(f"{len(found)} flaky test(s).")
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
