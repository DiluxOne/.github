#!/usr/bin/env python3
"""The manifests of a plugin for coding agents, one per tool (#552).

A plugin of the ai-agent-plugin kind is wired into several coding agents
(Claude Code, Codex, Copilot, Cursor, Gemini, OpenCode), each through a
manifest of its own. What each tool's manifest is, which fields hold the
plugin's name, version and description, and how a person installs it (from
a catalog, or by instructions) is data: kinds/ai-agent-plugin/tools.yml.
This script knows no tool by name.

  agent-manifests.py check [DIR]
                                the manifests the plugin at DIR (default .)
                                ships, one per tool it declares, agree on its
                                name, version and description; exit 1 naming
                                both files of each disagreement, a manifest
                                that is not JSON or has no name, or a plugin
                                with no manifest at all
  agent-manifests.py tools      the tools, one per line: id, manifest, install
  agent-manifests.py --test     self-test

The tools.yml it reads is the one beside this checkout of DiluxOne/.github
(TOOLS overrides it, for the self-test).
"""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CENTRAL = os.path.dirname(HERE)
KIND = "ai-agent-plugin"
TOOLS = os.environ.get("TOOLS") or os.path.join(CENTRAL, "kinds", KIND, "tools.yml")
FIELDS = ("name", "version", "description")
INSTALLS = ("catalog", "instructions")


def load_yaml(path):
    # yq on the runners, PyYAML where yq is not installed (a contributor's
    # machine), as scripts/policy.py reads its files.
    if shutil.which("yq"):
        out = subprocess.run(["yq", "-o=json", ".", path], check=True, capture_output=True, text=True).stdout
        return json.loads(out or "{}") or {}
    try:
        import yaml
    except ImportError:
        sys.exit("agent-manifests.py needs yq or PyYAML (python3 -m pip install pyyaml).")
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_tools(path=None):
    """{id: tool} from tools.yml, in the order written."""
    return (load_yaml(path or TOOLS).get("tools")) or {}


def tools_problems(tools):
    """What is wrong with tools.yml, one line each; [] when nothing is."""
    out = []
    if not isinstance(tools, dict) or not tools:
        return ["tools.yml: `tools` is a map of at least one tool"]
    catalogs = {}
    for tid, tool in tools.items():
        where = f"tools.{tid}"
        if not isinstance(tool, dict):
            out.append(f"{where}: a map")
            continue
        for key in ("name", "install", "how", "source"):
            if not tool.get(key):
                out.append(f"{where}: no `{key}`")
        if tool.get("install") not in INSTALLS:
            out.append(f"{where}: install is one of {', '.join(INSTALLS)}")
        manifest = tool.get("manifest")
        if manifest is not None:
            if not isinstance(manifest, str) or manifest.startswith("/") or ".." in manifest.split("/"):
                out.append(f"{where}: manifest is a path from the plugin's root")
            fields = tool.get("fields") or {}
            if set(fields) != set(FIELDS) or not all(isinstance(v, str) and v for v in fields.values()):
                out.append(f"{where}: fields names the keys of {', '.join(FIELDS)}")
        catalog = tool.get("catalog")
        if tool.get("install") == "catalog":
            if not isinstance(catalog, dict) or not (catalog.get("shares") or (catalog.get("path") and isinstance(catalog.get("entry"), dict))):
                out.append(f"{where}: a catalog tool has `catalog` with `path` and `entry`, or `shares`")
            elif catalog.get("path"):
                if "{repo}" not in json.dumps(catalog["entry"]):
                    out.append(f"{where}: catalog.entry points to {{repo}}")
                catalogs[tid] = catalog["path"]
            # A catalog only a tool's documentation shows: its source says where.
            if not re.match(r"https://", str(tool.get("source") or "")):
                out.append(f"{where}: a catalog tool's source is the documentation that shows it")
        elif catalog is not None:
            out.append(f"{where}: only a catalog tool has `catalog`")
    for tid, tool in tools.items():
        catalog = tool.get("catalog") if isinstance(tool, dict) else None
        shares = catalog.get("shares") if isinstance(catalog, dict) else None
        if shares and shares not in catalogs:
            out.append(f"tools.{tid}: catalog.shares names {shares}, which has no catalog file of its own")
    return out


def read_manifests(root, tools):
    """[(path, {field: value})] for every tool's manifest the plugin at `root`
    ships, in tools.yml's order; a manifest that is not a JSON object is an
    error (path, message) instead."""
    found, errors = [], []
    seen = set()
    for tool in tools.values():
        path = tool.get("manifest")
        if not path or path in seen or not os.path.isfile(os.path.join(root, path)):
            continue
        seen.add(path)
        try:
            with open(os.path.join(root, path), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            errors.append((path, f"is not valid JSON ({exc})"))
            continue
        if not isinstance(data, dict):
            errors.append((path, "is not a JSON object"))
            continue
        values = {}
        for field in FIELDS:
            value = data.get(tool["fields"][field])
            if value is not None:
                values[field] = value if isinstance(value, str) else json.dumps(value)
        found.append((path, values))
    return found, errors


def check_plugin(root, tools):
    """What is wrong with the manifests of the plugin at `root`, one line
    each: two manifests that disagree on its name, version or description
    (both files named), one with no name, one that cannot be read, or none
    at all."""
    found, errors = read_manifests(root, tools)
    out = [f"{path} {why}" for path, why in errors]
    if not found and not errors:
        names = ", ".join(t["manifest"] for t in tools.values() if t.get("manifest"))
        return [f"no manifest of any tool: a plugin of this kind ships at least one of {names}"]
    for path, values in found:
        if not values.get("name"):
            out.append(f"{path} has no name")
    for field in FIELDS:
        for i, (path_a, a) in enumerate(found):
            for path_b, b in found[i + 1:]:
                if field in a and field in b and a[field] != b[field]:
                    out.append(f"{path_a} and {path_b} disagree on the {field}: {a[field]!r} and {b[field]!r}")
    return out


def readme_lists_kind(text, kind=KIND):
    """Whether kinds/README.md's table has the kind's row, with what it is for."""
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] == f"`{kind}`" and f"{kind}/" in cells[1] and cells[2]:
            return True
    return False


