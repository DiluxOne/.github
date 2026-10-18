#!/usr/bin/env python3
"""The engine's changelog, from git (#287): every version, what merged in it.

Each version tag vX.Y.Z holds the commits since the version before it on
its own line (the nearest version tag among its ancestors, so a patch on an
older major counts from that major), grouped by their Conventional Commit
type; a breaking change (`!`) is listed first, under its own heading. The
commits on the default branch after the last version are "Unreleased".
Nobody writes it by hand: it is rebuilt before each version is tagged, and
the same notes go into that version's GitHub Release.

    changelog.py build [--next vX.Y.Z]
                                  the whole CHANGELOG.md, to stdout; with
                                  --next, what is unreleased is headed as
                                  that version (the release pull request)
    changelog.py notes vX.Y.Z     one version's notes (its GitHub Release)
    changelog.py --test
"""
import os
import re
import subprocess
import sys

REPO_URL = "https://github.com/DiluxOne/.github"
VERSION = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
SUBJECT = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?: (?P<text>.+)$")
GROUPS = [("feat", "Features"), ("fix", "Fixes"), ("perf", "Performance"), ("refactor", "Refactoring"),
          ("docs", "Documentation"), ("test", "Tests"), ("ci", "CI"), ("build", "Build and dependencies"),
          ("chore", "Maintenance"), ("revert", "Reverts")]


def git(*args, cwd=None):
    out = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:300])
    return out.stdout


def key(tag):
    return tuple(int(x) for x in VERSION.match(tag).groups())


def versions(cwd=None):
    """Every vX.Y.Z tag, oldest first by number (the moving vN tags are not
    versions)."""
    return sorted((t for t in git("tag", "-l", "v*", cwd=cwd).split() if VERSION.match(t)), key=key)


def previous(tag, tags, cwd=None):
    """The version this one counts from: the highest version below it whose
    commit is one of its ancestors; "" for the first."""
    for t in sorted((t for t in tags if key(t) < key(tag)), key=key, reverse=True):
        if subprocess.run(["git", "merge-base", "--is-ancestor", t, tag], cwd=cwd).returncode == 0:
            return t
    return ""


def line(subject):
    """A changelog line for one commit subject, and its group: the text, its
    scope in bold, and its pull request linked. Pure."""
    # Straight quotes in what is published, whatever the commit used.
    subject = subject.replace("«", '"').replace("»", '"')
    m = SUBJECT.match(subject.strip())
    if not m:
        return "other", f"- {subject.strip()}"
    text = re.sub(r"\(#(\d+)\)\s*$", lambda p: f"([#{p.group(1)}]({REPO_URL}/pull/{p.group(1)}))", m.group("text"))
    scope = f"**{m.group('scope')}:** " if m.group("scope") else ""
    group = "breaking" if m.group("bang") else (m.group("type") if m.group("type") in dict(GROUPS) else "other")
    return group, f"- {scope}{text}"


def section(subjects):
    """The grouped lines of a version: breaking first, then by type. Pure."""
    by = {}
    for s in subjects:
        g, l = line(s)
        by.setdefault(g, []).append(l)
    out = []
    for g, title in [("breaking", "Breaking changes")] + GROUPS + [("other", "Other")]:
        if by.get(g):
            out.append(f"### {title}\n\n" + "\n".join(by[g]) + "\n")
    return "\n".join(out) if out else "No changes.\n"


def subjects(rng, cwd=None):
    return [s for s in git("log", "--no-merges", "--format=%s", rng, cwd=cwd).splitlines() if s.strip()]


def notes(tag, tags=None, cwd=None):
    tags = tags or versions(cwd)
    prev = previous(tag, tags, cwd)
    return section(subjects(f"{prev}..{tag}" if prev else tag, cwd))


