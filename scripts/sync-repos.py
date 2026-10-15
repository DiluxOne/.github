#!/usr/bin/env python3
"""Keep every repository of the organisation in step with this one.

What GitHub lets the organisation hold itself (rulesets, issue types and
fields, Projects, secrets, the community files of this repository) lives
there. What it does not, this script brings to every repository that is not
archived and not excluded in repos.yml:

  labels    labels.yml: creates each label or brings its colour and
            description in line; never deletes one.
  settings  repos.yml `settings` and `security` (Dependabot's alerts and
            security updates among them), through the API.
  files     repos.yml `files` (CODEOWNERS), the opening block of AGENTS.md
            (agents-block.md, between its dx:org markers) and
            .github/dependabot.yml, written from the template of the
            repository's kind (kinds/<kind>/dependabot.yml, else
            policy/dependabot.default.yml) with only the ecosystems it has
            (github-actions always; npm, composer, docker by their manifest at
            its root) and what repos.yml `dependabot` adds for it. These never
            go straight to main: for a repository whose files differ, it opens
            an issue (Type Task) and a pull request that closes it, and the
            maintainer accepts the issue and merges, like any other change.
  own-checks  a repository whose kind asks for it (kinds/<kind>/pack.yml,
            `own-checks`) gets a ruleset named "own checks" requiring its own
            jobs' checks, from its last merged pull request; one that exists
            is left as it is. Then its rulesets the organisation's cover
            (another one on the default branch, a tag ruleset the same as the
            organisation's) are deleted.
  callers   the workflows that call the shared ones, held job for job to
            the templates in workflow-templates/ (repos.yml `callers`): the
            ones in `every-repository`, and any other whose shared workflows
            the repository calls. Each template job must be there with the
            same `uses:`, `needs` (its own jobs may join them), `if`,
            `permissions`, `secrets` handling and inputs, but the inputs the
            template says to fill in (`repository-owned`). Inputs and jobs of
            the repository's own are never compared. Like `files`, it opens
            an issue (Type Task) and a pull request rewriting each caller
            that differs, only the jobs that differ, keeping the
            repository's values, header, triggers and own jobs. A repository
            at an older major migrates first (docs/migrating.md). Not in
            `all`: a template change is a pull request in every repository.
  all       labels, settings, files and own-checks, in that order.
  check     changes nothing: lists, as Markdown, what differs in each
            repository, its callers and its Dependabot configuration
            included (the weekly drift check posts it as an issue), and a
            repository whose `design-system` in
            repos.yml names no system of design-systems/, or is `local` with
            no docs/design-system/README.md.

  sync-repos.py <labels|settings|files|own-checks|callers|all> [--repo NAME ...] [--dry-run]
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
    if security.get("automated_security_fixes"):
        gh("api", "-X", "PUT", f"repos/{full}/automated-security-fixes")
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
    _, dependabot = dependabot_wanted(repo, conf, default)
    if read(DEPENDABOT) != dependabot:
        wanted[DEPENDABOT] = dependabot
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
            f"the repository: {changed} differ here from DiluxOne/.github (repos.yml, agents-block.md, the Dependabot template of its kind). "
            "This brings them in step.\n\n🤖 AI-generated · scripts/sync-repos.py")
    pr_body = (f"## 📝 What changes\n\n{changed} as DiluxOne/.github keeps them for every repository.\n\n"
               "## 💡 Why\n\nGitHub reads these only from the repository, so the organisation keeps them in step from one place.")
    open_change(repo, default, wanted, "Keep the organisation's shared files in step", body,
                "chore/{}-org-shared-files", "chore: keep the organisation's shared files in step", pr_body,
                "chore: keep {} in step with the organisation")


def open_change(repo, default, wanted, title, body, branch_form, pr_title, pr_body, message_form):
    """An issue (Type Task) and a pull request that closes it, writing
    `wanted` ({path: content}) on the branch branch_form.format(<issue>),
    one commit per file (message_form.format(<path>)). A run that failed
    half way left its issue (and maybe its branch): they are reused instead
    of opening a second one."""
    full = f"{ORG}/{repo['name']}"
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
    branch = branch_form.format(number)
    if gh("api", f"repos/{full}/git/ref/heads/{branch}", check=False).returncode != 0:
        base = json.loads(gh("api", f"repos/{full}/git/ref/heads/{default}").stdout)["object"]["sha"]
        gh("api", "-X", "POST", f"repos/{full}/git/refs", "-f", f"ref=refs/heads/{branch}", "-f", f"sha={base}")
    for path, content in wanted.items():
        current = gh("api", f"repos/{full}/contents/{path}?ref={branch}", "--jq", ".sha", check=False)
        payload = {"message": message_form.format(path), "branch": branch,
                   "content": base64.b64encode(content.encode()).decode()}
        if current.returncode == 0 and current.stdout.strip():
            payload["sha"] = current.stdout.strip()
        gh("api", "-X", "PUT", f"repos/{full}/contents/{path}", "--input", "-", input_text=json.dumps(payload))
    pr_body = f"{pr_body}\n\nCloses #{number}\n\n🤖 AI-generated · scripts/sync-repos.py"
    pr = gh("pr", "create", "--repo", full, "--base", default, "--head", branch,
            "--title", pr_title, "--body", pr_body).stdout.strip()
    print(f"  issue #{number} (accept it) and {pr}")
    return number, pr


def sync_callers(repo, conf, dry):
    """Opens an issue and a pull request that bring the repository's callers
    in step with their templates (callers_drift(), rewrite_caller()). A
    repository at an older major migrates first (docs/migrating.md);
    DiluxOne/.github changes its own callers by hand."""
    full = f"{ORG}/{repo['name']}"
    if repo["name"] == ".github":
        print("  this repository's own callers change in a pull request here, by hand")
        return
    files = workflow_files(full)
    if not any(CALLS_RE.search(t) for t in files.values()):
        print("  calls none of the shared workflows: nothing to compare (docs/adopting.md)")
        return
    if old_versions(files.values(), current_major()):
        print("  calls the shared workflows at an older major: migrate it first (docs/migrating.md)")
        return
    open_prs = json.loads(gh("pr", "list", "--repo", full, "--state", "open", "--limit", "500", "--json", "headRefName").stdout)
    if any(p["headRefName"].endswith("-org-workflow-callers") for p in open_prs):
        print("  a pull request for the workflow callers is already open; skipped")
        return
    owned = (conf.get("callers") or {}).get("repository-owned") or {}
    wanted, notes = {}, []
    for name, path, found in callers_drift(files, conf):
        if not path:
            notes.append(f"no caller of workflow-templates/{name}: add it from the template by hand (docs/adopting.md)")
            continue
        text = open(os.path.join(TEMPLATES, name), encoding="utf-8").read()
        # A file that is the caller of two templates takes both rewrites.
        new, missing = rewrite_caller(wanted.get(path, files[path]), text, set(owned.get(name) or []))
        left = [f for n, p, f in callers_drift({**files, path: new}, conf) if p == path and n == name] if new else []
        if new is None:
            notes.append(f"{path}: no job of the repository gives {', '.join(missing)}; bring it in step by hand")
        elif left:
            notes.append(f"{path}: still differs after the rewrite ({'; '.join(left[0])}); bring it in step by hand")
        else:
            wanted[path] = new
    for note in notes:
        print(f"  {note}")
    if not wanted:
        print("  callers in step" if not notes else "  nothing this script can bring in step")
        return
    changed = ", ".join(wanted)
    if dry:
        import difflib
        print(f"  would open an issue and a pull request for: {changed}")
        for path, new in wanted.items():
            sys.stdout.writelines("    " + l for l in difflib.unified_diff(files[path].splitlines(True), new.splitlines(True), path, path))
        return
    default = (repo.get("defaultBranchRef") or {}).get("name") or "main"
    templates_named = ", ".join(sorted({f"workflow-templates/{n}" for n, p, _ in callers_drift(files, conf) if p in wanted}))
    body = (f"The organisation's workflow templates ({templates_named} in DiluxOne/.github) have jobs or settings "
            f"that {changed} here lack. This brings each caller in step, job by job, keeping the values that are "
            "this repository's (its support URL, slug, version constant, profile) and its own jobs and inputs."
            "\n\n🤖 AI-generated · scripts/sync-repos.py")
    pr_body = (f"## 📝 What changes\n\n{changed} as {templates_named} has them, with this repository's own values and jobs kept.\n\n"
               "## 💡 Why\n\nA job a template gains reaches every repository only through its callers; the weekly drift check "
               "(DiluxOne/.github, scripts/sync-repos.py check) found these out of step.")
    open_change(repo, default, wanted, "Keep the workflow callers in step with the organisation's templates", body,
                "ci/{}-org-workflow-callers", "ci: keep the workflow callers in step with the templates", pr_body,
                "ci: keep {} in step with its template")


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


# A call of a shared workflow at anything but a version tag vN: a commit, a
# branch, a tag of another shape. Nothing is pinned in any repository (#136).
# `v5-foo` is not a version tag; a comment (`# …@<sha>` in an example) is
# not a call.
PINNED_RE = re.compile(r"DiluxOne/\.github/\.github/workflows/([\w.-]+)@(?!v\d+(?:[\s\"'#]|$))([^\s\"']+)")
COMMENT_RE = re.compile(r"(^|\s)#.*$", re.M)


def pinned_calls(texts):
    """[(workflow, ref)] for every call of a shared workflow at a ref that is
    not a version tag, in these workflow files; comments are not read."""
    return sorted({(w, r) for t in texts for w, r in PINNED_RE.findall(COMMENT_RE.sub("", t))})


OWN = "own checks"


def workflow_files(full):
    """{path: text} of each workflow file of a repository (none: empty)."""
    listing = gh("api", f"repos/{full}/contents/.github/workflows", check=False)
    if listing.returncode != 0 and "404" not in listing.stderr:
        raise RuntimeError(f"could not list its workflows: {listing.stderr.strip()[:200]}")
    files = {}
    if listing.returncode == 0:
        for entry in json.loads(listing.stdout):
            if entry.get("name", "").endswith((".yml", ".yaml")):
                files[entry["path"]] = gh("api", f"repos/{full}/contents/{entry['path']}", "-H", "Accept: application/vnd.github.raw").stdout
    return files


def workflow_texts(full):
    """The text of each workflow file of a repository (none: an empty list)."""
    return list(workflow_files(full).values())


# The callers: each repository's workflows that call the shared ones, held
# job for job to the templates in workflow-templates/ (repos.yml `callers`).

TEMPLATES = os.path.join(CENTRAL, "workflow-templates")
SHARED_PREFIX = "DiluxOne/.github/.github/workflows/"
LOCAL_PREFIX = "./.github/workflows/"


def parse_yaml(text):
    """A YAML text as data, through yq or PyYAML like load_yaml(); a text
    that does not parse raises ValueError."""
    import shutil
    if shutil.which("yq"):
        out = subprocess.run(["yq", "-o=json", ".", "-"], input=text, capture_output=True, text=True)
        if out.returncode != 0:
            raise ValueError(f"not YAML: {out.stderr.strip()[:200]}")
        return json.loads(out.stdout or "null") or {}
    import yaml
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"not YAML: {exc}") from exc


def templates():
    """{name: (text, data)} of every workflow template."""
    found = {}
    for name in sorted(os.listdir(TEMPLATES)):
        if name.endswith(".yml"):
            text = open(os.path.join(TEMPLATES, name), encoding="utf-8").read()
            found[name] = (text, parse_yaml(text))
    return found


def split_uses(uses, central=False):
    """(shared workflow, ref) for a call of a shared workflow, else None. In
    DiluxOne/.github itself a local call (./.github/workflows/x.yml) is the
    same workflow, at whatever the template calls (ref None)."""
    uses = str(uses or "")
    if uses.startswith(SHARED_PREFIX) and "@" in uses:
        name, ref = uses[len(SHARED_PREFIX):].split("@", 1)
        return name, ref
    if central and uses.startswith(LOCAL_PREFIX):
        return uses[len(LOCAL_PREFIX):], None
    return None


def jobs_of(data):
    jobs = (data or {}).get("jobs") or {}
    return jobs if isinstance(jobs, dict) else {}


def shared_calls(data, central=False):
    """The shared workflows a workflow's jobs call."""
    return {s[0] for job in jobs_of(data).values() if isinstance(job, dict) and (s := split_uses(job.get("uses"), central))}


