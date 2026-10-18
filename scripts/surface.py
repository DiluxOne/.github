#!/usr/bin/env python3
"""What a pull request that is not a feature must not carry in (#144).

An accepted Bug or Docs issue lets a `fix` or `docs` pull request through
the accepted-issue gate; this keeps it from adding functionality nobody
accepted. scripts/conventions.sh calls it for an author who is not trusted,
on a pull request whose type is not `feat` (and has no `!`); bots and
trusted authors are never checked. It reads only git objects (the diff and
the files at the merge base and at the head): nothing of the pull request
is run, so it is safe on a fork's pull request, with no secret.

What counts lives in the kind's pack, as data: kinds/<kind>/surface.yml.

  docs-paths  globs (shell `case` patterns: `*` crosses directories) a
              `docs` pull request may change, added to the organisation's
              own list (`docs-paths:` in policy/review-policy.default.yml,
              which is all a repository with no kind gets)
  files       globs (`**` crosses directories, `*` does not) of the files
              the surface is read in; `exclude` the ones never read
  surface     the entries: `id`, `what` (how the message names it),
              `pattern` (a Python regular expression over a whole file, so a
              call may span lines), optionally `files` of its own, and
              `fixtures` (`fail` and `pass`, each `{base, head, path}`; base
              empty means the file is new)

An entry whose pattern has a `name` group is new when that name (a quoted
literal, compared without its quotes, or the expression as written,
whitespace aside) appears nowhere in the base's files of the entry: a hook
moved, or fired a second time, is not new. An entry without one is new when
the changed files hold more matches at the head than at the base: a call
moved from one file to another, or changed in place, is not new.

Security-sensitive code (#287) is another list in the same pack,
`sensitive`: entries (`id`, `what`, `pattern` over one line, `when`: changed,
the default, for a line added or removed, or removed, for one that only
weakens when it goes; not `on`, which YAML reads as true, and `fixtures`) a change may not touch without a
person merging it, whatever its issue's Type: what a line the diff adds or
removes matches. It is read by the auto-merge decision, never by the
accepted-issue gate.

  surface.py --sensitive KIND BASE HEAD print the sensitive code the diff
                                        touches (exit 1), nothing (exit 0);
                                        2 when it cannot tell
  surface.py --docs-paths [KIND]        print the docs globs, one per line
  surface.py --check KIND BASE HEAD     print what the diff adds (exit 1),
                                        nothing (exit 0); 2 when it cannot tell
  surface.py --test                     every pack's fixtures, and the
                                        workflow that runs it (C5)
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from policy import CENTRAL, KIND_RE, glob_to_regex, load_yaml  # noqa: E402

DEFAULT_POLICY = os.path.join(CENTRAL, "policy", "review-policy.default.yml")
MAX_BYTES = 2_000_000  # a file larger than this is not code anyone reads


def pack_file(kind):
    return os.path.join(CENTRAL, "kinds", kind, "surface.yml")


def load_pack(kind):
    """The kind's surface.yml as a dict ({} when the kind brings none)."""
    if not kind:
        return {}
    if not KIND_RE.fullmatch(kind) or not os.path.isdir(os.path.join(CENTRAL, "kinds", kind)):
        raise ValueError(f"kind '{kind}' has no pack in kinds/")
    return load_yaml(pack_file(kind)) or {}


def docs_paths(kind):
    org = load_yaml(DEFAULT_POLICY).get("docs-paths") or []
    return list(org) + list(load_pack(kind).get("docs-paths") or [])


def git(*args, data=None):
    return subprocess.run(["git", *args], check=True, capture_output=True, input=data).stdout


