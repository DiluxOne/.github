#!/usr/bin/env python3
"""Every setting the engine applies, from policy/settings-schema.yml (#568).

  settings.py overlay ENGINE_FILE ORG_FILE [--as PATH]
                       print ENGINE_FILE with the organisation's ORG_FILE laid
                       over it, by the schema's rules: a mapping merges key by
                       key, a value replaces, a list replaces unless the
                       schema marks it `add-only` (the engine's entries first,
                       then the organisation's new ones) or `by: name` (merged
                       by each entry's name), and a key marked `identity` is
                       never kept from the engine's. PATH is the file's path
                       in the engine (policy/autonomy.yml), else ENGINE_FILE's
  settings.py org-free [ROOT]
                       search the engine's packs, workflows, workflow
                       templates, scripts, review profiles and policy/ for
                       the organisation's own values (org.yml and
                       repos.yml: its App's slug, login and id, its
                       security repository, maintainers and catalogs, and
                       every repository but `.github`, the engine); exit 1,
                       listing each, when one is found. Comments, each
                       script's self-test, tests/ and scripts/fixtures/ are
                       not searched
  settings.py check [ROOT]
                       exit 1, with the reasons, when a key of the engine's
                       default files (org.yml, policy/autonomy.yml,
                       policy/review-policy.default.yml, kinds/*/pack.yml)
                       is not in the schema, when a setting is not found in
                       the scripts its `read-by` names, when an entry lacks
                       what it must say, or when docs/configuration.md is
                       not what `docs` writes
  settings.py docs [ROOT]
                       print docs/configuration.md, the reference of every
                       setting, from the schema and the engine's files
  settings.py explain FILE KEY [--org ORG_FILE] [--repo REPO_FILE]
                       print, for the setting KEY of FILE (policy/autonomy.yml
                       lanes.bugfix-reproduced.accept), the value in force and
                       the level it comes from: the engine's file, the
                       organisation's ORG_FILE over it, a repository's
                       REPO_FILE over that (the autonomy policy as
                       autonomy.py merges it)
  settings.py --test   self-test

Environment: DX_SETTINGS_SCHEMA, the schema to read (default:
policy/settings-schema.yml beside this script's directory; the engine's
own, never an organisation's).
"""
import ast
import copy
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
SCHEMA = os.path.join(ROOT, "policy", "settings-schema.yml")
# The most a configuration file may weigh: an alias bomb stops here.
MAX_BYTES = 1 << 20


def load(path):
    """A YAML file as data, with PyYAML where it is or yq; {} when missing."""
    if not path or not os.path.exists(path):
        return {}
    if os.path.getsize(path) > MAX_BYTES:
        raise ValueError(f"{path}: larger than {MAX_BYTES} bytes")
    try:
        import yaml
    except ImportError:
        yaml = None
    if yaml is not None:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    if shutil.which("yq"):
        out = subprocess.run(["yq", "-o=json", ".", path], check=True, capture_output=True, text=True).stdout
        return json.loads(out or "null")
    sys.exit(f"settings.py needs PyYAML or yq to read {path}")


def dump(data):
    """Data as YAML text, with PyYAML where it is or yq."""
    try:
        import yaml
    except ImportError:
        yaml = None
    if yaml is not None:
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000, default_flow_style=False)
    out = subprocess.run(["yq", "-P", "-o=yaml", ".", "-"], input=json.dumps(data), check=True, capture_output=True, text=True)
    return out.stdout


def schema(path=None):
    return load(path or os.environ.get("DX_SETTINGS_SCHEMA") or SCHEMA) or {}


def entries(conf, rel):
    """The schema's settings of the file REL (policy/autonomy.yml)."""
    out = []
    for pattern, settings in ((conf or {}).get("files") or {}).items():
        if fnmatch.fnmatchcase(rel, pattern):
            out.extend(settings or [])
    return out


def key_matches(key, path):
    """Whether a schema key (a.*.b, or `.` for the whole file) is PATH."""
    if key == ".":
        return not path
    parts = key.split(".")
    return len(parts) == len(path) and all(p == "*" or p == str(q) for p, q in zip(parts, path))


