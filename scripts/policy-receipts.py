#!/usr/bin/env python3
"""The policy's labels onto the receipts (#804, C3).

What the policy decided in a person's place was once a label anyone with
write access could add or take off: `lane:<name>` with `accepted-by:policy`
on an issue a lane accepted, `merged-by:policy` on a pull request the policy
merged. It is now a record on the repository's receipts branch, which only
dilux-bot writes (scripts/receipts.py: a lane decision, a merge decision).
This moves what the labels said onto the receipts, once, in every
repository of repos.yml but its `exclude` list:

  - every open issue and pull request carrying one of these labels gets the
    matching record, written from the label's last LabeledEvent (who added
    it, when, the policy's commit in force then, `migrated_from` the
    label); the record is read back, and only then is the label taken off.
    A write or a read-back that fails leaves the label on, and the run says
    so (exit 1);
  - every one closed in the last DAYS days (28: needed-a-person.py's WEEKS
    weeks, the longest window a digest reads) gets its record too and
    keeps its labels, so the digests after the migration still list the
    decisions of the weeks they read;
  - an item whose receipts already hold the proof (its lane decision in
    force is that lane; its merge decision in force is for its head) gets
    no new record: a second run writes nothing and takes nothing off.

The labels it moves, as the maintainer answered: `accepted-by:policy` on an
issue whose one `lane:<name>` is a lane that accepts by policy in
policy/autonomy.yml, and `merged-by:policy` on a pull request. The lane's
label stays: it routes (security-patch.yml and sync-repos.py add it, the
`if:` routes fire on it), and autonomy.py reads its LabeledEvent as the
lane's evidence. A planned release (`lane:release`, opened by dilux-bot,
`accepted-by:policy` added by dilux-bot) gets the plan's lane decision by
policy/autonomy.yml#planned-release, which release-issue.py verify now
reads. `accepted-by:policy` with neither (a lane that refused, more than
one lane) and `merged-by:policy` on an issue prove no decision: they stay,
unless the receipts already hold a lane in force, and the run lists them.

  policy-receipts.py migrate [--apply]
                           a dry run unless --apply: says what it would
                           write and take off, and changes nothing
  policy-receipts.py --test
                           self-test

Run by autonomy.py's `migrate-policy-labels` verb, from
.github/workflows/policy-receipts.yml (workflow_dispatch, main only).

Environment: GH_TOKEN (dilux-bot's App token: issues and pull requests
write, contents write for the receipts branches); OWNER (default the
organisation of org.yml); REPOS (names, space-separated; default every
repository of repos.yml but its exclude list).
"""
import datetime
import importlib.util
import json
import os
import subprocess
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import org  # noqa: E402

_spec = importlib.util.spec_from_file_location("receipts", os.path.join(HERE, "receipts.py"))
receipts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(receipts)
_spec = importlib.util.spec_from_file_location("needed_a_person", os.path.join(HERE, "needed-a-person.py"))
needed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(needed)

ACCEPTED = "accepted-by:policy"
MERGED = "merged-by:policy"
# The closed items it records: the window needed-a-person.py reads (WEEKS),
# so no pull request merged by policy in it counts as a person's merge for
# want of a record; the weekly digest's week is within it.
DAYS = 7 * needed.WEEKS
REVIEW_RULE = ".github/review-policy.yml#auto-merge"


# --- what the labels said, and what goes on the receipts (pure, tested) -----

def policy_lanes(policy):
    """The lanes that accept by policy, read from policy/autonomy.yml."""
    return sorted(n for n, lane in ((policy or {}).get("lanes") or {}).items()
                  if isinstance(lane, dict) and lane.get("accept") == "policy")


def labels_to_find(lanes):
    return [ACCEPTED, MERGED]


PLANNED_RULE = "policy/autonomy.yml#planned-release"
BOTS = {org.APP, org.BOT, f"{org.APP}[bot]", f"app/{org.APP}"}


