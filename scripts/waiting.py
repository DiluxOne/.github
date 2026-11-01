#!/usr/bin/env python3
"""What waits on whom (#479, #564): every open issue and pull request of the
organisation that waits on a person, the action and its URL, grouped by
person, in one issue the maintainer reads (waiting-digest.yml keeps its body
up to date, pinned in DiluxOne/.github), and on each item's board, its
"Waits on" row, with one mention of the person on the item itself the first
time a step waits on them (waiting-update.yml, on the item's events).

What blocks a pull request, read from GitHub, the first that applies:

  needs-human          a person has it (`needs-human`)         the maintainer
  its question         the autopilot asked (`waiting` in the board's state
                       of the issue it closes, #564; a state
                       edited by hand counts as one)            the maintainer
  an acceptance        an issue it closes is not `accepted`   the maintainer
  a failed check       a check of its head failed             its author (the
                                                              autopilot for its own)
  unresolved threads   a review conversation is open          its author
  the autopilot's work an autopilot draft                     the autopilot
  a draft              someone else's draft                   its author
  checks running       its head's checks have not finished    the checks
  a person's merge     nothing else: it is ready              the maintainer

What blocks an issue, the first that applies (none: it waits on nobody):

  needs-human          a person has it (`needs-human`)         the maintainer
  its question         the autopilot asked (`waiting` in its board's state)
                                                              the maintainer
  their claimed work   accepted and `claimed`, with no pull request open
                                                              its claimant
  its PRD              not accepted and `incomplete`          its author
  an answer            not accepted, the triage asked for more
                       (`verdict: needs-info` in its state)   its author
  an acceptance        `awaiting-acceptance`, not `accepted`  the maintainer

"The maintainer" is MAINTAINER's login; its author and its claimant are
theirs, so an outside contributor is named, and mentioned, only for their own
step, and never for a maintainer's (AGENTS.md, rule 7). The issue is public:
a private repository's items are counted under whom they wait on, never
named, and nobody is mentioned in it (no `@`).

  waiting.py            the issue's body, from the organisation's open issues
                        and pull requests (GH_TOKEN, OWNER, MAINTAINER; NOW,
                        an ISO time, defaults to now)
  waiting.py render FILE  the body from FILE, a JSON list of items as the
                        search below returns them (NOW, MAINTAINER as above)
  waiting.py update     one item (GITHUB_REPOSITORY, NUMBER, GH_TOKEN,
                        MAINTAINER, SENDER: who acted, never mentioned for
                        it): its board's "Waits on" row, and the mention
  waiting.py --test     self-test, from fixtures/waiting.json
"""
import datetime
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MARKER = "<!-- dx-waiting -->"
BOT_LOGINS = ("dilux-bot", "dilux-bot[bot]", "app/dilux-bot")
MAINTAINER, AUTHOR, CLAIMANT, AUTOPILOT, CHECKS = "the maintainer", "its author", "its claimant", "the autopilot", "the checks"
SIGN = "<sub>🤖 What waits (scripts/waiting.py)</sub>"
CLAIM_RE = re.compile(r"<!-- dx-claim (\{.*?\}) -->")

# What a person does about each step: the line starts with it, its URL next.
ACTIONS = {
    "needs-human": "Take over",
    "its question": "Answer the autopilot's question on",
    "an acceptance": "Add `accepted` to, or close,",
    "a failed check": "Fix the failed check of",
    "unresolved threads": "Resolve the review threads of",
    "the autopilot's work": "The autopilot works on",
    "a draft": "Finish the draft",
    "checks running": "The checks run on",
    "a person's merge": "Approve and merge",
    "their claimed work": "Open the pull request for the claim on",
    "its PRD": "Complete the PRD of",
    "an answer": "Answer the triage's question on",
}

ITEM = """
      number title url createdAt state
      author { login }
      repository { name nameWithOwner isPrivate }
      labels(first: 30) { nodes { name } }"""
PR_FIELDS = ITEM + """
      isDraft
      reviewThreads(first: 100) { nodes { isResolved } }
      commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
      closingIssuesReferences(first: 10) { nodes { number labels(first: 30) { nodes { name } }
        comments(last: 50) { nodes { author { __typename login } body } } } }"""
