#!/usr/bin/env python3
"""Receipts (#81): what was accepted, sealed; what was merged, proven.

Every seal and every receipt is a JSON file that dilux-bot commits to the
repository's `receipts` branch: an orphan branch (no history shared with the
code) that an organisation ruleset lets only dilux-bot create or update and
nobody delete or rewrite. A GitHub App's commits made through the API are
signed by GitHub and show as Verified.

  receipts.py seal-prd     on acceptance: the PRD's SHA-256, who accepted, when
                           (issues/<n>/prd-<UTC>.json)
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
  receipts.py merged       when the issue closes as completed: the receipt
                           (issues/<n>/merged-<UTC>.json; a reopened and
                           merged-again issue gets another): PRD and Spec hashes, the
                           pull request, its head commit, its checks, the
                           review's verdict, the criteria, the policy's commit,
                           who accepted and who merged
  receipts.py board        the issue's board: one bot comment, kept up to date
                           (it carries the board's state, below, as it was)
  receipts.py state get [KEY]        the board's state (#564), or one key of
                           it: a string printed bare, anything else as JSON,
                           nothing when it is not set
  receipts.py state set KEY=VALUE…   sets keys (VALUE read as JSON when it is
                           JSON, else as a string; `KEY=` removes the key)
  receipts.py state incr KEY         adds one to a number and prints it
  receipts.py state add KEY VALUE    adds VALUE to a list, once
  receipts.py state del KEY VALUE    takes VALUE out of a list
  receipts.py --test       self-test

The board's state (#564): what labels used to carry and is neither a
decision nor a warning a person reads at a glance (counters and the steps in
between) lives in a hidden block of the board, the one bot comment of an
issue or a pull request: `<!-- dx-state v1 {json} sha256=<hash> -->`. Only a
comment of the bot (DX_BOT_APP) that starts with the board's marker is read,
never another one; a block whose hash does not match what it holds was
edited by hand and reads as tampered (`tampered: true`), which the readers
take as the most restrictive state. Its keys:

  runs, free     the autopilot's runs that count, and the free ones (lists of N)
  rounds         the review rounds the autopilot answered (a number)
  waiting        the autopilot asked and waits for an answer (true)
  answered       a maintainer answered: the run it starts is free (true)
  verdict        the triage's category (bug, enhancement, question, ...)
  layer          where a defect shows (logic, browser, cli, api, workflow)
  repro          the reproduction: unconfirmed, confirmed,
                 could-not-reproduce, no-way, blocked or broken
  revert         a pull request of G8 that reverts a merge (true); reverted,
                 the issue or pull request it reverted (true)
  claim_long     a long claim, never released for want of a pull request
  spike          a person asked for an investigation first
  review_full    the next review is a full pass
  waits_on       {who, what, url}: the "Waits on" row of the board
  mentioned      the "login|step" mentions already posted, once each

Environment: GH_TOKEN; GITHUB_REPOSITORY (owner/name); NUMBER (the issue);
BODY (a file holding the issue's body); ACCEPTED_BY (seal-prd); POLICY_REF
(the commit of DiluxOne/.github whose policy applied); RECEIPTS_FIXTURE (a
directory standing in for the branch, for the self-test); STATE_FIXTURE (a
JSON file of an item's comments standing in for GitHub's, for the
self-test); DX_BOT_APP (the bot App's slug); STATE_SETTLE (the seconds a
state write waits before it reads the board again to check that it held, 2).
"""
import base64
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("issue_schema", os.path.join(HERE, "issue-schema.py"))
schema_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(schema_mod)

BRANCH = "receipts"
BOARD = "<!-- dx-board -->"
STATE_RE = re.compile(r"<!-- dx-state v1 (\{.*?\}) sha256=([0-9a-f]{64}) -->", re.S)
WAITS = "<!-- dx-waits -->"
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

