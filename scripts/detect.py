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
  detect.py propose  for the repositories repos.yml does not list, an issue
                     and a pull request adding each, with what detection
                     recognises (org-drift.yml, every day): a `platform`
                     lane issue, opened by dilux-bot from the run; repos.yml
                     is high risk, so a person merges the pull request
  detect.py --test   self-test

A stack is not a kind: a repository of any kind, or of none, is written in
a language whose tests run one way. policy/repro-stacks.yml says how to
recognise each (its files: a pattern with ** anywhere in the tree, any
other at the root) and the way to reproduce a
bug it proposes (scripts/repro-ways.py), for a repository that declares
none: the installer adds it to repos.yml `repro:`, and the organisation's
audit (scripts/sync-repos.py check) and the autopilot name it.

Environment: GH_TOKEN (contents: read; for propose, contents, issues and
pull requests: write on DiluxOne/.github), and for propose RUN_URL, this
workflow run's URL, which the lane checks.
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


TITLE = "New repositories for repos.yml"


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


def propose(central, conf, repos, found_of, run_url, io):
    """The proposal for every repository repos.yml lacks: (issue, pull
    request), or None when nothing is new or one is already open."""
    new = sorted(r for r in repos if r not in (conf.get("repos") or {}))
    if not new:
        print("Every repository is in repos.yml.")
        return None
    issue = io["open_issue"](TITLE)
    if issue and io["has_pull"](issue):
        print(f"A proposal is already open: #{issue}.")
        return None
    rules = packs()
    lines, unread = [], []
    for n in new:
        # One repository that cannot be read is proposed unclassified, and said.
        try:
            found = found_of(n)
        except RuntimeError as exc:
            print(f"  {n}: detection failed ({str(exc)[:120]}); proposed unclassified")
            found, unread = [], unread + [n]
        lines.append(entry(n, found, rules))
    body = ("The organisation has repositories that repos.yml does not list, so nothing says what they are. "
            "Detection (scripts/detect.py) read each one's root and proposes:\n\n" + "\n".join(f"- `{l.strip()}`" for l in lines) +
            (f"\n\nDetection could not read {', '.join(unread)}: proposed unclassified." if unread else "") +
            "\n\nCorrect the kinds, paths and roles in the pull request if they are wrong; an empty list leaves a repository unclassified. "
            "This is work of the `platform` lane (policy/autonomy.yml): accepted by policy. repos.yml is high risk, so a person merges it."
            f"\n\n<!-- dx-lane: platform run: {run_url} -->\n\n🤖 AI-generated · scripts/detect.py")
    # A run that opened the issue and failed before its pull request: the
    # issue is reused, never left to block the next run.
    if issue:
        io["edit"](issue, body)  # what this run proposes, not an earlier one
    else:
        issue = io["issue"](TITLE, body)
    text = with_entries(io["read"]("repos.yml"), lines)
    pr = io["pull"](issue, text, f"chore(repos): add {', '.join(new)} to repos.yml"[:72], new)
    return issue, pr