def self_test():
    failed = 0

    def check(name, got, want=True):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    # C1: the pack's tools.yml holds, and kinds/README.md lists the kind.
    tools = load_tools()
    check("tools.yml: every tool is well formed", tools_problems(tools), [])
    check("tools.yml: Claude Code installs from a catalog", (tools.get("claude-code") or {}).get("install"), "catalog")
    check("tools.yml: Gemini installs by instructions", (tools.get("gemini") or {}).get("install"), "instructions")
    check("tools.yml: a tool with no catalog is refused one", tools_problems({"t": {"name": "T", "install": "catalog", "how": "h", "source": "https://x", "manifest": None}}),
          ["tools.t: a catalog tool has `catalog` with `path` and `entry`, or `shares`"])
    check("tools.yml: a catalog shared with a tool that has none is refused",
          tools_problems({"t": {"name": "T", "install": "catalog", "how": "h", "source": "https://x", "manifest": None, "catalog": {"shares": "u"}}}),
          ["tools.t: catalog.shares names u, which has no catalog file of its own"])
    check("tools.yml: a manifest outside the plugin is refused",
          tools_problems({"t": {"name": "T", "install": "instructions", "how": "h", "source": "s", "manifest": "../x.json", "fields": {"name": "n", "version": "v", "description": "d"}}}),
          ["tools.t: manifest is a path from the plugin's root"])
    with open(os.path.join(CENTRAL, "kinds", "README.md"), encoding="utf-8") as fh:
        check("kinds/README.md: its table lists the kind, with what it is for", readme_lists_kind(fh.read()))
    check("a table row with no purpose does not count", readme_lists_kind("| `ai-agent-plugin` | [`ai-agent-plugin/`](ai-agent-plugin/) |  |"), False)

    # C2: two tools' manifests that disagree fail, naming both files.
    import tempfile

    scratch = []

    def plugin(files):
        root = tempfile.mkdtemp(prefix="agent-manifests-")
        scratch.append(root)
        for path, content in files.items():
            os.makedirs(os.path.dirname(os.path.join(root, path)) or root, exist_ok=True)
            with open(os.path.join(root, path), "w", encoding="utf-8") as fh:
                fh.write(content if isinstance(content, str) else json.dumps(content))
        return root
    same = {"name": "daw", "version": "1.2.0", "description": "A pipeline."}
    cc, cx, cu, gm = ".claude-plugin/plugin.json", ".codex-plugin/plugin.json", ".cursor-plugin/plugin.json", "gemini-extension.json"
    check("C2: manifests that agree pass", check_plugin(plugin({cc: same, cx: dict(same, skills="./skills/"), gm: same}), tools), [])
    got = check_plugin(plugin({cc: same, cx: dict(same, name="ddw")}), tools)
    check("C2: Claude Code's and Codex's manifests disagree on the name: it fails, naming both files",
          got, [f"{cc} and {cx} disagree on the name: 'daw' and 'ddw'"])
    got = check_plugin(plugin({cc: same, cx: same, gm: dict(same, version="1.3.0")}), tools)
    check("C2: a version that differs in one manifest fails, naming the two files each time",
          got, [f"{cc} and {gm} disagree on the version: '1.2.0' and '1.3.0'", f"{cx} and {gm} disagree on the version: '1.2.0' and '1.3.0'"])
    got = check_plugin(plugin({cc: same, cu: dict(same, description="Another.")}), tools)
    check("C2: so does a description", got, [f"{cc} and {cu} disagree on the description: 'A pipeline.' and 'Another.'"])
    check("C2: a field one manifest leaves out is not a disagreement", check_plugin(plugin({cc: same, cu: {"name": "daw"}}), tools), [])
    check("C2: a manifest with no name fails", check_plugin(plugin({cc: {"version": "1.0.0"}}), tools), [f"{cc} has no name"])
    got = check_plugin(plugin({cc: "{ not json"}), tools)
    check("C2: a manifest that is not JSON fails, naming it", len(got) == 1 and got[0].startswith(f"{cc} is not valid JSON"))
    got = check_plugin(plugin({"README.md": "x", "package.json": {"name": "other"}}), tools)
    check("C2: a plugin with no manifest of any tool fails", len(got) == 1 and got[0].startswith("no manifest of any tool"))
    rc = main(["check", plugin({cc: same, cx: dict(same, version="9.9.9")})])
    check("C2: the command exits 1 when they disagree", rc, 1)
    rc = main(["check", plugin({cc: same})])
    check("C2: and 0 when they agree", rc, 0)

    for root in scratch:
        shutil.rmtree(root, ignore_errors=True)
    print("all tests passed" if not failed else "FAILED")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if len(argv) in (1, 2) and argv[0] == "check":
        root = argv[1] if len(argv) == 2 else "."
        problems = check_plugin(root, load_tools())
        gh = os.environ.get("GITHUB_ACTIONS") == "true"
        for line in problems:
            print(f"::error::{line}" if gh else line)
        if not problems:
            print("The manifests of every tool agree on the plugin's name, version and description.")
        return 1 if problems else 0
    if argv == ["tools"]:
        for tid, tool in load_tools().items():
            print(f"{tid}\t{tool.get('manifest') or '-'}\t{tool.get('install')}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
