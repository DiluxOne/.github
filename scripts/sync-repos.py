#!/usr/bin/env python3
"""Keep every repository of the organisation in step with this one.

What GitHub lets the organisation hold itself (rulesets, issue types and
fields, Projects, secrets, the community files of this repository) lives
there. What it does not, this script brings to every repository that is not
archived and not excluded in repos.yml:

  labels    labels.yml: creates each label or brings its colour and
            description in line; never deletes one.
  settings  repos.yml `settings` and `security`, through the API.
  files     repos.yml `files` (CODEOWNERS) and the opening block of AGENTS.md
            (agents-block.md, between its dx:org markers). These never go
            straight to main: for a repository whose files differ, it opens
            an issue (Type Task) and a pull request that closes it, and the
            maintainer accepts the issue and merges, like any other change.
  own-checks  a repository whose kind asks for it (kinds/<kind>/pack.yml,
            `own-checks`) gets a ruleset named "own checks" requiring its own
            jobs' checks, from its last merged pull request; one that exists
            is left as it is. Then its rulesets the organisation's cover
            (another one on the default branch, a tag ruleset the same as the
            organisation's) are deleted.
  all       the four, in that order.
  check     changes nothing: lists, as Markdown, what differs in each
            repository (the weekly drift check posts it as an issue).

  sync-repos.py <labels|settings|files|own-checks|all> [--repo NAME ...] [--dry-run]
  sync-repos.py check [--repo NAME ...] [--report FILE]
  sync-repos.py --test

Run by a maintainer with `gh` signed in as an owner of the organisation.
"""
import base64
import json
import os
import re
import subprocess
import sys

ORG = os.environ.get("DX_ORG", "DiluxOne")
HERE = os.path.dirname(os.path.abspath(__file__))
CENTRAL = os.path.join(HERE, "..")
START = "<!-- dx:org:start"
END = "<!-- dx:org:end -->"


def load_yaml(path):
    # yq on the runners, PyYAML on a maintainer's machine, as scripts/policy.py.
    import shutil
    if shutil.which("yq"):
        return json.loads(subprocess.run(["yq", "-o=json", ".", path], check=True, capture_output=True, text=True).stdout or "null") or {}
    import yaml
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def gh(*args, check=True, input_text=None):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, input=input_text)
    if check and out.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)}: {out.stderr.strip()[:300]}")
    return out


def repositories(only, exclude):
    rows = json.loads(gh("repo", "list", ORG, "--no-archived", "--limit", "1000", "--json", "name,visibility,isFork,defaultBranchRef").stdout)
    if len(rows) >= 1000:
        raise SystemExit("more than 1000 repositories: the list would be cut; raise the limit")
    return [r for r in rows if r["name"] not in exclude and not r["isFork"] and (not only or r["name"] in only)]


def with_block(agents, block):
    """AGENTS.md with the organisation's block: replaced between its markers,
    or put right after the first heading when it has none."""
    block = block.rstrip("\n") + "\n"
    if agents.count(START) > 1 or agents.count(END) > 1 or (START in agents) != (END in agents) \
            or (START in agents and agents.index(END) < agents.index(START)):
        raise ValueError("AGENTS.md has a broken dx:org block (a marker missing, repeated or out of order); fix it by hand")
    if START in agents and END in agents:
        before = agents[: agents.index(START)]
        after = agents[agents.index(END) + len(END):]
        return before + block.rstrip("\n") + after
    lines = agents.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith("# "):
            return "".join(lines[: i + 1]) + "\n" + block + "".join(lines[i + 1:])
    return block + "\n" + agents


def sync_labels(repo, labels, dry):
    if dry:
        print(f"  would set {len(labels)} labels")
        return
    for label in labels:
        name, color, desc = str(label["name"]), str(label["color"]), str(label.get("description", ""))
        gh("label", "create", name, "--repo", f"{ORG}/{repo['name']}", "--color", color, "--description", desc, "--force")
    print(f"  {len(labels)} labels in step")


