#!/usr/bin/env python3
"""A security patch on the version in production, on a maintainer's OK (#287).

security-fix.yml writes an advisory's fix in the private repository and
records it on the claim's issue there ("Fix <GHSA> in <repository>"). Once
the advisory is a draft (a maintainer or the triage moved it) and the fix's
checks passed, security-patch.yml takes it through these stages, each one a
label on that issue:

  (none)          start: the fix is applied on the version in production
                  (scripts/production-version.py), with a changelog entry and
                  the markers of the patch, within the limits of its size and
                  paths (`limits`); the repository's checks run on it, and a
                  second model reviews it without the report. All green, the
                  maintainers are told, with the patch's tree, and the issue
                  gets `patch:ready` and the tree in its marker
  patch:ready     publish, once a maintainer (admin or maintain, checked
                  now) added `patch:go` after it was announced
                  (`go_verdict`): the same tree is built again, checked
                  against the announced one, and pushed to security/X.Y.Z
                  in the public repository by dilux-security, whose release
                  workflow releases it (plugin-release-wp.yml); `patch:pushed`
  patch:pushed    finish, once that release exists: the advisory is
                  published with the patched version, an issue in the public
                  repository carries the fix into its default branch, and
                  the claim's issue closes; `patch:released`
  patch:failed    the fix did not apply, broke a limit, failed its checks or
                  its review; a maintainer takes it from there
  patch:not-released  the version in production is not affected: the code
                  the fix changes was written after it (`unreleased`), so
                  no release holds the weakness. The fix goes into the
                  default branch as a pull request a person merges, the
                  advisory is closed unpublished, and the claim's issue
                  closes

Nothing publishes without `patch:go`: a stranger's report never reaches
users on its own. One patch per repository at a time.

  security-patch.py stage    LABELS (comma-separated), MARKER (the issue's
                             patch marker or empty), GO (ok, or why not):
                             prints start|publish|finish|wait|none and why
  security-patch.py go       EVENTS (the issue's timeline, JSON), AT (when it
                             was announced), ROLES (JSON login: role, read
                             live): whether `patch:go` is a maintainer's,
                             added after the announcement; prints ok or why
  security-patch.py limits   PATCH (the fix, as git format-patch wrote it):
                             what it breaks of the policy's limits, one per
                             line; exit 1 when any
  security-patch.py reviewer the model of the second review, from the policy
  security-patch.py marker   VERSION, TREE, AT: the marker line
  security-patch.py entry    README, VERSION_TEXT: the readme with a held
                             changelog entry for the patch on top
  security-patch.py unreleased  ROOT (a clone of the public repository with
                             its whole history and tags, the default branch
                             checked out), PATCH, TAG (the version in
                             production): whether the fix only changes code
                             written after TAG, as JSON {unreleased, why};
                             exit 0 when it does, 1 when not
  security-patch.py release  ROOT (the public repository's checkout),
                             VERSION: its kind's release command for that
                             version and its caller's slug, as JSON
                             {kind, slug, argv}
  security-patch.py --test
"""
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import fnmatch

MARK = re.compile(r"<!-- dx-security-patch: version=(\d+\.\d+\.\d+) tree=([0-9a-f]{40}) at=(\S+) -->")
STAGES = ("patch:ready", "patch:go", "patch:pushed", "patch:released", "patch:failed")
# What a security fix may be, unless the organisation's policy says less or
# more: a few files, a few hundred lines, and nothing that changes how the
# project is built, released or checked.
LIMITS = {"max-files": 10, "max-lines": 400,
          "forbidden": [".github/*", "*composer.json", "*composer.lock", "*package.json", "*package-lock.json",
                        "*yarn.lock", "*pnpm-lock.yaml", "*makefile", "*.mk", "*.sh", "*.distignore", "*phpunit.xml*",
                        "*phpcs.xml*", "*phpstan*.neon*", "*psalm.xml*", "*tests/bootstrap.php"]}
REVIEWER = "claude-sonnet-5-5"


def policy_of(policy):
    sp = (policy or {}).get("security-patch") or {}
    return {**LIMITS, **{k: v for k, v in sp.items() if k in LIMITS}}, sp.get("reviewer-model", REVIEWER)


def marker(version, tree, at):
    return f"<!-- dx-security-patch: version={version} tree={tree} at={at} -->"


def parse(text):
    m = MARK.search(text or "")
    return {"version": m.group(1), "tree": m.group(2), "at": m.group(3)} if m else None


def when(iso):
    return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))


def go_verdict(events, at, roles):
    """("ok", "") when the last `patch:go` on the issue was added by a
    maintainer (admin or maintain, read live: roles) after the patch was
    announced (at); else ("", why). A label added before the announcement
    approved nothing: the tree it would publish did not exist yet. Pure."""
    added = [e for e in events or [] if e.get("event") == "labeled" and (e.get("label") or {}).get("name") == "patch:go"]
    if not added:
        return "", "no patch:go yet"
    last = max(added, key=lambda e: e.get("created_at", ""))
    who = (last.get("actor") or {}).get("login", "")
    if roles.get(who) not in ("admin", "maintain"):
        return "", f"patch:go was added by {who or 'someone unknown'}, who does not maintain this repository"
    if not at or when(last.get("created_at", "1970-01-01T00:00:00Z")) < when(at):
        return "", "patch:go was added before the patch was announced; add it again"
    return "ok", ""


