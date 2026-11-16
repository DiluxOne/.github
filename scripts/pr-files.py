#!/usr/bin/env python3
"""A pull request's changed files, for the policy floor (#768).

The review starts as soon as a pull request is opened, and GitHub's files
API can still list nothing, or part of the change, for a few seconds: the
floor computed from that list was high for a change that is low. So the
list is checked against git, in the checkout the review has (fetch-depth 0,
the head commit from the event): when git sees a change the API does not
list yet, the API is read again, a bounded number of times.

  pr-files.py          PR, GITHUB_REPOSITORY, BASE and HEAD (the pull
                       request's base and head commits), DEFAULT_POLICY
                       (the organisation's review policy, whose
                       `files-wait: {reads, seconds}` is the bound: without
                       it, one read; a repository's policy cannot change
                       it, it is a property of GitHub's API): prints the changed
                       files, one per line (a rename's old path too, so
                       moving a file out of a high-risk directory counts);
                       its messages go to stderr
  pr-files.py --test   self-test, no network

The files API, not `gh pr diff --name-only`: GitHub refuses to render a diff
above 20 000 lines (HTTP 406). The files endpoint stops at 3 000 entries
without saying so, so its count is checked against the pull request's own
`changedFiles`:
  - the API lists every file: they are printed;
  - git and the API both see no change: the diff really is empty; nothing
    is printed, with a warning, and policy.py sets the floor high;
  - git sees a change the API does not list yet (none, or fewer than
    `changedFiles`): it reads again;
  - the bound runs out with the list still empty or partial: nothing is
    printed, with a warning that the files could not be listed, and
    policy.py sets the floor high ("no changed files could be listed"),
    which the review's summary prints;
  - the API is at its cap below `changedFiles`: waiting cannot fix that; it
    fails (exit 1), as the step did before.
"""
import json
import os
import subprocess
import sys
import time

API_CAP = 3000