def seal(number, body, accepted_by, policy_ref, at):
    return {"kind": "prd-seal", "issue": number, "prd_sha256": prd_hash(body), "accepted_by": accepted_by,
            "at": at, "policy": f"DiluxOne/.github@{policy_ref}" if policy_ref else None}


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


def receipt(number, body, last_seal, pr, checks, policy_ref, at):
    labels = [l for l in pr.get("labels", [])]
    pick = lambda prefix: next((l.split(":", 1)[1] for l in labels if l.startswith(prefix + ":")), None)
    result = schema_mod.check(body, "spec" if schema_mod.part_text(body, "spec") else "prd")
    return {
        "kind": "merge-receipt", "issue": number, "at": at,
        "prd_sha256": prd_hash(body), "prd_matches_seal": verdict(body, last_seal) == "match",
        "spec_sha256": spec_hash(body),
        "accepted_by": (last_seal or {}).get("accepted_by"),
        "pull_request": pr.get("number"), "head_commit": pr.get("head"), "merge_commit": pr.get("merge"),
        "merged_by": "policy" if "merged-by:policy" in labels else pr.get("merged_by"),
        "review": {"risk": pick("risk"), "complexity": pick("complexity"), "type": pick("type")},
        "checks": checks,
        "criteria": result.get("criteria", []),
        "policy": f"DiluxOne/.github@{policy_ref}" if policy_ref else None,
    }


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


def rule_link(policy):
    """A link to the autonomy policy as a decision read it: at its commit
    ("DiluxOne/.github@<ref>", as seals and receipts keep it), else main."""
    ref = (policy or "").partition("@")[2] or "main"
    return f"[the rule](https://github.com/DiluxOne/.github/blob/{ref}/policy/autonomy.yml)"


def board_text(number, ready, last_seal, merged, autopilot=None, labels=(), state=None):
    rows = ["| Gate | State |", "| --- | --- |"]
    rows.append(f"| G1 Issue ready | {'✓ the PRD follows the schema' if ready else '✗ see the G1 comment'} |")
    lane = next((l[5:] for l in labels if l.startswith("lane:")), None)
    if last_seal:
        by = last_seal.get("accepted_by") or ""
        # A lane seals as "policy (lane <name>)": it links the rule it followed (#188).
        if by.startswith("policy (lane "):
            by = f"{by}, {rule_link(last_seal.get('policy'))}"
        rows.append(f"| G2 Accepted | ✓ by {by} at {last_seal.get('at')}; PRD sealed `{last_seal.get('prd_sha256', '')[:12]}` |")
    elif lane and "accepted-by:policy" in labels:
        # Every automatic decision links the rule it followed (#188).
        rows.append(f"| G2 Accepted | ✓ by policy, lane `{lane}` ({rule_link(None)}) |")
    else:
        rows.append("| G2 Accepted | not sealed |")
    row = autopilot_row(autopilot)
    if row:
        rows.append(row)
    if merged:
        by = f"policy ({rule_link(merged.get('policy'))})" if merged.get("merged_by") == "policy" else merged.get("merged_by")
        rows.append(f"| G7 Merged | ✓ #{merged.get('pull_request')} by {by}; receipt in `receipts/issues/{number}/merged-{merged.get('at')}.json` |")
    state = dict(state or {})
    return f"{BOARD}\n**The issue's board**\n\n" + "\n".join(rows) + "\n" + waits_line(state) + f"\n\n{AI}\n" + state_block(state)


# --- the board's state (#564) ----------------------------------------------

def canonical(state):
    return json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=True).replace(">", "\\u003e")


def state_block(state):
    text = canonical(state)
    return f"<!-- dx-state v1 {text} sha256={sha(text)} -->"


def parse_state(body):
    """The state a board's body holds: {} when it holds none; with
    `tampered: true` when its hash does not match what it holds. Pure."""
    m = STATE_RE.search(body or "")
    if not m:
        return {}
    try:
        state = json.loads(m.group(1))
    except ValueError:
        return {"tampered": True}
    if not isinstance(state, dict):
        return {"tampered": True}
    if sha(m.group(1)) != m.group(2):
        state["tampered"] = True
    return state


