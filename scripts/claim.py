#!/usr/bin/env python3
"""A person claims an issue (#488): the autopilot steps aside, and no issue
is ever held by nobody.

A claim is held on GitHub itself, never in a store of ours: the `claimed`
label, the claimant as assignee, and one comment by dilux-bot carrying a
hidden `dx-claim` marker (the login, when it was claimed, its clock, whether
it was extended and when it was last reminded) that the bot edits as the
claim moves. Only a marker in a comment dilux-bot wrote is read. Every
decision is a pure function here; the CLI reads GitHub, asks them, and
applies the plan they return (.github/workflows/issue-claim.yml runs it with
dilux-bot's key and none of the repository's code).

  claim.py event     one event (GITHUB_EVENT_NAME, GITHUB_EVENT_PATH): a
                     command in a comment (`/claim`, `/unclaim [@login]`,
                     `/yield @login`, `/adopt` on a pull request, the
                     claimant's "still on it"), an issue opened, edited or
                     labelled (the form's checkbox, the clock that starts at
                     `accepted`), a person's pull request (it stops the
                     claim's clock, its pushes reset it; a third open one by
                     a person without write access is closed)
  claim.py daily     the daily run: reminders, releases, stalled pull
                     requests closed with thanks, and the daily list (one
                     comment per repository on the open `run:claims` issue in
                     the organisation's .github)
  claim.py repro     a claimed bug the reproduction confirmed: its failing
                     test sealed on the issue (TEST, SHA256, BRANCH and the
                     lane's facts), the claim's clock started, the person
                     told the branch; no lane issue until it is released
  claim.py --test    self-test

Both event and daily write `start=<JSON list of issues>` to GITHUB_OUTPUT:
the issues the workflow starts the autopilot on (a released claim, a stalled
pull request closed, an adopted one, the lane's issue of a claimed bug
released), so no release leaves an issue held by nobody.

The limits (days, claims per person, open pull requests) are data in
policy/autonomy.yml `claims:`, which a repository's .github/autonomy.yml
only tightens (scripts/autonomy.py).

Environment: GITHUB_REPOSITORY, GH_TOKEN; ORG_AUTONOMY / REPO_AUTONOMY as
autonomy.py reads them; NOW (an ISO time, for the self-test).
"""
import datetime
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import org  # noqa: E402  the organisation, from org.yml (#191)


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CLAIMED, LONG, FIRST, LIST = "claimed", "claim:long", "good first issue", "run:claims"
MARK = "dx-claim"
TEST_MARK = "dx-claim-test"
ADOPT_MARK = "dx-adopt"
LINK_MARK = "dx-claim-link"
PR_REMIND_MARK = "dx-claim-pr-reminder"
CHECKBOX = "I want to work on this myself"
SIGN = "<sub>🤖 dilux-bot · claims (DiluxOne/.github, scripts/claim.py)</sub>"
BOTS = (org.APP, org.BOT, f"app/{org.APP}")
DEFAULTS = {"remind-days": 7, "release-days": 10, "cap-days": 30, "pr-remind-days": 7, "pr-close-days": 14,
            "newcomer-claims": 1, "contributor-claims": 3, "open-prs": 2}
WRITERS = ("admin", "maintain", "write")


# --- time ------------------------------------------------------------------

def ts(text):
    """An ISO time as an aware datetime, or None."""
    if not text:
        return None
    try:
        return datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def iso(when):
    return when.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day(when):
    return when.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d")


def days(n):
    return datetime.timedelta(days=n)


def now():
    return ts(os.environ.get("NOW")) or datetime.datetime.now(datetime.timezone.utc)


def config(policy):
    """The claims' limits: the policy's `claims:`, the defaults for a key it
    leaves out."""
    got = dict(DEFAULTS)
    got.update({k: v for k, v in ((policy or {}).get("claims") or {}).items() if k in DEFAULTS})
    return got


# --- what was said ----------------------------------------------------------

def is_bot(login):
    return bool(login) and (login in BOTS or login.endswith("[bot]"))


def parse(body):
    """The command in a comment: (name, login) or None. A command is its
    comment's first line (`/claim`, `/unclaim`, `/unclaim @x`, `/yield @x`,
    `/adopt`, `/adopt <sha>`: the head the maintainer read); "still on it"
    anywhere in it asks for the one extension."""
    text = (body or "").strip()
    first = text.splitlines()[0].strip() if text else ""
    m = re.fullmatch(r"/(claim|unclaim|yield|adopt)(?:\s+@?([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))?)?\s*", first)
    if m:
        name, who = m.group(1), m.group(2) or ""
        if name == "claim" and who or name == "adopt" and who and not re.fullmatch(r"[0-9a-f]{7,40}", who):
            return None
        if name == "yield" and not who:
            return None
        return name, who
    if re.search(r"\bstill on it\b", text, re.I):
        return "extend", ""
    return None


def form_claim(body):
    """Whether the issue form's checkbox is ticked in the body."""
    return bool(re.search(r"^\s*[-*]\s*\[[xX]\]\s*" + re.escape(CHECKBOX), body or "", re.M))


def form_ticked(action, author, sender, body, before=None):
    """Whether this event is the issue's author claiming it in its form: on
    opening, the box ticked; on an edit, ticked by the author in that very
    edit. An edit by anyone else (the autopilot appending its Spec to a
    body whose box was ticked long ago) claims nothing, so a released claim
    never comes back by itself."""
    if not form_claim(body):
        return False
    if action == "opened":
        return True
    return action == "edited" and sender == author and before is not None and not form_claim(before)


def marker(name, obj):
    return f"<!-- {name} {json.dumps(obj, sort_keys=True)} -->"


def read_marker(comments, name):
    """(comment id, the JSON) of the last comment by dilux-bot carrying the
    marker `name`; (None, None) when there is none. A marker in anyone
    else's comment is never read."""
    found = (None, None)
    pat = re.compile(r"<!-- " + re.escape(name) + r" (\{.*?\}) -->")
    for c in comments or []:
        if not is_bot(((c.get("user") or c.get("author") or {}).get("login")) or ""):
            continue
        m = pat.search(c.get("body") or "")
        if m:
            try:
                found = (c.get("id"), json.loads(m.group(1)))
            except ValueError:
                continue
    return found


# --- who may claim ------------------------------------------------------------

def may_act(name, login, perm, target=""):
    """(ok, why) for a command only some may give: `/yield` and `/adopt` a
    maintainer (write access or more, read from GitHub: `perm`), `/unclaim
    @x` the claimant themselves or a maintainer."""
    if name in ("yield", "adopt") and perm not in WRITERS:
        return False, f"@{login}, only a maintainer (write access, read from GitHub) gives `/{name}`"
    if name == "unclaim" and target and target != login and perm not in WRITERS:
        return False, f"@{login}, only @{target} or a maintainer releases this claim"
    return True, ""


def claim_limit(merged, cfg):
    """How many open claims a person may hold: one with no merged pull
    request in the organisation, three with one."""
    return cfg["contributor-claims"] if merged else cfg["newcomer-claims"]


def autopilot_started(prs, runs):
    """Why the autopilot holds the issue, or "": an open `autopilot` pull
    request that closes it, or a run of it in progress (a URL)."""
    for p in prs or []:
        if p.get("state") == "OPEN" and "autopilot" in (p.get("labels") or []) and is_bot(p.get("author") or ""):
            return f"the autopilot is already on it in #{p['number']}"
    for r in runs or []:
        return f"the autopilot is already on it ({r})"
    return ""


def may_claim(login, issue, held, merged, started, cfg):
    """(ok, why) for a person's claim. `issue`: state, labels, the current
    claim (or None); `held`: the person's open claims in the organisation
    (this one not counted); `merged`: whether they have a merged pull
    request in it; `started`: autopilot_started's answer."""
    if issue.get("state", "OPEN") != "OPEN":
        return False, "the issue is closed"
    current = issue.get("claim")
    if current and current.get("login") == login:
        return False, f"@{login} already holds it"
    if current or CLAIMED in (issue.get("labels") or []):
        return False, f"@{(current or {}).get('login') or 'someone'} holds it already; it is released if they stop working on it"
    if started:
        return False, (f"{started}. The first one wins, so the autopilot keeps it; a maintainer can hand it to you with "
                       f"`/yield @{login}`, or open your pull request anyway and the maintainer picks at review")
    most = claim_limit(merged, cfg)
    if held >= most:
        who = "a person with a merged pull request in the organisation" if merged else "a person whose first pull request is not merged yet"
        return False, f"@{login} holds {held} open claim{'s' if held != 1 else ''}, and {who} holds at most {most} at a time; finish or `/unclaim` one first"
    return True, "claimed"