def read_blobs(rev, paths, strict=False):
    """{path: text} of the files that exist at rev, via one cat-file process.
    strict (the files the diff changes): a file it cannot read, too large or
    with a newline in its path, is an error, never skipped in silence."""
    odd = [p for p in paths if "\n" in p]  # cat-file reads one path per line
    if odd and strict:
        raise ValueError(f"a changed path holds a newline: {odd[0]!r}")
    paths = [p for p in paths if "\n" not in p]
    if not paths:
        return {}
    out = git("cat-file", "--batch", data="".join(f"{rev}:{p}\n" for p in paths).encode())
    blobs, i = {}, 0
    for p in paths:
        nl = out.index(b"\n", i)
        header = out[i:nl].split()
        i = nl + 1
        if header[-1] == b"missing":
            continue
        size = int(header[2])
        if header[1] == b"blob" and size <= MAX_BYTES:
            blobs[p] = out[i:i + size].decode("utf-8", "replace")
        elif header[1] == b"blob" and strict:
            raise ValueError(f"{p} is {size} bytes, more than this check reads ({MAX_BYTES})")
        i += size + 1
    return blobs


def selector(include, exclude):
    inc = [glob_to_regex(g) for g in include]
    exc = [glob_to_regex(g) for g in exclude]
    return lambda p: any(r.match(p) for r in inc) and not any(r.match(p) for r in exc)


def squash(text):
    return re.sub(r"\s+", "", text)


def literal(name):
    """The inner text of a quoted literal, or None."""
    if len(name) >= 2 and name[0] == name[-1] and name[0] in "'\"":
        return name[1:-1]
    return None


def compile_entry(entry):
    try:
        return re.compile(entry["pattern"])
    except (KeyError, re.error) as e:
        raise ValueError(f"surface entry {entry.get('id', '?')}: no usable pattern ({e})")


def findings(pack, changed, base_files, head_files, base_corpus):
    """What the head adds, as (what, path, name) triples.

    changed: the paths the diff touches; base_files/head_files: their text
    at each side; base_corpus(select): the whitespace-free text of every
    base file the selector takes."""
    found = []
    default_files = pack.get("files") or []
    exclude = pack.get("exclude") or []
    for entry in pack.get("surface") or []:
        rx = compile_entry(entry)
        take = selector(entry.get("files") or default_files, exclude)
        paths = [p for p in changed if take(p)]
        if not paths:
            continue
        if "name" in rx.groupindex:
            corpus = None
            for p in paths:
                if p not in head_files:
                    continue
                for m in rx.finditer(head_files[p]):
                    raw = squash(m.group("name"))
                    if corpus is None:
                        corpus = base_corpus(take)
                    inner = literal(raw)
                    known = (f"'{inner}'" in corpus or f'"{inner}"' in corpus) if inner is not None else raw in corpus
                    if not known and (entry["what"], p, raw) not in found:
                        found.append((entry["what"], p, raw))
        else:
            before = sum(len(rx.findall(base_files[p])) for p in paths if p in base_files)
            after = {p: len(rx.findall(head_files[p])) for p in paths if p in head_files}
            if sum(after.values()) > before:
                for p, n in after.items():
                    if n > len(rx.findall(base_files.get(p, ""))):
                        found.append((entry["what"], p, ""))
    return found


def check(kind, base, head):
    pack = load_pack(kind)
    if not pack.get("surface"):
        return []
    mb = git("merge-base", base, head).decode().strip()
    takes = [selector(e.get("files") or pack.get("files") or [], pack.get("exclude") or []) for e in pack["surface"]]
    changed = [p for p in git("diff", "--no-renames", "--name-only", "-z", mb, head).decode().split("\0") if p and any(t(p) for t in takes)]
    base_files, head_files = read_blobs(mb, changed, strict=True), read_blobs(head, changed, strict=True)
    cache = {}

    def base_corpus(take):
        key = id(take)
        if key not in cache:
            tree = [p for p in git("ls-tree", "-r", "-z", "--name-only", mb).decode().split("\0") if p and take(p)]
            cache[key] = squash("\n".join(read_blobs(mb, tree).values()))
        return cache[key]

    return findings(pack, changed, base_files, head_files, base_corpus)