def caller_for(template, files, central=False):
    """The repository's workflow file that calls this template's shared
    workflows: the one calling most of them, the template's own name first
    on a tie. None when no file calls any."""
    wanted = shared_calls(template)
    best = None
    for path in sorted(files):
        overlap = len(shared_calls(files[path][1], central) & wanted)
        if overlap:
            key = (overlap, os.path.basename(path) == template.get("_name"))
            if best is None or key > best[0]:
                best = (key, path)
    return best[1] if best else None


def plain(value):
    """A value as the text a comparison reads: booleans as YAML writes them,
    an expression without its ${{ }} and its spacing."""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = " ".join(str(value if value is not None else "").split())
    m = re.fullmatch(r"\$\{\{\s*(.*?)\s*\}\}", text)
    return m.group(1) if m else text


def needs_of(job):
    needs = job.get("needs") or []
    return sorted([needs] if isinstance(needs, str) else needs)


def job_differences(name, want, have, owned, central=False):
    """What a caller's job does other than its template's, as phrases."""
    found = []
    w, h = split_uses(want.get("uses")), split_uses(have.get("uses"), central)
    if (not w or not h) and want.get("uses") != have.get("uses") or \
            w and h and (h[0] != w[0] or (h[1] is not None and h[1] != w[1])):
        found.append(f"calls `{have.get('uses')}`, not `{want.get('uses')}`")
    # A job of the repository's own may join what a template's job waits
    # for (a suite of its own whose failure the weekly issue reports too).
    if not set(needs_of(want)) <= set(needs_of(have)):
        found.append(f"needs `{', '.join(needs_of(have)) or 'nothing'}`, not `{', '.join(needs_of(want)) or 'nothing'}`")
    if plain(want.get("if", "")) != plain(have.get("if", "")):
        found.append(f"runs `if: {plain(have.get('if', '')) or 'always'}`, not `if: {plain(want.get('if', '')) or 'always'}`")
    if (want.get("permissions") or {}) != (have.get("permissions") or {}):
        found.append("has other permissions")
    ws, hs = want.get("secrets"), have.get("secrets")
    if ws == "inherit" and hs != "inherit":
        found.append("passes its secrets by name, not `secrets: inherit`")
    elif isinstance(ws, dict) and hs != "inherit" and not set(ws) <= set(hs or {}):
        found.append(f"does not pass `{', '.join(sorted(set(ws) - set(hs or {})))}`")
    given = have.get("with") or {}
    for key, value in (want.get("with") or {}).items():
        if key in owned:
            continue
        if key not in given:
            found.append(f"does not pass `{key}: {plain(value)}`")
        elif plain(given[key]) != plain(value):
            found.append(f"passes `{key}: {plain(given[key])}`, not `{plain(value)}`")
    return [f"job `{name}` {f}" for f in found]


def callers_drift(files, conf, central=False):
    """What differs in a repository's callers from the templates that apply
    to it, as [(template, caller path or None, [phrases])], only those that
    differ. `files` is {path: text}."""
    spec = conf.get("callers") or {}
    every, owned = set(spec.get("every-repository") or []), spec.get("repository-owned") or {}
    parsed = {p: (t, parse_yaml(t)) for p, t in files.items()}
    out = []
    for name, (_, data) in templates().items():
        data = dict(data, _name=name)
        path = caller_for(data, parsed, central)
        if path is None:
            if name in every:
                out.append((name, None, [f"has no caller of `workflow-templates/{name}`"]))
            continue
        mine = jobs_of(parsed[path][1])
        found = []
        for job, want in jobs_of(data).items():
            if job not in mine:
                found.append(f"lacks the job `{job}`")
            else:
                found += job_differences(job, want, mine[job] or {}, set(owned.get(name) or []), central)
        if found:
            out.append((name, path, found))
    return out


def caller_lines(drifted, central=False):
    """The drift check's lines for callers_drift()'s result. DiluxOne/.github
    brings its own callers in step by hand (sync_callers() skips it)."""
    lines = []
    fix = "by hand, in a pull request here" if central else "`sync-repos.py callers`"
    for name, path, found in drifted:
        for f in found:
            if path:
                lines.append(f"`{path}` {f} of `workflow-templates/{name}` ({fix})")
            else:
                lines.append(f"{f}: add it from the template (docs/adopting.md)")
    return lines


# Rewriting a caller: job by job, on the text, so that the repository's
# header, triggers and jobs of its own stay as they are; a job it rewrites
# takes the template's text, comments included.

