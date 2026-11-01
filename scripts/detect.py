#!/usr/bin/env python3
"""What kind of project a repository looks like (#191), and its stack (#377).

Each pack says how to recognise its kind (kinds/<kind>/pack.yml, `detect`):
files that must be at the repository's root, a root file whose first lines
match a pattern (a plugin's header), and `any-files`, paths from the root of
which one at least must exist (a manifest in a folder: a plugin for coding
agents, #552). Detection only proposes: what a
repository is lives in repos.yml `repos:`, and a person merges that. The
daily drift check (scripts/sync-repos.py check) says, for a repository
repos.yml does not list, what detection proposes for it.

  detect.py NAME     the kinds repository NAME looks like, one per line
  detect.py way NAME [REF]
                     the way to reproduce a bug its stack proposes (#377),
                     as repos.yml `repro:` takes it; nothing when no stack of
                     policy/repro-stacks.yml matches
  detect.py adopt-issues
                     for each repository repos.yml does not list, one
                     "Adopt <repository>" Task issue, opened once, with the
                     entry detection proposes (org-drift.yml, every day,
                     #562): a maintainer's `accepted` is the only step
  detect.py adopt-body NAME
                     the body of NAME's Adopt issue, for a maintainer who
                     opens one by hand (title "Adopt NAME", label lane:adopt)
  detect.py adopt-pr NUMBER
                     for the Adopt issue NUMBER a maintainer accepted, the
                     pull request adding its entry to repos.yml
                     (org-adopt.yml; the `adopt` lane merges it)
  detect.py --test   self-test

A stack is not a kind: a repository of any kind, or of none, is written in
a language whose tests run one way. policy/repro-stacks.yml says how to
recognise each (its files: a pattern with ** anywhere in the tree, any
other at the root) and the way to reproduce a
bug it proposes (scripts/repro-ways.py), for a repository that declares
none: the installer adds it to repos.yml `repro:`, and the organisation's
audit (scripts/sync-repos.py check) and the autopilot name it.

Environment: GH_TOKEN (contents: read; for adopt-issues, issues: write on
DiluxOne/.github; for adopt-pr, contents and pull requests: write too).
"""
import fnmatch
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import org  # noqa: E402  the organisation, from org.yml (#191)
ORG = org.ORG
HEAD_BYTES = 8192


def load(path):
    import yaml
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def packs():
    """{kind: its `detect`} for every pack that says how to recognise it."""
    root = os.path.join(HERE, "..", "kinds")
    out = {}
    for kind in sorted(os.listdir(root)):
        path = os.path.join(root, kind, "pack.yml")
        if os.path.isfile(path) and load(path).get("detect"):
            out[kind] = load(path)["detect"]
    return out


def matches(rule, names, head, exists=None):
    """Whether a repository's root (its file names, and `head(name)`, the
    first bytes of a file) meets a pack's `detect`. `exists(path)` says
    whether a path below the root is a file (only `any-files` asks)."""
    if not rule.get("files") and not rule.get("header") and not rule.get("any-files"):
        return False  # a rule that checks nothing recognises nothing
    if not all(f in names for f in rule.get("files") or []):
        return False
    if rule.get("any-files"):
        exists = exists or (lambda path: path in names)
        if not any(exists(f) for f in rule["any-files"]):
            return False
    header = rule.get("header")
    if header:
        pattern = re.compile(header["pattern"])
        return any(pattern.search(head(n) or "") for n in sorted(names) if fnmatch.fnmatch(n, header["glob"]))
    return True


def kinds(names, head, rules=None, exists=None):
    """The kinds a repository's root looks like."""
    rules = packs() if rules is None else rules
    return [k for k, rule in rules.items() if matches(rule, names, head, exists)]


def gh(*args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"gh {args[0]} {args[1] if len(args) > 1 else ''}: {out.stderr.strip()[:200]}")
    return out.stdout


def run_gh(*args):
    """gh's (exit code, output, errors)."""
    out = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return out.returncode, out.stdout, out.stderr


