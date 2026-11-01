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
  agent-manifests.py catalog [DIR] [--repos FILE] [--plugin DiluxOne/NAME=DIR ...]
                                the catalog at DIR (diluxone-plugins-ai): every
                                entry of every catalog file points to a plugin
                                of the kind (repos.yml, FILE) in the form its
                                tool reads from GitHub (`source: github`,
                                DiluxOne/<name>, for Claude Code), and every
                                plugin is listed; with a plugin's checkout,
                                in the catalog of every tool it declares
  agent-manifests.py bump VERSION DiluxOne/NAME [DIR] [--ref TAG]
                                brings that plugin's entries in the catalog at
                                DIR up to the released VERSION (and to its tag)
  agent-manifests.py publish-plan NAME VERSION ISSUES.json PRS.json
                                what the publish workflow does next, from the
                                catalog's open issues and pull requests (`gh
                                ... list --json number,title`): `done N` when
                                the pull request for NAME VERSION is open,
                                `reuse N` when only its issue is (a run that
                                failed after opening it), `create -` when
                                neither is; exit 2 when a list is not one
  agent-manifests.py version VERSION [DIR]
                                the release pull request (pack.yml `release`):
                                every manifest at VERSION, the changelog.d
                                fragments written into CHANGELOG.md
  agent-manifests.py says DIR VERSION
                                exit 1 when a manifest does not say VERSION
  agent-manifests.py notes DIR VERSION
                                CHANGELOG.md's entry for VERSION (the release's
                                notes); exit 1 when it has none
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


ORG = "DiluxOne"
REPO_NAME = r"[A-Za-z0-9._-]+"


def catalog_files(tools):
    """{tool id: catalog path} of every tool with a catalog file of its own."""
    return {tid: t["catalog"]["path"] for tid, t in tools.items()
            if t.get("install") == "catalog" and isinstance(t.get("catalog"), dict) and t["catalog"].get("path")}


def entry_repo(source, form):
    """The repository (DiluxOne/<name>, as the organisation writes it) an
    entry's `source` points to, when it has the tool's form (tools.yml
    `catalog.entry`, {repo} the repository) and nothing else but a ref or a
    sha; None otherwise: another owner, another kind of source, a path."""
    if not isinstance(source, dict) or set(source) - set(form) - {"ref", "sha"}:
        return None
    repo = None
    for key, want in form.items():
        have = source.get(key)
        if not isinstance(have, str):
            return None
        if "{repo}" not in want:
            if have != want:
                return None
            continue
        head, tail = want.split("{repo}", 1)
        m = re.fullmatch(re.escape(head) + rf"(?i:{ORG})/({REPO_NAME})" + re.escape(tail), have)
        if not m or m.group(1).endswith(".git") or m.group(1) in (".", ".."):
            return None
        repo = f"{ORG}/{m.group(1)}"
    return repo


def read_catalog(root, path):
    """The catalog file's `plugins` list, [] when it has none; raises
    ValueError when it is not a JSON object with that list."""
    with open(os.path.join(root, path), encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or not isinstance(data.get("plugins", []), list):
        raise ValueError("not a catalog: a JSON object whose `plugins` is a list")
    return data.get("plugins") or []


def declared_tools(root, tools):
    """The tools whose manifest the plugin at `root` ships."""
    return [tid for tid, t in tools.items() if t.get("manifest") and os.path.isfile(os.path.join(root, t["manifest"]))]


def catalog_problems(root, tools, plugins, checkouts=None):
    """What is wrong with the catalog at `root`, one line each. Every entry of
    every catalog file points to a plugin of the kind (`plugins`, the
    repositories repos.yml gives it, DiluxOne/<name>) in the form its tool
    reads from GitHub, never a path, another owner or another source; Claude
    Code's catalog file is there; every plugin of the kind is listed in it,
    and, for the plugins whose checkout `checkouts` gives ({repo: dir}), in
    the catalog of every tool it declares, under its manifest's name."""
    out = []
    files = catalog_files(tools)
    listed = {}
    plugins = {p.lower(): p for p in plugins}
    for tid, path in files.items():
        if not os.path.isfile(os.path.join(root, path)):
            if tid == "claude-code":
                out.append(f"{path}: missing; it is the catalog every plugin of the kind is listed in")
            continue
        try:
            entries = read_catalog(root, path)
        except (OSError, ValueError) as exc:
            out.append(f"{path}: {exc}")
            continue
        for n, entry in enumerate(entries):
            name = entry.get("name") if isinstance(entry, dict) else None
            where = f"{path}: plugins[{n}] ({name or 'no name'})"
            repo = entry_repo(entry.get("source") if isinstance(entry, dict) else None, tools[tid]["catalog"]["entry"])
            if not name:
                out.append(f"{where} has no name")
            if repo is None:
                out.append(f"{where}: its source is not {json.dumps(tools[tid]['catalog']['entry'])} for a {ORG} repository")
            elif repo.lower() not in plugins:
                out.append(f"{where}: {repo} is not a plugin of the {KIND} kind in repos.yml")
            else:
                listed.setdefault(tid, {})[plugins[repo.lower()]] = name
    for repo in plugins.values():
        if repo not in listed.get("claude-code", {}):
            out.append(f"{repo} is a plugin of the {KIND} kind and {files.get('claude-code')} does not list it")
    for repo, directory in (checkouts or {}).items():
        manifests = dict(read_manifests(directory, tools)[0])
        for tid in declared_tools(directory, tools):
            catalog = tools[tid].get("catalog") if tools[tid].get("install") == "catalog" else None
            if not isinstance(catalog, dict):
                continue
            owner = catalog.get("shares") or tid
            name = manifests.get(tools[tid]["manifest"], {}).get("name")
            if repo not in listed.get(owner, {}):
                out.append(f"{repo} declares {tools[tid]['name']} and {files[owner]} does not list it")
            elif name and listed[owner][repo] != name:
                out.append(f"{files[owner]}: {repo} is listed as {listed[owner][repo]!r}, its manifest names it {name!r}")
    return out


def bump(root, tools, repo, version, ref=None):
    """Brings every catalog entry of `repo` up to `version` (and its source to
    `ref`, the release's tag), in every catalog file at `root`; the paths
    changed. Raises ValueError when no entry points to it."""
    changed = []
    for tid, path in catalog_files(tools).items():
        full = os.path.join(root, path)
        if not os.path.isfile(full):
            continue
        with open(full, encoding="utf-8") as fh:
            data = json.load(fh)
        hit = False
        for entry in data.get("plugins") or []:
            source = entry.get("source") if isinstance(entry, dict) else None
            if (entry_repo(source, tools[tid]["catalog"]["entry"]) or "").lower() == repo.lower():
                entry["version"] = version
                if ref:
                    source["ref"] = ref
                hit = True
        if hit:
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            changed.append(path)
    if not changed:
        raise ValueError(f"no catalog entry points to {repo}")
    return changed


PUBLISH_ISSUE = "Bring {name} to {version} in the catalog"
PUBLISH_PR = "chore(catalog): {name} {version}"


def publish_plan(name, version, issues, prs):
    """What the publish workflow does next (plugin-publish-ai.yml): ("done",
    n) when the catalog's pull request for this version is open, ("reuse", n)
    when only its issue is (an earlier run failed after opening it), and
    ("create", None) when neither is. Titles are matched whole, since GitHub's
    search is fuzzy. A list that is not one (a failed read) raises
    ValueError: never taken as "none open"."""
    found = {}
    for kind, items, title in (("pr", prs, PUBLISH_PR), ("issue", issues, PUBLISH_ISSUE)):
        if not isinstance(items, list) or not all(isinstance(i, dict) and isinstance(i.get("number"), int) for i in items):
            raise ValueError(f"the open {kind}s are not a list of {{number, title}}")
        want = title.format(name=name, version=version)
        hits = sorted(i["number"] for i in items if i.get("title") == want)
        found[kind] = hits[0] if hits else None
    if found["pr"] is not None:
        return "done", found["pr"]
    if found["issue"] is not None:
        return "reuse", found["issue"]
    return "create", None


CHANGELOG = "CHANGELOG.md"
FRAGMENTS = "changelog.d"
RELEASE_HEADING = re.compile(r"^## \[?(Unreleased|v?\d+\.\d+\.\d+)\b", re.M)


def set_version(root, tools, version, day):
    """The release pull request's tree (pack.yml `release.prepare`): every
    tool's manifest at `version`, and the changelog fragments
    (changelog.d/<n>.md) written into CHANGELOG.md under `## [version] - day`,
    above the newest release, then removed. The paths changed."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"{version} is not X.Y.Z")
    changed = []
    for tool in tools.values():
        path = tool.get("manifest")
        full = os.path.join(root, path) if path else ""
        if not path or path in changed or not os.path.isfile(full):
            continue
        with open(full, encoding="utf-8") as fh:
            data = json.load(fh)
        data[tool["fields"]["version"]] = version
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        changed.append(path)
    frag_dir = os.path.join(root, FRAGMENTS)
    names = sorted((f for f in os.listdir(frag_dir) if re.fullmatch(r"\d+\.md", f)), key=lambda f: int(f[:-3])) if os.path.isdir(frag_dir) else []
    lines = []
    for f in names:
        with open(os.path.join(frag_dir, f), encoding="utf-8") as fh:
            lines += [l.rstrip() for l in fh if l.strip()]
    if lines:
        log = os.path.join(root, CHANGELOG)
        text = open(log, encoding="utf-8").read() if os.path.isfile(log) else "# Changelog\n"
        section = f"## [{version}] - {day}\n\n" + "\n".join(lines) + "\n\n"
        m = RELEASE_HEADING.search(text)
        text = text[:m.start()] + section + text[m.start():] if m else text.rstrip("\n") + "\n\n" + section.rstrip("\n") + "\n"
        with open(log, "w", encoding="utf-8") as fh:
            fh.write(text)
        for f in names:
            os.remove(os.path.join(frag_dir, f))
        changed += [CHANGELOG] + [f"{FRAGMENTS}/{f}" for f in names]
    return changed


