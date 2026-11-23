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
  impact.py --test     self-test, on scratch repositories
"""
import importlib.util
import os
import re
import subprocess
import sys

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
        tok = raw.strip().strip(".,;:").removeprefix("./")
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
            if os.path.getsize(os.path.join(root, p)) > surface.MAX_BYTES:
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
    for owner, name, word in names[:NAMES]:
        if name in seen_names:
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
            if key in cut or size + n > limit - reserve:
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
        ok(f"a change: who calls the function its hunk names ({got})", "- `dx_rest_boot` (a name): `lib/boot.php`" in got)
        ok("no kind: no surface section", "Public surface" not in impact_map(d, spec, kind=""))
        ok("git that fails: one line, never an error", impact_map(d, spec, "nope", "HEAD").startswith("(The impact map could not be built"))
    if not fail:
        print("all tests passed")
    return fail


def main(argv):
    if argv[:1] == ["--test"]:
        return self_test()
    if argv[:1] != ["map"]:
        print(__doc__, file=sys.stderr)
        return 64
    opts = {}
    rest = argv[1:]
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
    repo = (opts.get("repo") or os.environ.get("GITHUB_REPOSITORY") or "").split("/")[-1]
    print(impact_map(".", spec, opts.get("base", ""), opts.get("head", ""), opts.get("kind"), repo))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