def rule(settings, path):
    for s in settings:
        if key_matches(str(s.get("key", "")), path):
            return s
    return {}


def merge(engine, theirs, settings, path=()):
    """THEIRS laid over ENGINE by the settings' rules. Pure."""
    r = rule(settings, list(path))
    if r.get("identity"):
        return copy.deepcopy(theirs)
    if isinstance(engine, dict) and isinstance(theirs, dict):
        out = copy.deepcopy(engine)
        for key, value in theirs.items():
            out[key] = merge(engine[key], value, settings, (*path, key)) if key in engine else copy.deepcopy(value)
        if not path:
            for s in settings:
                key = str(s.get("key", ""))
                if s.get("identity") and "." not in key and key in out and key not in theirs:
                    del out[key]
        return out
    if isinstance(engine, list) and isinstance(theirs, list):
        if r.get("merge") == "add-only":
            return copy.deepcopy(engine) + [copy.deepcopy(v) for v in theirs if v not in engine]
        by = r.get("by")
        if by and all(isinstance(v, dict) for v in engine + theirs):
            out = copy.deepcopy(engine)
            index = {v.get(by): n for n, v in enumerate(out)}
            for v in theirs:
                if v.get(by) in index:
                    out[index[v[by]]] = {**out[index[v[by]]], **copy.deepcopy(v)}
                else:
                    index[v.get(by)] = len(out)
                    out.append(copy.deepcopy(v))
            return out
    if r.get("merge") == "add-only" and isinstance(engine, list):
        raise ValueError(f"{'.'.join(map(str, path))}: a list, which an organisation only adds to")
    return copy.deepcopy(theirs)


def overlay(engine_file, org_file, rel=None, conf=None):
    rel = rel or os.path.relpath(os.path.abspath(engine_file), ROOT)
    engine, theirs = load(engine_file), load(org_file)
    # An empty file of the organisation's sets nothing.
    return engine if theirs is None else merge(engine, theirs, entries(conf if conf is not None else schema(), rel))


# Where the engine's code and data are (#568 C3): none of it may name the
# organisation that runs it. The organisation's own files (org.yml,
# repos.yml, labels.yml), the docs and the tests are not searched.
SEARCHED = ("kinds", ".github/workflows", "workflow-templates", "scripts", "review-profiles", "policy")
NOT_SEARCHED = ("scripts/fixtures/",)


def identity_values(root):
    """The organisation's own values, from its org.yml and repos.yml."""
    conf = load(os.path.join(root, "org.yml")) or {}
    repos = load(os.path.join(root, "repos.yml")) or {}
    bot = conf.get("bot") or {}
    out = set()
    if bot.get("app"):
        out |= {str(bot["app"]), f"{bot['app']}[bot]"}
    if bot.get("id"):
        out.add(str(bot["id"]))
    security = str(conf.get("security") or "")
    if security:
        out.add(security)
    out |= {str(m) for m in conf.get("maintainers") or []}
    out |= {str(c) for c in (conf.get("catalogs") or {}).values()}
    # A repository by its name; the security one by its full name, since
    # its name alone may be a word ("security").
    names = set((repos.get("repos") or {})) | set(repos.get("no-workflows") or []) | set(repos.get("exclude") or [])
    out |= {str(n) for n in names if n != ".github" and f"{conf.get('org')}/{n}" != security}
    return sorted(v for v in out if v)