def touched_lines(base_text, head_text):
    """(removed, added): the lines the change takes out and puts in. Pure."""
    import difflib
    removed, added = [], []
    for line in difflib.ndiff((base_text or "").splitlines(), (head_text or "").splitlines()):
        if line.startswith("- "):
            removed.append(line[2:])
        elif line.startswith("+ "):
            added.append(line[2:])
    return removed, added


def sensitive_findings(pack, changed, base_files, head_files):
    """The sensitive code the change touches, as (what, path, line) triples:
    a line added or removed that an entry's pattern matches (only a removed
    one for an entry `when: removed`)."""
    found = []
    default_files = pack.get("files") or []
    exclude = pack.get("exclude") or []
    for entry in pack.get("sensitive") or []:
        rx = compile_entry(entry)
        take = selector(entry.get("files") or default_files, exclude)
        for p in changed:
            if not take(p):
                continue
            removed, added = touched_lines(base_files.get(p), head_files.get(p))
            lines = removed if entry.get("when") == "removed" else removed + added
            hit = next((l for l in lines if rx.search(l)), None)
            if hit is not None:
                found.append((entry["what"], p, hit.strip()[:80]))
    return found


def check_sensitive(kind, base, head):
    pack = load_pack(kind)
    if not pack.get("sensitive"):
        return []
    mb = git("merge-base", base, head).decode().strip()
    takes = [selector(e.get("files") or pack.get("files") or [], pack.get("exclude") or []) for e in pack["sensitive"]]
    changed = [p for p in git("diff", "--no-renames", "--name-only", "-z", mb, head).decode().split("\0") if p and any(t(p) for t in takes)]
    return sensitive_findings(pack, changed, read_blobs(mb, changed, strict=True), read_blobs(head, changed, strict=True))


def describe(found):
    return [f"{what} ({path}{': ' + name if name else ''})" for what, path, name in found]


# --- self-test ---------------------------------------------------------------

def scratch_findings(pack, files):
    """findings() over in-memory files: {path: (base text or None, head text or None)}."""
    changed = [p for p, (b, h) in files.items() if b != h]
    base_files = {p: b for p, (b, h) in files.items() if b is not None}
    head_files = {p: h for p, (b, h) in files.items() if h is not None}
    return findings(pack, changed, base_files, head_files,
                    lambda take: squash("\n".join(t for p, t in base_files.items() if take(p))))


def default_path(pack, entry):
    glob = (entry.get("files") or pack.get("files") or ["fixture"])[0]
    return "includes/" + glob.split("/")[-1].replace("*", "fixture")


def fixture_files(pack, entry, fx):
    """A fixture: the head of one new file (a string), {base, head, path} for
    one file, or {files: {path: {base, head}}} for several; a file with no
    base is new, one with no head is deleted, and one with the same base and
    head is unchanged (only the base's other files say what exists)."""
    if isinstance(fx, str):
        fx = {"head": fx}
    if "files" in fx:
        return {p: ((v or {}).get("base"), (v or {}).get("head")) for p, v in fx["files"].items()}
    return {fx.get("path") or default_path(pack, entry): (fx.get("base"), fx.get("head"))}