def sync_settings(repo, conf, dry):
    full = f"{ORG}/{repo['name']}"
    settings = conf.get("settings") or {}
    security = conf.get("security") or {}
    public = repo["visibility"] == "PUBLIC"
    if dry:
        print(f"  would set {', '.join(sorted(settings))}; security for a {'public' if public else 'private'} repository")
        return
    args = []
    for key, value in settings.items():
        args += ["-F" if isinstance(value, bool) else "-f", f"{key}={str(value).lower() if isinstance(value, bool) else value}"]
    gh("api", "-X", "PATCH", f"repos/{full}", *args)
    if security.get("vulnerability_alerts"):
        gh("api", "-X", "PUT", f"repos/{full}/vulnerability-alerts")
    if public and security.get("private_vulnerability_reporting") in (True, "public-only"):
        gh("api", "-X", "PUT", f"repos/{full}/private-vulnerability-reporting")
    if public and security.get("secret_scanning") in (True, "public-only"):
        body = {"security_and_analysis": {"secret_scanning": {"status": "enabled"}, "secret_scanning_push_protection": {"status": "enabled"}}}
        gh("api", "-X", "PATCH", f"repos/{full}", "--input", "-", input_text=json.dumps(body))
    print("  settings in step")


def sync_files(repo, conf, block, dry):
    full = f"{ORG}/{repo['name']}"
    open_prs = json.loads(gh("pr", "list", "--repo", full, "--state", "open", "--limit", "500", "--json", "headRefName").stdout)
    if any(p["headRefName"].endswith("-org-shared-files") for p in open_prs):
        print("  a pull request for the shared files is already open; skipped")
        return
    default = (repo.get("defaultBranchRef") or {}).get("name") or "main"

    def read(path):
        out = gh("api", f"repos/{full}/contents/{path}?ref={default}", "-H", "Accept: application/vnd.github.raw", check=False)
        if out.returncode == 0:
            return out.stdout
        if "404" in out.stderr or "Not Found" in out.stderr:
            return None
        # A rate limit or a server error is not a missing file: stop rather
        # than propose overwriting what is there.
        raise RuntimeError(f"could not read {path}: {out.stderr.strip()[:200]}")

    wanted = {}
    for path, content in (conf.get("files") or {}).items():
        if read(path) != content:
            wanted[path] = content
    agents = read("AGENTS.md")
    if agents is None:
        print("  no AGENTS.md: the organisation's block waits until the repository has one")
    elif with_block(agents, block) != agents:
        wanted["AGENTS.md"] = with_block(agents, block)
    if not wanted:
        print("  files in step")
        return
    changed = ", ".join(wanted)
    if dry:
        print(f"  would open an issue and a pull request for: {changed}")
        return
    body = ("The organisation keeps some files the same in every repository, because GitHub reads them only from "
            f"the repository: {changed} differ here from DiluxOne/.github (repos.yml, agents-block.md). "
            "This brings them in step.\n\n🤖 AI-generated · scripts/sync-repos.py")
    # A run that failed half way left its issue (and maybe its branch): reuse
    # them instead of opening a second one.
    title = "Keep the organisation's shared files in step"
    found = json.loads(gh("issue", "list", "--repo", full, "--state", "open", "--search", f"in:title \"{title}\"", "--json", "number,title").stdout)
    found = [i for i in found if i["title"] == title]
    if found:
        number = str(found[0]["number"])
        print(f"  reusing the open issue #{number}")
    else:
        url = gh("issue", "create", "--repo", full, "--title", title, "--body", body).stdout.strip()
        number = url.rsplit("/", 1)[-1]
    if gh("api", "-X", "PATCH", f"repos/{full}/issues/{number}", "-f", "type=Task", check=False).returncode != 0:
        print(f"  warning: could not set #{number}'s Type to Task; set it by hand")
    branch = f"chore/{number}-org-shared-files"
    if gh("api", f"repos/{full}/git/ref/heads/{branch}", check=False).returncode != 0:
        base = json.loads(gh("api", f"repos/{full}/git/ref/heads/{default}").stdout)["object"]["sha"]
        gh("api", "-X", "POST", f"repos/{full}/git/refs", "-f", f"ref=refs/heads/{branch}", "-f", f"sha={base}")
    for path, content in wanted.items():
        current = gh("api", f"repos/{full}/contents/{path}?ref={branch}", "--jq", ".sha", check=False)
        payload = {"message": f"chore: keep {path} in step with the organisation", "branch": branch,
                   "content": base64.b64encode(content.encode()).decode()}
        if current.returncode == 0 and current.stdout.strip():
            payload["sha"] = current.stdout.strip()
        gh("api", "-X", "PUT", f"repos/{full}/contents/{path}", "--input", "-", input_text=json.dumps(payload))
    pr_body = (f"## 📝 What changes\n\n{changed} as DiluxOne/.github keeps them for every repository.\n\n"
               f"## 💡 Why\n\nGitHub reads these only from the repository, so the organisation keeps them in step from one place.\n\nCloses #{number}\n\n"
               "🤖 AI-generated · scripts/sync-repos.py")
    pr = gh("pr", "create", "--repo", full, "--base", default, "--head", branch,
            "--title", "chore: keep the organisation's shared files in step", "--body", pr_body).stdout.strip()
    print(f"  issue #{number} (accept it) and {pr}")