def proofs(item, lanes):
    """What ITEM's labels say the policy decided: ([(kind, lane, labels)],
    [why a label is left]). kind is "lane" or "merge"."""
    labels = set(item.get("labels") or [])
    found, left = [], []
    if item.get("is_pr"):
        if MERGED in labels:
            found.append(("merge", None, [MERGED]))
        for label in sorted(labels & ({ACCEPTED} | {f"lane:{n}" for n in lanes})):
            left.append(f"{label} on a pull request proves no lane's decision")
        return found, left
    mine = sorted(n for n in lanes if f"lane:{n}" in labels)
    adder = ((item.get("events") or {}).get(ACCEPTED) or {}).get("by") or ""
    if ACCEPTED in labels and len(mine) == 1:
        found.append(("lane", mine[0], [ACCEPTED]))
    elif ACCEPTED in labels and len(mine) > 1:
        left.append("two policy lanes: " + ", ".join(f"lane:{n}" for n in mine))
    elif ACCEPTED in labels and "lane:release" in labels and item.get("author") in BOTS and adder in BOTS:
        # A planned release (#247): the plan's acceptance.
        found.append(("plan", "release", [ACCEPTED]))
    elif ACCEPTED in labels:
        # No lane that accepts by policy, unless the receipts hold one in
        # force already (migrate_item).
        found.append(("rest", None, [ACCEPTED]))
    if MERGED in labels:
        left.append(f"{MERGED} on an issue proves no merge")
    return found, left


def evidence(item, labels):
    events = item.get("events") or {}
    return {"migrated": {l: events.get(l) for l in labels}}


def lane_record(item, lane, labels, policy_ref, run, rule=None):
    """The lane decision a migrated issue gets: when, and by whom, its lane's
    acceptance (`accepted-by:policy`) was labelled; its evidence the lane's
    label's last event too, the label that stays."""
    events = item.get("events") or {}
    ev = events.get(ACCEPTED) or {}
    at = ev.get("at") or item.get("created_at")
    rec = receipts.lane_decision(item["number"], lane, policy_ref, at, run, evidence(item, [f"lane:{lane}"] + list(labels)), rule=rule)
    rec["decided_by"] = ev.get("by") or "?"
    rec["migrated_from"] = ACCEPTED
    return rec


def merge_record(item, rule, policy_ref, run):
    ev = (item.get("events") or {}).get(MERGED) or {}
    at = ev.get("at") or item.get("created_at")
    rec = receipts.merge_decision(item["number"], "policy", rule, item.get("head"), policy_ref, at, run)
    rec["decided_by"] = ev.get("by") or "?"
    rec["migrated_from"] = MERGED
    rec["evidence"] = evidence(item, [MERGED])
    return rec


def merge_rule(io, repo, item, lanes):
    """The rule a migrated merge decision names: the lane of an issue it
    closes (its label, else its lane decision in force), else the review
    policy's auto-merge."""
    for issue in item.get("closes") or []:
        lane = next((l[len("lane:"):] for l in issue.get("labels") or [] if l.startswith("lane:") and l[len("lane:"):] in lanes), None)
        if not lane:
            in_force = receipts.lane_in_force(io.lane_decisions(repo, issue["number"]))
            lane = in_force.get("lane") if in_force else None
        if lane:
            return f"policy/autonomy.yml#lanes.{lane}.merge"
    return REVIEW_RULE


