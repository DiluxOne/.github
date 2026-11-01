#!/usr/bin/env python3
"""The engine's release lane (#563): a fix merged into a green main reaches
every repository with no person's step, once every release scenario passed
in the test repository; a breaking change waits on a person.

.github/workflows/release-lane.yml runs it on main, never on a fork's code:

  release-lane.py plan --repo R
        what is releasable since the last vX.Y.Z (scripts/next-version.py,
        from the labels of what merged) and whether a commit since says `!`:
        JSON {release, version, previous, major, breaking, why}; exit 0
  release-lane.py candidate --central OWNER/.github
        in a checkout of main: the `release-candidate` commit, main with
        the reusable workflows' inner calls of the engine at `@vN` moved to
        `@vN-next` (GitHub reads them before any expression, so the
        scenarios would otherwise try vN's), checked to differ from main in
        nothing else, and the lightweight `vN-next` tag moved to it
  release-lane.py decide --plan F --results F
        from the plan and the scenarios' results (scripts/release-scenarios.py
        run): `release`, `bug` (one failed: nothing tagged, nothing moved,
        a bug naming the scenario and its run) or `issue` (a `!`: the
        release issue for a person, nothing tagged); JSON
  release-lane.py act --plan F --results F --repo R [--run URL]
        does what `decide` says. A release: the release pull request
        (CHANGELOG.md from scripts/changelog.py build), merged, `vX.Y.Z`
        tagged at its merge commit, `vN` moved to it (lightweight: `git tag
        -f` and a force push of that ref alone), its GitHub Release
        published; JSON {moved_at, version, previous} on stdout
  release-lane.py watch --repo R --version V --previous P --since ISO
                        [--minutes 30] [--every 120] [--org O] [--property P]
        for `--minutes` after `vN` moved, every `--every` seconds: the runs
        of every adopted repository (org.yml `adopted-property`) since the
        move that ended in `startup_failure` or failed in one of the
        engine's own jobs; on the first, `vN` back at P, a bug with the
        run's link, and the release says so
  release-lane.py --test

Every command goes through `sh`, so the self-test records them with a fake
`gh` and `git`.
"""
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BREAKING = re.compile(r"^[a-z]+(\([^)]*\))?!:")
CANDIDATE = "release-candidate"
MARK = "<!-- dx-release-lane -->"


def sh(*argv, input=None):
    out = subprocess.run(list(argv), capture_output=True, text=True, input=input)
    if out.returncode:
        raise RuntimeError(f"{' '.join(argv[:3])}: {(out.stderr or out.stdout).strip()}")
    return out.stdout


# The plan.

def plan(nxt, subjects):
    """From next-version.py's JSON (with --tag-prefix v) and the subjects of
    the commits since the last release. Pure."""
    breaking = [s for s in subjects if BREAKING.match(s)] or (["a `type:breaking` or `version:major` label"] if nxt.get("bump") == "major" else [])
    version = f"v{nxt['next']}"
    out = {"release": bool(nxt.get("pending")), "version": version, "previous": f"v{nxt['last']}",
           "major": f"v{version[1:].split('.')[0]}", "breaking": bool(breaking)}
    if not out["release"]:
        out["why"] = "nothing releasable merged since the last release"
    elif breaking:
        out["why"] = f"a breaking change ({breaking[0]}): the scenarios run, then a person releases it"
    else:
        out["why"] = f"{nxt.get('bump')} since {out['previous']}"
    return out


# The candidate.

def rewrite_inner(text, central, major):
    """A reusable workflow's calls of the engine at `@vN` moved to
    `@vN-next`. Pure."""
    return re.sub(rf"(uses:\s*{re.escape(central)}/\.github/workflows/[^@\s]+)@{re.escape(major)}(?=\s|$)", rf"\1@{major}-next", text, flags=re.M)


def only_refs_differ(main_files, candidate_files, major):
    """The files where the candidate differs from main in more than its
    inner refs: [] when it is main but those. Pure."""
    out = [p for p in sorted(set(main_files) | set(candidate_files))
           if (candidate_files.get(p) or "").replace(f"@{major}-next", f"@{major}") != (main_files.get(p) or "")]
    return out