USES_RE = re.compile(r"DiluxOne/\.github/\.github/workflows/[\w.-]+@v(\d+)\b")
# Any call of a shared workflow, a version tag or a pinned commit alike.
CALLS_RE = re.compile(r"DiluxOne/\.github/\.github/workflows/[\w.-]+@\S+")


def current_major():
    """The newest major of the shared workflows: the highest vN tag here."""
    tags = json.loads(gh("api", "--paginate", "--slurp", f"repos/{ORG}/.github/git/matching-refs/tags/v").stdout)
    tags = [t for page in tags for t in page] if tags and isinstance(tags[0], list) else tags
    majors = [int(m.group(1)) for t in tags if (m := re.fullmatch(r"refs/tags/v(\d+)", t["ref"]))]
    return max(majors) if majors else 0


def old_versions(texts, current):
    """The majors older than the current one that these workflow files call."""
    return sorted({int(v) for t in texts for v in USES_RE.findall(t) if int(v) < current})


OWN = "own checks"


def workflow_texts(full):
    """The text of each workflow file of a repository (none: an empty list)."""
    listing = gh("api", f"repos/{full}/contents/.github/workflows", check=False)
    if listing.returncode != 0 and "404" not in listing.stderr:
        raise RuntimeError(f"could not list its workflows: {listing.stderr.strip()[:200]}")
    texts = []
    if listing.returncode == 0:
        for entry in json.loads(listing.stdout):
            if entry.get("name", "").endswith((".yml", ".yaml")):
                texts.append(gh("api", f"repos/{full}/contents/{entry['path']}", "-H", "Accept: application/vnd.github.raw").stdout)
    return texts


def own_checks_spec(full, default, texts):
    """The pack's `own-checks` when the repository needs the ruleset: its kind
    (kind: in its .github/review-policy.yml) asks for one and a workflow of
    its calls one of the pack's `callers-of`. None otherwise."""
    out = gh("api", f"repos/{full}/contents/.github/review-policy.yml?ref={default}", "-H", "Accept: application/vnd.github.raw", check=False)
    m = re.search(r"^kind:\s*([A-Za-z0-9_-]+)", out.stdout, re.M) if out.returncode == 0 else None
    pack = os.path.join(CENTRAL, "kinds", m.group(1), "pack.yml") if m else ""
    spec = (load_yaml(pack).get("own-checks") or None) if pack and os.path.isfile(pack) else None
    return spec if spec and calls_any(texts, spec.get("callers-of") or []) else None


def calls_any(texts, workflows):
    """Whether these workflow files call one of these shared workflows."""
    return any(re.search(r"DiluxOne/\.github/\.github/workflows/" + re.escape(w) + r"@", t) for t in texts for w in workflows)


def own_contexts(names, spec):
    """The check names "own checks" requires: those of the pack's jobs, but
    the ones it skips, once each, sorted."""
    jobs, skip = set(spec.get("jobs") or []), set(spec.get("skip") or [])
    picked = {n for n in names if " / " in n and n.split(" / ", 1)[0] in jobs and n.split(" / ", 1)[1] not in skip}
    return sorted(picked)


def covers(org_rs, name):
    """Whether an organisation ruleset applies to this repository."""
    cond = ((org_rs.get("conditions") or {}).get("repository_name") or {})
    include, exclude = cond.get("include") or [], cond.get("exclude") or []
    return org_rs.get("enforcement") == "active" and ("~ALL" in include or name in include) and name not in exclude


