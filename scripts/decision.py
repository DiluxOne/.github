#!/usr/bin/env python3
"""An organisation decision, carried out in every repository it names (#189).

A decision is an issue of DiluxOne/.github whose PRD has a Repositories
section (policy/issue-schema.yml): rules over what the organisation knows of
each repository, all of them true at once (`all`, `kind:`, `visibility:`,
`has:`, `name:`). Once a person accepts it, this opens one sub-issue in each
repository the rules select, as dilux-bot: the parent's title, Type and PRD
(but its Repositories section), linked as a native sub-issue. The delegated
lane (policy/autonomy.yml) accepts each, so the decision needs one
acceptance. A comment on the parent, kept up to date, lists the repositories
and their sub-issues. A repository that matches later gets its own on the
next run; one that stops matching keeps the sub-issue it has.

  decision.py open     the decision NUMBER (issue-accepted.yml, when a
                       person accepts it)
  decision.py sync     every open decision a person accepted (org-drift.yml,
                       every day)
  decision.py --test   self-test, with stand-ins for GitHub

Environment: GH_TOKEN (dilux-bot: issues write on every repository, and
contents read for the rules over files), GITHUB_REPOSITORY (the decisions'
repository, DiluxOne/.github), NUMBER for `open`. A repository that fails
is reported and the others go on; the run then fails.
"""
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMMENT = "<!-- dx-decision -->"
AI = "🤖 AI-generated · Claude Opus 5.5 (Anthropic)"


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


schema = module("issue_schema", "issue-schema.py")


# --- what a decision says (pure, tested) -----------------------------------

def rules_of(body):
    """The decision's rules, or None when its PRD has no Repositories section."""
    sections, _ = schema.parse(body)
    text = next((t for h, t in sections if h == "Repositories"), None)
    if text is None or text.strip().lower() in schema.EMPTY:
        return None
    rules, errors = schema.repository_rules(text)
    if errors:
        raise ValueError("; ".join(errors))
    return rules


def selects(rules, repo):
    """Whether a repository ({name, visibility, kind, files}) meets every rule."""
    for key, values in rules:
        if key == "all":
            continue
        if key == "name" and repo["name"] not in values:
            return False
        if key == "kind" and (repo.get("kind") or "") not in values:
            return False
        if key == "visibility" and (repo.get("visibility") or "").lower() not in [v.lower() for v in values]:
            return False
        if key == "has" and not all(v in (repo.get("files") or set()) for v in values):
            return False
    return True


def child_body(body, parent_ref):
    """The sub-issue's text: the parent's PRD as it was accepted, but its
    Repositories section (a sub-issue decides for its repository alone)."""
    sections, _ = schema.parse(body)
    prd = [s["heading"] for s in schema.schema()["prd"] if s["id"] != "repositories"]
    parts = []
    for h, t in sections:
        if h not in prd:
            continue
        t = t.strip()
        # What it carries out, as the Scope's first line: inside the PRD,
        # so the sub-issue passes G1 as its parent did.
        if h == "Scope":
            t = f"- Carries out {parent_ref} in this repository, accepted with it (the delegated lane).\n{t}"
        parts.append(f"### {h}\n\n{t}")
    return "\n\n".join(parts) + f"\n\n{AI}\n"


def table(parent_ref, chosen, children, failed):
    """The parent's comment: each repository the rules select and its sub-issue."""
    rows = ["| Repository | Sub-issue |", "| --- | --- |"]
    for name in chosen:
        if name in children:
            rows.append(f"| {name} | {children[name]} |")
        else:
            rows.append(f"| {name} | {'✗ failed, the next run tries again' if name in failed else 'pending'} |")
    head = (f"{COMMENT}\n**Repositories this decision reaches**\n\n"
            f"The rules in Repositories select {len(chosen)}; each has a sub-issue of {parent_ref}, accepted with it.")
    return f"{head}\n\n" + "\n".join(rows) + f"\n\n{AI}"


# --- GitHub ------------------------------------------------------------------

def gh(*args, input_text=None):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, input=input_text)
    if out.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {out.stderr.strip()[:300]}")
    return out.stdout


def lines(*args):
    """A paginated gh api call whose --jq prints one JSON value per line."""
    return [json.loads(l) for l in gh(*args).splitlines() if l.strip()]


