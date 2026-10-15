#!/usr/bin/env python3
"""What still needed a person, for the weekly digest (autonomy-digest.yml, #143).

Every pull request in the organisation that a person merged in the last four
weeks, or that is waiting on one now, with the reasons the gates, the labels
and the review recorded for it: why it did not merge on its own. Printed as
Markdown: this week's pull requests, the totals per reason and per week (and
per repository) over the four weeks, and a proposal, as text only, for each
reason that stopped 5 or more pull requests whose review found no blocker or
major. Changing a limit stays a pull request a person accepts and merges.

The digest goes on a public issue: a repository that is not public is only
counted, under its reasons; its name, titles and links never appear.

Nothing is stored between runs: the four weeks are read again from the API
each Monday, so a missed or re-run week, or a fix to the classification,
leaves no wrong total behind, and no state lives in a comment anyone with
access to the issue could edit.

  needed-a-person.py                print the section (GH_TOKEN, OWNER; NOW,
                                    an ISO time, defaults to now)
  needed-a-person.py classify FILE  print the reasons of each pull request in
                                    FILE (JSON lines, as the search returns
                                    them), one line each
  needed-a-person.py --test         self-test, from fixtures/needed-a-person.json
"""
import datetime
import fnmatch
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


autonomy = _load("autonomy", "autonomy.py")
autopilot = _load("autopilot", "autopilot.py")

BOT = "dilux-bot"
WEEKS = 4
PROPOSE_AT = 5
# Each reason, in the order the digest lists them. A reason `risk-cap:<cap>`
# is added per cap: the auto-merge's (low) or an autopilot lane's.
REASONS = {
    "high-risk": "high risk",
    "protected-path": "protected path",
    "critical": "Critical issue",
    "review-blocker": "review blocker",
    "rounds-exhausted": "autopilot rounds exhausted",
    "failed-gate": "failed gate",
    "size-cap": "size cap",
    "outside-author": "outside author",
    "risk-cap": "over the risk cap",
    "unknown": "unknown",
}
FAILED = {"FAILURE", "TIMED_OUT", "STARTUP_FAILURE", "ERROR"}
# Not counted by the size cap, as scripts/conventions.sh.
UNCOUNTED = re.compile(r"(^|/)(composer\.lock|package-lock\.json)$|(^|/)languages/[^/]+\.(po|pot|mo)$")
RECORD = re.compile(r"<!-- dx-review-record (.*?) -->", re.S)
ROUNDS_SPENT = "The autopilot spent its"


def policy():
    """The limits the classification compares with: the organisation's
    autonomy policy and default review policy (a repository's own files can
    only be stricter; the digest reads the organisation's)."""
    auto = autonomy.load(os.environ.get("ORG_AUTONOMY") or os.path.join(HERE, "..", "policy", "autonomy.yml"))
    review = autonomy.load(os.environ.get("ORG_REVIEW_POLICY") or os.path.join(HERE, "..", "policy", "review-policy.default.yml"))
    return {
        "constitution": auto.get("constitution") or [],
        "lanes": auto.get("lanes") or {},
        "trusted": review.get("trusted-authors") or [],
        "max-lines": int(review.get("max-changed-lines-untrusted") or 0),
    }


def login(actor):
    """GraphQL names an App `dilux-bot`; REST and the policy `dilux-bot[bot]`."""
    if not actor:
        return ""
    name = actor.get("login") or ""
    return f"{name}[bot]" if actor.get("__typename") == "Bot" and not name.endswith("[bot]") else name


def nodes(conn):
    return (conn or {}).get("nodes") or []


def by_bot(comment):
    return login(comment.get("author")) == f"{BOT}[bot]"