def same_rules(a, b):
    """Two rulesets that do the same: target, refs, rules and bypass."""
    def key(r):
        refs = (r.get("conditions") or {}).get("ref_name") or {}
        rules = sorted(json.dumps(x, sort_keys=True) for x in r.get("rules") or [])
        bypass = sorted(json.dumps(x, sort_keys=True) for x in r.get("bypass_actors") or [])
        return r.get("target"), sorted(refs.get("include") or []), sorted(refs.get("exclude") or []), rules, bypass
    return key(a) == key(b)


def superseded(name, mine, org):
    """The repository's own rulesets the organisation's cover: on the default
    branch, any but "own checks" once the organisation's branch ruleset
    applies; on tags, one that does what an organisation tag ruleset that
    applies does. Each as (id, name)."""
    org = [r for r in org if covers(r, name)]
    branch = any(r.get("target") == "branch" for r in org)
    found = []
    for r in mine:
        refs = ((r.get("conditions") or {}).get("ref_name") or {}).get("include") or []
        if r.get("target") == "branch" and branch and r.get("name") != OWN and set(refs) <= {"~DEFAULT_BRANCH", "refs/heads/main"}:
            found.append((r["id"], r["name"]))
        elif r.get("target") == "tag" and any(o.get("target") == "tag" and same_rules(r, o) for o in org):
            found.append((r["id"], r["name"]))
    return found


def rulesets(full):
    """The repository's own rulesets (not the organisation's), whole."""
    rows = json.loads(gh("api", f"repos/{full}/rulesets?includes_parents=false").stdout)
    return [json.loads(gh("api", f"repos/{full}/rulesets/{r['id']}").stdout) for r in rows if r.get("source_type") == "Repository"]


ORG_RULESETS = None


def org_rulesets():
    global ORG_RULESETS
    if ORG_RULESETS is None:
        rows = json.loads(gh("api", f"orgs/{ORG}/rulesets").stdout)
        ORG_RULESETS = [json.loads(gh("api", f"orgs/{ORG}/rulesets/{r['id']}").stdout) for r in rows]
    return ORG_RULESETS


def sync_own_checks(repo, dry):
    full = f"{ORG}/{repo['name']}"
    default = (repo.get("defaultBranchRef") or {}).get("name") or "main"
    spec = own_checks_spec(full, default, workflow_texts(full))
    mine = rulesets(full)
    has_own = any(r.get("name") == OWN for r in mine)
    if spec and not has_own:
        merged = json.loads(gh("pr", "list", "--repo", full, "--state", "merged", "--limit", "1", "--json", "headRefOid").stdout)
        names = []
        if merged:
            runs = json.loads(gh("api", "--paginate", "--slurp", f"repos/{full}/commits/{merged[0]['headRefOid']}/check-runs?per_page=100").stdout)
            names = [c["name"] for page in runs for c in page.get("check_runs", [])]
        contexts = own_contexts(names, spec)
        if not contexts:
            print(f"  no checks of its jobs ({', '.join(spec.get('jobs') or [])}) on its last merged pull request: \"{OWN}\" waits, and nothing is deleted")
            return
        if dry:
            print(f"  would create \"{OWN}\" with {len(contexts)} checks")
        else:
            body = {"name": OWN, "target": "branch", "enforcement": "active", "bypass_actors": [],
                    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
                    "rules": [{"type": "required_status_checks", "parameters": {
                        "strict_required_status_checks_policy": True, "do_not_enforce_on_create": False,
                        "required_status_checks": [{"context": c} for c in contexts]}}]}
            gh("api", "-X", "POST", f"repos/{full}/rulesets", "--input", "-", input_text=json.dumps(body))
            print(f"  \"{OWN}\" created with {len(contexts)} checks")
    for rid, rname in superseded(repo["name"], mine, org_rulesets()):
        if dry:
            print(f"  would delete the ruleset \"{rname}\" (the organisation's covers it)")
        else:
            gh("api", "-X", "DELETE", f"repos/{full}/rulesets/{rid}")
            print(f"  deleted the ruleset \"{rname}\" (the organisation's covers it)")


