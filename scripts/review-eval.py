#!/usr/bin/env python3
"""The review's evaluation set: a change to the review is scored first (#234).

The cases are real pull requests of the organisation's public repositories
(a private one's code would show in this public repository's logs):

  flag   the commit where the review raised a blocker or major that was
         then fixed: its `line` of `path`, which `fix`, a later commit of
         the pull request, changed (a thread that is only outdated or
         resolved, its line never changed, is no case; #844). The review
         must raise a blocker or major on that line again: another line
         of the file is a miss.
  clean  the last commit of a merged pull request on which the review left
         no thread at all. The review must not block it.

Each case is reviewed again, with the rules as they stand in the checkout,
by scripts/local-review.sh (the same brief, profiles and model the pull
request's review uses), PLAYS (3) times, each on a fresh checkout, and
scored on its median: found, or blocked, when 2 of 3 plays say so (a play
that could not be reviewed is dropped; fewer than 2 reviewed is
unreviewed). The set holds at least MIN_CASES (10) cases of each kind, or
it is neither run nor scored (#844). The score is the share of `flag` cases
found and of `clean` cases blocked; review-eval.yml fails a change to the
review whose score is worse than evals/review/baseline.json by more than
one case on either side.

  review-eval.py collect [N]   write evals/review/cases.json: N cases of each
                               kind (default 10), from the review's threads
                               (GH_TOKEN, read)
  review-eval.py check [FILE]  validate the set (default cases.json): exit 1
                               naming each flag case whose line its fix did
                               not change (git, the public repositories)
  review-eval.py run [--play N]
                               check the set, then review every case, all
                               the plays or play N alone; results on stdout
                               (JSON) (the Claude Code CLI, git, the checkout)
  review-eval.py score FILE... the results in the FILEs (one per play, or a
                               whole run) against the baseline: a table on
                               stdout, exit 1 when worse
  review-eval.py baseline FILE...
                               write the results as the baseline (a whole
                               run of every play alone)
  review-eval.py --test        self-test
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
import org  # noqa: E402  the organisation, from org.yml (#191)

CASES = os.path.join(ROOT, "evals", "review", "cases.json")
BASELINE = os.path.join(ROOT, "evals", "review", "baseline.json")
SLACK = 1
# A set of at least MIN_CASES of each kind, each case reviewed PLAYS times
# and scored on its median (C3, #844): one odd answer moves no case.
MIN_CASES = 10
PLAYS = 3

QUERY = """
query($q: String!) {
  search(query: $q, type: ISSUE, first: 50) {
    nodes { ... on PullRequest {
      number title baseRefOid headRefOid isCrossRepository
      commits(first: 100) { nodes { commit { oid } } }
      reviewThreads(first: 50) { nodes {
        isResolved isOutdated path originalLine resolvedBy { login }
        comments(first: 1) { nodes { author { login } body originalCommit { oid } } }
      } }
    } }
  }
}
"""


def is_review(t):
    c = ((t.get("comments") or {}).get("nodes") or [{}])[0] or {}
    return (c.get("author") or {}).get("login") == org.APP and "AI review" in (c.get("body") or "")


def line_changed(diff, line):
    """Whether `git diff -U0` text changes the old file's line: it falls in
    a `-a,b` hunk with b >= 1 (a hunk of additions alone changes none)."""
    for m in re.finditer(r"^@@ -(\d+)(?:,(\d+))? \+", diff or "", re.M):
        start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
        if count >= 1 and start <= line < start + count:
            return True
    return False


def first_fix(commits, line, diff_of):
    """The first of commits (those after the case's head, in order) whose
    diff from head, diff_of(commit), changes line; None when none does."""
    for c in commits:
        if line_changed(diff_of(c), line):
            return c
    return None


def git_url(repo):
    # DX_EVAL_GIT stands in for GitHub in the tests: a directory of o/r.
    return f"{os.environ.get('DX_EVAL_GIT', 'https://github.com')}/{repo}"


class Clones:
    """One clone per repository, to read the cases' commits."""

    def __init__(self, work):
        self.work, self.dirs = work, {}

    def git(self, repo, *args):
        d = self.dirs.get(repo)
        if d is None:
            d = os.path.join(self.work, repo.replace("/", "_"))
            if subprocess.run(["git", "clone", "-q", "--no-checkout", git_url(repo), d], capture_output=True).returncode != 0:
                d = ""
            self.dirs[repo] = d
        if not d:
            return None
        return subprocess.run(["git", "-C", d, *args], capture_output=True, text=True)

    def has(self, repo, pr, *oids):
        """Whether every oid is a commit of the clone, fetched when not."""
        def ok():
            return all((self.git(repo, "cat-file", "-e", o + "^{commit}") or subprocess.CompletedProcess([], 1)).returncode == 0 for o in oids)
        if ok():
            return True
        # The pull request's ref first (its commits after a squash merge),
        # then the commits themselves.
        if pr is not None:
            self.git(repo, "fetch", "-q", "origin", f"refs/pull/{pr}/head")
        if not ok():
            self.git(repo, "fetch", "-q", "origin", *oids)
        return ok()

    def diff(self, repo, a, b, path):
        out = self.git(repo, "diff", "-U0", a, b, "--", path)
        return out.stdout if out is not None and out.returncode == 0 else ""


def refused(cases, clones):
    """Why each flag case is refused, by its name: no line or fix, or the
    fix did not change its line (C1, #844)."""
    why = []
    for c in cases:
        if c.get("expect") != "flag":
            continue
        line, fix = c.get("line"), c.get("fix")
        if not isinstance(line, int) or isinstance(line, bool) or not fix or not c.get("path"):
            why.append(f"{c.get('id')}: no line, path or fix")
        elif not clones.has(c["repo"], c.get("pr"), c["head"], fix):
            why.append(f"{c['id']}: {c['head']} or {fix} cannot be read from {c['repo']}")
        elif not line_changed(clones.diff(c["repo"], c["head"], fix, c["path"]), line):
            why.append(f"{c['id']}: line {line} of {c['path']} was not changed by {fix}")
    return why


def cases_from(repo, prs, n, fix_of=None):
    """Up to n `flag` and n `clean` cases from one repository's pull requests.
    fix_of(pr, head, path, line, commits) is the commit after head that
    changed the line, or None: a thread whose line no commit changed is
    not a flag case (#844)."""
    flag, clean = [], []
    for pr in prs:
        # Only a branch of the repository itself: a fork's code never runs
        # where the review's key is (#234).
        if pr.get("isCrossRepository") is not False:
            continue
        threads = [t for t in ((pr.get("reviewThreads") or {}).get("nodes") or [])]
        fixed = [t for t in threads if is_review(t) and (((t.get("resolvedBy") or {}).get("login") == org.APP) or t.get("isOutdated"))]
        if fixed:
            commits = [((x or {}).get("commit") or {}).get("oid") for x in ((pr.get("commits") or {}).get("nodes") or [])]
            for t in fixed:
                head = (((t.get("comments") or {}).get("nodes") or [{}])[0].get("originalCommit") or {}).get("oid")
                line = t.get("originalLine")
                if not head or not isinstance(line, int) or head not in commits or len(flag) >= n:
                    continue
                after = [c for c in commits[commits.index(head) + 1:] if c]
                fix = fix_of(pr, head, t.get("path"), line, after) if fix_of else None
                if fix:
                    flag.append({"id": f"{repo}#{pr['number']}:flag", "repo": repo, "pr": pr["number"], "title": pr.get("title") or "",
                                 "base": pr.get("baseRefOid"), "head": head, "expect": "flag", "path": t.get("path"), "line": line, "fix": fix})
                    break
        elif not any(is_review(t) for t in threads) and len(clean) < n:
            clean.append({"id": f"{repo}#{pr['number']}:clean", "repo": repo, "pr": pr["number"], "title": pr.get("title") or "",
                          "base": pr.get("baseRefOid"), "head": pr.get("headRefOid"), "expect": "clean"})
    return flag, clean


def pick(per_repo, n):
    """n of each kind, taken round the repositories so no one dominates."""
    out = {"flag": [], "clean": []}
    for kind, i in (("flag", 0), ("clean", 1)):
        pools = [list(v[i]) for v in per_repo.values()]
        while len(out[kind]) < n and any(pools):
            for p in pools:
                if p and len(out[kind]) < n:
                    out[kind].append(p.pop(0))
    return sorted(out["flag"] + out["clean"], key=lambda c: c["id"])


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def public_repos():
    import yaml
    with open(os.path.join(ROOT, "repos.yml"), encoding="utf-8") as fh:
        names = sorted(((yaml.safe_load(fh) or {}).get("repos") or {}).keys())
    listed = {r["name"]: r for r in json.loads(gh("repo", "list", org.ORG, "--limit", "500", "--json", "name,visibility,isArchived"))}
    return [n for n in names if (listed.get(n) or {}).get("visibility") == "PUBLIC" and not listed[n].get("isArchived")]


def collect(n):
    per_repo = {}
    clones = Clones(tempfile.mkdtemp(prefix="dx-collect-"))
    for name in public_repos():
        full = f"{org.ORG}/{name}"
        out = gh("api", "graphql", "-f", f"query={QUERY}", "-f", f"q=repo:{full} is:pr is:merged commenter:app/{org.APP}")
        prs = json.loads(out)["data"]["search"]["nodes"]

        def fix_of(pr, head, path, line, after, full=full):
            if not clones.has(full, pr["number"], head, *after):
                return None
            return first_fix(after, line, lambda c: clones.diff(full, head, c, path))
        per_repo[full] = cases_from(full, prs, n, fix_of)
    return pick(per_repo, n)


def check(cases):
    """The set's validation: 0, or 1 with each refused case on stderr."""
    why = refused(cases, Clones(tempfile.mkdtemp(prefix="dx-check-")))
    for w in why:
        print(f"review-eval.py: {w}", file=sys.stderr)
    return 1 if why else 0


def as_line(v):
    """A finding's line as an int, or None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    return int(v) if isinstance(v, str) and v.strip().isdigit() else None


def verdict(case, review):
    """Whether the review did what the case expects. review is
    local-review.sh's last.json, or None when it gave none."""
    if not isinstance(review, dict):
        return None
    serious = [f for f in review.get("findings") or [] if isinstance(f, dict)
               and f.get("severity") in ("blocker", "major") and not f.get("pre_existing")]
    if case["expect"] == "flag":
        # The case's line, not its file: another line of the same file, or
        # a finding with no line, is a miss (C2, #844).
        line = as_line(case.get("line"))
        return line is not None and any(f.get("file") == case["path"] and as_line(f.get("line")) == line for f in serious)
    return not serious


def run_case(case, central, work):
    """Review one case; True, False, or None when it could not be reviewed."""
    repo_dir = os.path.join(work, case["repo"].replace("/", "_"))
    git = lambda *a: subprocess.run(["git", "-C", repo_dir, *a], capture_output=True, text=True)
    if not os.path.isdir(repo_dir):
        if subprocess.run(["git", "clone", "-q", git_url(case["repo"]), repo_dir]).returncode != 0:
            return None
    git("fetch", "-q", "origin", f"refs/pull/{case['pr']}/head", case["base"])
    if git("cat-file", "-e", case["head"] + "^{commit}").returncode != 0:
        git("fetch", "-q", "origin", case["head"])
    if git("checkout", "-q", "-B", f"eval/{case['pr']}", case["head"]).returncode != 0:
        return None
    state = os.path.join(repo_dir, ".git", "dx-review", "last.json")
    if os.path.exists(state):
        os.remove(state)
    try:
        # One case never holds the run: 15 minutes, then it is unreviewed.
        subprocess.run(["bash", os.path.join(central, "scripts", "local-review.sh"), "--base", case["base"], "--full", "--title", case["title"]],
                       cwd=repo_dir, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return None
    try:
        with open(state, encoding="utf-8") as fh:
            return verdict(case, json.load(fh))
    except (OSError, ValueError):
        return None


def short(items):
    """Why the set is too small to score, or '': fewer than MIN_CASES flag
    or clean cases (items are cases or results)."""
    why = [f"{sum(1 for c in items if c.get('expect') == k)} {k} cases, fewer than {MIN_CASES}"
           for k in ("flag", "clean") if sum(1 for c in items if c.get("expect") == k) < MIN_CASES]
    return "; ".join(why)


def unplayed(results):
    """The cases not played PLAYS times, by name."""
    return [r.get("id") for r in results if len(r.get("plays") or []) != PLAYS]


def merge(runs):
    """The plays of several runs (one per play, --play N) case by case."""
    out, at = [], {}
    for run in runs:
        for r in run:
            if r["id"] not in at:
                at[r["id"]] = {"id": r["id"], "expect": r["expect"], "plays": []}
                out.append(at[r["id"]])
            at[r["id"]]["plays"] += list(r.get("plays") or [])
    return out


def median(r):
    """A case's result over its plays: True (as expected), False, or None
    when fewer than 2 plays were reviewed. A flag case is found, and a
    clean one blocked, when 2 plays say so (2 of 3)."""
    played = [p for p in r.get("plays") or [] if p is not None]
    if len(played) < 2:
        return None
    if r["expect"] == "flag":
        return sum(1 for p in played if p) >= 2
    return sum(1 for p in played if not p) < 2


def score(results):
    ok = [(r["expect"], median(r)) for r in results]
    flag = [m for e, m in ok if e == "flag" and m is not None]
    clean = [m for e, m in ok if e == "clean" and m is not None]
    return {"found": sum(1 for m in flag if m), "flag": len(flag),
            "blocked": sum(1 for m in clean if not m), "clean": len(clean),
            "unreviewed": sum(1 for _, m in ok if m is None), "plays": PLAYS}


def worse(now, base):
    """Why the score is worse than the baseline by more than SLACK, or ''."""
    why = []
    if base.get("flag") and now["found"] < base["found"] - SLACK:
        why.append(f"it found {now['found']} of {now['flag']} known bugs, the baseline {base['found']} of {base['flag']}")
    if now["blocked"] > base.get("blocked", 0) + SLACK:
        why.append(f"it blocked {now['blocked']} of {now['clean']} clean pull requests, the baseline {base.get('blocked', 0)}")
    if now["unreviewed"] > SLACK:
        why.append(f"{now['unreviewed']} cases could not be reviewed")
    return "; ".join(why)


def table(results, now, base):
    out = ["| Case | Expects | Plays | Result |", "| --- | --- | --- | --- |"]
    words = {"flag": ("found", "missed"), "clean": ("clean", "blocked")}
    for r in results:
        yes, no = words.get(r["expect"], ("as expected", "not"))
        plays = ", ".join("not reviewed" if p is None else yes if p else no for p in r.get("plays") or [])
        m = median(r)
        res = "could not review" if m is None else ("as expected" if m else "**missed**" if r["expect"] == "flag" else "**blocked**")
        out.append(f"| {r['id']} | {r['expect']} | {plays} | {res} |")
    out += ["", f"Found {now['found']} of {now['flag']} known bugs (baseline {base.get('found', '?')} of {base.get('flag', '?')}); "
            f"blocked {now['blocked']} of {now['clean']} clean pull requests (baseline {base.get('blocked', '?')}); {now['unreviewed']} not reviewed."]
    return "\n".join(out)


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    bot = {"login": org.APP}
    first = lambda oid: {"nodes": [{"author": bot, "body": "x\n<sub>🤖 AI review · m (Anthropic)</sub>", "originalCommit": {"oid": oid}}]}
    commits = lambda *o: {"nodes": [{"commit": {"oid": x}} for x in o]}
    prs = [{"number": 1, "title": "fix: a", "baseRefOid": "b1", "headRefOid": "h1", "isCrossRepository": False, "commits": commits("c0", "c1", "c2", "h1"),
            "reviewThreads": {"nodes": [{"isOutdated": True, "path": "a.php", "originalLine": 7, "resolvedBy": None, "comments": first("c1")}]}},
           {"number": 2, "title": "feat: b", "baseRefOid": "b2", "headRefOid": "h2", "isCrossRepository": False, "reviewThreads": {"nodes": []}},
           {"number": 3, "title": "fix: c", "baseRefOid": "b3", "headRefOid": "h3", "isCrossRepository": False, "reviewThreads": {"nodes": [{"isOutdated": False, "path": "c.php", "resolvedBy": {"login": "me"}, "comments": first("c3")}]}}]
    seen = []
    fix_of = lambda pr, head, path, line, after: seen.append((head, path, line, after)) or "c2"
    flag, clean = cases_from("o/r", prs, 5, fix_of)
    check("cases: a fixed finding is a flag case at the commit it was raised on, with its line and fix", [(c["pr"], c["head"], c["path"], c["line"], c["fix"]) for c in flag], [(1, "c1", "a.php", 7, "c2")])
    check("cases: the fix is looked for among the commits after head", seen, [("c1", "a.php", 7, ["c2", "h1"])])
    check("cases: a thread whose line no commit changed is not a flag case", cases_from("o/r", prs[:1], 5, lambda *a: None), ([], []))
    check("line_changed: inside a -a,b hunk; never an addition alone", [line_changed("@@ -3,2 +3,1 @@\n@@ -9,0 +9,1 @@\n", n) for n in (2, 3, 4, 5, 9)], [False, True, True, False, False])
    check("first_fix: the first commit that changed the line", first_fix(["x", "y"], 3, {"x": "@@ -5 +5 @@", "y": "@@ -3 +3 @@"}.get), "y")
    check("cases: a pull request with no thread is clean at its last commit; a dismissed one is neither", [(c["pr"], c["head"]) for c in clean], [(2, "h2")])
    fork = [{"number": 9, "title": "x", "baseRefOid": "b", "headRefOid": "h", "isCrossRepository": True, "reviewThreads": {"nodes": []}},
            {"number": 8, "title": "y", "baseRefOid": "b", "headRefOid": "h", "reviewThreads": {"nodes": []}}]
    check("cases: never a fork's pull request, nor one that does not say", cases_from("o/r", fork, 5), ([], []))
    picked = pick({"o/a": ([{"id": "a1"}, {"id": "a2"}], []), "o/b": ([{"id": "b1"}], [])}, 2)
    check("pick: round the repositories", [c["id"] for c in picked], ["a1", "b1"])
    case_f = {"expect": "flag", "path": "a.php", "line": 3}
    check("verdict: flag found on its line", verdict(case_f, {"findings": [{"severity": "major", "file": "a.php", "line": 3}]}), True)
    check("verdict: a case with no line finds nothing", verdict({"expect": "flag", "path": "a.php"}, {"findings": [{"severity": "major", "file": "a.php"}]}), False)
    check("verdict: another line of the file, or no line, is missed", (verdict(case_f, {"findings": [{"severity": "major", "file": "a.php", "line": 4}]}), verdict(case_f, {"findings": [{"severity": "major", "file": "a.php"}]})), (False, False))
    check("verdict: flag missed (a minor, another file, a pre-existing one)", verdict(case_f, {"findings": [{"severity": "minor", "file": "a.php"}, {"severity": "major", "file": "b.php"}, {"severity": "blocker", "file": "a.php", "pre_existing": True}]}), False)
    check("verdict: clean kept clean; clean blocked", (verdict({"expect": "clean"}, {"findings": [{"severity": "minor"}]}), verdict({"expect": "clean"}, {"findings": [{"severity": "major"}]})), (True, False))
    check("verdict: no review is unknown", verdict(case_f, None), None)
    res = [{"id": "1", "expect": "flag", "plays": [True, True, False]}, {"id": "2", "expect": "flag", "plays": [False, True, False]},
           {"id": "3", "expect": "clean", "plays": [False, False, True]}, {"id": "4", "expect": "clean", "plays": [None, None, True]}]
    now = score(res)
    check("score: each case's median; found, blocked, unreviewed", now, {"found": 1, "flag": 2, "blocked": 1, "clean": 1, "unreviewed": 1, "plays": PLAYS})
    check("median: 2 reviewed plays that split find no bug and block nothing", (median({"expect": "flag", "plays": [True, None, False]}), median({"expect": "clean", "plays": [True, None, False]})), (False, True))
    check("merge: the plays of each run, case by case", merge([[{"id": "1", "expect": "flag", "plays": [True]}], [{"id": "1", "expect": "flag", "plays": [False]}]]), [{"id": "1", "expect": "flag", "plays": [True, False]}])
    check("short: fewer than MIN_CASES of a kind", (short(res), short([{"expect": k} for k in ("flag", "clean") for _ in range(MIN_CASES)])), (f"2 flag cases, fewer than {MIN_CASES}; 2 clean cases, fewer than {MIN_CASES}", ""))
    check("unplayed: a case not played PLAYS times", unplayed(res + [{"id": "5", "expect": "flag", "plays": [True]}]), ["5"])
    check("worse: within one case of the baseline is not worse", worse(now, {"found": 2, "flag": 2, "blocked": 0}), "")
    check("worse: two fewer bugs found is", worse({**now, "found": 0}, {"found": 2, "flag": 2, "blocked": 0}).startswith("it found 0 of 2"), True)
    check("worse: two more clean ones blocked is", "it blocked 2" in worse({**now, "blocked": 2}, {"found": 1, "flag": 2, "blocked": 0}), True)
    check("worse: more than one case unreviewed is", ("could not be reviewed" in worse({"found": 1, "flag": 1, "blocked": 0, "clean": 8, "unreviewed": 2}, {"found": 1, "flag": 1}), worse({"found": 1, "flag": 1, "blocked": 0, "clean": 9, "unreviewed": 1}, {"found": 1, "flag": 1})), (True, ""))
    check("table: says what was missed, and each play", ("**missed**" in table(res, now, {}), "| 1 | flag | found, found, missed | as expected |" in table(res, now, {})), (True, True))
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv[:1] == ["collect"]:
        cases = collect(int(argv[1]) if len(argv) > 1 else MIN_CASES)
        os.makedirs(os.path.dirname(CASES), exist_ok=True)
        with open(CASES, "w", encoding="utf-8") as fh:
            json.dump(cases, fh, indent=2)
            fh.write("\n")
        print(f"{len(cases)} cases in {CASES}")
        return 0
    if argv[:1] == ["check"] and len(argv) <= 2:
        with open(argv[1] if len(argv) == 2 else CASES, encoding="utf-8") as fh:
            return check(json.load(fh))
    if argv[:1] == ["run"] and (len(argv) == 1 or (len(argv) == 3 and argv[1] == "--play" and argv[2] in [str(n) for n in range(1, PLAYS + 1)])):
        with open(CASES, encoding="utf-8") as fh:
            cases = json.load(fh)
        # A set that does not hold is refused before any paid review (#844).
        if short(cases):
            print(f"review-eval.py: the set has {short(cases)}", file=sys.stderr)
            return 1
        if check(cases):
            return 1
        plays = [int(argv[2])] if len(argv) == 3 else list(range(1, PLAYS + 1))
        results = [{"id": c["id"], "expect": c["expect"], "plays": []} for c in cases]
        for n in plays:
            # Each play on its own clones: a fresh checkout and last.json.
            work = tempfile.mkdtemp(prefix=f"dx-eval-{n}-")
            for c, r in zip(cases, results):
                ok = run_case(c, ROOT, work)
                print(f"  play {n}, {c['id']}: {ok}", file=sys.stderr)
                r["plays"].append(ok)
        print(json.dumps(results, indent=2))
        return 0
    if argv[:1] in (["score"], ["baseline"]) and len(argv) >= 2:
        runs = []
        for f in argv[1:]:
            with open(f, encoding="utf-8") as fh:
                runs.append(json.load(fh))
        results = merge(runs)
        if short(results):
            print(f"review-eval.py: the set has {short(results)}; it is not scored", file=sys.stderr)
            return 1
        if unplayed(results):
            print(f"review-eval.py: not played {PLAYS} times: {', '.join(unplayed(results))}", file=sys.stderr)
            return 1
        now = score(results)
        if argv[0] == "baseline":
            if now["unreviewed"]:
                print(f"review-eval.py: {now['unreviewed']} cases were not reviewed; a baseline is written only from a whole run", file=sys.stderr)
                return 1
            with open(BASELINE, "w", encoding="utf-8") as fh:
                json.dump(now, fh, indent=2)
                fh.write("\n")
            print(json.dumps(now))
            return 0
        try:
            with open(BASELINE, encoding="utf-8") as fh:
                base = json.load(fh)
            # A baseline of another number of plays is not comparable.
            if base.get("plays") != PLAYS:
                raise ValueError("plays")
        except (OSError, ValueError):
            # No baseline is no gate: that fails, it never passes quietly.
            print(table(results, now, {}))
            print(f"\n**No baseline** of {PLAYS} plays at {BASELINE}: write one with `review-eval.py baseline`.")
            return 1
        print(table(results, now, base))
        why = worse(now, base)
        if why:
            print(f"\n**Worse than the baseline:** {why}.")
        return 1 if why else 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
