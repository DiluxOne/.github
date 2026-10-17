#!/usr/bin/env python3
"""The review's evaluation set: a change to the review is scored first (#234).

The cases are real pull requests of the organisation's public repositories
(a private one's code would show in this public repository's logs):

  flag   the commit where the review raised a blocker or major that was
         then fixed (the review resolved its thread, or its line changed):
         a real bug. The review must raise a blocker or major on that file
         again.
  clean  the last commit of a merged pull request on which the review left
         no thread at all. The review must not block it.

Each case is reviewed again, with the rules as they stand in the checkout,
by scripts/local-review.sh (the same brief, profiles and model the pull
request's review uses). The score is the share of `flag` cases found and of
`clean` cases blocked; review-eval.yml fails a change to the review whose
score is worse than evals/review/baseline.json by more than one case on
either side (a model does not answer the same twice).

  review-eval.py collect [N]   write evals/review/cases.json: N cases of each
                               kind (default 6), from the review's threads
                               (GH_TOKEN, read)
  review-eval.py run           review every case; results on stdout (JSON)
                               (the Claude Code CLI, git, the checkout)
  review-eval.py score FILE    the results in FILE against the baseline:
                               a table on stdout, exit 1 when worse
  review-eval.py baseline FILE write the results in FILE as the baseline
  review-eval.py --test        self-test
"""
import json
import os
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

QUERY = """
query($q: String!) {
  search(query: $q, type: ISSUE, first: 50) {
    nodes { ... on PullRequest {
      number title baseRefOid headRefOid
      reviewThreads(first: 50) { nodes {
        isResolved isOutdated path resolvedBy { login }
        comments(first: 1) { nodes { author { login } body originalCommit { oid } } }
      } }
    } }
  }
}
"""


def is_review(t):
    c = ((t.get("comments") or {}).get("nodes") or [{}])[0] or {}
    return (c.get("author") or {}).get("login") == org.APP and "AI review" in (c.get("body") or "")


def cases_from(repo, prs, n):
    """Up to n `flag` and n `clean` cases from one repository's pull requests."""
    flag, clean = [], []
    for pr in prs:
        threads = [t for t in ((pr.get("reviewThreads") or {}).get("nodes") or [])]
        fixed = [t for t in threads if is_review(t) and (((t.get("resolvedBy") or {}).get("login") == org.APP) or t.get("isOutdated"))]
        if fixed:
            t = fixed[0]
            head = (((t.get("comments") or {}).get("nodes") or [{}])[0].get("originalCommit") or {}).get("oid")
            if head and len(flag) < n:
                flag.append({"id": f"{repo}#{pr['number']}:flag", "repo": repo, "pr": pr["number"], "title": pr.get("title") or "",
                             "base": pr.get("baseRefOid"), "head": head, "expect": "flag", "path": t.get("path")})
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
    for name in public_repos():
        full = f"{org.ORG}/{name}"
        out = gh("api", "graphql", "-f", f"query={QUERY}", "-f", f"q=repo:{full} is:pr is:merged commenter:app/{org.APP}")
        prs = json.loads(out)["data"]["search"]["nodes"]
        per_repo[full] = cases_from(full, prs, n)
    return pick(per_repo, n)


def verdict(case, review):
    """Whether the review did what the case expects. review is
    local-review.sh's last.json, or None when it gave none."""
    if not isinstance(review, dict):
        return None
    serious = [f for f in review.get("findings") or [] if isinstance(f, dict)
               and f.get("severity") in ("blocker", "major") and not f.get("pre_existing")]
    if case["expect"] == "flag":
        return any(f.get("file") == case["path"] for f in serious)
    return not serious


def run_case(case, central, work):
    """Review one case; True, False, or None when it could not be reviewed."""
    repo_dir = os.path.join(work, case["repo"].replace("/", "_"))
    git = lambda *a: subprocess.run(["git", "-C", repo_dir, *a], capture_output=True, text=True)
    if not os.path.isdir(repo_dir):
        subprocess.run(["git", "clone", "-q", f"https://github.com/{case['repo']}", repo_dir], check=True)
    git("fetch", "-q", "origin", f"refs/pull/{case['pr']}/head", case["base"])
    if git("cat-file", "-e", case["head"] + "^{commit}").returncode != 0:
        git("fetch", "-q", "origin", case["head"])
    if git("checkout", "-q", "-B", f"eval/{case['pr']}", case["head"]).returncode != 0:
        return None
    state = os.path.join(repo_dir, ".git", "dx-review", "last.json")
    if os.path.exists(state):
        os.remove(state)
    subprocess.run(["bash", os.path.join(central, "scripts", "local-review.sh"), "--base", case["base"], "--full", "--title", case["title"]],
                   cwd=repo_dir, capture_output=True, text=True)
    try:
        with open(state, encoding="utf-8") as fh:
            return verdict(case, json.load(fh))
    except (OSError, ValueError):
        return None


def score(results):
    flag = [r for r in results if r["expect"] == "flag" and r["ok"] is not None]
    clean = [r for r in results if r["expect"] == "clean" and r["ok"] is not None]
    return {"found": sum(1 for r in flag if r["ok"]), "flag": len(flag),
            "blocked": sum(1 for r in clean if not r["ok"]), "clean": len(clean),
            "unreviewed": sum(1 for r in results if r["ok"] is None)}


