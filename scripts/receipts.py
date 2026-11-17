#!/usr/bin/env python3
"""Receipts (#81): what was accepted, sealed; what was merged, proven.

Every seal and every receipt is a JSON file that dilux-bot commits to the
repository's `receipts` branch: an orphan branch (no history shared with the
code) that an organisation ruleset lets only dilux-bot create or update and
nobody delete or rewrite. A GitHub App's commits made through the API are
signed by GitHub and show as Verified.

  receipts.py seal-prd     on acceptance: the PRD's SHA-256 and its text (#588),
                           who accepted, when (issues/<n>/prd-<UTC>.json)
  receipts.py seal-spec    at G3, when the autopilot wrote the Spec: its SHA-256
                           (issues/<n>/spec-<UTC>.json)
  receipts.py verify-spec  the Spec now against its seal: exit 0 only on "match"
                           (an autopilot merge needs the Spec it sealed)
  receipts.py verify-prd   the PRD now against its last seal: prints "match",
                           "changed" or "unsealed"; exit 1 when changed, 2 when
                           the seal could not be read (never taken as unsealed).
                           With --wait N: up to N tries, 10 seconds apart,
                           while it is "unsealed" or "changed", for the seal
                           of an acceptance that runs alongside (a
                           re-acceptance meets the old seal first, #353)
  receipts.py sealed-prd   the PRD's text as its last seal sealed it (#588):
                           the seal's own, else the issue's edit whose PRD
                           has the sealed hash (EDITS_JSON, a list of bodies,
                           stands in for the edit history); exit 1, printing
                           nothing, when neither has it, 2 when the seal
                           could not be read
  receipts.py merged       when the issue closes as completed: the receipt
                           (issues/<n>/merged-<UTC>.json; a reopened and
                           merged-again issue gets another): PRD and Spec hashes, the
                           pull request, its head commit, its checks, the
                           review's verdict, the criteria, the policy's commit,
                           who accepted and who merged: "policy" only from
                           the pull request's last merge decision, for the
                           head that merged (#804), never from a label; with
                           the lane in force, its rule, when it accepted and
                           the merge's rule
  receipts.py lane-decision
                           a lane's decision on the issue (#804;
                           issues/<n>/lane-<UTC>.json): LANE accepted it by
                           policy (DECIDED=policy, the default), with the
                           rule (policy/autonomy.yml#lanes.<LANE>), the
                           policy's commit, when, the run (RUN, else this
                           run's URL), EVIDENCE_JSON and RULE when another
                           rule decided (a planned release's
                           policy/autonomy.yml#planned-release); DECIDED=withdrawn
                           when the lane later refused it (nothing is
                           written when no lane is in force)
  receipts.py merge-decision
                           the policy's decision to merge pull request PR at
                           HEAD by RULE (the lane's `merge`, or the review
                           policy's auto-merge; pulls/<pr>/merge-<UTC>.json),
                           or DECIDED=withdrawn (nothing is written when no
                           decision is in force)
  receipts.py lane [get]   the lane in force, as JSON: exit 0 with it, 1
                           (null) with none or a withdrawn one, 2 when the
                           receipts could not be read (never taken as a lane)
  receipts.py decisions --since YYYY-MM-DD
                           what the policy decided, for the weekly digest
                           (#804): one JSON line per issue a lane accepted
                           since then, and per pull request whose last merge
                           decision is the policy's (from a week earlier:
                           the reader keeps what merged since, at the head
                           decided); exit 2 when the receipts could not be
                           read (never an empty week)
  receipts.py own-bug      whether the last seal accepted a maintainer's own
                           Bug with its writing (#564): sealed so, by the
                           issue's author (AUTHOR), and the PRD still the
                           sealed one; exit 0 when it did, 1 when not, 2
                           when the seal could not be read
  receipts.py board        the issue's board: one bot comment, kept up to date;
                           its hidden state block (#564) carried forward
  receipts.py state get [KEY]
                           the board's state (#564), or one key of it, as
                           JSON; exit 3 when the block was edited by hand
  receipts.py state set KEY=JSON...
                           those keys set in the board's state (KEY= removes
                           one), the board rewritten; refused (exit 3) on a
                           block edited by hand. ITEM=pr for a pull
                           request's board; with no BODY, an issue's body is
                           read from GitHub
  receipts.py migrate      the flow's old labels on the item (#802:
                           autopilot:run-N, free-N, round-N, waiting,
                           answered, catchup, core-wait; ITEM=pr for a pull
                           request) written onto its board, never lowering a
                           count there, read back, and only then taken off;
                           with no old label, nothing to do (exit 0), on any
                           board; refused (exit 3) on a board edited by hand
  receipts.py waits        whom the item waits on now (WAITS_JSON: who, a
                           login or a list of them, or role; what; url;
                           step; ITEM=pr for a pull request's board), on the board's
                           "Waits on" row, and one mention of that person
                           per waiting step (#564)
  receipts.py --test       self-test

Environment: GH_TOKEN; GITHUB_REPOSITORY (owner/name); NUMBER (the issue);
BODY (a file holding the issue's body); ACCEPTED_BY and ACCEPTED_HOW
(seal-prd; `own-bug` for a maintainer's own Bug, #564); AUTHOR (own-bug); POLICY_REF
(the commit of DiluxOne/.github whose policy applied); RECEIPTS_FIXTURE (a
directory standing in for the branch, and for the board's comment and the
mentions, under comments/<n>/, for the self-test).

The board's state (#564): one hidden block in the board's comment,
`<!-- dx-state v1 {...} -->`, JSON holding what the flow counts and where it
stands (whom it waits on, who was mentioned for which step, whether the
triage ran, #803: `triage`, {"ran": true, "verdict", "at"} or
{"ran": false, "why"}, shown as the board's Triage row), with a
SHA-256 of its content. The flow's counts and waits live there (#802, once
labels; FLOW_KEYS): a pull request's `runs` and `rounds`, an issue's `asked`,
`answered`, `catchup` and `core_wait`. It is read only from dilux-bot's own board comment;
a block whose hash does not match was edited by hand and reads as the most
restrictive state: nothing is set on it and nobody is mentioned from it.
Its `repro` key (#801) is where a bug's reproduction stands, in place of
the labels it kept: {"step", "layer", "reason", "at"}, `step` one of
REPRO_STEPS, `layer` one of repro-ways.py's LAYERS; the triage writes it
(`waiting`), the reproduction reads its layer and writes each outcome, and
the board shows it as its Reproduction row (repro_row). `state set` with no
BODY reads the issue's own body for the board's G1 row.

The board's marks: it starts with `<!-- dx-board -->`, by which it is found;
once the issue's acceptance is sealed, its second line is `<!-- dx-prd-seal -->`
(#715), the mark the release scenarios wait for after `accepted`.
"""
import base64
import datetime
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import org  # noqa: E402  the organisation's App, from org.yml (#568)
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("issue_schema", os.path.join(HERE, "issue-schema.py"))
schema_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(schema_mod)

BRANCH = "receipts"
BOARD = "<!-- dx-board -->"
# The hidden mark of a sealed acceptance (#715): the board's second line once
# the issue's acceptance is sealed, which the release scenarios wait for.
SEAL_MARK = "<!-- dx-prd-seal -->"
AI = "🤖 AI-generated · Claude Opus 5.5 (Anthropic)"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prd_hash(body):
    return sha(schema_mod.part_text(body, "prd"))


def spec_hash(body):
    text = schema_mod.part_text(body, "spec")
    return sha(text) if text else None


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- what a seal and a receipt say (pure, tested) -------------------------

OWN_BUG = "own-bug"


def seal(number, body, accepted_by, policy_ref, at, how=None):
    # The text too (#588, choice 5a): what changed since the seal can be
    # said; it is public on the issue already. `how` (#564): `own-bug` when
    # the triage accepted a maintainer's own Bug with its writing.
    s = {"kind": "prd-seal", "issue": number, "prd_sha256": prd_hash(body), "prd": schema_mod.part_text(body, "prd"),
         "accepted_by": accepted_by, "at": at, "policy": f"DiluxOne/.github@{policy_ref}" if policy_ref else None}
    if how:
        s["how"] = how
    return s


def own_bug_accepted(last_seal, body, author):
    """Whether LAST_SEAL accepted a maintainer's own Bug (#564): the triage
    sealed it so, the person it names is the issue's AUTHOR, and BODY's PRD
    is still the sealed one. Only dilux-bot writes the receipts branch, and
    the triage seals it so only after it read the author's maintain or
    admin role. Pure."""
    who = (author or "").strip().lower()
    return bool(last_seal and who and last_seal.get("how") == OWN_BUG
                and str(last_seal.get("accepted_by") or "").strip().lower() == who and verdict(body, last_seal) == "match")


def sealed_prd(last_seal, edits=()):
    """The PRD's text as LAST_SEAL sealed it: its own `prd` when its hash is
    the sealed one, else the PRD of the first body in EDITS (the issue's
    edit history) whose hash is; "" when neither. Pure."""
    if not last_seal:
        return ""
    want = last_seal.get("prd_sha256")
    own = last_seal.get("prd")
    if isinstance(own, str) and sha(own) == want:
        return own
    for body in edits or ():
        if isinstance(body, str) and prd_hash(body) == want:
            return schema_mod.part_text(body, "prd")
    return ""


def edit_history(repo, number):
    """The issue's bodies as edited, from GitHub's edit history (EDITS_JSON
    stands in for it); [] when it cannot be read: the comment then says the
    sealed text is not available."""
    if os.environ.get("EDITS_JSON"):
        return json.loads(os.environ["EDITS_JSON"])
    owner, _, name = repo.partition("/")
    q = "query($o:String!,$n:String!,$i:Int!){repository(owner:$o,name:$n){issue(number:$i){userContentEdits(first:100){nodes{diff}}}}}"
    try:
        data = gh("graphql", "-f", f"query={q}", "-F", f"o={owner}", "-F", f"n={name}", "-F", f"i={number}")
        return [n.get("diff") or "" for n in data["data"]["repository"]["issue"]["userContentEdits"]["nodes"]]
    except (RuntimeError, KeyError, TypeError):
        return []


def verdict(body, last_seal):
    if not last_seal:
        return "unsealed"
    return "match" if last_seal.get("prd_sha256") == prd_hash(body) else "changed"


def wait_verdict(get, tries, sleep):
    """The verdict once it is "match", or the last one after `tries` reads:
    "unsealed" and "changed" are read again, as the acceptance that runs
    alongside may not have sealed yet; a re-acceptance after an edit meets
    the old seal first and reads "changed" (#353). A seal that cannot be
    read (an exception from `get`) is not waited on."""
    v = "unsealed"
    for i in range(max(1, tries)):
        v = get()
        if v not in ("unsealed", "changed"):
            return v
        if i < tries - 1:
            sleep()
    return v


# --- what the policy decided in a person's place (#804; pure, tested) -------
# Once labels (`accepted-by:policy`, `merged-by:policy`) anyone with write
# access could add or take off; now records on the receipts branch, which
# only dilux-bot writes, append-only: the last one is in force. A lane's
# label (`lane:*`) stays, to route; it decides nothing here.

LANE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")
RULE_TEXT = re.compile(r"^[A-Za-z0-9._/#-]{1,200}$")
DECIDED = ("policy", "withdrawn")


def valid_lane(name):
    return bool(LANE_NAME.match(name or ""))


def valid_rule(rule):
    return bool(RULE_TEXT.match(rule or ""))


def policy_at(policy_ref):
    return f"DiluxOne/.github@{policy_ref}" if policy_ref else None


def lane_decision(number, lane, policy_ref, at, run, evidence, decided="policy", rule=None):
    """A lane's decision on an issue (issues/<n>/lane-<UTC>.json): the lane
    accepted it by policy, or `withdrawn` when the lane later refused it.
    RULE is the lane's own unless another rule of the policy decided (a
    planned release: policy/autonomy.yml#planned-release)."""
    return {"kind": "lane-decision", "issue": number, "lane": lane, "decided_by": "policy", "decided": decided,
            "rule": rule or f"policy/autonomy.yml#lanes.{lane}", "policy": policy_at(policy_ref), "at": at, "run": run, "evidence": evidence}


def merge_decision(pr, decided, rule, head, policy_ref, at, run):
    """The policy's decision to merge a pull request at HEAD
    (pulls/<pr>/merge-<UTC>.json), or `withdrawn` when it no longer does."""
    return {"kind": "merge-decision", "pull_request": pr, "decided": decided, "rule": rule, "head": head,
            "policy": policy_at(policy_ref), "at": at, "run": run}


def lane_in_force(decisions):
    """The last lane decision, when it accepted; None when there is none or
    the last one withdrew it."""
    last = decisions[-1] if decisions else None
    return last if last and last.get("decided") == "policy" else None


def merge_in_force(decisions, head):
    """The last merge decision, when it is the policy's and for HEAD, the
    head that merged; None otherwise: a decision for another head, or one
    withdrawn, is no merge by policy."""
    last = decisions[-1] if decisions else None
    return last if last and head and last.get("decided") == "policy" and last.get("head") == head else None