def build(cwd=None, head="HEAD", next_tag=""):
    tags = versions(cwd)
    parts = ["# Changelog\n",
             "Every version of the engine (the workflows, scripts, policy and kinds other repositories call), newest first, built from git by `scripts/changelog.py`: what merged in it, by type. What a major, a minor and a patch mean for whoever calls these workflows is in [docs/versioning.md](docs/versioning.md).\n"]
    if tags:
        pending = subjects(f"{tags[-1]}..{head}", cwd)
        if pending:
            import datetime
            title = (f"## [{next_tag[1:]}]({REPO_URL}/releases/tag/{next_tag}) · {datetime.date.today().isoformat()}" if next_tag else "## Unreleased")
            parts.append(title + "\n\n" + section(pending))
    for tag in reversed(tags):
        date = git("log", "-1", "--format=%cs", tag, cwd=cwd).strip()
        parts.append(f"## [{tag[1:]}]({REPO_URL}/releases/tag/{tag}) · {date}\n\n" + notes(tag, tags, cwd))
    return "\n".join(parts)


def self_test():
    import tempfile
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    check("line: scope, text and the pull request linked", line("feat(review): no shell (#288)"),
          ("feat", f"- **review:** no shell ([#288]({REPO_URL}/pull/288))"))
    check("line: straight quotes in what is published", line("fix: the «Unreleased.» line")[1], '- the "Unreleased." line')
    check("line: a breaking change and a subject that is no Conventional Commit",
          (line("feat(org)!: one pipeline (#33)")[0], line("Initial commit")), ("breaking", ("other", "- Initial commit")))
    sec = section(["fix: b", "feat(x)!: a", "feat: c", "whatever"])
    check("section: breaking first, then features, fixes, other",
          (sec.index("Breaking") < sec.index("Features") < sec.index("Fixes") < sec.index("Other")), True)
    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        g = lambda *a: subprocess.run(["git", *a], cwd=d, env=env, capture_output=True, text=True, check=True)
        g("init", "-q", "-b", "main")
        for msg, tag in (("feat: one", "v1.0.0"), ("fix: two", "v1.0.1"), ("feat!: three", "v2.0.0"), ("feat: four", "v2.1.0")):
            g("commit", "-q", "--allow-empty", "-m", msg)
            g("tag", tag)
        g("tag", "v2")
        g("checkout", "-q", "-b", "old", "v1.0.1")
        g("commit", "-q", "--allow-empty", "-m", "fix: backport")
        g("tag", "v1.0.2")
        g("checkout", "-q", "main")
        g("commit", "-q", "--allow-empty", "-m", "docs: later")
        tags = versions(d)
        check("versions: by number, the moving tags left out", tags, ["v1.0.0", "v1.0.1", "v1.0.2", "v2.0.0", "v2.1.0"])
        check("previous: the nearest version among its ancestors", (previous("v1.0.2", tags, d), previous("v2.0.0", tags, d), previous("v1.0.0", tags, d)),
              ("v1.0.1", "v1.0.1", ""))
        check("notes: only what merged in that version", ("backport" in notes("v1.0.2", tags, d), "three" in notes("v1.0.2", tags, d)), (True, False))
        full = build(d)
        check("build: unreleased on top, newest version first, each once",
              (full.index("## Unreleased") < full.index("## [2.1.0]") < full.index("## [1.0.0]"), full.count("## [1.0.1]"), "later" in full.split("## [2.1.0]")[0]),
              (True, 1, True))
        nxt = build(d, next_tag="v2.2.0")
        check("build --next: what is unreleased is headed as that version", ("## Unreleased" in nxt, "## [2.2.0]" in nxt), (False, True))
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv[:1] == ["build"]:
        nxt = argv[2] if argv[1:2] == ["--next"] and len(argv) == 3 and VERSION.match(argv[2]) else ""
        if len(argv) > 1 and not nxt:
            print(__doc__, file=sys.stderr)
            return 64
        sys.stdout.write(build(next_tag=nxt))
        return 0
    if len(argv) == 2 and argv[0] == "notes" and VERSION.match(argv[1]):
        sys.stdout.write(notes(argv[1]))
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