def stage(labels, mark, go):
    """(act, why) for one claim issue whose fix is recorded and whose
    advisory is a draft (the caller checks both). go: "ok" when patch:go is
    a maintainer's, after the announcement; otherwise why not."""
    labels = set(labels)
    if "patch:not-released" in labels:
        return "none", "no released version holds it; its fix went to the default branch"
    if "patch:failed" in labels or "patch:released" in labels:
        return "none", "done" if "patch:released" in labels else "it failed; a maintainer takes it"
    if "patch:pushed" in labels:
        return "finish", "pushed; finish once its release exists"
    if "patch:ready" in labels:
        if not parse(mark):
            return "wait", "announced, but its marker is missing: a maintainer looks"
        if "patch:go" not in labels:
            return "wait", "waits for a maintainer's patch:go"
        if go != "ok":
            return "wait", go or "patch:go could not be checked"
        return "publish", "a maintainer added patch:go"
    return "start", "a recorded fix on a draft advisory"


def _path(text):
    """A path as git writes it in a patch: a/ or b/ before it, and in double
    quotes with C escapes when it has unusual characters (non-ASCII, a
    quote). /dev/null is no path."""
    text = text.rstrip("\t\n")
    if text.startswith('"') and text.endswith('"'):
        raw = text[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape").encode("latin-1")
        text = raw.decode("utf-8", "replace")
    if text == "/dev/null":
        return ""
    return text[2:] if text[:2] in ("a/", "b/") else text


def changed(patch):
    """{path: changed lines} of a patch as git format-patch writes it: every
    path a change touches (both ends of a rename or a copy; for a change with
    no other name, every way its header can be read, so a forbidden path is
    never missed), and only the lines inside its hunks, counted from their
    headers, on the path the hunk writes."""
    out, paths, target, old, new, seen = {}, [], "", 0, 0, False
    add = lambda p_: (out.setdefault(p_, 0), paths.append(p_) if p_ not in paths else None) if p_ else None
    for line in (patch or "").splitlines():
        if old > 0 or new > 0:
            if line.startswith("-"):
                old -= 1
            elif line.startswith("+"):
                new -= 1
            elif line.startswith("\\"):
                continue
            else:
                old, new = old - 1, new - 1
                continue
            out[target] = out.get(target, 0) + 1
            continue
        if line.startswith("diff --git "):
            seen, paths, target = True, [], ""
            rest = line[len("diff --git "):]
            if rest.startswith('"'):
                end = rest.find('"', 1)
                add(_path(rest[:end + 1]))
                add(_path(rest[end + 2:]))
            else:
                # Every split where " b/" may start the second path.
                i = rest.find(" b/")
                while i != -1:
                    add(_path(rest[i + 1:]))
                    add(_path(rest[:i]))
                    i = rest.find(" b/", i + 1)
            continue
        if not seen:
            continue  # the commit message: no path is named there
        m = re.match(r"^(rename|copy) (from|to) (.+)$", line)
        if m:
            add(_path(m.group(3)))
            if m.group(2) == "to":
                target = _path(m.group(3))
            continue
        m = re.match(r"^(---|\+\+\+) (.+)$", line)
        if m:
            add(_path(m.group(2)))
            if m.group(1) == "+++" and _path(m.group(2)):
                target = _path(m.group(2))
            elif m.group(1) == "---" and not target:
                target = _path(m.group(2))
            continue
        h = re.match(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@", line)
        if h:
            old = int(h.group(1)) if h.group(1) is not None else 1
            new = int(h.group(2)) if h.group(2) is not None else 1
            target = target or (paths[-1] if paths else "")
    return out


def binaries(patch):
    """The paths a patch changes as binary files (`GIT binary patch`, or
    `Binary files ... differ`): no line count bounds them. Pure."""
    out, current = [], ""
    for line in (patch or "").splitlines():
        m = re.match(r"^\+\+\+ (.+)$", line)
        if line.startswith("diff --git "):
            rest = line[len("diff --git "):]
            current = _path(rest[rest.rfind(" b/") + 1:]) if " b/" in rest else rest
        elif m and _path(m.group(1)):
            current = _path(m.group(1))
        elif line.startswith("GIT binary patch") or (line.startswith("Binary files ") and line.endswith(" differ")):
            if current and current not in out:
                out.append(current)
    return out


def limits(patch, rules):
    """What the patch breaks of the limits, one sentence each. Pure."""
    files = changed(patch)
    out = []
    if not files:
        out.append("the patch changes nothing")
    if len(files) > rules["max-files"]:
        out.append(f"it changes {len(files)} files, more than {rules['max-files']}")
    total = sum(files.values())
    if total > rules["max-lines"]:
        out.append(f"it changes {total} lines, more than {rules['max-lines']}")
    for f in binaries(patch):
        out.append(f"it changes {f} as a binary file, which a security fix never carries")
    for f in sorted(files):
        # Case does not matter: make reads makefile and GNUmakefile too.
        hit = next((g for g in rules["forbidden"] if fnmatch.fnmatchcase(f.lower(), g.lower())), None)
        if hit:
            out.append(f"it changes {f}, which a security fix may not touch ({hit})")
    return out


def _trivial(text):
    """A line that says nothing of where it is: blank, or only punctuation
    and comment marks (a brace, ` */`, ` *`)."""
    return not re.search(r"[A-Za-z0-9]", text)


def _norm(text):
    """A line with its whitespace collapsed: a reformat keeps it the same."""
    return " ".join(text.split())


def anchors(patch):
    """[(path, [lines])] for each hunk of a file that already existed: the
    lines that place its change, as text with whitespace collapsed, every
    line it removes and the nearest line on each side of a change that is
    not trivial. A new file has no hunk here; a hunk with no such line has
    an empty list. Pure."""
    out, target, seen, old, new = [], "", False, 0, 0
    before, block, pending, hunk = None, False, False, None

    def mark(text):
        if hunk is not None and text is not None and text not in hunk[1]:
            hunk[1].append(text)

    for line in (patch or "").splitlines():
        if old > 0 or new > 0:
            if line.startswith("\\"):
                continue
            if line[:1] in ("-", "+"):
                if not block:
                    mark(before)
                    block = True
                if line.startswith("-"):
                    old -= 1
                    if not _trivial(line[1:]):
                        mark(_norm(line[1:]))
                else:
                    new -= 1
                pending = True
                continue
            if not _trivial(line[1:]):
                if pending:
                    mark(_norm(line[1:]))
                    pending = False
                before = _norm(line[1:])
            block = False
            old, new = old - 1, new - 1
            continue
        if line.startswith("diff --git "):
            seen, target = True, ""
            continue
        if not seen:
            continue
        m = re.match(r"^--- (.+)$", line)
        if m:
            target = _path(m.group(1))
            continue
        h = re.match(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,(\d+))? @@", line)
        if h:
            old = int(h.group(2)) if h.group(2) is not None else 1
            new = int(h.group(3)) if h.group(3) is not None else 1
            before, block, pending = None, False, False
            hunk = (target, []) if target else None
            if hunk:
                out.append(hunk)
    return out


def held(anchor_list, released_lines, current):
    """(True, why) when no line that places the fix is in the released
    tree, whatever file or indentation it has there, and every hunk has
    one. Only a line found once in the current tree (`current`, a count per
    line) places anything: `return false;` says nothing of where it is.
    Fails closed: a hunk that no such line places, or one such line the
    release already has, is (False, why). Pure."""
    if not anchor_list:
        return False, "the fix changes no line that was already there"
    for path, lines in anchor_list:
        own = [t for t in lines if current.get(t, 0) == 1]
        if not own:
            return False, f"a change of {path} has no line of its own to tell where it is"
        for text in own:
            if text in released_lines:
                return False, f"{path} holds code the fix changes that the release already has"
    return True, ""


def unreleased(root, patch, tag):
    """(True, why) when the version in production does not hold the code
    the fix changes: the fix applies on the default branch as it is, and
    no line that places it (`anchors`) is anywhere in the tag's tree, with
    its whitespace collapsed, so a reformat or a move after the release
    does not hide it. Otherwise (False, why), and a person decides."""
    import subprocess
    import tempfile

    def git(*a):
        return subprocess.run(["git", "-C", root, *a], capture_output=True, text=True, errors="replace")

    with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False, encoding="utf-8") as fh:
        fh.write(patch)
        name = fh.name
    try:
        if git("apply", "--check", name).returncode != 0:
            return False, "the fix does not apply on the default branch either"
    finally:
        os.unlink(name)
    # Every line of every text file, of the release and of the default
    # branch as it is, at once.
    trees = {}
    for rev in (tag, "HEAD"):
        g = git("grep", "-h", "-I", "--no-color", "-e", "", rev)
        if g.returncode not in (0, 1):
            return False, f"{rev} could not be read"
        trees[rev] = [_norm(l) for l in g.stdout.splitlines()]
    current = {}
    for line in trees["HEAD"]:
        current[line] = current.get(line, 0) + 1
    places = anchors(patch)
    ok, why = held(places, set(trees[tag]), current)
    if not ok:
        return False, why.replace("the release", tag)
    # And from the history: each such line was born adding code, never
    # editing what was there (a rename or a rewrite after the release would
    # hide released code from the text alone).
    where = {}
    g = git("grep", "-n", "-I", "--no-color", "-e", "", "HEAD")
    if g.returncode != 0:
        return False, "the default branch could not be read"
    for row in g.stdout.splitlines():
        m = re.match(r"^HEAD:(.+?):(\d+):(.*)$", row)
        if m and current.get(_norm(m.group(3))) == 1:
            where[_norm(m.group(3))] = (m.group(1), int(m.group(2)))
    for path, lines in places:
        for text in (t for t in lines if current.get(t, 0) == 1):
            if text not in where:
                return False, f"{path}: a line the fix changes could not be found on the default branch"
            file_, n = where[text]
            b = git("blame", "--porcelain", "-L", f"{n},{n}", "HEAD", "--", file_)
            m = re.match(r"^([0-9a-f]{40}) (\d+) \d+", b.stdout)
            name = re.search(r"^filename (.+)$", b.stdout, re.M)
            if b.returncode != 0 or not m or not name:
                return False, f"the history of {file_} could not be read"
            # The whole commit, renames paired (-M): a rename that also
            # edits shows its edits, never the file as all new.
            show = git("show", "-M", "--format=", "-U0", "--no-color", m.group(1))
            if show.returncode != 0 or not edit_free(section(show.stdout, name.group(1)), int(m.group(2))):
                return False, f"{path}: a line the fix changes was written by editing older code, which {tag} may hold"
    return True, f"no line the fix changes is in {tag}, and each was written as new code"


def section(diff, path):
    """The part of a whole commit's diff that writes `path` (its new name
    after a rename); "" when none does. Pure."""
    parts = re.split(r"^(?=diff --git )", diff, flags=re.M)
    for part in parts:
        if re.search(r"^\+\+\+ " + re.escape("b/" + path) + r"$", part, re.M):
            return part
    return ""


def edit_free(diff, line):
    """Whether the hunk of a -U0 diff that writes `line` (on its new side)
    only adds lines. Pure."""
    for h in re.finditer(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", diff, re.M):
        removed = int(h.group(1)) if h.group(1) is not None else 1
        start, count = int(h.group(2)), int(h.group(3)) if h.group(3) is not None else 1
        if start <= line < start + count:
            return removed == 0
    return False


def entry(readme, text):
    """The readme with a held entry for the patch on top of its changelog:
    `= Unreleased =`, the line `Unreleased.` and one note. release-markers.sh
    prepare then names it and stamps the markers."""
    lines = readme.split("\n")
    try:
        i = next(k for k, l in enumerate(lines) if l.strip() == "== Changelog ==")
    except StopIteration:
        raise ValueError("the readme has no == Changelog == section")
    note = re.sub(r"\s+", " ", text).strip()[:300] or "Security fix."
    block = ["", "= Unreleased =", "", "Unreleased.", f"* Security: {note}"]
    j = i + 1
    return "\n".join(lines[:j] + block + lines[j:])


def _release_issue():
    import importlib.util
    spec = importlib.util.spec_from_file_location("release_issue", os.path.join(HERE, "release-issue.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def release(root, version):
    """The kind's `prepare` command for VERSION, filled from the
    repository's own release caller (scripts/release-issue.py), and its
    slug: the same command the release pull request runs."""
    ri = _release_issue()
    kind = ri.kind_of(root)
    rel = ri.pack_release(os.path.join(HERE, ".."), kind)
    if not rel:
        raise ValueError(f"the kind {kind or '(none)'} publishes nothing: no security patch")
    inputs = ri.caller_inputs(root, rel["workflow"]) or {}
    if not inputs.get("slug"):
        raise ValueError(f"no job calls {rel['workflow']} with a slug")
    return {"kind": kind, "slug": inputs["slug"], "argv": ri.prepare_argv(rel, inputs, version, os.path.join(HERE, ".."))}


def publish_payload(adv, version, repo=""):
    """The PATCH that publishes the advisory once its patch is released
    (#317): every package it names patched at the version, and a package
    with no vulnerable range given everything before it, since GitHub
    publishes none without one; one naming no package names the
    repository's. Pure."""
    vulns = [v for v in (adv or {}).get("vulnerabilities") or [] if isinstance(v, dict)]
    if not vulns and repo:
        vulns = [{"package": {"ecosystem": "other", "name": repo.split("/")[-1]}}]
    return {"state": "published",
            "vulnerabilities": [{"package": v.get("package"),
                                 "vulnerable_version_range": v.get("vulnerable_version_range") or f"< {version}",
                                 "patched_versions": version,
                                 "vulnerable_functions": v.get("vulnerable_functions") or []} for v in vulns]}


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    adv = {"vulnerabilities": [{"package": {"ecosystem": "other", "name": "x"}, "vulnerable_version_range": None, "patched_versions": None, "vulnerable_functions": []},
                               {"package": {"ecosystem": "other", "name": "y"}, "vulnerable_version_range": ">= 1.0, < 2.1.0", "patched_versions": "2.0.9", "vulnerable_functions": ["f"]}]}
    pub = publish_payload(adv, "2.1.1")
    check("#317 publish: published, every package patched at the patch's version, an empty range filled as everything before it, a range it had kept",
          (pub["state"], [v["patched_versions"] for v in pub["vulnerabilities"]], [v["vulnerable_version_range"] for v in pub["vulnerabilities"]], pub["vulnerabilities"][1]["vulnerable_functions"]),
          ("published", ["2.1.1", "2.1.1"], ["< 2.1.1", ">= 1.0, < 2.1.0"], ["f"]))
    check("#317 publish: an advisory naming no package names the repository's, so it is publishable",
          publish_payload({"vulnerabilities": []}, "0.2.1", "o/r")["vulnerabilities"], [{"package": {"ecosystem": "other", "name": "r"}, "vulnerable_version_range": "< 0.2.1", "patched_versions": "0.2.1", "vulnerable_functions": []}])
    m = marker("2.1.1", "a" * 40, "2026-10-18T06:00:00Z")
    check("marker: reads back", parse("text\n" + m), {"version": "2.1.1", "tree": "a" * 40, "at": "2026-10-18T06:00:00Z"})
    check("stage: nothing yet starts", stage([], "", "")[0], "start")
    check("stage: announced, it waits for patch:go", stage(["patch:ready"], m, "")[0:2], ("wait", "waits for a maintainer's patch:go"))
    check("stage: patch:go from a maintainer publishes", stage(["patch:ready", "patch:go"], m, "ok")[0], "publish")
    check("stage: patch:go that is not a maintainer's waits, saying why", stage(["patch:ready", "patch:go"], m, "added by x")[0:2], ("wait", "added by x"))
    check("stage: no time passing publishes anything", stage(["patch:ready"], m, "ok")[0], "wait")
    check("stage: pushed finishes", stage(["patch:pushed"], m, "")[0], "finish")
    check("stage: released or failed does nothing", [stage([s_], m, "ok")[0] for s_ in ("patch:released", "patch:failed")], ["none", "none"])
    check("stage: announced without its marker waits for a person", stage(["patch:ready", "patch:go"], "", "ok")[0], "wait")
    check("stage: not released does nothing more", stage(["patch:not-released"], "", "")[0], "none")
    # Unreleased: which lines place a fix, and whether the tag holds them.
    hunk = ("diff --git a/f.php b/f.php\n--- a/f.php\n+++ b/f.php\n@@ -2,5 +2,6 @@ x\n"
            " function old() {}\n \n function reset() {\n-\tdelete();\n+\tif ( ok() ) {\n+\t\tdelete();\n+\t}\n }\n")
    check("unreleased: the lines that place a change are the nearest real ones and the removed ones, not braces or blanks, whitespace collapsed",
          anchors(hunk), [("f.php", ["function reset() {", "delete();"])])
    check("unreleased: a new file has no hunk to place", anchors("diff --git a/n.php b/n.php\n--- /dev/null\n+++ b/n.php\n@@ -0,0 +1,2 @@\n+a\n+b\n"), [])
    check("unreleased: a hunk with only braces around it has nothing to place it, and fails closed",
          held([("f.php", ["x();"]), ("f.php", [])], set(), {"x();": 1}), (False, "a change of f.php has no line of its own to tell where it is"))
    check("unreleased: one line of its own the release has, even moved or reindented, is enough to call it released",
          (held([("f.php", ["a();", "b();"])], {"b();"}, {"a();": 1, "b();": 1})[0], held([("f.php", ["a();"])], {"c();"}, {"a();": 1})[0]), (False, True))
    check("unreleased: a line found more than once now places nothing, released or not; with nothing else, it fails closed",
          (held([("f.php", ["return false;", "a();"])], {"return false;"}, {"return false;": 3, "a();": 1})[0],
           held([("f.php", ["return false;"])], set(), {"return false;": 3})[0]), (True, False))
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
        g = lambda *a: subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *a], check=True, capture_output=True, env=env)
        g("init", "-q")
        with open(os.path.join(d, "f.php"), "w") as fh:
            fh.write("<?php\nfunction old() { return 1; }\n")
        g("add", "-A")
        g("commit", "-q", "-m", "one")
        g("tag", "1.0.0")
        with open(os.path.join(d, "f.php"), "a") as fh:
            fh.write("\nfunction reset() {\n\tdelete();\n}\n")
        g("commit", "-q", "-am", "two")
        new_fix = ("diff --git a/f.php b/f.php\n--- a/f.php\n+++ b/f.php\n@@ -3,4 +3,6 @@ function old() { return 1; }\n"
                   " \n function reset() {\n-\tdelete();\n+\tif ( ok() ) {\n+\t\tdelete();\n+\t}\n }\n")
        old_fix = ("diff --git a/f.php b/f.php\n--- a/f.php\n+++ b/f.php\n@@ -1,3 +1,3 @@\n <?php\n-function old() { return 1; }\n+function old() { return 2; }\n \n")
        stale = new_fix.replace("-\tdelete();", "-\tdelete_all();")
        check("unreleased: a fix of code written after the tag is not in production",
              unreleased(d, new_fix, "1.0.0")[0], True)
        check("unreleased: a fix of code the tag holds is in production",
              unreleased(d, old_fix, "1.0.0"), (False, "f.php holds code the fix changes that 1.0.0 already has"))
        # The weakness released in 1.0.0, then reformatted and moved to another
        # file after it: the fix of the new file is still a fix of released code.
        g("checkout", "-q", "-b", "moved", "1.0.0")
        with open(os.path.join(d, "f.php"), "a") as fh:
            fh.write("function reset() {\n\tdelete();\n}\n")
        g("commit", "-q", "-am", "released weakness")
        g("tag", "1.1.0")
        g("mv", "f.php", "g.php")
        with open(os.path.join(d, "g.php")) as fh:
            body = fh.read().replace("\tdelete();", "    delete( );").replace("delete( );", "delete();")
        with open(os.path.join(d, "g.php"), "w") as fh:
            fh.write(body)
        g("commit", "-q", "-am", "moved and reindented")
        moved_fix = ("diff --git a/g.php b/g.php\n--- a/g.php\n+++ b/g.php\n@@ -3,3 +3,5 @@ function old() { return 1; }\n"
                     " function reset() {\n-    delete();\n+    if ( ok() ) {\n+        delete();\n+    }\n }\n")
        check("unreleased: a released weakness moved to another file and reindented is still released (fails closed)",
              unreleased(d, moved_fix, "1.1.0"), (False, "g.php holds code the fix changes that 1.1.0 already has"))
        with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False) as fh:
            fh.write(new_fix)
        g("checkout", "-q", "master" if "master" in g("branch").stdout.decode() else "main")
        rc = subprocess.run([sys.executable, __file__, "unreleased"], env={**env, "ROOT": d, "PATCH": fh.name, "TAG": "1.0.0"}, capture_output=True, text=True)
        os.unlink(fh.name)
        check("unreleased: the command exits 0 with its JSON when no release holds it",
              (rc.returncode, json.loads(rc.stdout or "{}").get("unreleased")), (0, True))
        with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False) as fh:
            fh.write(old_fix)
        rc = subprocess.run([sys.executable, __file__, "unreleased"], env={**env, "ROOT": d, "PATCH": fh.name, "TAG": "1.0.0"}, capture_output=True, text=True)
        os.unlink(fh.name)
        check("unreleased: the command exits 1 when the release holds it", (rc.returncode, json.loads(rc.stdout or "{}").get("unreleased")), (1, False))
        check("unreleased: a tag that does not exist cannot be read, and is no answer", unreleased(d, new_fix, "9.9.9")[0], False)
        # Released as wipe(), then renamed and rewritten in substance: no line
        # of the fix is in the release, but it was written by editing it.
        g("checkout", "-q", "-b", "renamed", "1.0.0")
        with open(os.path.join(d, "f.php"), "a") as fh:
            fh.write("\nfunction reset_v1() {\n\twipe_it();\n}\n")
        g("commit", "-q", "-am", "released as reset_v1")
        g("tag", "1.2.0")
        with open(os.path.join(d, "f.php")) as fh:
            body = fh.read().replace("function reset_v1() {\n\twipe_it();", "function reset() {\n\tdelete();")
        with open(os.path.join(d, "f.php"), "w") as fh:
            fh.write(body)
        g("commit", "-q", "-am", "renamed")
        check("unreleased: code released and then rewritten in substance is not taken for new (fails closed)",
              unreleased(d, new_fix, "1.2.0"), (False, "f.php: a line the fix changes was written by editing older code, which 1.2.0 may hold"))
        # Released, then renamed to another file and edited in the same commit.
        g("checkout", "-q", "-b", "renamed-edited", "1.2.0")
        g("mv", "f.php", "h.php")
        with open(os.path.join(d, "h.php")) as fh:
            body = fh.read().replace("function reset_v1() {\n\twipe_it();", "function reset() {\n\tdelete();")
        with open(os.path.join(d, "h.php"), "w") as fh:
            fh.write(body)
        g("commit", "-q", "-am", "moved and rewritten at once")
        check("unreleased: a rename and an edit in one commit is an edit, not new code (fails closed)",
              unreleased(d, new_fix.replace("f.php", "h.php"), "1.2.0")[0], False)
        # A patch with two hunks: one on new code, one on code the release has.
        g("checkout", "-q", "-b", "mixed", "1.0.0")
        with open(os.path.join(d, "f.php"), "a") as fh:
            fh.write("\n// one\n// two\n// three\n// four\n\nfunction reset() {\n\tdelete();\n}\n")
        g("commit", "-q", "-am", "new reset")
        with open(os.path.join(d, "f.php")) as fh:
            body = fh.read()
        with open(os.path.join(d, "f.php"), "w") as fh:
            fh.write(body.replace("return 1;", "return 2;").replace("\tdelete();", "\tif ( ok() ) {\n\t\tdelete();\n\t}"))
        mixed = subprocess.run(["git", "-C", d, "diff"], capture_output=True, text=True, env=env).stdout
        g("checkout", "-q", "--", "f.php")
        check("unreleased: a patch of two hunks, one on new code and one on released code, goes to a person",
              (len(anchors(mixed)), unreleased(d, mixed, "1.0.0")), (2, (False, "f.php holds code the fix changes that 1.0.0 already has")))
        check("unreleased: a fix that does not apply on the default branch is no answer",
              unreleased(d, stale, "1.0.0"), (False, "the fix does not apply on the default branch either"))
    check("unreleased: a -U0 hunk that only adds is edit-free, one that replaces is not",
          (edit_free("@@ -4,0 +5,3 @@\n+a\n+b\n+c\n", 6), edit_free("@@ -4,1 +4,2 @@\n-a\n+b\n+c\n", 5), edit_free("@@ -4,0 +5,1 @@\n+a\n", 9)), (True, False, False))
    ev = lambda who, t, name="patch:go", kind="labeled": {"event": kind, "label": {"name": name}, "actor": {"login": who}, "created_at": t}
    roles = {"boss": "admin", "helper": "maintain", "dev": "write", "dilux-bot[bot]": "none"}
    at = "2026-10-18T06:00:00Z"
    check("go: a maintainer's, after the announcement",
          [go_verdict([ev(w, "2026-10-18T07:00:00Z")], at, roles)[0] for w in ("boss", "helper", "dev", "dilux-bot[bot]", "stranger")], ["ok", "ok", "", "", ""])
    check("go: before the announcement approves nothing", go_verdict([ev("boss", "2026-10-18T05:00:00Z")], at, roles), ("", "patch:go was added before the patch was announced; add it again"))
    check("go: the last one counts, other labels do not",
          (go_verdict([ev("boss", "2026-10-18T07:00:00Z"), ev("dev", "2026-10-18T08:00:00Z")], at, roles)[0], go_verdict([ev("boss", "2026-10-18T07:00:00Z", "patch:ready")], at, roles)[0]), ("", ""))
    fp = lambda *files: "".join(f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n@@ -1 +1 @@\n-old\n+new\n" for f in files)
    rules = policy_of({})[0]
    check("limits: a small fix passes", limits(fp("includes/a.php", "tests/Unit/ATest.php"), rules), [])
    check("limits: too many files, a forbidden path", limits(fp(*[f"f{i}.php" for i in range(11)]) + fp(".github/workflows/x.yml", "composer.json"), rules)[:3],
          ["it changes 13 files, more than 10", "it changes .github/workflows/x.yml, which a security fix may not touch (.github/*)", "it changes composer.json, which a security fix may not touch (*composer.json)"])
    tricky = ('diff --git a/my file.php b/my file.php\n--- a/my file.php\n+++ b/my file.php\n@@ -1 +1 @@\n-old\n+new\n'
              'diff --git "a/a\\303\\261o/Makefile" "b/a\\303\\261o/Makefile"\n--- "a/a\\303\\261o/Makefile"\n+++ "b/a\\303\\261o/Makefile"\n@@ -1 +1 @@\n-x\n+y\n'
              'diff --git a/Makefile b/src/Moved.php\nsimilarity index 100%\nrename from Makefile\nrename to src/Moved.php\n'
              '-- \n2.43.0\n\n')
    got = changed(tricky)
    check("changed: spaces, quoted non-ASCII paths, both ends of a rename, only hunk lines (not format-patch's trailer)",
          (got.get("my file.php"), got.get("año/Makefile"), "Makefile" in got, "src/Moved.php" in got, sum(got.values())), (2, 2, True, True, 4))
    odd = "From x\nSubject: [PATCH] fix\n\n--- not a path\n---\ndiff --git a/.github/a b/c.yml b/.github/a b/c.yml\nold mode 100644\nnew mode 100755\n"
    check("changed: no path from the commit message; a header with ' b/' read every way",
          ("not a path" in changed(odd), ".github/a b/c.yml" in changed(odd)), (False, True))
    ren = "diff --git a/old.php b/new.php\nsimilarity index 90%\nrename from old.php\nrename to new.php\n--- a/old.php\n+++ b/new.php\n@@ -1 +1 @@\n-a\n+b\n"
    check("changed: a renamed file's lines go to its new path", (changed(ren)["new.php"], changed(ren)["old.php"]), (2, 0))
    binpatch = "diff --git a/x.phar b/x.phar\nnew file mode 100644\nindex 0000000..abc\nGIT binary patch\nliteral 10\nzcmV?d00001\n\nliteral 0\nHcmV?d00001\n\n"
    check("limits: a binary file is never carried (#287 review)", [l for l in limits(binpatch, rules) if "binary" in l], ["it changes x.phar as a binary file, which a security fix never carries"])
    check("limits: case does not matter, and every file that steers the checks is forbidden",
          [bool(limits(fp(f), rules)) for f in ("makefile", "GNUmakefile", "build/rules.mk", "phpstan.neon.dist", "psalm.xml", "tests/bootstrap.php", "includes/fix.php")],
          [True, True, True, True, True, True, False])
    check("limits: a forbidden path is caught when quoted or renamed away",
          [l for l in limits(tricky, rules) if "may not touch" in l], ["it changes Makefile, which a security fix may not touch (*makefile)", "it changes año/Makefile, which a security fix may not touch (*makefile)"])
    check("limits: too many lines, and an empty patch", (limits("diff --git a/a.php b/a.php\n--- a/a.php\n+++ b/a.php\n@@ -1 +1,402 @@\n-old\n" + "+x\n" * 402, rules), limits("", rules)), (["it changes 403 lines, more than 400"], ["the patch changes nothing"]))
    check("policy: the organisation narrows the limits and names the reviewer",
          policy_of({"security-patch": {"max-files": 3, "reviewer-model": "claude-opus-5-5", "nonsense": 1}}), ({**LIMITS, "max-files": 3}, "claude-opus-5-5"))
    readme = "=== X ===\nStable tag: 2.1.0\n\n== Changelog ==\n\n= 2.1.0 =\n\n* Old.\n"
    got = entry(readme, "Escape the title  in the list.\nMore")
    check("entry: a held entry on top of the changelog, the old one kept",
          (got.index("= Unreleased =") < got.index("= 2.1.0 ="), "\nUnreleased.\n" in got, "* Security: Escape the title in the list. More" in got, got.endswith("* Old.\n")), (True, True, True, True))
    try:
        entry("no changelog", "x")
        check("entry: a readme without a changelog fails", "no error", "an error")
    except ValueError:
        check("entry: a readme without a changelog fails", True, True)
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, ".github", "workflows"))
        open(os.path.join(root, ".github", "review-policy.yml"), "w").write("kind: wordpress-plugin\n")
        open(os.path.join(root, ".github", "workflows", "release.yml"), "w").write(
            "jobs:\n  release:\n    uses: DiluxOne/.github/.github/workflows/plugin-release-wp.yml@v5\n    with:\n      slug: diluxone-x\n      version-constant: DX_VERSION\n")
        r = release(root, "2.1.1")
        check("release: the kind, the caller's slug and the release command for the version",
              (r["kind"], r["slug"], "release-markers.sh" in r["argv"][1], "2.1.1" in r["argv"], "diluxone-x.php" in r["argv"], "DX_VERSION" in r["argv"]),
              ("wordpress-plugin", "diluxone-x", True, True, True, True))
    import subprocess
    import tempfile as _tf
    with _tf.NamedTemporaryFile("w", suffix=".patch", delete=False) as fh:
        fh.write(fp("Makefile"))
    cli = lambda *a, **env: subprocess.run([sys.executable, os.path.abspath(__file__), *a], capture_output=True, text=True, env=dict(os.environ, **env))
    lim, rev = cli("limits", PATCH=fh.name), cli("reviewer")
    os.unlink(fh.name)
    check("cli: limits says what breaks and exits 1; reviewer prints the policy's model",
          (lim.returncode, "Makefile" in lim.stdout, rev.returncode, rev.stdout.strip().startswith("claude-")), (1, True, 0, True))
    # The workflow holds to the stages (#287).
    try:
        import yaml
        wf = yaml.safe_load(open(os.path.join(HERE, "..", ".github", "workflows", "security-patch.yml"), encoding="utf-8"))
    except ImportError:
        wf = None
        print("skip the workflow's wiring: PyYAML is not installed here")
    if wf:
        jobs = wf["jobs"]
        run = lambda job, name: next(st for st in jobs[job]["steps"] if st.get("name") == name)
        plan_ = run("plan", "The claims and their stage")["run"]
        check("wiring: the plan reads who added patch:go and their role, and holds one patch per repository",
              ("security-patch.py go" in plan_, "collaborators/$who/permission" in plan_, "another patch of $repo is in progress" in plan_), (True, True, True))
        check("wiring: the build checks the limits before it builds",
              run("build", "The tree on the version in production")["run"].index("security-patch.py\" limits") < run("build", "The tree on the version in production")["run"].index("security-patch-build.sh"), True)
        tree_run = run("build", "The tree on the version in production")["run"]
        check("wiring (#247): the build asks whether the fix is unreleased only when it does not apply, on the default branch, and says each reason",
              (tree_run.index("security-patch-build.sh") < tree_run.index("security-patch.py\" unreleased"), 'git checkout -q -f "$default"' in tree_run,
               all(r in tree_run for r in ("reason=no-production", "reason=unreleased", "reason=does-not-apply"))), (True, True, True))
        fwd = run("act", "Into the default branch")
        check("wiring (#247): an unreleased fix goes to the default branch as a pull request a person merges, and the advisory closes unpublished",
              ("steps.announce.outputs.unreleased" in fwd["if"], "labels[]=security" in fwd["run"], "state=closed" in fwd["run"], "patch:not-released" in fwd["run"],
               "security-patch.py publish" in fwd["run"], fwd["run"].index("unset PRIVATE_KEY BOT_KEY") < fwd["run"].index("git clone")),
              (True, True, True, True, False, True))
        rv = jobs["review"]
        rv_step = next(st for st in rv["steps"] if "claude-code-action" in str(st.get("uses", "")))
        check("wiring: the second review has no shell, no key, and another model",
              ("Bash" in rv_step["with"]["claude_args"], "PRIVATE_KEY" in json.dumps(rv), "needs.plan.outputs.reviewer" in rv_step["with"]["claude_args"]), (False, False, True))
        pub = run("act", "Publish")
        check("wiring: publish pushes with dilux-security only, the announced tree, approved again last",
              ("DILUX_SECURITY_PRIVATE_KEY" in pub["env"]["PRIVATE_KEY"], "DILUX_BOT" in json.dumps(pub["env"]), '"$tree" = "$ANNOUNCED"' in pub["run"],
               pub["run"].index("security-patch.py\" go") < pub["run"].index("api-commit.py"), pub["run"].index("unset PRIVATE_KEY") < pub["run"].index("security-patch-build.sh")),
              (True, False, True, True, True))
        fin = run("act", "Finish")
        check("wiring: the advisory is published with dilux-security's key", "DILUX_SECURITY_PRIVATE_KEY" in fin["env"]["PRIVATE_KEY"], True)
        check("wiring (#317): the advisory's PATCH comes from publish_payload, and the closing comment names the carry once",
              ("security-patch.py publish" in fin["run"], "${pr_url:-" in fin["run"], "VERSION" in fin["env"] and "REPO" in fin["env"]), (True, False, True))
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv == ["stage"]:
        labels = [l for l in os.environ.get("LABELS", "").split(",") if l]
        act, why = stage(labels, os.environ.get("MARKER", ""), os.environ.get("GO", ""))
        print(json.dumps({"act": act, "why": why}))
        return 0
    if argv == ["go"]:
        ok, why = go_verdict(json.loads(os.environ.get("EVENTS") or "[]"), os.environ.get("AT", ""), json.loads(os.environ.get("ROLES") or "{}"))
        print(ok or why)
        return 0
    if argv in (["limits"], ["reviewer"]):
        import yaml
        with open(os.path.join(HERE, "..", "policy", "autonomy.yml"), encoding="utf-8") as fh:
            rules, model = policy_of(yaml.safe_load(fh))
        if argv == ["reviewer"]:
            print(model)
            return 0
        with open(os.environ["PATCH"], encoding="utf-8", errors="replace") as fh:
            broken = limits(fh.read(), rules)
        for b_ in broken:
            print(b_)
        return 1 if broken else 0
    if argv == ["marker"]:
        print(marker(os.environ["VERSION"], os.environ["TREE"], os.environ["AT"]))
        return 0
    if argv == ["entry"]:
        with open(os.environ["README"], encoding="utf-8") as fh:
            text = entry(fh.read(), os.environ.get("VERSION_TEXT", ""))
        with open(os.environ["README"], "w", encoding="utf-8") as fh:
            fh.write(text)
        return 0
    if argv == ["publish"]:
        # ADVISORY (the advisory's JSON), VERSION, REPO: the PATCH to send.
        with open(os.environ["ADVISORY"], encoding="utf-8") as fh:
            print(json.dumps(publish_payload(json.load(fh), os.environ["VERSION"], os.environ.get("REPO", ""))))
        return 0
    if argv == ["unreleased"]:
        with open(os.environ["PATCH"], encoding="utf-8", errors="replace") as fh:
            ok, why = unreleased(os.environ["ROOT"], fh.read(), os.environ["TAG"])
        print(json.dumps({"unreleased": ok, "why": why}))
        return 0 if ok else 1
    if argv == ["release"]:
        print(json.dumps(release(os.environ["ROOT"], os.environ["VERSION"])))
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