# --- the claim's clock --------------------------------------------------------

def new_claim(login, when, clock=None):
    """A claim's state. `clock` is when its clock started (acceptance, the
    reproduction of a bug, or the claim itself on an accepted issue), None
    while it waits for them."""
    return {"login": login, "since": iso(when), "clock": iso(clock) if clock else None, "start": iso(clock) if clock else None,
            "extended": False, "reminded": None}


def start_clock(state, when, reset=False):
    """The clock starts (at acceptance) or, `reset`, starts again (the
    reproduction of a claimed bug); the 30 days run from its first start."""
    out = dict(state)
    if out.get("clock") and not reset:
        return out
    out["clock"] = iso(when)
    out["start"] = out.get("start") or iso(when)
    out["reminded"] = None
    return out


def pushed(state, when):
    """A push to a linked branch resets the clock (never the 30 days)."""
    if not state.get("clock") or ts(when) <= ts(state["clock"]):
        return dict(state)
    return {**state, "clock": iso(ts(when)), "reminded": None}


def deadlines(state, cfg):
    """(remind, release) as datetimes, or (None, None) while the clock waits.
    The release is the earlier of ten days from the clock and thirty from
    its first start."""
    clock = ts(state.get("clock"))
    if not clock:
        return None, None
    release = min(clock + days(cfg["release-days"]), ts(state.get("start")) + days(cfg["cap-days"]))
    return clock + days(cfg["remind-days"]), release


def extend(state, when, cfg):
    """(new state, ok, why): the claimant's "still on it" restarts the clock
    once; a second is refused and the claim keeps the deadline the first set
    (choice 4a); never past thirty days from the clock's first start."""
    if not state.get("clock"):
        return dict(state), False, "its clock has not started yet (it starts when the issue is accepted)"
    if state.get("extended"):
        _, release = deadlines(state, cfg)
        return dict(state), False, f"it was extended once already; it is released on {day(release)} unless a pull request comes first"
    out = {**state, "clock": iso(when), "extended": True, "reminded": None}
    _, release = deadlines(out, cfg)
    return out, True, f"extended once: it is released on {day(release)} unless a pull request comes first"


def daily_claim(state, when, labels, has_pr, last_push, cfg):
    """What the daily run does to a claim: none, remind, release, or pending
    (its clock waits) or waiting (a pull request stopped it)."""
    if not state.get("clock"):
        return "pending"
    if LONG in labels:
        return "none"
    if has_pr:
        return "waiting"
    state = pushed(state, last_push) if last_push else state
    remind, release = deadlines(state, cfg)
    if when >= release:
        return "release"
    if when >= remind and state.get("reminded") != state.get("clock"):
        return "remind"
    return "none"


def daily_pr(pr, when, reminded, cfg):
    """A person's open pull request that closes an issue: none, remind,
    close, or waiting (it waits on a maintainer's review: its author's clock
    does not run). Changes requested or failing checks, and no push by its
    author since: a reminder at seven days, closed with thanks at fourteen."""
    stalled = pr.get("review") == "CHANGES_REQUESTED" or pr.get("checks") in ("FAILURE", "ERROR")
    if not stalled:
        return "waiting"
    since = max(t for t in (ts(pr.get("pushed")), ts(pr.get("reviewed")), ts(pr.get("created"))) if t)
    if when >= since + days(cfg["pr-close-days"]):
        return "close"
    if when >= since + days(cfg["pr-remind-days"]) and not reminded:
        return "remind"
    return "none"


# --- the plans ------------------------------------------------------------------

def state_text(state, cfg):
    """The claim's comment: who, since when, and the dates, with its marker."""
    remind, release = deadlines(state, cfg)
    if not remind:
        dates = f"Its clock starts when the issue is accepted (or, for a bug, reproduced): a reminder at {cfg['remind-days']} days without a pull request or a push, released at {cfg['release-days']}."
    else:
        dates = (f"Reminder on {day(remind)} and released on {day(release)} without a pull request or a push to a linked branch. "
                 "A push resets the clock; one comment saying \"still on it\" extends it once; never more than "
                 f"{cfg['cap-days']} days from its start without a pull request. A pull request stops the clock while it waits on a maintainer's review.")
    return (f"**Claimed by @{state['login']}** on {state['since'][:10]}. The autopilot does not start on this issue while it is claimed.\n\n"
            f"{dates}\n\n`/unclaim` releases it at once.\n\n{marker(MARK, state)}\n\n{SIGN}")


def plan_claim(login, by, when, issue, cfg):
    """The actions of a claim: the label, the person assigned, the state
    comment with the dates (C1). `issue["accepted"]`: whether it is accepted
    (or, for a bug, reproduced) now, which starts the clock; else it starts
    then (C2)."""
    state = new_claim(login, when, when if issue.get("accepted") else None)
    note = f"@{login} claimed this issue" + (f" (handed over by @{by})" if by and by != login else "") + f" on {iso(when)}."
    return [("label", CLAIMED), ("assign", login), ("state", state_text(state, cfg)), ("comment", f"{note}\n\n{SIGN}")], state


def plan_release(state, why, issue_number, start=True):
    """A claim released: the label off, the person unassigned, a comment
    saying why; the autopilot starts on it, so it is never held by nobody."""
    acts = [("unlabel", CLAIMED), ("unassign", state["login"]), ("state", None),
            ("comment", f"The claim of @{state['login']} is released: {why}. "
                        + ("The autopilot starts on it now; anyone may still open a pull request." if start else "") + f"\n\n{SIGN}")]
    if start:
        acts.append(("start", issue_number))
    return acts


def plan_end(issue, why, start=True, lane=True):
    """Every way a claim ends (`/unclaim`, the daily release, a stalled pull
    request closed; `/adopt` in plan_adopt_issue, which takes the lane's
    issue for the adoption) goes through here, so none forgets a claimed
    bug: one the reproduction confirmed goes to the `bugfix-reproduced` lane
    with the same test, and its test's marker is struck out so the gate no
    longer reads it (the lane opened by the caller when not `lane`);
    anything else is released, the autopilot started on it when `start`."""
    state, n = issue["claim"], issue["number"]
    if not issue.get("test"):
        return plan_release(state, why, n, start)
    return plan_release(state, why, n, start=False) + ([("lane", issue["test"])] if lane else []) + [("retire-test", issue.get("test_id"))]


def plan_yield(login, maintainer, prs, runs, when, issue, cfg):
    """A maintainer's `/yield @login` (C5): the autopilot's run cancelled,
    its draft closed with a comment, the issue claimed for the person."""
    acts = [("cancel", r) for r in runs]
    acts += [("close-pr", p["number"], f"Closed: @{maintainer} handed #{issue['number']} to @{login} with `/yield`. Thanks, autopilot.\n\n{SIGN}")
             for p in prs if p.get("state") == "OPEN" and "autopilot" in (p.get("labels") or []) and is_bot(p.get("author") or "")]
    claim_acts, state = plan_claim(login, maintainer, when, {**issue, "accepted": True}, cfg)
    return acts + claim_acts, state


def plan_pr_close(pr, issues, close_days=DEFAULTS["pr-close-days"]):
    """A stalled person's pull request closed with thanks, and the autopilot
    started on what it closed (C7): [(issue number, its actions)]. An issue
    its author claimed ends its claim through plan_end (a claimed bug to its
    lane)."""
    text = (f"Thank you, @{pr['author']}. This pull request has waited on its author for {close_days} days, so it is closed for now: "
            "reopen it when you come back, or ask a maintainer to `/adopt` it. The autopilot starts on the issue so it is not left waiting.\n\n" + SIGN)
    out = [(issues[0]["number"], [("close-pr", pr["number"], text)])]
    for i in issues:
        if (i.get("claim") or {}).get("login") == pr["author"]:
            out.append((i["number"], plan_end(i, f"its pull request #{pr['number']} was closed after {close_days} days without a push")))
        else:
            out.append((i["number"], [("start", i["number"])]))
    return out


