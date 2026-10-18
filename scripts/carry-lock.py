#!/usr/bin/env python3
"""Whether every published security patch is on the default branch (#287).

A security patch (security-patch.yml) is released from security/X.Y.Z, on
top of the version in production, never from the default branch: its fix
must then be carried into the default branch, or the next release from there
brings the vulnerability back. This tells which patches are not carried yet,
from git alone (a checkout with the whole history and the tags):

  - a security patch is a version tag vX.Y.Z or X.Y.Z whose commit is the
    patch's release commit ("chore(release): X.Y.Z, a security patch",
    scripts/security-patch-build.sh) and is not on the branch;
  - its fix is the commits since the version it was built on (the nearest
    version tag among its ancestors), but that release commit;
  - it is carried when every one of them has a patch-equivalent commit on
    the branch (`git cherry`), or one commit on the branch since they parted
    carries the whole fix at once (a squash merge): the same patch id as the
    fix's whole diff, however it got there.

  carry-lock.py check [BRANCH]   one line per patch not carried (exit 1);
                                 nothing (exit 0); 2 when it cannot tell
                                 (BRANCH: default HEAD)
  carry-lock.py fix TAG          the fix's commits of a security patch tag,
                                 oldest first, one SHA per line (the carry
                                 cherry-picks them)
  carry-lock.py --test
"""
import os
import re
import subprocess
import sys

VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
RELEASE = "chore(release): {version}, a security patch"


def git(*args, cwd=None):
    out = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])}: {out.stderr.strip()[:200]}")
    return out.stdout


def is_ancestor(a, b, cwd=None):
    return subprocess.run(["git", "merge-base", "--is-ancestor", a, b], cwd=cwd, capture_output=True).returncode == 0


def key(tag):
    return tuple(int(x) for x in VERSION.match(tag).groups())


def tags(cwd=None):
    return sorted((t for t in git("tag", "-l", cwd=cwd).split() if VERSION.match(t)), key=key)


def subject(rev, cwd=None):
    return git("log", "-1", "--format=%s", rev, cwd=cwd).strip()


def version_of(tag):
    return ".".join(VERSION.match(tag).groups())


def is_patch(tag, cwd=None):
    """Whether the tag is a security patch's: its commit is the patch's
    release commit."""
    return subject(f"{tag}^{{commit}}", cwd) == RELEASE.format(version=version_of(tag))


def base_of(tag, all_tags, cwd=None):
    """The version the patch was built on: the highest version below it
    among its ancestors; "" when none."""
    for t in sorted((t for t in all_tags if key(t) < key(tag)), key=key, reverse=True):
        if is_ancestor(t, tag, cwd):
            return t
    return ""


def fix_commits(tag, all_tags=None, cwd=None):
    """The fix's commits of a security patch tag, oldest first: those since
    the version it was built on, but its release commit."""
    all_tags = all_tags if all_tags is not None else tags(cwd)
    base = base_of(tag, all_tags, cwd)
    if not base:
        raise RuntimeError(f"{tag} has no version below it to be built on")
    release = git("rev-parse", f"{tag}^{{commit}}", cwd=cwd).strip()
    revs = git("rev-list", "--reverse", "--no-merges", f"{base}..{tag}", cwd=cwd).split()
    return [r for r in revs if r != release]


def patch_id(diff, cwd=None):
    """The stable patch id of a diff ("" for an empty one)."""
    out = subprocess.run(["git", "patch-id", "--stable"], input=diff, capture_output=True, text=True, cwd=cwd)
    return (out.stdout.split() or [""])[0]


def fix_id(tag, all_tags=None, cwd=None):
    """The patch id of a patch's whole fix: what the commits since the
    version it was built on change, but its release commit (the tag's own,
    the last)."""
    all_tags = all_tags if all_tags is not None else tags(cwd)
    return patch_id(git("diff", base_of(tag, all_tags, cwd), f"{tag}^{{commit}}^", cwd=cwd), cwd)