def person_accepted(full, number):
    events = lines("api", f"repos/{full}/issues/{number}/timeline", "--paginate", "--jq",
                   '.[] | select((.event == "labeled" or .event == "unlabeled") and .label.name == "accepted") | {event, type: .actor.type} | @json')
    return bool(events) and events[-1] == {"event": "labeled", "type": "User"}


def sealed(full, number, body):
    """Whether the PRD is the one sealed when a person accepted it
    (scripts/receipts.py verify-prd): an edit after acceptance is not
    carried anywhere until it is accepted again."""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(body)
    try:
        out = subprocess.run([sys.executable, os.path.join(HERE, "receipts.py"), "verify-prd"], capture_output=True, text=True,
                             env={**os.environ, "NUMBER": str(number), "BODY": fh.name, "GITHUB_REPOSITORY": full})
    finally:
        os.unlink(fh.name)
    return out.returncode == 0 and out.stdout.strip() == "match"


def facts(org, rules):
    """Every repository of the organisation, with what the rules ask of it."""
    sync = module("sync_repos", "sync-repos.py")
    conf = sync.load_yaml(os.path.join(HERE, "..", "repos.yml"))
    out = []
    want_kind = any(k == "kind" for k, _ in rules)
    want_files = any(k == "has" for k, _ in rules)
    for r in sync.repositories([], conf.get("exclude") or []):
        default = (r.get("defaultBranchRef") or {}).get("name") or "main"
        row = {"name": r["name"], "visibility": r.get("visibility", "")}
        # One repository that cannot be read is reported, never the end of the run.
        try:
            if want_kind:
                row["kind"] = sync.repo_kind(f"{org}/{r['name']}", default)
            if want_files:
                # An empty repository has no contents at all: no files, not an error.
                listing = subprocess.run(["gh", "api", f"repos/{org}/{r['name']}/contents/?ref={default}", "--jq", "[.[].name]"], capture_output=True, text=True)
                if listing.returncode != 0 and "404" not in listing.stderr:
                    raise RuntimeError(listing.stderr.strip()[:200])
                row["files"] = set(json.loads(listing.stdout or "[]")) if listing.returncode == 0 else set()
        except (RuntimeError, ValueError) as exc:
            row["error"] = str(exc)
        out.append(row)
    return out


def existing_children(full, number):
    """{repository name: "owner/name#n"} of the parent's sub-issues."""
    subs = lines("api", f"repos/{full}/issues/{number}/sub_issues", "--paginate", "--jq",
                 ".[] | {repo: (.repository_url | split(\"/\") | .[-1]), number} | @json")
    org = full.split("/", 1)[0]
    return {s["repo"]: f"{org}/{s['repo']}#{s['number']}" for s in subs}


def open_child(full, number, parent, repo):
    """Open the sub-issue, set its Type and link it. A run that failed half
    way left the issue unlinked: it is found by its text and reused, never
    opened twice."""
    org = full.split("/", 1)[0]
    body = child_body(parent["body"], f"{full}#{number}")
    found = [i for i in json.loads(gh("issue", "list", "--repo", f"{org}/{repo}", "--state", "open", "--search", f"in:title {parent['title']}",
                                      "--json", "number,title,body")) if i["title"] == parent["title"] and i["body"].strip() == body.strip()]
    if found:
        n = str(found[0]["number"])
    else:
        url = gh("issue", "create", "--repo", f"{org}/{repo}", "--title", parent["title"], "--body-file", "-", input_text=body).strip()
        n = url.rsplit("/", 1)[-1]
    if parent.get("type"):
        gh("api", "-X", "PATCH", f"repos/{org}/{repo}/issues/{n}", "-f", f"type={parent['type']}")
    child_id = gh("api", f"repos/{org}/{repo}/issues/{n}", "--jq", ".id").strip()
    gh("api", "-X", "POST", f"repos/{full}/issues/{number}/sub_issues", "-F", f"sub_issue_id={child_id}")
    return f"{org}/{repo}#{n}"


def upsert_comment(full, number, text):
    ids = gh("api", f"repos/{full}/issues/{number}/comments", "--paginate", "--jq",
             f'.[] | select(.user.type == "Bot" and (.body | startswith("{COMMENT}"))) | .id').split()
    if ids:
        gh("api", "-X", "PATCH", f"repos/{full}/issues/comments/{ids[-1]}", "-f", f"body={text}")
    else:
        gh("issue", "comment", str(number), "--repo", full, "--body", text)