def waits_line(state):
    """The board's "Waits on" row: who, what and the link; a dash when
    nothing waits on anyone. Pure."""
    w = (state or {}).get("waits_on") or {}
    if not w.get("who"):
        return f"| Waits on | nobody {WAITS} |"
    who = w["who"] if " " in w["who"] else f"@{w['who'].lstrip('@')}"
    link = f" {w['url']}" if w.get("url") else ""
    return f"| Waits on | {who}: {w.get('what', '')}{link} {WAITS} |"


def wait_on(state, who, what="", url="", person=True, sender=""):
    """(the state with its "Waits on" row set, the one mention to post or
    None) (#564). `who` empty: nothing waits. A person (`person`, `who` a
    login) is mentioned once per waiting step (`login|what`, kept in
    `mentioned`), never again, and never for what they just did themselves
    (`sender`, whose step is recorded as mentioned). Pure."""
    new = dict(state or {})
    if not who:
        new.pop("waits_on", None)
        return new, None
    new["waits_on"] = {"who": who, "what": what, "url": url}
    if not person:
        return new, None
    key = f"{who}|{what}"
    seen = [m for m in (new.get("mentioned") or []) if isinstance(m, str)]
    if key in seen:
        return new, None
    new["mentioned"] = seen + [key]
    if sender and sender.lower() == who.lower():
        return new, None
    return new, f"@{who}: {what} {url}".rstrip()


def with_state(body, state):
    """A board's body with its state block and its "Waits on" row replaced
    (added when missing). Pure."""
    # A tampered state stays so (it is written back with `tampered: true`):
    # writing it again never launders a hand edit.
    body = STATE_RE.sub("", body or "").rstrip()
    line = waits_line(state)
    lines = body.split("\n")
    at = next((i for i, l in enumerate(lines) if WAITS in l), None)
    if at is not None:
        lines[at] = line
    else:
        last = max((i for i, l in enumerate(lines) if l.startswith("|")), default=None)
        if last is None:
            lines[1:1] = ["", "| Gate | State |", "| --- | --- |", line]
        else:
            lines.insert(last + 1, line)
    return "\n".join(lines) + "\n" + state_block(state)


def apply(state, op, args):
    """The state after one `state` operation. Pure."""
    state = dict(state)
    if op == "set":
        for a in args:
            k, _, v = a.partition("=")
            if k == "tampered":
                continue
            if not v:
                state.pop(k, None)
                continue
            try:
                state[k] = json.loads(v)
            except ValueError:
                state[k] = v
    elif op == "incr":
        state[args[0]] = int(state.get(args[0]) or 0) + 1
    elif op == "add":
        cur = list(state.get(args[0]) or [])
        v = _value(args[1])
        if v not in cur:
            cur.append(v)
        state[args[0]] = cur
    elif op == "del":
        v = _value(args[1])
        state[args[0]] = [x for x in (state.get(args[0]) or []) if x != v]
    return state


def _value(v):
    try:
        return json.loads(v)
    except ValueError:
        return v


def show(value):
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value)