def squashed_in(tag, branch, all_tags, cwd=None):
    """Whether one commit on the branch, since it parted from the patch,
    carries the patch's whole fix at once (a squash merge)."""
    want = fix_id(tag, all_tags, cwd)
    if not want:
        return False
    since = git("merge-base", branch, tag, cwd=cwd).strip()
    for rev in git("rev-list", "--no-merges", f"{since}..{branch}", cwd=cwd).split():
        if patch_id(git("show", "--format=", rev, cwd=cwd), cwd) == want:
            return True
    return False


def missing(branch="HEAD", cwd=None):
    """[(version, commits not carried)] for each security patch not on the
    branch, oldest first."""
    all_tags = tags(cwd)
    out = []
    for t in all_tags:
        if is_ancestor(t, branch, cwd) or not is_patch(t, cwd):
            continue
        fix = set(fix_commits(t, all_tags, cwd))
        base = base_of(t, all_tags, cwd)
        # `git cherry BRANCH TAG BASE`: "+ sha" for a commit of base..tag
        # with no patch-equivalent on the branch.
        left = [l.split()[1] for l in git("cherry", branch, t, base, cwd=cwd).splitlines() if l.startswith("+ ")]
        left = [c for c in left if c in fix]
        if left and not squashed_in(t, branch, all_tags, cwd):
            out.append((version_of(t), left))
    return out


