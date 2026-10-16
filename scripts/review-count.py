#!/usr/bin/env python3
"""The first line of a review: how many findings, or nothing to fix (#234).

A review's comment, and the local review's findings file, open with the
count of what is left to fix, by severity, before any prose, and say it
plainly when nothing needs fixing. A finding about code the pull request
did not introduce (`pre_existing`, the review says so) is counted apart and
never counts as something this pull request must fix: it is not the
author's, and it never blocks.

  review-count.py line     findings (a JSON list) on stdin: the line
  review-count.py serious  findings on stdin: how many blockers and majors
                           the pull request introduced
  review-count.py --test   self-test
"""
import json
import sys

ORDER = ("blocker", "major", "minor")


def mine(findings):
    return [f for f in findings if isinstance(f, dict) and not f.get("pre_existing")]


def serious(findings):
    return sum(1 for f in mine(findings) if f.get("severity") in ("blocker", "major"))


def line(findings):
    findings = [f for f in findings if isinstance(f, dict)]
    by = {s: sum(1 for f in mine(findings) if f.get("severity") == s) for s in ORDER}
    old = len(findings) - len(mine(findings))
    tail = f" · {old} pre-existing, not this pull request's" if old else ""
    fix = by["blocker"] + by["major"]
    if not fix and not by["minor"]:
        return "**Nothing to fix.**" + tail
    parts = ", ".join(f"{by[s]} {s}" for s in ("blocker", "major") if by[s])
    head = f"**{fix} to fix** ({parts})" if fix else "**Nothing that must be fixed**"
    return head + (f" · {by['minor']} minor" if by["minor"] else "") + tail


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    f = lambda sev, pre=False: {"severity": sev, "file": "a", "title": "t", **({"pre_existing": True} if pre else {})}
    check("none: says so plainly", line([]), "**Nothing to fix.**")
    check("blockers and majors first, minors apart", line([f("major"), f("blocker"), f("minor"), f("major")]), "**3 to fix** (1 blocker, 2 major) · 1 minor")
    check("only minors: nothing must be fixed", line([f("minor"), f("minor")]), "**Nothing that must be fixed** · 2 minor")
    check("pre-existing: counted apart, never to fix", line([f("blocker", True), f("minor")]), "**Nothing that must be fixed** · 1 minor · 1 pre-existing, not this pull request's")
    check("only pre-existing: nothing to fix", line([f("major", True)]), "**Nothing to fix.** · 1 pre-existing, not this pull request's")
    check("serious: the pull request's own blockers and majors", serious([f("blocker"), f("major", True), f("minor"), f("major")]), 2)
    check("not a finding is skipped", (line(["x", None]), serious(["x"])), ("**Nothing to fix.**", 0))
    import subprocess as _sp
    import os as _os
    cli = lambda text: _sp.run([sys.executable, _os.path.abspath(__file__), "serious"], input=text, capture_output=True, text=True)
    check("cli: a cut or empty input is an error, never zero", (cli('[{"severity":"bl').returncode, cli("").returncode, cli("{}").returncode, cli('[{"severity":"major"}]').stdout.strip()), (1, 1, 1, "1"))
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv in (["line"], ["serious"]):
        # Fails closed: what is not a list of findings is an error, never
        # "nothing to fix".
        try:
            findings = json.loads(sys.stdin.read())
        except ValueError:
            findings = None
        if not isinstance(findings, list):
            print("review-count.py: the findings are not a JSON list", file=sys.stderr)
            return 1
        print(line(findings) if argv == ["line"] else serious(findings))
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