def bound(path, log=lambda m: print(m, file=sys.stderr)):
    """(reads, seconds) from `files-wait` in the policy at PATH; one read
    when the key is missing or not a bound."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from policy import load_yaml
    wait = (load_yaml(path) if path else {}).get("files-wait")
    if wait is None:
        return 1, 0
    reads, seconds = (wait.get("reads"), wait.get("seconds", 0)) if isinstance(wait, dict) else (None, None)
    if type(reads) is not int or reads < 1 or type(seconds) not in (int, float) or seconds < 0:
        log(f"::warning::`files-wait` in {path} is not {{reads: 1 or more, seconds: 0 or more}}; the files are read once.")
        return 1, 0
    return reads, seconds


def names(pages):
    """The paths of the files API's slurped pages, a rename's old path too."""
    out = []
    for page in pages:
        for f in page:
            out.append(f["filename"])
            if f.get("previous_filename"):
                out.append(f["previous_filename"])
    return out


def listing(read, git_files, reads, seconds, sleep=time.sleep, log=lambda m: print(m, file=sys.stderr)):
    """(exit code, the changed files). READ() returns (pages, changedFiles);
    GIT_FILES is what git sees changed, None when git could not tell."""
    listed = total = 0
    for n in range(1, reads + 1):
        pages, total = read()
        listed = sum(len(p) for p in pages)
        if listed and listed == total:
            return 0, names(pages)
        if not listed and not total and git_files == []:
            log("::warning::The pull request changes no file; the floor is high.")
            return 0, []
        if listed >= API_CAP and listed < total:
            log(f"::error::The files API listed {listed} of the pull request's {total} changed files; the policy is not computed on a partial list.")
            return 1, []
        if n < reads:
            log(f"The files API lists {listed} of {total} changed files (git sees {'?' if git_files is None else len(git_files)}); reading again in {seconds}s ({n} of {reads}).")
            sleep(seconds)
    log(f"::warning::The files API listed {listed} of {total} changed files after {reads} reads (git sees {'?' if git_files is None else len(git_files)}); the files could not be listed, and the floor is high.")
    return 0, []


def gh_read(repo, pr):
    def read():
        pages = json.loads(subprocess.run(["gh", "api", f"repos/{repo}/pulls/{pr}/files", "--paginate", "--slurp"],
                                          check=True, capture_output=True, text=True).stdout or "[]")
        total = subprocess.run(["gh", "pr", "view", str(pr), "--repo", repo, "--json", "changedFiles", "--jq", ".changedFiles"],
                               check=True, capture_output=True, text=True).stdout.strip()
        return pages, int(total or 0)
    return read


def git_changed(base, head):
    """What git sees changed between the merge base and HEAD; None when git cannot say."""
    r = subprocess.run(["git", "diff", "--name-only", f"{base}...{head}"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return [l for l in r.stdout.splitlines() if l.strip()]


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    def fake(*answers):
        """A reader that gives ANSWERS in turn, then the last one again."""
        seen = []

        def read():
            seen.append(1)
            return answers[min(len(seen), len(answers)) - 1]
        return read, seen

    def floor_of(files):
        """policy.py's floor and reasons for FILES, with the default policy."""
        import tempfile
        here = os.path.dirname(os.path.abspath(__file__))
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            env = dict(os.environ, DEFAULT_POLICY=os.path.join(here, "..", "policy", "review-policy.default.yml"),
                       REPO_POLICY=os.path.join(tmp, "none.yml"), CHANGED_FILES="\n".join(files), GITHUB_OUTPUT=out,
                       PR_AUTHOR="someone", GITHUB_REPOSITORY="DiluxOne/example")
            for k in ("POLICY_LEVEL", "POLICY_MODE"):
                env.pop(k, None)
            subprocess.run([sys.executable, os.path.join(here, "policy.py")], env=env, check=True, capture_output=True)
            kv = dict(l.split("=", 1) for l in open(out, encoding="utf-8").read().splitlines() if "=" in l)
        return kv.get("floor"), kv.get("reasons")

    added = [[{"filename": "docs/new.md"}]]
    read, seen = fake(([], 0), ([], 0), (added, 1))
    slept, said = [], []
    got = listing(read, ["docs/new.md"], 6, 10, sleep=slept.append, log=said.append)
    check("C1: an added file the API lists only on its third read is the output, after waiting",
          (got, len(seen), slept), ((0, ["docs/new.md"]), 3, [10, 10]))
    read, seen = fake(([], 0))
    slept, said = [], []
    got = listing(read, [], 6, 10, sleep=slept.append, log=said.append)
    check("C2: git and the API both empty: no wait, the empty-diff warning, nothing listed",
          (got, len(seen), slept, said), ((0, []), 1, [], ["::warning::The pull request changes no file; the floor is high."]))
    check("C2: policy.py gives high for that empty list", floor_of(got[1]), ("high", "no changed files could be listed"))
    read, seen = fake(([], 0), (added, 1))
    check("git that cannot tell is no empty diff: it waits", (listing(read, None, 6, 0, sleep=lambda s: None, log=said.append), len(seen)), ((0, ["docs/new.md"]), 2))
    read, seen = fake(([], 0))
    slept, said = [], []
    got = listing(read, ["docs/new.md"], 3, 5, sleep=slept.append, log=said.append)
    check("C3: still empty after the bound: it gives up, says the files could not be listed, lists nothing",
          (got, len(seen), slept, "could not be listed" in said[-1]), ((0, []), 3, [5, 5], True))
    check("C3: policy.py gives high and says why", floor_of(got[1]), ("high", "no changed files could be listed"))
    read, seen = fake(([[{"filename": "a.md"}]], 2))
    check("C3: a partial list is no list either", listing(read, ["a.md", "b.md"], 2, 0, sleep=lambda s: None, log=said.append), (0, []))
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        def bound_of(text):
            path = os.path.join(tmp, "policy.yml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            return bound(path, log=said.append)
        check("C4: the reads and the delay come from `files-wait`", bound_of("files-wait:\n  reads: 4\n  seconds: 2\n"), (4, 2))
        check("C4: a missing key means one read", bound_of("budget-usd: 3\n"), (1, 0))
        check("C4: a bound that is not one means one read", [bound_of(t) for t in ("files-wait: 3\n", "files-wait:\n  reads: 0\n", "files-wait:\n  reads: 2\n  seconds: -1\n")], [(1, 0)] * 3)
    here = os.path.dirname(os.path.abspath(__file__))
    reads, seconds = bound(os.path.join(here, "..", "policy", "review-policy.default.yml"))
    check("C4: the default policy waits about a minute", (reads > 1, 30 <= (reads - 1) * seconds <= 120), (True, True))
    read, seen = fake(([], 0), (added, 1))
    check("C4: with one read, nothing waits", (listing(read, ["docs/new.md"], 1, 10, sleep=slept.append, log=said.append), len(seen)), ((0, []), 1))
    read, _ = fake(([[{"filename": "b.md", "previous_filename": "a.md"}]], 1))
    check("a rename lists both its paths", listing(read, ["b.md"], 1, 0, sleep=slept.append, log=said.append), (0, ["b.md", "a.md"]))
    read, seen = fake(([[{"filename": f"f{i}"} for i in range(API_CAP)]], API_CAP + 5))
    said = []
    got = listing(read, ["x"], 6, 10, sleep=lambda s: None, log=said.append)
    check("the API at its cap below changedFiles fails, without waiting", (got, len(seen), any("partial list" in m for m in said)), ((1, []), 1, True))
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv:
        print(__doc__, file=sys.stderr)
        return 64
    e = os.environ.get
    reads, seconds = bound(e("DEFAULT_POLICY", ""))
    code, files = listing(gh_read(e("GITHUB_REPOSITORY", ""), e("PR", "")), git_changed(e("BASE", ""), e("HEAD", "HEAD")), reads, seconds)
    for f in files:
        print(f)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