def self_test():
    import tempfile
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

        def g(*a):
            return subprocess.run(["git", *a], cwd=d, env=env, capture_output=True, text=True, check=True).stdout.strip()

        def write(path, text):
            with open(os.path.join(d, path), "w", encoding="utf-8") as fh:
                fh.write(text)

        g("init", "-q", "-b", "main")
        write("a.php", "<?php\n$a = 1;\n")
        write("b.php", "<?php\n$b = 1;\n")
        g("add", "-A")
        g("commit", "-q", "-m", "feat: one")
        g("tag", "1.0.0")
        # main moves on after the version in production.
        write("b.php", "<?php\n$b = 2;\n")
        g("commit", "-qam", "feat: two")
        # The security patch, on the version in production.
        g("checkout", "-q", "-b", "security/1.0.1", "1.0.0")
        write("a.php", "<?php\n$a = esc_html( 1 );\n")
        g("commit", "-qam", "fix: escape a")
        g("commit", "-q", "--allow-empty", "-m", "chore(release): 1.0.1, a security patch")
        g("tag", "1.0.1")
        fix = g("rev-parse", "HEAD~1")
        g("checkout", "-q", "main")
        check("fix: the patch's commits, not its release commit", fix_commits("1.0.1", cwd=d), [fix])
        check("check: a patch not on main is missing", missing("main", d), [("1.0.1", [fix])])
        check("is_patch: only the patch's release commit makes a tag a patch", (is_patch("1.0.1", d), is_patch("1.0.0", d)), (True, False))
        # Carried by a cherry-pick: an equivalent commit on main.
        g("cherry-pick", fix)
        check("check: carried by an equivalent commit, nothing is missing", missing("main", d), [])
        # A fix of two commits, carried by one squash merge.
        g("checkout", "-q", "-b", "security/1.0.2", "1.0.1")
        write("c.php", "<?php\n$c = intval( 1 );\n")
        g("add", "c.php")
        g("commit", "-qm", "fix: intval c")
        write("a.php", "<?php\n$a = esc_html( absint( 1 ) );\n")
        g("commit", "-qam", "fix: absint a")
        g("commit", "-q", "--allow-empty", "-m", "chore(release): 1.0.2, a security patch")
        g("tag", "1.0.2")
        g("checkout", "-q", "main")
        check("check: a fix of two commits not carried is missing", [m[0] for m in missing("main", d)], ["1.0.2"])
        g("checkout", "-q", "-b", "squash", "main")
        g("cherry-pick", "--no-commit", "1.0.2~2", "1.0.2~1")
        g("commit", "-q", "-m", "fix(security): carry 1.0.2 (#9)")
        check("check: carried by one squash commit, nothing is missing", missing("squash", d), [])
        g("checkout", "-q", "main")
        g("merge", "-q", "--ff-only", "squash")
        # A later release from main contains it: ancestors are never patches to carry.
        g("tag", "1.1.0")
        check("check: a release tag on the branch is no patch to carry", missing("main", d), [])
        # A second patch, not carried: a fresh branch from before the pick.
        g("checkout", "-q", "-b", "security/1.1.1", "1.1.0")
        write("b.php", "<?php\n$b = absint( 2 );\n")
        g("commit", "-qam", "fix: absint b")
        g("commit", "-q", "--allow-empty", "-m", "chore(release): 1.1.1, a security patch")
        g("tag", "1.1.1")
        g("checkout", "-q", "main")
        check("check: the newer patch is missing, the carried one is not", [m[0] for m in missing("main", d)], ["1.1.1"])
        cwd, kept = os.getcwd(), os.environ.get("GIT_CONFIG_GLOBAL")
        os.chdir(d)
        os.environ["GIT_CONFIG_GLOBAL"] = "/dev/null"
        try:
            check("cli: missing says which and exits 1", main(["check", "main"]), 1)
            check("cli: a branch it cannot read exits 2", main(["check", "no-such-branch"]), 2)
            g("tag", "v9.9.9", "1.1.1")
            g("tag", "-d", "1.1.1")
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["fix", "9.9.9"])
            check("cli: fix finds a v-prefixed tag by its version", (rc, buf.getvalue().strip() != ""), (0, True))
        finally:
            os.chdir(cwd)
            if kept is None:
                os.environ.pop("GIT_CONFIG_GLOBAL", None)
            else:
                os.environ["GIT_CONFIG_GLOBAL"] = kept
    # The wiring (#287): the release from the default branch is locked, and
    # the security patch's finish carries the fix with this script.
    here = os.path.dirname(os.path.abspath(__file__))
    rel = open(os.path.join(here, "..", ".github", "workflows", "plugin-release-wp.yml"), encoding="utf-8").read()
    still = rel[rel.index("      - name: Still the release to make"):rel.index("      - name: The markers say this version")]
    check("wiring: a release from the default branch is locked until every patch is carried, the security path is not",
          ("carry-lock.py check" in still, still.index('if [ "$SECURITY" = true ]') < still.index("carry-lock.py check")), (True, True))
    sec = open(os.path.join(here, "..", ".github", "workflows", "security-patch.yml"), encoding="utf-8").read()
    fin = sec[sec.index("      - name: Finish"):]
    check("wiring: the finish opens the lane's issue and cherry-picks the released fix",
          ("lane:security-carry" in fin, "dx-lane: security-carry version:" in fin, "carry-lock.py\" fix" in fin, "git cherry-pick" in fin, "api-commit.py\" push" in fin),
          (True, True, True, True, True))
    check("wiring: a retried finish reuses the carry issue and opens the pull request it missed",
          ('gh issue list --repo "$REPO" --state all --label lane:security-carry' in fin, 'if [ -n "$num" ] && [ -z "$pr_url" ]' in fin, '--onto "$onto" --force' in fin), (True, True, True))
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    try:
        if argv[:1] == ["check"] and len(argv) <= 2:
            branch = argv[1] if len(argv) == 2 else "HEAD"
            git("rev-parse", "--verify", f"{branch}^{{commit}}")
            left = missing(branch)
            for version, commits in left:
                print(f"{version}: {len(commits)} commit(s) of its fix are not on {branch}")
            return 1 if left else 0
        if argv[:1] == ["fix"] and len(argv) == 2 and VERSION.match(argv[1]):
            have = tags()
            tag = argv[1] if argv[1] in have else (f"v{argv[1]}" if f"v{argv[1]}" in have else argv[1])
            print("\n".join(fix_commits(tag, have)))
            return 0
    except (RuntimeError, OSError) as err:
        print(f"carry-lock.py: {err}", file=sys.stderr)
        return 2
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