def adopt_branch(issue, pr):
    return f"feat/{issue}-adopted-{pr}"


def plan_adopt(pr, maintainer, issue_number, when):
    """`/adopt` (C10): the head the maintainer read, pinned now, copied to a
    branch of the repository (never a later commit), the person's pull
    request closed with thanks, the adoption recorded on the issue (the
    autopilot's push reads it for the Co-authored-by trailer), and the
    autopilot started from that branch."""
    rec = {"pr": pr["number"], "author": pr["author"], "author_id": pr.get("author_id"), "sha": pr["head"],
           "branch": adopt_branch(issue_number, pr["number"]), "by": maintainer, "at": iso(when)}
    note = (f"@{maintainer} adopted #{pr['number']} by @{pr['author']} at {pr['head'][:12]}, the commit they read: the autopilot continues from it on "
            f"`{rec['branch']}`, and every commit it pushes there carries `Co-authored-by` for @{pr['author']}.\n\n{marker(ADOPT_MARK, rec)}\n\n{SIGN}")
    return [("branch", rec["branch"], rec["sha"]), ("comment", note),
            ("close-pr", pr["number"], f"Adopted by @{maintainer}: the autopilot continues it from {pr['head'][:12]} in #{issue_number}'s pull request, with you as co-author. Thank you, @{pr['author']}.\n\n{SIGN}"),
            ("start", issue_number)], rec


def plan_adopt_issue(pr, maintainer, issue, when):
    """`/adopt` on the issue as it stands: its claim, if any, ends first
    (without a start of its own), then the adoption. A claimed bug the
    reproduction confirmed has no PRD sealed by a person, so the autopilot
    cannot start on the report: its claim and its test's marker end, and the
    adoption goes to the `bugfix-reproduced` lane's issue, opened with the
    same test (`lane-adopt`), which is the one issue started, from the
    adopted branch. Returns (actions, the adoption record, or None when it
    is made on the lane's issue once it exists)."""
    why = f"@{maintainer} adopted #{pr['number']}"
    if not issue.get("claim"):
        return plan_adopt(pr, maintainer, issue["number"], when)
    ended = plan_end(issue, why, start=False, lane=False)
    if issue.get("test"):
        return ended + [("lane-adopt", issue["test"], pr, maintainer)], None
    acts, rec = plan_adopt(pr, maintainer, issue["number"], when)
    return ended + acts, rec


def pr_limit(author, others, cfg):
    """(close, why) for a person without write access opening a pull request
    (choice 3a): beyond the organisation's limit of open ones, it is closed
    at once, linking the others."""
    if len(others) < cfg["open-prs"]:
        return False, ""
    links = ", ".join(others[:cfg["open-prs"]])
    return True, (f"@{author}, a person without write access keeps at most {cfg['open-prs']} pull requests open across the organisation, "
                  f"and you have {len(others)} ({links}). This one is closed for now: reopen it once one of those is merged or closed.")


def daily_list(repo, claims, waiting, given_up):
    """This repository's part of the daily list (the `run:claims` issue)."""
    lines = [f"<!-- {LIST} {repo} -->", f"### {repo}", ""]
    lines += ["**Claims**", ""] + ([f"- #{n}: @{who}, {what}" for n, who, what in claims] or ["- none"]) + [""]
    lines += ["**Waiting on a maintainer's review** (its author's clock does not run)", ""] + ([f"- #{n} by @{who}" for n, who in waiting] or ["- none"]) + [""]
    lines += ["**Anyone may `/claim`** (the autopilot gave up, or kept for a newcomer)", ""] + ([f"- #{n}: {why}" for n, why in given_up] or ["- none"])
    return "\n".join(lines) + f"\n\n{SIGN}"


# --- reading GitHub ----------------------------------------------------------------

def gh(*args, input_text=None, check=True):
    out = subprocess.run(["gh"] + list(args), input=input_text, capture_output=True, text=True)
    if check and out.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {out.stderr.strip()[:300]}")
    return out.stdout


def gh_json(*args):
    text = gh(*args)
    return json.loads(text) if text.strip() else None


ISSUE_QUERY = """query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      number state title body
      issueType { name }
      labels(first: 50) { nodes { name } }
      assignees(first: 20) { nodes { login } }
      linkedBranches(first: 10) { nodes { ref { name target { ... on Commit { committedDate } } } } }
      closedByPullRequestsReferences(first: 20, includeClosedPrs: false) {
        nodes { number state isDraft createdAt headRefName reviewDecision author { __typename login }
                labels(first: 30) { nodes { name } } }
      }
    }
  }
}"""


def issue_comments(repo, number):
    comments = gh_json("api", f"repos/{repo}/issues/{number}/comments", "--paginate", "--slurp") or []
    return [c for page in comments for c in page] if comments and isinstance(comments[0], list) else comments


def read_issue(repo, number):
    owner, name = repo.split("/", 1)
    data = gh_json("api", "graphql", "-f", f"query={ISSUE_QUERY}", "-F", f"owner={owner}", "-F", f"name={name}", "-F", f"number={number}")
    if (data or {}).get("errors"):
        raise RuntimeError(f"the issue could not be read: {json.dumps(data['errors'])[:300]}")
    i = data["data"]["repository"]["issue"]
    comments = issue_comments(repo, number)
    prs = [{"number": p["number"], "state": p["state"], "created": p["createdAt"], "review": p.get("reviewDecision") or "",
            "author": (p.get("author") or {}).get("login") or "", "author_type": (p.get("author") or {}).get("__typename") or "",
            "labels": [l["name"] for l in p["labels"]["nodes"]]} for p in i["closedByPullRequestsReferences"]["nodes"]]
    pushes = [((b.get("ref") or {}).get("target") or {}).get("committedDate") for b in i["linkedBranches"]["nodes"]]
    labels = [l["name"] for l in i["labels"]["nodes"]]
    _, state = read_marker(comments, MARK)
    test_id, test = read_marker(comments, TEST_MARK)
    return {"test": test, "test_id": test_id, "number": i["number"], "state": i["state"], "title": i["title"], "body": i.get("body") or "", "labels": labels,
            "type": (i.get("issueType") or {}).get("name") or "", "assignees": [a["login"] for a in i["assignees"]["nodes"]],
            "prs": prs, "comments": comments, "claim": state if CLAIMED in labels else None, "last_push": max([p for p in pushes if p] or [""]),
            "accepted": "accepted" in labels or "bug:confirmed" in labels}


def permission(repo, login):
    """The person's permission on the repository, read from GitHub, never
    from author_association alone."""
    out = gh("api", f"repos/{repo}/collaborators/{login}/permission", "--jq", ".permission", check=False).strip()
    return out or "none"


def org_of(repo):
    return repo.split("/", 1)[0]


def search_count(*query):
    return int(gh("api", "-X", "GET", "search/issues", "-f", "q=" + " ".join(query), "--jq", ".total_count").strip() or 0)


def autopilot_runs(repo, number):
    """The autopilot's runs in progress for the issue: their prep job is
    named for it (autopilot.yml)."""
    runs = []
    for status in ("in_progress", "queued"):
        for rid in gh("run", "list", "--repo", repo, "--status", status, "--limit", "50", "--json", "databaseId", "--jq", ".[].databaseId", check=False).split():
            jobs = gh("run", "view", rid, "--repo", repo, "--json", "jobs", "--jq", ".jobs[].name", check=False)
            if re.search(r"Autopilot \((start|continue|fix)\) · may it run · #" + str(number) + r"$", jobs, re.M):
                runs.append(rid)
    return runs