def comments(pr):
    """The first and the last comments (the review's summary comes early, a
    hand-over late), each once."""
    seen, out = set(), []
    for c in nodes(pr.get("early")) + nodes(pr.get("comments")):
        key = (login(c.get("author")), c.get("body"))
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def review_record(pr):
    """The last review's record, from the review's summary comment."""
    rec = None
    for c in comments(pr):
        body = c.get("body") or ""
        if by_bot(c) and body.startswith("<!-- dx-review -->"):
            m = RECORD.search(body)
            if m:
                try:
                    rec = json.loads(m.group(1))
                except ValueError:
                    pass
    return rec


def clean_review(pr):
    """A review ran and found no blocker or major."""
    rec = review_record(pr)
    if not rec or rec.get("blocking") is True:
        return False
    return not any((f or {}).get("severity") in ("blocker", "major") for f in rec.get("findings") or [])


def lane_of(pr):
    """The lane an autopilot pull request is decided by: its issue's
    `lane:<name>` label, else the lane of an issue a person accepted."""
    for issue in nodes(pr.get("closingIssuesReferences")):
        for lab in nodes(issue.get("labels")):
            if (lab.get("name") or "").startswith("lane:"):
                return lab["name"][5:]
    return autopilot.LANE


def above(level, cap):
    levels = autopilot.LEVELS
    return level in levels and cap in levels and levels.index(level) > levels.index(cap)


def changed_lines(pr):
    files = nodes(pr.get("files"))
    # Past the first 100 files the totals are all there is, lock files included.
    if pr.get("changedFiles") and pr["changedFiles"] > len(files):
        return (pr.get("additions") or 0) + (pr.get("deletions") or 0)
    return sum((f.get("additions") or 0) + (f.get("deletions") or 0) for f in files if not UNCOUNTED.search(f.get("path") or ""))


def classify(pr, pol):
    """The reasons a person had to decide this pull request, or ["unknown"]."""
    labels = {lab.get("name") for lab in nodes(pr.get("labels"))}
    author = login(pr.get("author"))
    rec = review_record(pr) or {}
    is_autopilot = author == f"{BOT}[bot]"
    reasons = []

    # The review's own rating; the record's `risk` also carries the policy
    # floor, which is a protected path below, not the review's judgement.
    risk = rec.get("model_risk") or rec.get("risk") or next((lab[5:] for lab in labels if lab.startswith("risk:")), "")
    complexity = rec.get("complexity") or next((lab[11:] for lab in labels if lab.startswith("complexity:")), "")
    floor = "" if is_autopilot else rec.get("floor") or ""
    if is_autopilot:
        lane = lane_of(pr)
        caps = (pol["lanes"].get(lane) or {}).get("merge") or {}
        cap_name = f"risk-cap:{lane}"
    else:
        caps = {"max-risk": "low", "max-complexity": "low"}
        cap_name = "risk-cap:auto-merge"
    max_risk, max_cx = caps.get("max-risk", "none"), caps.get("max-complexity", "none")
    if risk == "high" and above("high", max_risk):
        reasons.append("high-risk")
    # A protected path: for the autopilot, the rules that govern autonomy
    # (`constitution`); for anyone else, a high-risk path of the review
    # policy, which sets the floor to high.
    if is_autopilot:
        protected = any(any(fnmatch.fnmatch(f.get("path") or "", p) for p in pol["constitution"]) for f in nodes(pr.get("files")))
    else:
        protected = floor == "high"
    if protected:
        reasons.append("protected-path")
    if any(autopilot.criticality(i.get("body") or "") == "critical" for i in nodes(pr.get("closingIssuesReferences"))):
        reasons.append("critical")
    blocker = rec.get("blocking") is True or any((f or {}).get("severity") == "blocker" for f in rec.get("findings") or [])
    if blocker:
        reasons.append("review-blocker")
    if any(by_bot(c) and (c.get("body") or "").startswith(ROUNDS_SPENT) for c in comments(pr)):
        reasons.append("rounds-exhausted")
    outside = not is_autopilot and author not in pol["trusted"]
    # A bot's pull request a maintainer took over (no `autopilot` label) has no cap.
    capped = outside or (is_autopilot and "autopilot" in labels)
    size = capped and pol["max-lines"] > 0 and changed_lines(pr) > pol["max-lines"]
    # A failing check the reasons above already explain is not a gate of its own.
    failing = []
    for commit in nodes(pr.get("commits")):
        rollup = ((commit.get("commit") or {}).get("statusCheckRollup") or {})
        for ctx in nodes(rollup.get("contexts")):
            name = ctx.get("name") or ctx.get("context") or ""
            if (ctx.get("conclusion") or ctx.get("state")) not in FAILED:
                continue
            if blocker and "Claude review" in name:
                continue
            if size and "conventions" in name.lower():
                continue
            failing.append(name)
    if failing:
        reasons.append("failed-gate")
    if size:
        reasons.append("size-cap")
    if outside:
        reasons.append("outside-author")
    if (risk in ("low", "medium") and above(risk, max_risk)) or floor == "medium" or above(complexity, max_cx):
        reasons.append(cap_name)
    return reasons or ["unknown"]


