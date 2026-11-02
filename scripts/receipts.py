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
                           who accepted and who merged
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
                           those keys set in the board's state, the board
                           rewritten; refused (exit 3) on a block edited by
                           hand
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
stands (whom it waits on, who was mentioned for which step), with a
SHA-256 of its content. It is read only from dilux-bot's own board comment;
a block whose hash does not match was edited by hand and reads as the most
restrictive state: nothing is set on it and nobody is mentioned from it.
"""
import base64
import datetime
import hashlib
import json
import os
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


def mention(state, waits):
    """(the comment that mentions the people it waits on, or None; the new
    state): once per person per waiting step (its `step`, else its action
    and link), never a bot, never a role."""
    step = (waits or {}).get("step") or (clean((waits or {}).get("what")) + " " + str((waits or {}).get("url") or ""))
    done = [k for k in (state.get("mentioned") or []) if isinstance(k, str)]
    new = [w for w in logins_of(waits) if f"{w.lower()}|{step}" not in done]
    if not new:
        return None, state
    url = str(waits.get("url") or "")
    text = " ".join(f"@{w}" for w in new) + f": {clean(waits.get('what'))}" + (f" {url}" if url.startswith("https://github.com/") else "")
    return f"{text}\n\n{AI}", dict(state, mentioned=(done + [f"{w.lower()}|{step}" for w in new])[-50:])


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


def board_text(number, ready, last_seal, merged, autopilot=None, labels=(), held="", state=None, intact=True, raw_state=""):
    rows = ["| Gate | State |", "| --- | --- |"]
    rows.append(f"| G1 Issue ready | {'✓ the PRD follows the schema' if ready else '✗ see the G1 comment'} |")
    # A person holds it (#488, #561): a claim, an assignment, their own
    # open pull request that closes it; the autopilot does not start.
    if held and not autopilot:
        rows.append(f"| Held | 🙋 {held}: the autopilot does not start |")
    lane = next((l[5:] for l in labels if l.startswith("lane:")), None)
    if last_seal:
        by = last_seal.get("accepted_by") or ""
        # A lane seals as "policy (lane <name>)": it links the rule it followed (#188).
        if by.startswith("policy (lane "):
            by = f"{by}, {rule_link(last_seal.get('policy'))}"
        # A maintainer's own Bug (#564): accepted with its writing.
        elif last_seal.get("how") == OWN_BUG:
            by = f"{by}, their own Bug, accepted with its writing,"
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
    if not intact:
        rows.append("| State | ✗ the board's state was edited by hand: the bot sets nothing on it and mentions nobody; a maintainer restores it |")
    row = waits_row((state or {}).get("waits")) if intact else None
    if row:
        rows.append(row)
    # The state block, hidden (#564): carried as it was when it was edited
    # by hand, so a person's edit is never given a valid hash.
    block = raw_state if not intact else (state_block(state) if state else "")
    return f"{BOARD}\n**The issue's board**\n\n" + "\n".join(rows) + f"\n\n{AI}" + (f"\n{block}" if block else "")


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


def board_comment(repo, number):
    """(id, body) of dilux-bot's board comment on the issue or pull
    request, or (None, ""); under RECEIPTS_FIXTURE, comments/<n>/board.md."""
    if os.environ.get("RECEIPTS_FIXTURE"):
        path = os.path.join(os.environ["RECEIPTS_FIXTURE"], "comments", str(number), "board.md")
        return (path, open(path, encoding="utf-8").read()) if os.path.exists(path) else (None, "")
    out = subprocess.run(["gh", "api", "--paginate", f"repos/{repo}/issues/{number}/comments",
                          "--jq", '.[] | select(.user.type == "Bot" and (.user.login | startswith("' + org.APP + '")) and (.body | startswith("' + BOARD + '"))) | {id, body}'],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"the board could not be read: {out.stderr.strip()[:200]}")
    found = [json.loads(l) for l in out.stdout.splitlines() if l.strip()]
    return (found[-1]["id"], found[-1]["body"]) if found else (None, "")


def put_board(repo, number, cid, text):
    """The board's comment written: edited when it exists, else created."""
    if os.environ.get("RECEIPTS_FIXTURE"):
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


