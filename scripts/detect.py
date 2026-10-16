#!/usr/bin/env python3
"""What kind of project a repository looks like (#191).

Each pack says how to recognise its kind (kinds/<kind>/pack.yml, `detect`):
files that must be at the repository's root, and a root file whose first
lines match a pattern (a plugin's header). Detection only proposes: what a
repository is lives in repos.yml `repos:`, and a person merges that. The
daily drift check (scripts/sync-repos.py check) says, for a repository
repos.yml does not list, what detection proposes for it.

  detect.py NAME     the kinds repository NAME looks like, one per line
  detect.py --test   self-test

Environment: GH_TOKEN (contents: read).
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


def remote(full, default="main"):
    """The kinds a repository on GitHub looks like."""
    listing = subprocess.run(["gh", "api", f"repos/{full}/contents/?ref={default}", "--jq", "[.[] | select(.type == \"file\") | .name]"],
                             capture_output=True, text=True)
    if listing.returncode != 0:
        if "404" in listing.stderr:  # empty: nothing to recognise
            return []
        raise RuntimeError(f"could not list its root: {listing.stderr.strip()[:200]}")
    names = set(json.loads(listing.stdout or "[]"))

    def head(name):
        out = subprocess.run(["gh", "api", f"repos/{full}/contents/{name}?ref={default}", "-H", "Accept: application/vnd.github.raw"],
                             capture_output=True)
        return out.stdout[:HEAD_BYTES].decode("utf-8", "replace") if out.returncode == 0 else ""
    return kinds(names, head)


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
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if len(argv) == 1:
        for k in remote(f"{ORG}/{argv[0]}"):
            print(k)
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