def self_test():
    fail = 0

    def ok(name, cond):
        nonlocal fail
        print(("ok   " if cond else "FAIL ") + name)
        fail |= not cond

    kinds_dir = os.path.join(CENTRAL, "kinds")
    for kind in sorted(os.listdir(kinds_dir)):
        if not os.path.isfile(pack_file(kind)):
            continue
        pack = load_pack(kind)
        ok(f"{kind}: docs-paths is a list", isinstance(pack.get("docs-paths", []), list))
        for entry in pack.get("surface") or []:
            eid = entry.get("id", "?")
            fx = entry.get("fixtures") or {}
            ok(f"{kind}/{eid}: has what, a pattern, and fail and pass fixtures",
               bool(entry.get("what")) and bool(entry.get("pattern")) and bool(fx.get("fail")) and bool(fx.get("pass")))
            one = dict(pack, surface=[entry])
            for i, f in enumerate(fx.get("fail") or []):
                ok(f"{kind}/{eid}: fail fixture {i + 1} is found", bool(scratch_findings(one, fixture_files(pack, entry, f))))
            for i, f in enumerate(fx.get("pass") or []):
                got = scratch_findings(one, fixture_files(pack, entry, f))
                ok(f"{kind}/{eid}: pass fixture {i + 1} is not" + (f" (found {describe(got)})" if got else ""), not got)
        for entry in pack.get("sensitive") or []:
            eid = entry.get("id", "?")
            fx = entry.get("fixtures") or {}
            ok(f"{kind}/sensitive/{eid}: has what, a pattern, a `when` it knows, and fail and pass fixtures",
               bool(entry.get("what")) and bool(entry.get("pattern")) and entry.get("when", "changed") in ("changed", "removed") and bool(fx.get("fail")) and bool(fx.get("pass")))
            one = dict(pack, sensitive=[entry])
            for i, f in enumerate(fx.get("fail") or []):
                files = fixture_files(pack, entry, f)
                ok(f"{kind}/sensitive/{eid}: fail fixture {i + 1} is found",
                   bool(sensitive_findings(one, [p for p, (b, h) in files.items() if b != h], {p: b for p, (b, h) in files.items() if b is not None}, {p: h for p, (b, h) in files.items() if h is not None})))
            for i, f in enumerate(fx.get("pass") or []):
                files = fixture_files(pack, entry, f)
                got = sensitive_findings(one, [p for p, (b, h) in files.items() if b != h], {p: b for p, (b, h) in files.items() if b is not None}, {p: h for p, (b, h) in files.items() if h is not None})
                ok(f"{kind}/sensitive/{eid}: pass fixture {i + 1} is not" + (f" (found {describe(got)})" if got else ""), not got)
    ok("a kind with no pack is refused", _raises(lambda: load_pack("no-such-kind")))
    ok("a kind that is not a name is refused", _raises(lambda: load_pack("../x")))
    ok("the organisation's docs paths are there without a kind", "*.md" in docs_paths(""))
    ok("a kind adds its own", "readme.txt" in docs_paths("wordpress-plugin"))

    # The real thing, on git objects: a scratch repository.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        def sh(*a):
            subprocess.run(["git", "-C", d, *a], check=True, capture_output=True)

        def write(path, text):
            os.makedirs(os.path.dirname(os.path.join(d, path)) or d, exist_ok=True)
            with open(os.path.join(d, path), "w", encoding="utf-8") as fh:
                fh.write(text)

        sh("init", "-q")
        sh("config", "user.email", "t@t")
        sh("config", "user.name", "t")
        sh("config", "commit.gpgsign", "false")
        write("includes/a.php", "<?php\ndo_action( 'dx_saved' );\n")
        write("includes/b.php", "<?php\nfunction b() { return 1; }\n")
        sh("add", "-A")
        sh("commit", "-q", "-m", "chore: base")
        base = git("-C", d, "rev-parse", "HEAD").decode().strip()
        cwd = os.getcwd()
        os.chdir(d)
        try:
            write("includes/b.php", "<?php\nfunction b() { do_action( 'dx_saved' ); return 2; }\n")
            sh("commit", "-qam", "fix: b")
            ok("git: an existing hook fired again is not new", check("wordpress-plugin", base, "HEAD") == [])
            write("includes/b.php", "<?php\nadd_action( 'rest_api_init', function () {\n  register_rest_route( 'dx/v1', '/x', array() );\n} );\n")
            sh("commit", "-qam", "fix: b")
            got = describe(check("wordpress-plugin", base, "HEAD"))
            ok(f"git: a REST route is found ({got})", any("REST route" in g and "includes/b.php" in g for g in got))
            sh("checkout", "-q", "-b", "side", base)
            write("includes/c.php", "<?php\ndo_action( 'dx_saved' );\n")
            os.remove(os.path.join(d, "includes/a.php"))
            sh("add", "-A")
            sh("commit", "-qm", "refactor: move")
            ok("git: a hook moved to a new file is not new", check("wordpress-plugin", base, "HEAD") == [])
            ok("git: no kind, nothing checked", check("", base, "HEAD") == [])
            write("includes/big.php", "<?php\n" + "//" * (MAX_BYTES // 2) + "\n")
            sh("add", "-A")
            sh("commit", "-qm", "fix: big")
            ok("git: a changed file too large to read cannot be told apart, never skipped", _raises(lambda: check("wordpress-plugin", base, "HEAD")))
            sh("rm", "-q", "includes/big.php")
            write("includes/odd\nname.php", "<?php\nregister_rest_route( 'dx/v1', '/odd', array() );\n")
            sh("add", "-A")
            sh("commit", "-qm", "fix: odd")
            ok("git: a changed path with a newline cannot be told apart, never skipped", _raises(lambda: check("wordpress-plugin", base, "HEAD")))
        finally:
            os.chdir(cwd)

    # C5: the check runs in the conventions job, which has no secret and
    # runs only the organisation's scripts, never the pull request's.
    wf = open(os.path.join(CENTRAL, ".github", "workflows", "conventions.yml"), encoding="utf-8").read()
    job = wf.split("\n  conventions:\n", 1)[1].split("\n  docs:\n", 1)[0]
    ok("C5: the conventions job reads no secret", "secrets." not in job)
    runs = re.findall(r"(?:bash|python3) (\S+)", job)
    ok(f"C5: every script it runs is the organisation's ({runs})", bool(runs) and all(r.startswith(".dx-central/") for r in runs))
    ok("C5: the check gets the author's trust and the kind from the base's policy",
       "TRUSTED: ${{ steps.gate.outputs.trusted }}" in job and "KIND: ${{ steps.gate.outputs.kind }}" in job)
    org = open(os.path.join(CENTRAL, ".github", "workflows", "org-pull-request.yml"), encoding="utf-8").read()
    ok("C5: the organisation's pipeline runs it on pull_request (forks included), never pull_request_target",
       "\n  pull_request:\n" in org and "pull_request_target" not in org)
    am = open(os.path.join(CENTRAL, ".github", "workflows", "auto-merge.yml"), encoding="utf-8").read()
    ok("#287: the auto-merge decision reads the sensitive code a change touches, and not knowing counts as touching",
       "surface.py\" --sensitive" in am and 'SENSITIVE="$RUNNER_TEMP/sensitive"' in am and 'echo unknown > "$RUNNER_TEMP/sensitive"' in am)
    if not fail:
        print("all tests passed")
    return fail


def _raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


def main(argv):
    if argv[:1] == ["--test"]:
        return self_test()
    try:
        if argv[:1] == ["--docs-paths"]:
            print("\n".join(docs_paths(argv[1] if len(argv) > 1 else "")))
            return 0
        if argv[:1] == ["--check"] and len(argv) == 4:
            found = describe(check(*argv[1:]))
            print("\n".join(found))
            return 1 if found else 0
        if argv[:1] == ["--sensitive"] and len(argv) == 4:
            found = describe(check_sensitive(*argv[1:]))
            print("\n".join(found))
            return 1 if found else 0
    except (ValueError, subprocess.CalledProcessError, OSError) as e:
        print(f"surface.py: {e}", file=sys.stderr)
        return 2
    print("usage: surface.py --docs-paths [KIND] | --check KIND BASE HEAD | --sensitive KIND BASE HEAD | --test", file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
