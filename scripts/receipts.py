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
                           the seal could not be read (never taken as unsealed)
  receipts.py merged       when the issue closes as completed: the receipt
                           (issues/<n>/merged-<UTC>.json; a reopened and
                           merged-again issue gets another): PRD and Spec hashes, the
                           pull request, its head commit, its checks, the
                           review's verdict, the criteria, the policy's commit,
                           who accepted and who merged
  receipts.py board        the issue's board: one bot comment, kept up to date
  receipts.py --test       self-test

Environment: GH_TOKEN; GITHUB_REPOSITORY (owner/name); NUMBER (the issue);
BODY (a file holding the issue's body); ACCEPTED_BY (seal-prd); POLICY_REF
(the commit of DiluxOne/.github whose policy applied); RECEIPTS_FIXTURE (a
directory standing in for the branch, for the self-test).
"""
import base64
import datetime
import hashlib
import json
import os
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


def board_text(number, ready, last_seal, merged):
    rows = ["| Gate | State |", "| --- | --- |"]
    rows.append(f"| G1 Issue ready | {'✓ the PRD follows the schema' if ready else '✗ see the G1 comment'} |")
    if last_seal:
        rows.append(f"| G2 Accepted | ✓ by {last_seal.get('accepted_by')} at {last_seal.get('at')}; PRD sealed `{last_seal.get('prd_sha256', '')[:12]}` |")
    else:
        rows.append("| G2 Accepted | not sealed |")
    if merged:
        rows.append(f"| G7 Merged | ✓ #{merged.get('pull_request')} by {merged.get('merged_by')}; receipt in `receipts/issues/{number}/merged-{merged.get('at')}.json` |")
    return f"{BOARD}\n**The issue's board**\n\n" + "\n".join(rows) + f"\n\n{AI}"


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
        env = dict(os.environ, NUMBER="9", BODY=bf, GITHUB_REPOSITORY="o/r", ACCEPTED_BY="soydiloreto",
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
        try:
            sealed = last_seal(repo, number)
        except Exception as e:  # noqa: BLE001 — any failure to read is "unknown", never "unsealed" nor "changed"
            print(f"error: {e}")
            return 2
        v = verdict(body, sealed)
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
        print(board_text(number, ready, last_seal(repo, number), merged))
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