def migrate_item(io, repo, item, lanes, apply):
    """One item: each proof its labels carry written onto its receipts,
    read back, and only then, on an open item, its labels taken off.
    Returns [(outcome, text)]: outcome one of migrated, recorded (closed:
    written, labels kept), proven (already on the receipts), would (dry
    run), left, failed."""
    n, is_pr = item["number"], item.get("is_pr")
    name = f"{repo}#{n}"
    found, left = proofs(item, lanes)
    out = [("left", f"{name}: {why}; its label stays") for why in left]
    is_open = item.get("state") == "open"
    for kind, lane, labels in found:
        what = ", ".join(labels)
        if kind == "rest":
            # accepted-by:policy with no policy lane's label: taken off only
            # when the receipts already hold a policy lane's acceptance.
            try:
                in_force = receipts.lane_in_force(io.lane_decisions(repo, n))
            except Exception as e:  # noqa: BLE001
                out.append(("failed", f"{name}: its receipts could not be read ({e}); {what} stays"))
                continue
            if not in_force or in_force.get("lane") not in lanes:
                why = f"{ACCEPTED} with no lane that accepts by policy"
                out.append(("left", f"{name}: {why}; its label stays"))
            elif not is_open:
                out.append(("proven", f"{name} ({item.get('state')}): already on its receipts; {what} kept"))
            elif not apply:
                out.append(("would", f"{name}: already on its receipts; would take off {what}"))
            else:
                try:
                    for label in labels:
                        io.remove_label(repo, n, label)
                except Exception as e:  # noqa: BLE001
                    out.append(("failed", f"{name}: on its receipts, but {what} could not be taken off ({e})"))
                    continue
                out.append(("migrated", f"{name}: {what} taken off, already on its receipts"))
            continue
        try:
            if kind in ("lane", "plan"):
                in_force = receipts.lane_in_force(io.lane_decisions(repo, n))
                have = bool(in_force and in_force.get("lane") == lane and (kind == "lane" or in_force.get("rule") == PLANNED_RULE))
            else:
                have = bool(receipts.merge_in_force(io.merge_decisions(repo, n), item.get("head")))
        except Exception as e:  # noqa: BLE001 — unread is never "already proven"
            out.append(("failed", f"{name}: its receipts could not be read ({e}); {', '.join(labels)} stay"))
            continue
        if not have:
            if kind in ("lane", "plan"):
                at = ((item.get("events") or {}).get(ACCEPTED) or {}).get("at") or item.get("created_at")
                rec = lane_record(item, lane, labels, io.policy_at(at), io.run(), PLANNED_RULE if kind == "plan" else None)
                path = f"issues/{n}/lane-{io.now()}.json"
            else:
                if not item.get("head"):
                    out.append(("failed", f"{name}: no head commit to decide; {what} stays"))
                    continue
                at = ((item.get("events") or {}).get(MERGED) or {}).get("at") or item.get("created_at")
                try:
                    rule = merge_rule(io, repo, item, lanes)
                except Exception as e:  # noqa: BLE001
                    out.append(("failed", f"{name}: the lane of the issue it closes could not be read ({e}); {what} stays"))
                    continue
                rec = merge_record(item, rule, io.policy_at(at), io.run())
                path = f"pulls/{n}/merge-{io.now()}.json"
            if not apply:
                out.append(("would", f"{name}: would write {path} from {what}" + ("" if not is_open else f", then take off {what}")))
                continue
            try:
                io.write(repo, path, rec)
                back = io.read(repo, path)
            except Exception as e:  # noqa: BLE001
                out.append(("failed", f"{name}: {path} could not be written or read back ({e}); {what} stay"))
                continue
            if back != rec:
                out.append(("failed", f"{name}: {path} does not read back as written; {what} stay"))
                continue
        elif not apply:
            out.append(("would", f"{name}: already on its receipts" + (f"; would take off {what}" if is_open else "")))
            continue
        if not is_open:
            out.append(("recorded" if not have else "proven", f"{name} ({item.get('state')}): " + ("recorded" if not have else "already on its receipts") + f"; {what} kept"))
            continue
        try:
            for label in labels:
                io.remove_label(repo, n, label)
        except Exception as e:  # noqa: BLE001
            out.append(("failed", f"{name}: on its receipts, but {what} could not be taken off ({e})"))
            continue
        out.append(("migrated", f"{name}: {what} " + ("moved onto its receipts" if not have else "taken off, already on its receipts")))
    return out


def migrate(io, repos, lanes, since, apply):
    """Every repository's items; the lines to print and whether one failed."""
    lines, failed = [], False
    for repo in repos:
        try:
            items = io.items(repo, labels_to_find(lanes), since)
        except Exception as e:  # noqa: BLE001
            lines.append(f"failed: {repo}: its items could not be listed ({e})")
            failed = True
            continue
        # Pull requests first: a merge decision's rule reads the lane of
        # the issue it closes, from its label while it still has one.
        for item in sorted(items, key=lambda i: (not i.get("is_pr"), i["number"])):
            for outcome, text in migrate_item(io, repo, item, lanes, apply):
                lines.append(f"{outcome}: {text}")
                failed = failed or outcome == "failed"
    return lines, failed


# --- GitHub ------------------------------------------------------------------