def skipped_lines(path, text):
    """The lines of a file that are not searched: its comments, its
    docstrings and its self-test (a Python function named self_test,
    test... or ..._test, found with ast; a shell function whose name has
    `test` in it, or an `if` on `--test` at the top level)."""
    lines = text.split("\n")
    skip = set()
    for n, line in enumerate(lines, 1):
        code = line.strip()
        if code.startswith("#") or code.startswith("//") or (path.endswith(".php") and code.startswith("*")):
            skip.add(n)
    if path.endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return skip
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and re.fullmatch(r"self_test|test\w*|\w*_tests?", node.name) and node in tree.body:
                skip |= set(range(node.lineno, node.end_lineno + 1))
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) and isinstance(first.value.value, str):
                    skip |= set(range(first.lineno, first.end_lineno + 1))
    elif path.endswith(".sh"):
        n = 0
        while n < len(lines):
            end = None
            if re.match(r"^[A-Za-z_]*test[A-Za-z_]*\(\)\s*\{", lines[n]):
                end = "}"
            elif re.match(r"^if .*--test", lines[n]):
                end = "fi"
            if end:
                m = n
                while m < len(lines) and not re.match(rf"^{re.escape(end)}(?![\w-])", lines[m]):
                    m += 1
                skip |= set(range(n + 1, m + 2))
                n = m
            n += 1
    return skip


def org_free(root=ROOT, values=None):
    """Where the engine names the organisation: ["path:line: value"]."""
    values = identity_values(root) if values is None else values
    if not values:
        return []
    pattern = re.compile(r"(?<![\w-])(" + "|".join(re.escape(v) for v in sorted(values, key=len, reverse=True)) + r")(?![\w-])")
    found = []
    for top in SEARCHED:
        for base, dirs, files in os.walk(os.path.join(root, top)):
            dirs.sort()
            for name in sorted(files):
                path = os.path.join(base, name)
                rel = os.path.relpath(path, root).replace(os.sep, "/")
                if any(rel.startswith(p) for p in NOT_SEARCHED) or os.path.islink(path):
                    continue
                try:
                    with open(path, encoding="utf-8") as fh:
                        text = fh.read()
                except (UnicodeDecodeError, OSError):
                    continue
                skip = skipped_lines(rel, text)
                for n, line in enumerate(text.split("\n"), 1):
                    if n in skip:
                        continue
                    for m in pattern.finditer(line):
                        found.append(f"{rel}:{n}: {m.group(1)}")
    return found


# The engine's files whose every key is a setting (#568 C4). repos.yml is
# the organisation's own, replaced whole; its settings are the schema's
# alone.
CHECKED = ("org.yml", "policy/autonomy.yml", "policy/review-policy.default.yml", "kinds/*/pack.yml")
HOWS = ("any", "lower-only", "stricter", "up-to-ceiling", "add-only", "never")
DOC = "docs/configuration.md"


def files_of(root, pattern):
    import glob
    return sorted(os.path.relpath(p, root).replace(os.sep, "/") for p in glob.glob(os.path.join(root, pattern)))


def covered(settings, path):
    """Whether PATH is a setting, or lies inside one."""
    return any(key_matches(str(s.get("key", "")), path[:n]) for s in settings for n in range(1, len(path) + 1))


def inside(settings, path):
    """Whether some setting lies deeper than PATH, a mapping."""
    return any(str(s.get("key", "")) != "." and len(str(s["key"]).split(".")) > len(path)
               and key_matches(".".join(str(s["key"]).split(".")[:len(path)]), path) for s in settings)


def missing(settings, data, path=()):
    """The key paths of DATA that no setting covers."""
    out = []
    for key, value in (data or {}).items() if isinstance(data, dict) else ():
        here = (*path, str(key))
        if covered(settings, list(here)):
            continue
        if isinstance(value, dict) and inside(settings, list(here)):
            out += missing(settings, value, here)
        else:
            out.append(".".join(here))
    return out