def carry_out(full, number, io=None):
    """Open what is missing for one decision; returns the repositories that
    failed. `io` stands in for GitHub in the self-test."""
    io = io or {"issue": lambda: json.loads(gh("issue", "view", str(number), "--repo", full, "--json", "title,body,state")),
                "type": lambda: gh("api", f"repos/{full}/issues/{number}", "--jq", ".type.name // empty").strip(),
                "accepted": lambda: person_accepted(full, number), "sealed": lambda body: sealed(full, number, body), "facts": facts,
                "children": lambda: existing_children(full, number),
                "open": lambda parent, repo: open_child(full, number, parent, repo),
                "comment": lambda text: upsert_comment(full, number, text)}
    parent = io["issue"]()
    rules = rules_of(parent["body"])
    if rules is None:
        print(f"#{number} names no repositories: not a decision for several.")
        return []
    if parent.get("state") != "OPEN" or not io["accepted"]():
        print(f"#{number} is not open and accepted by a person: nothing opens.")
        return []
    # What is carried out is what the person read and accepted: a PRD that
    # passes G1, unchanged since its seal.
    if not schema.check(parent["body"])["ok"]:
        print(f"#{number}'s PRD does not pass G1: nothing opens until it does.")
        return []
    if not io["sealed"](parent["body"]):
        print(f"#{number}'s PRD is not the one a person accepted: nothing opens until it is accepted again.")
        return []
    parent["type"] = io["type"]()
    org = full.split("/", 1)[0]
    rows = io["facts"](org, rules)
    unread = sorted(r["name"] for r in rows if r.get("error"))
    chosen = sorted(r["name"] for r in rows if not r.get("error") and selects(rules, r) and r["name"] != full.split("/", 1)[1])
    children = io["children"]()
    failed = list(unread)
    for name in unread:
        print(f"  {name}: could not be read; the next run tries again")
    for repo in chosen:
        if repo in children:
            continue
        try:
            children[repo] = io["open"](parent, repo)
            print(f"  {repo}: {children[repo]}")
        except RuntimeError as exc:
            failed.append(repo)
            print(f"  {repo}: failed ({exc})")
    # A repository that stopped matching keeps its sub-issue, and its row.
    io["comment"](table(f"{full}#{number}", sorted(set(chosen) | set(unread) | set(children)), children, failed))
    return failed