def worse(now, base):
    """Why the score is worse than the baseline by more than SLACK, or ''."""
    why = []
    if base.get("flag") and now["found"] < base["found"] - SLACK:
        why.append(f"it found {now['found']} of {now['flag']} known bugs, the baseline {base['found']} of {base['flag']}")
    if now["blocked"] > base.get("blocked", 0) + SLACK:
        why.append(f"it blocked {now['blocked']} of {now['clean']} clean pull requests, the baseline {base.get('blocked', 0)}")
    if now["unreviewed"] > (now["flag"] + now["clean"] + now["unreviewed"]) // 2:
        why.append(f"{now['unreviewed']} cases could not be reviewed")
    return "; ".join(why)


def table(results, now, base):
    out = ["| Case | Expects | Result |", "| --- | --- | --- |"]
    for r in results:
        res = "could not review" if r["ok"] is None else ("as expected" if r["ok"] else "**missed**" if r["expect"] == "flag" else "**blocked**")
        out.append(f"| {r['id']} | {r['expect']} | {res} |")
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
    prs = [{"number": 1, "title": "fix: a", "baseRefOid": "b1", "headRefOid": "h1", "reviewThreads": {"nodes": [{"isOutdated": True, "path": "a.php", "resolvedBy": None, "comments": first("c1")}]}},
           {"number": 2, "title": "feat: b", "baseRefOid": "b2", "headRefOid": "h2", "reviewThreads": {"nodes": []}},
           {"number": 3, "title": "fix: c", "baseRefOid": "b3", "headRefOid": "h3", "reviewThreads": {"nodes": [{"isOutdated": False, "path": "c.php", "resolvedBy": {"login": "me"}, "comments": first("c3")}]}}]
    flag, clean = cases_from("o/r", prs, 5)
    check("cases: a fixed finding is a flag case at the commit it was raised on", [(c["pr"], c["head"], c["path"]) for c in flag], [(1, "c1", "a.php")])
    check("cases: a pull request with no thread is clean at its last commit; a dismissed one is neither", [(c["pr"], c["head"]) for c in clean], [(2, "h2")])
    picked = pick({"o/a": ([{"id": "a1"}, {"id": "a2"}], []), "o/b": ([{"id": "b1"}], [])}, 2)
    check("pick: round the repositories", [c["id"] for c in picked], ["a1", "b1"])
    case_f = {"expect": "flag", "path": "a.php"}
    check("verdict: flag found on its file", verdict(case_f, {"findings": [{"severity": "major", "file": "a.php"}]}), True)
    check("verdict: flag missed (a minor, another file, a pre-existing one)", verdict(case_f, {"findings": [{"severity": "minor", "file": "a.php"}, {"severity": "major", "file": "b.php"}, {"severity": "blocker", "file": "a.php", "pre_existing": True}]}), False)
    check("verdict: clean kept clean; clean blocked", (verdict({"expect": "clean"}, {"findings": [{"severity": "minor"}]}), verdict({"expect": "clean"}, {"findings": [{"severity": "major"}]})), (True, False))
    check("verdict: no review is unknown", verdict(case_f, None), None)
    res = [{"id": "1", "expect": "flag", "ok": True}, {"id": "2", "expect": "flag", "ok": False}, {"id": "3", "expect": "clean", "ok": False}, {"id": "4", "expect": "clean", "ok": None}]
    now = score(res)
    check("score: found, blocked, unreviewed", now, {"found": 1, "flag": 2, "blocked": 1, "clean": 1, "unreviewed": 1})
    check("worse: within one case of the baseline is not worse", worse(now, {"found": 2, "flag": 2, "blocked": 0}), "")
    check("worse: two fewer bugs found is", worse({**now, "found": 0}, {"found": 2, "flag": 2, "blocked": 0}).startswith("it found 0 of 2"), True)
    check("worse: two more clean ones blocked is", "it blocked 2" in worse({**now, "blocked": 2}, {"found": 1, "flag": 2, "blocked": 0}), True)
    check("worse: most cases unreviewed is", "could not be reviewed" in worse({"found": 0, "flag": 0, "blocked": 0, "clean": 1, "unreviewed": 3}, {}), True)
    check("table: says what was missed", "**missed**" in table(res, now, {}), True)
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv[:1] == ["collect"]:
        cases = collect(int(argv[1]) if len(argv) > 1 else 6)
        os.makedirs(os.path.dirname(CASES), exist_ok=True)
        with open(CASES, "w", encoding="utf-8") as fh:
            json.dump(cases, fh, indent=2)
            fh.write("\n")
        print(f"{len(cases)} cases in {CASES}")
        return 0
    if argv == ["run"]:
        with open(CASES, encoding="utf-8") as fh:
            cases = json.load(fh)
        work = tempfile.mkdtemp(prefix="dx-eval-")
        results = []
        for c in cases:
            ok = run_case(c, ROOT, work)
            print(f"  {c['id']}: {ok}", file=sys.stderr)
            results.append({"id": c["id"], "expect": c["expect"], "ok": ok})
        print(json.dumps(results, indent=2))
        return 0
    if argv[:1] in (["score"], ["baseline"]) and len(argv) == 2:
        with open(argv[1], encoding="utf-8") as fh:
            results = json.load(fh)
        now = score(results)
        if argv[0] == "baseline":
            with open(BASELINE, "w", encoding="utf-8") as fh:
                json.dump(now, fh, indent=2)
                fh.write("\n")
            print(json.dumps(now))
            return 0
        try:
            with open(BASELINE, encoding="utf-8") as fh:
                base = json.load(fh)
        except OSError:
            base = {}
        print(table(results, now, base))
        why = worse(now, base) if base else ""
        if why:
            print(f"\n**Worse than the baseline:** {why}.")
        return 1 if why else 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