def problems(root=ROOT):
    """What keeps the schema, the engine's files and the scripts apart."""
    conf = load(os.path.join(root, "policy", "settings-schema.yml")) or {}
    out = []
    for pattern, settings in (conf.get("files") or {}).items():
        for s in settings or []:
            where = f"{pattern} {s.get('key')}"
            for part in ("key", "org", "repo", "limit", "read-by", "issue", "says"):
                if s.get(part) in (None, "", []):
                    out.append(f"{where}: says no `{part}`")
            for level in ("org", "repo"):
                if s.get(level) is not None and s.get(level) not in HOWS:
                    out.append(f"{where}: `{level}` is one of {', '.join(HOWS)}")
            word = next((p for p in reversed(str(s.get("key", "")).split(".")) if p not in ("*", "")), "")
            for script in s.get("read-by") or []:
                path = os.path.join(root, script)
                if not os.path.isfile(path):
                    out.append(f"{where}: read by {script}, which is not there")
                elif word and not re.search(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])", open(path, encoding="utf-8").read()):
                    out.append(f"{where}: {script} does not read `{word}`")
    for pattern in CHECKED:
        for rel in files_of(root, pattern):
            for key in missing(entries(conf, rel), load(os.path.join(root, rel))):
                out.append(f"{rel} {key}: a setting the schema (policy/settings-schema.yml) does not list")
    doc = os.path.join(root, DOC)
    if not os.path.isfile(doc) or open(doc, encoding="utf-8").read() != docs(root):
        out.append(f"{DOC}: not what `settings.py docs` writes; run `python3 scripts/settings.py docs > {DOC}`")
    return out


def shown(value, limit=70):
    text = json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
    text = text if len(text) <= limit else text[:limit - 1] + "…"
    return "`" + text.replace("|", "\\|").replace("`", "'") + "`"


def default_of(root, rel_pattern, s):
    """A setting's default, for people."""
    if s.get("identity"):
        return "the organisation's own, never the engine's"
    if "default" in s:
        d = s["default"]
        return d if isinstance(d, str) and " " in d else shown(d)
    key = str(s.get("key", ""))
    if "*" in key or "*" in rel_pattern or key == ".":
        return f"each one's own, in `{rel_pattern}`"
    value = load(os.path.join(root, rel_pattern)) or {}
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return "none"
        value = value[part]
    return shown(value)


LEVELS_DOC = """The levels, named the same everywhere:

- **engine**: the engine's defaults, the files of DiluxOne/.github.
- **org**: the organisation's configuration, its own `.github` repository, laid over the engine's by `scripts/config-overlay.sh`. A file it has overrides only the keys it sets: a mapping key by key, a value or a list replaced, an `add-only` list added to (the engine's entries are kept), `labels.yml` merged by name. `repos.yml` and any file that is not YAML replace the engine's whole. The merged autonomy policy must pass `autonomy.py check`, or the run stops.
- **repo**: a repository's own file (`.github/autonomy.yml`, `.github/review-policy.yml`, its entry in `repos.yml`), read by the script that applies the setting, within what its organisation lets it and never past the engine's safeguards: autonomy cannot widen itself.

What a level may do: `any` value; `lower-only`; `stricter` (switch off, narrow, ask a person); `up-to-ceiling` (raise it up to the setting's ceiling; past it, held there with a warning); `add-only` (add entries, never remove one); `never`.
"""


def docs(root=ROOT):
    """docs/configuration.md, from the schema and the engine's files."""
    conf = load(os.path.join(root, "policy", "settings-schema.yml")) or {}
    out = ["# Configuration", "",
           "Every setting the engine applies (#568): its default, who may change it and how far. Written by `python3 scripts/settings.py docs` from [`policy/settings-schema.yml`](../policy/settings-schema.yml), which CI holds to the engine's files and to the scripts that read them (`settings.py check`): edit the schema, never this page. Which level a value in force comes from: `settings.py explain FILE KEY`.",
           "", LEVELS_DOC.rstrip(), ""]
    for pattern, settings in (conf.get("files") or {}).items():
        out += [f"## `{pattern}`", "", "| Setting | Default | org | repo | Limit | Read by | Issue |", "|---|---|---|---|---|---|---|"]
        for s in settings or []:
            key = str(s.get("key", ""))
            name = "(the whole list)" if key == "." else f"`{key}`"
            extra = " Added to, never replaced." if s.get("merge") == "add-only" else (" Merged by `name`." if s.get("by") else "")
            readers = ", ".join(f"[`{os.path.basename(r)}`](../{r})" for r in s.get("read-by") or [])
            cells = [f"{name}: {s.get('says', '')}{extra}", default_of(root, pattern, s), f"`{s.get('org')}`", f"`{s.get('repo')}`",
                     str(s.get("limit", "")), readers, str(s.get("issue", ""))]
            out.append("| " + " | ".join(c.replace("\n", " ").replace("|", "\\|") if i != 1 else c for i, c in enumerate(cells)) + " |")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def value_at(data, key):
    for part in key.split("."):
        if not isinstance(data, dict) or part not in data:
            return False, None
        data = data[part]
    return True, data