def says(root, tools, version):
    """The manifests of the plugin at `root` that do not say `version`."""
    return [path for path, values in read_manifests(root, tools)[0] if values.get("version") != version]


def notes(root, version):
    """CHANGELOG.md's entry for `version` (the lines under `## [version]`
    up to the next `## `), or None when it has none or it is empty."""
    path = os.path.join(root, CHANGELOG)
    if not os.path.isfile(path):
        return None
    out, inside = [], False
    for line in open(path, encoding="utf-8"):
        m = RELEASE_HEADING.match(line)
        if line.startswith("## "):
            if inside:
                break
            inside = bool(m) and m.group(1).lstrip("v") == version
            continue
        if inside:
            out.append(line)
    text = "".join(out).strip()
    return text + "\n" if text else None


def kind_repos(repos_yml):
    """DiluxOne/<name> of every repository repos.yml gives this kind."""
    repos = (load_yaml(repos_yml).get("repos") or {})
    return [f"{ORG}/{name}" for name, entry in repos.items()
            if any(isinstance(k, dict) and k.get("kind") == KIND for k in (entry or {}).get("kinds") or [])]


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

    # C5: the catalog lists every plugin of the kind, each from its own repository.
    daw, mermaid = "DiluxOne/dilux-agentic-workflow", "DiluxOne/diluxone-mermaid"
    check("C5: repos.yml gives the kind DAW and diluxone-mermaid", sorted(kind_repos(os.path.join(CENTRAL, "repos.yml"))), [daw, mermaid])
    cm, xm = ".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"

    def market(*entries):
        return {"name": "diluxone-plugins-ai", "owner": {"name": "DiluxOne"}, "plugins": list(entries)}
    gh_entry = lambda name, repo: {"name": name, "source": {"source": "github", "repo": repo}}  # noqa: E731
    url_entry = lambda name, repo: {"name": name, "source": {"source": "url", "url": f"https://github.com/{repo}.git"}}  # noqa: E731
    good = {cm: market(gh_entry("daw", daw), gh_entry("diluxone-mermaid", "diluxone/diluxone-mermaid")), xm: market(url_entry("daw", daw))}
    both = [daw, mermaid]
    check("C5: a catalog with both plugins, each `source: github` from its own DiluxOne repository, passes", catalog_problems(plugin(good), tools, both), [])
    got = catalog_problems(plugin({cm: market(gh_entry("daw", daw))}), tools, both)
    check("C5: a plugin of the kind the catalog leaves out fails", got, [f"{mermaid} is a plugin of the ai-agent-plugin kind and {cm} does not list it"])
    got = catalog_problems(plugin({cm: market(gh_entry("daw", daw), gh_entry("diluxone-mermaid", mermaid), gh_entry("evil", "someone/diluxone-mermaid"))}), tools, both)
    check("C5: an entry from another owner fails (spoofing)", len(got) == 1 and "plugins[2] (evil)" in got[0] and "for a DiluxOne repository" in got[0])
    for label, source in (("a path", "./"), ("a git URL in Claude Code's", {"source": "url", "url": f"https://github.com/{daw}.git"}),
                          ("an npm package", {"source": "npm", "package": "daw"}), ("a field more", {"source": "github", "repo": daw, "path": "x"})):
        got = catalog_problems(plugin({cm: market({"name": "daw", "source": source}, gh_entry("m", mermaid))}), tools, both)
        check(f"C5: an entry whose source is {label} fails", any("plugins[0] (daw): its source is not" in g for g in got))
    got = catalog_problems(plugin({cm: market(gh_entry("daw", daw), gh_entry("m", mermaid), gh_entry("x", "DiluxOne/diluxone-users-wordpress"))}), tools, both)
    check("C5: a DiluxOne repository that is not a plugin of the kind fails", got, [f"{cm}: plugins[2] (x): DiluxOne/diluxone-users-wordpress is not a plugin of the ai-agent-plugin kind in repos.yml"])
    check("C5: a catalog with no Claude Code file fails", catalog_problems(plugin({xm: market(url_entry("daw", daw))}), tools, [daw])[0].startswith(f"{cm}: missing"))
    daw_tree = plugin({cc: same, cx: same})
    got = catalog_problems(plugin({cm: market(gh_entry("daw", daw), gh_entry("m", mermaid))}), tools, both, {daw: daw_tree})
    check("C5: with its checkout, a plugin missing from the catalog of a tool it declares fails", got, [f"{daw} declares Codex and {xm} does not list it"])
    got = catalog_problems(plugin({cm: market(gh_entry("ddw", daw), gh_entry("m", mermaid)), xm: market(url_entry("daw", daw))}), tools, both, {daw: daw_tree})
    check("C5: and one listed under another name than its manifest's", got, [f"{cm}: {daw} is listed as 'ddw', its manifest names it 'daw'"])
    rc = main(["catalog", plugin(good), "--plugin", f"{daw}={daw_tree}"])
    check("C5: the command exits 0 for the good catalog", rc, 0)
    # The release brings the plugin's entries up to its version (option C1).
    root = plugin(good)
    check("C5: bump changes every catalog file that lists the plugin", bump(root, tools, daw, "1.3.0", "1.3.0"), [cm, xm])
    after = json.load(open(os.path.join(root, cm)))["plugins"]
    check("C5: its entry is at the version and the tag, the others untouched",
          (after[0]["version"], after[0]["source"]["ref"], "version" in after[1]), ("1.3.0", "1.3.0", False))
    check("C5: the catalog still passes after a bump", catalog_problems(root, tools, both), [])
    try:
        bump(root, tools, "DiluxOne/nothing-here", "1.0.0")
        check("C5: bump fails for a plugin the catalog does not list", False)
    except ValueError:
        check("C5: bump fails for a plugin the catalog does not list", True)
    # The publish workflow is safe to re-run: it never opens a second issue or
    # pull request, and a failed read of either list stops it.
    issue = {"number": 7, "title": "Bring daw to 1.3.0 in the catalog"}
    pr = {"number": 8, "title": "chore(catalog): daw 1.3.0"}
    check("publish: nothing open, it creates the issue", publish_plan("daw", "1.3.0", [], []), ("create", None))
    check("publish: the issue open with no pull request (a failed push or pull request), it reuses the issue",
          publish_plan("daw", "1.3.0", [issue], []), ("reuse", 7))
    check("publish: the pull request open, it stops", publish_plan("daw", "1.3.0", [issue], [pr]), ("done", 8))
    check("publish: the pull request open without its issue, it still stops", publish_plan("daw", "1.3.0", [], [pr]), ("done", 8))
    check("publish: another version's or plugin's issue is not this one",
          publish_plan("daw", "1.3.0", [{"number": 5, "title": "Bring daw to 1.3.01 in the catalog"}, {"number": 6, "title": "Bring dawx to 1.3.0 in the catalog"}], []),
          ("create", None))
    check("publish: two issues open, the oldest is reused", publish_plan("daw", "1.3.0", [dict(issue, number=9), issue], []), ("reuse", 7))
    for label, bad in (("nothing (a failed read)", None), ("an error object", {"message": "API rate limit exceeded"}), ("entries with no number", [{"title": "x"}])):
        try:
            publish_plan("daw", "1.3.0", bad, [])
            check(f"publish: issues that are {label} stop it", "went on", "stopped")
        except ValueError:
            check(f"publish: issues that are {label} stop it", "stopped", "stopped")
    plans = plugin({"i.json": [issue], "p.json": [], "empty.json": ""})
    check("publish: the command says `reuse N`, and exits 2 on a list that is not JSON",
          (main(["publish-plan", "daw", "1.3.0", os.path.join(plans, "i.json"), os.path.join(plans, "p.json")]),
           main(["publish-plan", "daw", "1.3.0", os.path.join(plans, "empty.json"), os.path.join(plans, "p.json")])), (0, 2))

    # The release pull request (pack.yml `release.prepare`).
    tree = plugin({cc: same, gm: same, "CHANGELOG.md": "# Changelog\n\nIntro.\n\n## [1.2.0] - 2026-10-01\n\n* Old.\n",
                   "changelog.d/12.md": "* Second.\n", "changelog.d/9.md": "* First.\n"})
    got = set_version(tree, tools, "1.3.0", "2026-11-01")
    log = open(os.path.join(tree, "CHANGELOG.md")).read()
    check("version: every manifest at the version, the fragments in the changelog by number, then removed",
          (got, check_plugin(tree, tools), json.load(open(os.path.join(tree, gm)))["version"], log, os.listdir(os.path.join(tree, "changelog.d"))),
          ([cc, gm, "CHANGELOG.md", "changelog.d/9.md", "changelog.d/12.md"], [], "1.3.0",
           "# Changelog\n\nIntro.\n\n## [1.3.0] - 2026-11-01\n\n* First.\n* Second.\n\n## [1.2.0] - 2026-10-01\n\n* Old.\n", []))

    check("release: the manifests say the version it prepared", (says(tree, tools, "1.3.0"), says(tree, tools, "1.2.0")), ([], [cc, gm]))
    check("release: its notes are the changelog's entry, and none for a version it lacks",
          (notes(tree, "1.3.0"), notes(tree, "1.2.0"), notes(tree, "9.9.9")), ("* First.\n* Second.\n", "* Old.\n", None))

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
    if argv and argv[0] == "catalog":
        # catalog [DIR] [--repos repos.yml] [--plugin DiluxOne/<name>=DIR ...]
        args, root, repos_yml, checkouts = argv[1:], ".", os.path.join(CENTRAL, "repos.yml"), {}
        while args:
            a = args.pop(0)
            if a == "--repos" and args:
                repos_yml = args.pop(0)
            elif a == "--plugin" and args and "=" in args[0]:
                repo, directory = args.pop(0).split("=", 1)
                checkouts[repo] = directory
            elif not a.startswith("-"):
                root = a
            else:
                print(__doc__, file=sys.stderr)
                return 2
        problems = catalog_problems(root, load_tools(), kind_repos(repos_yml), checkouts)
        for line in problems:
            print(f"::error::{line}" if os.environ.get("GITHUB_ACTIONS") == "true" else line)
        if not problems:
            print("The catalog lists every plugin of the kind, each from its own repository.")
        return 1 if problems else 0
    if len(argv) >= 3 and argv[0] == "bump":
        # bump VERSION DiluxOne/<name> [DIR] [--ref TAG]
        args = argv[1:]
        ref = None
        if "--ref" in args:
            i = args.index("--ref")
            ref = args[i + 1] if i + 1 < len(args) else None
            del args[i:i + 2]
        version, repo, root = args[0], args[1], args[2] if len(args) > 2 else "."
        if not re.fullmatch(r"\d+\.\d+\.\d+", version) or not re.fullmatch(rf"{ORG}/{REPO_NAME}", repo, re.I):
            print(f"bump: {version} is not X.Y.Z, or {repo} is not {ORG}/<name>", file=sys.stderr)
            return 2
        try:
            changed = bump(root, load_tools(), repo, version, ref)
        except ValueError as exc:
            print(f"bump: {exc}", file=sys.stderr)
            return 1
        print("\n".join(changed))
        return 0
    if len(argv) == 5 and argv[0] == "publish-plan":
        try:
            lists = []
            for path in argv[3:]:
                with open(path, encoding="utf-8") as fh:
                    lists.append(json.load(fh))
            action, number = publish_plan(argv[1], argv[2], *lists)
        except (OSError, ValueError) as exc:
            print(f"publish-plan: {exc}", file=sys.stderr)
            return 2
        print(f"{action} {number if number is not None else '-'}")
        return 0
    if len(argv) in (2, 3) and argv[0] == "version":
        # version VERSION [DIR]: the release pull request's tree.
        import datetime
        try:
            changed = set_version(argv[2] if len(argv) == 3 else ".", load_tools(), argv[1], datetime.date.today().isoformat())
        except ValueError as exc:
            print(f"version: {exc}", file=sys.stderr)
            return 2
        print("\n".join(changed))
        return 0
    if len(argv) == 3 and argv[0] == "says":
        off = says(argv[1], load_tools(), argv[2])
        for path in off:
            print(f"{path} does not say {argv[2]}", file=sys.stderr)
        return 1 if off else 0
    if len(argv) == 3 and argv[0] == "notes":
        text = notes(argv[1], argv[2])
        if text is None:
            print(f"{CHANGELOG} has no entry for {argv[2]} (`## [{argv[2]}] - <date>`), or it is empty.", file=sys.stderr)
            return 1
        sys.stdout.write(text)
        return 0
    if argv == ["tools"]:
        for tid, tool in load_tools().items():
            print(f"{tid}\t{tool.get('manifest') or '-'}\t{tool.get('install')}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