def remote(full, default="main", run=run_gh):
    """The kinds a repository on GitHub looks like. `run` calls gh (a
    caller's stand-in in its self-test)."""
    rc, out, err = run("api", f"repos/{full}/contents/?ref={default}")
    if rc != 0:
        if "404" in err:  # empty: nothing to recognise
            return []
        raise RuntimeError(f"could not list its root: {err.strip()[:200]}")
    names = {e if isinstance(e, str) else e["name"] for e in json.loads(out or "[]") if isinstance(e, str) or e.get("type", "file") == "file"}

    def head(name):
        rc, text, _ = run("api", f"repos/{full}/contents/{name}?ref={default}", "-H", "Accept: application/vnd.github.raw")
        return text[:HEAD_BYTES] if rc == 0 else ""

    def exists(path):
        if "/" not in path:
            return path in names
        rc, out, err = run("api", f"repos/{full}/contents/{path}?ref={default}")
        if rc != 0:
            if "404" in err:  # not there
                return False
            raise RuntimeError(f"could not read {path}: {err.strip()[:200]}")
        try:
            return json.loads(out or "{}").get("type") == "file"
        except (ValueError, AttributeError):
            return False
    return kinds(names, head, exists=exists)


STACKS = os.path.join(HERE, "..", "policy", "repro-stacks.yml")
# Folders of what a repository installs or builds, never its own tests.
INSTALLED = re.compile(r"(^|/)(node_modules|vendor|bower_components|bin|obj)/")


def stacks(path=STACKS):
    """{stack: {detect, name, way}}, in the order written."""
    return (load(path).get("stacks") or {}) if os.path.isfile(path) else {}


def glob(path, pattern):
    """fnmatch where ** spans folders and * stays inside one."""
    rx = re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
    return re.fullmatch(rx, path) is not None


# The keys of a way that are shell commands, where a path goes quoted.
COMMANDS = ("setup", "theme", "run", "teardown")


def filled(way, match):
    """A stack's way for the file that matched: {match} that file,
    {match-dir} its folder (nothing, at the root); quoted for the shell in
    a command."""
    import shlex
    folder = os.path.dirname(match)

    def fill(value, quote):
        if isinstance(value, list):
            return [fill(v, quote) for v in value]
        if not isinstance(value, str):
            return value
        m = shlex.quote(match) if quote else match
        d = shlex.quote(folder or ".") if quote else folder or "."
        return value.replace("{match-dir}/", folder + "/" if folder else "").replace("{match-dir}", d).replace("{match}", m)
    return {k: fill(v, k in COMMANDS) for k, v in way.items()}


def stack_way(paths, read, rules=None, reads=50):
    """(stack, the way's name, the way) for the first stack whose `detect`
    the repository's files meet (`read(path)`: a file's text); None when
    none does. At most `reads` files are read."""
    rules = stacks() if rules is None else rules
    files = sorted(p for p in paths if not INSTALLED.search(p))
    budget = [reads]

    def holds(path, text):
        if not text:
            return True
        if budget[0] <= 0:  # never "no stack" for what was not read
            raise RuntimeError(f"more than {reads} files to read to recognise its stack")
        budget[0] -= 1
        return text in (read(path) or "")
    for stack, s in rules.items():
        for rule in s.get("detect") or []:
            for path in files:
                if glob(path, rule["path"]) and holds(path, rule.get("contains")):
                    return stack, s["name"], filled(s["way"], path)
    return None


def tree(full, ref="main", run=run_gh):
    """Every file of a repository on GitHub, at REF. A tree GitHub
    truncates (more than 100,000 entries) is an error: a stack's file past
    the cut would read as no stack."""
    rc, out, err = run("api", f"repos/{full}/git/trees/{ref}?recursive=1")
    if rc != 0:
        if "409" in err:  # empty: no files
            return []
        raise RuntimeError(f"could not list its files: {err.strip()[:200]}")
    data = json.loads(out or "{}")
    if data.get("truncated"):
        raise RuntimeError("its tree is too large for GitHub to list whole")
    return [e["path"] for e in (data.get("tree") or []) if e.get("type") == "blob"]


def remote_way(full, ref="main", run=run_gh):
    """stack_way of a repository on GitHub."""
    def read(path):
        rc, text, err = run("api", f"repos/{full}/contents/{path}?ref={ref}", "-H", "Accept: application/vnd.github.raw")
        if rc != 0:  # a file it cannot read is no file without the text
            raise RuntimeError(f"could not read {path}: {err.strip()[:120]}")
        return text[:65536]
    return stack_way(tree(full, ref, run), read)