def apply_plan(repo, number, actions, state_id=None):
    """Applies a plan; returns the issues to start the autopilot on."""
    start = []
    for act in actions:
        kind = act[0]
        if kind == "label":
            gh("label", "create", act[1], "--repo", repo, "--color", "5319E7", "--description", "A person claimed it: the autopilot steps aside", check=False)
            gh("issue", "edit", str(number), "--repo", repo, "--add-label", act[1])
        elif kind == "unlabel":
            gh("issue", "edit", str(number), "--repo", repo, "--remove-label", act[1], check=False)
        elif kind == "assign":
            # A person outside the repository cannot be assigned: the
            # comment names them.
            gh("issue", "edit", str(number), "--repo", repo, "--add-assignee", act[1], check=False)
        elif kind == "unassign":
            gh("issue", "edit", str(number), "--repo", repo, "--remove-assignee", act[1], check=False)
        elif kind == "state":
            if act[1] is None:
                # Released: the comment stays, as the record, without its
                # marker, so nothing reads the claim again.
                if state_id:
                    gh("api", "-X", "PATCH", f"repos/{repo}/issues/comments/{state_id}", "-f", f"body=~~Claimed~~: released on {iso(now())}.\n\n{SIGN}")
            elif state_id:
                gh("api", "-X", "PATCH", f"repos/{repo}/issues/comments/{state_id}", "-f", f"body={act[1]}")
            else:
                gh("issue", "comment", str(number), "--repo", repo, "--body", act[1])
        elif kind == "comment":
            gh("issue", "comment", str(number), "--repo", repo, "--body", act[1])
        elif kind == "pr-comment":
            gh("pr", "comment", str(act[1]), "--repo", repo, "--body", act[2])
        elif kind == "close-pr":
            gh("pr", "close", str(act[1]), "--repo", repo, "--comment", act[2])
        elif kind == "cancel":
            gh("run", "cancel", str(act[1]), "--repo", repo, check=False)
        elif kind == "branch":
            gh("api", "-X", "POST", f"repos/{repo}/git/refs", "-f", f"ref=refs/heads/{act[1]}", "-f", f"sha={act[2]}")
        elif kind == "start":
            start.append(act[1])
        elif kind == "lane":
            lane = lane_open(repo, number, act[1])
            if lane:
                start.append(lane)
        elif kind == "lane-adopt":
            # A claimed bug adopted: the lane's issue, then the adoption made
            # there, so its start (the only one) is from the adopted branch.
            lane = lane_open(repo, number, act[1])
            if lane:
                start += apply_plan(repo, lane, plan_adopt(act[2], act[3], int(lane), now())[0])
        elif kind == "retire-test":
            # The test's comment stays, without its marker: the gate reads a
            # claimed bug's test only while the claim holds.
            if act[1]:
                body = gh("api", f"repos/{repo}/issues/comments/{act[1]}", "--jq", ".body")
                gh("api", "-X", "PATCH", f"repos/{repo}/issues/comments/{act[1]}", "-f",
                   "body=" + retire_test(body, iso(now())))
    return start


# --- the CLI -------------------------------------------------------------------------

def policy():
    autonomy = _load("autonomy", "autonomy.py")
    return config(autonomy.policy_in_force())


def held_claims(repo, login):
    """The person's open claims in the organisation: as assignee, or named by
    dilux-bot's claim marker where they could not be assigned (someone
    outside the repository). The text search only finds the candidates;
    each is counted from what only dilux-bot writes (claims_of), so nobody's
    comment adds a claim to someone else."""
    where = (f"org:{org_of(repo)}", "is:issue", "is:open", f"label:{CLAIMED}")
    found = {}
    for query in (f"assignee:{login}", f'"Claimed by @{login}" in:comments'):
        out = gh("api", "-X", "GET", "search/issues", "-f", "q=" + " ".join(where + (query,)), "-f", "per_page=100", "--jq",
                 '.items[] | {repo: (.repository_url | sub(".*/repos/"; "")), number, assignees: [.assignees[]?.login]} | tojson')
        for line in out.splitlines():
            item = json.loads(line)
            found[(item["repo"], item["number"])] = item
    issues = []
    for (r, n), item in sorted(found.items()):
        comments = [] if login in item["assignees"] else issue_comments(r, n)
        issues.append({"assignees": item["assignees"], "comments": comments})
    return claims_of(login, issues)


def claims_of(login, issues):
    """How many of the issues `login` holds: assigned to them, or named by
    dilux-bot's claim marker; a person's comment naming them never counts."""
    return sum(1 for i in issues if login in i["assignees"] or (read_marker(i["comments"], MARK)[1] or {}).get("login") == login)


def merged_any(repo, login):
    return search_count(f"org:{org_of(repo)}", "is:pr", "is:merged", f"author:{login}") > 0


def do_claim(repo, issue, login, by, when, cfg):
    """A claim by `login` (from `/claim`, the form's checkbox, or `/yield`):
    checked, then applied; returns (ok, why)."""
    started = autopilot_started(issue["prs"], autopilot_runs(repo, issue["number"]))
    held = held_claims(repo, login) - (1 if issue.get("claim") and issue["claim"].get("login") == login else 0)
    ok, why = may_claim(login, issue, held, merged_any(repo, login), started, cfg)
    if not ok:
        return False, why
    acts, _ = plan_claim(login, by, when, issue, cfg)
    state_id, _ = read_marker(issue["comments"], MARK)
    apply_plan(repo, issue["number"], acts, state_id)
    return True, why


def on_comment(repo, event, cfg, when):
    comment, iss = event["comment"], event["issue"]
    login = (comment.get("user") or {}).get("login") or ""
    if is_bot(login) or (comment.get("user") or {}).get("type") == "Bot":
        return []
    cmd = parse(comment.get("body"))
    if not cmd:
        return []
    name, who = cmd
    number = iss["number"]
    is_pr = bool(iss.get("pull_request"))
    say = lambda text: gh("issue", "comment", str(number), "--repo", repo, "--body", f"{text}\n\n{SIGN}")
    perm = permission(repo, login) if name in ("yield", "adopt", "unclaim") else "none"
    ok, why = may_act(name, login, perm, who)
    if not ok:
        if name != "adopt" or is_pr:
            say(why + ".")
        return []
    if name == "adopt":
        if not is_pr:
            return []
        pr = gh_json("pr", "view", str(number), "--repo", repo, "--json", "number,author,headRefOid,closingIssuesReferences,state")
        issues = [i["number"] for i in pr.get("closingIssuesReferences") or []]
        if pr.get("state") != "OPEN" or not issues:
            say("Nothing to adopt: the pull request is not open, or closes no issue (GitHub's link).")
            return []
        # The head the maintainer read: the SHA they name, which must still be
        # the head, or else the head read the moment the command came, named
        # in the comment, and never a later commit.
        head = pr["headRefOid"]
        if who and not head.startswith(who):
            say(f"@{login}, the head of #{number} is {head[:12]} now, not {who}: it moved since you read it. Read it again, then `/adopt {head[:12]}`.")
            return []
        author = pr["author"]["login"]
        uid = gh("api", f"users/{author}", "--jq", ".id", check=False).strip()
        issue = read_issue(repo, issues[0])
        state_id, _ = read_marker(issue["comments"], MARK)
        acts, _ = plan_adopt_issue({"number": number, "author": author, "author_id": int(uid) if uid.isdigit() else None, "head": head}, login, issue, when)
        return apply_plan(repo, issues[0], acts, state_id)
    if is_pr:
        return []
    issue = read_issue(repo, number)
    state_id, state = read_marker(issue["comments"], MARK)
    if name == "claim":
        ok, why = do_claim(repo, issue, login, "", when, cfg)
        if not ok:
            say(f"@{login}, the claim is refused: {why}.")
        return []
    if name == "unclaim":
        target = who or login
        current = issue.get("claim")
        if not current or current.get("login") != target:
            say(f"@{login}, @{target} holds no claim on this issue.")
            return []
        return apply_plan(repo, number, plan_end(issue, f"`/unclaim` by @{login} on {iso(when)}"), state_id)
    if name == "yield":
        if issue.get("claim"):
            say(f"@{login}, @{issue['claim']['login']} holds the claim already; `/unclaim @{issue['claim']['login']}` first.")
            return []
        acts, _ = plan_yield(who, login, issue["prs"], autopilot_runs(repo, number), when, issue, cfg)
        apply_plan(repo, number, acts, state_id)
        return []
    if name == "extend":
        current = issue.get("claim")
        if not current or current.get("login") != login:
            return []
        new, ok, why = extend(current, when, cfg)
        if ok:
            apply_plan(repo, number, [("state", state_text(new, cfg))], state_id)
        say(f"@{login}, {'the claim is ' + why if ok else 'the claim is not extended: ' + why}.")
        return []
    return []