def needed(pr):
    """"merged" when a person merged it, "waiting" when it waits on one now,
    None otherwise (merged by policy or by GitHub's auto-merge, or not done)."""
    labels = {lab.get("name") for lab in nodes(pr.get("labels"))}
    if pr.get("mergedAt"):
        if "merged-by:policy" in labels:
            return None
        merger = pr.get("mergedBy") or {}
        return "merged" if merger.get("__typename") == "User" else None
    if pr.get("state") != "OPEN" or pr.get("isDraft") or pr.get("autoMergeRequest"):
        return None
    # Waiting on a person: handed to one, or the machinery is done with it
    # (the review ran), or nothing automatic will look at it (a fork).
    if "needs-human" in labels or review_record(pr) or pr.get("isCrossRepository"):
        return "waiting"
    return None


def label(reason):
    if reason.startswith("risk-cap:"):
        cap = reason.split(":", 1)[1]
        return "over the auto-merge's cap (low)" if cap == "auto-merge" else f"over lane {cap}'s cap"
    return REASONS.get(reason, reason)


def order(reason):
    base = reason.split(":", 1)[0]
    keys = list(REASONS)
    return (keys.index(base) if base in keys else len(keys), reason)


def proposal(reason, n):
    found = f"stopped {n} pull requests whose review found no blocker or major in {WEEKS} weeks"
    after = "a pull request a person accepts and merges (the golden rule)"
    if reason == "high-risk":
        return f"The review's high risk {found}. If the review rates too high, the review profile is what to change, by {after}."
    if reason == "protected-path":
        return f"A protected path {found}. If one of those paths is safer than the policy says, narrowing `high-risk` in policy/review-policy.default.yml (or a repository's .github/review-policy.yml) is {after}; the paths that govern autonomy (`constitution` in policy/autonomy.yml) stay with a person."
    if reason == "critical":
        return f"A Critical issue {found}. Criticality is set on the issue: if they were not critical, what the issue form says about it is what to change, by {after}."
    if reason == "rounds-exhausted":
        return f"Running out of autopilot rounds {found} at the end. Raising `autopilot-rounds` in policy/autonomy.yml is {after}."
    if reason == "failed-gate":
        return f"A failed gate {found}. Before any limit, look for a flaky or wrong check in those runs."
    if reason == "size-cap":
        return f"The size cap {found}. Raising `max-changed-lines-untrusted` in policy/review-policy.default.yml is {after}."
    if reason == "outside-author":
        return f"An author outside `trusted-authors` {found}. Adding one who earned it to `trusted-authors` in policy/review-policy.default.yml (or a repository's) is {after}."
    if reason == "risk-cap:auto-merge":
        return f"The auto-merge's cap (low risk, low complexity, low floor) {found}. Letting more merge on its own is a change to policy/review-policy.default.yml and auto-merge.yml, by {after}."
    if reason.startswith("risk-cap:"):
        lane = reason.split(":", 1)[1]
        return f"The risk cap of lane {lane} {found}. Raising its `merge` in policy/autonomy.yml is {after}."
    return None