def candidate(central, major, root=".", run=sh):
    files = {}
    for path in sorted(glob.glob(os.path.join(root, ".github", "workflows", "*.yml"))):
        text = open(path, encoding="utf-8").read()
        if re.search(r"^  workflow_call:", text, re.M):
            files[os.path.relpath(path, root)] = text
    moved = {p: rewrite_inner(t, central, major) for p, t in files.items()}
    wrong = only_refs_differ(files, moved, major)
    if wrong:
        raise RuntimeError(f"the candidate differs from main beyond its inner refs: {', '.join(wrong)}")
    run("git", "-C", root, "checkout", "-B", CANDIDATE)
    for p, t in moved.items():
        if t != files[p]:
            with open(os.path.join(root, p), "w", encoding="utf-8") as fh:
                fh.write(t)
    run("git", "-C", root, "commit", "--allow-empty", "-qam", f"chore: release candidate, inner calls at @{major}-next")
    run("git", "-C", root, "push", "-f", "origin", f"HEAD:refs/heads/{CANDIDATE}")
    run("git", "-C", root, "tag", "-f", f"{major}-next", "HEAD")
    run("git", "-C", root, "push", "-f", "origin", f"refs/tags/{major}-next")
    return run("git", "-C", root, "rev-parse", "HEAD").strip()


# The decision.

def decide(p, results):
    """What the lane does, from its plan and the scenarios' results. Pure."""
    if not p.get("release"):
        return {"do": "none", "why": p.get("why", "")}
    failed = [r for r in results if not r.get("ok")]
    if not results:
        failed = [{"id": "(none ran)", "why": ["no scenario result"], "run": ""}]
    if failed:
        first = failed[0]
        lines = [f"- `{r['id']}`: {'; '.join(r.get('why') or []) or 'failed'} ({r.get('run') or 'no run'})" for r in failed]
        return {"do": "bug", "scenario": first["id"], "run": first.get("run", ""),
                "title": f"fix: release candidate {p['version']} fails scenario {first['id']}",
                "body": f"{MARK}\nThe release lane tried {p['version']} at `{p['major']}-next` in the test repository, and a scenario failed. Nothing was tagged and `{p['major']}` did not move.\n\n" + "\n".join(lines) + "\n"}
    if p.get("breaking"):
        return {"do": "issue", "why": p.get("why", "")}
    return {"do": "release", "version": p["version"]}


def release(p, repo, run=sh, sleep=time.sleep, minutes=60, root="."):
    """The release pull request, merged, the tag, the move and the Release.
    Returns {moved_at, version, previous}."""
    version, major = p["version"], p["major"]
    branch = f"chore/release-{version}"
    run("git", "-C", root, "checkout", "-B", branch, "origin/main")
    log = run("python3", os.path.join(HERE, "changelog.py"), "build", "--next", version, "--head", "origin/main")
    with open(os.path.join(root, "CHANGELOG.md"), "w", encoding="utf-8") as fh:
        fh.write(log)
    run("git", "-C", root, "commit", "-qam", f"chore: release {version}")
    run("git", "-C", root, "push", "-f", "origin", f"HEAD:refs/heads/{branch}")
    url = run("gh", "pr", "create", "--repo", repo, "--base", "main", "--head", branch, "--title", f"chore: release {version}",
              "--body", f"{MARK}\nThe release lane's release of {version}: every release scenario passed at `{major}-next`.\n").strip()
    number = url.rstrip("/").rsplit("/", 1)[-1]
    run("gh", "pr", "merge", number, "--repo", repo, "--squash", "--auto")
    sha, waited = "", 0
    while not sha:
        view = json.loads(run("gh", "pr", "view", number, "--repo", repo, "--json", "mergedAt,mergeCommit,state") or "{}")
        if view.get("mergedAt"):
            sha = (view.get("mergeCommit") or {}).get("oid", "")
            break
        if view.get("state") == "CLOSED" or waited >= minutes * 60:
            raise RuntimeError(f"the release pull request #{number} did not merge")
        sleep(30)
        waited += 30
    run("git", "-C", root, "fetch", "-q", "origin", sha)
    run("git", "-C", root, "tag", version, sha)
    run("git", "-C", root, "push", "origin", f"refs/tags/{version}")
    move(major, sha, run, root)
    notes = run("python3", os.path.join(HERE, "changelog.py"), "notes", version)
    run("gh", "release", "create", version, "--repo", repo, "--title", version, "--notes", notes, "--verify-tag", "--latest")
    return {"moved_at": now(), "version": version, "previous": p["previous"]}