def on_issue(repo, event, cfg, when):
    action, iss = event.get("action"), event["issue"]
    number = iss["number"]
    if action in ("opened", "edited"):
        author = (iss.get("user") or {}).get("login") or ""
        sender = (event.get("sender") or {}).get("login") or ""
        before = ((event.get("changes") or {}).get("body") or {}).get("from")
        if is_bot(author) or not form_ticked(action, author, sender, iss.get("body"), before):
            return []
        issue = read_issue(repo, number)
        if issue.get("claim"):
            return []
        ok, why = do_claim(repo, issue, author, "", when, cfg)
        if not ok:
            gh("issue", "comment", str(number), "--repo", repo, "--body", f"@{author}, the claim in the form is refused: {why}.\n\n{SIGN}")
        return []
    if action == "labeled" and (event.get("label") or {}).get("name") == "accepted":
        issue = read_issue(repo, number)
        if not issue.get("claim") or issue["claim"].get("clock"):
            return []
        state_id, _ = read_marker(issue["comments"], MARK)
        apply_plan(repo, number, [("state", state_text(start_clock(issue["claim"], when), cfg))], state_id)
    return []


def on_pull_request(repo, event, cfg, when):
    action, pr = event.get("action"), event["pull_request"]
    author = (pr.get("user") or {}).get("login") or ""
    if is_bot(author) or (pr.get("user") or {}).get("type") == "Bot":
        return []
    number = pr["number"]
    if action in ("opened", "reopened") and permission(repo, author) not in WRITERS:
        found = gh("api", "-X", "GET", "search/issues", "-f", f"q=org:{org_of(repo)} is:pr is:open author:{author}", "--jq", ".items[].html_url").split()
        others = [u for u in found if not u.endswith(f"{repo}/pull/{number}")]
        close, why = pr_limit(author, others, cfg)
        if close:
            gh("pr", "close", str(number), "--repo", repo, "--comment", f"{why}\n\n{SIGN}")
            return []
    data = gh_json("pr", "view", str(number), "--repo", repo, "--json", "closingIssuesReferences")
    for ref in (data or {}).get("closingIssuesReferences") or []:
        issue = read_issue(repo, ref["number"])
        state_id, _ = read_marker(issue["comments"], MARK)
        current = issue.get("claim")
        if current and current.get("login") == author:
            if action == "synchronize" or (action == "closed" and not pr.get("merged")):
                apply_plan(repo, ref["number"], [("state", state_text(pushed(current, iso(when)), cfg))], state_id)
            continue
        if action not in ("opened", "reopened"):
            continue
        started = autopilot_started(issue["prs"], [])
        _, linked = read_marker(issue["comments"], LINK_MARK)
        if started and not (linked and number in linked.get("prs", [])):
            ap = next(p["number"] for p in issue["prs"] if "autopilot" in p["labels"] and p["state"] == "OPEN")
            text = (f"Two pull requests close this issue: the autopilot's #{ap} and #{number} by @{author}. Both stay open and neither blocks the other; "
                    f"the maintainer picks one at review.\n\n{marker(LINK_MARK, {'prs': sorted(set((linked or {}).get('prs', []) + [number]))})}\n\n{SIGN}")
            gh("issue", "comment", str(ref["number"]), "--repo", repo, "--body", text)
    return []


PRS_QUERY = """query($q: String!) {
  search(query: $q, type: ISSUE, first: 100) {
    nodes { ... on PullRequest { number createdAt reviewDecision author { __typename login }
      latestReviews(first: 20) { nodes { state submittedAt } }
      commits(last: 1) { nodes { commit { committedDate authors(first: 5) { nodes { user { login } } } statusCheckRollup { state } } } }
      closingIssuesReferences(first: 5) { nodes { number } }
      comments(last: 50) { nodes { author { login } body } } } }
  }
}"""


def daily(repo, cfg, when):
    start, claims, waiting, given_up = [], [], [], []
    numbers = gh("issue", "list", "--repo", repo, "--state", "open", "--label", CLAIMED, "--limit", "200", "--json", "number", "--jq", ".[].number").split()
    failed = []
    for n in numbers:
        try:
            start += daily_issue(repo, n, cfg, when, claims)
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as err:
            print(f"::warning::#{n}: {str(err)[:300]}")
            failed.append(n)
    data = gh_json("api", "graphql", "-f", f"query={PRS_QUERY}", "-F", f"q=repo:{repo} is:pr is:open")
    for pr in ((data or {}).get("data") or {}).get("search", {}).get("nodes") or []:
        try:
            start += daily_pull(repo, pr, cfg, when, waiting)
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as err:
            print(f"::warning::#{(pr or {}).get('number')}: {str(err)[:300]}")
            failed.append((pr or {}).get("number"))
    for n in gh("issue", "list", "--repo", repo, "--state", "open", "--label", FIRST, "--json", "number,labels", "--jq",
                f'.[] | select([.labels[].name] | index("{CLAIMED}") == null) | .number').split():
        given_up.append((n, "kept for a newcomer (`good first issue`)"))
    for line in gh("pr", "list", "--repo", repo, "--state", "open", "--label", "autopilot", "--label", "needs-human", "--json", "closingIssuesReferences",
                   "--jq", ".[].closingIssuesReferences[].number").split():
        given_up.append((line, "the autopilot reached its cap"))
    write_list(repo, daily_list(repo, claims, waiting, given_up))
    return start, failed


def daily_issue(repo, n, cfg, when, claims):
    """One claim's daily step; returns the issues to start the autopilot on."""
    start = []
    issue = read_issue(repo, n)
    state_id, state = read_marker(issue["comments"], MARK)
    if not state:
        return []
    has_pr = any(p["state"] == "OPEN" and p["author"] == state["login"] for p in issue["prs"])
    what = daily_claim(state, when, issue["labels"], has_pr, issue.get("last_push"), cfg)
    _, release = deadlines(pushed(state, issue["last_push"]) if issue.get("last_push") else state, cfg)
    if what == "remind":
        new = {**(pushed(state, issue["last_push"]) if issue.get("last_push") else state)}
        new["reminded"] = new["clock"]
        apply_plan(repo, n, [("state", state_text(new, cfg)), ("comment", f"@{state['login']}, a reminder: this claim is released on {day(release)} without a pull request or a push to a linked branch. Comment \"still on it\" to extend it once, or `/unclaim` it.\n\n{SIGN}")], state_id)
    elif what == "release":
        return apply_plan(repo, n, plan_end({**issue, "claim": state}, f"no pull request or push by {day(release)}"), state_id)
    claims.append((n, state["login"], {"pending": "its clock waits for acceptance", "waiting": "a pull request stopped its clock"}.get(what, f"released on {day(release)}" if release else "")))
    return start


def daily_pull(repo, pr, cfg, when, waiting):
    """One person's pull request's daily step; returns the issues to start
    the autopilot on."""
    start = []
    author = (pr.get("author") or {}).get("login") or ""
    if not pr or (pr.get("author") or {}).get("__typename") != "User" or is_bot(author):
        return []
    issues = [i["number"] for i in pr["closingIssuesReferences"]["nodes"]]
    if not issues:
        return []
    commit = ((pr["commits"]["nodes"] or [{}])[0]).get("commit") or {}
    by_author = any(((a.get("user") or {}).get("login")) == author for a in (commit.get("authors") or {}).get("nodes") or [])
    reviews = [r["submittedAt"] for r in pr["latestReviews"]["nodes"] if r["state"] == "CHANGES_REQUESTED"]
    info = {"author": author, "number": pr["number"], "review": pr.get("reviewDecision") or "", "created": pr["createdAt"],
            "checks": (commit.get("statusCheckRollup") or {}).get("state") or "", "pushed": commit.get("committedDate") if by_author else None,
            "reviewed": max(reviews) if reviews else None}
    since = max(t for t in (info["pushed"], info["reviewed"], info["created"]) if t)
    reminded = any(marker(PR_REMIND_MARK, {"since": since}) in (c.get("body") or "") and is_bot(((c.get("author") or {}).get("login")) or "")
                   for c in pr["comments"]["nodes"])
    what = daily_pr(info, when, reminded, cfg)
    if what == "waiting":
        waiting.append((pr["number"], author))
    elif what == "remind":
        gh("pr", "comment", str(pr["number"]), "--repo", repo, "--body",
           f"@{author}, a reminder: this pull request waits on you (changes requested or failing checks). With no push from you it is closed, with thanks, {cfg['pr-close-days'] - cfg['pr-remind-days']} days from now; reopen it when you come back.\n\n{marker(PR_REMIND_MARK, {'since': since})}\n\n{SIGN}")
    elif what == "close":
        read = {n: read_issue(repo, n) for n in issues}
        for n, acts in plan_pr_close(info, list(read.values()), cfg["pr-close-days"]):
            start += apply_plan(repo, n, acts, read_marker(read[n]["comments"], MARK)[0])
    return start