def drift(repo, conf, labels, block, current=0):
    """What differs in a repository from what this repository keeps, as lines."""
    full = f"{ORG}/{repo['name']}"
    found = []
    default = (repo.get("defaultBranchRef") or {}).get("name") or "main"
    if current:
        texts = workflow_texts(full)
        old = old_versions(texts, current)
        if not any(CALLS_RE.search(t) for t in texts) and repo["name"] not in (conf.get("no-workflows") or []):
            found.append("calls none of the shared workflows (docs/adopting.md)")
        if old:
            found.append(f"calls the shared workflows at {', '.join('@v' + str(v) for v in old)}; the current is @v{current} (docs/migrating.md)")
        mine = rulesets(full)
        if own_checks_spec(full, default, texts) and not any(r.get("name") == OWN for r in mine):
            found.append(f"no \"{OWN}\" ruleset: nothing requires its own jobs' checks (`sync-repos.py own-checks`)")
        try:
            org = org_rulesets()
        except RuntimeError:
            # The weekly check's token may not read the organisation's
            # rulesets (organisation administration); what they cover is
            # then not reported, rather than guessed.
            org = []
        for _, rname in superseded(repo["name"], mine, org):
            found.append(f"the ruleset \"{rname}\" is covered by the organisation's (`sync-repos.py own-checks` deletes it)")
    have = {l["name"]: l for l in json.loads(gh("label", "list", "--repo", full, "--limit", "1000", "--json", "name,color,description").stdout)}
    for label in labels:
        name = str(label["name"])
        mine = have.get(name)
        if mine is None:
            found.append(f"label `{name}` is missing")
        elif mine["color"].upper() != str(label["color"]).upper() or (mine.get("description") or "") != str(label.get("description", "")):
            found.append(f"label `{name}` has another colour or description")
    data = json.loads(gh("api", f"repos/{full}").stdout)
    for key, value in (conf.get("settings") or {}).items():
        # A token that cannot see a setting says nothing about it: not drift.
        if key in data and data[key] != value:
            found.append(f"setting `{key}` is `{data[key]}`, not `{value}`")
    for path, content in (conf.get("files") or {}).items():
        out = gh("api", f"repos/{full}/contents/{path}?ref={default}", "-H", "Accept: application/vnd.github.raw", check=False)
        if out.returncode != 0 and "404" not in out.stderr:
            raise RuntimeError(f"could not read {path}: {out.stderr.strip()[:200]}")
        if out.returncode != 0:
            found.append(f"`{path}` is missing")
        elif out.stdout != content:
            found.append(f"`{path}` differs")
    out = gh("api", f"repos/{full}/contents/AGENTS.md?ref={default}", "-H", "Accept: application/vnd.github.raw", check=False)
    if out.returncode == 0:
        try:
            if with_block(out.stdout, block) != out.stdout:
                found.append("`AGENTS.md` does not carry the organisation's current block")
        except ValueError:
            found.append("`AGENTS.md` has a broken dx:org block")
    else:
        found.append("no `AGENTS.md`")
    return found