def run_propose():
    """propose, against GitHub, from a checkout of DiluxOne/.github's main."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("sync_repos", os.path.join(HERE, "sync-repos.py"))
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    central = os.environ.get("GITHUB_REPOSITORY", f"{ORG}/.github")
    root = os.path.join(HERE, "..")
    conf = load(os.path.join(root, "repos.yml"))
    rows = sync.repositories([], conf.get("exclude") or [])
    defaults = {r["name"]: (r.get("defaultBranchRef") or {}).get("name") or "main" for r in rows}

    def open_issue(title):
        found = json.loads(gh("issue", "list", "--repo", central, "--state", "open", "--search", f"in:title \"{title}\"", "--json", "title,number"))
        return next((str(i["number"]) for i in found if i["title"] == title), None)

    def has_pull(n):
        return bool(json.loads(gh("pr", "list", "--repo", central, "--state", "open", "--head", f"chore/{n}-new-repositories", "--json", "number")))

    def issue(title, body):
        url = gh("issue", "create", "--repo", central, "--title", title, "--label", "lane:platform,accepted-by:policy", "--body", body).strip()
        n = url.rsplit("/", 1)[-1]
        subprocess.run(["gh", "api", "-X", "PATCH", f"repos/{central}/issues/{n}", "-f", "type=Task"], capture_output=True)
        return n

    def read(path):
        with open(os.path.join(root, path), encoding="utf-8") as fh:
            return fh.read()

    def pull(n, text, title, new):
        branch = f"chore/{n}-new-repositories"
        g = lambda *a: subprocess.run(["git", "-C", root, "-c", f"user.name={org.BOT}", "-c", f"user.email={org.BOT_ID}+{org.BOT}@users.noreply.github.com", *a],
                                      check=True, capture_output=True, text=True)
        g("checkout", "-q", "-b", branch)
        with open(os.path.join(root, "repos.yml"), "w", encoding="utf-8") as fh:
            fh.write(text)
        g("commit", "-q", "-am", title)
        # Through the API, so GitHub signs the commit (#190); the branch is
        # this proposal's alone, so a run that left it is rewritten.
        subprocess.run([sys.executable, os.path.join(HERE, "api-commit.py"), "push", branch, "--onto", "HEAD~1", "--force"], check=True, cwd=root)
        body = (f"## What changes\n\n`repos.yml` lists {', '.join(new)}, with what detection recognises in each.\n\n"
                f"## Why\n\nNothing said what they are: until repos.yml does, they get the triage and the basic checks, and nothing merges on its own there.\n\n"
                f"Closes #{n}\n\n🤖 AI-generated · scripts/detect.py")
        return gh("pr", "create", "--repo", central, "--head", branch, "--title", title, "--body", body).strip()

    def edit(n, body):
        gh("issue", "edit", n, "--repo", central, "--body", body)

    io = {"open_issue": open_issue, "has_pull": has_pull, "issue": issue, "edit": edit, "read": read, "pull": pull}
    got = propose(central, conf, list(defaults), lambda name: remote(f"{ORG}/{name}", defaults[name]), os.environ.get("RUN_URL", ""), io)
    if got:
        print(f"Proposed in #{got[0]}: {got[1]}")
    return 0


def self_test():
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
    calls = []
    io = {"open_issue": lambda t: None, "has_pull": lambda n: False, "read": lambda p: conf_text,
          "edit": lambda n, b: calls.append(("edit", n, b)),
          "issue": lambda t, b: calls.append(("issue", t, b)) or 41,
          "pull": lambda n, text, title, new: calls.append(("pull", n, title, new)) or 42}
    got = propose("DiluxOne/.github", yaml.safe_load(conf_text), ["a-repo", "z-repo", "new-one"], lambda n: ["wordpress-plugin"], "https://github.com/DiluxOne/.github/actions/runs/9", io)
    check("propose: an issue and a pull request for what is new", (got, [c[0] for c in calls]), ((41, 42), ["issue", "pull"]))
    check("propose: the issue is the platform lane's, naming the run", "<!-- dx-lane: platform run: https://github.com/DiluxOne/.github/actions/runs/9 -->" in calls[0][2], True)
    check("propose: the pull request's title names them", calls[1][2], "chore(repos): add new-one to repos.yml")
    calls.clear()
    check("propose: nothing when every repository is listed", propose("x", yaml.safe_load(conf_text), ["a-repo"], lambda n: [], "u", io), None)
    check("propose: nothing while a proposal is open", propose("x", yaml.safe_load(conf_text), ["new"], lambda n: [], "u", dict(io, open_issue=lambda t: 7, has_pull=lambda n: True)), None)
    check("propose: nothing opened in either case", calls, [])
    got = propose("x", yaml.safe_load(conf_text), ["new"], lambda n: [], "u", dict(io, open_issue=lambda t: 7))
    check("propose: an issue left without its pull request gets it, with this run's text, no second issue", (got, [c[0] for c in calls]), ((7, 42), ["edit", "pull"]))
    calls.clear()

    def broken(n):
        raise RuntimeError("HTTP 502")
    propose("x", yaml.safe_load(conf_text), ["new"], broken, "u", io)
    check("propose: a repository that cannot be read is proposed unclassified, and named", ("new: {kinds: []}" in calls[0][2], "Detection could not read new" in calls[0][2]), (True, True))

    # #377: a repository's stack, and the way to reproduce a bug it proposes.
    import importlib.util
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
    if argv == ["propose"]:
        return run_propose()
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