def parse_time(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def week(pr, kind, now):
    """0 for the last seven days (and for what waits now), up to WEEKS-1."""
    if kind == "waiting":
        return 0
    days = (now - parse_time(pr["mergedAt"])).total_seconds() / 86400
    i = int(days // 7)
    return i if 0 <= i < WEEKS else None


def public(pr):
    return ((pr.get("repository") or {}).get("visibility") or "") == "PUBLIC"


def digest(prs, pol, now):
    rows = []
    seen = set()
    for pr in prs:
        key = pr.get("url")
        if key in seen:
            continue
        seen.add(key)
        kind = needed(pr)
        if not kind:
            continue
        w = week(pr, kind, now)
        if w is None:
            continue
        rows.append({"pr": pr, "kind": kind, "week": w, "reasons": classify(pr, pol), "clean": clean_review(pr)})

    def day(i):
        return (now - datetime.timedelta(days=7 * (i + 1))).strftime("%Y-%m-%d")

    out = ["**Needed a person** (merged by a person, or waiting on one)", ""]
    this = [r for r in rows if r["week"] == 0]
    shown = [r for r in this if public(r["pr"])]
    hidden = [r for r in this if not public(r["pr"])]
    if not this:
        out.append(f"Nothing in the organisation was merged by a person, or waits on one, since {day(0)}.")
    for r in shown:
        pr = r["pr"]
        what = "waiting" if r["kind"] == "waiting" else "merged"
        why = ", ".join(label(x) for x in sorted(r["reasons"], key=order))
        out.append(f"- [{pr['repository']['nameWithOwner']}] {pr.get('title', '')} ({pr.get('url', '')}), {what}: {why}")
    if hidden:
        tally = {}
        for r in hidden:
            for x in r["reasons"]:
                tally[x] = tally.get(x, 0) + 1
        parts = ", ".join(f"{label(x)} {n}" for x, n in sorted(tally.items(), key=lambda kv: order(kv[0])))
        out.append("")
        out.append(f"And {len(hidden)} in private repositories (not named here, since this issue is public): {parts}.")

    # The four weeks.
    weeks = list(range(WEEKS - 1, -1, -1))
    per = {}
    for r in rows:
        for x in r["reasons"]:
            per.setdefault(x, [0] * WEEKS)[r["week"]] += 1
    out += ["", f"**The last {WEEKS} weeks, per reason** (a pull request with two reasons counts under each; the newest week includes what waits now)", ""]
    out.append("| Reason | " + " | ".join(f"since {day(i)}" for i in weeks) + " | Total |")
    out.append("| --- |" + " ---: |" * (WEEKS + 1))
    for x in sorted(per, key=order):
        out.append(f"| {label(x)} | " + " | ".join(str(per[x][i]) for i in weeks) + f" | {sum(per[x])} |")
    out.append("| **Pull requests** | " + " | ".join(str(sum(1 for r in rows if r["week"] == i)) for i in weeks) + f" | {len(rows)} |")

    repos = {}
    private = 0
    for r in rows:
        if public(r["pr"]):
            name = r["pr"]["repository"]["nameWithOwner"]
            repos[name] = repos.get(name, 0) + 1
        else:
            private += 1
    if rows:
        out += ["", "**Per repository**", "", "| Repository | Pull requests |", "| --- | ---: |"]
        out += [f"| {name} | {n} |" for name, n in sorted(repos.items(), key=lambda kv: (-kv[1], kv[0]))]
        if private:
            out.append(f"| Private repositories | {private} |")

    # The proposals: only from what the numbers show.
    props = []
    for x in sorted(per, key=order):
        n = sum(1 for r in rows if x in r["reasons"] and r["clean"])
        text = proposal(x, n) if n >= PROPOSE_AT else None
        if text:
            props.append(f"- {text}")
    out += ["", "**Proposals** (text only: nothing changes until a person accepts and merges a pull request)", ""]
    out += props or [f"None: no reason stopped {PROPOSE_AT} or more pull requests whose review found no blocker or major in {WEEKS} weeks."]
    return "\n".join(out) + "\n"


QUERY = """
query($q: String!, $endCursor: String) {
  search(query: $q, type: ISSUE, first: 25, after: $endCursor) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      number title url state isDraft mergedAt isCrossRepository additions deletions changedFiles
      repository { nameWithOwner visibility }
      author { __typename login }
      mergedBy { __typename login }
      autoMergeRequest { enabledAt }
      labels(first: 50) { nodes { name } }
      files(first: 100) { nodes { path additions deletions } }
      closingIssuesReferences(first: 5) { nodes { body labels(first: 20) { nodes { name } } } }
      early: comments(first: 50) { nodes { author { __typename login } body } }
      comments(last: 50) { nodes { author { __typename login } body } }
      commits(last: 1) { nodes { commit { statusCheckRollup { contexts(first: 100) { nodes {
        __typename
        ... on CheckRun { name conclusion }
        ... on StatusContext { context state }
      } } } } } }
    } }
  }
}
"""


def search(q):
    """Every pull request the search finds; a failing call fails the run
    instead of reporting an empty week."""
    out = subprocess.run(["gh", "api", "graphql", "--paginate", "-f", f"query={QUERY}", "-f", f"q={q}",
                          "--jq", ".data.search.nodes[] | @json"], check=True, capture_output=True, text=True).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def fetch(owner, now):
    since = (now - datetime.timedelta(days=7 * WEEKS)).strftime("%Y-%m-%d")
    return search(f"org:{owner} is:pr is:merged merged:>={since}") + search(f"org:{owner} is:pr is:open draft:false")


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        if got == want:
            print(f"ok   {name}")
        else:
            print(f"FAIL {name}: got {got!r}, want {want!r}")
            failed = 1

    with open(os.path.join(HERE, "fixtures", "needed-a-person.json"), encoding="utf-8") as fh:
        fx = json.load(fh)
    pol = policy()
    now = parse_time(fx["now"])

    def pr(case, **extra):
        p = json.loads(json.dumps(fx["base"]))
        p.update(json.loads(json.dumps(case.get("pr") or {})))
        p.update(extra)
        return p

    covered = set()
    for case in fx["cases"]:
        got = classify(pr(case), pol)
        covered.update(x.split(":", 1)[0] for x in got)
        check(f"C4: {case['name']}", got, case["want"])
    check("C4: every reason has a fixture", sorted(set(REASONS) - covered), [])

    # C1: what a person merged is listed with its reasons; what policy or
    # GitHub's auto-merge merged is not.
    cases = {c["name"]: c for c in fx["cases"]}
    size_case = "size cap (its failing conventions check is not a gate of its own)"
    mine = pr(cases["high risk from the review"], url="u-person", title="A person merged it")
    by_policy = pr(cases["high risk from the review"], url="u-policy", title="Merged by policy", labels={"nodes": [{"name": "merged-by:policy"}]})
    by_app = pr(cases["high risk from the review"], url="u-app", title="Auto-merged", mergedBy={"__typename": "Bot", "login": BOT})
    nothing = pr(cases["no reason recorded"], url="u-none", title="Nothing recorded")
    out = digest([mine, by_policy, by_app, nothing], pol, now)
    check("C1: a pull request a person merged is listed with its reason", "A person merged it (u-person), merged: high risk" in out, True)
    check("C1: one with no recorded reason says unknown", "Nothing recorded (u-none), merged: unknown" in out, True)
    check("C1: merged by policy is not listed", "Merged by policy" in out, False)
    check("C1: auto-merged by the App is not listed", "Auto-merged" in out, False)
    waiting = pr(cases["outside author"], url="u-wait", title="Waits", mergedAt=None, mergedBy=None, state="OPEN", isCrossRepository=True)
    check("C1: a pull request waiting on a person is listed as waiting", "Waits (u-wait), waiting: outside author" in digest([waiting], pol, now), True)
    queued = dict(waiting, autoMergeRequest={"enabledAt": fx["now"]})
    check("C1: one set to merge on its own is not waiting", "Waits" in digest([queued], pol, now), False)
    check("C1: an empty week says so", "Nothing in the organisation was merged by a person" in digest([], pol, now), True)

    # C2: a private repository is counted under its reasons, never named.
    secret = pr(cases[size_case], url="https://github.com/DiluxOne/secret-plugin/pull/7", title="Secret title",
                repository={"nameWithOwner": "DiluxOne/secret-plugin", "visibility": "PRIVATE"})
    internal = dict(secret, url="u-internal", repository={"nameWithOwner": "DiluxOne/internal-one", "visibility": "INTERNAL"})
    out = digest([secret, internal, mine], pol, now)
    check("C2: neither its name, its title nor its link appears", any(s in out for s in ("secret-plugin", "Secret title", "internal-one", "u-internal")), False)
    check("C2: it is counted under its reasons", "And 2 in private repositories (not named here, since this issue is public): size cap 2, outside author 2." in out, True)
    check("C2: per repository, only as a count", "| Private repositories | 2 |" in out, True)

    # C3: four weeks, per reason and per week; a proposal only from 5 or more
    # whose review found no blocker or major.
    def at(days, case, n, **extra):
        when = (now - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return pr(cases[case], url=f"u-{days}-{n}", title=f"t{n}", mergedAt=when, **extra)
    month = [at(d, size_case, i) for i, d in enumerate((1, 2, 9, 16, 23))]
    month += [at(d, "high risk from the review", i) for i, d in enumerate((3, 10, 11, 12))]
    month += [at(40, size_case, 99)]
    out = digest(month, pol, now)
    check("C3: totals per reason and per week", "| size cap | 1 | 1 | 1 | 2 | 5 |" in out, True)
    check("C3: a reason in some weeks only", "| high risk | 0 | 0 | 3 | 1 | 4 |" in out, True)
    check("C3: the pull requests per week", "| **Pull requests** | 1 | 1 | 4 | 3 | 9 |" in out, True)
    check("C3: a proposal for a reason with 5 clean reviews", "The size cap stopped 5 pull requests" in out, True)
    check("C3: none for a reason with 4", "high risk stopped" in out, False)
    major = '<!-- dx-review -->\nx\n<!-- dx-review-record {"risk":"low","complexity":"low","floor":"low","blocking":false,"findings":[{"severity":"major","file":"a","title":"t"}]} -->'
    dirty = [dict(p, comments={"nodes": [{"author": {"__typename": "Bot", "login": BOT}, "body": major}]}) for p in month]
    check("C3: none when the reviews found a major", "The size cap stopped" in digest(dirty, pol, now), False)
    check("C3: the proposal is text only and says a person merges", "accepts and merges" in out, True)
    check("C3: no proposal says so", "None: no reason stopped 5" in digest([mine], pol, now), True)
    check("C3: the per-repository totals", "| DiluxOne/diluxone-offload-wordpress | 9 |" in out, True)

    if not failed:
        print("all tests passed")
    return failed


def main(argv):
    if argv[:1] == ["--test"]:
        return self_test()
    if argv[:1] == ["classify"] and len(argv) == 2:
        pol = policy()
        with open(argv[1], encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    pr = json.loads(line)
                    print(f"{pr.get('url', '')}: {', '.join(classify(pr, pol))}")
        return 0
    if argv:
        print(__doc__, file=sys.stderr)
        return 64
    now = parse_time(os.environ["NOW"]) if os.environ.get("NOW") else datetime.datetime.now(datetime.timezone.utc)
    sys.stdout.write(digest(fetch(os.environ["OWNER"], now), policy(), now))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
