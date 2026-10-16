#!/usr/bin/env python3
"""What became of the review's findings, for the weekly digest (#234).

The review's blockers and majors are inline threads on the pull request,
each one a finding with a history: who resolved it, whether the line it
points at changed, what a person replied. Over the pull requests merged in
the last four weeks, each thread the review opened is classified:

  fixed           the review resolved it (it saw the fix), the line it
                  points at changed after it (GitHub marks it outdated), or
                  the reply that resolved it starts with "fixed"
  wrong           a person resolved it, replying "wrong: <why>"
  intentional     a person resolved it, replying "intentional: <why>"
  does not matter a person resolved it, replying "does not matter: <why>"
  dismissed       a person resolved it with none of those, the line unchanged
  open            still open when the pull request merged

The noise is the share of wrong, does not matter and dismissed: findings
that changed nothing. It is printed per kind and per repository, the
private ones counted and never named (the digest is a public issue).
Minors are not threads, so they are not measured here.

The words a person replies with are the convention for dismissing a finding
(CONTRIBUTING.md): the first word or words of the reply, in English or
Spanish ("mal", "intencional", "no importa", "arreglado").

  review-outcomes.py                the digest's section (GH_TOKEN, OWNER;
                                    NOW, an ISO time, defaults to now)
  review-outcomes.py --test         self-test
"""
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import org  # noqa: E402  the organisation, from org.yml (#191)

WEEKS = 4
SEARCH_CAP = 1000
OUTCOMES = ("fixed", "wrong", "intentional", "does not matter", "dismissed", "open")
NOISE = ("wrong", "does not matter", "dismissed")
REPLIES = [
    ("fixed", re.compile(r"^\W*(fixed|arreglado|corregido)\b", re.I)),
    ("wrong", re.compile(r"^\W*(wrong|mal|incorrecto)\b", re.I)),
    ("intentional", re.compile(r"^\W*(intentional|intencional|a prop[oó]sito)\b", re.I)),
    ("does not matter", re.compile(r"^\W*(does not matter|doesn'?t matter|no importa)\b", re.I)),
]


def is_bot(author):
    login = (author or {}).get("login") or ""
    return (author or {}).get("__typename") == "Bot" or login in (org.APP, org.BOT)


def review_thread(t):
    """A thread the review opened: its first comment is the bot's and ends
    with the review's AI line."""
    first = ((t.get("comments") or {}).get("nodes") or [None])[0] or {}
    return is_bot(first.get("author")) and "AI review" in (first.get("body") or "")


def outcome(t):
    if not t.get("isResolved"):
        return "open"
    if is_bot(t.get("resolvedBy")):
        return "fixed"
    replies = [c for c in ((t.get("comments") or {}).get("nodes") or [])[1:] if not is_bot(c.get("author"))]
    for c in reversed(replies):
        for name, rx in REPLIES:
            if rx.search(c.get("body") or ""):
                return name
    if t.get("isOutdated"):
        return "fixed"
    return "dismissed"


def tally(prs, kinds):
    """{(scope, name): {outcome: n}} for 'kind' and 'repo' scopes; private
    repositories go under one row."""
    out = {}
    for pr in prs:
        repo = (pr.get("repository") or {})
        full = repo.get("nameWithOwner") or "?"
        public = repo.get("visibility") == "PUBLIC"
        name = full.split("/", 1)[-1]
        for t in ((pr.get("reviewThreads") or {}).get("nodes") or []):
            if not review_thread(t):
                continue
            o = outcome(t)
            for key in (("kind", kinds.get(name) or "unclassified"), ("repo", name if public else "private repositories")):
                out.setdefault(key, {k: 0 for k in OUTCOMES})[o] += 1
    return out


def noise(row):
    total = sum(row.values())
    return (sum(row[k] for k in NOISE) / total) if total else 0.0


def section(prs, kinds):
    t = tally(prs, kinds)
    out = [f"**What became of the review's blockers and majors** (pull requests merged in the last {WEEKS} weeks; the noise is what changed nothing: wrong, does not matter, dismissed)", ""]
    if not t:
        return "\n".join(out + ["No review threads in these weeks."]) + "\n"
    head = "| | Threads | " + " | ".join(o.capitalize() for o in OUTCOMES) + " | Noise |"
    sep = "| --- " * (len(OUTCOMES) + 3) + "|"
    for scope, title in (("kind", "By kind"), ("repo", "By repository")):
        rows = sorted((k[1], v) for k, v in t.items() if k[0] == scope)
        out += [f"_{title}_", "", head, sep]
        for name, row in rows:
            out.append(f"| {name} | {sum(row.values())} | " + " | ".join(str(row[o]) for o in OUTCOMES) + f" | {noise(row):.0%} |")
        out.append("")
    out.append('A person dismissing a finding replies "wrong:", "intentional:" or "does not matter:" before resolving it, so it counts for what it was (CONTRIBUTING.md).')
    return "\n".join(out) + "\n"