# How far before SINCE `decisions` looks for a merge decision: the policy
# decides a merge before the merge queue merges it, and the digest keeps
# only what merged since SINCE, at the head decided.
MERGE_LOOKBACK_DAYS = 7


def decision_rows(paths, read_one, since):
    """What the policy decided, for the weekly digest (#804): from PATHS (the
    receipts branch's files) and READ_ONE (a path's record), one row per
    issue whose last lane decision accepted it on or after SINCE
    ({"kind": "accepted", "number", "lane", "rule", "policy", "at"}) and one
    per pull request whose last merge decision is the policy's, made on or
    after SINCE less MERGE_LOOKBACK_DAYS ({"kind": "merged", "number",
    "head", "rule", "policy", "at"}): whether and when it merged, at which
    head, is the reader's to check. A record's name carries the time it was
    written, never before its `at`, so only the recent ones are read."""
    prefixes = {"issues": "lane-", "pulls": "merge-"}
    last = {}
    for path in paths:
        parts = path.split("/")
        if len(parts) != 3 or parts[0] not in prefixes or not parts[1].isdigit():
            continue
        top, n, name = parts
        if not (name.startswith(prefixes[top]) and name.endswith(".json")):
            continue
        key = (top, int(n))
        if key not in last or name > last[key]:
            last[key] = name
    day = datetime.date.fromisoformat(since[:10])
    floors = {"issues": since, "pulls": (day - datetime.timedelta(days=MERGE_LOOKBACK_DAYS)).isoformat()}
    rows = []
    for (top, n), name in sorted(last.items()):
        floor = floors[top]
        if name[len(prefixes[top]):-len(".json")] < floor:
            continue
        d = read_one(f"{top}/{n}/{name}")
        if d.get("decided") != "policy" or (d.get("at") or "") < floor:
            continue
        if top == "issues":
            rows.append({"kind": "accepted", "number": n, "lane": d.get("lane"), "rule": d.get("rule"), "policy": d.get("policy"), "at": d.get("at")})
        else:
            rows.append({"kind": "merged", "number": n, "head": d.get("head"), "rule": d.get("rule"), "policy": d.get("policy"), "at": d.get("at")})
    return rows


def receipt(number, body, last_seal, pr, checks, policy_ref, at, lane=None, merge=None):
    """The merge receipt. LANE is the lane decision in force, MERGE the pull
    request's last merge decision: merged by policy only when that decision
    is the policy's and for the head that merged (#804), never from a label."""
    labels = [l for l in pr.get("labels", [])]
    pick = lambda prefix: next((l.split(":", 1)[1] for l in labels if l.startswith(prefix + ":")), None)
    result = schema_mod.check(body, "spec" if schema_mod.part_text(body, "spec") else "prd")
    lane = lane_in_force([lane] if lane else [])
    merge = merge_in_force([merge] if merge else [], pr.get("head"))
    return {
        "kind": "merge-receipt", "issue": number, "at": at,
        "prd_sha256": prd_hash(body), "prd_matches_seal": verdict(body, last_seal) == "match",
        "spec_sha256": spec_hash(body),
        "accepted_by": (last_seal or {}).get("accepted_by"),
        "pull_request": pr.get("number"), "head_commit": pr.get("head"), "merge_commit": pr.get("merge"),
        "merged_by": "policy" if merge else pr.get("merged_by"),
        "lane": (lane or {}).get("lane"), "lane_rule": (lane or {}).get("rule"), "lane_policy": (lane or {}).get("policy"),
        "accepted_at": (lane or {}).get("at"),
        "merged_rule": (merge or {}).get("rule"), "merged_policy": (merge or {}).get("policy"),
        "review": {"risk": pick("risk"), "complexity": pick("complexity"), "type": pick("type")},
        "checks": checks,
        "criteria": result.get("criteria", []),
        "policy": f"DiluxOne/.github@{policy_ref}" if policy_ref else None,
    }


# --- the board's state and whom it waits on (#564; pure, tested) -----------

STATE_RE = re.compile(r"<!-- dx-state v1 (.*?) -->", re.S)
LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


