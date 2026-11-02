#!/usr/bin/env python3
"""What waits on whom (#479, #564): every open issue and pull request of the
organisation that waits on someone, with the action and its full URL,
grouped by person, in one issue the maintainer reads (pinned in
DiluxOne/.github, its body rewritten), kept up to date on every event of
an issue or a pull request (waiting-update.yml, from issues.yml and the
pull request pipelines) and swept once a day (waiting-digest.yml).

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

And an issue (#564), the first that applies:

  needs-human          a person has it                         the maintainer
  its question         the autopilot asked (`autopilot:waiting`) the maintainer
  the claimed work     a person claimed it (`claimed`)         the claimant
  completing it        `incomplete`: the G1 comment says what  its author
  the answer           `needs-info`: the triage asked          its author
  an acceptance        complete, not `accepted` yet            the maintainer
  the autopilot's work accepted, nobody holds it               the autopilot

"The maintainer" is org.yml's maintainers; an outside contributor is only
ever waited on for their own step, and a maintainer never for theirs (rule
7). The item's board (scripts/receipts.py waits) names whom it waits on and
mentions that person once per waiting step: the step is the action and when
it began (the label that started it, or the head commit of a pull request).

The issue is public: a private repository's items are counted under what
blocks them, never named.

  waiting.py              the view's body, from the organisation's open
                          issues and pull requests (GH_TOKEN, OWNER)
  waiting.py render FILE  the body from FILE, a JSON list of items as the
                          search below returns them (NOW, an ISO time,
                          defaults to now)
  waiting.py update       one item (GITHUB_REPOSITORY, NUMBER): whom it
                          waits on now, on its board, with one mention
  waiting.py publish      the view rewritten in the pinned issue of
                          VIEW_REPO (org.yml's central repository), created
                          and pinned when there is none
  waiting.py --test       self-test, from fixtures/waiting.json
"""
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import org  # noqa: E402  the organisation's App, from org.yml (#568)
MARKER = "<!-- dx-waiting -->"
BOT_LOGINS = (org.APP, org.BOT, f"app/{org.APP}")
MAINTAINER, AUTHOR, AUTOPILOT, CHECKS, CLAIMANT = "the maintainer", "its author", "the autopilot", "the checks", "the claimant"
LABEL = "run:waiting"

FIELDS = """__typename
      ... on Issue {
        number title url createdAt
        author { login }
        repository { name nameWithOwner isPrivate }
        labels(first: 30) { nodes { name } }
        assignees(first: 5) { nodes { login } }
        timelineItems(itemTypes: [LABELED_EVENT], last: 30) { nodes { ... on LabeledEvent { createdAt label { name } } } }
      }
      ... on PullRequest {
        number title url createdAt isDraft
        author { login }
        repository { name nameWithOwner isPrivate }
        labels(first: 30) { nodes { name } }
        reviewThreads(first: 100) { nodes { isResolved } }
        commits(last: 1) { nodes { commit { oid statusCheckRollup { state } } } }
        closingIssuesReferences(first: 10) { nodes { number labels(first: 30) { nodes { name } } } }
      }"""
QUERY = """query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 50, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { %s }
  }
}""" % FIELDS
ONE = """query($o: String!, $n: String!, $i: Int!) {
  repository(owner: $o, name: $n) { issueOrPullRequest(number: $i) { %s ... on Issue { state body } ... on PullRequest { state body } } }
}""" % FIELDS


def names(conn):
    return [n.get("name") for n in ((conn or {}).get("nodes") or []) if n]


def is_pr(item):
    return item.get("__typename") == "PullRequest" or "isDraft" in item


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


def issue_blocker(issue):
    """(what blocks it, on whom it waits) for one issue, or None when
    nothing waits on anyone (the triage has not answered yet, or it is one
    of the bot's own run: issues). Pure."""
    labels = names(issue.get("labels"))
    if any(l.startswith("run:") for l in labels):
        return None
    if "needs-human" in labels:
        return "needs-human", MAINTAINER
    if "autopilot:waiting" in labels:
        return "its question", MAINTAINER
    if "claimed" in labels:
        return "the claimed work", CLAIMANT
    if "incomplete" in labels:
        return "completing it", AUTHOR
    if "needs-info" in labels:
        return "the answer", AUTHOR
    if "accepted" not in labels and "awaiting-acceptance" in labels:
        return "an acceptance", MAINTAINER
    if "accepted" in labels:
        return "the autopilot's work", AUTOPILOT
    return None