def bot_app():
    if os.environ.get("DX_BOT_APP"):
        return os.environ["DX_BOT_APP"]
    try:
        spec = importlib.util.spec_from_file_location("org", os.path.join(HERE, "org.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.APP
    except Exception:  # noqa: BLE001
        return "dilux-bot"


def comments(repo, number):
    if os.environ.get("STATE_FIXTURE"):
        p = os.environ["STATE_FIXTURE"]
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else []
    out = subprocess.run(["gh", "api", f"repos/{repo}/issues/{number}/comments", "--paginate"], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:300])
    # --paginate prints one JSON array per page.
    return [c for page in json.loads("[" + re.sub(r"\]\s*\[", "],[", out.stdout.strip() or "[]") + "]") for c in page]


def board_comment(cs, app):
    """The bot's board among an item's comments (its last), never another
    person's comment. Pure."""
    mine = [c for c in cs if (c.get("user") or {}).get("type") == "Bot" and str((c.get("user") or {}).get("login", "")).startswith(app)
            and str(c.get("body") or "").startswith(BOARD)]
    return mine[-1] if mine else None


# The state each item's board held when this process last read it: the base
# a write's change is measured from (#567).
_READ = {}


def merge(fresh, base, new):
    """`fresh` with the change from `base` to `new` applied, and nothing
    else of `new`: a key the writer did not touch keeps what another writer
    put there; a list gains the items the writer added and loses the ones it
    took out, whatever else it holds. Pure."""
    out = dict(fresh)
    for k in set(base) | set(new):
        b, n = base.get(k), new.get(k)
        if b == n:
            continue
        if k not in new:
            out.pop(k, None)
        elif isinstance(n, list) and isinstance(b, (list, type(None))):
            cur = [x for x in (out.get(k) if isinstance(out.get(k), list) else []) if x not in (b or []) or x in n]
            out[k] = cur + [x for x in n if x not in (b or []) and x not in cur]
        else:
            out[k] = n
    return out


def read_state(repo, number):
    c = board_comment(comments(repo, number), bot_app())
    state = parse_state(c.get("body")) if c else {}
    _READ[(repo, str(number))] = dict(state)
    return state


def _put(repo, number, cs, c, body):
    if os.environ.get("STATE_FIXTURE"):
        if c:
            c["body"] = body
        else:
            cs.append({"id": len(cs) + 1, "user": {"login": f"{bot_app()}[bot]", "type": "Bot"}, "body": body})
        json.dump(cs, open(os.environ["STATE_FIXTURE"], "w", encoding="utf-8"))
    elif c:
        gh("-X", "PATCH", f"repos/{repo}/issues/comments/{c['id']}", "--input", "-", data={"body": body})
    else:
        gh("-X", "POST", f"repos/{repo}/issues/{number}/comments", "--input", "-", data={"body": body})


def write_state(repo, number, state, title="The board", tries=5):
    """Writes the state on the item's board: the board's comment edited,
    or a new one when it has none yet. Several workflows write the same
    board and GitHub offers no compare-and-swap on a comment (#567), so only
    this writer's change (from the state it last read) is applied, on the
    board as it is right before the write; then the board is read again, a
    moment later, and the change written again if a writer that read before
    it landed on top of it."""
    key = (repo, str(number))
    base = _READ.get(key)
    settle = 0 if os.environ.get("STATE_FIXTURE") else float(os.environ.get("STATE_SETTLE", "2"))
    for attempt in range(tries):
        cs = comments(repo, number)
        c = board_comment(cs, bot_app())
        fresh = parse_state(c.get("body")) if c else {}
        target = state if base is None else merge(fresh, base, state)
        if c and target == fresh:
            _READ[key] = fresh
            return
        _put(repo, number, cs, c, with_state(c["body"] if c else f"{BOARD}\n**{title}**\n\n{AI}", target))
        if base is None:
            base = fresh
        if settle:
            import time
            time.sleep(settle * (attempt + 1))
        c = board_comment(comments(repo, number), bot_app())
        got = parse_state(c.get("body")) if c else {}
        if c and merge(got, base, state) == got:
            _READ[key] = got
            return
    raise RuntimeError(f"#{number}: the board's state kept changing under this write ({tries} tries)")


def issue_labels(repo, number):
    """The issue's labels, read from GitHub (LABELS_JSON stands in for them
    in the self-test); none when they cannot be read: the board then says
    less, never something wrong."""
    if os.environ.get("LABELS_JSON"):
        return json.loads(os.environ["LABELS_JSON"])
    out = subprocess.run(["gh", "issue", "view", str(number), "--repo", repo, "--json", "labels", "--jq", "[.labels[].name]"],
                         capture_output=True, text=True)
    return json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else []


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
        "content": "# Receipts\n\nSeals and receipts of this repository's issues, written by dilux-bot (DiluxOne/.github, scripts/receipts.py). Nobody else writes here, and nothing here is deleted or rewritten.\n"}]})
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
    # Never an overwrite: without a sha, the API refuses a path that exists.
    payload = {"message": message, "branch": BRANCH, "content": base64.b64encode((json.dumps(obj, indent=2) + "\n").encode()).decode()}
    gh("-X", "PUT", f"repos/{repo}/contents/{path}", "--input", "-", data=payload)


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