def decisions(full):
    """The open issues a person accepted whose PRD names repositories."""
    rows = json.loads(gh("issue", "list", "--repo", full, "--state", "open", "--label", "accepted", "--limit", "200",
                         "--json", "number,body"))
    return [r["number"] for r in rows if "### Repositories" in (r.get("body") or "")]


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    prd = ("### Problem\n\nEvery plugin pins an old PHP.\n\n### Scope\n\n- PHP 7.4 at least.\n\n### Out of scope\n\n- Themes.\n\n"
           "### Acceptance criteria\n\n- C1: Given a plugin, when its CI runs, then PHP 7.4 is the lowest.\n\n"
           "### Criticality\n\nNormal\n\n### Repositories\n\n- kind: wordpress-plugin\n- visibility: public\n\n" + AI + "\n")
    check("rules: read from the Repositories section", rules_of(prd), [("kind", ["wordpress-plugin"]), ("visibility", ["public"])])
    check("rules: none without the section", rules_of(prd.replace("### Repositories\n\n- kind: wordpress-plugin\n- visibility: public\n\n", "")), None)
    check("rules: none when the form left it empty", rules_of(prd.replace("- kind: wordpress-plugin\n- visibility: public", "_No response_")), None)
    try:
        rules_of(prd.replace("visibility: public", "owner: me"))
        check("rules: a broken one stops it", "no error", "error")
    except ValueError:
        check("rules: a broken one stops it", "error", "error")
    plugin = {"name": "offload", "visibility": "PUBLIC", "kind": "wordpress-plugin", "files": {"composer.json"}}
    check("selects: every rule true", selects(rules_of(prd), plugin), True)
    check("selects: a private one is out", selects(rules_of(prd), dict(plugin, visibility="PRIVATE")), False)
    check("selects: another kind is out", selects(rules_of(prd), dict(plugin, kind=None)), False)
    check("selects: has a file at its root", (selects([("has", ["composer.json"])], plugin), selects([("has", ["Dockerfile"])], plugin)), (True, False))
    check("selects: by name", (selects([("name", ["offload", "mail"])], plugin), selects([("name", ["mail"])], plugin)), (True, False))
    check("selects: all", selects([("all", None)], {"name": "x"}), True)
    body = child_body(prd, "DiluxOne/.github#300")
    check("child: the parent's PRD, as accepted", body.startswith("### Problem\n\nEvery plugin pins an old PHP.") and "### Criticality\n\nNormal" in body, True)
    check("child: without the Repositories section", "### Repositories" in body, False)
    check("child: says what it carries out", "Carries out DiluxOne/.github#300 in this repository" in body, True)
    check("child: its PRD passes G1", schema.check(body)["ok"], True)

    repos = [plugin, dict(plugin, name="mail"), dict(plugin, name="secret", visibility="PRIVATE"), {"name": ".github", "visibility": "PUBLIC", "kind": "wordpress-plugin"}]
    calls = {"open": [], "comment": []}

    def io(state="OPEN", accepted=True, children=None, fail=(), is_sealed=True, body_=None, rows=None):
        def open_(parent, repo):
            if repo in fail:
                raise RuntimeError("HTTP 502")
            calls["open"].append((repo, parent["type"]))
            return f"DiluxOne/{repo}#1"
        return {"issue": lambda: {"title": "PHP 7.4 at least", "body": body_ or prd, "state": state}, "type": lambda: "Task",
                "accepted": lambda: accepted, "sealed": lambda b: is_sealed, "facts": lambda org, rules: rows or repos, "children": lambda: dict(children or {}),
                "open": open_, "comment": lambda text: calls["comment"].append(text)}
    carry_out("DiluxOne/.github", 300, io())
    check("carry out: a sub-issue in each repository selected, with the parent's Type", calls["open"], [("mail", "Task"), ("offload", "Task")])
    check("carry out: never in the decisions' own repository", any(r == ".github" for r, _ in calls["open"]), False)
    check("carry out: the parent's comment lists them", "| offload | DiluxOne/offload#1 |" in calls["comment"][-1] and calls["comment"][-1].startswith(COMMENT), True)
    calls["open"].clear()
    carry_out("DiluxOne/.github", 300, io(children={"offload": "DiluxOne/offload#4"}))
    check("carry out: one that has its sub-issue gets no second", calls["open"], [("mail", "Task")])
    carry_out("DiluxOne/.github", 300, io(children={"gone": "DiluxOne/gone#2"}))
    check("carry out: one that stopped matching keeps its row", "| gone | DiluxOne/gone#2 |" in calls["comment"][-1], True)
    calls["open"].clear()
    check("carry out: a failure is reported and the others go on", (carry_out("DiluxOne/.github", 300, io(fail=("mail",))), calls["open"]), (["mail"], [("offload", "Task")]))
    check("carry out: the comment says it failed", "| mail | ✗ failed" in calls["comment"][-1], True)
    calls["open"].clear()
    carry_out("DiluxOne/.github", 300, io(accepted=False))
    carry_out("DiluxOne/.github", 300, io(state="CLOSED"))
    check("carry out: nothing for a decision a person has not accepted, or closed", calls["open"], [])
    carry_out("DiluxOne/.github", 300, io(is_sealed=False))
    check("carry out: nothing for a PRD edited after it was accepted", calls["open"], [])
    carry_out("DiluxOne/.github", 300, io(body_=prd.replace("- C1: Given a plugin, when its CI runs, then PHP 7.4 is the lowest.", "- C1: PHP 7.4.")))
    check("carry out: nothing for a PRD that does not pass G1", calls["open"], [])
    got = carry_out("DiluxOne/.github", 300, io(rows=[plugin, {"name": "broken", "error": "HTTP 404"}]))
    check("carry out: a repository that cannot be read is reported, the rest go on", (got, calls["open"]), (["broken"], [("offload", "Task")]))
    check("carry out: the comment lists the unread one as failed", "| broken | ✗ failed" in calls["comment"][-1], True)

    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    full = os.environ.get("GITHUB_REPOSITORY", "DiluxOne/.github")
    if argv == ["open"]:
        return 1 if carry_out(full, int(os.environ["NUMBER"])) else 0
    if argv == ["sync"]:
        bad = 0
        for number in decisions(full):
            print(f"{full}#{number}")
            try:
                bad += bool(carry_out(full, number))
            except (RuntimeError, ValueError) as exc:
                bad += 1
                print(f"  failed: {exc}")
        return 1 if bad else 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
