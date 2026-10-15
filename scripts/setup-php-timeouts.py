#!/usr/bin/env python3
"""Every workflow job that sets up PHP has time to do it (#173).

shivammathur/setup-php installs PHP on the organisation's runner image,
which carries none by design (#140): from php-builder, with an apt install
of about 200 packages, it alone can take six minutes on a busy VM. A job
that runs it with a shorter `timeout-minutes` is cancelled in "Setup PHP"
before its own work starts, and blocks the pull request.

  setup-php-timeouts.py [workflow ...]   default: .github/workflows/*.yml

Fails naming each job (file, job id) that uses setup-php with a
`timeout-minutes` under 15. A job without one gets GitHub's 360. A timeout
written as an expression (`${{ matrix.suite.timeout }}`) is the caller's
input, bounded where it is read (scripts/test-targets.py), not here.

`setup-php-timeouts.py --test` checks these rules.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

MINIMUM = 15
ACTION = "shivammathur/setup-php@"
HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOWS = os.path.join(HERE, "..", ".github", "workflows")


def read_yaml(path):
    """yq where it is (the runners), PyYAML otherwise (a contributor's machine),
    as scripts/autonomy.py does."""
    if shutil.which("yq"):
        out = subprocess.run(["yq", "-o=json", ".", path], check=True, capture_output=True, text=True).stdout
        return json.loads(out or "{}") or {}
    try:
        import yaml
    except ImportError:
        sys.exit(f"{os.path.basename(sys.argv[0])} needs yq or PyYAML to read {path}")
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def short(minutes):
    """The job's timeout when it is under the minimum, else None."""
    if minutes is None or (isinstance(minutes, str) and "${{" in minutes):
        return None
    try:
        value = float(minutes)
    except (TypeError, ValueError):
        return minutes
    return minutes if value < MINIMUM else None


def problems(paths):
    """One line per job that runs setup-php with too little time."""
    out = []
    for path in paths:
        jobs = (read_yaml(path) or {}).get("jobs") or {}
        for job_id, job in jobs.items():
            steps = (job or {}).get("steps") or []
            if not any(str((st or {}).get("uses", "")).startswith(ACTION) for st in steps):
                continue
            bad = short(job.get("timeout-minutes"))
            if bad is not None:
                out.append(f"{os.path.basename(path)}: job '{job_id}' uses setup-php with timeout-minutes {bad}; it needs at least {MINIMUM}")
    return out


def test():
    failed = 0

    def check(label, got, want):
        nonlocal failed
        if got == want:
            print(f"ok   {label}")
        else:
            failed = 1
            print(f"FAIL {label}: got {got!r}, want {want!r}")

    php = "      - uses: shivammathur/setup-php@eb7c497e18156a6bbabfef1d3a82760b9eda3962 # 2.40.0\n"
    other = "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n"
    with tempfile.TemporaryDirectory() as temp:
        def wf(name, body):
            path = os.path.join(temp, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("on: workflow_call\njobs:\n" + body)
            return path

        short_job = wf("a.yml", "  review-rules:\n    runs-on: x\n    timeout-minutes: 5\n    steps:\n" + other + php)
        check("C2 (#173): a job that uses setup-php with 5 minutes fails, named", problems([short_job]),
              [f"a.yml: job 'review-rules' uses setup-php with timeout-minutes 5; it needs at least {MINIMUM}"])
        check("C2 (#173): 15 minutes is enough",
              problems([wf("b.yml", "  unit:\n    runs-on: x\n    timeout-minutes: 15\n    steps:\n" + php)]), [])
        check("C2 (#173): no timeout is GitHub's 360",
              problems([wf("c.yml", "  unit:\n    runs-on: x\n    steps:\n" + php)]), [])
        check("C2 (#173): a job without setup-php keeps its short timeout",
              problems([wf("d.yml", "  quick:\n    runs-on: x\n    timeout-minutes: 5\n    steps:\n" + other)]), [])
        check("C2 (#173): a timeout from an expression is the caller's",
              problems([wf("e.yml", "  e2e:\n    runs-on: x\n    timeout-minutes: ${{ matrix.suite.timeout }}\n    steps:\n" + php)]), [])
        check("C2 (#173): a reusable-workflow job has no steps",
              problems([wf("f.yml", "  call:\n    uses: ./.github/workflows/x.yml\n")]), [])
    # C1 (#173): the organisation's own workflows, Review rules among them.
    check("C1 (#173): every job of these workflows that uses setup-php has 15 minutes or more",
          problems(sorted(glob.glob(os.path.join(WORKFLOWS, "*.yml")))), [])
    return failed


def main(argv):
    if argv[:1] == ["--test"]:
        return test()
    paths = argv or sorted(glob.glob(os.path.join(WORKFLOWS, "*.yml")))
    found = problems(paths)
    for line in found:
        print(f"::error::{line}")
    if not found:
        print(f"Every job that uses setup-php has {MINIMUM} minutes or more.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
