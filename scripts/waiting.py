#!/usr/bin/env python3
"""What waits, every day (#479): every open pull request of the organisation
older than a day, with what blocks it and on whom it waits, in one issue the
maintainer reads (waiting-digest.yml keeps its body up to date, pinned in
DiluxOne/.github, instead of one comment per pull request).

What blocks a pull request, read from GitHub, the first that applies:

  needs-human          a person has it (`needs-human`)         the maintainer
  its question         the autopilot asked (`autopilot:waiting` on the issue
                       it closes)                               the maintainer
  an acceptance        an issue it closes is not `accepted`   the maintainer
  a failed check       a check of its head failed             its author (the
                                                              autopilot for its own)
  unresolved threads   a review conversation is open          its author
  the autopilot's work an autopilot draft                     the autopilot
  a draft              someone else's draft                   its author
  checks running       its head's checks have not finished    the checks
  a person's merge     nothing else: it is ready              the maintainer

The issue is public: a private repository's pull requests are counted under
what blocks them, never named.

  waiting.py            the issue's body, from the organisation's open pull
                        requests (GH_TOKEN, OWNER; NOW, an ISO time,
                        defaults to now)
  waiting.py render FILE  the body from FILE, a JSON list of pull requests as
                        the search below returns them (NOW as above)
  waiting.py --test     self-test, from fixtures/waiting.json
"""
import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import org  # noqa: E402  the organisation's App, from org.yml (#568)
MARKER = "<!-- dx-waiting -->"
BOT_LOGINS = (org.APP, org.BOT, f"app/{org.APP}")
MAINTAINER, AUTHOR, AUTOPILOT, CHECKS = "the maintainer", "its author", "the autopilot", "the checks"
ORDER = (MAINTAINER, AUTHOR, AUTOPILOT, CHECKS)
DAY = datetime.timedelta(days=1)

QUERY = """query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 50, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      number title url createdAt isDraft
      author { login }
      repository { name isPrivate }
      labels(first: 30) { nodes { name } }
      reviewThreads(first: 100) { nodes { isResolved } }
      commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
      closingIssuesReferences(first: 10) { nodes { number labels(first: 30) { nodes { name } } } }
    } }
  }
}"""


def names(conn):
    return [n.get("name") for n in ((conn or {}).get("nodes") or []) if n]


def blocker(pr):
    """(what blocks it, on whom it waits) for one pull request. Pure."""
    labels = names(pr.get("labels"))
    author = ((pr.get("author") or {}).get("login") or "")
    autopilot = "autopilot" in labels and author in BOT_LOGINS
    issues = (pr.get("closingIssuesReferences") or {}).get("nodes") or []
    if "needs-human" in labels:
        return "needs-human", MAINTAINER
    if any("autopilot:waiting" in names(i.get("labels")) for i in issues):
        return "its question", MAINTAINER
    if any("accepted" not in names(i.get("labels")) for i in issues):
        return "an acceptance", MAINTAINER
    commits = (pr.get("commits") or {}).get("nodes") or []
    state = (((commits[-1] if commits else {}).get("commit") or {}).get("statusCheckRollup") or {}).get("state") or ""
    if state in ("FAILURE", "ERROR"):
        return "a failed check", AUTOPILOT if autopilot else AUTHOR
    open_threads = sum(1 for t in ((pr.get("reviewThreads") or {}).get("nodes") or []) if not t.get("isResolved"))
    if open_threads:
        return f"{open_threads} unresolved thread{'s' if open_threads > 1 else ''}", AUTOPILOT if autopilot else AUTHOR
    if pr.get("isDraft"):
        return ("the autopilot's work", AUTOPILOT) if autopilot else ("a draft", AUTHOR)
    if state in ("PENDING", "EXPECTED"):
        return "checks running", CHECKS
    return "a person's merge", MAINTAINER


def parse(ts):
    return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def age(created, now):
    days = (now - parse(created)).total_seconds() / 86400
    return f"{int(days)} day{'s' if int(days) != 1 else ''}"