def remote_policy(full, ref="main", run=run_gh):
    """A repository's own .github/review-policy.yml on GitHub, as data
    ({} when it has none)."""
    import yaml
    rc, out, err = run("api", f"repos/{full}/contents/.github/review-policy.yml?ref={ref}", "-H", "Accept: application/vnd.github.raw")
    if rc != 0:
        if "404" in err:
            return {}
        raise RuntimeError(f"could not read its review policy: {err.strip()[:200]}")
    data = yaml.safe_load(out or "") or {}
    return data if isinstance(data, dict) else {}


def way_yaml(name, way, indent=0):
    """A way as YAML: `name:` and its keys, indented."""
    import yaml
    text = yaml.safe_dump({name: way}, sort_keys=False, allow_unicode=True, width=200)
    return "".join(" " * indent + line + "\n" for line in text.rstrip("\n").split("\n"))


def entry(name, found, rules):
    """The repos.yml line for a new repository: its kinds over "**", with
    the roles their packs propose; an unclassified one when none."""
    if not found:
        return f"  {name}: {{kinds: []}}"
    parts = [f"{{kind: {k}, paths: [\"**\"], roles: [{', '.join(rules[k].get('roles') or [])}]}}" for k in found]
    return f"  {name}: {{kinds: [{', '.join(parts)}]}}"


def with_entries(text, lines):
    """repos.yml with each new line in its place, by name, in `repos:`."""
    out = text.split("\n")
    start = out.index("repos:")
    name = lambda l: l.strip().split(":", 1)[0].lower()
    for line in sorted(lines, key=name):
        # Before the first entry that sorts after it; the others stay as they are.
        i = start + 1
        # An entry written as a block (#562) goes on below its first line,
        # and a comment line between entries is passed over.
        while i < len(out) and out[i].startswith("  ") and (out[i].startswith("   ") or out[i].lstrip().startswith("#") or name(out[i]) < name(line)):
            i += 1
        out.insert(i, line)
    return "\n".join(out)


# "Adopt <repository>" (#562): one Task issue per repository of the
# organisation that repos.yml lacks, opened once and found by its title. Its
# body is a PRD (G1), with the entry detection proposes as a YAML block a
# maintainer may correct, and a marker naming the repository. A maintainer's
# `accepted` is the only step: org-adopt.yml then opens the pull request
# that adds that entry to repos.yml (the `adopt` lane merges it by policy)
# and, once it is merged, adopts the repository (sync-repos.py adopt).
ADOPT_TITLE = "Adopt {}"
ADOPT_MARKER = re.compile(r"<!--\s*dx-adopt:\s*([A-Za-z0-9._-]+)\s*-->")
ADOPT_BLOCK = re.compile(r"^```ya?ml\n(.*?)^```", re.M | re.S)
AI_LINE = "🤖 AI-generated · detect.py (DiluxOne)"


def adopt_entry(name, found, rules):
    """The entry an Adopt issue proposes, as YAML: its kinds (detection's),
    the attributes left to say, commented."""
    line = entry(name, found, rules)
    return (line.strip() + "\n"
            "# Add what detection cannot know, in the braces: project: <its Project's number>,\n"
            "# design-system: <one of design-systems/>, callers: {<input>: <value>} (repos.yml, #562).\n")


def adopt_body(name, found, rules, unread=False):
    """The Adopt issue's body: a PRD whose scope is the proposed entry."""
    seen = (f"Detection (scripts/detect.py) recognises it as {', '.join(found)}." if found else
            "Detection (scripts/detect.py) could not read it, so it is proposed unclassified." if unread else
            "Detection (scripts/detect.py) recognises no kind in it, so it is proposed unclassified.")
    return (f"<!-- dx-adopt: {name} -->\n### Problem\n\n{ORG}/{name} is a repository of the organisation that repos.yml does not list, so it is outside the flow: "
            f"no ruleset of the organisation covers it, its security, callers, `make pre-pr` and Dependabot file are not kept, and it is on no Project. {seen}\n\n"
            "### Scope\n\n- Its entry in repos.yml, as below (correct it here before accepting: the entry used is this block as it is when `accepted` is added).\n"
            f"- `sync-repos.py adopt --repo {name}` once that entry is merged.\n\n"
            f"```yaml\n{adopt_entry(name, found, rules)}```\n\n"
            "### Out of scope\n\n- Any other repository, and any other change to repos.yml.\n\n"
            f"### Acceptance criteria\n\n- C1: Given this issue accepted by a maintainer, when org-adopt.yml runs, then repos.yml lists {name} with the entry above "
            f"and `sync-repos.py check` finds nothing of it out of step but what a person must do.\n\n"
            f"### Criticality\n\nNormal\n\n{AI_LINE}")