ITEM_FIELDS = """number state createdAt author{login} labels(first:50){nodes{name}}
timelineItems(itemTypes:[LABELED_EVENT],last:100){nodes{... on LabeledEvent{createdAt label{name} actor{login}}}}"""
SEARCH = ("query($q:String!,$after:String){search(query:$q,type:ISSUE,first:50,after:$after){pageInfo{hasNextPage endCursor}"
          "nodes{__typename ... on Issue{" + ITEM_FIELDS + "} ... on PullRequest{" + ITEM_FIELDS
          + " headRefOid closingIssuesReferences(first:10){nodes{number labels(first:50){nodes{name}}}}}}}}")


def item_of(node):
    """A search result as migrate_item reads it: the last LabeledEvent of
    each label, who and when."""
    events = {}
    for e in ((node.get("timelineItems") or {}).get("nodes") or []):
        label = ((e or {}).get("label") or {}).get("name")
        if label:
            events[label] = {"by": ((e.get("actor") or {}).get("login")), "at": e.get("createdAt")}
    names = lambda n: [l.get("name") for l in ((n.get("labels") or {}).get("nodes") or [])]
    return {"number": node["number"], "is_pr": node.get("__typename") == "PullRequest",
            "state": (node.get("state") or "").lower() if node.get("state") == "OPEN" else "closed",
            "created_at": node.get("createdAt"), "author": (node.get("author") or {}).get("login"), "labels": names(node), "events": events, "head": node.get("headRefOid"),
            "closes": [{"number": c["number"], "labels": names(c)} for c in ((node.get("closingIssuesReferences") or {}).get("nodes") or [])]}


def gh(*args):
    out = subprocess.run(["gh", "api", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:300])
    return json.loads(out.stdout) if out.stdout.strip() else {}


class GitHub:
    def __init__(self, policy_dir):
        self.policy_dir = policy_dir

    def items(self, repo, labels, since):
        wanted = ",".join(f'"{l}"' for l in labels)
        found = {}
        for q in (f"repo:{repo} is:open label:{wanted}", f"repo:{repo} is:closed closed:>={since} label:{wanted}"):
            after = None
            while True:
                args = ["graphql", "-f", f"query={SEARCH}", "-f", f"q={q}"] + (["-f", f"after={after}"] if after else [])
                page = gh(*args)["data"]["search"]
                for node in page["nodes"]:
                    if node and node.get("number"):
                        found[node["number"]] = item_of(node)
                if not page["pageInfo"]["hasNextPage"]:
                    break
                after = page["pageInfo"]["endCursor"]
        return list(found.values())

    def lane_decisions(self, repo, n):
        return receipts.lane_decisions(repo, n)

    def merge_decisions(self, repo, n):
        return receipts.merge_decisions(repo, n)

    def write(self, repo, path, obj):
        receipts.write(repo, path, obj, f"#{obj.get('issue') or obj.get('pull_request')}: {obj.get('migrated_from')} onto the receipts (#804)")

    def read(self, repo, path):
        return receipts.read(repo, path)

    def remove_label(self, repo, n, label):
        try:
            gh("-X", "DELETE", f"repos/{repo}/issues/{n}/labels/{urllib.parse.quote(label, safe='')}")
        except RuntimeError as e:
            if "404" not in str(e) and "Not Found" not in str(e):  # already off
                raise

    def policy_at(self, at):
        """The last commit to change policy/autonomy.yml before AT: the
        policy in force when the label was added; None when git cannot say."""
        out = subprocess.run(["git", "-C", self.policy_dir, "log", "-1", "--format=%H", f"--before={at}", "--", "policy/autonomy.yml"],
                             capture_output=True, text=True)
        sha = out.stdout.strip()
        return sha if out.returncode == 0 and len(sha) == 40 else None

    def run(self):
        return receipts.run_url()

    def now(self):
        return receipts.now()


def adopted(conf):
    repos = conf.get("repos") if isinstance(conf.get("repos"), dict) else {}
    skip = set(conf.get("exclude") or [])
    return [n for n in repos if n not in skip]


# --- self-test ---------------------------------------------------------------