def move(major, target, run=sh, root="."):
    """`vN` at `target`, lightweight: a tag with no object of its own (an
    annotated one breaks the organisation's required workflow)."""
    run("git", "-C", root, "tag", "-f", major, f"{target}^{{commit}}")
    run("git", "-C", root, "push", "-f", "origin", f"refs/tags/{major}")


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def act(p, results, repo, run=sh, sleep=time.sleep, root=".", lane_run=""):
    d = decide(p, results)
    if d["do"] == "bug":
        body = d["body"] + (f"\nThe lane's run: {lane_run}\n" if lane_run else "")
        run("gh", "issue", "create", "--repo", repo, "--title", d["title"], "--body", body)
    elif d["do"] == "issue":
        ri = release_issue(p["version"][1:], d["why"], lane_run)
        run("gh", "issue", "create", "--repo", repo, "--title", ri["title"], "--body", ri["body"], *sum((["--label", l] for l in ri["labels"]), []))
    elif d["do"] == "release":
        d.update(release(p, repo, run, sleep, root=root))
    return d


def release_issue(version, why, lane_run=""):
    import importlib.util
    spec = importlib.util.spec_from_file_location("release_issue", os.path.join(HERE, "release-issue.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.engine_issue(version, why, lane_run)


class Fake:
    """A fake `gh` and `git` that records every command."""

    def __init__(self, answers=None):
        self.calls, self.answers = [], answers or {}

    def __call__(self, *argv, input=None):
        self.calls.append(argv)
        for key, value in self.answers.items():
            if " ".join(argv).startswith(key) or key in " ".join(argv):
                return value(argv) if callable(value) else value
        return ""

    def has(self, *prefix):
        return any(c[:len(prefix)] == prefix for c in self.calls)

    def named(self, word):
        return [c for c in self.calls if any(word in str(a) for a in c)]


def self_test():
    failed = 0

    def check(name, got, want=True):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    nxt = {"last": "7.10.0", "next": "7.10.1", "bump": "patch", "pending": True}
    p = plan(nxt, ["fix(autopilot): a stuck draft goes on (#600)"])
    check("plan: a fix since the last release is a patch, not breaking", (p["release"], p["version"], p["previous"], p["major"], p["breaking"]), (True, "v7.10.1", "v7.10.0", "v7", False))
    check("plan: nothing pending, nothing released", plan(dict(nxt, pending=False, bump="none"), [])["release"], False)
    check("plan: a `!` is breaking", plan(dict(nxt, bump="minor", next="7.11.0"), ["feat!: a required input"])["breaking"], True)
    check("plan: a major label is breaking", plan(dict(nxt, bump="major", next="8.0.0"), [])["breaking"], True)

    central = "O/.github"
    text = "jobs:\n  a:\n    uses: O/.github/.github/workflows/autopilot.yml@v7\n  b:\n    uses: ./.github/workflows/x.yml\n"
    moved = rewrite_inner(text, central, "v7")
    check("candidate: the inner calls move to @v7-next", moved, text.replace("autopilot.yml@v7", "autopilot.yml@v7-next"))
    check("candidate: differs from main only in those refs", only_refs_differ({"a.yml": text}, {"a.yml": moved}, "v7"), [])
    check("candidate: anything else is named", only_refs_differ({"a.yml": text}, {"a.yml": moved + "# more\n"}, "v7"), ["a.yml"])

    passed = [{"id": "issue-complete", "ok": True, "why": [], "run": "https://github.com/o/t/actions/runs/1"},
              {"id": "spec-to-draft", "ok": True, "why": [], "run": "https://github.com/o/t/actions/runs/2"}]
    # C4: a fix, main green, every scenario passing.
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        fake = Fake({"gh pr create": "https://github.com/O/.github/pull/700\n",
                     "gh pr view": json.dumps({"mergedAt": "2026-11-02T10:00:00Z", "mergeCommit": {"oid": "abc123"}, "state": "MERGED"}),
                     "changelog.py build": "# Changelog\n", "changelog.py notes": "notes\n"})
        d = act(p, passed, "O/.github", run=fake, sleep=lambda s: None, root=root)
        check("C4: all pass → release", d["do"], "release")
        check("C4: the release pull request is merged", fake.has("gh", "pr", "merge", "700"), True)
        check("C4: vX.Y.Z is tagged at its merge commit, lightweight", (fake.has("git", "-C", root, "tag", "v7.10.1", "abc123"), fake.has("git", "-C", root, "push", "origin", "refs/tags/v7.10.1")), (True, True))
        tags = [c for c in fake.calls if c[3:4] == ("tag",)]
        check("C4: no tag is annotated", any("-a" in c or "-m" in c or "-s" in c for c in tags), False)
        check("C4: v7 points at it, a force push of that ref alone", (fake.has("git", "-C", root, "tag", "-f", "v7", "abc123^{commit}"), fake.has("git", "-C", root, "push", "-f", "origin", "refs/tags/v7")), (True, True))
        check("C4: its GitHub Release is published", fake.has("gh", "release", "create", "v7.10.1"), True)
        check("C4: no person's step: no release issue", fake.has("gh", "issue", "create"), False)
        check("C4: what the watch needs", (d["version"], d["previous"]), ("v7.10.1", "v7.10.0"))
        # C5: one scenario fails.
        fake = Fake()
        failing = passed[:1] + [{"id": "spec-to-draft", "ok": False, "why": ["no label autopilot"], "run": "https://github.com/o/t/actions/runs/9"}]
        d = act(p, failing, "O/.github", run=fake, root=root)
        bug = fake.named("fails scenario")
        check("C5: one fails → a bug", d["do"], "bug")
        check("C5: nothing tagged, v7 not moved, nothing released", [c for c in fake.calls if c[:1] == ("git",) or c[:2] in (("gh", "release"), ("gh", "pr"))], [])
        check("C5: the bug names the scenario and its run", bool(bug) and "spec-to-draft" in " ".join(bug[0]) and "https://github.com/o/t/actions/runs/9" in " ".join(bug[0]), True)
        check("C5: no result at all is a failure", decide(p, [])["do"], "bug")
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    import argparse
    ap = argparse.ArgumentParser(prog="release-lane.py")
    ap.add_argument("mode", choices=("plan", "candidate", "decide", "act"))
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    ap.add_argument("--central", default="")
    ap.add_argument("--plan", default="")
    ap.add_argument("--results", default="")
    ap.add_argument("--run", default="")
    ap.add_argument("--version", default="")
    ap.add_argument("--previous", default="")
    ap.add_argument("--since", default="")
    ap.add_argument("--minutes", type=int, default=30)
    ap.add_argument("--every", type=int, default=120)
    ap.add_argument("--org", default="")
    ap.add_argument("--property", default="")
    a = ap.parse_args(argv)
    sys.path.insert(0, HERE)
    import org
    central = a.central or org.CENTRAL

    def load(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def results_of(path):
        text = open(path, encoding="utf-8").read() if path and os.path.exists(path) else ""
        m = re.search(r"<!-- dx-scenarios (.*) -->", text)
        return json.loads(m.group(1)) if m else []

    if a.mode == "plan":
        nxt = json.loads(sh("python3", os.path.join(HERE, "next-version.py"), "--repo", a.repo, "--tag-prefix", "v", "--json"))
        subjects = sh("git", "log", "--format=%s", f"v{nxt['last']}..HEAD").splitlines()
        print(json.dumps(plan(nxt, subjects)))
        return 0
    if a.mode == "candidate":
        print(candidate(central, load(a.plan)["major"] if a.plan else "v7"))
        return 0
    if a.mode == "decide":
        print(json.dumps(decide(load(a.plan), results_of(a.results))))
        return 0
    if a.mode == "act":
        print(json.dumps(act(load(a.plan), results_of(a.results), a.repo, lane_run=a.run)))
        return 0
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