def adopt_issues(conf, repos, found_of, io):
    """One Adopt issue for each repository repos.yml lacks, unless one with
    its title was ever opened (open or closed: a closed one is a decision).
    The numbers opened, in order."""
    listed = conf.get("repos") or {}
    new = sorted(r for r in repos if r not in listed)
    if not new:
        print("Every repository is in repos.yml.")
        return []
    rules, opened = packs(), []
    for n in new:
        title = ADOPT_TITLE.format(n)
        if io["find_issue"](title):
            print(f"  {n}: \"{title}\" is already open, or was closed")
            continue
        # One repository that cannot be read is proposed unclassified, and said.
        try:
            found, unread = found_of(n), False
        except RuntimeError as exc:
            print(f"  {n}: detection failed ({str(exc)[:120]}); proposed unclassified")
            found, unread = [], True
        opened.append(io["issue"](title, adopt_body(n, found, rules, unread)))
    return opened


def adopt_of(body):
    """(name, entry) an Adopt issue's body names and proposes: the entry as
    data ({kinds, ...}); (None, None) when it carries no marker or no block
    that is one entry for that name."""
    import yaml
    m, block = ADOPT_MARKER.search(body or ""), ADOPT_BLOCK.search(body or "")
    if not m or not block:
        return None, None
    try:
        data = yaml.safe_load(block.group(1))
    except yaml.YAMLError:
        return m.group(1), None
    if not isinstance(data, dict) or list(data) != [m.group(1)] or not isinstance(data[m.group(1)], dict):
        return m.group(1), None
    return m.group(1), data[m.group(1)]


def entry_text(name, value):
    """repos.yml's line for an entry: its flow form, as the file writes them."""
    import yaml
    return f"  {name}: " + yaml.safe_dump(value, default_flow_style=True, sort_keys=False, width=10000).strip()


