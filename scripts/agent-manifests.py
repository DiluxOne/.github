#!/usr/bin/env python3
"""The manifests of a plugin for coding agents, one per tool (#552).

A plugin of the ai-agent-plugin kind is wired into several coding agents
(Claude Code, Codex, Copilot, Cursor, Gemini, OpenCode), each through a
manifest of its own. What each tool's manifest is, which fields hold the
plugin's name, version and description, and how a person installs it (from
a catalog, or by instructions) is data: kinds/ai-agent-plugin/tools.yml.
This script knows no tool by name.

  agent-manifests.py tools      the tools, one per line: id, manifest, install
  agent-manifests.py --test     self-test

The tools.yml it reads is the one beside this checkout of DiluxOne/.github
(TOOLS overrides it, for the self-test).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CENTRAL = os.path.dirname(HERE)
KIND = "ai-agent-plugin"
TOOLS = os.environ.get("TOOLS") or os.path.join(CENTRAL, "kinds", KIND, "tools.yml")
FIELDS = ("name", "version", "description")
INSTALLS = ("catalog", "instructions")


def load_yaml(path):
    try:
        import yaml
    except ImportError:
        sys.exit("agent-manifests.py needs PyYAML (python3 -m pip install pyyaml).")
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

    print("all tests passed" if not failed else "FAILED")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv == ["tools"]:
        for tid, tool in load_tools().items():
            print(f"{tid}\t{tool.get('manifest') or '-'}\t{tool.get('install')}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
