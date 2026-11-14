#!/usr/bin/env python3
"""The files a pull request changes, for the policy floor (#768).

  pr-files.py OUT      write the pull request's changed files to OUT, one per
                       line (a rename gives both its paths, so moving a file
                       out of a high-risk directory counts), and print how
                       they were read, FILES_STATE for scripts/policy.py:
                         listed    the list was read
                         empty     the diff is really empty: nothing to wait for
                         unlisted  still no file listed past the bound
  pr-files.py --test   self-test, without the network

Only the state goes to stdout (the step reads it); what it says, errors
included, goes to stderr.

Environment: GITHUB_REPOSITORY, PR, BASE and HEAD (the pull request's
commits), DEFAULT_POLICY (the organisation's
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
Before that, the compare API (computed from git when it is asked, so it does
not lag) says whether the diff is really empty: then nothing is waited for.
A compare that fails counts as not empty, so it can only lead to waiting,
never to a lower floor.
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

    def compare_empty(self, base, head):
        """True only when the compare API answers that base...head changes no file."""
        if not base or not head:
            return False
        try:
            count = gh("api", f"repos/{self.repo}/compare/{base}...{head}", "--jq", '.files | if type == "array" then length else -1 end').strip()
        except RuntimeError as err:
            print(f"the compare API did not answer ({err}); the diff counts as not empty", file=sys.stderr)
            return False
        return count == "0"

    def total(self):
        return int(gh("pr", "view", str(self.pr), "--repo", self.repo, "--json", "changedFiles", "--jq", ".changedFiles").strip() or 0)


def names(files):
    out = []
    for f in files:
        for name in (f.get("filename"), f.get("previous_filename")):
            if name and name not in out:
                out.append(name)
    return out


def read(api, attempts, interval, sleep=None, base="", head=""):
    """(state, files, reads): ("empty", [], 0) when the diff is really
    empty, else the list once it is not empty and its count is
    the pull request's total, read up to `attempts` times. Raises
    RuntimeError when a list that is not empty still differs from the total."""
    sleep = sleep or time.sleep
    if api.compare_empty(base, head):
        return "empty", [], 0
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
    return "unlisted", [], attempts


def main(argv):
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    wait = bound(load_yaml(os.environ["DEFAULT_POLICY"]))
    if wait is None:
        print(f"::error::files-wait in {os.environ['DEFAULT_POLICY']} is not {{attempts: N >= 1, interval-seconds: N >= 0}}.", file=sys.stderr)
        return 1
    try:
        state, files, _ = read(GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["PR"]), *wait,
                                base=os.environ.get("BASE", ""), head=os.environ.get("HEAD", ""))
    except RuntimeError as err:
        print(f"::error::{err}", file=sys.stderr)
        return 1
    with open(argv[0], "w", encoding="utf-8") as fh:
        fh.write("".join(f + "\n" for f in files))
    print(state)
    return 0


class Fake:
    """A pull request whose files API answers each read from `reads` (the
    last one again once they run out), its total the list's length unless
    `totals` says; its compare says the diff is empty when `empty` is True,
    and fails when it is None."""

    def __init__(self, reads, totals=None, empty=False):
        self.reads, self.totals, self.empty, self.calls = reads, totals, empty, 0

    def compare_empty(self, base, head):
        return self.empty is True

    def files(self):
        self.calls += 1
        return self.reads[min(self.calls, len(self.reads)) - 1]

    def total(self):
        if self.totals is None:
            return len(self.reads[min(self.calls, len(self.reads)) - 1])
        return self.totals[min(self.calls, len(self.totals)) - 1]


def self_test():
    global GitHub
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
    api = Fake([[]], empty=True)
    slept = []
    got = read(api, 12, 10, sleep=slept.append, base="b", head="h")
    check("C2: an empty compare does not wait: FILES_STATE=empty", got == ("empty", [], 0) and api.calls == 0 and not slept, (got, api.calls, slept))
    api = Fake([[], added], empty=None)
    check("C2: a compare that fails counts as not empty: the list is waited for", read(api, 12, 0, sleep=lambda s: None)[:2] == ("listed", ["docs/new.md"]), api.calls)
    check("C2: no base or head is no empty diff", GitHub("o/r", "1").compare_empty("", "h") is False)
    renamed = [{"filename": "docs/a.md", "previous_filename": ".github/workflows/a.yml"}]
    check("a rename lists both its paths", read(Fake([renamed]), 1, 0)[1] == ["docs/a.md", ".github/workflows/a.yml"])
    api, slept = Fake([[]]), []
    got = read(api, 5, 7, sleep=slept.append)
    check("C3: [] on every read past the bound: FILES_STATE=unlisted", got == ("unlisted", [], 5) and api.calls == 5 and slept == [7] * 4, (got, api.calls, slept))
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

    def run_main(policy, fake):
        """main() with this policy file and API: (exit, printed, list, sleeps)."""
        global GitHub
        real, real_sleep, sleeps = GitHub, time.sleep, []
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "files")
            GitHub = lambda repo, pr: fake  # noqa: E731
            time.sleep = sleeps.append
            saved = dict(os.environ)
            os.environ.update({"DEFAULT_POLICY": policy, "GITHUB_REPOSITORY": "o/r", "PR": "1"})
            try:
                printed = io.StringIO()
                with contextlib.redirect_stdout(printed):
                    code = main([out])
            finally:
                os.environ.clear()
                os.environ.update(saved)
                GitHub, time.sleep = real, real_sleep
            listed = open(out, encoding="utf-8").read() if os.path.exists(out) else None
        return code, printed.getvalue().strip(), listed, sleeps

    with tempfile.TemporaryDirectory() as tmp:
        fixture = os.path.join(tmp, "policy.yml")
        with open(fixture, "w", encoding="utf-8") as fh:
            fh.write("files-wait:\n  attempts: 4\n  interval-seconds: 3\n")
        got = run_main(fixture, Fake([[], added]))
        check("C1: main writes the list and says it was listed", got[:3] == (0, "listed", "docs/new.md\n"), got)
        default = os.path.join(HERE, "..", "policy", "review-policy.default.yml")
        wait = (defaults.get("files-wait") or {})
        fake = Fake([[]])
        got = run_main(default, fake)
        check("C4: the bound is review-policy.default.yml's files-wait", got[1] == "unlisted" and fake.calls == wait.get("attempts") and got[3] == [wait.get("interval-seconds")] * (fake.calls - 1), (got, fake.calls, wait))
        fake = Fake([[]])
        got = run_main(fixture, fake)
        check("C4: a fixture with another value changes the number of reads", got[1] == "unlisted" and fake.calls == 4 and got[3] == [3, 3, 3], (got, fake.calls))
        with open(fixture, "w", encoding="utf-8") as fh:
            fh.write("budget-usd: 3\n")
        got = run_main(fixture, Fake([[]]))
        check("C4: no files-wait in the policy fails, with no bound of its own", got[0] == 1 and got[2] is None, got)
        check("an error is not printed where the step reads the state", got[1] == "", got)
    with open(os.path.join(HERE, "..", ".github", "workflows", "claude-review.yml"), encoding="utf-8") as fh:
        workflow = fh.read()
    step = workflow[workflow.index("- name: Policy floor (deterministic)"):workflow.index("- name: Scope (previous verdict")]
    check("C4: the policy step reads the files through pr-files.py, with no bound of its own", "scripts/pr-files.py" in step and "sleep" not in step and "files-wait:" not in step, step)
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