# What the person does, said on the board and in the mention.
ACTIONS = {
    "needs-human": "a person takes it from here (`needs-human`): read why and decide",
    "its question": "answer the autopilot's question",
    "an acceptance": "accept it (the `accepted` label) or say why not",
    "a failed check": "fix the failed check",
    "a draft": "finish the draft and mark it ready",
    "a person's merge": "review it and merge it",
    "the claimed work": "open the pull request for the claimed issue",
    "completing it": "complete the issue: the G1 comment says what is missing",
    "the answer": "answer what the triage asked",
}


def action(what):
    if what.endswith("unresolved thread") or what.endswith("unresolved threads"):
        return f"resolve the review's open conversations ({what})"
    return ACTIONS.get(what, what)


def item_blocker(item):
    return blocker(item) if is_pr(item) else issue_blocker(item)


def people(item, who, maintainers):
    """The logins it waits on: org.yml's maintainers, its author, or its
    claimant (an assignee, else its author); none for a role or a bot."""
    author = (item.get("author") or {}).get("login") or ""
    if who == MAINTAINER:
        found = list(maintainers)
    elif who == AUTHOR:
        found = [author]
    elif who == CLAIMANT:
        found = [a.get("login") for a in ((item.get("assignees") or {}).get("nodes") or []) if a] or [author]
    else:
        found = []
    return [p for p in found if p and p not in BOT_LOGINS and not p.endswith("[bot]")]


def step_of(item, what):
    """When the waiting step began: the last time the label behind it was
    added, or a pull request's head commit; a new one is a new step."""
    if is_pr(item):
        commits = (item.get("commits") or {}).get("nodes") or []
        return f"{what}@{((commits[-1] if commits else {}).get('commit') or {}).get('oid') or ''}"
    label = {"needs-human": "needs-human", "its question": "autopilot:waiting", "the claimed work": "claimed", "completing it": "incomplete",
             "the answer": "needs-info", "an acceptance": "awaiting-acceptance", "the autopilot's work": "accepted"}.get(what, "")
    times = [e.get("createdAt") for e in ((item.get("timelineItems") or {}).get("nodes") or []) if (e.get("label") or {}).get("name") == label]
    return f"{what}@{times[-1] if times else ''}"


def waits_of(item, maintainers):
    """What the item's board says it waits on (scripts/receipts.py waits),
    or None. Pure."""
    found = item_blocker(item)
    if not found:
        return None
    what, who = found
    logins = people(item, who, maintainers)
    role = who if who != AUTHOR else "its author"
    out = {"role": role, "what": action(what), "url": item.get("url") or "", "step": step_of(item, what)}
    if logins:
        out["who"] = logins
    return out


def heading(who, item, maintainers):
    """The group an item is listed under: the person by name, or the role."""
    logins = people(item, who, maintainers)
    if logins:
        return ", ".join(f"`{l}`" for l in logins)
    return who


def render(items, now, maintainers=()):
    """The view's body: every item that waits on someone, by whom, one line
    per action with its full URL, oldest first; private ones counted. Pure."""
    groups, hidden = {}, {}
    order = []
    for it in sorted(items, key=lambda i: i.get("createdAt") or ""):
        found = item_blocker(it)
        if not found:
            continue
        what, who = found
        group = heading(who, it, maintainers)
        if group not in groups:
            groups[group] = []
            order.append(group)
        if (it.get("repository") or {}).get("isPrivate"):
            hidden[(group, what)] = hidden.get((group, what), 0) + 1
            continue
        title = re.sub(r"[\[\]]", lambda m: "(" if m.group(0) == "[" else ")", it.get("title") or "")
        kind = "pull request" if is_pr(it) else "issue"
        groups[group].append(f"- **{action(what)}**: {it['url']} ({kind} {it['repository']['name']}#{it['number']}, {title})")
    # The maintainer first, then the people, then the autopilot and the checks.
    rank = lambda g: (0 if g == heading(MAINTAINER, {}, maintainers) else 2 if g in (AUTOPILOT, CHECKS) else 1, g)
    lines = [MARKER, f"# What waits ({now.strftime('%Y-%m-%d %H:%M')} UTC)", "",
             "Every open issue and pull request of the organisation that waits on someone, what to do and its link, by whom it waits on "
             "(#479, #564, `scripts/waiting.py`). This body is rewritten on every event of an issue or a pull request, and once a day.", ""]
    if not order:
        lines += ["Nothing waits on anyone."]
    for g in sorted(order, key=rank):
        lines += [f"## Waits on {g}", ""] + groups[g]
        lines += [f"- {n} in private repositories: **{action(what)}**" for (w, what), n in sorted(hidden.items()) if w == g]
        lines += [""]
    return "\n".join(lines).rstrip() + "\n"