def retire_test(body, when):
    """A claimed bug's test comment once its claim ends: the text kept, its
    marker gone, so the gate no longer reads it."""
    return re.sub(r"<!-- " + re.escape(TEST_MARK) + r" \{.*?\} -->", f"~~Its claim~~ ended on {when}: the test is no longer the claimant's.", body or "")


def lane_open(repo, number, test):
    """The `bugfix-reproduced` lane's issue for a claimed bug released, with
    the test it was sealed with (the reproduction's own run named, which the
    lane checks)."""
    env = dict(os.environ, REPORT=str(number), RUN_URL=test.get("run", ""), SHA256=test["sha256"], BASE=test.get("base", ""),
               WAY=test.get("way", ""), SPEC=test.get("spec", ""), NOUN=test.get("noun", ""), THEME=test.get("theme", ""))
    out = json.loads(subprocess.run([sys.executable, os.path.join(HERE, "repro-lane.py"), "prd"], capture_output=True, text=True, env=env, check=True).stdout)
    for name, color, desc in (("lane:bugfix-reproduced", "1D76DB", "A bug the reproduction confirmed with a failing test"),
                              ("accepted-by:policy", "0E8A16", "Accepted by a lane of the autonomy policy, not by a person")):
        gh("label", "create", name, "--repo", repo, "--color", color, "--description", desc, "--force", check=False)
    url = gh("issue", "create", "--repo", repo, "--title", out["title"], "--body", out["body"], "--label", "lane:bugfix-reproduced").strip()
    lane = url.rsplit("/", 1)[-1]
    gh("api", "-X", "PATCH", f"repos/{repo}/issues/{lane}", "-f", "type=Bug", check=False)
    ok = subprocess.run([sys.executable, os.path.join(HERE, "autonomy.py"), "lane-accept"], capture_output=True, text=True, env=dict(os.environ, NUMBER=lane))
    if ok.returncode != 0:
        gh("issue", "comment", lane, "--repo", repo, "--body", f"No lane accepted this issue ({ok.stdout.strip()}), so it waits for a maintainer.\n\n{SIGN}")
        return None
    gh("issue", "edit", lane, "--repo", repo, "--add-label", "accepted-by:policy")
    body = gh("issue", "view", lane, "--repo", repo, "--json", "body", "--jq", ".body")
    path = os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), f"lane-{lane}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    subprocess.run([sys.executable, os.path.join(HERE, "receipts.py"), "seal-prd"], check=True,
                   env=dict(os.environ, NUMBER=lane, BODY=path, ACCEPTED_BY="policy (lane bugfix-reproduced)"))
    gh("issue", "comment", str(number), "--repo", repo, "--body", f"The fix is #{lane}: the `bugfix-reproduced` lane took it with the same failing test, and the autopilot works it.\n\n{SIGN}")
    return lane


def write_list(repo, text):
    """This repository's comment on the organisation's open `run:claims`
    issue (choice 2a), rewritten each day; only the organisation's .github
    opens the issue, so two repositories never open two."""
    central = f"{org_of(repo)}/.github"
    found = gh("issue", "list", "--repo", central, "--state", "open", "--label", LIST, "--limit", "1", "--json", "number", "--jq", ".[0].number // empty", check=False).strip()
    if not found:
        if repo != central:
            return
        gh("label", "create", LIST, "--repo", central, "--color", "C5DEF5", "--description", "The daily list of claims", "--force", check=False)
        found = gh("issue", "create", "--repo", central, "--title", "Claims: the daily list", "--label", LIST, "--body",
                   "The claims of every repository, their deadlines, the persons' pull requests waiting on a maintainer, and the issues anyone may `/claim`: one comment per repository, rewritten each day by its daily run.\n\n" + SIGN).strip().rsplit("/", 1)[-1]
    comments = gh_json("api", f"repos/{central}/issues/{found}/comments", "--paginate", "--slurp") or []
    comments = [c for page in comments for c in page] if comments and isinstance(comments[0], list) else comments
    mine = next((c["id"] for c in comments if is_bot((c.get("user") or {}).get("login") or "") and (c.get("body") or "").startswith(f"<!-- {LIST} {repo} -->")), None)
    if mine:
        gh("api", "-X", "PATCH", f"repos/{central}/issues/comments/{mine}", "-f", f"body={text}")
    else:
        gh("issue", "comment", found, "--repo", central, "--body", text)


def repro_text(login, test, cfg, state):
    _, release = deadlines(state, cfg)
    return (f"@{login}, the bug is reproduced and it is yours: the failing test `{test['test']}` is on the branch `{test['branch']}`. "
            f"Start your branch from it; your pull request must carry that test unchanged (its SHA-256 `{test['sha256']}`, which the gate checks) and make it pass. "
            f"The claim's clock starts now: it is released on {day(release)} without a pull request or a push, and then the autopilot fixes it with the same test.\n\n"
            f"{marker(TEST_MARK, test)}\n\n{SIGN}")


def repro(repo, cfg, when):
    number = os.environ["NUMBER"]
    issue = read_issue(repo, number)
    state_id, state = read_marker(issue["comments"], MARK)
    if not issue.get("claim") or not state:
        print(f"#{number} is not claimed")
        return 1
    test = {k.lower(): os.environ.get(k, "") for k in ("TEST", "SHA256", "BRANCH", "BASE", "WAY", "SPEC", "NOUN", "THEME")}
    test["run"] = os.environ.get("RUN_URL", "")
    new = start_clock(state, when, reset=True)
    apply_plan(repo, number, [("state", state_text(new, cfg)), ("comment", repro_text(state["login"], test, cfg, new))], state_id)
    return 0