def state_hash(state):
    return sha(json.dumps({k: v for k, v in state.items() if k != "sha256"}, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def state_block(state):
    """The hidden block: the state and its hash, as JSON that cannot end the
    HTML comment it sits in."""
    data = dict({k: v for k, v in state.items() if k != "sha256"}, sha256=state_hash(state))
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "<!-- dx-state v1 " + text.replace("<", "\\u003c").replace(">", "\\u003e").replace("--", "-\\u002d") + " -->"


def parse_state(body):
    """(state, intact) from a board's comment: no block is an empty state;
    one that does not parse or whose hash does not match is not intact."""
    m = STATE_RE.search(body or "")
    if not m:
        return {}, True
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return {}, False
    if not isinstance(data, dict) or data.get("sha256") != state_hash(data):
        return {}, False
    data.pop("sha256")
    return data, True


# What a GraphQL reader (waiting.py, flow-numbers.py) asks of an item's
# comments to find its board (#802): the first and the last 20, and how
# many there are. The board is written early and edited in place, so it is
# usually among the first; one that is in neither window is read from all
# of dilux-bot's comments (graphql_board's read_all).
COMMENTS_GQL = ("comments(first: 20) { totalCount nodes { author { login } body } } "
                "lastComments: comments(last: 20) { nodes { author { login } body } }")


def graphql_board(item, bots, read_all=None):
    """(state, intact) of the item's board, dilux-bot's own last `dx-board`
    comment (a comment by anyone else is never the board), from the
    comments COMMENTS_GQL read. When none is among them and the item has
    more comments than were read, read_all() gives the bodies of all of the
    bot's comments, kept on the item so it is read once. No board is an
    empty state."""
    first = item.get("comments") or {}
    nodes = list(first.get("nodes") or []) + list(((item.get("lastComments") or {}).get("nodes")) or [])
    found = [c.get("body") or "" for c in nodes
             if c and ((c.get("author") or {}).get("login") or "") in bots and (c.get("body") or "").startswith(BOARD)]
    total = first.get("totalCount")
    if not found and read_all is not None and isinstance(total, int) and total > len(first.get("nodes") or []):
        bodies = list(read_all())
        item["comments"] = {"totalCount": len(bodies), "nodes": [{"author": {"login": bots[0]}, "body": b} for b in bodies]}
        item.pop("lastComments", None)
        found = [b for b in bodies if b.startswith(BOARD)]
    return parse_state(found[-1]) if found else ({}, True)


# The flow's counts and waits (#802), once labels: on a pull request's board,
# `runs` ([{"n": N, "free": bool}], every run of the autopilot on it; those
# not free count towards autopilot-runs) and `rounds` (the fix rounds
# already run); on an issue's, `asked` (when the autopilot's question was
# asked, while it waits for the answer), `answered` (a maintainer answered
# it: the run that starts is free), `catchup` (the sweep's continue only
# catches up with another merge: free too) and `core_wait` (the pull
# request on the engine's core it waits for).
FLOW_KEYS = ("runs", "rounds", "asked", "answered", "catchup", "core_wait")


def set_keys(state, changes):
    """The state with `changes` applied: a key set to None is removed. Pure."""
    out = dict(state)
    for k, v in changes.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = v
    return out


# The labels that held them before (#802), which `migrate` moves onto the
# boards and takes off.
OLD_RE = re.compile(r"^autopilot:(?:(run|free|round)-([0-9]+)|(waiting|answered|catchup|core-wait))$")


def old_labels(labels):
    """The flow's old labels among `labels`. Pure."""
    return [str(l) for l in labels or [] if OLD_RE.match(str(l))]


def state_from_labels(labels, state, core=None):
    """The board's state once the old labels' meaning is on it (#802):
    merged into `state`, never lowering what is already there (a run
    counted on either counts; the higher rounds). `core`, the pull request
    an issue labelled `core-wait` waits for, when its comment says. Pure."""
    out = dict(state or {})
    runs = {r["n"]: dict(r) for r in out.get("runs") or [] if isinstance(r, dict) and isinstance(r.get("n"), int)}
    rounds = int(out.get("rounds") or 0) if str(out.get("rounds") or 0).isdigit() else 0
    for label in old_labels(labels):
        kind, n, wait = OLD_RE.match(label).groups()
        if kind in ("run", "free"):
            free = kind == "free"
            runs[int(n)] = {"n": int(n), "free": bool(runs[int(n)].get("free")) and free if int(n) in runs else free}
        elif kind == "round":
            rounds = max(rounds, int(n))
        elif wait == "waiting":
            out["asked"] = out.get("asked") or True
        elif wait == "core-wait":
            out["core_wait"] = out.get("core_wait") or core or True
        else:
            out[wait] = True
    if runs:
        out["runs"] = [runs[n] for n in sorted(runs)]
    if rounds:
        out["rounds"] = rounds
    return out


def fixture_log(line):
    """Under RECEIPTS_FIXTURE, what was read, written and taken off, in
    order (calls.log), for the self-test and the migration's test. Only a
    fixture that holds the items' labels (labels/, the migration's world)
    gets the log: any other fixture is left as its test made it."""
    fx = os.environ.get("RECEIPTS_FIXTURE")
    if fx and os.path.isdir(os.path.join(fx, "labels")):
        with open(os.path.join(fx, "calls.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")


def item_labels(repo, number):
    """The item's labels, for the migration: raised when they cannot be
    read, never taken for none (under RECEIPTS_FIXTURE, labels/<n>.json)."""
    if os.environ.get("RECEIPTS_FIXTURE"):
        path = os.path.join(os.environ["RECEIPTS_FIXTURE"], "labels", f"{number}.json")
        return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []
    out = subprocess.run(["gh", "api", f"repos/{repo}/issues/{number}", "--jq", "[.labels[].name]"], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"#{number}'s labels could not be read: {out.stderr.strip()[:200]}")
    return json.loads(out.stdout or "[]")


def remove_label(repo, number, label):
    fixture_log(f"unlabel {number} {label}")
    if os.environ.get("RECEIPTS_FIXTURE"):
        path = os.path.join(os.environ["RECEIPTS_FIXTURE"], "labels", f"{number}.json")
        left = [l for l in json.load(open(path, encoding="utf-8")) if l != label]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(left, f)
        return
    from urllib.parse import quote
    try:
        gh("-X", "DELETE", f"repos/{repo}/issues/{number}/labels/{quote(label, safe='')}")
    except RuntimeError as e:
        if "404" not in str(e):  # already off
            raise


def core_of(comments):
    """The pull request the autopilot's comment on the core names (`#N:`), or None."""
    for _, b in reversed(comments or []):
        m = re.search(r"#([0-9]+):", b) if b.startswith("<!-- dx-autopilot-core -->") else None
        if m:
            return int(m.group(1))
    return None


def clean(text):
    """A short text for a table cell: no pipes, no mentions, one line."""
    return re.sub(r"\s+", " ", str(text or "")).replace("|", "/").replace("@", "＠").strip()[:200]


def waits_row(waits):
    """The board's "Waits on" row: the person (named, never mentioned
    here) or the role, the action, and its link."""
    if not waits:
        return None
    logins = logins_of(waits)
    whom = ", ".join(f"`{l}`" for l in logins) if logins else clean(waits.get("role") or "nobody")
    url = str(waits.get("url") or "")
    link = f" ([link]({url}))" if url.startswith("https://github.com/") else ""
    return f"| Waits on | {whom}: {clean(waits.get('what'))}{link} |"


def logins_of(waits):
    """The people it waits on (`who`: a login or a list of them), never a
    bot."""
    who = (waits or {}).get("who") or []
    who = [who] if isinstance(who, str) else who if isinstance(who, list) else []
    return [w for w in who if isinstance(w, str) and LOGIN.match(w)]


MENTION_RE = re.compile(r"<!-- dx-mention ([0-9a-f]{16}) -->")


def mention_mark(key):
    return f"<!-- dx-mention {sha(key)[:16]} -->"


def mentioned_in(bodies):
    """The mentions already made, from the marks in the bot's comments."""
    return {m for b in bodies for m in MENTION_RE.findall(b or "")}


def mention(state, waits, said=()):
    """(the comment that mentions the people it waits on, or None; the new
    state): once per person per waiting step (its `step`, else its action
    and link), never a bot, never a role. A mention is recorded twice: in
    the state, and as a hidden mark in its own comment (SAID, the marks
    found in the bot's comments), so a board another job rewrote with an
    older state still never repeats one."""
    step = (waits or {}).get("step") or (clean((waits or {}).get("what")) + " " + str((waits or {}).get("url") or ""))
    done = [k for k in (state.get("mentioned") or []) if isinstance(k, str)]
    key = lambda w: f"{w.lower()}|{step}"
    new = [w for w in logins_of(waits) if key(w) not in done and sha(key(w))[:16] not in set(said)]
    if not new:
        return None, state
    url = str(waits.get("url") or "")
    text = " ".join(f"@{w}" for w in new) + f": {clean(waits.get('what'))}" + (f" {url}" if url.startswith("https://github.com/") else "")
    marks = "".join(mention_mark(key(w)) for w in new)
    return f"{text}\n\n{AI}\n{marks}", dict(state, mentioned=(done + [key(w) for w in new])[-50:])


def announce(state, waits, bodies, put, post):
    """Mention whom it waits on, then write the board (PUT with the new
    state): the comment first, so a post that fails leaves the board as it
    was and the next run mentions them; a board write that fails after it
    is covered by the comment's mark (BODIES, the bot's comments). Returns
    the comment posted, or None."""
    text, state = mention(dict(state, waits=waits), waits, mentioned_in(bodies))
    if text:
        post(text)
    put(state)
    return text


# The reproduction's state (#801): the board's `repro` key, {"step", "layer",
# "reason", "at"}, in place of the labels it used to keep. Each step, as the
# board's Reproduction row says it. The layers are repro-ways.py's LAYERS
# (the self-test keeps them in step).
REPRO_STEPS = {
    "waiting": ("⏳", "waits to run"),
    "confirmed": ("✓", "reproduced by a failing test"),
    "not-reproduced": ("✗", "not reproduced: it waits for more information"),
    "no-way": ("🙋", "no way this repository declares reproduces it: a person takes it"),
    "no-verdict": ("…", "no verdict: its environment did not reach one"),
    "broken": ("⚠", "the test did not run (not a verdict)"),
    "blocked": ("⛔", "blocked by a bug in the repository's test setup"),
}
LAYERS = ("logic", "browser", "cli", "api", "workflow")


def repro_row(repro):
    """The board's Reproduction row: the step in words, the layer and the
    reason (cleaned: it comes from the model or repro-ways, shaped by the
    issue's text). None when the reproduction has no state."""
    if not isinstance(repro, dict) or not repro:
        return None
    icon, words = REPRO_STEPS.get(repro.get("step"), ("·", "not started"))
    parts = [f"{icon} {words}"]
    if repro.get("layer") in LAYERS:
        parts.append(f"layer `{repro['layer']}`")
    if clean(repro.get("reason")):
        parts.append(clean(repro.get("reason")))
    return "| Reproduction | " + " · ".join(parts) + " |"


# The labels the reproduction kept before #801, retired: what each meant
# goes into the state (migrate), sync-repos.py retire-labels takes them off.
RETIRED = ("bug:unconfirmed", "could-not-reproduce", "repro:no-way") + tuple(f"layer:{l}" for l in LAYERS)


def migrate(labels, current=None, at=None):
    """(the board's `repro`, the labels to add, the labels to remove) for an
    issue whose LABELS carry retired ones; (None, [], []) when none does.
    `bug:unconfirmed` is `waiting`; `layer:X`, layer X; `could-not-reproduce`,
    `not-reproduced` and `needs-info`; `repro:no-way`, `no-way` and
    `needs-human`; a `bug:confirmed` one's, `confirmed`. CURRENT, the board's
    `repro` now: a step already there was written since, by the new flow, so
    it stays and nothing is added; a layer already there stays. Pure."""
    labels = [l for l in labels if isinstance(l, str)]
    remove = [l for l in labels if l in RETIRED]
    if not remove:
        return None, [], []
    current = dict(current) if isinstance(current, dict) else {}
    layer = next((l[6:] for l in remove if l.startswith("layer:")), None)
    repro, add = {}, []
    if "repro:no-way" in labels:
        repro = {"step": "no-way", "reason": "no way this repository declares reproduces it (the repro:no-way label, before #801): its comment says why"}
        add = ["needs-human"]
    elif "could-not-reproduce" in labels:
        repro = {"step": "not-reproduced", "reason": "the reproduction found nothing (the could-not-reproduce label, before #801): its comment says why"}
        add = ["needs-info"]
    elif "bug:confirmed" in labels:
        repro = {"step": "confirmed"}
    elif "bug:unconfirmed" in labels:
        repro = {"step": "waiting"}
    if current.get("step"):
        repro, add = current, []
    else:
        repro = dict(current, **repro, at=at or now())
    if layer and not repro.get("layer"):
        repro["layer"] = layer
    return repro, add, remove


def autopilot_row(a):
    """The autopilot's row: its pull request, the run, criteria done of total."""
    if not a:
        return None
    state = ("✓ merged" if a.get("state") == "MERGED" else "✗ closed" if a.get("state") == "CLOSED"
             else "🙋 a person has it" if a.get("needs_human") else "🟡 working (draft)" if a.get("draft") else "✓ ready for review")
    parts = [state, f"{a.get('done', 0)} of {a.get('total', 0)} criteria", f"[#{a['pr']}]({a['url']})"]
    if a.get("run"):
        parts.append(f"[the run]({a['run']})")
    return "| Autopilot | " + " · ".join(parts) + " |"


# What the triage's verdict (its category) reads as on the board (#803).
# A bug to reproduce has no label since #801: its words, not the retired one.
TRIAGE_VERDICTS = {"bug_unconfirmed": "a bug to reproduce", "needs_info": "needs-info", "by_design": "by-design",
                   "pro_feature": "pro-feature", "planned": "planned", "enhancement": "a feature request",
                   "question": "question", "duplicate": "duplicate", "security": "security"}


def triage_row(t):
    """The triage's row (#803): whether it ran, when, and its verdict, from
    the state's `triage` key; none before the triage wrote it."""
    if not isinstance(t, dict):
        return None
    if t.get("ran") is True:
        v = str(t.get("verdict") or "")
        return f"| Triage | ✓ ran at {clean(t.get('at'))}: {TRIAGE_VERDICTS.get(v) or clean(v)} |"
    return f"| Triage | ✗ could not run ({clean(t.get('why') or 'unknown')}): a maintainer re-runs the job or triages it by hand |"


def rule_link(policy):
    """A link to the autonomy policy as a decision read it: at its commit
    ("DiluxOne/.github@<ref>", as seals and receipts keep it), else main."""
    ref = (policy or "").partition("@")[2] or "main"
    return f"[the rule](https://github.com/DiluxOne/.github/blob/{ref}/policy/autonomy.yml)"


def rule_named(rule, policy):
    """A rule by its name, linked at its commit when it is the autonomy
    policy's (#804); another one (the review policy's) is named only."""
    name = f"`{rule}`" if valid_rule(rule) else "`?`"
    return f"{name} ({rule_link(policy)})" if (rule or "").startswith("policy/autonomy.yml") else name


def board_text(number, ready, last_seal, merged, autopilot=None, labels=(), held="", state=None, intact=True, raw_state="", lane=None):
    rows = ["| Gate | State |", "| --- | --- |"]
    rows.append(f"| G1 Issue ready | {'✓ the PRD follows the schema' if ready else '✗ see the G1 comment'} |")
    # Whether the triage ran (#803): the board says it, no label does.
    row = triage_row((state or {}).get("triage")) if intact else None
    if row:
        rows.append(row)
    # A person holds it (#488, #561): a claim, an assignment, their own
    # open pull request that closes it; the autopilot does not start.
    if held and not autopilot:
        rows.append(f"| Held | 🙋 {held}: the autopilot does not start |")
    # Where the reproduction stands (#801), from the state, never from a
    # state edited by hand.
    row = repro_row((state or {}).get("repro")) if intact else None
    if row:
        rows.append(row)
    # The lane in force (#804), from its decision on the receipts, never
    # from a label.
    lane = lane_in_force([lane] if lane else [])
    if lane:
        rows.append(f"| Lane | `{clean(lane.get('lane'))}` by policy, {rule_named(lane.get('rule'), lane.get('policy'))}, accepted at {clean(lane.get('at'))} |")
    if last_seal:
        by = last_seal.get("accepted_by") or ""
        # A lane seals as "policy (lane <name>)": it links the rule it followed (#188).
        if by.startswith("policy (lane "):
            by = f"{by}, {rule_link(last_seal.get('policy'))}"
        # A maintainer's own Bug (#564): accepted with its writing.
        elif last_seal.get("how") == OWN_BUG:
            by = f"{by}, their own Bug, accepted with its writing,"
        rows.append(f"| G2 Accepted | ✓ by {by} at {last_seal.get('at')}; PRD sealed `{last_seal.get('prd_sha256', '')[:12]}` |")
    elif lane:
        # Every automatic decision links the rule it followed (#188).
        rows.append(f"| G2 Accepted | ✓ by policy, lane `{clean(lane.get('lane'))}` ({rule_link(lane.get('policy'))}) at {clean(lane.get('at'))} |")
    else:
        rows.append("| G2 Accepted | not sealed |")
    row = autopilot_row(autopilot)
    if row:
        rows.append(row)
    if merged:
        if merged.get("merged_by") != "policy":
            by = merged.get("merged_by")
        elif merged.get("merged_rule"):
            # #804: the rule the merge decision followed, at its commit.
            by = f"policy, {rule_named(merged.get('merged_rule'), merged.get('merged_policy') or merged.get('policy'))},"
        else:
            by = f"policy ({rule_link(merged.get('policy'))})"
        rows.append(f"| G7 Merged | ✓ #{merged.get('pull_request')} by {by} at {merged.get('at')}; receipt in `receipts/issues/{number}/merged-{merged.get('at')}.json` |")
    if not intact:
        rows.append("| State | ✗ the board's state was edited by hand: the bot sets nothing on it and mentions nobody; a maintainer restores it |")
    row = waits_row((state or {}).get("waits")) if intact else None
    if row:
        rows.append(row)
    # The state block, hidden (#564): carried as it was when it was edited
    # by hand, so a person's edit is never given a valid hash.
    block = raw_state if not intact else (state_block(state) if state else "")
    mark = f"{SEAL_MARK}\n" if last_seal else ""
    return f"{BOARD}\n{mark}**The issue's board**\n\n" + "\n".join(rows) + f"\n\n{AI}" + (f"\n{block}" if block else "")


def pr_board_text(state=None, intact=True, raw_state=""):
    """A pull request's board (#564): one bot comment of the pull request,
    with whom it waits on and its state; its gates are its checks."""
    rows = ["| | State |", "| --- | --- |"]
    if not intact:
        rows.append("| State | ✗ the board's state was edited by hand: the bot sets nothing on it and mentions nobody; a maintainer restores it |")
    row = waits_row((state or {}).get("waits")) if intact else None
    rows.append(row or "| Waits on | nobody |")
    block = raw_state if not intact else (state_block(state) if state else "")
    return f"{BOARD}\n**The pull request's board**\n\n" + "\n".join(rows) + f"\n\n{AI}" + (f"\n{block}" if block else "")


def holder(repo, number):
    """Why a person holds the issue (autopilot.py held_by, #488), read from
    GitHub (HELD stands in for it in the self-test); "" when nobody does or
    it cannot be read: the board then says less, never something wrong."""
    if "HELD" in os.environ:
        return os.environ["HELD"]
    try:
        ap = _autopilot()
        return ap.held_by(*ap.read_holder(repo, number))
    except Exception:  # the board never fails on it
        return ""


def issue_labels(repo, number):
    """The issue's labels, read from GitHub (LABELS_JSON stands in for them
    in the self-test); none when they cannot be read: the board then says
    less, never something wrong."""
    if os.environ.get("LABELS_JSON"):
        return json.loads(os.environ["LABELS_JSON"])
    out = subprocess.run(["gh", "issue", "view", str(number), "--repo", repo, "--json", "labels", "--jq", "[.labels[].name]"],
                         capture_output=True, text=True)
    return json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else []


def issue_body(repo, number):
    """The issue's body, read from GitHub; raised when it cannot be read:
    a board drawn from no body would say the issue is incomplete; ""
    under RECEIPTS_FIXTURE."""
    if os.environ.get("RECEIPTS_FIXTURE"):
        return ""
    out = subprocess.run(["gh", "api", f"repos/{repo}/issues/{number}", "--jq", ".body // \"\""], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"the issue's body could not be read: {out.stderr.strip()[:200]}")
    return out.stdout


def autopilot_state(repo, number):
    """The autopilot's pull request for the issue, and its progress, read
    from GitHub (AUTOPILOT_JSON stands in for it in the self-test)."""
    if os.environ.get("AUTOPILOT_JSON"):
        return json.loads(os.environ["AUTOPILOT_JSON"]) or None
    try:
        refs = json.loads(subprocess.run(["gh", "issue", "view", str(number), "--repo", repo, "--json", "closedByPullRequestsReferences"],
                                         capture_output=True, text=True, check=True).stdout)["closedByPullRequestsReferences"]
        for ref in reversed(refs):
            pr = json.loads(subprocess.run(["gh", "pr", "view", str(ref["number"]), "--repo", repo, "--json", "number,url,body,isDraft,state,labels"],
                                           capture_output=True, text=True, check=True).stdout)
            labels = [l["name"] for l in pr["labels"]]
            if "autopilot" not in labels:
                continue
            ap = _autopilot()
            done, total = ap.progress(pr["body"] or "")
            return {"pr": pr["number"], "url": pr["url"], "draft": pr["isDraft"], "state": pr["state"],
                    "needs_human": "needs-human" in labels, "done": done, "total": total, "run": os.environ.get("AUTOPILOT_RUN", "")}
    except (subprocess.CalledProcessError, KeyError, ValueError):
        return None
    return None


def bot_comments(repo, number):
    """[(id, body)] of dilux-bot's comments on the issue or pull request,
    in order; under RECEIPTS_FIXTURE, comments/<n>/board.md and the
    mentions. A read that fails is raised, never taken for none."""
    if os.environ.get("RECEIPTS_FIXTURE"):
        fixture_log(f"read {number}")
        base = os.path.join(os.environ["RECEIPTS_FIXTURE"], "comments", str(number))
        out = []
        if os.path.exists(os.path.join(base, "mentions.md")):
            out += [(None, b) for b in open(os.path.join(base, "mentions.md"), encoding="utf-8").read().split("\n---\n") if b.strip()]
        if os.path.exists(os.path.join(base, "board.md")):
            out.append((os.path.join(base, "board.md"), open(os.path.join(base, "board.md"), encoding="utf-8").read()))
        return out
    out = subprocess.run(["gh", "api", "--paginate", f"repos/{repo}/issues/{number}/comments",
                          "--jq", '.[] | select(.user.type == "Bot" and (.user.login | startswith("' + org.APP + '"))) | {id, body}'],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"the board could not be read: {out.stderr.strip()[:200]}")
    return [(c["id"], c["body"] or "") for c in (json.loads(l) for l in out.stdout.splitlines() if l.strip())]


def board_comment(repo, number, comments=None):
    """(id, body) of dilux-bot's board comment, or (None, "")."""
    found = [c for c in (bot_comments(repo, number) if comments is None else comments) if c[1].startswith(BOARD)]
    return found[-1] if found else (None, "")


def put_board(repo, number, cid, text):
    """The board's comment written: edited when it exists, else created."""
    if os.environ.get("RECEIPTS_FIXTURE"):
        fixture_log(f"write {number}")
        path = os.path.join(os.environ["RECEIPTS_FIXTURE"], "comments", str(number), "board.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return
    if cid:
        gh("-X", "PATCH", f"repos/{repo}/issues/comments/{cid}", "-f", f"body={text}")
    else:
        gh("-X", "POST", f"repos/{repo}/issues/{number}/comments", "-f", f"body={text}")


def post_comment(repo, number, text):
    if os.environ.get("RECEIPTS_FIXTURE"):
        path = os.path.join(os.environ["RECEIPTS_FIXTURE"], "comments", str(number), "mentions.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n---\n")
        return
    gh("-X", "POST", f"repos/{repo}/issues/{number}/comments", "-f", f"body={text}")


def _autopilot():
    spec = importlib.util.spec_from_file_location("autopilot", os.path.join(HERE, "autopilot.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- the receipts branch ---------------------------------------------------

def gh(*args, data=None):
    cmd = ["gh", "api"] + list(args)
    out = subprocess.run(cmd, input=json.dumps(data) if data is not None else None,
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:300])
    return json.loads(out.stdout) if out.stdout.strip() else {}


def ensure_branch(repo):
    try:
        gh(f"repos/{repo}/git/ref/heads/{BRANCH}")
        return
    except RuntimeError as e:
        if "404" not in str(e) and "Not Found" not in str(e):
            raise
    tree = gh("-X", "POST", f"repos/{repo}/git/trees", "--input", "-", data={"tree": [{
        "path": "README.md", "mode": "100644", "type": "blob",
        "content": "# Receipts\n\nSeals and receipts of this repository's issues, written by " + org.APP + " (" + org.CENTRAL + ", scripts/receipts.py). Nobody else writes here, and nothing here is deleted or rewritten.\n"}]})
    commit = gh("-X", "POST", f"repos/{repo}/git/commits", "--input", "-", data={"message": "Receipts begin", "tree": tree["sha"], "parents": []})
    try:
        gh("-X", "POST", f"repos/{repo}/git/refs", "--input", "-", data={"ref": f"refs/heads/{BRANCH}", "sha": commit["sha"]})
    except RuntimeError as e:
        # Another first write made it a moment ago: use that one.
        if "already exists" not in str(e):
            raise


def write(repo, path, obj, message):
    if os.environ.get("RECEIPTS_FIXTURE"):
        full = os.path.join(os.environ["RECEIPTS_FIXTURE"], path)
        if os.path.exists(full):
            raise RuntimeError(f"{path} exists; a receipt is never overwritten")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)
        return
    ensure_branch(repo)
    put(repo, path, obj, message)


# Two writers at once (two issues accepted together, #561), or a burst of
# them (the release lane accepts all its scenarios at once, #774): a write's
# commit meets a branch head that just moved, and GitHub answers 409, or 422
# on a stale head. Each try reads the head anew; a path that already exists
# is never written again. The wait before a try is a random time up to an
# exponential back-off (full jitter), so writers that collided spread out
# instead of retrying together, and the tries are bounded by time, not by a
# count, which a burst bigger than the count would run out of.
WRITE_SECONDS = 300
BACKOFF_BASE = 0.5
BACKOFF_MAX = 20


def backoff(n, rand=random.random):
    """The wait before try n + 1: a random time in [0, min(BACKOFF_MAX,
    BACKOFF_BASE * 2 ** (n - 1))]."""
    return rand() * min(BACKOFF_MAX, BACKOFF_BASE * 2 ** min(n - 1, 32))


def put(repo, path, obj, message, api=None, nap=None, rand=None, clock=None):
    """Write one receipt on the branch, retrying when the branch moved under
    it (HTTP 409, or 422 on a sha or a conflict) with a jittered back-off
    until WRITE_SECONDS have passed; never an overwrite: without a sha the
    API refuses a path that exists, and a 422 for a path that exists ends
    there. api, nap, rand and clock are for the self-test."""
    api = api or gh
    nap = nap or time.sleep
    rand = rand or random.random
    clock = clock or time.monotonic
    # Never an overwrite: without a sha, the API refuses a path that exists.
    payload = {"message": message, "branch": BRANCH, "content": base64.b64encode((json.dumps(obj, indent=2) + "\n").encode()).decode()}
    start = clock()
    n = 0
    while True:
        n += 1
        try:
            return api("-X", "PUT", f"repos/{repo}/contents/{path}", "--input", "-", data=payload)
        except RuntimeError as e:
            text = str(e)
            moved = "409" in text or ("422" in text and re.search(r"(?i)\bsha\b|conflict", text))
            if not moved:
                raise
            if "422" in text and exists(repo, path, api):
                raise RuntimeError(f"{path} exists; a receipt is never overwritten") from e
            spent = clock() - start
            if spent >= WRITE_SECONDS:
                raise RuntimeError(f"{text}; the receipts branch kept moving for {int(spent)} s") from e
            nap(backoff(n, rand))


def exists(repo, path, api=None):
    """Whether path is on the receipts branch; a read that fails other
    than 404 is raised."""
    try:
        (api or gh)(f"repos/{repo}/contents/{path}?ref={BRANCH}")
        return True
    except RuntimeError as e:
        if "404" in str(e) or "Not Found" in str(e):
            return False
        raise


def list_dir(repo, path):
    """The names under path on the receipts branch; [] when the branch or the
    path does not exist (HTTP 404). Any other error is raised: the gate must
    not take a failure to read for "never sealed"."""
    if os.environ.get("RECEIPTS_FIXTURE"):
        full = os.path.join(os.environ["RECEIPTS_FIXTURE"], path)
        return sorted(os.listdir(full)) if os.path.isdir(full) else []
    try:
        return sorted(e["name"] for e in gh(f"repos/{repo}/contents/{path}?ref={BRANCH}"))
    except RuntimeError as e:
        if "404" in str(e) or "Not Found" in str(e):
            return []
        raise


def tree_paths(repo):
    """Every file on the receipts branch, in one read (#804); [] when the
    branch does not exist. Any other failure, or a listing GitHub cut short,
    is raised: never taken for "nothing decided"."""
    if os.environ.get("RECEIPTS_FIXTURE"):
        base = os.environ["RECEIPTS_FIXTURE"]
        return sorted(os.path.relpath(os.path.join(d, f), base).replace(os.sep, "/") for d, _, fs in os.walk(base) for f in fs)
    try:
        tree = gh(f"repos/{repo}/git/trees/{BRANCH}?recursive=1")
    except RuntimeError as e:
        if "404" in str(e) or "Not Found" in str(e):
            return []
        raise
    if tree.get("truncated"):
        raise RuntimeError(f"{repo}'s receipts are too many to list in one read")
    return [e["path"] for e in tree.get("tree", []) if e.get("type") == "blob"]


def read(repo, path):
    if os.environ.get("RECEIPTS_FIXTURE"):
        with open(os.path.join(os.environ["RECEIPTS_FIXTURE"], path), encoding="utf-8") as f:
            return json.load(f)
    return json.loads(base64.b64decode(gh(f"repos/{repo}/contents/{path}?ref={BRANCH}")["content"]))


def decisions(repo, path, prefix):
    """The records under PATH whose names start with PREFIX, oldest first;
    a read that fails is raised, never taken for none."""
    return [read(repo, f"{path}/{n}") for n in list_dir(repo, path) if n.startswith(prefix)]


def lane_decisions(repo, number):
    return decisions(repo, f"issues/{number}", "lane-")


def merge_decisions(repo, pr):
    return decisions(repo, f"pulls/{pr}", "merge-")


def run_url():
    """The run writing a record: RUN, else this workflow run's URL."""
    if os.environ.get("RUN"):
        return os.environ["RUN"]
    if os.environ.get("GITHUB_RUN_ID"):
        return f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    return None


def last_seal(repo, number):
    seals = [n for n in list_dir(repo, f"issues/{number}") if n.startswith("prd-")]
    return read(repo, f"issues/{number}/{seals[-1]}") if seals else None


def self_test():
    import tempfile
    failed = 0

    def check(name, got, want):
        nonlocal failed
        if got == want:
            print(f"ok   {name}")
        else:
            print(f"FAIL {name}: got {got!r}, want {want!r}")
            failed = 1

    body = """### Problem

No dark mode.

### Scope

- A toggle.

### Out of scope

- Themes.

### Acceptance criteria

- C1: Given a visitor, when they press the toggle, then the page turns dark.

### Criticality

Normal
"""
    s = seal(7, body, "soydiloreto", "abc123", "2026-10-11T00:00:00Z")
    check("a seal holds the PRD's hash", s["prd_sha256"], prd_hash(body))
    check("a seal names who accepted", s["accepted_by"], "soydiloreto")
    check("verify: the same PRD matches", verdict(body, s), "match")
    check("verify: a report added above does not matter", verdict("### What happened?\n\nx\n\n" + body, s), "match")
    check("verify: a changed criterion is caught", verdict(body.replace("turns dark", "turns light"), s), "changed")
    check("verify: no seal is unsealed", verdict(body, None), "unsealed")
    check("C5 (#588): a seal holds the PRD's text", s["prd"], schema_mod.part_text(body, "prd"))
    old = {k: v for k, v in s.items() if k != "prd"}
    check("C5 (#588): the sealed text: the seal's own, else the edit whose hash is the sealed one, else none",
          (sealed_prd(s), sealed_prd(old, ["### Problem\n\nOther.\n", "### What happened?\n\nx\n\n" + body]), sealed_prd(old, ["x"]), sealed_prd(None)),
          (schema_mod.part_text(body, "prd"), schema_mod.part_text(body, "prd"), "", ""))
    check("C5 (#588): a seal's text that does not hash to it is not taken", sealed_prd(dict(s, prd="forged")), "")
    def reads(*vs):
        it = iter(vs)
        return lambda: next(it)
    naps = []
    check("#353 wait: a re-acceptance's old seal (changed) is read again until the new one matches",
          (wait_verdict(reads("changed", "changed", "match"), 12, lambda: naps.append(1)), len(naps)), ("match", 2))
    check("#353 wait: a seal that never comes ends unsealed after every try",
          wait_verdict(reads(*["unsealed"] * 3), 3, lambda: None), "unsealed")
    check("#353 wait: an edit after acceptance stays changed after every try",
          wait_verdict(reads(*["changed"] * 3), 3, lambda: None), "changed")
    check("#353 wait: a match on the first read does not wait", wait_verdict(reads("match"), 12, lambda: 1 / 0), "match")
    pr = {"number": 12, "head": "h1", "merge": "m1", "merged_by": "soydiloreto", "labels": ["risk:low", "complexity:low", "type:feat"]}
    r = receipt(7, body, s, pr, {"success": 20, "failure": 0}, "abc123", "2026-10-11T01:00:00Z")
    check("a receipt says the PRD matches its seal", r["prd_matches_seal"], True)
    check("a receipt carries the review's verdict", r["review"], {"risk": "low", "complexity": "low", "type": "feat"})
    check("a receipt names who accepted", r["accepted_by"], "soydiloreto")
    check("a receipt lists the criteria", r["criteria"], ["C1"])
    pr2 = dict(pr, labels=pr["labels"] + ["merged-by:policy"])
    b = board_text(7, True, s, r)
    # C2 (#804): the digest's rows, from the receipts alone.
    recs = {
        "issues/1/lane-2026-10-05T10:00:00Z.json": lane_decision(1, "platform", "abc", "2026-10-05T10:00:00Z", None, None),
        "issues/4/lane-2026-10-05T10:00:00Z.json": lane_decision(4, "platform", "abc", "2026-10-05T10:00:00Z", None, None),
        "issues/4/lane-2026-10-06T10:00:00Z.json": lane_decision(4, "platform", "abc", "2026-10-06T10:00:00Z", None, None, "withdrawn"),
        "issues/5/lane-2026-09-20T10:00:00Z.json": lane_decision(5, "platform", "abc", "2026-09-20T10:00:00Z", None, None),
        "issues/1/prd-2026-10-05T10:00:00Z.json": {},
        "pulls/9/merge-2026-09-30T10:00:00Z.json": merge_decision(9, "policy", "r", "h9", "abc", "2026-09-30T10:00:00Z", None),
        "pulls/8/merge-2026-09-20T10:00:00Z.json": merge_decision(8, "policy", "r", "h8", "abc", "2026-09-20T10:00:00Z", None),
        "pulls/7/merge-2026-10-05T10:00:00Z.json": merge_decision(7, "withdrawn", "r", "h7", "abc", "2026-10-05T10:00:00Z", None),
        "README.md": {},
    }
    reads = []
    rows = decision_rows(sorted(recs), lambda p: reads.append(p) or recs[p], "2026-10-04")
    check("C2 (#804): the issues a lane accepted since SINCE, and the merge decisions in force from a week before",
          [(r["kind"], r["number"]) for r in rows], [("accepted", 1), ("merged", 9)])
    check("C2 (#804): a row names the lane, the rule, the policy's commit and when",
          (rows[0]["lane"], rows[0]["rule"], rows[0]["policy"], rows[0]["at"], rows[1]["head"]),
          ("platform", "policy/autonomy.yml#lanes.platform", "DiluxOne/.github@abc", "2026-10-05T10:00:00Z", "h9"))
    check("C2 (#804): only the last record of each item, and only recent ones, are read", sorted(reads),
          ["issues/1/lane-2026-10-05T10:00:00Z.json", "issues/4/lane-2026-10-06T10:00:00Z.json", "pulls/7/merge-2026-10-05T10:00:00Z.json", "pulls/9/merge-2026-09-30T10:00:00Z.json"])
    check("the board starts with its marker", b.startswith(BOARD), True)
    check("the board shows the seal", "PRD sealed" in b and s["prd_sha256"][:12] in b, True)
    check("#715: a sealed board carries the seal's mark, after the board's", b.startswith(f"{BOARD}\n{SEAL_MARK}\n"), True)
    check("#715: an unsealed board carries no seal mark", SEAL_MARK in board_text(7, True, None, None, None, ["lane:platform", "accepted-by:policy"]), False)
    a = {"pr": 12, "url": "https://github.com/o/r/pull/12", "draft": True, "state": "OPEN", "done": 1, "total": 3, "run": "https://github.com/o/r/actions/runs/9"}
    ab = board_text(7, True, s, None, a)
    check("C6: the board links the pull request and the run, with the progress", ("[#12](https://github.com/o/r/pull/12)" in ab, "[the run](https://github.com/o/r/actions/runs/9)" in ab, "1 of 3 criteria" in ab), (True, True, True))
    check("C6: a person's pull request says so", "a person has it" in board_text(7, True, s, None, dict(a, needs_human=True)), True)
    check("C6: no autopilot, no row", "Autopilot" in board_text(7, True, s, None, None), False)
    ls = seal(7, body, "policy (lane bugfix-reproduced)", "def456", "t")
    check("#188: a lane's sealed acceptance links the rule at its commit", "✓ by policy (lane bugfix-reproduced), [the rule](https://github.com/DiluxOne/.github/blob/def456/policy/autonomy.yml) at t" in board_text(7, True, ls, None), True)
    ob = seal(7, body, "boss", "abc123", "t", OWN_BUG)
    check("C2 (#564): a maintainer's own Bug is sealed so, by its author", (ob["how"], ob["accepted_by"], "how" in s), (OWN_BUG, "boss", False))
    check("C2 (#564): it is accepted for its author, while the PRD is the sealed one",
          (own_bug_accepted(ob, body, "boss"), own_bug_accepted(ob, body, "Boss"), own_bug_accepted(ob, body.replace("turns dark", "turns light"), "boss")), (True, True, False))
    check("C2 (#564): never for someone else, never from a person's seal, never with no seal",
          (own_bug_accepted(ob, body, "alice"), own_bug_accepted(ob, body, ""), own_bug_accepted(s, body, "soydiloreto"), own_bug_accepted(None, body, "boss")), (False, False, False, False))
    check("C2 (#564): the board says it was the author's own Bug", "✓ by boss, their own Bug, accepted with its writing, at t" in board_text(7, True, ob, None), True)
    check("#188: a person whose login starts with policy is a person", "policyfoo at" in board_text(7, True, seal(7, body, "policyfoo", "x", "t"), None), True)
    check("#188: a lane's label alone is no acceptance", "not sealed" in board_text(7, True, None, None, None, ["lane:platform"]), True)
    mb = board_text(7, True, s, dict(receipt(7, body, s, pr, {}, "abc123", "t"), merged_by="policy"))
    check("#188: a merge by policy links the rule at the commit it read", "by policy ([the rule](https://github.com/DiluxOne/.github/blob/abc123/policy/autonomy.yml))" in mb, True)
    check("#188: a person's merge names the person", "by soydiloreto at" in b, True)
    # C1 (#804): the lane and the policy's merge, on the receipts, never in a label.
    ld = lane_decision(7, "platform", "def456", "2026-11-01T00:00:00Z", "https://github.com/o/r/actions/runs/1", {"author": "dilux-bot"})
    check("C1 (#804) a lane decision names the lane, who decided, the rule and the policy's commit",
          (ld["kind"], ld["issue"], ld["lane"], ld["decided_by"], ld["decided"], ld["rule"], ld["policy"], ld["at"], ld["run"], ld["evidence"]),
          ("lane-decision", 7, "platform", "policy", "policy", "policy/autonomy.yml#lanes.platform", "DiluxOne/.github@def456",
           "2026-11-01T00:00:00Z", "https://github.com/o/r/actions/runs/1", {"author": "dilux-bot"}))
    wd = lane_decision(7, "platform", "def456", "2026-11-02T00:00:00Z", None, None, "withdrawn")
    md = merge_decision(12, "policy", "policy/autonomy.yml#lanes.platform.merge", "h1", "def456", "2026-11-03T00:00:00Z", "https://github.com/o/r/actions/runs/2")
    check("C1 (#804) a merge decision names the pull request, the rule, the head and the policy's commit",
          (md["kind"], md["pull_request"], md["decided"], md["rule"], md["head"], md["policy"], md["at"]),
          ("merge-decision", 12, "policy", "policy/autonomy.yml#lanes.platform.merge", "h1", "DiluxOne/.github@def456", "2026-11-03T00:00:00Z"))
    check("C1 (#804) the lane in force is the last decision; a withdrawn one leaves none",
          (lane_in_force([ld]) == ld, lane_in_force([ld, wd]), lane_in_force([]), lane_in_force([wd, ld]) == ld), (True, None, None, True))
    check("C1 (#804) a merge by policy is the last decision, for the head that merged",
          (merge_in_force([md], "h1") == md, merge_in_force([md], "h2"), merge_in_force([md, dict(md, decided="withdrawn")], "h1"),
           merge_in_force([], "h1"), merge_in_force([md], None)), (True, None, None, None, None))
    plain = dict(pr, merged_by="dilux-bot")
    lr = receipt(7, body, ls, plain, {}, "abc123", "2026-11-04T00:00:00Z", ld, md)
    check("C1 (#804) the merge receipt says policy from the decision, with the lane, its rule, when it was accepted and the merge's rule",
          (lr["merged_by"], lr["lane"], lr["lane_rule"], lr["accepted_at"], lr["merged_rule"]),
          ("policy", "platform", "policy/autonomy.yml#lanes.platform", "2026-11-01T00:00:00Z", "policy/autonomy.yml#lanes.platform.merge"))
    check("C1 (#804) a head that does not match, or a withdrawn decision, gives no policy",
          (receipt(7, body, ls, dict(plain, head="h2"), {}, None, "t", ld, md)["merged_by"],
           receipt(7, body, ls, plain, {}, None, "t", ld, dict(md, decided="withdrawn"))["merged_by"],
           receipt(7, body, ls, plain, {}, None, "t", None, None)["merged_by"]), ("dilux-bot", "dilux-bot", "dilux-bot"))
    check("C1 (#804) a label says nothing: merged-by:policy with no decision is the person who merged",
          receipt(7, body, s, pr2, {}, None, "t")["merged_by"], "soydiloreto")
    check("C1 (#804) with no lane, the receipt has none", [receipt(7, body, s, pr, {}, None, "t")[k] for k in ("lane", "lane_rule", "accepted_at", "merged_rule")],
          [None, None, None, None])
    lb2 = board_text(7, True, ls, lr, lane=ld)
    check("C1 (#804) the board names the lane, the rule at its commit, and when it was accepted",
          "| Lane | `platform` by policy, `policy/autonomy.yml#lanes.platform` ([the rule](https://github.com/DiluxOne/.github/blob/def456/policy/autonomy.yml)), accepted at 2026-11-01T00:00:00Z |" in lb2, True)
    check("C1 (#804) and when it merged, by which rule",
          "✓ #12 by policy, `policy/autonomy.yml#lanes.platform.merge` ([the rule](https://github.com/DiluxOne/.github/blob/def456/policy/autonomy.yml)), at 2026-11-04T00:00:00Z;" in lb2, True)
    check("C1 (#804) the labels say nothing on the board: no lane decision, no lane row and no acceptance by policy",
          ("Lane" in board_text(7, True, None, None, None, ["lane:platform", "accepted-by:policy"]),
           "not sealed" in board_text(7, True, None, None, None, ["lane:platform", "accepted-by:policy"])), (False, True))
    check("C1 (#804) a lane decision alone accepts on the board, with its rule",
          "✓ by policy, lane `platform` ([the rule](https://github.com/DiluxOne/.github/blob/def456/policy/autonomy.yml)) at 2026-11-01T00:00:00Z" in board_text(7, True, None, None, lane=ld), True)
    check("C1 (#804) a merge rule outside the policy is named, not linked",
          "by policy, `.github/review-policy.yml#auto-merge`, at" in board_text(7, True, s, dict(lr, merged_rule=".github/review-policy.yml#auto-merge")), True)
    check("C1 (#804) a lane name or a rule that is not plain is refused", (valid_lane("platform"), valid_lane("a|b"), valid_lane(""), valid_rule("x`y")), (True, False, False, False))
    # #564: the board's state, hidden, hashed, carried; whom it waits on.
    st = {"runs": 2, "waits": {"who": "alice", "what": "answer --> <b>", "url": "https://github.com/o/r/issues/7"}}
    blk = state_block(st)
    check("#564 the state round-trips through its block", parse_state("board\n" + blk), (st, True))
    check("#564 a value cannot end the comment it sits in", blk.count("-->"), 1)
    check("#564 no block is an empty state", parse_state("<!-- dx-board -->\nrows"), ({}, True))
    check("#564 a block edited by hand is not intact", parse_state(blk.replace('"runs":2', '"runs":0')), ({}, False))
    check("#564 nor is one that does not parse", parse_state("<!-- dx-state v1 {nope -->"), ({}, False))
    # #802 C2: the flow's old labels, onto the board.
    was = ["autopilot", "autopilot:run-1", "autopilot:free-2", "autopilot:run-3", "autopilot:round-2", "autopilot:waiting", "autopilot:core-wait"]
    check("#802 C2 the old labels are the flow's seven, never `autopilot` or its continue",
          old_labels(was + ["autopilot:continue", "autopilot:run-x", "autopilot:waiting-x"]), was[1:])
    moved = state_from_labels(was, {"waits": {"role": "the autopilot"}}, 5)
    check("#802 C2 their state: every run, the rounds, the question and the core, beside what was there",
          moved, {"waits": {"role": "the autopilot"}, "runs": [{"n": 1, "free": False}, {"n": 2, "free": True}, {"n": 3, "free": False}],
                  "rounds": 2, "asked": True, "core_wait": 5})
    check("#802 C2 merged again, nothing changes; a count already higher is never lowered",
          (state_from_labels(was, moved, 5) == moved, state_from_labels(["autopilot:round-1", "autopilot:free-1"], {"rounds": 4, "runs": [{"n": 1, "free": False}]})),
          (True, {"rounds": 4, "runs": [{"n": 1, "free": False}]}))
    check("#802 the core's comment names the pull request it waits for", (core_of([(1, "<!-- dx-autopilot-core -->\nwaits for #12: x")]), core_of([(1, "#3: x")])), (12, None))
    check("#802 a key set to nothing is removed", set_keys({"a": 1, "b": 2}, {"a": None, "c": 3}), {"b": 2, "c": 3})
    # #802: a GraphQL reader's board, past the comments it read.
    bots, chat = ("dilux-bot",), [{"author": {"login": "ana"}, "body": "x"}] * 20
    board_c = BOARD + "\n" + state_block({"asked": True})
    far, reads = {"comments": {"totalCount": 60, "nodes": chat}, "lastComments": {"nodes": chat}}, []
    read = lambda: reads.append(1) or ["hi", board_c]
    check("#802 a board in neither window is read from all of the bot's comments, once",
          (graphql_board(far, bots, read), graphql_board(far, bots, read), len(reads)), (({"asked": True}, True), ({"asked": True}, True), 1))
    near = {"comments": {"totalCount": 60, "nodes": chat}, "lastComments": {"nodes": [{"author": {"login": "dilux-bot"}, "body": board_c}]}}
    check("#802 one among those read is read with no more; a person's is never the board; few comments, nothing more to read",
          (graphql_board(near, bots, lambda: 1 / 0), graphql_board({"comments": {"nodes": [{"author": {"login": "mallory"}, "body": board_c}]}}, bots),
           graphql_board({"comments": {"totalCount": 20, "nodes": chat}}, bots, lambda: 1 / 0)),
          (({"asked": True}, True), ({}, True), ({}, True)))
    wb = board_text(7, True, s, None, state=st)
    check("C5 the board names whom it waits on, the action and its link, mentioning nobody",
          ("| Waits on | `alice`: answer --> <b> ([link](https://github.com/o/r/issues/7)) |" in wb, "@alice" in wb), (True, False))
    check("C5 its state is carried, hidden, at the end", wb.rstrip().endswith(blk), True)
    check("C5 a role is named as one", waits_row({"role": "a maintainer", "what": "accept it", "url": "https://github.com/o/r/issues/7"}), "| Waits on | a maintainer: accept it ([link](https://github.com/o/r/issues/7)) |")
    check("C5 a link that is not GitHub's is not linked", "evil" in (waits_row({"who": "alice", "what": "x", "url": "https://evil.example"}) or ""), False)
    # C1 (#801): the reproduction's step, its layer and its outcome, on the board.
    check("C1 (#801) the Reproduction row shows the step and the layer",
          repro_row({"step": "waiting", "layer": "browser"}), "| Reproduction | ⏳ waits to run · layer `browser` |")
    check("C1 (#801) and the outcome, with its reason",
          repro_row({"step": "confirmed", "layer": "logic", "reason": "the test fails on main", "at": "t"}),
          "| Reproduction | ✓ reproduced by a failing test · layer `logic` · the test fails on main |")
    check("C1 (#801) every step reads in words", all(repro_row({"step": st}) == f"| Reproduction | {icon} {words} |" and words != st
                                                     for st, (icon, words) in REPRO_STEPS.items()), True)
    check("C1 (#801) the Spec's steps, every one", sorted(REPRO_STEPS), sorted(["waiting", "confirmed", "not-reproduced", "no-way", "no-verdict", "broken", "blocked"]))
    check("C1 (#801) a step it does not know is said as not started", repro_row({"step": "x|y"}), "| Reproduction | · not started |")
    check("C1 (#801) no reproduction, no row; nor for a value that is no state", (repro_row(None), repro_row({}), repro_row("waiting")), (None, None, None))
    check("C2 (#801) the row names the reason, cleaned: one line, no pipe, no mention, bounded",
          repro_row({"step": "no-way", "layer": "browser", "reason": "it needs a | browser\ntest, ask @alice " + "x" * 300}),
          "| Reproduction | 🙋 no way this repository declares reproduces it: a person takes it · layer `browser` · "
          + clean("it needs a | browser\ntest, ask @alice " + "x" * 300) + " |")
    check("C2 (#801) clean() is what makes it so", ("|" in clean("a | b"), "@" in clean("@a"), "\n" in clean("a\nb"), len(clean("x" * 300))), (False, False, False, 200))
    check("C2 (#801) found nothing and no way say whom they wait on", ("more information" in repro_row({"step": "not-reproduced"}), "a person" in repro_row({"step": "no-way"})), (True, True))
    # C3 (#801): the retired labels' meaning, as the board's state.
    check("C3 (#801) the retired labels are the eight", sorted(RETIRED),
          sorted(["bug:unconfirmed", "could-not-reproduce", "repro:no-way"] + [f"layer:{l}" for l in LAYERS]))
    check("C3 (#801) bug:unconfirmed and its layer: it waits, on that layer",
          migrate(["bug:unconfirmed", "layer:browser", "accepted"], at="t"), ({"step": "waiting", "layer": "browser", "at": "t"}, [], ["bug:unconfirmed", "layer:browser"]))
    m = migrate(["layer:cli", "could-not-reproduce", "bug:unconfirmed"], at="t")
    check("C3 (#801) could-not-reproduce: not reproduced, needs-info, the reason said",
          (m[0]["step"], m[0]["layer"], bool(m[0]["reason"]), m[1], m[2]), ("not-reproduced", "cli", True, ["needs-info"], ["layer:cli", "could-not-reproduce", "bug:unconfirmed"]))
    m = migrate(["repro:no-way", "layer:workflow"], at="t")
    check("C3 (#801) repro:no-way: no way, needs-human, the reason said",
          (m[0]["step"], m[0]["layer"], bool(m[0]["reason"]), m[1], m[2]), ("no-way", "workflow", True, ["needs-human"], ["repro:no-way", "layer:workflow"]))
    check("C3 (#801) a layer alone: the layer, no step", migrate(["layer:api"], at="t"), ({"layer": "api", "at": "t"}, [], ["layer:api"]))
    check("C3 (#801) a confirmed bug's layer: confirmed", migrate(["bug:confirmed", "layer:logic"], at="t")[0], {"step": "confirmed", "layer": "logic", "at": "t"})
    check("C3 (#801) no retired label: nothing to do", migrate(["bug:confirmed", "needs-info", "layer:screen"]), (None, [], []))
    check("C3 (#801) a step already on the board is newer: it stays, only the labels come off",
          migrate(["bug:unconfirmed", "could-not-reproduce", "layer:cli"], {"step": "confirmed", "reason": "r", "at": "s"}, at="t"),
          ({"step": "confirmed", "reason": "r", "at": "s", "layer": "cli"}, [], ["bug:unconfirmed", "could-not-reproduce", "layer:cli"]))
    check("C3 (#801) and a layer already there stays", migrate(["layer:cli"], {"layer": "browser"}, at="t")[0], {"layer": "browser", "at": "t"})
    check("C1 (#801) a layer that is none of the layers is not shown", "evil" in repro_row({"step": "waiting", "layer": "evil`|x"}), False)
    rb = board_text(7, True, None, None, state={"repro": {"step": "not-reproduced", "layer": "cli", "reason": "it passes"}})
    check("C1 (#801) the board carries the row", "| Reproduction | ✗ not reproduced: it waits for more information · layer `cli` · it passes |" in rb, True)
    check("C1 (#801) a state edited by hand shows no reproduction", "Reproduction" in board_text(7, True, None, None, state={}, intact=False,
                                                                                          raw_state='<!-- dx-state v1 {"repro":{"step":"waiting"}} -->'), False)
    check("#803 the board says the triage ran, when, and its verdict",
          triage_row({"ran": True, "verdict": "needs_info", "at": "2026-11-17T00:00:00Z"}), "| Triage | ✓ ran at 2026-11-17T00:00:00Z: needs-info |")
    check("#803 or that it could not run, and what a maintainer does",
          triage_row({"ran": False, "why": "failed"}), "| Triage | ✗ could not run (failed): a maintainer re-runs the job or triages it by hand |")
    check("#801 a bug's verdict names no retired label", any(v in RETIRED for v in TRIAGE_VERDICTS.values()), False)
    check("#803 no triage key, no row; a verdict's text is cleaned", (triage_row(None), "@" in triage_row({"ran": True, "verdict": "@x|y", "at": "t"})), (None, False))
    tb = board_text(7, True, s, None, state={}, intact=False, raw_state=blk.replace('"runs":2', '"runs":0'))
    check("#564 a state edited by hand is said, kept as it was, and names nobody", ("edited by hand" in tb, '"runs":0' in tb, "Waits on" in tb), (True, True, False))
    w = {"who": "alice", "what": "complete the issue", "url": "https://github.com/o/r/issues/7"}
    t1, st1 = mention({}, w)
    t2, st2 = mention(st1, w)
    check("C5 the author is mentioned when it waits on them, with the action and its link", t1.startswith("@alice: complete the issue https://github.com/o/r/issues/7"), True)
    check("C5 once: the same step mentions nobody again", (t2, st2), (None, st1))
    check("C5 a mention already made, found by its mark in the bot's comments, is not made again from a state another job overwrote",
          mention({}, w, mentioned_in([t1]))[0], None)
    check("C5 the mark hides in the comment", (mention_mark("alice|s") in mention({}, dict(w, step="s"))[0], "alice|" in t1), (True, False))
    check("C5 a new step mentions them again", mention(st1, dict(w, what="answer the question", url="https://github.com/o/r/issues/7#issuecomment-1"))[0] is not None, True)
    boards, posts = [], []

    def failing(t):
        raise RuntimeError("POST failed")
    try:
        announce({}, w, [], boards.append, failing)
    except RuntimeError:
        pass
    check("C3 a mention whose post fails is not recorded on the board", boards, [])
    announce({}, w, [], boards.append, posts.append)
    check("C3 so the next run mentions them, once", (len(posts), posts[0].startswith("@alice"), "alice|" in str(boards[-1].get("mentioned"))), (1, True, True))
    check("C3 a board write that failed after the post never mentions again", announce({}, w, posts, boards.append, posts.append), None)
    pb = pr_board_text({"waits": {"who": ["boss"], "what": "review it and merge it", "url": "https://github.com/o/r/pull/8"}})
    check("C3 a pull request's board names whom it waits on", ("pull request's board" in pb, "| Waits on | `boss`: review it and merge it ([link](https://github.com/o/r/pull/8)) |" in pb, "G1" in pb), (True, True, False))
    tm = mention({}, {"who": ["boss", "ana", "dilux-bot[bot]"], "what": "x", "step": "s"})
    check("C3 several people, each once, in one comment, never a bot", (tm[0].split(":")[0], mention(tm[1], {"who": ["boss", "ana"], "what": "x", "step": "s"})[0]), ("@boss @ana", None))
    check("C5 a role, a bot or nobody is never mentioned", (mention({}, {"role": "a maintainer", "what": "x"})[0], mention({}, {"who": "dilux-bot[bot]", "what": "x"})[0], mention({}, None)[0]), (None, None, None))
    with tempfile.TemporaryDirectory() as d:
        os.environ["RECEIPTS_FIXTURE"] = d
        write("o/r", "issues/7/prd-2026-10-11T00:00:00Z.json", s, "seal")
        later = dict(s, prd_sha256="x", at="2026-10-12T00:00:00Z")
        write("o/r", "issues/7/prd-2026-10-12T00:00:00Z.json", later, "seal again")
        check("the last seal wins", last_seal("o/r", 7)["at"], "2026-10-12T00:00:00Z")
        try:
            write("o/r", "issues/7/prd-2026-10-12T00:00:00Z.json", s, "again")
            check("a seal is never overwritten", "overwrote", "refused")
        except RuntimeError:
            check("a seal is never overwritten", "refused", "refused")
        check("an issue with no seal has none", last_seal("o/r", 8), None)
        import subprocess as sp
        bf = os.path.join(d, "body.md")
        with open(bf, "w", encoding="utf-8") as f:
            f.write(body)
        env = dict(os.environ, AUTOPILOT_JSON="null", LABELS_JSON="[]", NUMBER="9", BODY=bf, GITHUB_REPOSITORY="o/r", ACCEPTED_BY="soydiloreto",
                   PR_JSON=json.dumps(pr), CHECKS_JSON='{"success": 3}')
        run = lambda *a: sp.run([sys.executable, os.path.abspath(__file__)] + list(a), env=env, capture_output=True, text=True)
        check("cli: verify an issue never sealed", run("verify-prd").stdout.strip(), "unsealed")
        check("cli: seal-prd writes a seal", run("seal-prd").returncode, 0)
        check("cli: verify the sealed PRD", run("verify-prd").stdout.strip(), "match")
        check("C2 cli: a person's seal is no own Bug", (run("own-bug").returncode, run("own-bug").stdout.strip()), (1, "no"))
        env11 = dict(env, NUMBER="11", ACCEPTED_BY="boss", ACCEPTED_HOW=OWN_BUG, AUTHOR="boss")
        sp.run([sys.executable, os.path.abspath(__file__), "seal-prd"], env=env11, capture_output=True, text=True)
        got11 = sp.run([sys.executable, os.path.abspath(__file__), "own-bug"], env=env11, capture_output=True, text=True)
        check("C2 cli: seal-prd with ACCEPTED_HOW=own-bug, then own-bug for its author", (got11.returncode, got11.stdout.strip()), (0, "yes"))
        check("C2 cli: and not for anyone else", sp.run([sys.executable, os.path.abspath(__file__), "own-bug"], env=dict(env11, AUTHOR="alice"), capture_output=True, text=True).returncode, 1)
        # C5 (#588): the accepted body edited reads `changed`, and the
        # sealed text is found to say what changed.
        ef = os.path.join(d, "edited.md")
        with open(ef, "w", encoding="utf-8") as f:
            f.write(body.replace("turns dark", "turns light"))
        check("C5 cli: an edited accepted body reads changed", (run_e := sp.run([sys.executable, os.path.abspath(__file__), "verify-prd"], env=dict(env, BODY=ef), capture_output=True, text=True)).stdout.strip(), "changed")
        check("C5 cli: and exits 1", run_e.returncode, 1)
        got = sp.run([sys.executable, os.path.abspath(__file__), "sealed-prd"], env=dict(env, BODY=ef), capture_output=True, text=True)
        check("C5 cli: sealed-prd prints the text that was sealed", (got.returncode, got.stdout.strip() == schema_mod.part_text(body, "prd").strip()), (0, True))
        check("cli: merged writes a receipt", run("merged").returncode, 0)
        check("cli: the board shows the receipt", "G7 Merged" in run("board").stdout, True)
        check("cli: verify-spec with no Spec seal fails", run("verify-spec").returncode, 1)
        # C5 (#564): whom it waits on, on the board, and one mention.
        wenv = dict(env, NUMBER="12", HELD="", WAITS_JSON=json.dumps({"who": "alice", "what": "complete the issue: the G1 comment says what is missing", "url": "https://github.com/o/r/issues/12"}))
        wrun = lambda *a, **kw: sp.run([sys.executable, os.path.abspath(__file__)] + list(a), env=dict(wenv, **kw), capture_output=True, text=True)
        wrun("waits"), wrun("waits")
        board12 = open(os.path.join(d, "comments/12/board.md"), encoding="utf-8").read()
        mentions12 = open(os.path.join(d, "comments/12/mentions.md"), encoding="utf-8").read()
        check("C5 cli: the board names the author it waits on", "| Waits on | `alice`: complete the issue" in board12, True)
        check("C5 cli: and mentions them once, however often it runs", mentions12.count("@alice: complete the issue"), 1)
        with open(os.path.join(d, "comments/12/board.md"), "w", encoding="utf-8") as f:
            f.write(board_text(12, True, None, None))
        wrun("waits")
        check("C5 cli: a board rewritten by another job, with no state, still mentions nobody twice",
              open(os.path.join(d, "comments/12/mentions.md"), encoding="utf-8").read().count("@alice: complete the issue"), 1)
        board12 = open(os.path.join(d, "comments/12/board.md"), encoding="utf-8").read()
        check("C5 cli: the board's run keeps the state", parse_state(wrun("board").stdout)[0].get("waits", {}).get("who"), "alice")
        check("#564 cli: state set, then state get", (wrun("state", "set", "runs=3").returncode, wrun("state", "get", "runs").stdout.strip()), (0, "3"))
        with open(os.path.join(d, "comments/12/board.md"), "w", encoding="utf-8") as f:
            f.write(board12.replace('"who":"alice"', '"who":"mallory"'))
        check("#564 cli: on a state edited by hand, get and set exit 3, and nobody is mentioned",
              (wrun("state", "get").returncode, wrun("state", "set", "runs=0").returncode, wrun("waits", WAITS_JSON='{"who": "mallory", "what": "x"}').returncode,
               open(os.path.join(d, "comments/12/mentions.md"), encoding="utf-8").read().count("@")), (3, 3, 3, 1))
        import time
        time.sleep(1.1)
        run("merged")
        check("cli: a second merge does not overwrite the first", len([n for n in os.listdir(os.path.join(d, "issues/9")) if n.startswith("merged-")]), 2)
        os.makedirs(os.path.join(d, "issues/10"))
        with open(os.path.join(d, "issues/10/prd-x.json"), "w") as f:
            f.write("{not json")
        r10 = sp.run([sys.executable, os.path.abspath(__file__), "verify-prd"], env=dict(env, NUMBER="10"), capture_output=True, text=True)
        check("cli: a seal that cannot be read exits 2", r10.returncode, 2)
        # C1 (#804): the lane and the merge decisions through the CLI, read back by `lane get` and `merged`.
        lenv = dict(env, NUMBER="20", LANE="platform", POLICY_REF="def456", RUN="https://github.com/o/r/actions/runs/3")
        lrun = lambda *a, **kw: sp.run([sys.executable, os.path.abspath(__file__)] + list(a), env=dict(lenv, **kw), capture_output=True, text=True)
        check("C1 (#804) cli: an issue with no lane decision has no lane (exit 1, null)", (lrun("lane", "get").returncode, lrun("lane", "get").stdout.strip()), (1, "null"))
        check("C1 (#804) cli: lane-decision writes it, and lane get reads it",
              (lrun("lane-decision").returncode, json.loads(lrun("lane", "get").stdout or "null").get("lane"), lrun("lane").returncode), (0, "platform", 0))
        check("C1 (#804) cli: a lane that is not plain is refused", lrun("lane-decision", LANE="x|y", NUMBER="21").returncode, 64)
        check("C1 (#804) cli: a planned release names the rule that decided it, and a rule that is not plain is refused",
              (json.loads(lrun("lane-decision", LANE="release", NUMBER="230", RULE="policy/autonomy.yml#planned-release").stdout)["rule"],
               lrun("lane-decision", LANE="release", NUMBER="231", RULE="a rule; rm").returncode), ("policy/autonomy.yml#planned-release", 64))
        time.sleep(1.1)
        check("C1 (#804) cli: a withdrawn decision leaves no lane", (lrun("lane-decision", DECIDED="withdrawn", LANE="").returncode, lrun("lane", "get").returncode), (0, 1))
        check("C1 (#804) cli: nothing to withdraw writes nothing", (lrun("lane-decision", DECIDED="withdrawn", NUMBER="22").returncode, os.path.isdir(os.path.join(d, "issues/22"))), (0, False))
        time.sleep(1.1)
        lrun("lane-decision")
        menv = dict(PR="12", HEAD="h1", RULE="policy/autonomy.yml#lanes.platform.merge")
        check("C1 (#804) cli: merge-decision writes it under the pull request", (lrun("merge-decision", **menv).returncode, len(os.listdir(os.path.join(d, "pulls/12")))), (0, 1))
        check("C1 (#804) cli: a merge decision needs its pull request and its head", (lrun("merge-decision", PR="", HEAD="h1").returncode, lrun("merge-decision", PR="13", HEAD="").returncode), (64, 64))
        mr = json.loads(lrun("merged", PR_JSON=json.dumps(dict(pr, merged_by="dilux-bot"))).stdout)
        check("C1 (#804) cli: the merge receipt names the lane, its rule, when accepted, and policy from the decision",
              (mr["merged_by"], mr["lane"], mr["lane_rule"], bool(mr["accepted_at"]), mr["merged_rule"]),
              ("policy", "platform", "policy/autonomy.yml#lanes.platform", True, "policy/autonomy.yml#lanes.platform.merge"))
        time.sleep(1.1)
        check("C1 (#804) cli: withdrawn, the next receipt says who merged", (lrun("merge-decision", DECIDED="withdrawn", PR="12", HEAD="h1").returncode,
              json.loads(lrun("merged", PR_JSON=json.dumps(dict(pr, merged_by="dilux-bot"))).stdout)["merged_by"]), (0, "dilux-bot"))
        check("C1 (#804) cli: nothing to withdraw on a pull request writes nothing", (lrun("merge-decision", DECIDED="withdrawn", PR="14", HEAD="h").returncode, os.path.isdir(os.path.join(d, "pulls/14"))), (0, False))
        lb20 = lrun("board", LABELS_JSON='["lane:org-sync", "accepted-by:policy"]').stdout
        check("C1 (#804) cli: the board shows the lane from its decision, never from a label", ("`platform` by policy" in lb20, "org-sync" in lb20), (True, False))
        os.makedirs(os.path.join(d, "issues/23"))
        with open(os.path.join(d, "issues/23/lane-x.json"), "w") as f:
            f.write("{not json")
        check("C1 (#804) cli: a lane that cannot be read exits 2, never read as a lane", lrun("lane", "get", NUMBER="23").returncode, 2)
        del os.environ["RECEIPTS_FIXTURE"]
    # #561 C5: two writers at once, each answered 409 once by a branch that
    # moved, then written; a path that exists is never written again.
    branch_files, calls, naps5 = {}, [], []

    def moving_api(*args, data=None):
        url = next(a for a in args if a.startswith("repos/"))
        path = url.split("/contents/", 1)[1].split("?", 1)[0]
        calls.append((args[1] if args[0] == "-X" else "GET", path))
        if args[:2] == ("-X", "PUT"):
            if path in branch_files:
                raise RuntimeError('gh: Invalid request. "sha" wasn\'t supplied. (HTTP 422)')
            if sum(1 for c in calls if c == ("PUT", path)) == 1:
                raise RuntimeError("gh: is at abc but expected def (HTTP 409)")
            branch_files[path] = data["content"]
            return {"content": {"path": path}}
        if path in branch_files:
            return {"path": path}
        raise RuntimeError("gh: Not Found (HTTP 404)")

    for n in (8, 9):
        put("o/r", f"issues/{n}/prd-1.json", {"issue": n}, f"seal #{n}", api=moving_api, nap=naps5.append)
    check("#561 C5: two seals written at the same moment both succeed, each after one 409", (sorted(branch_files), len(naps5)),
          (["issues/8/prd-1.json", "issues/9/prd-1.json"], 2))
    try:
        put("o/r", "issues/8/prd-1.json", {"issue": 8, "x": 1}, "again", api=moving_api, nap=naps5.append)
        again = "written"
    except RuntimeError as e:
        again = str(e)
    check("#561 C5: a path that exists is never written again", ("never overwritten" in again, json.loads(base64.b64decode(branch_files["issues/8/prd-1.json"]))),
          (True, {"issue": 8}))
    always = lambda *a, data=None: (_ for _ in ()).throw(RuntimeError("gh: conflict (HTTP 409)"))
    fake = [0.0]
    tries10 = []

    def counted(*a, data=None):
        tries10.append(fake[0])
        return always(*a, data=data)
    try:
        put("o/r", "issues/10/prd-1.json", {}, "x", api=counted, nap=lambda s: fake.__setitem__(0, fake[0] + s),
            rand=lambda: 1.0, clock=lambda: fake[0])
        capped = "written"
    except RuntimeError as e:
        capped = str(e)
    check("#561 C5, #774: a branch that keeps moving fails once the bound passes, said",
          ("409" in capped, f"kept moving for {int(fake[0])} s" in capped, fake[0] >= WRITE_SECONDS, fake[0] - tries10[-2] <= BACKOFF_MAX),
          (True, True, True, True))
    check("#774: the tries are bounded by time, not by five", len(tries10) > 5, True)
    # #774: full jitter, each wait within [0, min(cap, base * 2 ** (n - 1))].
    check("#774: the jitter stays within its window",
          [(backoff(n, lambda: 0.0), backoff(n, lambda: 1.0)) for n in (1, 2, 3, 6, 7, 40)],
          [(0.0, 0.5), (0.0, 1.0), (0.0, 2.0), (0.0, 16.0), (0.0, 20), (0.0, 20)])
    check("#774: the default jitter is random within its window", all(0 <= backoff(3) <= 2.0 for _ in range(200)), True)
    # #774: eight writers at once on a branch that takes one commit at a
    # time and answers 409 to a write that meets another.
    import threading
    burst, head8 = {}, threading.Lock()

    def one_at_a_time(*args, data=None):
        path = next(a for a in args if a.startswith("repos/")).split("/contents/", 1)[1]
        if not head8.acquire(blocking=False):
            raise RuntimeError("gh: is at abc but expected def (HTTP 409)")
        try:
            time.sleep(0.005)
            burst[path] = data["content"]
        finally:
            head8.release()
        return {"content": {"path": path}}

    paths8 = [f"issues/{n}/prd-2.json" for n in range(20, 28)]
    gate8, lost = threading.Barrier(len(paths8)), []

    def writer(p):
        gate8.wait()
        try:
            put("o/r", p, {}, "seal", api=one_at_a_time, nap=lambda s: time.sleep(s * 0.02))
        except RuntimeError as e:
            lost.append(str(e))
    writers = [threading.Thread(target=writer, args=(p,)) for p in paths8]
    for t in writers:
        t.start()
    for t in writers:
        t.join()
    check("#774: writers that move the branch in a burst are all written", (sorted(burst), lost), (paths8, []))
    try:
        put("o/r", "issues/11/prd-1.json", {}, "x", api=lambda *a, data=None: (_ for _ in ()).throw(RuntimeError("gh: Bad credentials (HTTP 401)")), nap=lambda s: 1 / 0)
        other = "written"
    except RuntimeError as e:
        other = str(e)
    check("#561 C5: any other failure is not retried", "401" in other, True)
    # A job that runs this script reads the organisation's scripts whole:
    # it loads autopilot.py for an autopilot pull request's board (#306).
    try:
        import yaml
        wf = yaml.safe_load(open(os.path.join(HERE, "..", ".github", "workflows", "issue-accepted.yml"), encoding="utf-8"))
        runs = {name: json.dumps(job) for name, job in wf["jobs"].items() if "receipts.py" in json.dumps(job)}
        rw_spec = importlib.util.spec_from_file_location("repro_ways_layers", os.path.join(HERE, "repro-ways.py"))
        rw = importlib.util.module_from_spec(rw_spec)
        rw_spec.loader.exec_module(rw)
        check("C1 (#801) the board's layers are repro-ways.py's", LAYERS, rw.LAYERS)
        whole = lambda t: "git init -q .dx-central" in t or ('"repository": "DiluxOne/.github"' in t and '"path": ".dx-central"' in t)
        check("#306 every job that runs receipts.py checks the scripts out whole", sorted(n for n, t in runs.items() if not whole(t)), [])
        # C5 (#564): every event of an issue puts whom it waits on on its
        # board (waiting.py update, which hands it to `waits` here).
        issues_wf = yaml.safe_load(open(os.path.join(HERE, "..", ".github", "workflows", "issues.yml"), encoding="utf-8"))
        upd = yaml.safe_load(open(os.path.join(HERE, "..", ".github", "workflows", "waiting-update.yml"), encoding="utf-8"))
        check("C5 every event of an issue puts whom it waits on on its board",
              (issues_wf["jobs"]["waiting"]["uses"], any("waiting.py update" in (st.get("run") or "") for st in upd["jobs"]["update"]["steps"]),
               "receipts.py\"), \"waits\"" in open(os.path.join(HERE, "waiting.py"), encoding="utf-8").read()),
              ("./.github/workflows/waiting-update.yml", True, True))
    except ImportError:
        print("skip the workflow's wiring (no PyYAML here)")
    if not failed:
        print("all tests passed")
    return failed


def main(argv):
    if argv[:1] == ["--test"]:
        return self_test()
    mode = argv[0] if argv else ""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    number = int(os.environ.get("NUMBER", "0") or 0)
    body = open(os.environ["BODY"], encoding="utf-8").read() if os.environ.get("BODY") else ""
    policy_ref = os.environ.get("POLICY_REF")
    if mode == "seal-prd":
        at = now()
        s = seal(number, body, os.environ.get("ACCEPTED_BY", "?"), policy_ref, at, os.environ.get("ACCEPTED_HOW") or None)
        write(repo, f"issues/{number}/prd-{at}.json", s, f"Seal #{number}'s PRD")
        print(json.dumps(s))
        return 0
    if mode == "seal-spec":
        at = now()
        s = {"kind": "spec-seal", "issue": number, "spec_sha256": spec_hash(body), "at": at,
             "policy": f"DiluxOne/.github@{policy_ref}" if policy_ref else None}
        write(repo, f"issues/{number}/spec-{at}.json", s, f"Seal #{number}'s Spec")
        print(json.dumps(s))
        return 0
    if mode == "verify-spec":
        try:
            seals = [n for n in list_dir(repo, f"issues/{number}") if n.startswith("spec-")]
            sealed = read(repo, f"issues/{number}/{seals[-1]}") if seals else None
        except Exception as e:  # noqa: BLE001
            print(f"error: {e}")
            return 2
        if not sealed:
            print("unsealed")
            return 1
        live = spec_hash(body)
        v = "match" if live is not None and sealed.get("spec_sha256") == live else "changed"
        print(v)
        return 0 if v == "match" else 1
    if mode == "verify-prd":
        tries = int(argv[2]) if argv[1:2] == ["--wait"] and len(argv) > 2 else 1
        try:
            import time
            v = wait_verdict(lambda: verdict(body, last_seal(repo, number)), tries, lambda: time.sleep(10))
        except Exception as e:  # noqa: BLE001 — any failure to read is "unknown", never "unsealed" nor "changed"
            print(f"error: {e}")
            return 2
        print(v)
        return 1 if v == "changed" else 0
    if mode == "sealed-prd":
        try:
            last = last_seal(repo, number)
        except Exception as e:  # noqa: BLE001 — unknown, never "not sealed"
            print(f"error: {e}", file=sys.stderr)
            return 2
        text = sealed_prd(last) or sealed_prd(last, edit_history(repo, number))
        if text:
            print(text)
        return 0 if text else 1
    if mode == "own-bug":
        try:
            last = last_seal(repo, number)
        except Exception as e:  # noqa: BLE001 — unknown, never read as accepted
            print(f"error: {e}", file=sys.stderr)
            return 2
        ok = own_bug_accepted(last, body, os.environ.get("AUTHOR", ""))
        print("yes" if ok else "no")
        return 0 if ok else 1
    if mode == "merged":
        pr = json.loads(os.environ.get("PR_JSON", "{}"))
        checks = json.loads(os.environ.get("CHECKS_JSON", "{}"))
        # #804: the lane in force and the pull request's last merge
        # decision, from the receipts; a read that fails stops it, never a
        # receipt that would say less than what was decided.
        lane_lanes = lane_decisions(repo, number)
        merges = merge_decisions(repo, pr["number"]) if pr.get("number") else []
        r = receipt(number, body, last_seal(repo, number), pr, checks, policy_ref, now(),
                    lane_in_force(lane_lanes), merges[-1] if merges else None)
        write(repo, f"issues/{number}/merged-{r['at']}.json", r, f"Receipt for #{number}")
        print(json.dumps(r))
        return 0
    if mode == "lane-decision":
        decided = os.environ.get("DECIDED") or "policy"
        lane = os.environ.get("LANE", "")
        if decided == "withdrawn" and number > 0:
            # Only a lane in force is withdrawn; LANE may be left out.
            in_force = lane_in_force(lane_decisions(repo, number))
            if not in_force:
                print(f"#{number}: no lane in force, nothing to withdraw")
                return 0
            lane = lane or in_force["lane"]
        rule = os.environ.get("RULE") or None
        if decided not in DECIDED or not valid_lane(lane) or number <= 0 or (rule and not valid_rule(rule)):
            print("lane-decision needs NUMBER, a plain LANE, DECIDED policy or withdrawn, and a plain RULE when one is given", file=sys.stderr)
            return 64
        evidence = json.loads(os.environ.get("EVIDENCE_JSON") or "null")
        at = now()
        d = lane_decision(number, lane, policy_ref, at, run_url(), evidence, decided, rule)
        write(repo, f"issues/{number}/lane-{at}.json", d, f"Lane {lane} for #{number}: {decided}")
        print(json.dumps(d))
        return 0
    if mode == "merge-decision":
        decided = os.environ.get("DECIDED") or "policy"
        pr_n = int(os.environ["PR"]) if os.environ.get("PR", "").isdigit() else 0
        head, rule = os.environ.get("HEAD", ""), os.environ.get("RULE", "")
        if decided not in DECIDED or pr_n <= 0 or not re.match(r"^[0-9a-zA-Z]{1,64}$", head) or (decided == "policy" and not valid_rule(rule)):
            print("merge-decision needs PR, HEAD, DECIDED policy or withdrawn, and a plain RULE when it is the policy's", file=sys.stderr)
            return 64
        if decided == "withdrawn":
            last = merge_decisions(repo, pr_n)
            if not last or last[-1].get("decided") != "policy":
                print(f"#{pr_n}: no merge decision in force, nothing to withdraw")
                return 0
            rule = rule or last[-1].get("rule")
        at = now()
        d = merge_decision(pr_n, decided, rule or None, head, policy_ref, at, run_url())
        write(repo, f"pulls/{pr_n}/merge-{at}.json", d, f"Merge of #{pr_n}: {decided}")
        print(json.dumps(d))
        return 0
    if mode == "lane":
        # The lane in force, as JSON: exit 0 with it, 1 (null) with none,
        # 2 when the receipts cannot be read, never taken as a lane.
        try:
            in_force = lane_in_force(lane_decisions(repo, number))
        except Exception as e:  # noqa: BLE001
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(json.dumps(in_force))
        return 0 if in_force else 1
    if mode == "decisions":
        # The rows the weekly digest reads (#804), one JSON line each; exit
        # 2 when the receipts cannot be read, never an empty week.
        since = argv[2] if argv[1:2] == ["--since"] and len(argv) > 2 else ""
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", since):
            print("decisions needs --since YYYY-MM-DD", file=sys.stderr)
            return 64
        try:
            rows = decision_rows(tree_paths(repo), lambda p: read(repo, p), since)
        except Exception as e:  # noqa: BLE001
            print(f"error: {e}", file=sys.stderr)
            return 2
        for row in rows:
            print(json.dumps(dict(row, repository=repo), sort_keys=True))
        return 0
    if mode in ("board", "state", "waits", "migrate"):
        comments = bot_comments(repo, number)
        cid, current = board_comment(repo, number, comments)
        state, intact = parse_state(current)
        m = STATE_RE.search(current or "")
        raw = m.group(0) if m and not intact else ""
        is_pr = os.environ.get("ITEM") == "pr"
        if mode == "state" and argv[1:2] == ["get"]:
            print(json.dumps(state.get(argv[2]) if len(argv) > 2 else state))
            return 0 if intact else 3
        if not is_pr and not os.environ.get("BODY") and repo and not os.environ.get("RECEIPTS_FIXTURE"):
            # #802: a writer with no copy of the issue's body (the sweep,
            # the review's reply) still draws its G1 row right.
            body = issue_body(repo, number)
        # What the issue's board shows besides its state, read once, before
        # the state is read again just ahead of the write (#802): a writer
        # that sets its own keys then loses no other writer's.
        ctx = []

        def gather():
            names = [n for n in list_dir(repo, f"issues/{number}") if n.startswith("merged-")]
            return (schema_mod.check(body)["ok"], last_seal(repo, number), read(repo, f"issues/{number}/{names[-1]}") if names else None,
                    autopilot_state(repo, number), issue_labels(repo, number), holder(repo, number), lane_in_force(lane_decisions(repo, number)))

        def render(st):
            if is_pr:
                return pr_board_text(st, intact, raw)
            ready, seal_, merged, auto, labels, held, lane = ctx[0]
            return board_text(number, ready, seal_, merged, auto, labels, held, st, intact, raw, lane)
        if not is_pr and mode != "migrate":
            ctx.append(gather())

        def fresh():
            """(comment id, state) read again, just before a write."""
            c, text = board_comment(repo, number)
            st, ok = parse_state(text)
            if not ok:
                raise RuntimeError("the board's state was edited by hand while it was being written")
            return c, st
        if mode == "board":
            print(render(state))
            return 0
        old = old_labels(item_labels(repo, number)) if mode == "migrate" else []
        if mode == "migrate" and not old:
            # Nothing to move, whatever the board: an item with no old label
            # is never stopped by a board edited by hand (#802).
            print(f"#{number}: no old label of the flow")
            return 0
        if not intact:
            print("The board's state was edited by hand: nothing is set on it, nobody is mentioned"
                  + (" (its old labels stay on it)" if old else "") + ".", file=sys.stderr)
            return 3
        if mode == "state" and argv[1:2] == ["set"]:
            changes = {}
            for pair in argv[2:]:
                key, _, value = pair.partition("=")
                changes[key] = json.loads(value) if value else None
            cid, state = fresh()
            state = set_keys(state, changes)
            put_board(repo, number, cid, render(state))
            print(f"#{number}'s board: " + json.dumps(changes, sort_keys=True))
            return 0
        if mode == "migrate":
            # #802: the flow's old labels onto the board: written, read
            # back and compared, and only then taken off. Once more, it
            # finds none and does nothing (above).
            core = core_of(comments) if "autopilot:core-wait" in old else None
            cid, st = fresh()
            want = state_from_labels(old, st, core)
            if want != st:
                if not is_pr:
                    ctx.append(gather())
                put_board(repo, number, cid, render(want))
            back, ok = parse_state(board_comment(repo, number)[1])
            if not ok or any(back.get(k) != want.get(k) for k in FLOW_KEYS):
                print(f"#{number}'s board does not hold what its labels said: they stay on it.", file=sys.stderr)
                return 1
            for label in old:
                remove_label(repo, number, label)
            print(f"#{number}: {', '.join(old)} moved onto its board: " + json.dumps({k: back[k] for k in FLOW_KEYS if k in back}, sort_keys=True))
            return 0
        if mode == "waits":
            waits = json.loads(os.environ.get("WAITS_JSON") or "null")

            def put_waits(st):
                c, now_ = fresh()
                put_board(repo, number, c, render(set_keys(now_, {"waits": st.get("waits"), "mentioned": st.get("mentioned")})))
            text = announce(state, waits, [b for _, b in comments], put_waits,
                            lambda t: post_comment(repo, number, t))
            print(f"#{number} waits on {(waits or {}).get('who') or (waits or {}).get('role') or 'nobody'}" + ("; mentioned" if text else ""))
            return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