def gh(*args):
    res = subprocess.run(["gh"] + list(args), capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip()[:300])
    return res.stdout


def fetch(owner):
    """The organisation's open issues and pull requests."""
    q, after, out = f"org:{owner} is:open", None, []
    while True:
        args = ["api", "graphql", "-f", f"query={QUERY}", "-f", f"q={q}"] + (["-f", f"after={after}"] if after else [])
        page = json.loads(gh(*args))["data"]["search"]
        out += [n for n in page["nodes"] if n]
        if not page["pageInfo"]["hasNextPage"]:
            return out
        after = page["pageInfo"]["endCursor"]


def update(repo, number, maintainers, read=None, put=None):
    """One item: whom it waits on now, handed to receipts.py waits (its
    board and one mention). A closed one waits on nobody. read and put are
    for the self-test. Returns the waits."""
    if read is None:
        owner, name = repo.split("/", 1)
        read = lambda: json.loads(gh("api", "graphql", "-f", f"query={ONE}", "-F", f"o={owner}", "-F", f"n={name}", "-F", f"i={number}"))["data"]["repository"]["issueOrPullRequest"]
    item = read()
    waits = waits_of(item, maintainers) if item and item.get("state") == "OPEN" else None
    (put or receipts_waits)(repo, number, item or {}, waits)
    return waits


def receipts_waits(repo, number, item, waits):
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(item.get("body") or "")
    env = dict(os.environ, GITHUB_REPOSITORY=repo, NUMBER=str(number), BODY=fh.name, WAITS_JSON=json.dumps(waits),
               ITEM="pr" if is_pr(item) else "issue")
    res = subprocess.run([sys.executable, os.path.join(HERE, "receipts.py"), "waits"], env=env, capture_output=True, text=True)
    os.unlink(fh.name)
    print(res.stdout.strip() or res.stderr.strip())
    if res.returncode not in (0, 3):
        raise RuntimeError(f"the board could not be written: {res.stderr.strip()[:300]}")


def publish(text, view_repo):
    """The view, in the open `run:waiting` issue of VIEW_REPO: its body
    rewritten, or the issue created and pinned."""
    gh("label", "create", LABEL, "--repo", view_repo, "--color", "C5DEF5", "--force",
       "--description", "What waits on whom (waiting.py): one pinned issue, its body rewritten on every event")
    number = gh("issue", "list", "--repo", view_repo, "--state", "open", "--label", LABEL, "--limit", "1", "--json", "number", "--jq", ".[0].number // empty").strip()
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(text)
    try:
        if number:
            gh("issue", "edit", number, "--repo", view_repo, "--body-file", fh.name)
        else:
            number = gh("issue", "create", "--repo", view_repo, "--title", "What waits", "--label", LABEL, "--body-file", fh.name).strip().rsplit("/", 1)[-1]
            try:
                gh("issue", "pin", number, "--repo", view_repo)
            except RuntimeError:
                print(f"::warning::#{number} could not be pinned; pin it by hand.")
    finally:
        os.unlink(fh.name)
    print(f"What waits: https://github.com/{view_repo}/issues/{number}")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(text)