QUERY = """
query($q: String!, $endCursor: String) {
  search(query: $q, type: ISSUE, first: 25, after: $endCursor) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      repository { nameWithOwner visibility }
      reviewThreads(first: 100) { nodes {
        isResolved isOutdated
        resolvedBy { __typename login }
        comments(first: 20) { nodes { author { __typename login } body } }
      } }
    } }
  }
}
"""


def fetch(owner, now):
    since = (now - datetime.timedelta(days=7 * WEEKS)).strftime("%Y-%m-%d")
    q = f"org:{owner} is:pr is:merged merged:>={since} commenter:app/{org.APP}"
    out = subprocess.run(["gh", "api", "graphql", "--paginate", "-f", f"query={QUERY}", "-f", f"q={q}",
                          "--jq", '"count \\(.data.search.issueCount)", (.data.search.nodes[] | @json)'],
                         check=True, capture_output=True, text=True).stdout
    prs = []
    for line in out.splitlines():
        if line.startswith("count "):
            if int(line[6:]) > SEARCH_CAP:
                sys.exit(f"The search found {line[6:]} pull requests, more than the {SEARCH_CAP} one search returns: the totals would be cut.")
        elif line.strip():
            prs.append(json.loads(line))
    return prs


def kinds_of():
    """Each repository's kind from repos.yml; several kinds read as the first."""
    import yaml
    with open(os.path.join(HERE, "..", "repos.yml"), encoding="utf-8") as fh:
        conf = yaml.safe_load(fh) or {}
    out = {}
    for name, entry in (conf.get("repos") or {}).items():
        ks = [k.get("kind") for k in ((entry or {}).get("kinds") or []) if k.get("kind")]
        out[name] = ks[0] if ks else "unclassified"
    return out


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    bot = {"__typename": "Bot", "login": org.BOT}
    me = {"__typename": "User", "login": "someone"}
    first = {"author": bot, "body": "This breaks X.\n<sub>🤖 AI review · m (Anthropic)</sub>"}
    t = lambda resolved=True, by=me, outdated=False, *replies: {"isResolved": resolved, "isOutdated": outdated, "resolvedBy": by,
                                                                "comments": {"nodes": [first] + [{"author": me, "body": r} for r in replies]}}
    check("the review resolved it: fixed", outcome(t(True, bot)), "fixed")
    check("a person, replying wrong: wrong", outcome(t(True, me, False, "Wrong: the caller checks it.")), "wrong")
    check("intentional, in Spanish", outcome(t(True, me, False, "intencional, es así a propósito")), "intentional")
    check("does not matter", outcome(t(True, me, False, "doesn't matter here")), "does not matter")
    check("a person, replying fixed: fixed", outcome(t(True, me, False, "Fixed in abc123.")), "fixed")
    check("the line changed after it: fixed", outcome(t(True, me, True)), "fixed")
    check("a person, no reason, the line unchanged: dismissed", outcome(t(True, me, False, "ok")), "dismissed")
    check("the last reply decides", outcome(t(True, me, False, "wrong", "Fixed after all.")), "fixed")
    check("still open at merge", outcome(t(False, None)), "open")
    other = {"isResolved": True, "resolvedBy": me, "comments": {"nodes": [{"author": me, "body": "a person's own thread"}]}}
    prs = [{"repository": {"nameWithOwner": "o/pub", "visibility": "PUBLIC"}, "reviewThreads": {"nodes": [t(True, bot), t(True, me, False, "wrong"), other]}},
           {"repository": {"nameWithOwner": "o/secret", "visibility": "PRIVATE"}, "reviewThreads": {"nodes": [t(True, me)]}}]
    got = tally(prs, {"pub": "wordpress-plugin", "secret": "wordpress-plugin"})
    check("tally: by kind, a person's own thread left out", (got[("kind", "wordpress-plugin")]["fixed"], got[("kind", "wordpress-plugin")]["wrong"], got[("kind", "wordpress-plugin")]["dismissed"]), (1, 1, 1))
    check("tally: a private repository is never named", (("repo", "secret") in got, got[("repo", "private repositories")]["dismissed"]), (False, 1))
    text = section(prs, {"pub": "wordpress-plugin", "secret": "wordpress-plugin"})
    check("section: the noise per row, the private one unnamed", ("| wordpress-plugin | 3 | 1 | 1 | 0 | 0 | 1 | 0 | 67% |" in text, "secret" not in text), (True, True))
    check("section: no threads says so", "No review threads" in section([], {}), True)
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv:
        print(__doc__, file=sys.stderr)
        return 64
    now = datetime.datetime.fromisoformat(os.environ["NOW"].replace("Z", "+00:00")) if os.environ.get("NOW") else datetime.datetime.now(datetime.timezone.utc)
    print(section(fetch(os.environ.get("OWNER") or org.ORG, now), kinds_of()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
