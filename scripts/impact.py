#!/usr/bin/env python3
"""The impact map of a change, built from git with no model (#958).

Before the code is written, the autopilot read the repository with the
model to learn what a change touches, and the review read it again to judge
it. This prints what git can tell instead, for the work's prompt
(scripts/autopilot.py `prompt work`) and the review's brief
(scripts/review-brief.sh `IMPACT=`), as Markdown cut to 4 KB:

  files     the files the Spec's `Spec: files` section names (backticked or
            path-like tokens that exist in the repository), and, for a
            change (BASE HEAD), the files its diff changes
  surface   the kind's public surface they touch: the entries of
            kinds/<kind>/surface.yml (read through scripts/surface.py) whose
            `files` globs match a file and whose pattern is in it (a file
            not written yet: whose globs match it)
  tests     the files under the repository's declared test paths
            (`test-first:`, read through scripts/test-first.py) that name a
            file's path or its stem
  callers   the files that name a file's path or its stem (a word), or a symbol the
            change touches (the identifiers the Spec backticks; for a diff,
            the names in its hunk headers and in the def, function and class
            lines it adds or removes), with `git grep -F` (fixed strings,
            after `--`, never through a shell); the file itself and
            generated or vendored paths left out, at most 10 per name

The map is cut on a line boundary to 4096 bytes, in that order of priority
(files, surface, tests, callers), with a last line saying what was left out.
A repository with no kind or no `test-first:` gets a map without surface or
tests, never an error. Paths and names from the Spec are data: only tokens
that match a path or an identifier pattern are kept.

  impact.py map [--spec FILE] [--base BASE --head HEAD] [--kind KIND] [--repo NAME]
        print the map; with no BASE and HEAD, of the working tree. The kind
        is the repository's (`kind:` in its .github/review-policy.yml) when
        --kind is not given; NAME (default GITHUB_REPOSITORY) finds its
        `test-first:` in repos.yml too
  impact.py threats [--brief] [--spec FILE] [--base BASE --head HEAD] [--kind KIND]
        the deterministic trigger for threats: print why the change needs
        its `Spec: threats` section, one line per entry that fires (exit 1),
        or nothing (exit 0); 2 when it cannot tell. --brief prints, when it
        fires, the review brief's lines instead: "Threats required: <why>"
        and the Spec's threats section as it stands (or that it has none),
        and when it cannot tell, "Threats required: the trigger could not
        tell", so that the brief fails closed as the decision does. The entries are the
        organisation's (policy/threats.yml) and the kind's (`threats:` in
        kinds/<kind>/surface.yml, add-only), read from this checkout of the
        engine, never from the change's head: on a Spec (the issue body's
        Spec sections, as G3 reads them), the paths its `Spec: files` names
        and its text, line by line; on a change, the paths it changes and
        the lines its diff adds or removes in code, never in a docs path or
        a declared test (but for an entry with `docs: true`)
  impact.py kind       the kind the repository in the working directory
                       declares, or nothing
  impact.py --test     self-test, on scratch repositories
"""
import fnmatch
import importlib.util
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import surface  # noqa: E402  the kind's pack, read as the surface check reads it
from policy import CENTRAL, glob_to_regex, load_yaml  # noqa: E402

LIMIT = 4096
PER_NAME = 10
MAX_TESTS = 15  # the tests that name most of the files first
TOTAL_CALLERS = 80
NAMES = 40
GREP_SECONDS = 20
SEARCH_SECONDS = 60  # the whole search's budget: the names left are not searched
# A path or an identifier, as the Spec or the diff may name one: nothing
# else is kept, so nothing else reaches git.
SAFE_PATH = re.compile(r"[A-Za-z0-9_@+.-]+(?:/[A-Za-z0-9_@+.-]+)*")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# A stem too common to say who calls a file.
COMMON = {"index", "main", "init", "__init__", "setup", "config", "utils", "util", "test", "tests", "readme", "license",
          "changelog", "package", "composer", "makefile", "action", "plugin", "style", "styles", "common", "helpers"}
# Generated, vendored or history files are never a caller.
NOISE = ["vendor/**", "node_modules/**", "dist/**", "build/**", "*.min.js", "*.min.css", "*.map", "*.lock",
         "package-lock.json", "CHANGELOG*", "changelog/**", ".changes/**"]