def self_test():
    failed = 0

    def check(name, ok, detail=""):
        nonlocal failed
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
        failed += 0 if ok else 1

    block = f"{START} (x) -->\nRULES\n{END}\n"
    plain = "# AGENTS.md\n\nIntro.\n\n## Mine\n"
    once = with_block(plain, block)
    check("the block goes right after the first heading", once.startswith("# AGENTS.md\n\n" + START) and once.endswith("Intro.\n\n## Mine\n"), once)
    check("a second run changes nothing", with_block(once, block) == once, with_block(once, block))
    newer = with_block(once, block.replace("RULES", "NEW RULES"))
    check("a new block replaces the old one, and only it", "NEW RULES" in newer and "\nRULES" not in newer.replace("NEW RULES", "") and newer.endswith("Intro.\n\n## Mine\n"), newer)
    check("no heading: the block goes first", with_block("Just text.\n", block).startswith(START))
    for name, broken in (("a start with no end", f"# A\n{START} -->\nx\n"), ("an end before the start", f"# A\n{END}\n{START} -->\n"), ("two blocks", once + once)):
        try:
            with_block(broken, block)
            check(f"a broken block fails: {name}", False, "no error")
        except ValueError:
            check(f"a broken block fails: {name}", True)
    labels = load_yaml(os.path.join(CENTRAL, "labels.yml"))
    names = [str(l["name"]) for l in labels]
    check("labels.yml: every label has a name, a colour and no repeat", all(re.fullmatch(r"[0-9A-F]{6}", str(l["color"])) for l in labels) and len(names) == len(set(names)), names)
    check("labels.yml: accepted is there", "accepted" in names)
    conf = load_yaml(os.path.join(CENTRAL, "repos.yml"))
    check("repos.yml: settings, security and files", isinstance(conf.get("settings"), dict) and isinstance(conf.get("security"), dict) and ".github/CODEOWNERS" in (conf.get("files") or {}), conf)
    projects = conf.get("projects") or {}
    check("repos.yml: every Project is a positive number, every repository a name", projects and all(isinstance(n, int) and n > 0 for n in projects.values()) and all(re.fullmatch(r"[A-Za-z0-9._-]+", r) for r in projects), projects)
    block_file = open(os.path.join(CENTRAL, "agents-block.md"), encoding="utf-8").read()
    check("agents-block.md: carries both markers", block_file.startswith(START) and block_file.rstrip().endswith(END))
    # drift() against a stand-in for gh: one repository with a label of
    # another colour, a missing one, a setting off, CODEOWNERS different and
    # AGENTS.md without the block.
    global gh
    real = gh

    class Out:
        def __init__(self, stdout="", returncode=0, stderr=""):
            self.stdout, self.returncode, self.stderr = stdout, returncode, stderr

    def fake(*args, check=True, input_text=None):
        joined = " ".join(args)
        if args[:2] == ("label", "list"):
            return Out(json.dumps([{"name": "accepted", "color": "000000", "description": "x"}]))
        if joined.startswith("api repos/o/r/contents/.github/CODEOWNERS"):
            return Out("* @someone-else\n")
        if joined.startswith("api repos/o/r/contents/AGENTS.md"):
            return Out("# AGENTS.md\n\nMine.\n")
        if joined.startswith("api repos/o/r"):
            return Out(json.dumps({"allow_squash_merge": True, "allow_merge_commit": True}))
        return Out("", 1, "HTTP 404")
    globals()["gh"] = fake
    try:
        global ORG
        saved, ORG = ORG, "o"
        lines = drift({"name": "r"}, {"settings": {"allow_squash_merge": True, "allow_merge_commit": False, "has_wiki": False}, "files": {".github/CODEOWNERS": "* @soydiloreto\n"}},
                      [{"name": "accepted", "color": "0E8A16", "description": "y"}, {"name": "planned", "color": "0E8A16"}], block)
    finally:
        ORG = saved
        globals()["gh"] = real
    text = "\n".join(lines)
    check("drift: a label of another colour", "label `accepted` has another colour" in text, lines)
    check("drift: a missing label", "label `planned` is missing" in text, lines)
    check("drift: a setting off", "setting `allow_merge_commit` is `True`" in text, lines)
    check("drift: a setting the token cannot read is not drift", "has_wiki" not in text, lines)
    check("drift: a file that differs", "`.github/CODEOWNERS` differs" in text, lines)
    check("drift: AGENTS.md without the block", "does not carry the organisation's current block" in text, lines)
    check("drift: a setting in step is not reported", "allow_squash_merge" not in text, lines)
    files = ["uses: DiluxOne/.github/.github/workflows/conventions.yml@v3", "uses: DiluxOne/.github/.github/workflows/issue-triage.yml@v5", "uses: actions/checkout@v7"]
    check("versions: an older major is found", old_versions(files, 5) == [3], old_versions(files, 5))
    check("versions: the current major is not", old_versions(files[1:], 5) == [], old_versions(files[1:], 5))
    check("versions: another owner's action is not", old_versions(["uses: actions/checkout@v2"], 5) == [], "")
    check("calls: a pinned commit counts as calling the shared workflows", bool(CALLS_RE.search("uses: DiluxOne/.github/.github/workflows/plugin-release-wp.yml@0123456789abcdef0123456789abcdef01234567")), "")
    spec = load_yaml(os.path.join(CENTRAL, "kinds", "wordpress-plugin", "pack.yml")).get("own-checks") or {}
    check("pack wordpress-plugin: own-checks names its callers and jobs", spec.get("callers-of") and spec.get("jobs"), spec)
    names = ["checks / PHPStan", "checks / What changed", "tests / E2E (single)", "tests / E2E (single)", "conventions / Conventions (branch, title, commits)", "review / Claude review", "Dependabot", "real-s3 / AWS"]
    check("own checks: its jobs' checks, once, sorted, without the skipped", own_contexts(names, spec) == ["checks / PHPStan", "tests / E2E (single)"], own_contexts(names, spec))
    check("own checks: a repository calling the checks needs one", calls_any(["uses: DiluxOne/.github/.github/workflows/plugin-checks-wp.yml@v5"], spec["callers-of"]))
    check("own checks: one calling only the issue workflows does not", not calls_any(["uses: DiluxOne/.github/.github/workflows/issue-triage.yml@v5"], spec["callers-of"]))
    tag_rules = [{"type": "deletion"}, {"type": "update"}]
    org = [{"name": "org: main", "target": "branch", "enforcement": "active", "conditions": {"repository_name": {"include": ["r"]}}, "rules": [{"type": "pull_request"}]},
           {"name": "org: release tags", "target": "tag", "enforcement": "active", "conditions": {"repository_name": {"include": ["r"]}, "ref_name": {"include": ["refs/tags/*.*.*"]}}, "rules": tag_rules}]
    mine = [{"id": 1, "name": "main", "target": "branch", "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}}, "rules": [{"type": "required_status_checks"}]},
            {"id": 2, "name": OWN, "target": "branch", "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}}},
            {"id": 3, "name": "release tags", "target": "tag", "conditions": {"ref_name": {"include": ["refs/tags/*.*.*"]}}, "rules": tag_rules},
            {"id": 4, "name": "Tag protection", "target": "tag", "conditions": {"ref_name": {"include": ["~ALL"]}}, "rules": tag_rules},
            {"id": 5, "name": "release branches", "target": "branch", "conditions": {"ref_name": {"include": ["refs/heads/release/*"]}}}]
    got = superseded("r", mine, org)
    check("superseded: the old main and a tag ruleset the same as the organisation's", got == [(1, "main"), (3, "release tags")], got)
    check("superseded: nothing while the organisation's rulesets do not cover the repository", superseded("other", mine, org) == [], superseded("other", mine, org))
    paused = [dict(o, enforcement="evaluate") for o in org]
    check("superseded: nothing when the organisation's are not active", superseded("r", mine, paused) == [], superseded("r", mine, paused))
    if not failed:
        print("all tests passed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if not argv or argv[0] not in ("labels", "settings", "files", "own-checks", "all", "check"):
        print(__doc__)
        return 64
    what, rest = argv[0], argv[1:]
    dry = "--dry-run" in rest
    only = [rest[i + 1] for i, a in enumerate(rest) if a == "--repo" and i + 1 < len(rest)]
    conf = load_yaml(os.path.join(CENTRAL, "repos.yml"))
    labels = load_yaml(os.path.join(CENTRAL, "labels.yml"))
    block = open(os.path.join(CENTRAL, "agents-block.md"), encoding="utf-8").read()
    failures = 0
    repos = repositories(only, conf.get("exclude") or [])
    missing = sorted(set(only) - {r["name"] for r in repos})
    if missing:
        print(f"No such repository (or archived, or excluded): {', '.join(missing)}")
        return 1
    if what == "check":
        report = [f"# Repositories out of step with {ORG}/.github", "",
                  "What differs from `labels.yml`, `repos.yml` and `agents-block.md`. Labels and settings: `python3 scripts/sync-repos.py all`; files: the pull requests it opens.", ""]
        dirty = 0
        current = current_major()
        for repo in repos:
            try:
                lines = drift(repo, conf, labels, block, current)
            except RuntimeError as exc:
                lines = [f"could not be checked: {exc}"]
            if lines:
                dirty += 1
                report += [f"## {repo['name']}", ""] + [f"- {line}" for line in lines] + [""]
        if not dirty:
            report = [f"Every repository is in step with {ORG}/.github."]
        text = "\n".join(report) + "\n"
        path = next((rest[i + 1] for i, a in enumerate(rest) if a == "--report" and i + 1 < len(rest)), None)
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        print(text)
        print(f"{dirty} repositories out of step.")
        return 0
    for repo in repos:
        print(f"{ORG}/{repo['name']}")
        try:
            if what in ("labels", "all"):
                sync_labels(repo, labels, dry)
            if what in ("settings", "all"):
                sync_settings(repo, conf, dry)
            if what in ("files", "all"):
                sync_files(repo, conf, block, dry)
            if what in ("own-checks", "all"):
                sync_own_checks(repo, dry)
        except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
            failures += 1
            print(f"  failed: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