# Two writers at once (two issues accepted together, #561): the second
# write's commit meets a branch head that just moved, and GitHub answers
# 409, or 422 on a stale head. Each try reads the head anew; a path that
# already exists is never written again.
WRITE_TRIES = 5


def put(repo, path, obj, message, api=None, nap=None):
    """Write one receipt on the branch, retrying when the branch moved under
    it (HTTP 409, or 422 on a sha or a conflict) up to WRITE_TRIES times
    with a short back-off; never an overwrite: without a sha the API
    refuses a path that exists, and a 422 for a path that exists ends
    there. api and nap are for the self-test."""
    api = api or gh
    nap = nap or time.sleep
    # Never an overwrite: without a sha, the API refuses a path that exists.
    payload = {"message": message, "branch": BRANCH, "content": base64.b64encode((json.dumps(obj, indent=2) + "\n").encode()).decode()}
    for n in range(1, WRITE_TRIES + 1):
        try:
            return api("-X", "PUT", f"repos/{repo}/contents/{path}", "--input", "-", data=payload)
        except RuntimeError as e:
            text = str(e)
            moved = "409" in text or ("422" in text and re.search(r"(?i)\bsha\b|conflict", text))
            if not moved or n == WRITE_TRIES:
                raise
            if "422" in text and exists(repo, path, api):
                raise RuntimeError(f"{path} exists; a receipt is never overwritten") from e
            nap(0.5 * 2 ** (n - 1))
    return None


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
    ob = seal(7, body, "boss", "abc123", "t", OWN_BUG)
    check("C2 (#564): a maintainer's own Bug is sealed so, by its author", (ob["how"], ob["accepted_by"], "how" in s), (OWN_BUG, "boss", False))
    check("C2 (#564): it is accepted for its author, while the PRD is the sealed one",
          (own_bug_accepted(ob, body, "boss"), own_bug_accepted(ob, body, "Boss"), own_bug_accepted(ob, body.replace("turns dark", "turns light"), "boss")), (True, True, False))
    check("C2 (#564): never for someone else, never from a person's seal, never with no seal",
          (own_bug_accepted(ob, body, "alice"), own_bug_accepted(ob, body, ""), own_bug_accepted(s, body, "soydiloreto"), own_bug_accepted(None, body, "boss")), (False, False, False, False))
    check("C2 (#564): the board says it was the author's own Bug", "✓ by boss, their own Bug, accepted with its writing, at t" in board_text(7, True, ob, None), True)
    check("#188: a person whose login starts with policy is a person", "policyfoo at" in board_text(7, True, seal(7, body, "policyfoo", "x", "t"), None), True)
    check("#188: a lane's label alone is no acceptance", "not sealed" in board_text(7, True, None, None, None, ["lane:platform"]), True)
    mb = board_text(7, True, s, receipt(7, body, s, pr2, {}, "abc123", "t"))
    check("#188: a merge by policy links the rule at the commit it read", "by policy ([the rule](https://github.com/DiluxOne/.github/blob/abc123/policy/autonomy.yml))" in mb, True)
    check("#188: a person's merge names the person", "by soydiloreto;" in b, True)
    # #564: the board's state, hidden, hashed, carried; whom it waits on.
    st = {"runs": 2, "waits": {"who": "alice", "what": "answer --> <b>", "url": "https://github.com/o/r/issues/7"}}
    blk = state_block(st)
    check("#564 the state round-trips through its block", parse_state("board\n" + blk), (st, True))
    check("#564 a value cannot end the comment it sits in", blk.count("-->"), 1)
    check("#564 no block is an empty state", parse_state("<!-- dx-board -->\nrows"), ({}, True))
    check("#564 a block edited by hand is not intact", parse_state(blk.replace('"runs":2', '"runs":0')), ({}, False))
    check("#564 nor is one that does not parse", parse_state("<!-- dx-state v1 {nope -->"), ({}, False))
    wb = board_text(7, True, s, None, state=st)
    check("C5 the board names whom it waits on, the action and its link, mentioning nobody",
          ("| Waits on | `alice`: answer --> <b> ([link](https://github.com/o/r/issues/7)) |" in wb, "@alice" in wb), (True, False))
    check("C5 its state is carried, hidden, at the end", wb.rstrip().endswith(blk), True)
    check("C5 a role is named as one", waits_row({"role": "a maintainer", "what": "accept it", "url": "https://github.com/o/r/issues/7"}), "| Waits on | a maintainer: accept it ([link](https://github.com/o/r/issues/7)) |")
    check("C5 a link that is not GitHub's is not linked", "evil" in (waits_row({"who": "alice", "what": "x", "url": "https://evil.example"}) or ""), False)
    tb = board_text(7, True, s, None, state={}, intact=False, raw_state=blk.replace('"runs":2', '"runs":0'))
    check("#564 a state edited by hand is said, kept as it was, and names nobody", ("edited by hand" in tb, '"runs":0' in tb, "Waits on" in tb), (True, True, False))
    w = {"who": "alice", "what": "complete the issue", "url": "https://github.com/o/r/issues/7"}
    t1, st1 = mention({}, w)
    t2, st2 = mention(st1, w)
    check("C5 the author is mentioned when it waits on them, with the action and its link", t1.startswith("@alice: complete the issue https://github.com/o/r/issues/7"), True)
    check("C5 once: the same step mentions nobody again", (t2, st2), (None, st1))
    check("C5 a new step mentions them again", mention(st1, dict(w, what="answer the question", url="https://github.com/o/r/issues/7#issuecomment-1"))[0] is not None, True)
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
    try:
        put("o/r", "issues/10/prd-1.json", {}, "x", api=always, nap=lambda s: None)
        capped = "written"
    except RuntimeError as e:
        capped = str(e)
    check("#561 C5: a branch that keeps moving fails after the tries, said", "409" in capped, True)
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
        check("#306 every job that runs receipts.py checks the scripts out whole", sorted(n for n, t in runs.items() if "git init -q .dx-central" not in t), [])
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
        r = receipt(number, body, last_seal(repo, number), pr, checks, policy_ref, now())
        write(repo, f"issues/{number}/merged-{r['at']}.json", r, f"Receipt for #{number}")
        print(json.dumps(r))
        return 0
    if mode in ("board", "state", "waits"):
        cid, current = board_comment(repo, number)
        state, intact = parse_state(current)
        m = STATE_RE.search(current or "")
        raw = m.group(0) if m and not intact else ""

        def render(st):
            if os.environ.get("ITEM") == "pr":
                return pr_board_text(st, intact, raw)
            names = [n for n in list_dir(repo, f"issues/{number}") if n.startswith("merged-")]
            merged = read(repo, f"issues/{number}/{names[-1]}") if names else None
            return board_text(number, schema_mod.check(body)["ok"], last_seal(repo, number), merged, autopilot_state(repo, number),
                              issue_labels(repo, number), holder(repo, number), st, intact, raw)
        if mode == "board":
            print(render(state))
            return 0
        if mode == "state" and argv[1:2] == ["get"]:
            print(json.dumps(state.get(argv[2]) if len(argv) > 2 else state))
            return 0 if intact else 3
        if not intact:
            print("The board's state was edited by hand: nothing is set on it, nobody is mentioned.", file=sys.stderr)
            return 3
        if mode == "state" and argv[1:2] == ["set"]:
            for pair in argv[2:]:
                key, _, value = pair.partition("=")
                state[key] = json.loads(value) if value else None
            put_board(repo, number, cid, render(state))
            return 0
        if mode == "waits":
            waits = json.loads(os.environ.get("WAITS_JSON") or "null")
            text, state = mention(dict(state, waits=waits), waits)
            put_board(repo, number, cid, render(state))
            if text:
                post_comment(repo, number, text)
            print(f"#{number} waits on {(waits or {}).get('who') or (waits or {}).get('role') or 'nobody'}" + ("; mentioned" if text else ""))
            return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