NOISE_RX = [glob_to_regex("**/" + g) for g in NOISE]
DEF_LINE = re.compile(r"\b(?:def|function|class)\s+&?([A-Za-z_][A-Za-z0-9_]*)")
HUNK = re.compile(r"^@@ [^@]* @@ ?(.*)$")
SPEC_HEAD = re.compile(r"^###\s+Spec:\s*(.+?)\s*$", re.M)


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(root, *args, timeout=None):
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=timeout)


def noise(path):
    return any(r.match(path) for r in NOISE_RX)


# --- what the Spec names -------------------------------------------------------

def spec_section(text, name):
    """The text of the Spec's `### Spec: NAME` section ("" when none). Pure."""
    heads = list(SPEC_HEAD.finditer(text or ""))
    for i, m in enumerate(heads):
        if m.group(1).strip().lower() == name.lower():
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            nxt = re.search(r"^#{1,6}\s", text[m.end():end], re.M)
            return text[m.end():m.end() + nxt.start()] if nxt else text[m.end():end]
    return ""


def path_tokens(text):
    """The path-like tokens of TEXT, in order, once each: backticked ones and
    bare words with a slash or an extension. Only SAFE_PATH ones. Pure."""
    found = []
    for raw in re.findall(r"`([^`\n]+)`", text or "") + re.findall(r"[^\s`(),;:'\"<>]+", re.sub(r"`[^`\n]*`", " ", text or "")):
        tok = raw.strip().lstrip(",;:").rstrip(".,;:").removeprefix("./")
        if ("/" in tok or re.search(r"\.[A-Za-z0-9]{1,8}$", tok)) and SAFE_PATH.fullmatch(tok) and tok not in found \
                and not tok.startswith(("http", "-")) and ".." not in tok.split("/"):
            found.append(tok)
    return found


def spec_files(text):
    """The paths the Spec's `Spec: files` section names (the whole text when
    it has no such section). Pure."""
    return path_tokens(spec_section(text, "files") or ("" if SPEC_HEAD.search(text or "") else text))


