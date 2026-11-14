#!/usr/bin/env python3
"""The files a pull request changes, for the policy floor (#768).

  pr-files.py OUT      write the pull request's changed files to OUT, one per
                       line (a rename gives both its paths, so moving a file
                       out of a high-risk directory counts), and print how
                       they were read, FILES_STATE for scripts/policy.py:
                         listed    the list was read
  pr-files.py --test   self-test, without the network

Environment: GITHUB_REPOSITORY, PR, DEFAULT_POLICY (the organisation's
review policy, whose `files-wait` is the bound) and GH_TOKEN for gh.

The files API, not `gh pr diff --name-only`: GitHub refuses to render a diff
above 20 000 lines (HTTP 406), and a translation or lock-file change gets
there easily. The files endpoint has a cap of its own, 3 000 entries, and
reaches it silently, so the count is checked against the pull request's own
total (`changedFiles`), and a list that still differs from it fails: a floor
computed on a partial list could miss a high-risk path.

Just after a pull request is opened, its files list can be empty for a while
(GitHub computes it after the event). The list is read again, up to
`files-wait.attempts` reads `files-wait.interval-seconds` apart
(policy/review-policy.default.yml, the organisation's only: a repository
cannot shorten it), until it is not empty and its count is `changedFiles`.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from policy import load_yaml  # noqa: E402  the same reader as the policy


def bound(defaults):
    """(attempts, interval in seconds) from the policy's `files-wait`; None
    when it is not two numbers, attempts at least 1."""
    wait = defaults.get("files-wait") if isinstance(defaults, dict) else None
    if not isinstance(wait, dict):
        return None
    attempts, interval = wait.get("attempts"), wait.get("interval-seconds")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (attempts, interval)) or attempts < 1 or interval < 0:
        return None
    return attempts, interval


def gh(*args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {out.stderr.strip()[:300]}")
    return out.stdout


class GitHub:
    """The reads, from GitHub through gh."""

    def __init__(self, repo, pr):
        self.repo, self.pr = repo, pr

    def files(self):
        pages = json.loads(gh("api", f"repos/{self.repo}/pulls/{self.pr}/files", "--paginate", "--slurp") or "[]")
        return [f for page in pages for f in page]

    def total(self):
        return int(gh("pr", "view", str(self.pr), "--repo", self.repo, "--json", "changedFiles", "--jq", ".changedFiles").strip() or 0)


def names(files):
    out = []
    for f in files:
        for name in (f.get("filename"), f.get("previous_filename")):
            if name and name not in out:
                out.append(name)
    return out


def read(api, attempts, interval, sleep=time.sleep):
    """(state, files, reads): the list once it is not empty and its count is
    the pull request's total, read up to `attempts` times. Raises
    RuntimeError when a list that is not empty still differs from the total."""
    files, total = [], 0
    for n in range(1, attempts + 1):
        files, total = api.files(), api.total()
        if files and len(files) == total:
            return "listed", names(files), n
        if n < attempts:
            print(f"the files API listed {len(files)} of {total} changed files; reading again in {interval}s ({n} of {attempts})", file=sys.stderr)
            sleep(interval)
    if files:
        raise RuntimeError(f"The files API listed {len(files)} of the pull request's {total} changed files after {attempts} reads; the policy is not computed on a partial list.")
    return "listed", [], attempts


def main(argv):
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    wait = bound(load_yaml(os.environ["DEFAULT_POLICY"]))
    if wait is None:
        print(f"::error::files-wait in {os.environ['DEFAULT_POLICY']} is not {{attempts: N >= 1, interval-seconds: N >= 0}}.")
        return 1
    try:
        state, files, _ = read(GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["PR"]), *wait)
    except RuntimeError as err:
        print(f"::error::{err}")
        return 1
    with open(argv[0], "w", encoding="utf-8") as fh:
        fh.write("".join(f + "\n" for f in files))
    print(state)
    return 0


class Fake:
    """A pull request whose files API answers each read from `reads` (the
    last one again once they run out), its total the list's length unless
    `totals` says."""

    def __init__(self, reads, totals=None):
        self.reads, self.totals, self.calls = reads, totals, 0

    def files(self):
        self.calls += 1
        return self.reads[min(self.calls, len(self.reads)) - 1]

    def total(self):
        if self.totals is None:
            return len(self.reads[min(self.calls, len(self.reads)) - 1])
        return self.totals[min(self.calls, len(self.totals)) - 1]


def self_test():
    failed = 0

    def check(name, ok, detail=""):
        nonlocal failed
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
        failed += 0 if ok else 1

    added = [{"filename": "docs/new.md", "status": "added"}]
    slept = []
    api = Fake([[], [], added])
    got = read(api, 12, 10, sleep=slept.append)
    check("C1: [] twice, then the added file: the list holds it", got == ("listed", ["docs/new.md"], 3), got)
    check("C1: it waited the interval between the reads", slept == [10, 10], slept)
    api = Fake([added], totals=[0, 1])
    check("C1: a list whose total still lags is read again", read(api, 12, 0, sleep=lambda s: None) == ("listed", ["docs/new.md"], 2), api.calls)
    renamed = [{"filename": "docs/a.md", "previous_filename": ".github/workflows/a.yml"}]
    check("a rename lists both its paths", read(Fake([renamed]), 1, 0)[1] == ["docs/a.md", ".github/workflows/a.yml"])
    try:
        read(Fake([added], totals=[3000]), 2, 0, sleep=lambda s: None)
        check("a list that still differs from the total fails", False, "no error")
    except RuntimeError as err:
        check("a list that still differs from the total fails", "1 of the pull request's 3000" in str(err), err)
    defaults = load_yaml(os.path.join(HERE, "..", "policy", "review-policy.default.yml"))
    check("the bound is the policy's files-wait", bound(defaults) is not None, defaults.get("files-wait"))
    for value in ({}, {"attempts": 0, "interval-seconds": 1}, {"attempts": "12", "interval-seconds": 1}, {"attempts": True, "interval-seconds": 1}, {"attempts": 3, "interval-seconds": -1}):
        check(f"files-wait {value} is no bound", bound({"files-wait": value}) is None)

    # main(), end to end, with the policy in a fixture and the API faked.
    import contextlib
    import io
    import tempfile
    global GitHub
    real = GitHub
    with tempfile.TemporaryDirectory() as tmp:
        policy, out = os.path.join(tmp, "policy.yml"), os.path.join(tmp, "files")
        with open(policy, "w", encoding="utf-8") as fh:
            fh.write("files-wait:\n  attempts: 4\n  interval-seconds: 0\n")
        fake = Fake([[], added])
        GitHub = lambda repo, pr: fake  # noqa: E731
        saved = dict(os.environ)
        os.environ.update({"DEFAULT_POLICY": policy, "GITHUB_REPOSITORY": "o/r", "PR": "1"})
        try:
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                code = main([out])
        finally:
            os.environ.clear()
            os.environ.update(saved)
            GitHub = real
        with open(out, encoding="utf-8") as fh:
            listed = fh.read()
        check("C1: main writes the list and says it was listed", code == 0 and listed == "docs/new.md\n" and printed.getvalue().strip() == "listed", (code, listed, printed.getvalue()))
    if not failed:
        print("all tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--test"]:
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()):  # the waits' lines
            sys.exit(self_test())
    sys.exit(main(sys.argv[1:]))