def read(repo, path):
    if os.environ.get("RECEIPTS_FIXTURE"):
        with open(os.path.join(os.environ["RECEIPTS_FIXTURE"], path), encoding="utf-8") as f:
            return json.load(f)
    return json.loads(base64.b64decode(gh(f"repos/{repo}/contents/{path}?ref={BRANCH}")["content"]))


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
    check("merged by policy says so", receipt(7, body, s, pr2, {}, None, "t")["merged_by"], "policy")
    b = board_text(7, True, s, r)
    check("the board starts with its marker", b.startswith(BOARD), True)
    check("the board shows the seal", "PRD sealed" in b and s["prd_sha256"][:12] in b, True)
    a = {"pr": 12, "url": "https://github.com/o/r/pull/12", "draft": True, "state": "OPEN", "done": 1, "total": 3, "run": "https://github.com/o/r/actions/runs/9"}
    ab = board_text(7, True, s, None, a)
    check("C6: the board links the pull request and the run, with the progress", ("[#12](https://github.com/o/r/pull/12)" in ab, "[the run](https://github.com/o/r/actions/runs/9)" in ab, "1 of 3 criteria" in ab), (True, True, True))
    check("C6: a person's pull request says so", "a person has it" in board_text(7, True, s, None, dict(a, needs_human=True)), True)
    check("C6: no autopilot, no row", "Autopilot" in board_text(7, True, s, None, None), False)
    lb = board_text(7, True, None, None, None, ["lane:platform", "accepted-by:policy"])
    check("#188: a lane's acceptance names the lane and links its rule", "✓ by policy, lane `platform` ([the rule](https://github.com/DiluxOne/.github/blob/main/policy/autonomy.yml))" in lb, True)
    ls = seal(7, body, "policy (lane bugfix-reproduced)", "def456", "t")
    check("#188: a lane's sealed acceptance links the rule at its commit", "✓ by policy (lane bugfix-reproduced), [the rule](https://github.com/DiluxOne/.github/blob/def456/policy/autonomy.yml) at t" in board_text(7, True, ls, None), True)
    check("#188: a person whose login starts with policy is a person", "policyfoo at" in board_text(7, True, seal(7, body, "policyfoo", "x", "t"), None), True)
    check("#188: a lane's label alone is no acceptance", "not sealed" in board_text(7, True, None, None, None, ["lane:platform"]), True)
    mb = board_text(7, True, s, receipt(7, body, s, pr2, {}, "abc123", "t"))
    check("#188: a merge by policy links the rule at the commit it read", "by policy ([the rule](https://github.com/DiluxOne/.github/blob/abc123/policy/autonomy.yml))" in mb, True)
    check("#188: a person's merge names the person", "by soydiloreto;" in b, True)
    # The board's state (#564): counters and steps round-trip, a hand edit is caught.
    st = apply(apply(apply(apply({}, "add", ["runs", "1"]), "add", ["free", "2"]), "incr", ["rounds"]),
               "set", ["layer=browser", "repro=no-way", "waiting=true"])
    check("C1: counters and steps round-trip through the board", parse_state(board_text(7, True, s, None, None, (), st)),
          {"runs": [1], "free": [2], "rounds": 1, "layer": "browser", "repro": "no-way", "waiting": True})
    check("C1: add is once, del takes it out, set with nothing removes", (apply(apply({"runs": [1]}, "add", ["runs", "1"]), "del", ["runs", "1"]),
          apply({"layer": "cli"}, "set", ["layer="])), ({"runs": []}, {}))
    blk = state_block({"runs": [1]})
    check("C1: a hand-edited counter reads as tampered", parse_state(blk.replace('"runs":[1]', '"runs":[]'))["tampered"], True)
    check("C1: a tampered state stays tampered when written again", parse_state(with_state(BOARD, parse_state(blk.replace("[1]", "[]"))))["tampered"], True)
    check("C1: set never clears tampered", apply({"tampered": True}, "set", ["tampered=false"])["tampered"], True)
    check("C1: no state reads as empty", parse_state("<!-- dx-board -->\nno state"), {})
    check("C1: a closing comment in a value cannot end the block", parse_state(state_block({"x": "a --> b"})), {"x": "a --> b"})
    bot, person = {"login": "dilux-bot[bot]", "type": "Bot"}, {"login": "mallory", "type": "User"}
    forged = {"user": person, "body": BOARD + "\n" + state_block({"runs": []})}
    real = {"user": bot, "body": BOARD + "\n" + state_block({"runs": [1, 2]})}
    check("C1: the state is read from the bot's board only, never a person's comment", board_comment([real, forged], "dilux-bot")["body"], real["body"])
    check("C1: a person's comment alone is no board", board_comment([forged], "dilux-bot"), None)
    wb = with_state(board_text(7, True, s, None), {"waits_on": {"who": "alice", "what": "answer the question", "url": "https://github.com/o/r/issues/7#c"}})
    check("C5: the board names whom it waits on, with the action and the link", "| Waits on | @alice: answer the question https://github.com/o/r/issues/7#c" in wb, True)
    check("C5: the row is replaced, never repeated", with_state(wb, {}).count("| Waits on |"), 1)
    check("C5: nobody waited on says so", "| Waits on | nobody" in with_state(wb, {}), True)
    # #564 C5: when it waits on the issue's author (an outside contributor),
    # the board names them and they are mentioned once, on the item.
    url = "https://github.com/o/r/issues/7"
    st1, said1 = wait_on({}, "alice", "Complete the PRD of", url)
    check("C5: the board names the author it waits on", waits_line(st1), f"| Waits on | @alice: Complete the PRD of {url} {WAITS} |")
    check("C5: and mentions them, with the action and its URL", said1, f"@alice: Complete the PRD of {url}")
    st2, said2 = wait_on(st1, "alice", "Complete the PRD of", url)
    check("C5: once: the same step again mentions nobody", (said2, st2["mentioned"]), (None, ["alice|Complete the PRD of"]))
    check("C5: the mention survives a board written again", parse_state(with_state(with_state(board_text(7, True, s, None), st1), st2)).get("mentioned"), ["alice|Complete the PRD of"])
    st3, said3 = wait_on(st2, "alice", "Answer the triage's question on", url)
    check("C5: a new step of theirs mentions them again", said3, f"@alice: Answer the triage's question on {url}")
    check("C5: the autopilot's step names it, mentions nobody", wait_on({}, "the autopilot", "The autopilot works on", url, person=False), ({"waits_on": {"who": "the autopilot", "what": "The autopilot works on", "url": url}}, None))
    check("C5: what they just did themselves mentions nobody, and is recorded", wait_on({}, "Alice", "Complete the PRD of", url, sender="alice"), ({"waits_on": {"who": "Alice", "what": "Complete the PRD of", "url": url}, "mentioned": ["Alice|Complete the PRD of"]}, None))
    check("C5: nothing waits: the row goes, the mentions stay", wait_on(st2, ""), ({"mentioned": ["alice|Complete the PRD of"]}, None))
    with tempfile.TemporaryDirectory() as d:
        fx = os.path.join(d, "comments.json")
        env0 = dict(os.environ, STATE_FIXTURE=fx, GITHUB_REPOSITORY="o/r", NUMBER="3", DX_BOT_APP="dilux-bot")
        st_run = lambda *a: subprocess.run([sys.executable, os.path.abspath(__file__), "state"] + list(a), env=env0, capture_output=True, text=True)
        check("cli: state get on an item with no board is empty", st_run("get", "layer").stdout.strip(), "")
        st_run("set", "layer=browser", "repro=no-way")
        check("cli: state set makes the board", (st_run("get", "layer").stdout.strip(), len(json.load(open(fx)))), ("browser", 1))
        check("cli: state incr counts", (st_run("incr", "rounds").stdout.strip(), st_run("incr", "rounds").stdout.strip()), ("1", "2"))
        st_run("add", "runs", "1")
        st_run("add", "runs", "2")
        check("cli: state add and get of a list", st_run("get", "runs").stdout.strip(), "[1, 2]")
        check("cli: the whole state", json.loads(st_run("get").stdout), {"layer": "browser", "repro": "no-way", "rounds": 2, "runs": [1, 2]})
        check("cli: one board comment, never more", len(json.load(open(fx))), 1)
    # Two writers of the same board (#567): each read it before the other
    # wrote; both changes survive, whichever writes last.
    with tempfile.TemporaryDirectory() as d:
        saved = {k: os.environ.get(k) for k in ("STATE_FIXTURE", "DX_BOT_APP")}
        os.environ.update(STATE_FIXTURE=os.path.join(d, "comments.json"), DX_BOT_APP="dilux-bot")
        try:
            _READ.clear()
            write_state("o/r", 5, apply(read_state("o/r", 5), "set", ["answered=true", "waiting=true"]))
            a, b = read_state("o/r", 5), read_state("o/r", 5)
            write_state("o/r", 5, apply(a, "set", ["waiting="]))
            _READ[("o/r", "5")] = b  # the second writer read before the first wrote
            write_state("o/r", 5, apply(apply(b, "add", ["runs", "3"]), "add", ["mentioned", "alice|x"]))
            check("race: a stale writer keeps the other's change", read_state("o/r", 5), {"answered": True, "runs": [3], "mentioned": ["alice|x"]})
            c, e = read_state("o/r", 5), read_state("o/r", 5)
            write_state("o/r", 5, apply(apply(c, "add", ["runs", "4"]), "set", ["answered="]))
            _READ[("o/r", "5")] = e
            write_state("o/r", 5, apply(apply(e, "add", ["free", "5"]), "add", ["mentioned", "bob|y"]))
            check("race: both writers' list items and cleared keys survive", read_state("o/r", 5),
                  {"runs": [3, 4], "free": [5], "mentioned": ["alice|x", "bob|y"]})
            # A writer that lands between our write and our check is caught,
            # and ours is written again on top of it.
            real, calls = globals()["comments"], []

            def racing(repo, number):
                cs = real(repo, number)
                calls.append(1)
                if len(calls) == 2:  # right after the first PATCH
                    board = board_comment(cs, "dilux-bot")
                    # The other writer read before ours landed: it drops our 9.
                    board["body"] = with_state(board["body"], apply(parse_state(board["body"]), "set", ["spike=true", "runs=[3,4]"]))
                    json.dump(cs, open(os.environ["STATE_FIXTURE"], "w", encoding="utf-8"))
                return cs
            stale = read_state("o/r", 5)
            globals()["comments"] = racing
            try:
                write_state("o/r", 5, apply(stale, "add", ["runs", "9"]))
            finally:
                globals()["comments"] = real
            got = read_state("o/r", 5)
            check("race: a write that lands right after ours is detected, and ours written again", (got.get("spike"), got.get("runs")), (True, [3, 4, 9]))
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            _READ.clear()
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
        env = dict(os.environ, STATE_FIXTURE=os.path.join(d, "comments.json"), AUTOPILOT_JSON="null", LABELS_JSON="[]", NUMBER="9", BODY=bf, GITHUB_REPOSITORY="o/r", ACCEPTED_BY="soydiloreto",
                   PR_JSON=json.dumps(pr), CHECKS_JSON='{"success": 3}')
        run = lambda *a: sp.run([sys.executable, os.path.abspath(__file__)] + list(a), env=env, capture_output=True, text=True)
        check("cli: verify an issue never sealed", run("verify-prd").stdout.strip(), "unsealed")
        check("cli: seal-prd writes a seal", run("seal-prd").returncode, 0)
        check("cli: verify the sealed PRD", run("verify-prd").stdout.strip(), "match")
        check("cli: merged writes a receipt", run("merged").returncode, 0)
        check("cli: the board shows the receipt", "G7 Merged" in run("board").stdout, True)
        check("cli: verify-spec with no Spec seal fails", run("verify-spec").returncode, 1)
        import time
        time.sleep(1.1)
        run("merged")
        check("cli: a second merge does not overwrite the first", len([n for n in os.listdir(os.path.join(d, "issues/9")) if n.startswith("merged-")]), 2)
        os.makedirs(os.path.join(d, "issues/10"))
        with open(os.path.join(d, "issues/10/prd-x.json"), "w") as f:
            f.write("{not json")
        r10 = sp.run([sys.executable, os.path.abspath(__file__), "verify-prd"], env=dict(env, NUMBER="10"), capture_output=True, text=True)
        check("cli: a seal that cannot be read exits 2", r10.returncode, 2)
        del os.environ["RECEIPTS_FIXTURE"]
    # A job that runs this script reads the organisation's scripts whole:
    # it loads autopilot.py for an autopilot pull request's board (#306).
    try:
        import yaml
        wf = yaml.safe_load(open(os.path.join(HERE, "..", ".github", "workflows", "issue-accepted.yml"), encoding="utf-8"))
        runs = {name: json.dumps(job) for name, job in wf["jobs"].items() if "receipts.py" in json.dumps(job)}
        check("#306 every job that runs receipts.py checks the scripts out whole", sorted(n for n, t in runs.items() if "git init -q .dx-central" not in t), [])
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
        s = seal(number, body, os.environ.get("ACCEPTED_BY", "?"), policy_ref, at)
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
    if mode == "merged":
        pr = json.loads(os.environ.get("PR_JSON", "{}"))
        checks = json.loads(os.environ.get("CHECKS_JSON", "{}"))
        r = receipt(number, body, last_seal(repo, number), pr, checks, policy_ref, now())
        write(repo, f"issues/{number}/merged-{r['at']}.json", r, f"Receipt for #{number}")
        print(json.dumps(r))
        return 0
    if mode == "board":
        ready = schema_mod.check(body)["ok"]
        names = [n for n in list_dir(repo, f"issues/{number}") if n.startswith("merged-")]
        merged = read(repo, f"issues/{number}/{names[-1]}") if names else None
        # The state is read first: a board written without it would lose it.
        state = read_state(repo, number)
        print(board_text(number, ready, last_seal(repo, number), merged, autopilot_state(repo, number), issue_labels(repo, number), state))
        return 0
    if mode == "state":
        op, args = (argv[1] if len(argv) > 1 else "get"), argv[2:]
        state = read_state(repo, number)
        if op == "get":
            print(show(state.get(args[0]) if args else state))
            return 0
        if op not in ("set", "incr", "add", "del") or (op != "set" and not args) or (op in ("add", "del") and len(args) < 2):
            print(__doc__, file=sys.stderr)
            return 64
        new = apply(state, op, args)
        if new != state:
            write_state(repo, number, new, os.environ.get("BOARD_TITLE", "The board"))
        if op == "incr":
            print(new[args[0]])
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