def spec_symbols(text):
    """The code names the Spec backticks: an identifier with an underscore or
    a capital inside it, or one written as a call. Pure."""
    out = []
    for raw in re.findall(r"`([^`\n]+)`", text or ""):
        m = re.fullmatch(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*(\(.*\))?\s*", raw)
        if not m:
            continue
        name = m.group(1)
        if len(name) >= 4 and (m.group(2) or "_" in name.strip("_") or re.search(r"[a-z][A-Z]", name)) and name not in out:
            out.append(name)
    return out


def diff_symbols(patch):
    """The names a unified diff touches: in its hunk headers and in the def,
    function and class lines it adds or removes. Pure."""
    out = []
    for line in (patch or "").splitlines():
        m = HUNK.match(line)
        if m:
            cands = DEF_LINE.findall(m.group(1)) or re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", m.group(1))[-1:]
        elif line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            cands = DEF_LINE.findall(line)
        else:
            continue
        for name in cands:
            if len(name) >= 4 and name not in out:
                out.append(name)
    return out


# --- the repository, from git --------------------------------------------------

def tracked(root, rev=None):
    out = git(root, "ls-tree", "-r", "-z", "--name-only", rev) if rev else git(root, "ls-files", "-z")
    if out.returncode != 0:
        raise RuntimeError(f"git could not list the files: {out.stderr.strip()[:200]}")
    return [p for p in out.stdout.split("\0") if p]


def changed_files(root, base, head):
    mb = git(root, "merge-base", base, head)
    if mb.returncode != 0:
        raise RuntimeError(f"no merge base of {base} and {head}: {mb.stderr.strip()[:200]}")
    mb = mb.stdout.strip()
    out = git(root, "diff", "--no-renames", "--name-only", "-z", mb, head)
    patch = git(root, "diff", "--no-renames", "-U0", mb, head)
    if out.returncode != 0 or patch.returncode != 0:
        raise RuntimeError(f"git diff {mb}..{head} failed")
    return [p for p in out.stdout.split("\0") if p], patch.stdout, mb


def grep(root, name, rev=None, word=False):
    """The files that hold NAME as a fixed string (a word, for a symbol), at
    REV or in the working tree; [] when git cannot tell in time."""
    args = ["grep", "-l", "-I", "-F", "--full-name"] + (["-w"] if word else []) + ["-e", name] + ([rev] if rev else []) + ["--"]
    try:
        out = git(root, *args, timeout=GREP_SECONDS)
    except subprocess.TimeoutExpired:
        return []
    if out.returncode not in (0, 1):
        return []
    prefix = f"{rev}:" if rev else ""
    return [l[len(prefix):] if prefix and l.startswith(prefix) else l for l in out.stdout.splitlines() if l]


def stem(path):
    base = os.path.basename(path)
    return base.split(".", 1)[0] if not base.startswith(".") else base


def repo_kind(root):
    """The kind the repository's .github/review-policy.yml declares, or ""."""
    try:
        pol = load_yaml(os.path.join(root, ".github", "review-policy.yml"))
    except (OSError, ValueError, Exception):  # a policy that does not parse names no kind
        return ""
    kind = str((pol or {}).get("kind") or "").strip() if isinstance(pol, dict) else ""
    return kind if re.fullmatch(r"[a-z0-9-]+", kind) else ""


def declaration(root, name, rev):
    """The repository's `test-first:` declaration (scripts/test-first.py), or
    None when it declares none or it cannot be read."""
    try:
        tf = _load("test_first_impact", "test-first.py")
        return tf, tf.declaration(root, CENTRAL, name, rev or "HEAD")[1]
    except Exception:  # no declaration is no tests section, never an error
        return None, None


# --- the map -------------------------------------------------------------------

def surface_hits(pack, files, read):
    """[(id, what, [files])] of the pack's surface entries a file touches:
    its `files` globs match it, and its pattern is in it (a file that does
    not exist yet: its globs alone). read(path) is its text or None."""
    out = []
    exclude = pack.get("exclude") or []
    for entry in pack.get("surface") or []:
        take = surface.selector(entry.get("files") or pack.get("files") or [], exclude)
        try:
            rx = surface.compile_entry(entry)
        except ValueError:
            continue
        hit = []
        for p in files:
            if not take(p):
                continue
            text = read(p)
            if text is None or rx.search(text):
                hit.append(p)
        if hit:
            out.append((entry.get("id", "?"), entry.get("what", ""), hit))
    return out


def build(root, spec="", base="", head="", kind="", repo=""):
    """The map's parts: {files, surface, tests, callers, kind}."""
    rev = head or None
    every = tracked(root, rev)
    present = set(every)
    files = [p for p in spec_files(spec) if p in present]
    symbols = spec_symbols(spec)
    if base and head:
        changed, patch, _ = changed_files(root, base, head)
        for p in changed:
            if p in present and SAFE_PATH.fullmatch(p) and p not in files:
                files.append(p)
        symbols += [s for s in diff_symbols(patch) if s not in symbols]

    def read(p):
        if p not in present:
            return None
        if rev:
            got = surface.read_blobs(rev, [p]) if os.path.abspath(root) == os.path.abspath(".") else _blob(root, rev, p)
            return got.get(p, "")
        try:
            if os.path.getsize(os.path.join(root, p)) > surface.MAX_BYTES:  # a file too large to read touches nothing
                return ""
            with open(os.path.join(root, p), encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return ""

    hits = []
    if kind:
        try:
            hits = surface_hits(surface.load_pack(kind), files, read)
        except ValueError:
            hits = []
    tf, decl = declaration(root, repo, head or "HEAD")
    test_set = {p for p, _ in tf.tests_of(decl, every)} if decl else set()

    tests, callers, total = {}, [], 0
    for p in files:
        if p in test_set:
            tests.setdefault(p, [])
    names = []
    for p in files:
        names.append((p, p, False))
        s = stem(p)
        if len(s) >= 4 and s.lower() not in COMMON and IDENT.fullmatch(s.replace("-", "_")):
            names.append((p, s, True))
    names += [(None, s, True) for s in symbols]
    seen_names = set()
    deadline = time.monotonic() + SEARCH_SECONDS
    for owner, name, word in names[:NAMES]:
        if name in seen_names or time.monotonic() > deadline:
            continue
        seen_names.add(name)
        found = [f for f in grep(root, name, rev, word) if f != owner and not noise(f)]
        for f in found:
            if f in test_set and owner and f not in files:
                tests.setdefault(f, [])
                if owner not in tests[f]:
                    tests[f].append(owner)
        others = [f for f in found if f not in test_set and f not in files][:PER_NAME]
        if others and total < TOTAL_CALLERS:
            others = others[:TOTAL_CALLERS - total]
            total += len(others)
            label = f"`{name}`" + (" (a name)" if owner is None else "")
            callers.append((label, others))
    return {"files": files, "surface": hits, "tests": tests, "callers": callers, "kind": kind,
            "declared": decl is not None}


def _blob(root, rev, path):
    out = subprocess.run(["git", "-C", root, "show", f"{rev}:{path}"], capture_output=True)
    if out.returncode != 0 or len(out.stdout) > surface.MAX_BYTES:
        return {}
    return {path: out.stdout.decode("utf-8", "replace")}


def render(parts, limit=LIMIT):
    """The map as Markdown lines, cut on a line boundary to LIMIT bytes, in
    order of priority, with a last line saying what was left out. Pure."""
    sections = []
    sections.append(("files", "Files it touches:", [f"- `{p}`" for p in parts["files"]] or ["- none the Spec names exists yet"]))
    if parts.get("kind"):
        rows = [f"- `{i}`: {what} ({', '.join(f'`{p}`' for p in ps[:5])}{', …' if len(ps) > 5 else ''})" for i, what, ps in parts["surface"]]
        sections.append(("surface", f"Public surface of the kind `{parts['kind']}` it touches (kinds/{parts['kind']}/surface.yml):", rows or ["- none"]))
    if parts.get("declared"):
        ranked = sorted(parts["tests"].items(), key=lambda kv: -len(kv[1]))
        rows = [f"- `{t}`" + (f": names {', '.join(f'`{o}`' for o in owners)}" if owners else "") for t, owners in ranked[:MAX_TESTS]]
        if len(ranked) > MAX_TESTS:
            rows.append(f"- and {len(ranked) - MAX_TESTS} more")
        sections.append(("tests", "Tests that cover them (the declared test paths):", rows or ["- none found"]))
    rows = [f"- {label}: {', '.join(f'`{f}`' for f in found)}" for label, found in parts["callers"]]
    sections.append(("callers", "Who calls or names them:", rows or ["- none found"]))
    lines, cut = [], {}
    reserve = 160
    size = 0
    for key, title, rows in sections:
        for i, line in enumerate([title] + rows + [""]):
            n = len(line.encode("utf-8")) + 1
            if cut or size + n > limit - reserve:
                if line and i > 0:
                    cut[key] = cut.get(key, 0) + 1
                elif i == 0:
                    cut.setdefault(key, 0)
                continue
            lines.append(line)
            size += n
    while lines and not lines[-1]:
        lines.pop()
    if cut:
        said = ", ".join(f"{n} line(s) of {k}" if n else k for k, n in cut.items())
        lines.append(f"(left out to stay within {limit} bytes: {said})")
    return "\n".join(lines)


def impact_map(root=".", spec="", base="", head="", kind=None, repo=""):
    """The map's text, or one line saying why it could not be built."""
    if kind is None:
        kind = repo_kind(root)
    try:
        return render(build(root, spec, base, head, kind, repo))
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        return f"(The impact map could not be built: {str(e)[:200]}.)"


# --- the threat trigger --------------------------------------------------------

THREATS_FILE = os.path.join(CENTRAL, "policy", "threats.yml")


def threat_entries(kind=""):
    """The organisation's entries and the kind's, each compiled once:
    [(entry, [path regexes], pattern or None)]. A kind with no pack is an
    error (ValueError), as the surface check's."""
    org = (load_yaml(THREATS_FILE) or {}).get("threats") or []
    pack = surface.load_pack(kind) if kind else {}
    out = []
    for entry in list(org) + list(pack.get("threats") or []):
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("what"):
            raise ValueError(f"a threats entry with no id or what: {entry!r:.80}")
        try:
            rx = re.compile(entry["pattern"]) if entry.get("pattern") else None
        except re.error as e:
            raise ValueError(f"threats entry {entry['id']}: its pattern does not compile ({e})")
        globs = [glob_to_regex(g) for g in entry.get("paths") or []]
        if not rx and not globs:
            raise ValueError(f"threats entry {entry['id']}: neither paths nor a pattern")
        out.append((entry, globs, rx))
    return out


def shown(text):
    return re.sub(r"[`\s]+", " ", text).strip()[:60]


def threat_hits(entries, paths, lines):
    """Why the change needs its threats, one line per entry that fires: a
    path its globs match, or a line its pattern matches. Pure."""
    out = []
    for entry, globs, rx in entries:
        where = next((p for p in paths if any(g.match(p) for g in globs)), None)
        if where is None and rx is not None:
            m = next((m for line in lines for m in [rx.search(line)] if m), None)
            where = f"\"{shown(m.group(0))}\"" if m else None
        if where is not None:
            out.append(f"{entry['id']}: {entry['what']}, {where}")
    return out


def on_text(text, kind="", entries=None):
    """The trigger on a Spec (or a PRD): the paths it names (`Spec: files`,
    or the whole text when it has none) and its lines."""
    entries = threat_entries(kind) if entries is None else entries
    return threat_hits(entries, spec_files(text), (text or "").splitlines())


def diff_lines(patch):
    """The lines a unified diff adds or removes, never its file headers. Pure."""
    return [line for _, line in diff_file_lines(patch)]


def diff_file_lines(patch):
    """[(path, line)] of the lines a unified diff adds or removes, each with
    the file it is in (its `+++ b/` name, or `--- a/` for a file deleted; a
    name git quotes stays quoted, so it matches no prose glob and counts as
    code). Pure."""
    out, in_hunk, path = [], False, ""
    for line in (patch or "").splitlines():
        if line.startswith("diff --git "):
            in_hunk, path = False, ""
        elif not in_hunk and line.startswith("--- a/"):
            path = line[6:]
        elif not in_hunk and line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line[:1] in ("+", "-"):
            out.append((path, line[1:]))
    return out


def spec_part(text):
    """The Spec sections of an issue's body, from its first `### Spec: `
    heading to the end, as G3 and the decision read them (autopilot.py
    spec_of); "" when it has none. Pure."""
    m = SPEC_HEAD.search(text or "")
    return text[m.start():] if m else ""


def prose_globs(kind=""):
    """The docs-paths (the organisation's and the kind's, shell `case`
    globs: `*` crosses directories) whose lines are prose, not code."""
    return surface.docs_paths(kind)


def is_prose(path, docs, tests):
    """Whether PATH is prose or a test, whose diff lines do not fire an
    entry that does not ask for them (`docs: true`): a docs path, or a
    declared test path. Pure."""
    return path in tests or any(fnmatch.fnmatchcase(path, g) for g in docs)


def on_change(root, base, head, kind="", entries=None, repo=""):
    """The trigger on a change: the paths it changes, and the lines its diff
    adds or removes in code. A line of a docs path (the organisation's and
    the kind's `docs-paths`) or of a declared test (`test-first:`) is prose
    about the code, not the code, and fires only an entry with `docs: true`
    (a kind whose Markdown is what an agent runs): the review's trigger then
    fires on no more than what the code does, as G3 at the draft reads the
    Spec alone (#974)."""
    entries = threat_entries(kind) if entries is None else entries
    changed, patch, _ = changed_files(root, base, head)
    pairs = diff_file_lines(patch)
    docs = prose_globs(kind)
    tf, decl = declaration(root, repo, head or "HEAD")
    tests = {p for p, _ in tf.tests_of(decl, sorted({p for p, _ in pairs}))} if decl else set()
    every = [line for _, line in pairs]
    code = [line for p, line in pairs if not is_prose(p, docs, tests)]
    out = []
    for e in entries:
        out += threat_hits([e], changed, every if e[0].get("docs") else code)
    return out


def brief_lines(spec, hits):
    """The impact map's threats part in the review's brief, when the
    trigger fired: why, and the Spec's threats section as data. Pure."""
    if not hits:
        return ""
    section = spec_section(spec, "threats").strip()
    said = (f"The Spec's threats section, as it stands:\n\n{section}" if section
            else "The Spec has no threats section." if SPEC_HEAD.search(spec or "") else "There is no Spec to read it from (a change before its issue's Spec).")
    return f"Threats required: {'; '.join(hits)}\n\n{said}"


def unknown_lines(why):
    """The brief's lines when the trigger cannot tell (exit 2): it fails
    closed, as the decision does, so the review checks by hand. Pure."""
    return (f"Threats required: the trigger could not tell ({why}); check by hand whether the change "
            "touches an input, a permission, authentication, a secret or a workflow, and if it does, "
            "that the Spec's threats section covers each with what stops it.")


def fixture_problems(entries, label):
    """[(name, ok)] for each entry: its keys, and its fixtures (`fail` ones
    fire, `pass` ones do not), for impact.py's and surface.py's --test."""
    out = []
    for entry, globs, rx in entries:
        eid = f"{label}/threats/{entry['id']}"
        fx = entry.get("fixtures") or {}
        out.append((f"{eid}: has what, paths or a pattern, and fail and pass fixtures", bool(fx.get("fail")) and bool(fx.get("pass"))))
        one = [(entry, globs, rx)]
        for kind_, want in (("fail", True), ("pass", False)):
            for i, f in enumerate(fx.get(kind_) or []):
                paths, lines = ([f["path"]], []) if isinstance(f, dict) and f.get("path") else ([], [f if isinstance(f, str) else str((f or {}).get("text", ""))])
                got = bool(threat_hits(one, paths, lines))
                out.append((f"{eid}: {kind_} fixture {i + 1} " + ("fires" if want else "does not"), got == want))
    return out


# --- self-test -----------------------------------------------------------------

def self_test():
    import tempfile
    fail = 0

    def ok(name, cond):
        nonlocal fail
        print(("ok   " if cond else "FAIL ") + name)
        fail |= not cond

    ok("a Spec's files section, its backticked and bare paths",
       spec_files("### Spec: approach\n\n`x/y.py`\n\n### Spec: files\n\n- `a/b.py` (new)\n- c.md, docs/d.md\n- `$(rm -rf /)`\n") == ["a/b.py", "c.md", "docs/d.md"])
    ok("no path that climbs out", spec_files("### Spec: files\n\n- `../etc/passwd`\n") == [])
    ok("a Spec's symbols: a call, a snake or camel name; never a plain word",
       spec_symbols("`prompt_work`, `check(..., threats=...)`, `kindProfile`, `accepted`, `make pre-pr`") == ["prompt_work", "check", "kindProfile"])
    ok("a diff's symbols: hunk headers and defs added or removed",
       diff_symbols("@@ -1,2 +1,2 @@ def build_map(root):\n-def old_name():\n+function new_name() {\n+x = 1\n") == ["build_map", "old_name", "new_name"])
    big = render({"files": [f"src/f{i:04d}.py" for i in range(400)], "surface": [], "tests": {}, "callers": [], "kind": ""})
    ok("cut to 4096 bytes, saying what was left out", len(big.encode()) <= LIMIT and "left out" in big.splitlines()[-1])
    pri = render({"files": ["a.py"], "surface": [("s", "w", ["a.py"])], "tests": {"t/test_a.py": ["a.py"]},
                  "callers": [(f"`n{i}`", [f"c{i}_{j}.py" for j in range(10)]) for i in range(60)], "kind": "k", "declared": True})
    ok("callers are cut first, the files, surface and tests kept",
       "`a.py`" in pri and "`s`: w" in pri and "t/test_a.py" in pri and "left out" in pri and len(pri.encode()) <= LIMIT)

    for name, good in fixture_problems(threat_entries(""), "policy/threats.yml"):
        ok(name, good)
    org = threat_entries("")
    ok("a Spec that names a workflow fires",
       any(h.startswith("workflow:") and ".github/workflows/x.yml" in h for h in on_text("### Spec: files\n\n- `.github/workflows/x.yml`\n", entries=org)))
    ok("a Spec that touches none does not", on_text("### Spec: approach\n\nSay hello.\n\n### Spec: files\n\n- `src/a.py`\n", entries=org) == [])
    ok("a diff's lines, never its file headers", diff_lines("diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n") == ["old", "new"])
    ok("a kind adds its own", len(threat_entries("wordpress-plugin")) > len(org))

    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

        def sh(*a):
            subprocess.run(["git", "-C", d, *a], check=True, capture_output=True, env=env)

        def write(path, text):
            os.makedirs(os.path.dirname(os.path.join(d, path)) or d, exist_ok=True)
            with open(os.path.join(d, path), "w", encoding="utf-8") as fh:
                fh.write(text)

        sh("init", "-q", "-b", "main")
        write(".github/review-policy.yml", "kind: wordpress-plugin\n")
        write("includes/rest.php", "<?php\nfunction dx_rest_boot() {\n  register_rest_route( 'dx/v1', '/x', array() );\n}\n")
        write("plugin.php", "<?php\nrequire_once __DIR__ . '/includes/rest.php';\n")
        write("tests/Unit/RestTest.php", "<?php\n// includes/rest.php\n")
        write("vendor/lib/x.php", "<?php\n// includes/rest.php\n")
        write("lib/boot.php", "<?php\ndx_rest_boot();\n")
        sh("add", "-A")
        sh("commit", "-qm", "base")
        base = git(d, "rev-parse", "HEAD").stdout.strip()
        spec = "### Spec: files\n\n- `includes/rest.php`\n"
        got = impact_map(d, spec)
        ok("the working tree: the file", "`includes/rest.php`" in got)
        ok("its caller, never a vendored one", "`plugin.php`" in got and "vendor/" not in got)
        ok("its test, from the kind's test-first", "`tests/Unit/RestTest.php`" in got)
        ok("the kind's surface it touches", "`rest-route`" in got and "`setting`" not in got)
        write("app.php", "<?php\ndx_rest_boot();\n")
        write("includes/rest.php", "<?php\nfunction dx_rest_boot() {\n  return 2;\n}\n")
        sh("add", "-A")
        sh("commit", "-qm", "change")
        got = impact_map(d, "", base, "HEAD")
        ok("a change: the files its diff changes", "`includes/rest.php`" in got and "`app.php`" in got)
        ok("a change: who calls the function its hunk names", "- `dx_rest_boot` (a name): `lib/boot.php`" in got)
        ok("no kind: no surface section", "Public surface" not in impact_map(d, spec, kind=""))
        ok("git that fails: one line, never an error", impact_map(d, spec, "nope", "HEAD").startswith("(The impact map could not be built"))
        ok("a change that touches none fires nothing", on_change(d, base, "HEAD", entries=org) == [])
        mid = git(d, "rev-parse", "HEAD").stdout.strip()
        write(".github/workflows/ci.yml", "on: push\n")
        write("app.php", "<?php\n$id = $_GET['id'];\n")
        sh("add", "-A")
        sh("commit", "-qm", "threat")
        got = on_change(d, mid, "HEAD", "wordpress-plugin")
        ok(f"a change: a workflow it adds, an input a line reads ({got})",
           any(h.startswith("workflow:") for h in got) and any(h.startswith("input:") for h in got) and any(h.startswith("wp-input:") for h in got))
        mid = git(d, "rev-parse", "HEAD").stdout.strip()
        write("docs/auth.md", "The access_token expires; the password is never logged.\n")
        write("README.md", "Set GH_TOKEN and `permissions:` as the docs say.\n")
        write("tests/Unit/AuthTest.php", "<?php\n$_POST['password'] = 'x';\n")
        sh("add", "-A")
        sh("commit", "-qm", "prose")
        ok("a change: docs and declared tests that name a token fire nothing (#974)",
           on_change(d, mid, "HEAD", "wordpress-plugin") == [])
        doc_entry = ({"id": "d", "what": "w", "docs": True}, [], re.compile("access_token"))
        ok("a change: an entry with docs: true reads the docs' lines too",
           on_change(d, mid, "HEAD", entries=[doc_entry]) == ['d: w, "access_token"'])
        write("app.php", "<?php\n$t = $access_token;\n")
        sh("add", "-A")
        sh("commit", "-qm", "code")
        ok("a change: the same word in code fires", any(h.startswith("secret:") for h in on_change(d, mid, "HEAD", "wordpress-plugin")))
        ok("the kind is the repository's", main_kind(d) == "wordpress-plugin")
    ok("a diff's lines with their files, a deleted one by its old name",
       diff_file_lines("diff --git a/x b/x\n--- a/x\n+++ /dev/null\n@@ -1 +0,0 @@\n--- a/y\n"
                       "diff --git a/z b/z\n--- /dev/null\n+++ b/z\n@@ -0,0 +1 @@\n+new\n") == [("x", "-- a/y"), ("z", "new")])
    ok("prose: a docs glob crosses directories, a declared test is one, code is not",
       is_prose("docs/a/b.md", ["*.md"], set()) and is_prose("t/x.php", [], {"t/x.php"}) and not is_prose("src/a.py", ["*.md"], set()))
    ok("the Spec part of an issue body, the PRD left out",
       spec_part("## PRD\n\nThe password page.\n\n### Spec: files\n\n- `a.py`\n") == "### Spec: files\n\n- `a.py`\n" and spec_part("## PRD\n\nx\n") == "")
    late = render({"files": ["src/" + "a" * 90 + f"{i:03d}.py" for i in range(45)], "surface": [], "tests": {}, "callers": [("`n`", ["c.py"])], "kind": ""})
    ok("once a section is cut, no later one goes in, not even its title",
       "Who calls" not in late and "files, 1 line(s) of callers" in late.splitlines()[-1])
    ok("the brief's lines: why, and the Spec's threats as they stand",
       brief_lines("### Spec: files\n\n- x\n\n### Spec: threats\n\n- Tampering: none.\n", ["workflow: w, x"])
       == "Threats required: workflow: w, x\n\nThe Spec's threats section, as it stands:\n\n- Tampering: none.")
    ok("the brief's lines: a Spec with none says so", "has no threats section" in brief_lines("### Spec: files\n\n- x\n", ["w"]))
    ok("the brief's lines: nothing when it does not fire", brief_lines("x", []) == "")
    ok("the brief's lines: a trigger that cannot tell fails closed",
       unknown_lines("bad yaml").startswith("Threats required: the trigger could not tell (bad yaml)"))
    if not fail:
        print("all tests passed")
    return fail


def main_kind(root="."):
    return repo_kind(root)


def main(argv):
    if argv[:1] == ["--test"]:
        return self_test()
    if argv == ["kind"]:
        print(main_kind("."))
        return 0
    if argv[:1] not in (["map"], ["threats"]):
        print(__doc__, file=sys.stderr)
        return 64
    opts = {}
    rest = argv[1:]
    brief = "--brief" in rest
    rest = [a for a in rest if a != "--brief"]
    while rest:
        if rest[0] in ("--spec", "--base", "--head", "--kind", "--repo") and len(rest) > 1:
            opts[rest[0][2:]] = rest[1]
            rest = rest[2:]
        else:
            print(f"impact.py: unknown argument {rest[0]!r}", file=sys.stderr)
            return 64
    spec = ""
    if opts.get("spec"):
        try:
            with open(opts["spec"], encoding="utf-8") as fh:
                spec = fh.read()
        except OSError:
            spec = ""
    if bool(opts.get("base")) != bool(opts.get("head")):
        print("impact.py: --base and --head go together", file=sys.stderr)
        return 64
    if argv[0] == "threats":
        repo = (opts.get("repo") or os.environ.get("GITHUB_REPOSITORY") or "").split("/")[-1]
        try:
            kind = opts.get("kind") if opts.get("kind") is not None else repo_kind(".")
            entries = threat_entries(kind)
            hits = on_text(spec_part(spec), entries=entries) if spec_part(spec) else []
            if opts.get("base"):
                hits += [h for h in on_change(".", opts["base"], opts["head"], kind, entries, repo) if h not in hits]
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as e:
            print(f"impact.py: {e}", file=sys.stderr)
            if brief:
                print(unknown_lines(str(e).splitlines()[0][:200] if str(e) else type(e).__name__))
            return 2
        if hits:
            print(brief_lines(spec, hits) if brief else "\n".join(hits))
        return 1 if hits else 0
    repo = (opts.get("repo") or os.environ.get("GITHUB_REPOSITORY") or "").split("/")[-1]
    print(impact_map(".", spec, opts.get("base", ""), opts.get("head", ""), opts.get("kind"), repo))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
