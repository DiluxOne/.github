#!/usr/bin/env python3
"""A job after one that survives skipped jobs must survive them too (#257).

GitHub runs a job only if every job in its `needs` chain succeeded, unless
its `if:` calls a status function (`always()`, `!cancelled()`, `success()`,
`failure()`, `cancelled()`). A job written to run after an optional one
(`if: always() && ...`) runs; the job after it, with a plain condition, is
skipped, because a job further up was. That is how the autopilot stopped
starting after #255 added the optional `diagnose` job to issue-repro.yml.

This fails a workflow where a job needs one whose `if:` starts with
`always()` or `!cancelled()` and has no status function of its own.

    needs-chain.py [workflow.yml ...]   default: .github/workflows/*.yml
    needs-chain.py --test
"""
import glob
import re
import sys

import yaml

STATUS = re.compile(r"\b(always|success|failure|cancelled)\(\)")
SURVIVES = re.compile(r"^\s*(\$\{\{\s*)?(always\(\)|!\s*cancelled\(\))")


def problems(workflow):
    jobs = (workflow or {}).get("jobs") or {}
    out = []
    for name, job in jobs.items():
        needs = job.get("needs") or []
        if isinstance(needs, str):
            needs = [needs]
        cond = str(job.get("if", ""))
        if STATUS.search(cond):
            continue
        for need in needs:
            if SURVIVES.match(str((jobs.get(need) or {}).get("if", ""))):
                out.append(f"job `{name}` needs `{need}`, which runs after skipped jobs, but its if has no status function: add `!cancelled() && needs.{need}.result == 'success'`")
    return out


def test():
    wf = lambda s: yaml.safe_load(s)
    bad = wf("""
jobs:
  a: {}
  b: {needs: a, if: "always() && needs.a.result == 'success'"}
  c: {needs: [b], if: "needs.b.outputs.x != ''"}
""")
    assert problems(bad) and "`c`" in problems(bad)[0], problems(bad)
    good = wf("""
jobs:
  a: {}
  b: {needs: a, if: "${{ !cancelled() && needs.a.result == 'success' }}"}
  c: {needs: [b], if: "!cancelled() && needs.b.result == 'success'"}
  e: {needs: a}
""")
    assert problems(good) == [], problems(good)
    assert problems(wf("jobs:\n  a: {needs: b}\n")) == []
    plain = wf("""
jobs:
  a: {}
  b: {needs: a, if: "always()"}
  c: {needs: [a, b]}
""")
    assert len(problems(plain)) == 1 and "`b`" in problems(plain)[0], problems(plain)
    print("needs-chain: ok")


def main(argv):
    if argv == ["--test"]:
        return test()
    files = argv or sorted(glob.glob(".github/workflows/*.yml"))
    bad = 0
    for path in files:
        with open(path) as f:
            for p in problems(yaml.safe_load(f)):
                print(f"::error file={path}::{p}")
                bad += 1
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