def main(argv):
    if argv[:1] == ["--test"]:
        return self_test()
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    cfg, when = policy(), now()
    if argv[:1] == ["repro"]:
        return repro(repo, cfg, when)
    start, failed = [], []
    if argv[:1] == ["event"]:
        with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as fh:
            event = json.load(fh)
        name = os.environ.get("GITHUB_EVENT_NAME", "")
        if name == "issue_comment" and event.get("action") == "created":
            start = on_comment(repo, event, cfg, when)
        elif name == "issues":
            start = on_issue(repo, event, cfg, when)
        elif name == "pull_request_target":
            start = on_pull_request(repo, event, cfg, when)
    elif argv[:1] == ["daily"]:
        # One that fails is said and the rest go on; what was released still
        # starts, and the run then fails, so it is seen.
        start, failed = daily(repo, cfg, when)
    else:
        print(__doc__, file=sys.stderr)
        return 64
    start = sorted({str(n) for n in start})
    print(f"Start the autopilot on: {', '.join('#' + n for n in start) or 'none'}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"start={json.dumps(start)}\n")
    if argv[:1] == ["daily"] and failed:
        print(f"::error::The daily run could not finish {len(failed)} of them: {', '.join(f'#{n}' for n in failed)}.")
        return 1
    return 0


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        if got == want:
            print(f"ok   {name}")
        else:
            print(f"FAIL {name}: got {got!r}, want {want!r}")
            failed = 1

    cfg = config({})
    t0 = ts("2026-11-01T09:00:00Z")
    at = lambda n: t0 + days(n)
    bot = {"login": org.BOT}
    accepted = {"number": 7, "state": "OPEN", "labels": ["accepted"], "claim": None, "accepted": True}

    # C1: `/claim` on an accepted issue nobody holds: labelled, the person
    # named, and (autopilot.py held_by) the autopilot does not start.
    check("C1 commands are read from the first line",
          [parse("/claim"), parse("/claim\nI'll take it"), parse("/unclaim"), parse("/unclaim @ana"), parse("/yield @ana"), parse("/yield"),
           parse("/adopt"), parse("/adopt 0123abc"), parse("/adopt @ana"), parse("/claim @ana"), parse("I could /claim it"), parse("")],
          [("claim", ""), ("claim", ""), ("unclaim", ""), ("unclaim", "ana"), ("yield", "ana"), None,
           ("adopt", ""), ("adopt", "0123abc"), None, None, None, None])
    check("C1 an accepted issue nobody holds may be claimed", may_claim("ana", accepted, 0, False, "", cfg), (True, "claimed"))
    acts, state = plan_claim("ana", "", t0, accepted, cfg)
    check("C1 the claim labels it, assigns the person, writes its state and a comment naming them",
          [a[0] for a in acts], ["label", "assign", "state", "comment"])
    check("C1 ... `claimed`, @ana", (acts[0][1], acts[1][1], "@ana claimed this issue" in acts[3][1]), (CLAIMED, "ana", True))
    check("C1 the state comment says the dates and the autopilot does not start",
          ("Reminder on 2026-11-08 and released on 2026-11-11" in acts[2][1], "The autopilot does not start" in acts[2][1]), (True, True))
    check("C1 the state is read back from dilux-bot's comment", read_marker([{"id": 5, "user": bot, "body": acts[2][1]}], MARK), (5, state))
    check("C1 a marker in a person's comment is never read",
          read_marker([{"id": 6, "user": {"login": "mallory"}, "body": marker(MARK, {**state, "login": "mallory"})}], MARK), (None, None))
    check("C1 a claimed issue is refused to another, with who holds it",
          may_claim("bob", {**accepted, "labels": ["accepted", CLAIMED], "claim": state}, 0, True, "", cfg)[0], False)
    # C2: claimed in the form before acceptance; the clock starts at `accepted`.
    form = "### What happened?\n\nIt broke.\n\n### Who works on it\n\n- [X] I want to work on this myself\n"
    check("C2 the form's checkbox claims it, ticked only", (form_claim(form), form_claim(form.replace("[X]", "[ ]")), form_claim("I want to work on this myself")), (True, False, False))
    acts, before = plan_claim("ana", "", t0, {**accepted, "labels": [], "accepted": False}, cfg)
    check("C2 a claim before acceptance is recorded with no clock, and says when it starts",
          (before["clock"], "Its clock starts when the issue is accepted" in acts[2][1], daily_claim(before, at(40), [], False, None, cfg)), (None, True, "pending"))
    started = start_clock(before, at(3))
    check("C2 the clock starts at the `accepted` event, and the dates run from it",
          (started["clock"], started["start"], [day(d) for d in deadlines(started, cfg)]), (iso(at(3)), iso(at(3)), ["2026-11-11", "2026-11-14"]))
    check("C2 a second `accepted` does not restart a running clock", start_clock(started, at(5))["clock"], iso(at(3)))
    check("C2 the form claims on opening, or when its author ticks it in an edit; never on someone else's edit of a ticked body",
          [form_ticked("opened", "ana", "ana", form), form_ticked("edited", "ana", "ana", form, form.replace("[X]", "[ ]")),
           form_ticked("edited", "ana", org.BOT, form, form.replace("[X]", "[ ]")), form_ticked("edited", "ana", "ana", form, form),
           form_ticked("edited", "ana", "ana", form, None)], [True, True, False, False, False])
    # C3: day 7 reminds, day 10 releases and starts the autopilot; a push to
    # a linked branch resets the clock.
    check("C3 days 6, 7 and 10 without a pull request or a push",
          [daily_claim(state, at(n), [], False, None, cfg) for n in (6, 7, 10)], ["none", "remind", "release"])
    check("C3 reminded once per clock", daily_claim({**state, "reminded": state["clock"]}, at(8), [], False, None, cfg), "none")
    rel = plan_release(state, "no pull request or push by 2026-11-11", 7)
    check("C3 the release takes the label off, unassigns, says why, and starts the autopilot",
          ([a[0] for a in rel], rel[-1], "@ana" in rel[3][1] and "The autopilot starts on it now" in rel[3][1]),
          (["unlabel", "unassign", "state", "comment", "start"], ("start", 7), True))
    check("C3 every claim ends through plan_end: without a test, the release as it was", plan_end({"number": 7, "claim": state}, "why"), plan_release(state, "why", 7))
    unclaim = plan_end({"number": 7, "claim": state, "test": {"test": "t", "sha256": "a" * 64}, "test_id": 55}, "`/unclaim` by @ana")
    check("C8 `/unclaim` of a claimed bug: released, the lane opened with its test, the test's marker struck out, the autopilot not started on the report",
          (unclaim[-2:], any(a[0] == "start" for a in unclaim)), ([("lane", {"test": "t", "sha256": "a" * 64}), ("retire-test", 55)], False))
    # /adopt of a claimed bug: no start on the unsealed report and no second
    # lane run; the adoption is made on the lane's issue, its only start.
    bug = {"number": 7, "claim": state, "test": {"test": "t", "sha256": "a" * 64}, "test_id": 55}
    pr41 = {"number": 41, "author": "ana", "author_id": 77, "head": "d" * 40}
    adopt_bug, rec_bug = plan_adopt_issue(pr41, "soy", bug, at(9))
    lane_acts = plan_adopt(pr41, "soy", 90, at(9))[0]
    check("C8 `/adopt` of a claimed bug ends its claim and test marker, starts nothing on the report, and adopts on the lane's issue",
          ([a[0] for a in adopt_bug], rec_bug, adopt_bug[-1][2:], [a for a in lane_acts if a[0] == "start"], [a[1] for a in lane_acts if a[0] == "branch"]),
          (["unlabel", "unassign", "state", "comment", "retire-test", "lane-adopt"], None, (pr41, "soy"), [("start", 90)], ["feat/90-adopted-41"]))
    plain, _ = plan_adopt_issue(pr41, "soy", {"number": 7, "claim": state}, at(9))
    check("C10 `/adopt` of a claimed issue without a test releases it without a start of its own, then starts it once, from the adopted branch",
          ([a[0] for a in plain].count("start"), plain[-1], [a[0] for a in plain][:3]), (1, ("start", 7), ["unlabel", "unassign", "state"]))
    check("C10 `/adopt` of an unclaimed issue is the adoption alone", plan_adopt_issue(pr41, "soy", {"number": 7}, at(9))[0], plan_adopt(pr41, "soy", 7, at(9))[0])
    given = repro_text("ana", {"test": "t", "sha256": "a" * 64, "branch": "b"}, cfg, state)
    gone = retire_test(given, "2026-11-11T00:00:00Z")
    check("C8 a struck-out test is read no more, and says why",
          (read_marker([{"id": 55, "user": bot, "body": given}], TEST_MARK)[0], read_marker([{"id": 55, "user": bot, "body": gone}], TEST_MARK), "~~Its claim~~ ended" in gone),
          (55, (None, None), True))
    src = open(os.path.abspath(__file__), encoding="utf-8").read().split("\ndef self_test")[0]
    check("C8 no release bypasses plan_end (plan_release is called from it alone)",
          [ln.strip()[:40] for ln in src.splitlines() if "plan_release(" in ln and not ln.lstrip().startswith("def ")],
          ["return plan_release(state, why, n, start", "return plan_release(state, why, n, start"])
    check("C3 a push to a linked branch on day 6 resets the clock: day 10 is not the release, day 16 is",
          [daily_claim(state, at(n), [], False, iso(at(6)), cfg) for n in (10, 13, 16)], ["none", "remind", "release"])
    check("C3 a push older than the clock changes nothing", pushed(state, iso(t0 - days(2))), state)
    check("C3 a pull request stops the clock; `claim:long` exempts it",
          (daily_claim(state, at(20), [], True, None, cfg), daily_claim(state, at(20), [LONG], False, None, cfg)), ("waiting", "none"))
    # C4: one "still on it" extends it; a second is refused and the claim
    # keeps the first one's deadline (choice 4a); 30 days from the clock's
    # start release it whatever happened since.
    check("C4 \"still on it\" is the extension, anywhere in the comment", parse("Sorry, still on it, back Monday"), ("extend", ""))
    once, ok, why = extend(state, at(9), cfg)
    check("C4 the first extension restarts the clock once", (ok, once["clock"], once["extended"], day(deadlines(once, cfg)[1])), (True, iso(at(9)), True, "2026-11-20"))
    twice, ok2, why2 = extend(once, at(15), cfg)
    check("C4 a second is refused, and the first one's deadline stands",
          (ok2, twice, "released on 2026-11-20" in why2, daily_claim(twice, at(19), [], False, None, cfg)), (False, once, True, "release"))
    check("C4 pushes every week never take it past 30 days from the clock's start",
          [daily_claim(state, at(n), [], False, iso(at(24)), cfg) for n in (29, 30)], ["none", "release"])
    check("C4 nor does an extension late in the claim", daily_claim(extend(pushed(state, iso(at(22))), at(28), cfg)[0], at(30), [], False, None, cfg), "release")
    # C5: the first one wins. `/claim` once the autopilot started is refused
    # with why; a maintainer's `/yield @login` cancels its run, closes its
    # draft and claims the issue for the person.
    ap_pr = {"number": 30, "state": "OPEN", "labels": ["autopilot"], "author": org.BOT}
    person_pr = {"number": 31, "state": "OPEN", "labels": [], "author": "bob"}
    run = "https://github.com/o/r/actions/runs/9"
    check("C5 the autopilot started: its open pull request, or its run in progress",
          (autopilot_started([ap_pr], []), autopilot_started([], [run]), autopilot_started([person_pr, {**ap_pr, "state": "CLOSED"}], [])),
          ("the autopilot is already on it in #30", f"the autopilot is already on it ({run})", ""))
    ok, why = may_claim("ana", accepted, 0, True, autopilot_started([ap_pr], []), cfg)
    check("C5 `/claim` is refused, saying why and how a maintainer hands it over",
          (ok, why.startswith("the autopilot is already on it in #30. The first one wins"), "`/yield @ana`" in why), (False, True, True))
    acts, yielded = plan_yield("ana", "soydiloreto", [ap_pr, person_pr], ["9"], t0, accepted, cfg)
    check("C5 `/yield` plans: cancel the run, close the autopilot's draft (not a person's), then claim it for the person",
          [a[:2] for a in acts], [("cancel", "9"), ("close-pr", 30), ("label", CLAIMED), ("assign", "ana"), ("state", acts[4][1]), ("comment", acts[5][1])])
    check("C5 ... the claim names who handed it over, and its clock runs from now",
          ("handed over by @soydiloreto" in acts[5][1], yielded["clock"], "/yield" in acts[1][2]), (True, iso(t0), True))
    check("C5 only a maintainer gives `/yield` or `/adopt`; `/unclaim @x` the claimant or a maintainer",
          [may_act("yield", "bob", "read", "ana")[0], may_act("yield", "soy", "admin", "ana")[0], may_act("adopt", "bob", "triage")[0],
           may_act("unclaim", "bob", "read", "ana")[0], may_act("unclaim", "ana", "none", "ana")[0], may_act("unclaim", "ana", "none")[0], may_act("unclaim", "soy", "write", "ana")[0]],
          [False, True, False, False, True, True, True])
    # C7: a person's pull request with changes requested (or failing checks)
    # and no push by its author: reminded at 7 days, closed with thanks at
    # 14 and the autopilot started; one that waits on a maintainer's review
    # stops its author's clock and is listed as waiting on the maintainer.
    stalled = {"number": 41, "author": "ana", "review": "CHANGES_REQUESTED", "checks": "SUCCESS", "created": iso(t0 - days(3)),
               "pushed": iso(t0 - days(1)), "reviewed": iso(t0)}
    check("C7 changes requested: days 6, 7, 13 (reminded) and 14 with no push by its author",
          [daily_pr(stalled, at(6), False, cfg), daily_pr(stalled, at(7), False, cfg), daily_pr(stalled, at(13), True, cfg), daily_pr(stalled, at(14), True, cfg)],
          ["none", "remind", "none", "close"])
    check("C7 a push by its author restarts its days", daily_pr({**stalled, "pushed": iso(at(10))}, at(14), True, cfg), "none")
    check("C7 failing checks count as waiting on its author", daily_pr({**stalled, "review": "", "checks": "FAILURE", "reviewed": None}, at(14), True, cfg), "close")
    closing = plan_pr_close(stalled, [{"number": 7, "claim": None}])
    check("C7 closed with thanks (\"reopen it when you come back\"), and the autopilot started on the issue",
          ([(n, [a[0] for a in acts]) for n, acts in closing], closing[-1][1], "Thank you, @ana" in closing[0][1][0][2] and "reopen it when you come back" in closing[0][1][0][2]),
          ([(7, ["close-pr"]), (7, ["start"])], [("start", 7)], True))
    sealed = {"test": "tests/Unit/Repro/Issue7Test.php", "sha256": "a" * 64, "branch": "test/repro-issue-7"}
    bug = {"number": 7, "claim": state, "test": sealed, "test_id": 55}
    closing = plan_pr_close(stalled, [bug, {"number": 8, "claim": None}])
    check("C7/C8 the stalled close of a claimed bug's pull request sends it to its lane with the same test, never the autopilot on the report",
          [(n, [a[0] for a in acts]) for n, acts in closing],
          [(7, ["close-pr"]), (7, ["unlabel", "unassign", "state", "comment", "lane", "retire-test"]), (8, ["start"])])
    check("C7 ... and a claim of someone else's on the issue is left as it is",
          [(n, [a[0] for a in acts]) for n, acts in plan_pr_close({**stalled, "author": "bob"}, [bug])], [(7, ["close-pr"]), (7, ["start"])])
    review = {**stalled, "review": "REVIEW_REQUIRED", "reviewed": None, "pushed": iso(t0 - days(60))}
    check("C7 one that waits on a maintainer's review is never closed for it, however long",
          [daily_pr(review, at(n), False, cfg) for n in (14, 90)], ["waiting", "waiting"])
    check("C7 ... and its claim's clock does not run", daily_claim(state, at(90), [], True, None, cfg), "waiting")
    listed = daily_list("o/r", [(7, "ana", "a pull request stopped its clock")], [(41, "ana")], [])
    check("C7 the daily list names it as waiting on the maintainer",
          "**Waiting on a maintainer's review** (its author's clock does not run)\n\n- #41 by @ana" in listed, True)
    # C9: one open claim at a time with no merged pull request in the
    # organisation, three with one.
    forged = {"assignees": [], "comments": [{"id": 9, "user": {"login": "mallory"}, "body": "**Claimed by @ana** " + marker(MARK, {**state, "login": "ana"})}]}
    real = {"assignees": [], "comments": [{"id": 5, "user": bot, "body": state_text(state, cfg)}]}
    check("C9 a claim is counted from dilux-bot's marker or the assignee, never from a person's comment naming someone",
          (claims_of("ana", [forged]), claims_of("ana", [real]), claims_of("ana", [{"assignees": ["ana"], "comments": []}, forged, real]), claims_of("bob", [real])),
          (0, 1, 2, 0))
    check("C9 the limits: one for a newcomer, three for a contributor", (claim_limit(False, cfg), claim_limit(True, cfg)), (1, 3))
    ok, why = may_claim("ana", accepted, 1, False, "", cfg)
    check("C9 no merged pull request and one open claim: a second is refused, saying why",
          (ok, "@ana holds 1 open claim" in why and "at most 1 at a time" in why), (False, True))
    check("C9 with a merged pull request: a second and a third, not a fourth",
          [may_claim("ana", accepted, n, True, "", cfg)[0] for n in (1, 2, 3)], [True, True, False])
    check("C9 a repository's tighter limit holds", may_claim("ana", accepted, 1, True, "", config({"claims": {"contributor-claims": 1}}))[0], False)
    # Choice 3a: a person without write access keeps at most two pull
    # requests open across the organisation; a third is closed at once.
    others = ["https://github.com/o/a/pull/1", "https://github.com/o/b/pull/2"]
    close, why = pr_limit("ana", others, cfg)
    check("3a a third open pull request is closed, linking the other two", (close, all(u in why for u in others)), (True, True))
    check("3a a second is not", pr_limit("ana", others[:1], cfg), (False, ""))
    if not failed:
        print("all tests passed")
    return failed


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
