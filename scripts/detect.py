#!/usr/bin/env python3
"""What kind of project a repository looks like (#191).

Each pack says how to recognise its kind (kinds/<kind>/pack.yml, `detect`):
files that must be at the repository's root, and a root file whose first
lines match a pattern (a plugin's header). Detection only proposes: what a
repository is lives in repos.yml `repos:`, and a person merges that. The
daily drift check (scripts/sync-repos.py check) says, for a repository
repos.yml does not list, what detection proposes for it.

  detect.py NAME     the kinds repository NAME looks like, one per line
  detect.py propose  for the repositories repos.yml does not list, an issue
                     and a pull request adding each, with what detection
                     recognises (org-drift.yml, every day): a `platform`
                     lane issue, opened by dilux-bot from the run; repos.yml
                     is high risk, so a person merges the pull request
  detect.py --test   self-test

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
ORG = "DiluxOne"
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


def matches(rule, names, head):
    """Whether a repository's root (its file names, and `head(name)`, the
    first bytes of a file) meets a pack's `detect`."""
    if not all(f in names for f in rule.get("files") or []):
        return False
    header = rule.get("header")
    if header:
        pattern = re.compile(header["pattern"])
        return any(pattern.search(head(n) or "") for n in sorted(names) if fnmatch.fnmatch(n, header["glob"]))
    return True


def kinds(names, head, rules=None):
    """The kinds a repository's root looks like."""
    rules = packs() if rules is None else rules
    return [k for k, rule in rules.items() if matches(rule, names, head)]


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
    return kinds(names, head)


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
    end = start + 1
    while end < len(out) and (out[end].startswith("  ") or out[end].strip() == "" and end + 1 < len(out) and out[end + 1].startswith("  ")):
        end += 1
    block = [l for l in out[start + 1:end] if l.strip()] + lines
    block.sort(key=lambda l: l.strip().split(":", 1)[0].lower())
    return "\n".join(out[:start + 1] + block + out[end:])


def propose(central, conf, repos, found_of, run_url, io):
    """The proposal for every repository repos.yml lacks: (issue, pull
    request), or None when nothing is new or one is already open."""
    new = sorted(r for r in repos if r not in (conf.get("repos") or {}))
    if not new:
        print("Every repository is in repos.yml.")
        return None
    if io["open_issue"](TITLE):
        print(f"A proposal is already open: {TITLE}.")
        return None
    rules = packs()
    lines = [entry(n, found_of(n), rules) for n in new]
    body = ("The organisation has repositories that repos.yml does not list, so nothing says what they are. "
            "Detection (scripts/detect.py) read each one's root and proposes:\n\n" + "\n".join(f"- `{l.strip()}`" for l in lines) +
            "\n\nCorrect the kinds, paths and roles in the pull request if they are wrong; an empty list leaves a repository unclassified. "
            "This is work of the `platform` lane (policy/autonomy.yml): accepted by policy. repos.yml is high risk, so a person merges it."
            f"\n\n<!-- dx-lane: platform run: {run_url} -->\n\n🤖 AI-generated · scripts/detect.py")
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
        found = json.loads(gh("issue", "list", "--repo", central, "--state", "open", "--search", f"in:title \"{title}\"", "--json", "title"))
        return any(i["title"] == title for i in found)

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
        g = lambda *a: subprocess.run(["git", "-C", root, "-c", "user.name=dilux-bot[bot]", "-c", "user.email=dilux-bot[bot]@users.noreply.github.com", *a],
                                      check=True, capture_output=True, text=True)
        g("checkout", "-q", "-b", branch)
        with open(os.path.join(root, "repos.yml"), "w", encoding="utf-8") as fh:
            fh.write(text)
        g("commit", "-q", "-am", title)
        # Through the API, so GitHub signs the commit (#190).
        subprocess.run([sys.executable, os.path.join(HERE, "api-commit.py"), "push", branch, "--onto", "HEAD~1"], check=True, cwd=root)
        body = (f"## What changes\n\n`repos.yml` lists {', '.join(new)}, with what detection recognises in each.\n\n"
                f"## Why\n\nNothing said what they are: until repos.yml does, they get the triage and the basic checks, and nothing merges on its own there.\n\n"
                f"Closes #{n}\n\n🤖 AI-generated · scripts/detect.py")
        return gh("pr", "create", "--repo", central, "--head", branch, "--title", title, "--body", body).strip()

    io = {"open_issue": open_issue, "issue": issue, "read": read, "pull": pull}
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
    calls = []
    io = {"open_issue": lambda t: False, "read": lambda p: conf_text,
          "issue": lambda t, b: calls.append(("issue", t, b)) or 41,
          "pull": lambda n, text, title, new: calls.append(("pull", n, title, new)) or 42}
    got = propose("DiluxOne/.github", yaml.safe_load(conf_text), ["a-repo", "z-repo", "new-one"], lambda n: ["wordpress-plugin"], "https://github.com/DiluxOne/.github/actions/runs/9", io)
    check("propose: an issue and a pull request for what is new", (got, [c[0] for c in calls]), ((41, 42), ["issue", "pull"]))
    check("propose: the issue is the platform lane's, naming the run", "<!-- dx-lane: platform run: https://github.com/DiluxOne/.github/actions/runs/9 -->" in calls[0][2], True)
    check("propose: the pull request's title names them", calls[1][2], "chore(repos): add new-one to repos.yml")
    calls.clear()
    check("propose: nothing when every repository is listed", propose("x", yaml.safe_load(conf_text), ["a-repo"], lambda n: [], "u", io), None)
    check("propose: nothing while a proposal is open", propose("x", yaml.safe_load(conf_text), ["new"], lambda n: [], "u", dict(io, open_issue=lambda t: True)), None)
    check("propose: nothing opened in either case", calls, [])
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv == ["propose"]:
        return run_propose()
    if len(argv) == 1:
        for k in remote(f"{ORG}/{argv[0]}"):
            print(k)
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