def parse(ts):
    return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


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
    boss = ["boss"]
    items = fx["prs"] + fx["issues"]
    for p in fx["prs"]:
        check(f"C7 {p['title']}: {p['want'][0]}, waits on {p['want'][1]}", blocker(p), tuple(p["want"]))
    for i in fx["issues"]:
        check(f"C3 issue {i['title']}: {i['want']}", list(issue_blocker(i) or []) or None, i["want"])
    body = render(items, now, boss)
    check("C3 the body starts with its marker", body.startswith(MARKER), True)
    public = [i for i in items if not i["repository"]["isPrivate"] and item_blocker(i)]
    check("C3 issues and pull requests alike: each that waits is listed, its action with its full URL",
          [i["url"] for i in public if f"**{action(item_blocker(i)[0])}**: {i['url']} (" not in body], [])
    check("C3 issues are listed", "(issue diluxone-users-wordpress#" in body, True)
    check("C3 one line per action", len([l for l in body.splitlines() if l.startswith("- **")]), len(public))
    check("C3 grouped by person: the maintainer by name first, then the author by name, then the autopilot",
          body.index("## Waits on `boss`") < body.index("## Waits on `someone`") < body.index("## Waits on the autopilot"), True)
    check("C3 a private one is counted, never named", ("secret-repo" in body, "- 1 in private repositories: **fix the failed check**" in body), (False, True))
    check("C3 a pull request of today is listed too", "opened today" in body, True)
    check("C3 a title cannot break the link", "[x] link" in body, False)
    check("C3 nothing waiting says so", "Nothing waits on anyone." in render([], now, boss), True)
    check("C3 the bot's own run: issues wait on nobody", issue_blocker({"labels": {"nodes": [{"name": "run:waiting"}, {"name": "needs-human"}]}}), None)
    # The board and the one mention (rule 7: each waits on its own people).
    acc = next(i for i in fx["issues"] if i["title"] == "complete, not accepted")
    w = waits_of(acc, boss)
    check("C3 an acceptance waits on the maintainer, named, with the action and its URL",
          (w["who"], w["what"], w["url"]), (["boss"], "accept it (the `accepted` label) or say why not", acc["url"]))
    inc = next(i for i in fx["issues"] if i["title"] == "incomplete, an outside contributor's")
    wi = waits_of(inc, boss)
    check("C3 an outside contributor's incomplete issue waits on them, never on the maintainer", wi["who"], ["outsider"])
    check("C3 the step is when it began: the label's last time", wi["step"], "completing it@2026-10-29T10:00:00Z")
    pr_ready = next(p for p in fx["prs"] if p["want"] == ["a person's merge", "the maintainer"])
    check("C3 a pull request's step is its head commit", waits_of(pr_ready, boss)["step"].startswith("a person's merge@"), True)
    check("C3 the autopilot's work names nobody", "who" in waits_of(next(i for i in fx["issues"] if i["title"] == "accepted"), boss), False)
    rc = _receipts()
    st, said = {}, []
    for _ in range(3):
        text, st = rc.mention(st, w)
        said += [text] if text else []
    check("C3 the person is mentioned once per waiting step, never again", (len(said), said[0].startswith("@boss: accept it")), (1, True))
    later = dict(w, step="an acceptance@2026-11-01T00:00:00Z")
    check("C3 a new waiting step mentions them again, once", [bool(rc.mention(st, later)[0]), bool(rc.mention(rc.mention(st, later)[1], later)[0])], [True, False])
    puts = []
    got = update("o/r", 5, boss, read=lambda: dict(acc, state="OPEN"), put=lambda *a: puts.append(a))
    check("C3 update hands the item's waits to its board", (got, puts[0][3]), (w, w))
    puts.clear()
    update("o/r", 5, boss, read=lambda: dict(acc, state="CLOSED"), put=lambda *a: puts.append(a))
    check("C3 a closed item waits on nobody", puts[0][3], None)
    print("all tests passed" if not fails else f"{len(fails)} failed")
    return 1 if fails else 0


def _receipts():
    import importlib.util
    spec = importlib.util.spec_from_file_location("receipts", os.path.join(HERE, "receipts.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv):
    if argv == ["--test"]:
        return self_test()
    maintainers = org.MAINTAINERS
    if len(argv) == 2 and argv[0] == "render":
        with open(argv[1], encoding="utf-8") as fh:
            sys.stdout.write(render(json.load(fh), now_(), maintainers))
        return 0
    if argv == ["update"]:
        update(os.environ["GITHUB_REPOSITORY"], int(os.environ["NUMBER"]), maintainers)
        return 0
    if argv == ["publish"]:
        publish(render(fetch(os.environ.get("OWNER", "DiluxOne")), now_(), maintainers), os.environ.get("VIEW_REPO") or org.CENTRAL)
        return 0
    if not argv:
        sys.stdout.write(render(fetch(os.environ.get("OWNER", "DiluxOne")), now_(), maintainers))
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
