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

And a job that waits on another it does not need (#694): every entry of a
job's `needs` is used, its outputs or its result (`needs.<job>.outputs`,
`needs.<job>.result`) read in the job, or carries a comment `# order: <why>`
naming the gate or the order it keeps (an artifact it downloads, a check
that must pass first), on the entry's line, on the `needs:` line for every
entry written there, or on the comment lines right above either. A need
that is neither only makes the job wait in series, and is removed.

    needs-chain.py [workflow.yml ...]   default: .github/workflows/*.yml
    needs-chain.py --test
"""
import glob
import json
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


ORDER = re.compile(r"#\s*order:\s*\S")
JOB = re.compile(r"^  ([A-Za-z0-9_-]+):\s*(#.*)?$")


def job_blocks(text):
    """{job: [its lines]} of a workflow's text, from `jobs:` on. Pure."""
    out, name, inside = {}, None, False
    for line in text.split("\n"):
        if re.match(r"^jobs:\s*(#.*)?$", line):
            inside = True
            continue
        if inside and re.match(r"^\S", line):
            inside, name = False, None
        if not inside:
            continue
        m = JOB.match(line)
        if m:
            name = m.group(1)
            out[name] = []
        elif name:
            out[name].append(line)
    return out


def ordered(lines):
    """The needs written in a job's `lines` that carry `# order: <why>`:
    on the entry's own line, on the `needs:` line (for each entry written
    there), or on the comment lines right above either. Pure."""
    out, above, inside = set(), False, False
    for line in lines:
        bare = line.strip()
        if bare.startswith("#"):
            above = above or bool(ORDER.search(bare))
            continue
        m = re.match(r"^    needs:\s*(.*)$", line)
        if m:
            inside = True
            value = m.group(1).split("#", 1)[0]
            names = re.findall(r"[A-Za-z0-9_-]+", value)
            if above or ORDER.search(line):
                out |= set(names)
            above = False
            continue
        if inside and re.match(r"^      -\s", line):
            name = line.split("-", 1)[1].split("#", 1)[0].strip()
            if above or ORDER.search(line):
                out.add(name)
            above = False
            continue
        inside, above = False, False
    return out


def unused(workflow, text):
    """Every need of a job that is neither used (its outputs or result read
    in the job) nor carries `# order: <why>` (#694). Pure."""
    jobs = (workflow or {}).get("jobs") or {}
    blocks = job_blocks(text)
    out = []
    for name, job in jobs.items():
        needs = job.get("needs") or []
        if isinstance(needs, str):
            needs = [needs]
        rest = json.dumps({k: v for k, v in (job or {}).items() if k != "needs"})
        keep = ordered(blocks.get(name) or [])
        for need in needs:
            if "toJSON(needs)" in rest or re.search(rf"needs\.{re.escape(need)}\.(outputs|result)\b", rest) or need in keep:
                continue
            out.append(f"job `{name}` needs `{need}` but reads neither its outputs nor its result: say the gate or the order it keeps "
                       f"with a comment `# order: <why>` on it, or remove it so the job does not wait in series")
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
    text = """jobs:
  a:
    runs-on: x
  b:
    runs-on: x
  c:
    # order: after a's artifact, which it downloads
    needs: [a]
  d:
    needs:
      - a  # order: the check a runs must pass first
      - b
    if: needs.b.result == 'success'
  e:
    needs: [a, b]
    steps:
      - run: echo "${{ needs.a.outputs.x }}"
  f:
    needs:
      # order: a must pass first
      - a
      - b
"""
    got = unused(yaml.safe_load(text), text)
    why = ": say the gate or the order it keeps with a comment `# order: <why>` on it, or remove it so the job does not wait in series"
    # A comment line above an entry is that entry's alone.
    assert got == ["job `e` needs `b` but reads neither its outputs nor its result" + why, "job `f` needs `b` but reads neither its outputs nor its result" + why], got
    assert ordered(job_blocks(text)["f"]) == {"a"}, ordered(job_blocks(text)["f"])
    assert job_blocks("on: push\njobs:\n  a:\n    runs-on: x\nenv: {}\n") == {"a": ["    runs-on: x"]}
    # C5: every workflow of this repository holds it.
    for path in sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml"))):
        text = open(path, encoding="utf-8").read()
        assert unused(yaml.safe_load(text), text) == [], (path, unused(yaml.safe_load(text), text))
    print("needs-chain: ok")


def main(argv):
    if argv == ["--test"]:
        return test()
    files = argv or sorted(glob.glob(".github/workflows/*.yml"))
    bad = 0
    for path in files:
        with open(path) as f:
            text = f.read()
        doc = yaml.safe_load(text)
        for p in problems(doc) + unused(doc, text):
            print(f"::error file={path}::{p}")
            bad += 1
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