def explain(rel, key, org_file=None, repo_file=None, root=ROOT):
    """(the value in force, the level it comes from) of KEY in REL."""
    engine = load(os.path.join(root, rel)) or {}
    theirs = load(org_file) if org_file else {}
    merged = merge(engine, theirs or {}, entries(schema(), rel)) if theirs else engine
    force = merged
    if repo_file and rel == "policy/autonomy.yml":
        sys.path.insert(0, HERE)
        import autonomy
        force = autonomy.merge(merged, load(repo_file) or {})
    has, value = value_at(force, key)
    for level, data in (("repo", load(repo_file) if repo_file else {}), ("org", theirs or {})):
        there, mine = value_at(data, key)
        if there and mine == value:
            return value, level
    return value, "engine" if has else "none"


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    import tempfile
    conf = schema()
    autonomy = entries(conf, "policy/autonomy.yml")
    check("the schema has the autonomy policy's settings", bool(rule(autonomy, ["lanes", "human-issue", "merge"])), True)
    check("a key with * is any lane", key_matches("lanes.*.accept", ["lanes", "x", "accept"]), True)
    check("but not deeper", key_matches("lanes.*.accept", ["lanes", "x", "accept", "y"]), False)
    check("`.` is the whole file", key_matches(".", []), True)
    engine = {"autopilot": True, "constitution": ["policy/**", "rules/**"], "person-merges": ["security"],
              "budgets-usd": {"autopilot-work": 20, "autopilot-fix": 10},
              "lanes": {"bugfix-reproduced": {"accept": "policy", "repositories": ["*"], "merge": {"max-risk": "medium", "max-complexity": "medium"}},
                        "human-issue": {"accept": "human", "merge": {"max-risk": "medium", "max-complexity": "high"}}}}
    got = merge(engine, {"lanes": {"bugfix-reproduced": {"accept": "human"}}}, autonomy)
    check("C1: one key set, only that key changes", got["lanes"]["bugfix-reproduced"], {**engine["lanes"]["bugfix-reproduced"], "accept": "human"})
    check("C1: every other key is the engine's", {k: v for k, v in got.items() if k != "lanes"}, {k: v for k, v in engine.items() if k != "lanes"})
    check("C1: and the other lanes", got["lanes"]["human-issue"], engine["lanes"]["human-issue"])
    got = merge(engine, {"lanes": {"human-issue": {"merge": {"max-risk": "low"}}}}, autonomy)
    check("a mapping merges key by key", got["lanes"]["human-issue"]["merge"], {"max-risk": "low", "max-complexity": "high"})
    got = merge(engine, {"budgets-usd": {"autopilot-work": 5}}, autonomy)
    check("a value replaces", got["budgets-usd"], {"autopilot-work": 5, "autopilot-fix": 10})
    got = merge(engine, {"lanes": {"bugfix-reproduced": {"repositories": ["a"]}}}, autonomy)
    check("B1: a list replaces the engine's", got["lanes"]["bugfix-reproduced"]["repositories"], ["a"])
    got = merge(engine, {"constitution": ["docs/**"], "person-merges": []}, autonomy)
    check("B1: an add-only list keeps the engine's entries, then adds", got["constitution"], ["policy/**", "rules/**", "docs/**"])
    check("B1: an add-only list cannot be emptied", got["person-merges"], ["security"])
    try:
        merge(engine, {"constitution": "none"}, autonomy)
        check("an add-only list replaced by a value fails", "merged", "ValueError")
    except ValueError:
        check("an add-only list replaced by a value fails", "ValueError", "ValueError")
    got = merge(engine, {"lanes": {"theirs": {"accept": "human"}}}, autonomy)
    check("a key the engine has not is added", got["lanes"]["theirs"], {"accept": "human"})
    orgs = entries(conf, "org.yml")
    got = merge({"org": "DiluxOne", "bot": {"app": "dilux-bot", "id": 1}, "maintainers": ["a"], "attribution": "warn"},
                {"org": "Acme", "bot": {"app": "acme-bot"}}, orgs)
    check("identity keys are never kept from the engine's", got, {"org": "Acme", "bot": {"app": "acme-bot"}, "attribution": "warn"})
    labels = entries(conf, "labels.yml")
    got = merge([{"name": "accepted", "color": "0E8A16"}, {"name": "claimed", "color": "5319E7"}],
                [{"name": "accepted", "description": "Acme's"}, {"name": "acme:own", "color": "000000"}], labels)
    check("labels merge by name", got, [{"name": "accepted", "color": "0E8A16", "description": "Acme's"}, {"name": "claimed", "color": "5319E7"}, {"name": "acme:own", "color": "000000"}])
    check("a kind's pack has its rules", rule(entries(conf, "kinds/web-app/pack.yml"), ["release", "publishes-to"]).get("org"), "any")
    # C4: the schema covers every key of the engine's files, and the docs.
    check("C4: the engine's files, the schema, the scripts and the docs agree", problems(ROOT), [])
    with_more = {"autopilot": True, "lanes": {"x": {"accept": "human", "new-key": 1}}, "brand-new": 2}
    check("C4: a key the schema does not list is found", missing(autonomy, with_more), ["lanes.x.new-key", "brand-new"])
    check("C4: a setting covers what lies inside it", missing(autonomy, {"budgets-usd": {"x": 1}, "security-patch": {"max-files": 1}}), [])
    check("C4: the docs list every setting", all(f"`{s['key']}`" in docs(ROOT) for s in autonomy), True)
    check("C4: a default is the engine's file's", default_of(ROOT, "policy/autonomy.yml", {"key": "autopilot-runs"}), "`5`")
    check("C4: an identity is never the engine's", default_of(ROOT, "org.yml", {"key": "bot", "identity": True}), "the organisation's own, never the engine's")
    with tempfile.TemporaryDirectory() as t:
        o, r = os.path.join(t, "o.yml"), os.path.join(t, "r.yml")
        with open(o, "w", encoding="utf-8") as fh:
            fh.write("lanes:\n  human-issue: {merge: {max-risk: low}}\n  bugfix-reproduced: {accept: human}\n")
        with open(r, "w", encoding="utf-8") as fh:
            fh.write("lanes:\n  human-issue: {merge: {max-risk: medium}}\n")
        check("explain: the engine's", explain("policy/autonomy.yml", "autopilot-runs", o, r), (5, "engine"))
        check("explain: the organisation's", explain("policy/autonomy.yml", "lanes.bugfix-reproduced.accept", o, r), ("human", "org"))
        check("explain: the repository's", explain("policy/autonomy.yml", "lanes.human-issue.merge.max-risk", o, r), ("medium", "repo"))
        check("explain: a key that is none", explain("policy/autonomy.yml", "lanes.nope", o), (None, "none"))
    # C3: the organisation's values, and where they are not searched.
    values = identity_values(ROOT)
    check("C3: the App, its login and id, the maintainers and the catalog are searched", {"dilux-bot", "dilux-bot[bot]", "333187390", "soydiloreto", "diluxone-plugins-ai", "DiluxOne/security"} <= set(values), True)
    check("C3: every repository but the engine, the security one by its full name", ("diluxone-mermaid" in values, ".github" in values, "security" in values), (True, False, False))
    py = 'X = 1\n# dilux-bot\n"""a"""\n\n\ndef self_test():\n    return "dilux-bot"\n\n\ndef merge_tests():\n    return 1\n\n\ndef main():\n    return 2\n'
    check("C3: a Python script's comments and self-tests are skipped", sorted(skipped_lines("x.py", py)), [2, 6, 7, 10, 11])
    sh = 'a=1\n# x\nself_test() {\n  b=2\n}\nif [ "${1:-}" = --test ]; then\n  self_test\nfi\nmain\n'
    check("C3: a shell script's comments and its --test block are skipped", sorted(skipped_lines("x.sh", sh)), [2, 3, 4, 5, 6, 7, 8])
    check("C3: in YAML only comments", sorted(skipped_lines("x.yml", "a: 1\n  # b\nc: 2\n")), [2])
    with tempfile.TemporaryDirectory() as t:
        os.makedirs(os.path.join(t, "kinds", "k"))
        with open(os.path.join(t, "kinds", "k", "pack.yml"), "w", encoding="utf-8") as fh:
            fh.write("# acme-bot\nrelease: {publishes-to: acme-plugins}\nwho: [xacme-bot, acme-bot-x]\nbot: acme-bot[bot]\n")
        check("C3: a value is found as a whole word, and only there", org_free(t, ["acme-bot", "acme-bot[bot]", "acme-plugins"]),
              ["kinds/k/pack.yml:2: acme-plugins", "kinds/k/pack.yml:4: acme-bot[bot]"])
        check("C3: no values, nothing to find", org_free(t, []), [])
    with tempfile.TemporaryDirectory() as t:
        e, o = os.path.join(t, "e.yml"), os.path.join(t, "o.yml")
        with open(e, "w", encoding="utf-8") as fh:
            fh.write("a: 1\nmerge-queue: \"off\"\nb: {c: 2, d: 3}\n")
        with open(o, "w", encoding="utf-8") as fh:
            fh.write("b: {c: 4}\n")
        got = overlay(e, o, "x.yml", {})
        check("overlay: two files", got, {"a": 1, "merge-queue": "off", "b": {"c": 4, "d": 3}})
        with open(os.path.join(t, "empty.yml"), "w", encoding="utf-8") as fh:
            fh.write("# nothing set\n")
        check("overlay: an empty file of the organisation's sets nothing", overlay(e, os.path.join(t, "empty.yml"), "x.yml", {}), {"a": 1, "merge-queue": "off", "b": {"c": 2, "d": 3}})
        check("overlay: written as YAML that reads the same", load_text(dump(got)), got)
        with open(o, "w", encoding="utf-8") as fh:
            fh.write("x" * (MAX_BYTES + 1))
        try:
            overlay(e, o, "x.yml", {})
            check("a file too large to be configuration fails", "read", "ValueError")
        except ValueError:
            check("a file too large to be configuration fails", "ValueError", "ValueError")
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def load_text(text):
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8") as fh:
        fh.write(text)
    try:
        return load(fh.name)
    finally:
        os.unlink(fh.name)


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv[:1] == ["check"] and len(argv) <= 2:
        found = problems(argv[1] if len(argv) == 2 else ROOT)
        for line in found:
            print(line)
        return 1 if found else 0
    if argv[:1] == ["docs"] and len(argv) <= 2:
        sys.stdout.write(docs(argv[1] if len(argv) == 2 else ROOT))
        return 0
    if argv[:1] == ["explain"] and len(argv) >= 3:
        opts = dict(zip(argv[3::2], argv[4::2]))
        if len(argv) % 2 == 0 or set(opts) - {"--org", "--repo"}:
            print(__doc__, file=sys.stderr)
            return 64
        value, level = explain(argv[1], argv[2], opts.get("--org"), opts.get("--repo"))
        print(json.dumps({"key": f"{argv[1]} {argv[2]}", "value": value, "level": level}))
        return 0
    if argv[:1] == ["org-free"] and len(argv) <= 2:
        found = org_free(argv[1] if len(argv) == 2 else ROOT)
        for line in found:
            print(f"{line}: the organisation's own value, in the engine (org.yml or repos.yml holds it; read it from there)")
        return 1 if found else 0
    if argv[:1] == ["overlay"] and len(argv) in (3, 5) and (len(argv) == 3 or argv[3] == "--as"):
        try:
            sys.stdout.write(dump(overlay(argv[1], argv[2], argv[4] if len(argv) == 5 else None)))
        except (ValueError, OSError) as exc:
            print(f"::error::{argv[2]}: {exc}", file=sys.stderr)
            return 1
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