class Fake:
    """The receipts branch, the labels and the clock, in memory."""

    def __init__(self, items, files=None, fail_write=False, bad_read=False):
        self.items_ = items
        self.files = dict(files or {})
        self.fail_write, self.bad_read = fail_write, bad_read
        self.log = []
        self.tick = 0

    def items(self, repo, labels, since):
        self.log.append(("items", repo, since))
        return [i for i in self.items_ if i.get("state") == "open" and set(i["labels"]) & set(labels)
                or i.get("state") == "closed" and (i.get("closed_at") or "") >= since and set(i["labels"]) & set(labels)]

    def _decisions(self, repo, prefix):
        return [self.files[p] for p in sorted(self.files) if p.startswith(f"{repo}/{prefix}")]

    def lane_decisions(self, repo, n):
        return self._decisions(repo, f"issues/{n}/lane-")

    def merge_decisions(self, repo, n):
        return self._decisions(repo, f"pulls/{n}/merge-")

    def write(self, repo, path, obj):
        self.log.append(("write", repo, path))
        if self.fail_write:
            raise RuntimeError("HTTP 500")
        if f"{repo}/{path}" in self.files:
            raise RuntimeError("exists")
        self.files[f"{repo}/{path}"] = json.loads(json.dumps(obj))

    def read(self, repo, path):
        self.log.append(("read", repo, path))
        got = json.loads(json.dumps(self.files[f"{repo}/{path}"]))
        if self.bad_read:
            got["lane" if "lane" in got else "head"] = "else"
        return got

    def remove_label(self, repo, n, label):
        # Taken off only once its proof reads back from the receipts.
        self.log.append(("remove", repo, n, label))
        item = next(i for i in self.items_ if i["number"] == n)
        item["labels"] = [l for l in item["labels"] if l != label]

    def policy_at(self, at):
        return "a" * 40

    def run(self):
        return "https://github.com/DiluxOne/.github/actions/runs/1"

    def now(self):
        self.tick += 1
        return f"2026-11-17T10:00:{self.tick:02d}Z"


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        if got != want:
            failed += 1
            print(f"FAIL {name}: {got!r} != {want!r}")

    policy = {"lanes": {"platform": {"accept": "policy"}, "bugfix-reproduced": {"accept": "policy"}, "release": {"accept": "human"},
                        "adopt": {"accept": "human"}, "org-sync": {"accept": "policy"}}}
    lanes = policy_lanes(policy)
    check("the lanes that accept by policy, from the policy", lanes, ["bugfix-reproduced", "org-sync", "platform"])
    check("the labels it looks for: only the policy's two; a lane's label is no decision", labels_to_find(lanes), [ACCEPTED, MERGED])
    check("C2: the closed items it records cover the digest's whole window (needed-a-person.py's WEEKS)", DAYS, 7 * needed.WEEKS)
    R = "DiluxOne/x"

    def issue(n, labels, state="open", closed_at=None):
        return {"number": n, "is_pr": False, "state": state, "closed_at": closed_at, "created_at": "2026-11-10T08:00:00Z", "labels": list(labels),
                "events": {l: {"by": "dilux-bot", "at": f"2026-11-1{n % 10}T09:00:00Z"} for l in labels}, "head": None, "closes": []}

    def pull(n, labels, closes=(), state="open", closed_at=None):
        d = issue(n, labels, state, closed_at)
        d.update(is_pr=True, head="c0ffee", closes=list(closes))
        return d

    def removes(fake):
        return [e for e in fake.log if e[0] == "remove"]

    # C3: the record is written and read back before the label is removed.
    items = [issue(1, ["lane:platform", ACCEPTED, "type:task"]), pull(2, [MERGED], closes=[{"number": 1, "labels": ["lane:platform", ACCEPTED]}])]
    fake = Fake(items)
    lines, bad = migrate(fake, [R], lanes, "2026-11-10", True)
    check("C3: nothing failed", (bad, [l for l in lines if l.startswith("failed")]), (False, []))
    for n, path in ((1, "issues/1/lane-"), (2, "pulls/2/merge-")):
        w = next(i for i, e in enumerate(fake.log) if e[0] == "write" and e[2].startswith(path))
        r = next(i for i, e in enumerate(fake.log) if e[0] == "read" and e[2].startswith(path))
        rm = [i for i, e in enumerate(fake.log) if e[0] == "remove" and e[2] == n]
        check(f"C3: #{n} written, read back, then its labels taken off", bool(rm) and w < r < min(rm), True)
    check("C3: the labels it moved are off; the lane's label, which routes, and the others stay", [i["labels"] for i in items], [["lane:platform", "type:task"], []])
    lane = receipts.lane_in_force(fake.lane_decisions(R, 1))
    check("C3: the lane decision names the lane, the rule, who and when",
          (lane["lane"], lane["rule"], lane["decided"], lane["decided_by"], lane["at"], lane["migrated_from"], lane["policy"]),
          ("platform", "policy/autonomy.yml#lanes.platform", "policy", "dilux-bot", "2026-11-11T09:00:00Z", ACCEPTED, "DiluxOne/.github@" + "a" * 40))
    check("C3: its evidence is the labels' last adders", lane["evidence"]["migrated"][ACCEPTED], {"by": "dilux-bot", "at": "2026-11-11T09:00:00Z"})
    merge = receipts.merge_in_force(fake.merge_decisions(R, 2), "c0ffee")
    check("C3: the merge decision is for its head, by its issue's lane",
          (merge["rule"], merge["decided"], merge["migrated_from"], merge["at"]),
          ("policy/autonomy.yml#lanes.platform.merge", "policy", MERGED, "2026-11-12T09:00:00Z"))
    check("C3: a merge with no lane's issue names the review policy",
          merge_rule(Fake([]), R, pull(3, [MERGED]), lanes), REVIEW_RULE)
    check("C3: the issue's lane is read from its receipts once its label is off",
          merge_rule(fake, R, pull(4, [MERGED], closes=[{"number": 1, "labels": []}]), lanes), "policy/autonomy.yml#lanes.platform.merge")
    check("C3: the digest reads the migrated records",
          sorted((r["kind"], r["number"]) for r in receipts.decision_rows(
              [p[len(R) + 1:] for p in fake.files], lambda p: fake.files[f"{R}/{p}"], "2026-11-10")),
          [("accepted", 1), ("merged", 2)])

    # A second run is a no-op.
    before = (dict(fake.files), [list(i["labels"]) for i in items])
    fake.log.clear()
    lines, bad = migrate(fake, [R], lanes, "2026-11-10", True)
    check("C3: a second run writes nothing and takes nothing off",
          ([e for e in fake.log if e[0] in ("write", "remove")], (fake.files, [i["labels"] for i in items]), bad), ([], before, False))

    # A failed write or read-back leaves the label on.
    for what, fake in (("write", Fake([issue(5, ["lane:platform", ACCEPTED])], fail_write=True)),
                       ("read-back", Fake([issue(5, ["lane:platform", ACCEPTED])], bad_read=True))):
        lines, bad = migrate(fake, [R], lanes, "2026-11-10", True)
        check(f"C3: a failed {what} leaves the labels on and fails the run",
              (removes(fake), fake.items_[0]["labels"], bad, any(l.startswith("failed: DiluxOne/x#5") for l in lines)),
              ([], ["lane:platform", ACCEPTED], True, True))
    fake = Fake([pull(6, [MERGED])])
    fake.lane_decisions = fake.merge_decisions = lambda repo, n: (_ for _ in ()).throw(RuntimeError("HTTP 502"))
    lines, bad = migrate(fake, [R], lanes, "2026-11-10", True)
    check("C3: unreadable receipts are never taken for a proof", (removes(fake), bad), ([], True))

    # Recently closed items get a record and keep their label.
    fake = Fake([issue(7, ["lane:org-sync", ACCEPTED], "closed", "2026-11-12"), pull(8, [MERGED], state="closed", closed_at="2026-11-13"),
                 issue(9, ["lane:org-sync", ACCEPTED], "closed", "2026-11-01")])
    lines, bad = migrate(fake, [R], lanes, "2026-11-10", True)
    check("C3: closed in the window: recorded, labels kept",
          (sorted(p for p in fake.files), removes(fake), [i["labels"] for i in fake.items_][:2], bad),
          ([f"{R}/issues/7/lane-2026-11-17T10:00:02Z.json", f"{R}/pulls/8/merge-2026-11-17T10:00:01Z.json"], [],
           [["lane:org-sync", ACCEPTED], [MERGED]], False))
    check("C3: closed before the window: untouched", any("#9" in l for l in lines), False)
    fake.log.clear()
    migrate(fake, [R], lanes, "2026-11-10", True)
    check("C3: a closed one is recorded once", [e for e in fake.log if e[0] == "write"], [])

    # The dry run changes nothing.
    items = [issue(10, ["lane:platform", ACCEPTED]), pull(11, [MERGED]), issue(12, ["lane:bugfix-reproduced", ACCEPTED], "closed", "2026-11-12")]
    fake = Fake(items)
    lines, bad = migrate(fake, [R], lanes, "2026-11-10", False)
    check("C3: the dry run writes nothing and takes nothing off",
          ([e for e in fake.log if e[0] in ("write", "remove")], fake.files, [i["labels"] for i in items]),
          ([], {}, [["lane:platform", ACCEPTED], [MERGED], ["lane:bugfix-reproduced", ACCEPTED]]))
    check("C3: the dry run says what it would do", sum(l.startswith("would: ") for l in lines), 3)

    # An open item whose proof is already on the receipts only loses its labels.
    fake = Fake([issue(13, ["lane:platform", ACCEPTED])],
                {f"{R}/issues/13/lane-2026-11-16T00:00:00Z.json": receipts.lane_decision(13, "platform", "b", "2026-11-16T00:00:00Z", None, None)})
    migrate(fake, [R], lanes, "2026-11-10", True)
    check("C3: already proven: no new record, accepted-by:policy off, the lane's label kept",
          ([e for e in fake.log if e[0] == "write"], fake.items_[0]["labels"]), ([], ["lane:platform"]))
    withdrawn = receipts.lane_decision(14, "platform", "b", "2026-11-16T00:00:00Z", None, None, "withdrawn")
    fake = Fake([issue(14, ["lane:platform", ACCEPTED])], {f"{R}/issues/14/lane-2026-11-16T00:00:00Z.json": withdrawn})
    migrate(fake, [R], lanes, "2026-11-10", True)
    check("C3: a withdrawn decision is no proof: a record is written", len([e for e in fake.log if e[0] == "write"]), 1)

    # A run that wrote the record and failed to take the label off: the
    # next one takes it off, from the receipts.
    class HalfOff(Fake):
        def remove_label(self, repo, n, label):
            if label == ACCEPTED and not getattr(self, "healed", False):
                raise RuntimeError("HTTP 502")
            super().remove_label(repo, n, label)
    fake = HalfOff([issue(15, ["lane:platform", ACCEPTED])])
    lines, bad = migrate(fake, [R], lanes, "2026-11-10", True)
    check("C3: a label that could not be taken off fails the run, its record kept",
          (bad, fake.items_[0]["labels"], len(fake.lane_decisions(R, 15))), (True, ["lane:platform", ACCEPTED], 1))
    fake.healed = True
    fake.log.clear()
    lines, bad = migrate(fake, [R], lanes, "2026-11-10", True)
    check("C3: the next run takes it off and writes nothing",
          (bad, fake.items_[0]["labels"], [e for e in fake.log if e[0] == "write"]), (False, ["lane:platform"], []))
    # accepted-by:policy alone, whose receipts hold a policy lane in force: taken off.
    fake = Fake([issue(16, [ACCEPTED])], {f"{R}/issues/16/lane-2026-11-16T00:00:00Z.json": receipts.lane_decision(16, "org-sync", "b", "2026-11-16T00:00:00Z", None, None)})
    lines, bad = migrate(fake, [R], lanes, "2026-11-10", True)
    check("C3: accepted-by:policy alone, a policy lane in force on the receipts: taken off, nothing written",
          (bad, fake.items_[0]["labels"], [e for e in fake.log if e[0] == "write"]), (False, [], []))
    # A planned release in flight (#247): the plan's decision, then the label off; lane:release stays.
    plan = dict(issue(17, ["lane:release", ACCEPTED]), author="dilux-bot")
    fake = Fake([plan])
    lines, bad = migrate(fake, [R], lanes, "2026-11-10", True)
    got = fake.lane_decisions(R, 17)
    check("C3: a planned release gets the plan's lane decision before accepted-by:policy comes off",
          (bad, plan["labels"], [(d["lane"], d["rule"], d["migrated_from"], d["decided_by"]) for d in got]),
          (False, ["lane:release"], [("release", PLANNED_RULE, ACCEPTED, "dilux-bot")]))
    check("C3: a planned release the receipts already hold writes nothing more", (migrate(Fake([dict(plan, labels=["lane:release", ACCEPTED])], dict(fake.files)), [R], lanes, "2026-11-10", True)[1]), False)

    # What proves no lane's decision stays, and is said.
    cases = [(issue(20, [ACCEPTED, "lane:release"]), "no lane that accepts by policy"),
             (dict(issue(21, [ACCEPTED, "lane:release"]), author="someone"), "no lane that accepts by policy"),
             (issue(22, ["lane:platform", "lane:org-sync", ACCEPTED]), "two policy lanes"),
             (issue(23, [MERGED]), "proves no merge"),
             (pull(24, [ACCEPTED]), "on a pull request proves no lane's decision")]
    for item, why in cases:
        fake = Fake([item])
        labels = list(item["labels"])
        lines, bad = migrate(fake, [R], lanes, "2026-11-10", True)
        check(f"left: {why}", (fake.files, item["labels"], any(why in l and l.startswith("left: ") for l in lines), bad), ({}, labels, True, False))

    # What GitHub returns, read.
    node = {"__typename": "PullRequest", "number": 30, "state": "MERGED", "createdAt": "t0", "headRefOid": "abc",
            "labels": {"nodes": [{"name": MERGED}]},
            "timelineItems": {"nodes": [{"createdAt": "t1", "label": {"name": MERGED}, "actor": {"login": "a"}},
                                        {"createdAt": "t2", "label": {"name": MERGED}, "actor": {"login": "dilux-bot"}}, {}]},
            "closingIssuesReferences": {"nodes": [{"number": 29, "labels": {"nodes": [{"name": "lane:org-sync"}]}}]}}
    check("item_of: the label's last adder, the head, the issues it closes", item_of(node),
          {"number": 30, "is_pr": True, "state": "closed", "created_at": "t0", "author": None, "labels": [MERGED],
           "events": {MERGED: {"by": "dilux-bot", "at": "t2"}}, "head": "abc", "closes": [{"number": 29, "labels": ["lane:org-sync"]}]})
    check("item_of: an open issue", item_of({"__typename": "Issue", "number": 1, "state": "OPEN"})["state"], "open")
    check("adopted: repos.yml's repositories but its exclude list",
          adopted({"repos": {".github": {}, "a": {}, "b": {}}, "exclude": ["b"]}), [".github", "a"])
    print("all tests passed" if not failed else f"{failed} failed")
    return 1 if failed else 0


def main(argv):
    if argv[:1] == ["--test"]:
        return self_test()
    if argv[:1] != ["migrate"] or any(a not in ("--apply",) for a in argv[1:]):
        print(__doc__, file=sys.stderr)
        return 64
    apply = "--apply" in argv
    import autonomy  # noqa: E402  its YAML reader
    root = os.path.join(HERE, "..")
    lanes = policy_lanes(autonomy.load(os.path.join(root, "policy", "autonomy.yml")))
    owner = os.environ.get("OWNER") or org.ORG
    names = os.environ.get("REPOS", "").split() or adopted(autonomy.load(os.path.join(root, "repos.yml")))
    since = (datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=DAYS)).isoformat()
    print(("Moving" if apply else "Dry run: would move") + f" {', '.join(labels_to_find(lanes))} onto the receipts, in {len(names)} repositories, open or closed since {since}.")
    lines, failed = migrate(GitHub(root), [f"{owner}/{n}" for n in names], lanes, since, apply)
    for line in lines:
        print(line)
    counts = {}
    for line in lines:
        counts[line.split(":", 1)[0]] = counts.get(line.split(":", 1)[0], 0) + 1
    print("Done: " + (", ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "nothing carried these labels") + ".")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
