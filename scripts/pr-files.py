#!/usr/bin/env python3
"""A pull request's changed files, for the policy floor (#768).

The review starts as soon as a pull request is opened, and GitHub's files
API can still list nothing, or part of the change, for a few seconds: the
floor computed from that list was high for a change that is low. So the
list is checked against git, in the checkout the review has (fetch-depth 0,
the head commit from the event): when git sees a change the API does not
list yet, the API is read again, a bounded number of times.

  pr-files.py          PR, GITHUB_REPOSITORY, BASE and HEAD (the pull
                       request's base and head commits): prints the changed
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
  - the API is at its cap below `changedFiles`: waiting cannot fix that; it
    fails (exit 1), as the step did before.
"""
import json
import os
import subprocess
import sys
import time

API_CAP = 3000


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
    code, files = listing(gh_read(e("GITHUB_REPOSITORY", ""), e("PR", "")), git_changed(e("BASE", ""), e("HEAD", "HEAD")), 6, 10)
    for f in files:
        print(f)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