ISSUE_FIELDS = ITEM + """
      comments(last: 100) { nodes { author { __typename login } body } }
      closedByPullRequestsReferences(first: 5) { totalCount }"""
QUERY = """query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 50, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      __typename
      ... on PullRequest {""" + PR_FIELDS + """ }
      ... on Issue {""" + ISSUE_FIELDS + """ }
    }
  }
}"""
ITEM_QUERY = """query($o: String!, $n: String!, $i: Int!) {
  repository(owner: $o, name: $n) {
    issueOrPullRequest(number: $i) {
      __typename
      ... on PullRequest {""" + PR_FIELDS + """ }
      ... on Issue {""" + ISSUE_FIELDS + """ }
    }
  }
}"""


def names(conn):
    return [n.get("name") for n in ((conn or {}).get("nodes") or []) if n]


_RECEIPTS = []


def receipts():
    """scripts/receipts.py, the board's state (#564), loaded once."""
    if not _RECEIPTS:
        spec = importlib.util.spec_from_file_location("receipts", os.path.join(HERE, "receipts.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _RECEIPTS.append(mod)
    return _RECEIPTS[0]


def bot_comments(issue):
    """The comments of the organisation's App among those the search read,
    as receipts.py reads them. Pure but for loading receipts.py."""
    rc = receipts()
    cs = [{"user": {"login": (c.get("author") or {}).get("login") or "", "type": (c.get("author") or {}).get("__typename") or ""},
           "body": c.get("body") or ""} for c in ((issue.get("comments") or {}).get("nodes") or []) if c]
    return [c for c in cs if c["user"]["type"] == "Bot" and c["user"]["login"].startswith(rc.bot_app())]


def issue_state(issue):
    """An issue's board's state (#564), from the comments the search read:
    only the bot's board counts. Pure but for loading receipts.py."""
    rc = receipts()
    c = rc.board_comment(bot_comments(issue), rc.bot_app())
    return rc.parse_state(c["body"]) if c else {}


def is_bot(login):
    return not login or login in BOT_LOGINS or login.endswith("[bot]")


def blocker(pr):
    """(what blocks it, on whom it waits) for one pull request. Pure."""
    labels = names(pr.get("labels"))
    author = ((pr.get("author") or {}).get("login") or "")
    autopilot = "autopilot" in labels and author in BOT_LOGINS
    issues = (pr.get("closingIssuesReferences") or {}).get("nodes") or []
    if "needs-human" in labels:
        return "needs-human", MAINTAINER
    if any(st.get("waiting") or st.get("tampered") for st in map(issue_state, issues)):
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


def issue_blocker(issue):
    """(what blocks it, on whom it waits) for one issue, or None when it
    waits on nobody (the autopilot's, or nobody's yet). Pure."""
    labels = names(issue.get("labels"))
    state = issue_state(issue)
    if "needs-human" in labels:
        return "needs-human", MAINTAINER
    if state.get("waiting") or state.get("tampered"):
        return "its question", MAINTAINER
    if "accepted" in labels:
        if "claimed" in labels and not ((issue.get("closedByPullRequestsReferences") or {}).get("totalCount") or 0):
            return "their claimed work", CLAIMANT
        return None
    if "incomplete" in labels:
        return "its PRD", AUTHOR
    if state.get("verdict") == "needs-info":
        return "an answer", AUTHOR
    if "awaiting-acceptance" in labels:
        return "an acceptance", MAINTAINER
    return None


def what_waits(item):
    return blocker(item) if item.get("__typename") == "PullRequest" else issue_blocker(item)


def claimant(issue):
    """The login the bot's last dx-claim marker names (scripts/claim.py)."""
    who = None
    for c in bot_comments(issue):
        for m in CLAIM_RE.finditer(c["body"]):
            try:
                who = json.loads(m.group(1)).get("login") or who
            except ValueError:
                continue
    return who


def person(item, role, maintainer):
    """The login a step waits on, or None when it is no person's (the
    autopilot, the checks, a bot, a maintainer nobody named). Pure."""
    if role == MAINTAINER:
        return maintainer or None
    if role == AUTHOR:
        who = (item.get("author") or {}).get("login") or ""
        return None if is_bot(who) else who
    if role == CLAIMANT:
        who = claimant(item)
        return None if is_bot(who or "") else who
    return None


def action(what, item=None):
    if what == "an acceptance" and (item or {}).get("__typename") == "PullRequest":
        return "Accept the issue closed by"
    return ACTIONS.get("unresolved threads" if what.endswith("unresolved thread") or what.endswith("unresolved threads") else what, what)


def parse(ts):
    return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def age(created, now):
    days = (now - parse(created)).total_seconds() / 86400
    return f"{int(days)} day{'s' if int(days) != 1 else ''}"


def render(items, now, maintainer=""):
    """The issue's body: every open item that waits, grouped by the person
    it waits on (the maintainer first), one line per action with its URL,
    oldest first; then the autopilot's and the checks'. Private ones
    counted, never named; nobody mentioned. Pure."""
    groups, hidden, roles = {}, {}, {}
    for p in sorted(items, key=lambda p: p["createdAt"]):
        res = what_waits(p)
        if not res:
            continue
        what, role = res
        who = person(p, role, maintainer) or role
        roles[who] = role
        if (p.get("repository") or {}).get("isPrivate"):
            hidden.setdefault(who, {})
            hidden[who][what] = hidden[who].get(what, 0) + 1
            continue
        title = p["title"].replace("[", "(").replace("]", ")")
        groups.setdefault(who, []).append(f"- {action(what, p)} {p['url']} ({p['repository']['name']}#{p['number']} {title}: "
                                          f"**{what}**, open {age(p['createdAt'], now)})")
    people = sorted(set(groups) | set(hidden), key=lambda w: (0 if roles.get(w) == MAINTAINER else 2 if w in (AUTOPILOT, CHECKS) else 1,
                                                             w == CHECKS, w.lower()))
    lines = [MARKER, f"# What waits ({now.strftime('%Y-%m-%d %H:%M')} UTC)", "",
             "Every open issue and pull request of the organisation that waits on someone, the action and its link, by person "
             "(#479, #564, `scripts/waiting.py`). It is rewritten when an item changes, and every day; the person is mentioned "
             "once, on the item itself.", ""]
    if not people:
        lines += ["Nothing waits on anyone."]
    for who in people:
        head = who if who in (AUTOPILOT, CHECKS, MAINTAINER, AUTHOR, CLAIMANT) else f"`{who}`" + (" (the maintainer)" if roles.get(who) == MAINTAINER else "")
        lines += [f"## Waits on {head}", ""] + groups.get(who, [])
        lines += [f"- {n} in private repositories: **{what}**" for what, n in sorted((hidden.get(who) or {}).items())]
        lines += [""]
    return "\n".join(lines).rstrip() + "\n"


def step(item, state, maintainer, sender=""):
    """(the item's new board state, the mention to post or None) for one
    item now (#564): its "Waits on" row, and one mention of the person the
    first time this step waits on them. Pure."""
    res = what_waits(item) if item.get("state", "OPEN") == "OPEN" else None
    if not res:
        return receipts().wait_on(state, "")
    what, role = res
    who = person(item, role, maintainer)
    return receipts().wait_on(state, who or role, action(what, item), item.get("url", ""), person=bool(who), sender=sender)


def gh_json(args):
    res = subprocess.run(["gh"] + args, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip()[:300])
    return json.loads(res.stdout)


def fetch(owner):
    """The organisation's open issues and pull requests."""
    q, after, out = f"org:{owner} is:open", None, []
    while True:
        page = gh_json(["api", "graphql", "-f", f"query={QUERY}", "-f", f"q={q}"] + (["-f", f"after={after}"] if after else []))["data"]["search"]
        out += [n for n in page["nodes"] if n and n.get("__typename") in ("Issue", "PullRequest")]
        if not page["pageInfo"]["hasNextPage"]:
            return out
        after = page["pageInfo"]["endCursor"]


def update(repo, number, maintainer, sender):
    """One item, on GitHub: its board's "Waits on" row, and the mention."""
    rc = receipts()
    if os.environ.get("ITEM_FIXTURE"):
        item = json.load(open(os.environ["ITEM_FIXTURE"], encoding="utf-8"))
    else:
        owner, name = repo.split("/", 1)
        item = gh_json(["api", "graphql", "-f", f"query={ITEM_QUERY}", "-F", f"o={owner}", "-F", f"n={name}", "-F", f"i={number}"])["data"]["repository"]["issueOrPullRequest"]
    if not item:
        print(f"#{number} could not be read")
        return 1
    state = rc.read_state(repo, number)
    new, mention = step(item, state, maintainer, sender)
    if new != state:
        rc.write_state(repo, number, new, "The pull request's board" if item.get("__typename") == "PullRequest" else "The board")
    if mention:
        body = f"{mention}\n\n{SIGN}"
        if os.environ.get("MENTION_LOG"):
            with open(os.environ["MENTION_LOG"], "a", encoding="utf-8") as fh:
                fh.write(body + "\n")
        else:
            subprocess.run(["gh", "api", "-X", "POST", f"repos/{repo}/issues/{number}/comments", "-f", f"body={body}"], check=True, capture_output=True)
    w = new.get("waits_on") or {}
    print(f"#{number}: waits on {w.get('who') or 'nobody'}{(': ' + w.get('what', '')) if w else ''}{' (mentioned)' if mention else ''}")
    return 0


def now_():
    return parse(os.environ["NOW"]) if os.environ.get("NOW") else datetime.datetime.now(datetime.timezone.utc)


def self_test():
    fails = []

    def check(name, got, want):
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        if got != want:
            fails.append(name)

    rc = receipts()
    with open(os.path.join(HERE, "fixtures", "waiting.json"), encoding="utf-8") as fh:
        fx = json.load(fh)
    now = parse(fx["now"])
    for p in fx["prs"]:
        p.setdefault("__typename", "PullRequest")
        check(f"C7 {p['title']}: {p['want'][0]}, waits on {p['want'][1]}", blocker(p), tuple(p["want"]))
    for i in fx["issues"]:
        i.setdefault("__typename", "Issue")
        check(f"#564 C3 issue {i['title']}: {i['want']}", list(issue_blocker(i) or []) or None, i["want"])
    items = fx["prs"] + fx["issues"]
    body = render(items, now, "boss")
    check("C7 the body starts with its marker", body.startswith(MARKER), True)
    public = [p for p in items if not p["repository"]["isPrivate"] and what_waits(p)]
    check("#564 C3 issues and pull requests alike, of today too: each action with its full URL",
          all(f"- {action(what_waits(p)[0], p)} {p['url']} " in body for p in public), True)
    check("#564 C3 an issue nobody waits on is not listed", "accepted, the autopilot's" in body, False)
    check("#564 C3 grouped by person: the maintainer first, then each author, then the autopilot and the checks",
          [body.index(h) for h in ("## Waits on `boss` (the maintainer)", "## Waits on `ana`", "## Waits on `someone`", "## Waits on the autopilot", "## Waits on the checks")]
          == sorted(body.index(h) for h in ("## Waits on `boss` (the maintainer)", "## Waits on `ana`", "## Waits on `someone`", "## Waits on the autopilot", "## Waits on the checks")), True)
    accept = next(i for i in fx["issues"] if i["want"] == ["an acceptance", MAINTAINER])
    mine = body[body.index("## Waits on `boss`"):body.index("## Waits on `ana`")]
    check("#564 C3 the maintainer's acceptance, with its link, under the maintainer", f"- Add `accepted` to, or close, {accept['url']} " in mine, True)
    claimed = next(i for i in fx["issues"] if i["want"] == ["their claimed work", CLAIMANT])
    check("#564 C3 a claim waits on its claimant, named from the bot's marker", person(claimed, CLAIMANT, "boss"), "ana")
    check("#564 C3 a forged claim marker in a person's comment names nobody",
          claimant({"comments": {"nodes": [{"author": {"__typename": "User", "login": "mallory"}, "body": '<!-- dx-claim {"login": "mallory"} -->'}]}}), None)
    check("C7 a private one is counted, never named", ("secret-repo" in body, "- 1 in private repositories: **a failed check**" in body), (False, True))
    check("#564 C3 nobody is mentioned in the public view", "@" in body.replace("dilux-bot[bot]", ""), False)
    check("C7 a title cannot break the link", "[x] link" in body, False)
    check("#564 C3 without a maintainer's login, their steps are under the maintainer", "## Waits on the maintainer" in render(items, now, ""), True)
    # The item's board and its one mention (waiting.py update).
    incomplete = next(i for i in fx["issues"] if i["want"] == ["its PRD", AUTHOR])
    st, said = step(incomplete, {}, "boss")
    check("#564 C3 an outside contributor's step: the board names them, with the action and its URL",
          st["waits_on"], {"who": "ana", "what": "Complete the PRD of", "url": incomplete["url"]})
    check("#564 C3 and they are mentioned on the item, once", said, f"@ana: Complete the PRD of {incomplete['url']}")
    check("#564 C3 the same step again mentions nobody", step(incomplete, st, "boss")[1], None)
    st2, said2 = step(accept, {}, "boss")
    check("#564 C3 the maintainer's step mentions the maintainer, never the author", (said2, "ana" in json.dumps(st2)), (f"@boss: Add `accepted` to, or close, {accept['url']}", False))
    check("#564 C3 a new step of the same person mentions them again", bool(step(incomplete, {**st, "mentioned": ["ana|Answer the triage's question on"]}, "boss")[1]), True)
    check("#564 C3 a step of the person who just acted mentions nobody, and is recorded", step(incomplete, {}, "boss", sender="ana")[1:], (None,))
    check("#564 C3 ... recorded so it is not mentioned later", step(incomplete, step(incomplete, {}, "boss", sender="ana")[0], "boss")[1], None)
    auto = next(p for p in fx["prs"] if p["want"] == ["the autopilot's work", AUTOPILOT])
    st3, said3 = step(auto, {}, "boss")
    check("#564 C3 the autopilot's work: named on the board, nobody mentioned", (st3["waits_on"]["who"], said3), (AUTOPILOT, None))
    st4, said4 = step({**incomplete, "state": "CLOSED"}, st, "boss")
    check("#564 C3 a closed item waits on nobody, and its mentions stay", ("waits_on" in st4, st4.get("mentioned"), said4), (False, ["ana|Complete the PRD of"], None))
    check("#564 C3 the row on the board", rc.waits_line(st), f"| Waits on | @ana: Complete the PRD of {incomplete['url']} {rc.WAITS} |")
    # update(), end to end on fixtures: the board's comment written, the mention posted once.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        env = {"STATE_FIXTURE": os.path.join(d, "c.json"), "ITEM_FIXTURE": os.path.join(d, "item.json"), "MENTION_LOG": os.path.join(d, "m.log")}
        json.dump(incomplete, open(env["ITEM_FIXTURE"], "w", encoding="utf-8"))
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                update("o/r", 7, "boss", "")
                update("o/r", 7, "boss", "")
            said = open(env["MENTION_LOG"], encoding="utf-8").read()
            check("#564 C3 update twice: one mention, signed", (said.count("@ana: Complete the PRD of"), SIGN in said), (1, True))
            check("#564 C3 update writes the board's Waits on row", rc.read_state("o/r", 7).get("waits_on", {}).get("who"), "ana")
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    hand = {"comments": {"nodes": [{"author": {"__typename": "Bot", "login": rc.bot_app()},
                                    "body": rc.with_state(rc.BOARD, {"waiting": False}).replace('"waiting":false', '"waiting":true')}]}}
    check("#564 a board's state edited by hand counts as the autopilot's question", issue_state(hand).get("tampered"), True)
    forged = {"comments": {"nodes": [{"author": {"__typename": "User", "login": "mallory"}, "body": rc.with_state(rc.BOARD, {"waiting": True})}]}}
    check("#564 a person's comment that copies the board is not read", issue_state(forged), {})
    check("#564 no label carries the question", "autopilot:" + "waiting" in open(__file__, encoding="utf-8").read(), False)
    check("C7 nothing waiting says so", "Nothing waits on anyone." in render([], now), True)
    print("all tests passed" if not fails else f"{len(fails)} failed")
    return 1 if fails else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    maintainer = os.environ.get("MAINTAINER", "")
    if len(argv) == 2 and argv[0] == "render":
        with open(argv[1], encoding="utf-8") as fh:
            sys.stdout.write(render(json.load(fh), now_(), maintainer))
        return 0
    if argv == ["update"]:
        return update(os.environ["GITHUB_REPOSITORY"], int(os.environ["NUMBER"]), maintainer, os.environ.get("SENDER", ""))
    if not argv:
        sys.stdout.write(render(fetch(os.environ.get("OWNER", "DiluxOne")), now_(), maintainer))
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