def render(prs, now):
    """The issue's body: the pull requests older than a day, by whom they
    wait on, oldest first; private ones counted. Pure."""
    old = [p for p in prs if now - parse(p["createdAt"]) > DAY]
    groups = {w: [] for w in ORDER}
    hidden = {}
    for p in sorted(old, key=lambda p: p["createdAt"]):
        what, who = blocker(p)
        if (p.get("repository") or {}).get("isPrivate"):
            hidden[(who, what)] = hidden.get((who, what), 0) + 1
            continue
        author = (p.get("author") or {}).get("login") or "?"
        whom = f"{who} (`{author}`)" if who == AUTHOR else who
        groups[who].append(f"- [{p['repository']['name']}#{p['number']}]({p['url']}) {p['title'].replace('[', '(').replace(']', ')')}: "
                           f"**{what}**, waits on {whom}, open {age(p['createdAt'], now)}")
    lines = [MARKER, f"# What waits ({now.strftime('%Y-%m-%d')})", "",
             "Every open pull request of the organisation older than a day, what blocks it and on whom it waits (#479, "
             "`scripts/waiting.py`). This body is rewritten every day.", ""]
    if not old:
        lines += ["Nothing has waited more than a day."]
    for who in ORDER:
        if groups[who] or any(k[0] == who for k in hidden):
            lines += [f"## Waits on {who}", ""] + groups[who]
            lines += [f"- {n} in private repositories: **{what}**" for (w, what), n in sorted(hidden.items()) if w == who]
            lines += [""]
    return "\n".join(lines).rstrip() + "\n"


def fetch(owner, now):
    """The organisation's open pull requests opened before a day ago."""
    since = (now - DAY).strftime("%Y-%m-%dT%H:%M:%SZ")
    q, after, out = f"org:{owner} is:pr is:open created:<{since}", None, []
    while True:
        args = ["gh", "api", "graphql", "-f", f"query={QUERY}", "-f", f"q={q}"] + (["-f", f"after={after}"] if after else [])
        res = subprocess.run(args, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"the search failed: {res.stderr.strip()[:300]}")
        page = json.loads(res.stdout)["data"]["search"]
        out += [n for n in page["nodes"] if n]
        if not page["pageInfo"]["hasNextPage"]:
            return out
        after = page["pageInfo"]["endCursor"]


def now_():
    return parse(os.environ["NOW"]) if os.environ.get("NOW") else datetime.datetime.now(datetime.timezone.utc)


def self_test():
    fails = []

    def check(name, got, want):
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        if got != want:
            fails.append(name)

    with open(os.path.join(HERE, "fixtures", "waiting.json"), encoding="utf-8") as fh:
        fx = json.load(fh)
    now = parse(fx["now"])
    want = {p["title"]: tuple(p["want"]) for p in fx["prs"]}
    for p in fx["prs"]:
        check(f"C7 {p['title']}: {p['want'][0]}, waits on {p['want'][1]}", blocker(p), want[p["title"]])
    body = render(fx["prs"], now)
    check("C7 the body starts with its marker", body.startswith(MARKER), True)
    check("C7 a pull request of today is not listed", "opened today" in body, False)
    check("C7 every public one older than a day is listed, with what blocks it and on whom it waits",
          all(f"**{p['want'][0]}**, waits on {p['want'][1]}" in body for p in fx["prs"]
              if not p["repository"]["isPrivate"] and now - parse(p["createdAt"]) > DAY), True)
    check("C7 a private one is counted, never named", ("secret-repo" in body, "- 1 in private repositories: **a failed check**" in body), (False, True))
    check("C7 grouped by whom it waits on, the maintainer first", body.index("## Waits on the maintainer") < body.index("## Waits on its author"), True)
    check("C7 the author is named where it waits on them", "waits on its author (`someone`)" in body, True)
    check("C7 a title cannot break the link", "[x] link" in body, False)
    check("C7 nothing older than a day says so", "Nothing has waited more than a day." in render([], now), True)
    print("all tests passed" if not fails else f"{len(fails)} failed")
    return 1 if fails else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if len(argv) == 2 and argv[0] == "render":
        with open(argv[1], encoding="utf-8") as fh:
            sys.stdout.write(render(json.load(fh), now_()))
        return 0
    if not argv:
        now = now_()
        sys.stdout.write(render(fetch(os.environ.get("OWNER", "DiluxOne"), now), now))
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
