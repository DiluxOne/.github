#!/usr/bin/env python3
"""Push local commits as commits GitHub signs (#190).

A bot that runs `git commit` and `git push` leaves unsigned commits, and the
organisation's ruleset is to require signed commits on every branch. A
commit made through the API with the App's token is signed by GitHub
("Verified"), as scripts/receipts.py already writes the receipts. This makes
each local commit again through the API, in order, with its message, its
tree and its parent on GitHub, moves the branch to the last one, and then
points the local branch at it: the trees are the same, so the work goes on
from there as if git had pushed it.

  api-commit.py push BRANCH [--onto REF] [--force]
      the commits of HEAD that the remote BRANCH lacks. With --onto, a ref
      that is on GitHub (a commit, origin/<branch>): where a new BRANCH
      starts, or, with --force, what it is rewritten onto. Without commits
      to make, it only creates or moves the branch to --onto.
  api-commit.py --test   self-test, against a local repository and a
                         stand-in for GitHub

Environment: GH_TOKEN (contents: write), GITHUB_REPOSITORY (owner/name).
The bots' work is linear, but for one merge (#550): the default branch
merged into the work, clean. A merge commit is made again, with all its
parents, only when it has two, its other parent is on the default branch on
GitHub, and its tree is the one git's own merge gives (`git merge-tree
--write-tree`), so it brings nothing but what main already has, but for the
files that merge leaves in conflict, resolved (#556); a file under
.github/workflows resolved by hand only with ENGINE=true, the
organisation's own repository (#498). Every other merge is refused. Run
from the checkout.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile

ZERO = "0" * 40


def git(*args, cwd=None):
    out = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)
    if out.returncode != 0:
        raise RuntimeError(f"git {args[0]} exited {out.returncode}: {out.stderr.strip()[:200]}")
    return out.stdout


def gh_api(method, path, body=None):
    args = ["gh", "api", "-X", method, path]
    if body is not None:
        args += ["--input", "-"]
    out = subprocess.run(args, capture_output=True, text=True, input=json.dumps(body) if body is not None else None)
    if out.returncode != 0:
        raise RuntimeError(f"{method} {path.split('?')[0]}: {out.stderr.strip()[:300]}")
    return json.loads(out.stdout) if out.stdout.strip() else {}


def remote_head(api, repo, branch):
    """The branch's commit on GitHub, or None when it has none."""
    try:
        return api("GET", f"repos/{repo}/git/ref/heads/{branch}")["object"]["sha"]
    except RuntimeError as exc:
        if "404" in str(exc) or "Not Found" in str(exc):
            return None
        raise


def on_default(api, repo, sha):
    """Whether the commit is on GitHub's default branch (never only a fork's,
    whose commits GitHub's API also shows)."""
    default = api("GET", f"repos/{repo}")["default_branch"]
    try:
        return api("GET", f"repos/{repo}/compare/{sha}...{default}")["status"] in ("ahead", "identical")
    except RuntimeError:
        return False


def clean_merge(c, parents, api, repo, cwd=None):
    """Why the merge commit c may not be pushed, or None when it is main
    merged in, clean (#550) or with its conflicts resolved (#556)."""
    if len(parents) != 2:
        return f"{c[:12]} merges {len(parents)} parents; only the default branch merged in is pushed"
    if not on_default(api, repo, parents[1]):
        return f"{c[:12]} merges {parents[1][:12]}, which is not on the default branch on GitHub"
    out = subprocess.run(["git", "merge-tree", "--write-tree", "--name-only", "--no-messages", *parents], cwd=cwd, capture_output=True, text=True)
    if out.returncode not in (0, 1):
        return f"{c[:12]}: git merge-tree failed: {out.stderr.strip()[:200]}"
    tree, *conflicted = [l for l in out.stdout.splitlines() if l.strip()]
    # #556: what differs from git's own merge is only the files it left in
    # conflict, resolved; nothing else slips in.
    differ = set(git("diff-tree", "-r", "--no-renames", "--name-only", "-z", tree, f"{c}^{{tree}}", cwd=cwd).split("\0")) - {""}
    if differ - set(conflicted):
        return f"{c[:12]} is not the merge of its parents: it changes {sorted(differ - set(conflicted))[0]}, which the merge left alone; changed merges are not pushed"
    workflows = sorted(p for p in differ if p.startswith(".github/workflows/"))
    if workflows and os.environ.get("ENGINE") != "true":
        return f"{c[:12]} resolves {workflows[0]} by hand; .github/workflows is not pushed outside the organisation's own repository"
    return None