def run_adopt_issues():
    """adopt-issues, against GitHub, from a checkout of DiluxOne/.github's main."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("sync_repos", os.path.join(HERE, "sync-repos.py"))
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    central = os.environ.get("GITHUB_REPOSITORY", f"{ORG}/.github")
    conf = load(os.path.join(HERE, "..", "repos.yml"))
    rows = sync.repositories([], conf.get("exclude") or [])
    defaults = {r["name"]: (r.get("defaultBranchRef") or {}).get("name") or "main" for r in rows}

    def find_issue(title):
        found = json.loads(gh("issue", "list", "--repo", central, "--state", "all", "--search", f"in:title \"{title}\"", "--json", "title,number"))
        return next((str(i["number"]) for i in found if i["title"] == title), None)

    def issue(title, body):
        url = gh("issue", "create", "--repo", central, "--title", title, "--label", "lane:adopt", "--body", body).strip()
        n = url.rsplit("/", 1)[-1]
        subprocess.run(["gh", "api", "-X", "PATCH", f"repos/{central}/issues/{n}", "-f", "type=Task"], capture_output=True)
        print(f"Opened #{n}: {title}")
        return n

    adopt_issues(conf, list(defaults), lambda name: remote(f"{ORG}/{name}", defaults[name]), {"find_issue": find_issue, "issue": issue})
    return 0


def adopt_change(text, name, entry_value):
    """repos.yml's text with the Adopt issue's entry added in `repos:`, and
    nothing else."""
    return with_entries(text, [entry_text(name, entry_value)])


def run_adopt_pr(number):
    """adopt-pr NUMBER: for an Adopt issue a maintainer accepted, the pull
    request that adds its entry to repos.yml (the `adopt` lane's, #562),
    from a checkout of main; the issue is checked as the lane checks it."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("autonomy", os.path.join(HERE, "autonomy.py"))
    autonomy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(autonomy)
    central = os.environ.get("GITHUB_REPOSITORY", f"{ORG}/.github")
    issue = autonomy.read_issue(central, number)
    name, value, why = autonomy.adopt_issue(issue, central, autonomy.maintainer_of(central))
    if not name:
        print(f"Not adopted: {why}.")
        return 1
    root = os.path.join(HERE, "..")
    if name in (load(os.path.join(root, "repos.yml")).get("repos") or {}):
        print(f"{name} is already in repos.yml.")
        return 0
    branch = f"chore/{number}-adopt"
    title = f"chore(repos): adopt {name}"[:72]
    if json.loads(gh("pr", "list", "--repo", central, "--state", "open", "--head", branch, "--json", "number")):
        print(f"A pull request from {branch} is already open.")
        return 0
    with open(os.path.join(root, "repos.yml"), encoding="utf-8") as fh:
        text = adopt_change(fh.read(), name, value)
    g = lambda *a: subprocess.run(["git", "-C", root, "-c", f"user.name={org.BOT}", "-c", f"user.email={org.BOT_ID}+{org.BOT}@users.noreply.github.com", *a],
                                  check=True, capture_output=True, text=True)
    g("checkout", "-q", "-B", branch)
    with open(os.path.join(root, "repos.yml"), "w", encoding="utf-8") as fh:
        fh.write(text)
    g("commit", "-q", "-am", title)
    # Through the API, so GitHub signs the commit (#190); the branch is this
    # issue's alone, so a run that left it is rewritten.
    subprocess.run([sys.executable, os.path.join(HERE, "api-commit.py"), "push", branch, "--onto", "HEAD~1", "--force"], check=True, cwd=root)
    body = (f"## 📝 What changes\n\n`repos.yml` lists {name}, with the entry the Adopt issue proposes ({why}), and nothing else.\n\n"
            f"## 💡 Why\n\nA maintainer accepted adopting it; once this merges, org-adopt.yml runs `sync-repos.py adopt --repo {name}`, "
            "so the repository is in every ruleset, its security is on, its callers, `make pre-pr` and Dependabot file are kept and it is on its Project.\n\n"
            f"Closes #{number}\n\n{AI_LINE}")
    print(gh("pr", "create", "--repo", central, "--base", "main", "--head", branch, "--title", title, "--body", body).strip())
    return 0


def self_test():
    import importlib.util
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    rules = packs()
    check("the wordpress-plugin pack says how to recognise one", "wordpress-plugin" in rules, True)
    plugin = {"readme.txt": "=== X ===", "my-plugin.php": "<?php\n/**\n * Plugin Name: My Plugin\n * Version: 1.0\n */", "composer.json": "{}"}
    head = lambda files: (lambda n: files.get(n, ""))
    check("a plugin: a readme.txt and a header at its root", kinds(set(plugin), head(plugin), rules), ["wordpress-plugin"])
    check("a header with WordPress's other comment styles", kinds({"readme.txt", "p.php"}, head({"p.php": "<?php\n# Plugin Name: P"}), rules), ["wordpress-plugin"])
    nohead = dict(plugin, **{"my-plugin.php": "<?php echo 1;"})
    check("no plugin header, no plugin", kinds(set(nohead), head(nohead), rules), [])
    noreadme = {k: v for k, v in plugin.items() if k != "readme.txt"}
    check("no readme.txt, no plugin", kinds(set(noreadme), head(noreadme), rules), [])
    check("a site with a package.json is nothing a pack knows yet", kinds({"package.json", "next.config.js"}, head({}), rules), [])
    check("the header only in a root .php file", kinds({"readme.txt", "notes.md"}, head({"notes.md": "Plugin Name: no"}), rules), [])
    conf_text = "# head\nrepos:\n  a-repo: {kinds: []}\n  z-repo: {kinds: []}\n\nprojects:\n  a-repo: 1\n"
    import yaml
    added = with_entries(conf_text, [entry("m-plugin", ["wordpress-plugin"], rules), entry("b-site", [], rules)])
    check("propose: the new lines in their place, by name", [l.split(":")[0].strip() for l in added.split("\n") if l.startswith("  ") and "kinds" in l], ["a-repo", "b-site", "m-plugin", "z-repo"])
    check("propose: the file still parses, with the plugin's kind and roles",
          yaml.safe_load(added)["repos"]["m-plugin"], {"kinds": [{"kind": "wordpress-plugin", "paths": ["**"], "roles": ["back", "front"]}]})
    check("propose: the rest of the file is untouched", added.endswith("\n\nprojects:\n  a-repo: 1\n") and added.startswith("# head\n"), True)
    check("a rule that checks nothing recognises nothing", matches({"roles": ["back"]}, {"a"}, lambda n: ""), False)
    # A plugin for coding agents (#552): one manifest of tools.yml, in a folder or at the root.
    check("the ai-agent-plugin pack says how to recognise one", "ai-agent-plugin" in rules, True)
    at = lambda *paths: (lambda p: p in paths)  # noqa: E731
    check("a plugin for coding agents: Claude Code's manifest in its folder",
          kinds({"README.md"}, head({}), rules, at(".claude-plugin/plugin.json")), ["ai-agent-plugin"])
    check("a plugin for coding agents: another tool's manifest only",
          kinds({"README.md", "gemini-extension.json"}, head({}), rules), ["ai-agent-plugin"])
    check("a catalog (a marketplace, no plugin manifest) is not one",
          kinds({"README.md"}, head({}), rules, at(".claude-plugin/marketplace.json")), [])
    def fake_api(*args):
        if args[1].startswith("repos/o/p/contents/?"):
            return 0, json.dumps([{"name": "README.md", "type": "file"}, {"name": ".claude-plugin", "type": "dir"}]), ""
        if args[1].startswith("repos/o/p/contents/.claude-plugin/plugin.json"):
            return 0, json.dumps({"type": "file"}), ""
        return 1, "", "HTTP 404"
    check("remote: a manifest in a folder is looked up, and recognised", remote("o/p", "main", fake_api), ["ai-agent-plugin"])
    def broken_api(*args):
        if args[1].startswith("repos/o/p/contents/?"):
            return fake_api(*args)
        return 1, "", "HTTP 502: Bad Gateway"
    try:
        remote("o/p", "main", broken_api)
        check("remote: a failed read of a manifest is an error, not 'absent'", "absent", "error")
    except RuntimeError:
        check("remote: a failed read of a manifest is an error, not 'absent'", "error", "error")
    hand = "repos:\n  zeta: {kinds: []}\n  alpha: {kinds: []}\n"
    check("propose: hand-ordered lines stay where they are", with_entries(hand, ["  beta: {kinds: []}"]), "repos:\n  beta: {kinds: []}\n  zeta: {kinds: []}\n  alpha: {kinds: []}\n")
    # #562 C5: one "Adopt <repository>" issue per repository repos.yml lacks.
    spec = importlib.util.spec_from_file_location("issue_schema", os.path.join(HERE, "issue-schema.py"))
    schema = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(schema)
    issues, opened = {}, []

    def open_one(title, body):
        issues[title] = body
        opened.append(title)
        return str(40 + len(opened))
    io = {"find_issue": lambda t: t in issues, "issue": open_one}
    conf = yaml.safe_load(conf_text)
    got = adopt_issues(conf, ["a-repo", "z-repo", "new-one", "b-site"], lambda n: ["wordpress-plugin"] if n == "new-one" else [], io)
    check("C5: each repository repos.yml lacks gets its own Adopt issue", (got, opened), (["41", "42"], ["Adopt b-site", "Adopt new-one"]))
    body = issues["Adopt new-one"]
    check("C5: its body passes the issue schema (G1)", schema.check(body)["ok"], True)
    check("C5: it names the repository and proposes the kind detection found", adopt_of(body),
          ("new-one", {"kinds": [{"kind": "wordpress-plugin", "paths": ["**"], "roles": ["back", "front"]}]}))
    check("C5: one with no kind found is proposed unclassified, and says so", (adopt_of(issues["Adopt b-site"]), "recognises no kind" in issues["Adopt b-site"]), (("b-site", {"kinds": []}), True))
    check("C5: run again, never a second issue", (adopt_issues(conf, ["a-repo", "new-one", "b-site"], lambda n: [], io), len(opened)), ([], 2))
    check("C5: nothing when every repository is listed", adopt_issues(conf, ["a-repo", "z-repo"], lambda n: [], io), [])

    def broken(n):
        raise RuntimeError("HTTP 502")
    adopt_issues(conf, ["late"], broken, io)
    check("C5: a repository that cannot be read is proposed unclassified, and said", (adopt_of(issues["Adopt late"])[1], "could not read it" in issues["Adopt late"]), ({"kinds": []}, True))
    edited = body.replace("{kinds: [", "{project: 16, kinds: [")
    check("C5: a maintainer's correction of the block is the entry", adopt_of(edited)[1]["project"], 16)
    check("C5: a block naming another repository, or two, or none, is no entry",
          [adopt_of(body.replace("\nnew-one: {", "\nother: {"))[1], adopt_of(body.replace("```yaml\n", "```yaml\nx: {kinds: []}\n"))[1], adopt_of("no marker")[0]], [None, None, None])
    check("C5: the pull request's repos.yml is its base with that entry added, and nothing else",
          (yaml.safe_load(adopt_change(conf_text, "new-one", adopt_of(edited)[1]))["repos"]["new-one"],
           [l for l in adopt_change(conf_text, "new-one", adopt_of(edited)[1]).split("\n") if l not in conf_text.split("\n")]),
          (adopt_of(edited)[1], [entry_text("new-one", adopt_of(edited)[1])]))
    check("C5: the entry's line, as repos.yml writes them, reads back the same",
          yaml.safe_load("repos:\n" + entry_text("new-one", adopt_of(edited)[1]) + "\n")["repos"]["new-one"], adopt_of(edited)[1])

    # #377: a repository's stack, and the way to reproduce a bug it proposes.
    spec = importlib.util.spec_from_file_location("repro_ways", os.path.join(HERE, "repro-ways.py"))
    rw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rw)
    found = lambda files: stack_way(set(files), lambda p: files.get(p, ""))  # noqa: E731
    py = found({"pyproject.toml": "[project]\nname = 'x'\n[tool.pytest.ini_options]\n", "src/x/__init__.py": ""})
    check("C1 pyproject.toml with pytest: a Python way", (py[0], py[1], py[2]["test"]), ("python-pytest", "pytest", "tests/repro/test_issue_{n}.py"))
    check("C1 it writes a JUnit report the verdict reads, with each test's file", ("--junitxml=build/repro.xml" in py[2]["run"], py[2]["junit"], "junit_family=xunit1" in py[2]["run"]), (True, "build/repro.xml", True))
    check("C1 its needs are the file that matched", py[2]["needs"], ["pyproject.toml"])
    check("a pyproject.toml without pytest is no Python way", found({"pyproject.toml": "[project]\nname = 'x'\n"}), None)
    check("a pytest.ini is one", found({"pytest.ini": "[pytest]\n"})[1], "pytest")
    net = found({"src/Api/Api.csproj": '<Project Sdk="Microsoft.NET.Sdk"/>',
                 "tests/Api.Tests/Api.Tests.csproj": '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><PackageReference Include="Microsoft.NET.Test.Sdk" /></ItemGroup></Project>',
                 "Api.sln": ""})
    check("C2 a test project: a dotnet test way with a JUnit logger",
          (net[1], net[2]["run"].split(" dotnet test ")[1].split(" ")[0], "--logger \"junit;LogFilePath=" in net[2]["run"], net[2]["junit"]),
          ("dotnet-test", "tests/Api.Tests/Api.Tests.csproj", True, "build/repro.xml"))
    check("C2 its test goes into the test project, its logger is installed in setup",
          (net[2]["test"], any("JunitXml.TestLogger" in c for c in net[2]["setup"])), ("tests/Api.Tests/Repro/Issue{n}Tests.cs", True))
    spaced = found({"tests/My Tests/My.Tests.csproj": "Microsoft.NET.Test.Sdk"})[2]
    check("a path with a space goes quoted into the commands, as is into the test and needs",
          ("dotnet test 'tests/My Tests/My.Tests.csproj'" in spaced["run"], spaced["test"], spaced["needs"]),
          (True, "tests/My Tests/Repro/Issue{n}Tests.cs", ["tests/My Tests/My.Tests.csproj"]))
    check("C2 a project that is not a test project proposes nothing", found({"src/Api/Api.csproj": '<Project Sdk="Microsoft.NET.Sdk"/>'}), None)
    check("C2 a test project at the root: its test under Repro/",
          found({"Lib.Tests.csproj": "Microsoft.NET.Test.Sdk"})[2]["test"], "Repro/Issue{n}Tests.cs")
    check("a go.mod, a package.json with jest or vitest, a composer.json with PHPUnit",
          [found(f)[1] for f in ({"go.mod": "module x"}, {"package.json": '{"devDependencies": {"jest": "^30"}}'},
                                 {"package.json": '{"devDependencies": {"vitest": "^3"}}'}, {"composer.json": '{"require-dev": {"phpunit/phpunit": "^11"}}'})],
          ["go-test", "jest", "vitest", "phpunit"])
    check("what is installed is not the repository's (node_modules, vendor)",
          found({"node_modules/x/pytest.ini": "", "vendor/y/go.mod": ""}), None)
    check("a stack nothing recognises proposes nothing", found({"README.md": "x", "index.html": ""}), None)
    check("every stack's way is a way repro-ways.py takes",
          {s: rw.problems({"ways": {w["name"]: filled(w["way"], "a/b.x")}}) for s, w in stacks().items()}, {s: [] for s in stacks()})
    pinned = re.compile(r"(pytest==|jest-junit@|gotestsum@v|JunitXml\.TestLogger --version )\d")
    check("every stack's way writes a JUnit report, and each tool it installs is pinned",
          [s for s, w in stacks().items() if not w["way"].get("junit") or any(t in c and not pinned.search(c) for c in w["way"].get("setup") or []
                                                                               for t in ("pytest", "jest-junit", "gotestsum", "JunitXml"))], [])
    import yaml
    check("way_yaml: a way as YAML, indented", yaml.safe_load(way_yaml("pytest", py[2], 4)), {"pytest": py[2]})
    listing = json.dumps({"tree": [{"path": "pyproject.toml", "type": "blob"}, {"path": "src", "type": "tree"}]})

    def fake(*args):
        if "git/trees" in args[1]:
            return 0, listing, ""
        return 0, "[tool.pytest.ini_options]\n", ""
    check("remote_way: a repository on GitHub, from its tree", remote_way("Acme/x", "main", fake)[1], "pytest")
    check("remote_policy: a repository's own policy, {} when it has none, an error when it cannot be read",
          (remote_policy("Acme/x", "main", lambda *a: (0, "kind: x\n", "")), remote_policy("Acme/x", "main", lambda *a: (1, "", "HTTP 404"))), ({"kind": "x"}, {}))
    try:
        remote_policy("Acme/x", "main", lambda *a: (1, "", "HTTP 502"))
        check("remote_policy: one that cannot be read is no empty policy", False, True)
    except RuntimeError:
        check("remote_policy: one that cannot be read is no empty policy", True, True)
    try:
        remote_way("Acme/x", "main", lambda *a: (0, listing, "") if "git/trees" in a[1] else (1, "", "HTTP 502"))
        check("remote_way: a file it cannot read is an error, never a repository with no stack", False, True)
    except RuntimeError:
        check("remote_way: a file it cannot read is an error, never a repository with no stack", True, True)
    try:
        stack_way({f"p{i}/x.csproj" for i in range(3)}, lambda p: "", reads=2)
        check("stack_way: more files to read than it may is an error, never no stack", False, True)
    except RuntimeError:
        check("stack_way: more files to read than it may is an error, never no stack", True, True)
    check("remote_way: an empty repository proposes nothing", remote_way("Acme/x", "main", lambda *a: (1, "", "HTTP 409: Git Repository is empty.")), None)
    try:
        remote_way("Acme/x", "main", lambda *a: (1, "", "HTTP 404: Not Found"))
        check("remote_way: a tree it cannot read is an error, never a repository with no stack", False, True)
    except RuntimeError:
        check("remote_way: a tree it cannot read is an error, never a repository with no stack", True, True)
    try:
        remote_way("Acme/x", "main", lambda *a: (0, json.dumps({"tree": [{"path": "README.md", "type": "blob"}], "truncated": True}), ""))
        check("remote_way: a tree GitHub truncated is an error, never a repository with no stack", False, True)
    except RuntimeError:
        check("remote_way: a tree GitHub truncated is an error, never a repository with no stack", True, True)
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv == ["adopt-issues"]:
        return run_adopt_issues()
    if argv[:1] == ["adopt-pr"] and len(argv) == 2 and argv[1].isdigit():
        return run_adopt_pr(int(argv[1]))
    if argv[:1] == ["adopt-body"] and len(argv) == 2:
        print(adopt_body(argv[1], remote(f"{ORG}/{argv[1]}"), packs()), end="")
        return 0
    if argv[:1] == ["way"] and len(argv) in (2, 3):
        found = remote_way(argv[1] if "/" in argv[1] else f"{ORG}/{argv[1]}", argv[2] if len(argv) == 3 else "main")
        if found:
            print(f"# {found[0]}\n" + way_yaml(found[1], found[2]), end="")
        return 0
    if len(argv) == 1:
        for k in remote(f"{ORG}/{argv[0]}"):
            print(k)
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