JOB_RE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*(#.*)?$")
KEY_RE = re.compile(r"^    ([A-Za-z0-9_-]+):")
INPUT_RE = re.compile(r"^      ([A-Za-z0-9_-]+):")
# What job_differences() compares: a rewrite takes these from the template.
COMPARED = ("uses", "needs", "if", "permissions", "with", "secrets")


def job_blocks(text):
    """(head, [(job, lines)]) of a workflow's text: everything up to its
    first job, then each job with the comments and the blank line before it."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, l in enumerate(lines) if re.match(r"^jobs:\s*(#.*)?$", l)), None)
    if start is None:
        raise ValueError("no jobs: section")
    start += 1
    heads = [i for i in range(start, len(lines)) if JOB_RE.match(lines[i])]
    bounds = []
    for k, h in enumerate(heads):
        s = h
        floor = heads[k - 1] + 1 if k else start
        while s > floor and (not lines[s - 1].strip() or lines[s - 1].startswith("  #")):
            s -= 1
        bounds.append(s)
    blocks = [(JOB_RE.match(lines[h]).group(1), lines[s:(bounds[k + 1] if k + 1 < len(bounds) else len(lines))])
              for k, (h, s) in enumerate(zip(heads, bounds))]
    return "".join(lines[:bounds[0] if bounds else len(lines)]), blocks


def keyed(lines, key_re, indent):
    """{key: (first, end)} of the keys at this indent in a job's lines: a key
    runs to the next line at its indent or less that is not a comment."""
    keys, current = {}, None
    for i, line in enumerate(lines):
        m = key_re.match(line)
        if m:
            current = m.group(1)
            keys[current] = [i, i + 1]
        elif current and line.strip() and (len(line) - len(line.lstrip(" ")) > indent or line.lstrip().startswith("#")):
            if not line.lstrip().startswith("#"):
                keys[current][1] = i + 1
        elif current and line.strip():
            current = None
    return {k: tuple(v) for k, v in keys.items()}


def merged_job(template_lines, have_lines, owned, fallback, keep_needs=False):
    """The template's job with the repository's values: its inputs the
    template says to fill in (from this job, else `fallback`, {input: lines}
    from its other jobs), the inputs and keys it adds, its secrets where the
    template passes none or names them while it inherits, and its `needs`
    when they add its own jobs to the template's (keep_needs). None when an
    input to fill in has no value of the repository's."""
    out = list(template_lines)
    have_keys = keyed(have_lines, KEY_RE, 4)
    keys = keyed(out, KEY_RE, 4)
    if keep_needs and "needs" in have_keys:
        a, b = have_keys["needs"]
        if "needs" in keys:
            s, e = keys["needs"]
        else:  # the template's job waits for nothing: the repository's own go right under its name
            s = e = next(i for i, l in enumerate(out) if JOB_RE.match(l)) + 1
        out[s:e] = have_lines[a:b]
    have_inputs = {}
    if "with" in have_keys:
        a, b = have_keys["with"]
        sub = have_lines[a:b]
        have_inputs = {k: sub[s:e] for k, (s, e) in keyed(sub, INPUT_RE, 6).items()}
    keys = keyed(out, KEY_RE, 4)
    if "with" in keys:
        a, b = keys["with"]
        sub = out[a:b]
        inputs = keyed(sub, INPUT_RE, 6)
        for key, (s, e) in sorted(inputs.items(), key=lambda kv: -kv[1][0]):
            if key in owned:
                value = have_inputs.get(key) or fallback.get(key)
                if value is None:
                    return None
                sub[s:e] = value
        extra = [l for k, v in have_inputs.items() if k not in inputs for l in v]
        last = max((e for _, e in keyed(sub, INPUT_RE, 6).values()), default=1)
        sub[last:last] = extra
        out[a:b] = sub
    elif have_inputs:
        a, b = keys["uses"]
        out[b:b] = ["    with:\n"] + [l for v in have_inputs.values() for l in v]
    keys = keyed(out, KEY_RE, 4)
    if "secrets" in have_keys:
        a, b = have_keys["secrets"]
        theirs = have_lines[a:b]
        if "secrets" not in keys:
            out += theirs
        elif theirs[0].split(":", 1)[1].strip().startswith("inherit"):
            s, e = keys["secrets"]
            out[s:e] = theirs
    for key, (a, b) in have_keys.items():
        if key not in keys and key not in COMPARED:
            out += have_lines[a:b]
    return out


def rewrite_caller(text, template_text, owned):
    """The caller's text with each job of its template that is missing or
    differs taken from the template, with the repository's values kept.
    (new text, [inputs no job of the repository fills in]); the text is None
    when one of those stops it."""
    head, mine = job_blocks(text)
    _, theirs = job_blocks(template_text)
    have = dict(mine)
    data_mine, data_theirs = jobs_of(parse_yaml(text)), jobs_of(parse_yaml(template_text))
    fallback = {}
    for _, lines in mine:
        keys = keyed(lines, KEY_RE, 4)
        if "with" in keys:
            a, b = keys["with"]
            sub = lines[a:b]
            for k, (s, e) in keyed(sub, INPUT_RE, 6).items():
                fallback.setdefault(k, sub[s:e])
    replaced, missing = {}, []
    for job, lines in theirs:
        if job in have and not job_differences(job, data_theirs[job], data_mine.get(job) or {}, owned):
            continue
        keep = job in have and set(needs_of(data_theirs[job])) <= set(needs_of(data_mine.get(job) or {}))
        new = merged_job(lines, have.get(job, []), owned, fallback, keep)
        if new is None:
            given = (data_mine.get(job) or {}).get("with") or {}
            missing += [k for k in owned if k in (data_theirs[job].get("with") or {}) and k not in given and k not in fallback]
            continue
        while new and not new[0].strip():
            new.pop(0)
        replaced[job] = new
    if missing:
        return None, sorted(set(missing))
    order = [j for j, _ in theirs]
    blocks = []
    for job, lines in mine:
        blocks.append((job, replaced.pop(job) if job in replaced else lines))
    for job in order:
        if job in replaced:
            before = [j for j in order[:order.index(job)] if any(b[0] == j for b in blocks)]
            at = max((i for i, b in enumerate(blocks) if before and b[0] == before[-1]), default=-1) + 1
            blocks.insert(at, (job, replaced.pop(job)))
    body = []
    for i, (_, lines) in enumerate(blocks):
        lines = list(lines)
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        body += (["\n"] if i else []) + lines
    while body and not body[-1].strip():
        body.pop()
    return head + "".join(body), []


def policy_kind(text):
    """The kind a repository's .github/review-policy.yml names, quoted or not."""
    m = re.search(r"""^kind:\s*["']?([A-Za-z0-9_-]+)["']?\s*(#.*)?$""", text or "", re.M)
    return m.group(1) if m else None


def repo_kind(full, default):
    """The kind the repository's .github/review-policy.yml names, or None."""
    out = gh("api", f"repos/{full}/contents/.github/review-policy.yml?ref={default}", "-H", "Accept: application/vnd.github.raw", check=False)
    if out.returncode != 0 and "404" not in out.stderr:
        raise RuntimeError(f"could not read its review policy: {out.stderr.strip()[:200]}")
    return policy_kind(out.stdout) if out.returncode == 0 else None


def own_checks_spec(full, default, texts):
    """The pack's `own-checks` when the repository needs the ruleset: its kind
    (kind: in its .github/review-policy.yml) asks for one and a workflow of
    its calls one of the pack's `callers-of`. None otherwise."""
    kind = repo_kind(full, default)
    pack = os.path.join(CENTRAL, "kinds", kind, "pack.yml") if kind else ""
    spec = (load_yaml(pack).get("own-checks") or None) if pack and os.path.isfile(pack) else None
    return spec if spec and calls_any(texts, spec.get("callers-of") or []) else None


def calls_any(texts, workflows):
    """Whether these workflow files call one of these shared workflows."""
    return any(re.search(r"DiluxOne/\.github/\.github/workflows/" + re.escape(w) + r"@", t) for t in texts for w in workflows)


def pipeline_jobs():
    """The jobs of the organisation's required pipeline (org-pull-request.yml):
    their checks are the organisation's to require, not "own checks"'."""
    text = open(os.path.join(CENTRAL, ".github", "workflows", "org-pull-request.yml"), encoding="utf-8").read()
    jobs = text[text.index("\njobs:"):]
    return set(re.findall(r"^  ([A-Za-z0-9_-]+):\s*$", jobs, re.M))


def own_contexts(names, spec):
    """The check names "own checks" requires: those of the pack's jobs, but
    the ones it skips, once each, sorted."""
    jobs, skip = set(spec.get("jobs") or []), set(spec.get("skip") or [])
    picked = {n for n in names if " / " in n and n.split(" / ", 1)[0] in jobs and n.split(" / ", 1)[1] not in skip}
    return sorted(picked)


def required_checks(ruleset):
    return [c["context"] for r in ruleset.get("rules") or [] if r.get("type") == "required_status_checks"
            for c in (r.get("parameters") or {}).get("required_status_checks") or []]


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


MAIN_REFS = {"~DEFAULT_BRANCH", "refs/heads/main"}


def superseded(name, mine, org, pipeline):
    """The repository's own rulesets the organisation's cover, each as
    (id, name): on tags, one that does exactly what an organisation tag
    ruleset that applies does; on the default branch, one whose every rule
    an organisation branch ruleset on the default branch has too, but its
    required checks, and whose every required check is either the
    organisation pipeline's or already in "own checks". Anything else stays."""
    org = [r for r in org if covers(r, name)]
    org_branch = [r for r in org if r.get("target") == "branch"
                  and set(((r.get("conditions") or {}).get("ref_name") or {}).get("include") or []) & MAIN_REFS]
    org_rules = {json.dumps(x, sort_keys=True) for r in org_branch for x in r.get("rules") or []}
    own = {c for r in mine if r.get("name") == OWN and r.get("enforcement", "active") == "active" for c in required_checks(r)}
    org_bypass = {json.dumps(x, sort_keys=True) for r in org_branch for x in r.get("bypass_actors") or []}
    found = []
    for r in mine:
        refs = set(((r.get("conditions") or {}).get("ref_name") or {}).get("include") or [])
        if r.get("target") == "tag":
            if any(o.get("target") == "tag" and same_rules(r, o) for o in org):
                found.append((r["id"], r["name"]))
        elif r.get("target") == "branch" and r.get("name") != OWN and org_branch and refs and refs <= MAIN_REFS:
            rules = {json.dumps(x, sort_keys=True) for x in r.get("rules") or [] if x.get("type") != "required_status_checks"}
            checks = required_checks(r)
            bypass = {json.dumps(x, sort_keys=True) for x in r.get("bypass_actors") or []}
            if rules <= org_rules and bypass <= org_bypass and all(c in own or c.split(" / ", 1)[0] in pipeline for c in checks):
                found.append((r["id"], r["name"]))
    return found


def rulesets(full):
    """The repository's own rulesets (not the organisation's), whole."""
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{full}/rulesets?includes_parents=false&per_page=100").stdout)
    rows = [r for page in pages for r in page]
    return [json.loads(gh("api", f"repos/{full}/rulesets/{r['id']}").stdout) for r in rows if r.get("source_type") == "Repository"]


ORG_RULESETS = None


def org_rulesets():
    global ORG_RULESETS
    if ORG_RULESETS is None:
        pages = json.loads(gh("api", "--paginate", "--slurp", f"orgs/{ORG}/rulesets?per_page=100").stdout)
        ORG_RULESETS = [json.loads(gh("api", f"orgs/{ORG}/rulesets/{r['id']}").stdout) for page in pages for r in page]
    return ORG_RULESETS


def recent_check_names(full, count=5):
    """The check names on the heads of the last merged pull requests: more
    than one, so a docs-only one that skipped the suites does not decide."""
    merged = json.loads(gh("pr", "list", "--repo", full, "--state", "merged", "--limit", str(count), "--json", "headRefOid").stdout)
    names = set()
    for pr in merged:
        pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{full}/commits/{pr['headRefOid']}/check-runs?per_page=100").stdout)
        names |= {c["name"] for page in pages for c in page.get("check_runs", [])}
    return names


def sync_own_checks(repo, dry):
    """Creates "own checks" where the kind asks for it and there is none: the
    pack's jobs' checks on the last merged pull requests, plus every check
    the repository's old default-branch rulesets required that is not the
    organisation pipeline's, so none is lost. Then deletes what superseded()
    finds; a ruleset with a rule or a check nothing else carries stays."""
    full = f"{ORG}/{repo['name']}"
    default = (repo.get("defaultBranchRef") or {}).get("name") or "main"
    spec = own_checks_spec(full, default, workflow_texts(full))
    mine = rulesets(full)
    pipeline = pipeline_jobs()
    if spec and not any(r.get("name") == OWN for r in mine):
        # Only what an active ruleset required on the default branch: a
        # release branch's checks, or a disabled ruleset's, may never run there.
        old = {c for r in mine if r.get("target") == "branch" and r.get("enforcement") == "active"
               and set(((r.get("conditions") or {}).get("ref_name") or {}).get("include") or ["none"]) <= MAIN_REFS
               for c in required_checks(r) if c.split(" / ", 1)[0] not in pipeline}
        contexts = sorted(set(own_contexts(recent_check_names(full), spec)) | old)
        if not contexts:
            print(f"  no checks of its jobs ({', '.join(spec.get('jobs') or [])}) on its last merged pull requests: \"{OWN}\" waits, and nothing is deleted")
            return
        body = {"name": OWN, "target": "branch", "enforcement": "active", "bypass_actors": [],
                "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
                "rules": [{"type": "required_status_checks", "parameters": {
                    "strict_required_status_checks_policy": True, "do_not_enforce_on_create": False,
                    "required_status_checks": [{"context": c} for c in contexts]}}]}
        if dry:
            print(f"  would create \"{OWN}\" with {len(contexts)} checks")
        else:
            gh("api", "-X", "POST", f"repos/{full}/rulesets", "--input", "-", input_text=json.dumps(body))
            print(f"  \"{OWN}\" created with {len(contexts)} checks")
        mine = mine + [{"id": None, **body}]
    for rid, rname in superseded(repo["name"], mine, org_rulesets(), pipeline):
        if dry:
            print(f"  would delete the ruleset \"{rname}\" (the organisation's and \"{OWN}\" cover it)")
        else:
            gh("api", "-X", "DELETE", f"repos/{full}/rulesets/{rid}")
            print(f"  deleted the ruleset \"{rname}\" (the organisation's and \"{OWN}\" cover it)")


def design_systems():
    """The organisation's design systems: each directory of design-systems/
    with its tokens.json."""
    base = os.path.join(CENTRAL, "design-systems")
    return sorted(d for d in os.listdir(base) if os.path.isfile(os.path.join(base, d, "tokens.json"))) if os.path.isdir(base) else []


def design_system_problems(conf, known):
    """What is wrong with repos.yml's `design-system`, as lines."""
    mapping = conf.get("design-system") or {}
    if not isinstance(mapping, dict):
        return ["`design-system` is a map of repository to system"]
    found = []
    for repo, system in mapping.items():
        if not re.fullmatch(r"[A-Za-z0-9._-]+", str(repo)):
            found.append(f"`design-system`: `{repo}` is not a repository's name")
        if system != "local" and system not in known:
            found.append(f"`design-system`: {repo} names `{system}`, which is neither a system of design-systems/ ({', '.join(known) or 'none'}) nor `local`")
    return found


# Dependabot: every repository's .github/dependabot.yml is written from its
# kind's template (kinds/<kind>/dependabot.yml; without one, the
# organisation's default), keeping only the ecosystems the repository has.

DEPENDABOT = ".github/dependabot.yml"
DEPENDABOT_DEFAULT = "policy/dependabot.default.yml"
ECOSYSTEM_RE = re.compile(r"""^  - package-ecosystem:\s*["']?([A-Za-z0-9_-]+)["']?\s*(#.*)?$""")
DIRECTORIES_RE = re.compile(r"^    directories:.*$")
# What at a repository's root says it has an ecosystem; github-actions always.
MANIFESTS = {"package.json": "npm", "composer.json": "composer", "Dockerfile": "docker"}
# What repos.yml `dependabot` may add to an ecosystem of a repository.
DEPENDABOT_KEYS = {"directories", "ignore"}


def dependabot_template(kind):
    """The Dependabot template of a kind, as a path from this repository's
    root: the pack's dependabot.yml, else the organisation's default."""
    if kind and re.fullmatch(r"[A-Za-z0-9_-]+", kind) and os.path.isfile(os.path.join(CENTRAL, "kinds", kind, "dependabot.yml")):
        return f"kinds/{kind}/dependabot.yml"
    return DEPENDABOT_DEFAULT


def dependabot_entries(text):
    """(head, [(ecosystem, lines)]) of a Dependabot template: everything up
    to its first entry of `updates`, then each entry with the comments right
    above it, blank lines around them left out."""
    lines = text.splitlines(keepends=True)
    heads = [i for i, l in enumerate(lines) if ECOSYSTEM_RE.match(l)]
    if not heads:
        raise ValueError("no `- package-ecosystem:` entry under `updates:`")
    starts = []
    for k, h in enumerate(heads):
        s = h
        while s > (heads[k - 1] + 1 if k else 0) and lines[s - 1].startswith("  #"):
            s -= 1
        starts.append(s)

    def trimmed(part):
        part = list(part)
        while part and not part[-1].strip():
            part.pop()
        if part and not part[-1].endswith("\n"):
            part[-1] += "\n"
        return part
    entries = [(ECOSYSTEM_RE.match(lines[h]).group(1), trimmed(lines[s:(starts[k + 1] if k + 1 < len(starts) else len(lines))]))
               for k, (h, s) in enumerate(zip(heads, starts))]
    return "".join(trimmed(lines[:starts[0]])), entries


def dependabot_ecosystems(root, extra):
    """{ecosystem: [directories]} a repository has: github-actions always,
    the others by their manifest at its root (`root`, the names there), plus
    the directories repos.yml adds (`extra`, its `dependabot` entry)."""
    found = {"github-actions": ["/"]}
    for name, eco in MANIFESTS.items():
        if name in root:
            found[eco] = ["/"]
    for eco, spec in extra.items():
        for d in (spec or {}).get("directories") or []:
            if d not in found.setdefault(eco, []):
                found[eco].append(d)
    return {eco: dirs for eco, dirs in found.items() if dirs}


def render_dependabot(template, ecosystems, extra):
    """The template's text with only these ecosystems' entries, each with its
    directories and the repository's `ignore` (repos.yml) added."""
    head, entries = dependabot_entries(template)
    unknown = sorted(set(ecosystems) - {e for e, _ in entries})
    if unknown:
        raise ValueError(f"the template has no entry for {', '.join(unknown)}")
    blocks = []
    for eco, lines in entries:
        if eco not in ecosystems:
            continue
        lines = [f"    directories: {json.dumps(ecosystems[eco])}\n" if DIRECTORIES_RE.match(l) else l for l in lines]
        ignore = (extra.get(eco) or {}).get("ignore") or []
        if ignore:
            lines += ["    # This repository's own, from DiluxOne/.github repos.yml (`dependabot`).\n", "    ignore:\n"]
            lines += [f"      - {json.dumps(i)}\n" for i in ignore]
        blocks.append("".join(lines))
    return head + "\n".join(blocks)


def dependabot_problems(conf):
    """What is wrong with repos.yml's `dependabot`, as lines."""
    mapping = conf.get("dependabot") or {}
    if not isinstance(mapping, dict):
        return ["`dependabot` is a map of repository to its ecosystems"]
    known = {e for e, _ in dependabot_entries(open(os.path.join(CENTRAL, DEPENDABOT_DEFAULT), encoding="utf-8").read())[1]}
    found = []
    for repo, ecos in mapping.items():
        if not re.fullmatch(r"[A-Za-z0-9._-]+", str(repo)):
            found.append(f"`dependabot`: `{repo}` is not a repository's name")
        if not isinstance(ecos, dict):
            found.append(f"`dependabot`: {repo} is a map of ecosystem to what it adds")
            continue
        for eco, spec in ecos.items():
            if eco not in known:
                found.append(f"`dependabot`: {repo} names `{eco}`, not an ecosystem of the templates ({', '.join(sorted(known))})")
            elif not isinstance(spec, dict) or set(spec) - DEPENDABOT_KEYS:
                found.append(f"`dependabot`: {repo}'s `{eco}` may hold only {' and '.join(sorted(DEPENDABOT_KEYS))}")
            elif not all(isinstance(d, str) and d.startswith("/") for d in spec.get("directories") or []) \
                    or not all(isinstance(i, dict) and i.get("dependency-name") for i in spec.get("ignore") or []):
                found.append(f"`dependabot`: {repo}'s `{eco}`: each directory starts with `/`, each `ignore` names a `dependency-name`")
    return found


def root_names(full, default):
    """The names at a repository's root (an empty repository: none)."""
    out = gh("api", f"repos/{full}/contents/?ref={default}", check=False)
    if out.returncode != 0:
        if "404" in out.stderr:
            return set()
        raise RuntimeError(f"could not list its root: {out.stderr.strip()[:200]}")
    rows = json.loads(out.stdout or "[]")
    return {r.get("name") for r in rows if isinstance(r, dict)} if isinstance(rows, list) else set()


def dependabot_wanted(repo, conf, default):
    """(template, text): the Dependabot configuration a repository should
    carry, and the template it comes from."""
    full = f"{ORG}/{repo['name']}"
    extra = (conf.get("dependabot") or {}).get(repo["name"]) or {}
    template = dependabot_template(repo_kind(full, default))
    text = open(os.path.join(CENTRAL, template), encoding="utf-8").read()
    return template, render_dependabot(text, dependabot_ecosystems(root_names(full, default), extra), extra)


def drift(repo, conf, labels, block, current=0):
    """What differs in a repository from what this repository keeps, as lines."""
    full = f"{ORG}/{repo['name']}"
    found = []
    default = (repo.get("defaultBranchRef") or {}).get("name") or "main"
    if current:
        files = workflow_files(full)
        texts = list(files.values())
        old = old_versions(texts, current)
        adopted = any(CALLS_RE.search(t) for t in texts)
        if not adopted and repo["name"] not in (conf.get("no-workflows") or []):
            found.append("calls none of the shared workflows (docs/adopting.md)")
        if old:
            found.append(f"calls the shared workflows at {', '.join('@v' + str(v) for v in old)}; the current is @v{current} (docs/migrating.md)")
        elif adopted:
            # At an older major the migration rewrites every caller; compared
            # once it is on the current one.
            try:
                central = repo["name"] == ".github"
                found += caller_lines(callers_drift(files, conf, central), central)
            except ValueError as exc:  # a workflow that does not parse is reported, not skipped
                found.append(f"its workflow callers could not be compared: {str(exc)[:200]}")
        for w, r in pinned_calls(texts):
            found.append(f"calls `{w}` at `@{r}` instead of `@v{current}`: nothing is pinned to a commit in any repository (docs/workflows.md, #136)")
        # Said, never guessed: a ruleset that cannot be read is reported as
        # such, not as nothing to report.
        try:
            mine = rulesets(full)
            org = org_rulesets()
        except RuntimeError as exc:
            found.append(f"its rulesets could not be checked: {exc}")
            mine, org = None, []
        if mine is not None and own_checks_spec(full, default, texts) and not any(r.get("name") == OWN for r in mine):
            found.append(f"no \"{OWN}\" ruleset: nothing requires its own jobs' checks (`sync-repos.py own-checks`)")
        for _, rname in superseded(repo["name"], mine or [], org, pipeline_jobs()):
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
    template, dependabot = dependabot_wanted(repo, conf, default)
    out = gh("api", f"repos/{full}/contents/{DEPENDABOT}?ref={default}", "-H", "Accept: application/vnd.github.raw", check=False)
    if out.returncode != 0 and "404" not in out.stderr:
        raise RuntimeError(f"could not read {DEPENDABOT}: {out.stderr.strip()[:200]}")
    if out.returncode != 0:
        found.append(f"`{DEPENDABOT}` is missing (its template: `{template}`; `sync-repos.py files`)")
    elif out.stdout != dependabot:
        found.append(f"`{DEPENDABOT}` differs from its template, `{template}` (`sync-repos.py files`)")
    if (conf.get("security") or {}).get("automated_security_fixes"):
        out = gh("api", f"repos/{full}/automated-security-fixes", check=False)
        # Said only when GitHub answers that they are off.
        if out.returncode == 0 and json.loads(out.stdout or "{}").get("enabled") is False:
            found.append("Dependabot security updates are off (`sync-repos.py settings`)")
    out = gh("api", f"repos/{full}/contents/AGENTS.md?ref={default}", "-H", "Accept: application/vnd.github.raw", check=False)
    if out.returncode == 0:
        try:
            if with_block(out.stdout, block) != out.stdout:
                found.append("`AGENTS.md` does not carry the organisation's current block")
        except ValueError:
            found.append("`AGENTS.md` has a broken dx:org block")
    else:
        found.append("no `AGENTS.md`")
    system = (conf.get("design-system") or {}).get(repo["name"])
    if system == "local":
        out = gh("api", f"repos/{full}/contents/docs/design-system/README.md?ref={default}", "-H", "Accept: application/vnd.github.raw", check=False)
        if out.returncode != 0 and "404" not in out.stderr:
            raise RuntimeError(f"could not read docs/design-system/README.md: {out.stderr.strip()[:200]}")
        if out.returncode != 0:
            found.append("its design system is `local` (repos.yml), but it has no `docs/design-system/README.md`")
    elif system is not None and system not in design_systems():
        found.append(f"its design system `{system}` (repos.yml) is not one of design-systems/")
    return found


def callers_test(check, conf):
    """The callers' comparison and rewrite (#150), against the templates."""
    spec = conf.get("callers") or {}
    owned = spec.get("repository-owned") or {}
    tpl = {name: text for name, (text, _) in templates().items()}
    for name in spec.get("every-repository") or []:
        check(f"callers: every-repository names a template ({name})", name in tpl, sorted(tpl))
    for name, keys in owned.items():
        given = {k for job in jobs_of(parse_yaml(tpl.get(name, ""))).values() for k in (job.get("with") or {})}
        check(f"callers: every input repository-owned in {name} is one its template sets", name in tpl and set(keys) <= given, (keys, given))
    issues = tpl["issues.yml"]
    comments = tpl["pull-request-comments.yml"]
    # The support-url line, and what follows its value (a comment, #170).
    url_line = re.search(r"^      support-url: https://example\.com/support.*\n", issues, re.M).group(0)
    note = url_line[len("      support-url: https://example.com/support"):]
    # The fixture of C1: an issues.yml from before #120, without repro-triaged,
    # with its own support URL, an input and a job of its own.
    start = issues.index("  repro-triaged:")
    old = issues[:start] + issues[issues.index("  # When a person accepts"):]
    old = old.replace("https://example.com/support", "https://wordpress.org/support/plugin/mine/")
    old = old.replace("name: Issues\n", "name: Issues\n\n# Mine: this header stays.\n")
    old += "    with:\n      workflow: Pull request\n\n  mine:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo mine\n"
    files = {".github/workflows/issues.yml": old, ".github/workflows/pull-request-comments.yml": comments}
    got = callers_drift(files, conf)
    check("C1 (#150): a caller without the template's repro-triaged is out of step, with the job",
          got == [("issues.yml", ".github/workflows/issues.yml", ["lacks the job `repro-triaged`"])], got)
    lines = caller_lines(got)
    check("C1 (#150): the report names the caller, the job and the template's path",
          len(lines) == 1 and "`.github/workflows/issues.yml`" in lines[0] and "`repro-triaged`" in lines[0] and "`workflow-templates/issues.yml`" in lines[0], lines)
    # The fixture of C2: the template but its support URL, the profile, an
    # input and a job of the repository's own, an own job in a `needs`.
    same = issues.replace("https://example.com/support", "https://diluxone.com/support/") + "\n  mine:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo mine\n"
    checks = tpl["plugin-checks-wp.yml"].replace("slug: my-plugin", "slug: mine\n      main-file: mine.php\n      php-versions: '[\"8.3\"]'")
    checks = checks.replace("needs: [checks, tests]", "needs: [checks, tests, coverage]")
    c2 = {".github/workflows/issues.yml": same, ".github/workflows/pull-request-comments.yml": comments.replace("profile: general", "profile: plugin-wp"),
          ".github/workflows/plugin-checks.yml": checks}
    check("C2 (#150): a caller that differs only in what is the repository's own is in step", callers_drift(c2, conf) == [], callers_drift(c2, conf))
    # C2 (#170): comments are not compared. A caller copied before the
    # templates' comments changed, or with comments of its own, is in step.
    before = same.replace("# with the label repro:run.\n", "# with the label repro:run. Fill in support-url.\n").replace(note, "\n")
    before = before.replace("  repro:\n", "  # Mine: a note on a job.\n  repro:\n").replace("      trigger: triage\n", "      trigger: triage # mine\n")
    old_profile = re.sub(r"(      profile: general) #.*", r"\1 # or plugin-wp for a WordPress plugin; with general, the kind in .github/review-policy.yml adds its own", comments)
    commented = {**c2, ".github/workflows/issues.yml": before, ".github/workflows/pull-request-comments.yml": old_profile}
    check("C2 (#170): a caller whose comments differ from the template's is in step",
          before != same and old_profile != comments and callers_drift(commented, conf) == [], callers_drift(commented, conf))
    check("callers: a template whose workflows the repository does not call does not apply",
          not any(n == "release-wp.yml" for n, _, _ in callers_drift(files, conf)), callers_drift(files, conf))
    check("callers: a repository with no caller of an every-repository template is told so",
          callers_drift({".github/workflows/issues.yml": same}, conf) == [("pull-request-comments.yml", None, ["has no caller of `workflow-templates/pull-request-comments.yml`"])],
          callers_drift({".github/workflows/issues.yml": same}, conf))
    named = same.replace(f"    with:\n      support-url: https://diluxone.com/support/{note}    secrets: inherit",
                         f"    with:\n      support-url: https://diluxone.com/support/{note}    secrets:\n      DILUX_BOT_PRIVATE_KEY: ${{{{ secrets.DILUX_BOT_PRIVATE_KEY }}}}")
    named = named.replace("      trigger: triage", "      trigger: label").replace("      actions: write\n", "      actions: read\n")
    named = named.replace("uses: DiluxOne/.github/.github/workflows/issue-accepted.yml@v5", "uses: DiluxOne/.github/.github/workflows/issue-accepted.yml@v4")
    got = callers_drift({**c2, ".github/workflows/issues.yml": named}, conf)
    text = "\n".join(got[0][2]) if got else ""
    check("callers: secrets by name where the template inherits, an input, permissions and a major that differ",
          all(s in text for s in ("job `triage` passes its secrets by name", "job `repro-triaged` passes `trigger: label`, not `triage`",
                                  "job `accepted` has other permissions", "job `accepted` calls `DiluxOne/.github/.github/workflows/issue-accepted.yml@v4`")), got)
    weekly = checks.replace("needs: [checks, tests, coverage]", "needs: [checks]")
    got = callers_drift({**c2, ".github/workflows/plugin-checks.yml": weekly}, conf)
    check("callers: a `needs` without one of the template's jobs differs", got and "job `weekly-failure` needs `checks`, not `checks, tests`" in got[0][2], got)
    local = comments.replace("DiluxOne/.github/.github/workflows/review-reply.yml@v5", "./.github/workflows/review-reply.yml")
    check("callers: in DiluxOne/.github a local call is the same workflow",
          callers_drift({**c2, ".github/workflows/pull-request-comments.yml": local}, conf, central=True) == [], "")
    check("callers: DiluxOne/.github's own lines say by hand, not `callers` (which skips it)",
          "by hand" in caller_lines(callers_drift(files, conf, True), True)[0] and "`sync-repos.py callers`" not in caller_lines(callers_drift(files, conf, True), True)[0], "")
    odd = dict(jobs_of(parse_yaml(issues))["triage"], uses="./local.yml")
    check("callers: a template job with no shared `uses:` is compared as text, not a crash",
          job_differences("x", odd, dict(odd, uses="./other.yml"), set()) == ["job `x` calls `./other.yml`, not `./local.yml`"] and job_differences("x", odd, odd, set()) == [], "")
    check("callers: elsewhere a local call is not", callers_drift({**c2, ".github/workflows/pull-request-comments.yml": local}, conf) != [], "")
    # The rewrite: only what differs, the repository's values and jobs kept.
    new, missing = rewrite_caller(old, issues, set(owned["issues.yml"]))
    check("rewrite: the caller comes out in step", new is not None and callers_drift({**files, ".github/workflows/issues.yml": new}, conf) == [], (missing, new))
    new = new or ""
    check("rewrite: its support URL, header, own input and own job are kept",
          all(s in new for s in ("support-url: https://wordpress.org/support/plugin/mine/", "# Mine: this header stays.", "workflow: Pull request", "  mine:\n")) and "example.com" not in new, new)
    check("rewrite: repro-triaged goes after repro, before accepted",
          new.index("  repro:\n") < new.index("  repro-triaged:\n") < new.index("  accepted:\n"), new)
    check("rewrite: a caller in step is left as it is", rewrite_caller(same, issues, set(owned["issues.yml"]))[0] == same.rstrip("\n") + "\n", "")
    fixed, _ = rewrite_caller(named, issues, set(owned["issues.yml"]))
    check("rewrite: secrets, inputs, permissions and the major back to the template's",
          fixed is not None and callers_drift({**c2, ".github/workflows/issues.yml": fixed}, conf) == [], fixed)
    perms = checks.replace("      checks: read # and the checks of its head\n", "")
    fixed, _ = rewrite_caller(perms, tpl["plugin-checks-wp.yml"], set(owned["plugin-checks-wp.yml"]))
    check("rewrite: a job's own inputs and its own `needs` survive the template's job",
          fixed is not None and callers_drift({**c2, ".github/workflows/plugin-checks.yml": fixed}, conf) == []
          and "main-file: mine.php" in fixed and "slug: mine" in fixed and "coverage" in fixed, fixed)
    waits = comments.replace("  reply:\n", "  reply:\n    needs: [mine]\n").replace("    secrets: inherit", "    secrets:\n      DILUX_BOT_PRIVATE_KEY: ${{ secrets.DILUX_BOT_PRIVATE_KEY }}")
    fixed, _ = rewrite_caller(waits, comments, set(owned["pull-request-comments.yml"]))
    check("rewrite: a job's own `needs` stays where the template's job waits for nothing",
          fixed is not None and "    needs: [mine]\n" in fixed and "secrets: inherit" in fixed, fixed)
    bare = old.replace(f"    with:\n      support-url: https://wordpress.org/support/plugin/mine/{note}", "")
    check("rewrite: an input to fill in that the repository never gives stops it",
          rewrite_caller(bare.replace("  triage:", "  triaged:"), issues, set(owned["issues.yml"])) == (None, ["support-url"]),
          rewrite_caller(bare.replace("  triage:", "  triaged:"), issues, set(owned["issues.yml"])))
    two = issues.replace("    with:\n" + url_line, "")
    named_only = two.replace("  repro-triaged:", "  repro-mine:")
    got = rewrite_caller(named_only.replace("  triage:", "  triaged:"), two.replace("trigger: triage", "trigger: triage\n      support-url: x"), {"support-url", "trigger"})
    check("rewrite: the inputs it says are missing are only those no job gives", got == (None, ["support-url"]), got)
    # C3: `callers` against a stand-in for gh: one issue (Task), one pull
    # request closing it, the caller in it with the repository's support URL.
    calls, written = [], {}

    class Out:
        def __init__(self, stdout="", returncode=0, stderr=""):
            self.stdout, self.returncode, self.stderr = stdout, returncode, stderr

    def fake(*args, check=True, input_text=None):
        joined = " ".join(args)
        calls.append(args)
        if joined == "api repos/o/r/contents/.github/workflows":
            return Out(json.dumps([{"name": p.rsplit("/", 1)[1], "path": p} for p in files]))
        for p in files:
            if joined.startswith(f"api repos/o/r/contents/{p} "):
                return Out(files[p])
        if "matching-refs/tags/v" in joined:
            return Out(json.dumps([[{"ref": "refs/tags/v5"}]]))
        if args[:2] in (("pr", "list"), ("issue", "list")):
            return Out("[]")
        if args[:2] == ("issue", "create"):
            return Out("https://github.com/o/r/issues/7\n")
        if args[:2] == ("pr", "create"):
            return Out("https://github.com/o/r/pull/8\n")
        if "ref/heads/main" in joined:
            return Out(json.dumps({"object": {"sha": "abc"}}))
        if joined.startswith("api -X PUT repos/o/r/contents/"):
            payload = json.loads(input_text)
            written[args[3].split("/contents/", 1)[1]] = (payload["branch"], base64.b64decode(payload["content"]).decode())
            return Out("{}")
        if joined.startswith("api -X"):
            return Out("{}")
        return Out("", 1, "HTTP 404")
    global ORG
    saved_gh, saved_org = globals()["gh"], ORG
    globals()["gh"], ORG = fake, "o"
    try:
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            sync_callers({"name": "r", "defaultBranchRef": {"name": "main"}}, conf, False)
    finally:
        globals()["gh"], ORG = saved_gh, saved_org
    issues_opened = [a for a in calls if a[:2] == ("issue", "create")]
    prs = [a for a in calls if a[:2] == ("pr", "create")]
    check("C3 (#150): one issue, set to Task", len(issues_opened) == 1 and any(a[:3] == ("api", "-X", "PATCH") and "type=Task" in a for a in calls), calls)
    body = prs[0][prs[0].index("--body") + 1] if len(prs) == 1 else ""
    title = prs[0][prs[0].index("--title") + 1] if len(prs) == 1 else ""
    check("C3 (#150): one pull request that closes it, from ci/7-…, its title a short Conventional Commit",
          len(prs) == 1 and "Closes #7" in body and prs[0][prs[0].index("--head") + 1] == "ci/7-org-workflow-callers"
          and re.fullmatch(r"ci: .{1,68}", title) is not None, prs)
    branch, content = written.get(".github/workflows/issues.yml", ("", ""))
    check("C3 (#150): the caller in it has repro-triaged and keeps the repository's support URL",
          branch == "ci/7-org-workflow-callers" and "  repro-triaged:" in content and "support-url: https://wordpress.org/support/plugin/mine/" in content, written)
    check("C3 (#150): a caller in step is not rewritten", ".github/workflows/pull-request-comments.yml" not in written, sorted(written))
    # One file that is the caller of two templates gets both rewrites.
    reply = comments[comments.index("\njobs:\n") + len("\njobs:\n"):].replace("    secrets: inherit", "    secrets:\n      DILUX_BOT_PRIVATE_KEY: ${{ secrets.DILUX_BOT_PRIVATE_KEY }}")
    files.clear()
    files[".github/workflows/all.yml"] = old.rstrip("\n") + "\n\n" + reply
    calls.clear()
    written.clear()
    globals()["gh"], ORG = fake, "o"
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            sync_callers({"name": "r", "defaultBranchRef": {"name": "main"}}, conf, False)
    finally:
        globals()["gh"], ORG = saved_gh, saved_org
    both = written.get(".github/workflows/all.yml", ("", ""))[1]
    check("callers: a file that is the caller of two templates takes both rewrites",
          "  repro-triaged:" in both and "  reply:" in both and callers_drift({".github/workflows/all.yml": both}, conf) == [], both)


def dependabot_test(check, conf, labels, block):
    """The Dependabot templates and what `files` and `check` do with them (#178)."""
    templates_found = [DEPENDABOT_DEFAULT] + sorted(f"kinds/{k}/dependabot.yml" for k in os.listdir(os.path.join(CENTRAL, "kinds"))
                                                    if os.path.isfile(os.path.join(CENTRAL, "kinds", k, "dependabot.yml")))
    check("dependabot: the wordpress-plugin kind has its template", "kinds/wordpress-plugin/dependabot.yml" in templates_found, templates_found)
    names = {str(l["name"]) for l in labels}
    every = {"github-actions": ["/"], "npm": ["/"], "composer": ["/"], "docker": ["/"]}
    for path in templates_found:
        text = open(os.path.join(CENTRAL, path), encoding="utf-8").read()
        data = parse_yaml(text)
        updates = data.get("updates") or []
        check(f"dependabot {path}: version 2, one entry per ecosystem the organisation's repositories use",
              data.get("version") == 2 and sorted(u.get("package-ecosystem") for u in updates) == sorted(every), updates)
        # C2: daily, no cooldown, majors included, one pull request per ecosystem.
        check(f"C2 (#178) {path}: every ecosystem checked daily, with no cooldown and nothing ignored",
              all((u.get("schedule") or {}).get("interval") == "daily" and "cooldown" not in u and "ignore" not in u for u in updates), updates)
        groups = [g for u in updates for g in (u.get("groups") or {}).values()]
        check(f"C2 (#178) {path}: every group takes every dependency and every kind of update, majors included",
              groups and all(g.get("patterns") == ["*"] and not set(g) - {"patterns", "applies-to"} for g in groups), groups)
        check(f"C2 (#178) {path}: one group for the version updates and one for the security updates per ecosystem",
              all(sorted((g.get("applies-to") or "version-updates") for g in (u.get("groups") or {}).values()) == ["security-updates", "version-updates"] for u in updates), updates)
        check(f"dependabot {path}: labels the organisation has, Conventional Commit prefixes with their scope",
              all(set(u.get("labels") or []) <= names and (u.get("labels") or []) and (u.get("commit-message") or {}).get("prefix") in ("ci", "build")
                  and (u.get("commit-message") or {}).get("include") == "scope" for u in updates), (updates, sorted(names)))
        check(f"dependabot {path}: every entry has one `directories:` line to fill in",
              all(sum(1 for l in lines if DIRECTORIES_RE.match(l)) == 1 for _, lines in dependabot_entries(text)[1]), "")
        check(f"dependabot {path}: written with every ecosystem at the root, it is the template itself", render_dependabot(text, every, {}) == text, render_dependabot(text, every, {}))
    plugin = open(os.path.join(CENTRAL, "kinds/wordpress-plugin/dependabot.yml"), encoding="utf-8").read()
    check("dependabot: a kind's template, else the default", [dependabot_template(k) for k in ("wordpress-plugin", None, "nope", "../kinds/wordpress-plugin")]
          == ["kinds/wordpress-plugin/dependabot.yml", DEPENDABOT_DEFAULT, DEPENDABOT_DEFAULT, DEPENDABOT_DEFAULT], "")
    got = parse_yaml(render_dependabot(plugin, dependabot_ecosystems({"package.json", "composer.json", "readme.txt"}, {}), {}))
    check("C1 (#178): a plugin with a package.json and a composer.json gets github-actions, npm and composer, no docker",
          [u["package-ecosystem"] for u in got["updates"]] == ["github-actions", "npm", "composer"], got)
    got = parse_yaml(render_dependabot(plugin, dependabot_ecosystems({"readme.txt"}, {}), {}))
    check("C1 (#178): a plugin with no manifest gets github-actions alone", [u["package-ecosystem"] for u in got["updates"]] == ["github-actions"], got)
    extra = (conf.get("dependabot") or {}).get(".github") or {}
    default = open(os.path.join(CENTRAL, DEPENDABOT_DEFAULT), encoding="utf-8").read()
    mine = render_dependabot(default, dependabot_ecosystems({"README.md", "runner"}, extra), extra)
    got = parse_yaml(mine)
    docker = [u for u in got["updates"] if u["package-ecosystem"] == "docker"]
    check("C1 (#178): an addition repos.yml allows (directories, ignore) is kept",
          docker and docker[0]["directories"] == ["/runner"] and docker[0]["ignore"][0]["dependency-name"] == "ubuntu", got)
    here = open(os.path.join(CENTRAL, DEPENDABOT), encoding="utf-8").read()
    check("C1 (#178): this repository's own .github/dependabot.yml is in step with its template", here == mine, mine)
    try:
        render_dependabot(default, {"pip": ["/"]}, {})
        check("dependabot: an ecosystem the template lacks stops it", False, "no error")
    except ValueError:
        check("dependabot: an ecosystem the template lacks stops it", True)
    check("repos.yml: `dependabot` names repositories, ecosystems of the templates, directories and ignore only", dependabot_problems(conf) == [], dependabot_problems(conf))
    bad = dependabot_problems({"dependabot": {"r": {"pip": {}, "npm": {"versioning-strategy": "auto"}, "docker": {"directories": ["runner"]}}, "s": ["npm"]}})
    check("repos.yml: an unknown ecosystem, a key it may not add, a relative directory and a list are refused", len(bad) == 4, bad)

    # C1 and C3 against a stand-in for gh: a plugin (package.json at its root)
    # whose dependabot.yml is the weekly one of before.
    class Out:
        def __init__(self, stdout="", returncode=0, stderr=""):
            self.stdout, self.returncode, self.stderr = stdout, returncode, stderr
    weekly = plugin.replace("interval: daily", "interval: weekly")
    state = {"dependabot": weekly, "fixes": True}
    calls, written = [], {}

    def fake(*args, check=True, input_text=None):
        joined = " ".join(args)
        calls.append(args)
        if joined.startswith("api repos/o/r/contents/.github/review-policy.yml"):
            return Out("kind: wordpress-plugin\n")
        if joined.startswith("api repos/o/r/contents/?ref="):
            return Out(json.dumps([{"name": "package.json"}, {"name": "plugin.php"}]))
        if joined.startswith(f"api repos/o/r/contents/{DEPENDABOT}?ref=main"):
            return Out(state["dependabot"]) if state["dependabot"] is not None else Out("", 1, "HTTP 404")
        if joined.startswith("api repos/o/r/contents/.github/CODEOWNERS"):
            return Out(conf["files"][".github/CODEOWNERS"])
        if joined.startswith("api repos/o/r/contents/AGENTS.md"):
            return Out(with_block("# AGENTS.md\n", block))
        if joined == "api repos/o/r/automated-security-fixes":
            return Out(json.dumps({"enabled": state["fixes"], "paused": False}))
        if args[:2] == ("label", "list"):
            return Out("[]")
        if args[:2] in (("pr", "list"), ("issue", "list")):
            return Out("[]")
        if args[:2] == ("issue", "create"):
            return Out("https://github.com/o/r/issues/7\n")
        if args[:2] == ("pr", "create"):
            return Out("https://github.com/o/r/pull/8\n")
        if "ref/heads/main" in joined:
            return Out(json.dumps({"object": {"sha": "abc"}}))
        if joined.startswith("api -X PUT repos/o/r/contents/"):
            payload = json.loads(input_text)
            written[args[3].split("/contents/", 1)[1]] = (payload["branch"], base64.b64decode(payload["content"]).decode())
            return Out("{}")
        if joined.startswith("api -X"):
            return Out("{}")
        if joined == "api repos/o/r":
            return Out("{}")
        return Out("", 1, "HTTP 404")
    global ORG
    saved_gh, saved_org = globals()["gh"], ORG
    repo = {"name": "r", "defaultBranchRef": {"name": "main"}}
    want = render_dependabot(plugin, {"github-actions": ["/"], "npm": ["/"]}, {})
    globals()["gh"], ORG = fake, "o"
    try:
        import contextlib
        import io
        lines = drift(repo, conf, [], block)
        state["dependabot"], state["fixes"] = want, False
        in_step = drift(repo, conf, [], block)
        state["dependabot"] = None
        missing = drift(repo, conf, [], block)
        state["dependabot"] = weekly
        with contextlib.redirect_stdout(io.StringIO()):
            sync_files(repo, conf, block, False)
    finally:
        globals()["gh"], ORG = saved_gh, saved_org
    check("C3 (#178): the drift check names a dependabot.yml that differs, and its template",
          any(f"`{DEPENDABOT}` differs from its template, `kinds/wordpress-plugin/dependabot.yml`" in l for l in lines), lines)
    check("C3 (#178): one in step is not reported", not any("dependabot.yml" in l for l in in_step), in_step)
    check("C3 (#178): a missing one is", any(f"`{DEPENDABOT}` is missing" in l for l in missing), missing)
    check("drift: Dependabot security updates off are reported, on are not",
          any("security updates are off" in l for l in in_step) and not any("security updates" in l for l in lines), (lines, in_step))
    prs = [a for a in calls if a[:2] == ("pr", "create")]
    check("C1 (#178): `files` writes the template's dependabot.yml, with the plugin's ecosystems, in a pull request that closes its issue",
          written.get(DEPENDABOT) == ("chore/7-org-shared-files", want) and len(prs) == 1 and "Closes #7" in prs[0][prs[0].index("--body") + 1], (sorted(written), prs))
    check("C1 (#178): the files in step are not rewritten", sorted(written) == [DEPENDABOT], sorted(written))


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
    known = design_systems()
    check("design systems: wordpress-admin is one", "wordpress-admin" in known, known)
    check("repos.yml: every design-system is a system of design-systems/ or local", design_system_problems(conf, known) == [], design_system_problems(conf, known))
    got = design_system_problems({"design-system": {"a": "wordpress-admin", "b": "local", "c": "material", "bad name": "local"}}, known)
    check("repos.yml: an unknown design system, and a name that is not a repository's, are refused", len(got) == 2 and "`material`" in got[0] and "bad name" in got[1], got)
    check("repos.yml: a design-system that is not a map is refused", design_system_problems({"design-system": ["a"]}, known) != [], "")
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
        if joined.startswith("api repos/o/r/contents/docs/design-system/"):
            return Out("", 1, "HTTP 404")
        if joined.startswith("api repos/o/r"):
            return Out(json.dumps({"allow_squash_merge": True, "allow_merge_commit": True}))
        return Out("", 1, "HTTP 404")
    globals()["gh"] = fake
    try:
        global ORG
        saved, ORG = ORG, "o"
        lines = drift({"name": "r"}, {"settings": {"allow_squash_merge": True, "allow_merge_commit": False, "has_wiki": False}, "files": {".github/CODEOWNERS": "* @soydiloreto\n"},
                                      "design-system": {"r": "local"}},
                      [{"name": "accepted", "color": "0E8A16", "description": "y"}, {"name": "planned", "color": "0E8A16"}], block)
        unknown = drift({"name": "r"}, {"design-system": {"r": "material"}}, [], block)
        named = drift({"name": "r"}, {"design-system": {"r": "wordpress-admin"}}, [], block)
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
    check("drift: a local design system with no docs/design-system/README.md", "no `docs/design-system/README.md`" in text, lines)
    check("drift: a design system design-systems/ does not have", any("`material`" in line for line in unknown), unknown)
    check("drift: a design system of design-systems/ is in step", not any("design system" in line for line in named), named)
    files = ["uses: DiluxOne/.github/.github/workflows/conventions.yml@v3", "uses: DiluxOne/.github/.github/workflows/issue-triage.yml@v5", "uses: actions/checkout@v7"]
    check("versions: an older major is found", old_versions(files, 5) == [3], old_versions(files, 5))
    check("versions: the current major is not", old_versions(files[1:], 5) == [], old_versions(files[1:], 5))
    check("versions: another owner's action is not", old_versions(["uses: actions/checkout@v2"], 5) == [], "")
    check("calls: a pinned commit counts as calling the shared workflows", bool(CALLS_RE.search("uses: DiluxOne/.github/.github/workflows/plugin-release-wp.yml@0123456789abcdef0123456789abcdef01234567")), "")
    pinned = ["uses: DiluxOne/.github/.github/workflows/plugin-release-wp.yml@0123456789abcdef0123456789abcdef01234567 # v5.4.0", "uses: DiluxOne/.github/.github/workflows/svn-auth-check.yml@main", "uses: DiluxOne/.github/.github/workflows/conventions.yml@v5", "uses: actions/checkout@0123456789abcdef0123456789abcdef01234567"]
    check("C3 (#136): a shared workflow called at a commit or a branch is named with its ref", pinned_calls(pinned) == [("plugin-release-wp.yml", "0123456789abcdef0123456789abcdef01234567"), ("svn-auth-check.yml", "main")], pinned_calls(pinned))
    check("C3 (#136): a call at v5, and another owner's pinned action, are not", pinned_calls(pinned[2:]) == [], pinned_calls(pinned[2:]))
    check("C3 (#136): a commented example is not a call, v5-foo is not a version", pinned_calls(["# uses: DiluxOne/.github/.github/workflows/x.yml@0123456789abcdef0123456789abcdef01234567", "uses: DiluxOne/.github/.github/workflows/y.yml@v5-foo"]) == [("y.yml", "v5-foo")], pinned_calls(["uses: DiluxOne/.github/.github/workflows/y.yml@v5-foo"]))
    check("C3 (#136): a quoted call at v5 is not pinned; a dotted tag and a branch ref are", pinned_calls(['uses: "DiluxOne/.github/.github/workflows/a.yml@v5"', "uses: 'DiluxOne/.github/.github/workflows/b.yml@v5.4.0'", "uses: DiluxOne/.github/.github/workflows/c.yml@refs/heads/main"]) == [("b.yml", "v5.4.0"), ("c.yml", "refs/heads/main")], pinned_calls(['uses: "DiluxOne/.github/.github/workflows/a.yml@v5"', "uses: 'DiluxOne/.github/.github/workflows/b.yml@v5.4.0'"]))
    spec = load_yaml(os.path.join(CENTRAL, "kinds", "wordpress-plugin", "pack.yml")).get("own-checks") or {}
    check("pack wordpress-plugin: own-checks names its callers and jobs", spec.get("callers-of") and spec.get("jobs"), spec)
    names = ["checks / PHPStan", "checks / What changed", "tests / E2E (single)", "tests / E2E (single)", "conventions / Conventions (branch, title, commits)", "review / Claude review", "Dependabot", "real-s3 / AWS"]
    check("own checks: its jobs' checks, once, sorted, without the skipped", own_contexts(names, spec) == ["checks / PHPStan", "tests / E2E (single)"], own_contexts(names, spec))
    check("own checks: a repository calling the checks needs one", calls_any(["uses: DiluxOne/.github/.github/workflows/plugin-checks-wp.yml@v5"], spec["callers-of"]))
    check("own checks: one calling only the issue workflows does not", not calls_any(["uses: DiluxOne/.github/.github/workflows/issue-triage.yml@v5"], spec["callers-of"]))
    saved_gh = globals()["gh"]
    globals()["gh"] = lambda *a, check=True, input_text=None: type("O", (), {"stdout": "", "returncode": 1, "stderr": "HTTP 502"})()
    try:
        own_checks_spec("o/r", "main", ["uses: DiluxOne/.github/.github/workflows/plugin-checks-wp.yml@v5"])
        check("own checks: a policy that cannot be read stops, rather than reads as no kind", False, "no error")
    except RuntimeError:
        check("own checks: a policy that cannot be read stops, rather than reads as no kind", True)
    globals()["gh"] = lambda *a, check=True, input_text=None: type("O", (), {"stdout": "", "returncode": 1, "stderr": "HTTP 404"})()
    check("own checks: no policy, no ruleset", own_checks_spec("o/r", "main", ["uses: DiluxOne/.github/.github/workflows/plugin-checks-wp.yml@v5"]) is None)
    globals()["gh"] = saved_gh
    check("pipeline: the organisation's required jobs", {"conventions", "review"} <= pipeline_jobs(), pipeline_jobs())
    check("kind: plain, quoted and with a comment", [policy_kind("kind: wordpress-plugin\n"), policy_kind('kind: "wordpress-plugin"\n'), policy_kind("a: b\nkind: 'x-y'  # mine\n"), policy_kind("other: 1\n")] == ["wordpress-plugin", "wordpress-plugin", "x-y", None])
    tag_rules = [{"type": "deletion"}, {"type": "update"}]
    pipe = {"conventions", "review", "auto-merge"}
    org = [{"name": "org: main", "target": "branch", "enforcement": "active", "conditions": {"repository_name": {"include": ["r"]}, "ref_name": {"include": ["~DEFAULT_BRANCH"]}}, "rules": [{"type": "pull_request"}, {"type": "deletion"}, {"type": "workflows"}]},
           {"name": "org: release tags", "target": "tag", "enforcement": "active", "conditions": {"repository_name": {"include": ["r"]}, "ref_name": {"include": ["refs/tags/*.*.*"]}}, "rules": tag_rules}]

    def rsc(*names):
        return {"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": n} for n in names]}}
    own_rs = {"id": 2, "name": OWN, "target": "branch", "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}}, "rules": [rsc("checks / PHPStan", "real-s3 / AWS")]}
    mine = [{"id": 1, "name": "main", "target": "branch", "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}}, "rules": [{"type": "deletion"}, {"type": "pull_request"}, rsc("checks / PHPStan", "conventions / Conventions", "review / Claude review")]},
            own_rs,
            {"id": 3, "name": "release tags", "target": "tag", "conditions": {"ref_name": {"include": ["refs/tags/*.*.*"]}}, "rules": tag_rules},
            {"id": 4, "name": "Tag protection", "target": "tag", "conditions": {"ref_name": {"include": ["~ALL"]}}, "rules": tag_rules},
            {"id": 5, "name": "release branches", "target": "branch", "conditions": {"ref_name": {"include": ["refs/heads/release/*"]}}, "rules": [{"type": "deletion"}]},
            {"id": 6, "name": "Copilot", "target": "branch", "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}}, "rules": [{"type": "copilot_code_review"}]},
            {"id": 7, "name": "suites", "target": "branch", "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}}, "rules": [rsc("real-azure / Blob")]}]
    got = superseded("r", mine, org, pipe)
    check("superseded: the old main (its checks the pipeline's or own) and a tag ruleset the same as the organisation's", got == [(1, "main"), (3, "release tags")], got)
    check("superseded: not a ruleset with a rule the organisation's lack, nor a check only it requires", all(i not in (6, 7) for i, _ in got), got)
    check("superseded: not the old main while \"own checks\" lacks one of its checks", superseded("r", [m for m in mine if m["id"] != 2], org, pipe) == [(3, "release tags")], superseded("r", [m for m in mine if m["id"] != 2], org, pipe))
    check("superseded: nothing while the organisation's rulesets do not cover the repository", superseded("other", mine, org, pipe) == [], superseded("other", mine, org, pipe))
    strict = [dict(mine[0], rules=[{"type": "pull_request", "parameters": {"required_approving_review_count": 2}}, rsc("checks / PHPStan")]), own_rs]
    check("superseded: not a ruleset whose rule is stricter than the organisation's", superseded("r", strict, org, pipe) == [], superseded("r", strict, org, pipe))
    bypassed = [dict(mine[0], bypass_actors=[{"actor_id": 9, "actor_type": "Integration", "bypass_mode": "always"}]), own_rs]
    check("superseded: not a ruleset someone may bypass that the organisation's do not let", superseded("r", bypassed, org, pipe) == [], superseded("r", bypassed, org, pipe))
    check("superseded: a disabled \"own checks\" covers nothing", superseded("r", [mine[0], dict(own_rs, enforcement="disabled")], org, pipe) == [], "")
    paused = [dict(o, enforcement="evaluate") for o in org]
    check("superseded: nothing when the organisation's are not active", superseded("r", mine, paused, pipe) == [], superseded("r", mine, paused, pipe))
    callers_test(check, conf)
    dependabot_test(check, conf, labels, block_file)
    if not failed:
        print("all tests passed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if not argv or argv[0] not in ("labels", "settings", "files", "own-checks", "callers", "all", "check"):
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
                  "What differs from `labels.yml`, `repos.yml`, `agents-block.md`, the Dependabot templates (`kinds/<kind>/dependabot.yml`, `policy/dependabot.default.yml`) and `workflow-templates/`. Labels and settings: `python3 scripts/sync-repos.py all`; files and Dependabot: the pull requests it opens; workflow callers: `python3 scripts/sync-repos.py callers --repo NAME`, a pull request each.", ""]
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
            if what == "callers":
                sync_callers(repo, conf, dry)
        except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
            failures += 1
            print(f"  failed: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