def changes(parent, commit, cwd=None):
    """The tree entries a commit changes from its parent: {path: (mode, blob
    sha)} for what it adds or modifies, None for what it removes."""
    out = {}
    raw = git("diff-tree", "-r", "--no-renames", "--no-commit-id", "-z", parent, commit, cwd=cwd).split("\0")
    i = 0
    while i < len(raw) - 1:
        meta, path = raw[i], raw[i + 1]
        i += 2
        if not meta.startswith(":"):
            continue
        _, new_mode, _, new_sha, status = meta[1:].split(" ")
        out[path] = None if status == "D" else (new_mode, new_sha)
    return out


def push(repo, branch, onto=None, force=False, api=gh_api, cwd=None):
    """Make HEAD's commits that GitHub lacks again through the API; returns
    the new head on GitHub."""
    remote = remote_head(api, repo, branch)
    base = git("rev-parse", onto, cwd=cwd).strip() if onto else None
    start = base if (force or remote is None) else remote
    if start is None:
        raise RuntimeError(f"{branch} is not on GitHub: say where it starts (--onto)")
    if not force and remote is not None and base and base != remote:
        raise RuntimeError(f"{branch} is at {remote[:12]} on GitHub, not at --onto; use --force to rewrite it")
    # Only on top of what GitHub has: a branch that moved there since is not
    # overwritten without --force.
    known = subprocess.run(["git", "merge-base", "--is-ancestor", start, "HEAD"], cwd=cwd, capture_output=True)
    if known.returncode != 0:
        raise RuntimeError(f"{branch} on GitHub ({start[:12]}) is not under HEAD: fetch it and build on it, or use --force")
    # The branch's own line: what a merge brings in is on GitHub already.
    commits = git("rev-list", "--reverse", "--first-parent", f"{start}..HEAD", cwd=cwd).split()
    head = start
    for c in commits:
        parents = git("rev-list", "--parents", "-n", "1", c, cwd=cwd).split()[1:]
        if len(parents) != 1:
            why = clean_merge(c, parents, api, repo, cwd=cwd)
            if why:
                raise RuntimeError(why)
        entries = []
        for path, entry in changes(parents[0], c, cwd=cwd).items():
            if entry is None:
                entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
                continue
            mode, blob = entry
            if mode == "160000":
                raise RuntimeError(f"{path} is a submodule; not supported")
            content = subprocess.run(["git", "cat-file", "blob", blob], capture_output=True, cwd=cwd, check=True).stdout
            made = api("POST", f"repos/{repo}/git/blobs", {"content": base64.b64encode(content).decode(), "encoding": "base64"})
            entries.append({"path": path, "mode": mode, "type": "blob", "sha": made["sha"]})
        base_tree = api("GET", f"repos/{repo}/git/commits/{head}")["tree"]["sha"]
        tree = api("POST", f"repos/{repo}/git/trees", {"base_tree": base_tree, "tree": entries})["sha"] if entries else base_tree
        message = git("log", "-1", "--format=%B", c, cwd=cwd).rstrip("\n")
        head = api("POST", f"repos/{repo}/git/commits", {"message": message, "tree": tree, "parents": [head, *parents[1:]]})["sha"]
    if remote is None:
        api("POST", f"repos/{repo}/git/refs", {"ref": f"refs/heads/{branch}", "sha": head})
    elif head != remote:
        api("PATCH", f"repos/{repo}/git/refs/heads/{branch}", {"sha": head, "force": force})
    # The local branch follows: same trees, GitHub's commits.
    refspec = f"+refs/heads/{branch}:refs/remotes/origin/{branch}"
    try:
        git("fetch", "-q", "origin", refspec, cwd=cwd)
    except RuntimeError:
        # A checkout that keeps no credentials: the token, for this fetch only.
        token = os.environ.get("GH_TOKEN", "")
        auth = "AUTHORIZATION: basic " + base64.b64encode(f"x-access-token:{token}".encode()).decode()
        git("-c", f"http.extraheader={auth}", "fetch", "-q", "origin", refspec, cwd=cwd)
    git("reset", "-q", "--soft", head, cwd=cwd)
    return head


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    with tempfile.TemporaryDirectory() as d:
        origin, work = os.path.join(d, "origin.git"), os.path.join(d, "work")
        git("init", "-q", "--bare", origin)
        git("init", "-q", "-b", "main", work)
        env = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]

        def commit(msg, files=None, remove=(), mode=None):
            for p, text in (files or {}).items():
                full = os.path.join(work, p)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w") as fh:
                    fh.write(text)
                if mode:
                    os.chmod(full, mode)
            for p in remove:
                os.remove(os.path.join(work, p))
            git("add", "-A", cwd=work)
            git(*env, "commit", "-q", "--allow-empty", "-m", msg, cwd=work)
            return git("rev-parse", "HEAD", cwd=work).strip()

        commit("chore: base", {"a.txt": "a\n", "dir/b.txt": "b\n"})
        git("remote", "add", "origin", origin, cwd=work)
        git("push", "-q", "origin", "main", cwd=work)
        base = git("rev-parse", "HEAD", cwd=work).strip()
        git("checkout", "-q", "-b", "feat/1-x", cwd=work)
        commit("feat: one (C1)", {"a.txt": "a2\n", "new.sh": "#!/bin/sh\n"}, mode=0o755)
        commit("feat: two (C2)\n\nA body.\n\nAssisted-by: Claude Opus 5.5 (Anthropic)", remove=["dir/b.txt"])
        commit("chore: empty")

        # GitHub, played by the bare repository: blobs, trees and commits are
        # made there with git's own plumbing, so the result can be compared.
        calls = []

        def api(method, path, body=None):
            calls.append((method, path.split("/git/")[-1].split("/")[0] if "/git/" in path else path))
            if path.endswith("/git/blobs"):
                data = base64.b64decode(body["content"])
                sha = subprocess.run(["git", "hash-object", "-w", "--stdin"], input=data, capture_output=True, cwd=origin, check=True).stdout.decode().strip()
                return {"sha": sha}
            if "/git/commits/" in path and method == "GET":
                return {"tree": {"sha": git("rev-parse", path.rsplit("/", 1)[1] + "^{tree}", cwd=origin).strip()}}
            if path.endswith("/git/trees"):
                idx = os.path.join(d, "idx")
                os.makedirs(os.path.join(d, "wt"), exist_ok=True)
                envi = {**os.environ, "GIT_INDEX_FILE": idx, "GIT_WORK_TREE": os.path.join(d, "wt")}
                subprocess.run(["git", "read-tree", body["base_tree"]], cwd=origin, env=envi, check=True)
                for e in body["tree"]:
                    if e["sha"] is None:
                        subprocess.run(["git", "update-index", "--force-remove", e["path"]], cwd=origin, env=envi, check=True)
                    else:
                        subprocess.run(["git", "update-index", "--add", "--cacheinfo", f"{e['mode']},{e['sha']},{e['path']}"], cwd=origin, env=envi, check=True)
                sha = subprocess.run(["git", "write-tree"], cwd=origin, env=envi, capture_output=True, text=True, check=True).stdout.strip()
                os.remove(idx)
                return {"sha": sha}
            if path.endswith("/git/commits") and method == "POST":
                ps = [a for p in body["parents"] for a in ("-p", p)]
                sha = subprocess.run(["git", *env, "commit-tree", body["tree"], *ps, "-m", body["message"]],
                                     cwd=origin, capture_output=True, text=True, check=True).stdout.strip()
                return {"sha": sha}
            if path == "repos/o/r":
                return {"default_branch": "main"}
            if "/compare/" in path:
                sha, ref = path.split("/compare/")[1].split("...")
                if subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=origin).returncode != 0:
                    raise RuntimeError("HTTP 404 Not Found")
                if git("rev-parse", f"refs/heads/{ref}", cwd=origin).strip() == sha:
                    return {"status": "identical"}
                under = subprocess.run(["git", "merge-base", "--is-ancestor", sha, f"refs/heads/{ref}"], cwd=origin).returncode == 0
                return {"status": "ahead" if under else "diverged"}
            if "/git/ref/heads/" in path:
                out = subprocess.run(["git", "rev-parse", "--verify", "-q", "refs/heads/" + path.split("/git/ref/heads/")[1]], cwd=origin, capture_output=True, text=True)
                if out.returncode != 0:
                    raise RuntimeError("HTTP 404 Not Found")
                return {"object": {"sha": out.stdout.strip()}}
            if path.endswith("/git/refs") and method == "POST":
                git("update-ref", body["ref"], body["sha"], cwd=origin)
                return {}
            if "/git/refs/heads/" in path and method == "PATCH":
                git("update-ref", "refs/heads/" + path.split("/git/refs/heads/")[1], body["sha"], cwd=origin)
                return {}
            raise AssertionError(path)

        local_tree = git("rev-parse", "HEAD^{tree}", cwd=work).strip()
        head = push("o/r", "feat/1-x", onto=base, api=api, cwd=work)
        check("push: GitHub's branch ends at the same tree", git("rev-parse", f"{head}^{{tree}}", cwd=origin).strip(), local_tree)
        check("push: one commit each, in order, with their messages",
              git("log", "--format=%s", f"{base}..{head}", cwd=origin).split("\n")[:3], ["chore: empty", "feat: two (C2)", "feat: one (C1)"])
        check("push: a body and its trailer are kept", "Assisted-by: Claude Opus 5.5 (Anthropic)" in git("log", "-1", "--format=%B", f"{head}~1", cwd=origin), True)
        check("push: the executable bit is kept", "100755" in git("ls-tree", head, "new.sh", cwd=origin), True)
        check("push: a removed file is gone", git("ls-tree", "-r", "--name-only", head, cwd=origin).split(), ["a.txt", "new.sh"])
        check("push: the local branch points at GitHub's commit", git("rev-parse", "HEAD", cwd=work).strip(), head)
        check("push: the working tree is untouched", git("status", "--porcelain", cwd=work), "")

        calls.clear()
        commit("feat: three (C3)", {"c.txt": "c\n"})
        head2 = push("o/r", "feat/1-x", api=api, cwd=work)
        check("push again: only the commit GitHub lacks", git("log", "--format=%s", f"{head}..{head2}", cwd=origin).strip(), "feat: three (C3)")
        check("push again: moves the branch, never creates it", (any(m == "PATCH" for m, _ in calls), ("POST", "refs") in calls), (True, False))
        check("push again: nothing to push is no new commit", push("o/r", "feat/1-x", api=api, cwd=work), head2)

        git("checkout", "-q", "-b", "test/repro", base, cwd=work)
        only = push("o/r", "test/repro", onto=base, api=api, cwd=work)
        check("push: no commits only creates the branch at --onto", only, base)
        commit("test: a failing test", {"t.txt": "t\n"})
        again = push("o/r", "test/repro", onto=base, force=True, api=api, cwd=work)
        check("push --force: rewritten onto --onto", git("rev-parse", f"{again}~1", cwd=origin).strip(), base)
        # GitHub's branch moved on its own: never written over without --force.
        git("checkout", "-q", "feat/1-x", cwd=work)
        moved = subprocess.run(["git", *env, "commit-tree", f"{head2}^{{tree}}", "-p", head2, "-m", "someone else"], cwd=origin, capture_output=True, text=True, check=True).stdout.strip()
        git("update-ref", "refs/heads/feat/1-x", moved, cwd=origin)
        commit("feat: four (C4)", {"d.txt": "d\n"})
        try:
            push("o/r", "feat/1-x", api=api, cwd=work)
            check("push: a branch that moved on GitHub is not written over", "pushed", "refused")
        except RuntimeError:
            check("push: a branch that moved on GitHub is not written over", "refused", "refused")
        check("main: --onto with no ref is a usage error", main(["push", "x", "--onto"]), 64)
        try:
            push("o/r", "nowhere", api=api, cwd=work)
            check("push: a new branch needs --onto", "pushed", "refused")
        except RuntimeError:
            check("push: a new branch needs --onto", "refused", "refused")
        try:
            push("o/r", "feat/1-x", onto=base, api=api, cwd=work)
            check("push: --onto elsewhere than GitHub's head needs --force", "pushed", "refused")
        except RuntimeError:
            check("push: --onto elsewhere than GitHub's head needs --force", "refused", "refused")

        # The default branch merged in (#550): clean, it is made again with
        # both parents; any other merge is refused.
        def refused(name, branch, why):
            try:
                push("o/r", branch, api=api, cwd=work)
                check(name, "pushed", "refused")
            except RuntimeError as exc:
                check(name, "refused" if why in str(exc) else str(exc), "refused")

        def main_moves(msg, files):
            git("checkout", "-q", "main", cwd=work)
            sha = commit(msg, files)
            git("push", "-q", "origin", "main", cwd=work)
            git("checkout", "-q", "feat/2-m", cwd=work)
            return sha

        git("checkout", "-q", "-b", "feat/2-m", base, cwd=work)
        commit("feat: x (C1)", {"x.txt": "x\n"})
        mine = push("o/r", "feat/2-m", onto=base, api=api, cwd=work)
        moved = main_moves("chore: main moves", {"m.txt": "m\n"})
        git(*env, "merge", "-q", "--no-edit", "main", cwd=work)
        commit("feat: y (C2)", {"y.txt": "y\n"})
        local_tree = git("rev-parse", "HEAD^{tree}", cwd=work).strip()
        merged = push("o/r", "feat/2-m", api=api, cwd=work)
        check("push merge: GitHub's branch ends at the same tree", git("rev-parse", f"{merged}^{{tree}}", cwd=origin).strip(), local_tree)
        check("push merge: made with both parents, main's kept as it is",
              git("rev-list", "--parents", "-n", "1", f"{merged}~1", cwd=origin).split()[1:], [mine, moved])
        check("push merge: main's commits are not made again", git("rev-list", "--count", f"{mine}..{merged}", cwd=origin).strip(), "3")

        git("checkout", "-q", "-b", "side", base, cwd=work)
        commit("feat: elsewhere", {"s.txt": "s\n"})
        git("push", "-q", "origin", "side", cwd=work)
        git("checkout", "-q", "feat/2-m", cwd=work)
        git(*env, "merge", "-q", "--no-edit", "side", cwd=work)
        refused("push merge: a branch other than the default is refused", "feat/2-m", "not on the default branch")
        git("reset", "-q", "--hard", merged, cwd=work)

        main_moves("chore: main moves again", {"n.txt": "n\n"})
        git(*env, "merge", "-q", "--no-commit", "main", cwd=work)
        with open(os.path.join(work, "extra.txt"), "w") as fh:
            fh.write("slipped in\n")
        git("add", "-A", cwd=work)
        git(*env, "commit", "-q", "--no-edit", cwd=work)
        refused("push merge: a merge that changes more than main is refused", "feat/2-m", "changes extra.txt, which the merge left alone")
        git("reset", "-q", "--hard", merged, cwd=work)

        # #556: a fix round on a pull request that conflicts with main merges
        # it and resolves the conflicts; only those files may differ from
        # git's own merge, and a workflow only in the engine's repository.
        def conflicting_merge(name, resolved):
            main_moves(f"chore: main changes {name}", {name: "main\n"})
            commit(f"feat: {name} (C3)", {name: "mine\n"})
            subprocess.run(["git", *env, "merge", "-q", "--no-edit", "main"], cwd=work, capture_output=True)
            for p, text in resolved.items():
                with open(os.path.join(work, p), "w") as fh:
                    fh.write(text)
            git("add", "-A", cwd=work)
            git(*env, "commit", "-q", "--no-edit", cwd=work)

        conflicting_merge("x.txt", {"x.txt": "resolved\n", "extra.txt": "slipped in\n"})
        refused("push merge: a resolved merge that changes a file beyond the conflict is refused", "feat/2-m", "changes extra.txt")
        git("reset", "-q", "--hard", merged, cwd=work)

        conflicting_merge("x.txt", {"x.txt": "main\nmine\n"})
        local_tree = git("rev-parse", "HEAD^{tree}", cwd=work).strip()
        try:
            resolved = push("o/r", "feat/2-m", api=api, cwd=work)
        except RuntimeError as exc:
            resolved = str(exc)
        check("push merge: a conflict with main resolved by hand is pushed, at the same tree",
              git("rev-parse", f"{resolved}^{{tree}}", cwd=origin).strip() if len(resolved) == 40 else resolved, local_tree)
        check("push merge: the resolved merge keeps main's commit as its other parent",
              git("rev-parse", f"{resolved}^2", cwd=origin).strip() if len(resolved) == 40 else resolved, git("rev-parse", "main", cwd=work).strip())
        merged = resolved

        flow = ".github/workflows/ci.yml"
        conflicting_merge(flow, {flow: "resolved\n"})
        old = os.environ.pop("ENGINE", None)
        try:
            refused("push merge: a workflow resolved by hand is refused outside the engine's repository", "feat/2-m", "resolves .github/workflows/ci.yml")
            os.environ["ENGINE"] = "true"
            try:
                push("o/r", "feat/2-m", api=api, cwd=work)
                check("push merge: a workflow resolved by hand is pushed in the engine's repository", "pushed", "pushed")
            except RuntimeError as exc:
                check("push merge: a workflow resolved by hand is pushed in the engine's repository", str(exc), "pushed")
        finally:
            os.environ.pop("ENGINE", None)
            if old is not None:
                os.environ["ENGINE"] = old
        merged = git("rev-parse", "HEAD", cwd=work).strip()

        # #561 C2: a work run on a branch main conflicts with merges main
        # first, resolves the conflict, then commits a criterion: both go,
        # the merge with main's commit as its other parent.
        conflicting_merge("y.txt", {"y.txt": "main\nmine\n"})
        commit("feat: after the merge (C4)", {"z.txt": "z\n"})
        local_tree = git("rev-parse", "HEAD^{tree}", cwd=work).strip()
        try:
            after = push("o/r", "feat/2-m", api=api, cwd=work)
        except RuntimeError as exc:
            after = str(exc)
        check("push merge: a work run's resolved merge of main, then a criterion's commit, both go",
              (git("rev-parse", f"{after}^{{tree}}", cwd=origin).strip(), git("rev-parse", f"{after}^^2", cwd=origin).strip()) if len(after) == 40 else after,
              (local_tree, git("rev-parse", "main", cwd=work).strip()))
        merged = after if len(after) == 40 else merged

        third = git(*env, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-p", "main", "-p", "side", "-m", "octopus", cwd=work).strip()
        git("reset", "-q", "--hard", third, cwd=work)
        refused("push merge: an octopus merge is refused", "feat/2-m", "merges 3 parents")

    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if len(argv) >= 2 and argv[0] == "push":
        if "--onto" in argv and argv.index("--onto") + 1 >= len(argv):
            print("--onto needs a ref", file=sys.stderr)
            return 64
        if not os.environ.get("GITHUB_REPOSITORY"):
            print("GITHUB_REPOSITORY (owner/name) is not set", file=sys.stderr)
            return 64
        onto = argv[argv.index("--onto") + 1] if "--onto" in argv else None
        try:
            head = push(os.environ["GITHUB_REPOSITORY"], argv[1], onto=onto, force="--force" in argv)
        except RuntimeError as exc:
            print(f"Not pushed: {exc}", file=sys.stderr)
            return 1
        print(f"{argv[1]} is at {head} on GitHub, signed by GitHub.")
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
