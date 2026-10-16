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
Merge commits are refused: the bots' work is linear. Run from the checkout.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile

ZERO = "0" * 40


def git(*args, cwd=None):
    out = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)
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
    commits = git("rev-list", "--reverse", "--topo-order", f"{start}..HEAD", cwd=cwd).split()
    head = start
    for c in commits:
        parents = git("rev-list", "--parents", "-n", "1", c, cwd=cwd).split()[1:]
        if len(parents) != 1:
            raise RuntimeError(f"{c[:12]} is a merge commit; the bots' work is linear")
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
        head = api("POST", f"repos/{repo}/git/commits", {"message": message, "tree": tree, "parents": [head]})["sha"]
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
        commit("feat: two (C2)\n\nA body.\n\nCo-Authored-By: Claude <noreply@anthropic.com>", remove=["dir/b.txt"])
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
                sha = subprocess.run(["git", *env, "commit-tree", body["tree"], "-p", body["parents"][0], "-m", body["message"]],
                                     cwd=origin, capture_output=True, text=True, check=True).stdout.strip()
                return {"sha": sha}
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
        check("push: a body and its trailer are kept", "Co-Authored-By: Claude" in git("log", "-1", "--format=%B", f"{head}~1", cwd=origin), True)
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

    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if len(argv) >= 2 and argv[0] == "push":
        onto = argv[argv.index("--onto") + 1] if "--onto" in argv else None
        head = push(os.environ["GITHUB_REPOSITORY"], argv[1], onto=onto, force="--force" in argv)
        print(f"{argv[1]} is at {head} on GitHub, signed by GitHub.")
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
