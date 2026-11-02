#!/usr/bin/env python3
"""The engine's release lane (#563): a fix merged into a green main reaches
every repository with no person's step, once every release scenario passed
in the test repository; a breaking change waits on a person.

.github/workflows/release-lane.yml runs it on main, never on a fork's code:

  release-lane.py plan --repo R
        what is releasable since the last vX.Y.Z (scripts/next-version.py,
        from the labels of what merged) and whether a commit since says `!`:
        JSON {release, version, previous, major, breaking, why, sha}, `sha`
        the commit planned, the only one the lane may release; exit 0
  release-lane.py candidate --central OWNER/.github
        in a checkout of main: the `release-candidate` commit, main with
        the reusable workflows' inner calls of the engine at `@vN` moved to
        `@vN-next` (GitHub reads them before any expression, so the
        scenarios would otherwise try vN's), checked to differ from main in
        nothing else, made through the API with GH_TOKEN (scripts/api-
        commit.py, so GitHub signs it: never `git commit` and a push from
        the runner, #610), and the lightweight `vN-next` tag moved to it
  release-lane.py decide --plan F --results F
        from the plan and the scenarios' results (scripts/release-scenarios.py
        run): `release`, `bug` (one failed: nothing tagged, nothing moved,
        a bug naming the scenario and its run) or `issue` (a `!`: the
        release issue for a person, nothing tagged); JSON
  release-lane.py act --plan F --results F --repo R [--run URL]
        does what `decide` says. A release, only while main is still the
        plan's `sha` (else `none`): the release pull request (CHANGELOG.md
        from scripts/changelog.py build), merged, `vX.Y.Z` tagged at its
        merge commit when its parent is that `sha`, `vN` moved to it
        (lightweight: `git tag -f` and a force push of that ref alone), its
        GitHub Release published or, when engine-release.yml made it first,
        edited; JSON {moved_at, version, previous[, error]} on stdout, and
        exit 1 when `vN` moved but the Release failed (the watch still runs)
  release-lane.py watch --repo R --version V --previous P --since ISO
                        [--minutes 30] [--every 120] [--org O] [--property P]
        for `--minutes` after `vN` moved, every `--every` seconds: the runs
        of every adopted repository (org.yml `adopted-property`) since the
        move that ended in `startup_failure` or failed in one of the
        engine's own steps of an engine job (ENGINE_STEPS, never the
        product's lint or tests inside it), read with GH_READ_TOKEN; on the
        first, `vN` back at P, a bug with the
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


def sh(*argv, input=None, env=None):
    out = subprocess.run(list(argv), capture_output=True, text=True, input=input, env=env)
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
    # The organisation's ruleset refuses an unsigned commit on any branch
    # (#610): the commit object is built here without `git commit` (empty
    # when nothing moved, as --allow-empty made it), then made again through
    # the API with the App's token (scripts/api-commit.py, GH_TOKEN), which
    # GitHub signs, moves the branch and points the local HEAD at it. It
    # runs from the checkout, which in release-lane.yml is `root`.
    run("git", "-C", root, "add", "-u")
    tree = run("git", "-C", root, "write-tree").strip()
    sha = run("git", "-C", root, "commit-tree", tree, "-p", "HEAD", "-m", f"chore: release candidate, inner calls at @{major}-next").strip()
    run("git", "-C", root, "reset", "-q", "--soft", sha)
    run(sys.executable, os.path.join(HERE, "api-commit.py"), "push", CANDIDATE, "--onto", "HEAD~1", "--force")
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
    """The release pull request, merged, the tag, the move and the Release,
    of the commit the scenarios tried (the plan's `sha`) and nothing else:
    main past it releases nothing (the next green run plans it again), and
    a release pull request merged on a main that moved meanwhile is tagged
    nowhere. Returns {moved_at, version, previous}, with `error` when the
    Release could not be published after `vN` moved (the watch still runs);
    or {do: none, why} when main moved."""
    version, major, planned = p["version"], p["major"], p.get("sha") or ""
    if not planned:
        raise RuntimeError("the plan names no commit: nothing is released that the scenarios did not try")
    run("git", "-C", root, "fetch", "-q", "origin", "main")
    head = run("git", "-C", root, "rev-parse", "origin/main").strip()
    if head != planned:
        return {"do": "none", "why": f"main moved past {planned[:12]}, the commit the scenarios tried: its own green run plans it again"}
    branch = f"chore/release-{version}"
    run("git", "-C", root, "checkout", "-B", branch, planned)
    log = run("python3", os.path.join(HERE, "changelog.py"), "build", "--next", version, "--head", planned)
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
    parent = run("git", "-C", root, "rev-parse", f"{sha}^").strip()
    if parent != planned:
        raise RuntimeError(f"the release pull request #{number} merged onto {parent[:12]}, not {planned[:12]}, the commit the scenarios tried: nothing tagged, {major} did not move")
    run("git", "-C", root, "tag", version, sha)
    run("git", "-C", root, "push", "origin", f"refs/tags/{version}")
    move(major, sha, run, root)
    out = {"moved_at": now(), "version": version, "previous": p["previous"]}
    # From here `vN` moved: whatever fails, the watch must still run.
    try:
        notes = run("python3", os.path.join(HERE, "changelog.py"), "notes", version)
        publish(version, notes, repo, run)
    except RuntimeError as err:
        out["error"] = f"{major} moved to {version}, but its Release could not be published: {err}"
    return out


def publish(version, notes, repo, run=sh):
    """The GitHub Release of `version`: engine-release.yml also makes it on
    the tag's push, so the one that exists is edited, and a create that
    lost the race edits the one the workflow made."""
    edit = ("gh", "release", "edit", version, "--repo", repo, "--title", version, "--notes", notes, "--latest")
    try:
        run("gh", "release", "view", version, "--repo", repo, "--json", "tagName")
    except RuntimeError:
        try:
            run("gh", "release", "create", version, "--repo", repo, "--title", version, "--notes", notes, "--verify-tag", "--latest")
            return
        except RuntimeError:
            pass
    run(*edit)


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


# The watch.

# The steps of an engine job that are the engine's own, not the product's:
# the runner resolving the engine's actions, and the engine's checkouts of
# its scripts and configuration. A product's lint, test or review that fails
# inside an engine job is the product's, and moves nothing back.
ENGINE_STEPS = ("Set up job", "The organisation's configuration (#197)", "The organisation's scripts and policy", "The scripts")


def engine_failure(run_, central):
    """Whether a run, as `gh api repos/R/actions/runs/ID` gives it with its
    failed jobs (`failed_jobs`: {name, steps}, the names of the steps that
    failed), failed on the engine: it never started, or a job of a workflow
    of the engine (one of its `referenced_workflows`, whose jobs are named
    `<caller> / <job>`) failed in one of ENGINE_STEPS. Pure."""
    if run_.get("conclusion") == "startup_failure":
        return True
    if run_.get("conclusion") != "failure":
        return False
    engine = any(str(w.get("path", "")).startswith(f"{central}/.github/workflows/") for w in run_.get("referenced_workflows") or [])
    return engine and any(isinstance(j, dict) and " / " in str(j.get("name", "")) and any(st in ENGINE_STEPS for st in j.get("steps") or [])
                          for j in run_.get("failed_jobs") or [])


def first_failure(runs, central, since, minutes=30):
    """The first run, by its start, within `minutes` after `since` that
    failed on the engine, or None. Pure."""
    start = parse_time(since)
    end = start + datetime.timedelta(minutes=minutes)
    inside = [r for r in runs if start <= parse_time(r.get("created_at")) <= end and engine_failure(r, central)]
    return min(inside, key=lambda r: parse_time(r.get("created_at"))) if inside else None


def parse_time(value):
    return datetime.datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)


def pages(text):
    """The items of `gh api --paginate --jq` output, which prints one JSON
    array per page: every page's array, joined. Pure."""
    out, text, at = [], text or "", 0
    decoder = json.JSONDecoder()
    while True:
        while at < len(text) and text[at].isspace():
            at += 1
        if at >= len(text):
            return out
        value, at = decoder.raw_decode(text, at)
        out.extend(value if isinstance(value, list) else [value])


def adopted(org_name, prop, run=sh):
    values = pages(run("gh", "api", "--paginate", f"orgs/{org_name}/properties/values?per_page=100", "--jq", "[.[]]"))
    return sorted(v["repository_full_name"] for v in values
                  if any(p.get("property_name") == prop and str(p.get("value")).lower() == "true" for p in v.get("properties") or []))


def runs_since(full, since, run=sh):
    listed = pages(run("gh", "api", "--paginate", f"repos/{full}/actions/runs?created=>={since}&per_page=100", "--jq", ".workflow_runs"))
    out = []
    for r in listed:
        if r.get("conclusion") == "failure":
            jobs = pages(run("gh", "api", "--paginate", f"repos/{full}/actions/runs/{r['id']}/jobs?per_page=100", "--jq", "[.jobs[] | select(.conclusion == \"failure\") | {name, steps: [.steps[]? | select(.conclusion == \"failure\") | .name]}]"))
            r = dict(r, failed_jobs=jobs)
        out.append(r)
    return out


def rollback(p, failure, repo, run=sh, root="."):
    """`vN` back at the previous release, a bug with the run's link, and
    the release says so."""
    major, link = p["major"], failure.get("html_url", "")
    move(major, p["previous"], run, root)
    run("gh", "issue", "create", "--repo", repo, "--title", f"fix: {p['version']} failed in a repository; {major} is back at {p['previous']}",
        "--body", f"{MARK}\nWithin 30 minutes of `{major}` moving to {p['version']}, a run failed on the engine: {link}\n\n`{major}` points at {p['previous']} again.\n")
    body = json.loads(run("gh", "release", "view", p["version"], "--repo", repo, "--json", "body") or "{}").get("body", "")
    run("gh", "release", "edit", p["version"], "--repo", repo, "--notes",
        f"> {major} moved back to {p['previous']}: this release failed in a repository ({link}).\n\n{body}")


def watch(p, repo, central, org_name, prop, since, run=sh, sleep=time.sleep, minutes=30, every=120, root=".", read=None):
    """Returns the failed run it rolled back on, or None. `read` reads every
    repository's runs (a read-only token for the installation); `run`
    writes, in this repository alone (its tags, issues and Release)."""
    read = read or run
    waited = 0
    while True:
        # A read that fails is tried again at the next poll, never taken for
        # a quiet half hour: the last poll failing is an error.
        try:
            runs = [r for full in adopted(org_name, prop, read) for r in runs_since(full, since, read)]
            failed = ""
        except (RuntimeError, ValueError) as err:
            runs, failed = [], str(err)
            print(f"::warning::the watch could not read the runs: {failed}", file=sys.stderr)
        bad = first_failure(runs, central, since, minutes)
        if bad:
            rollback(p, bad, repo, run, root)
            return bad
        if waited >= minutes * 60:
            if failed:
                raise RuntimeError(f"the watch could not read the runs at its last poll, nothing is known of the last minutes: {failed}")
            return None
        sleep(every)
        waited += every


def _raises(fn):
    try:
        fn()
    except RuntimeError as err:
        return err
    return None


def check_workflow(check, path=os.path.join(ROOT, ".github", "workflows", "release-lane.yml")):
    """What the self-test cannot see in a fake: the tokens release-lane.yml
    mints, and that the watch runs once `vN` moved even when `act` failed."""
    import yaml
    jobs = (yaml.safe_load(open(path, encoding="utf-8")) or {}).get("jobs") or {}

    def tokens(job):
        return [st.get("with") or {} for st in jobs.get(job, {}).get("steps") or [] if "create-github-app-token" in str(st.get("uses"))]
    cand = tokens("candidate")
    check("workflow: the candidate's token may push the workflow files it rewrites", [t.get("permission-workflows") for t in cand], ["write"])
    envs = [st.get("env") or {} for st in jobs.get("candidate", {}).get("steps") or [] if "release-lane.py candidate" in str(st.get("run"))]
    check("workflow: the candidate's commit is made with the App's token (#610)", [e.get("GH_TOKEN") for e in envs], ["${{ steps.app.outputs.token }}"])
    watch_tokens = tokens("watch")
    writes = [t for t in watch_tokens if any(v == "write" for k, v in t.items() if k.startswith("permission-"))]
    check("workflow: the watch's write token is this repository's alone", bool(writes) and all(t.get("repositories") for t in writes), True)
    wide = [t for t in watch_tokens if not t.get("repositories")]
    check("workflow: the watch's installation-wide token only reads", bool(wide) and all(v in ("read",) for t in wide for k, v in t.items() if k.startswith("permission-")), True)
    check("workflow: the watch runs once v7 moved, even when act failed after", "always()" in str(jobs.get("watch", {}).get("if")), True)


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
    p = dict(plan(nxt, ["fix(autopilot): a stuck draft goes on (#600)"]), sha="p1")
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
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, ".github", "workflows"))
        with open(os.path.join(root, ".github", "workflows", "a.yml"), "w", encoding="utf-8") as fh:
            fh.write("on:\n  workflow_call:\n" + text)
        fake = Fake()
        candidate(central, "v7", root=root, run=fake)
        words = [[str(a) for a in c] for c in fake.calls]
        check("candidate: no commit is made in the runner (#610)", [c for c in words if c[:1] == ["git"] and "commit" in c], [])
        check("candidate: no branch is pushed from the runner (#610)", [c for c in words if c[:1] == ["git"] and "push" in c and any(a.startswith("refs/heads/") or a.startswith("HEAD:") for a in c)], [])
        check("candidate: its commit goes through the API, signed (#610)", [c[2:] for c in words if c[1:2] and c[1].endswith("api-commit.py")], [["push", CANDIDATE, "--onto", "HEAD~1", "--force"]])
        check("candidate: v7-next is moved at the signed commit", fake.has("git", "-C", root, "push", "-f", "origin", "refs/tags/v7-next"), True)

    passed = [{"id": "issue-complete", "ok": True, "why": [], "run": "https://github.com/o/t/actions/runs/1"},
              {"id": "spec-to-draft", "ok": True, "why": [], "run": "https://github.com/o/t/actions/runs/2"}]
    # C4: a fix, main green, every scenario passing.
    with tempfile.TemporaryDirectory() as root:
        def missing(argv):
            raise RuntimeError("release not found")

        def merged(parent="p1", main="p1", **more):
            return Fake({"rev-parse origin/main": main + "\n", "rev-parse abc123^": parent + "\n",
                         "gh pr create": "https://github.com/O/.github/pull/700\n",
                         "gh pr view": json.dumps({"mergedAt": "2026-11-02T10:00:00Z", "mergeCommit": {"oid": "abc123"}, "state": "MERGED"}),
                         "changelog.py build": "# Changelog\n", "changelog.py notes": "notes\n", **more})
        fake = merged(**{"gh release view": missing})
        d = act(p, passed, "O/.github", run=fake, sleep=lambda s: None, root=root)
        check("C4: all pass → release", d["do"], "release")
        check("C4: the release is built from the commit the scenarios tried", (fake.has("git", "-C", root, "checkout", "-B", "chore/release-v7.10.1", "p1"), bool([c for c in fake.named("changelog.py") if "build" in c and c[-1] == "p1"])), (True, True))
        check("C4: the release pull request is merged", fake.has("gh", "pr", "merge", "700"), True)
        check("C4: vX.Y.Z is tagged at its merge commit, lightweight", (fake.has("git", "-C", root, "tag", "v7.10.1", "abc123"), fake.has("git", "-C", root, "push", "origin", "refs/tags/v7.10.1")), (True, True))
        tags = [c for c in fake.calls if c[3:4] == ("tag",)]
        check("C4: no tag is annotated", any("-a" in c or "-m" in c or "-s" in c for c in tags), False)
        check("C4: v7 points at it, a force push of that ref alone", (fake.has("git", "-C", root, "tag", "-f", "v7", "abc123^{commit}"), fake.has("git", "-C", root, "push", "-f", "origin", "refs/tags/v7")), (True, True))
        check("C4: its GitHub Release is published", fake.has("gh", "release", "create", "v7.10.1"), True)
        check("C4: no person's step: no release issue", fake.has("gh", "issue", "create"), False)
        check("C4: what the watch needs", (d["version"], d["previous"], "error" in d), ("v7.10.1", "v7.10.0", False))
        # Main moved past the commit the scenarios tried.
        fake = merged(main="p2")
        d = act(p, passed, "O/.github", run=fake, sleep=lambda s: None, root=root)
        check("main moved since the plan: nothing released, the next green run plans it", (d["do"], fake.has("gh", "pr"), [c for c in fake.calls if c[3:4] == ("tag",)]), ("none", False, []))
        fake = merged(parent="p2")
        try:
            act(p, passed, "O/.github", run=fake, sleep=lambda s: None, root=root)
            raised = False
        except RuntimeError as err:
            raised = "nothing tagged" in str(err)
        check("main moved while the release pull request waited: an error, nothing tagged, v7 not moved", (raised, [c for c in fake.calls if c[3:4] == ("tag",)]), (True, []))
        fake = Fake()
        check("a plan with no commit releases nothing", ("no commit" in str(_raises(lambda: release(dict(p, sha=""), "O/.github", run=fake, root=root))), fake.calls), (True, []))
        # engine-release.yml made the Release first.

        def created_first(argv):
            raise RuntimeError("a release with the same tag name already exists")
        fake = merged(**{"gh release view": missing, "gh release create": created_first})
        d = act(p, passed, "O/.github", run=fake, sleep=lambda s: None, root=root)
        check("the Release made by engine-release.yml first is edited, not an error", (fake.has("gh", "release", "edit", "v7.10.1"), "error" in d), (True, False))
        fake = merged()
        act(p, passed, "O/.github", run=fake, sleep=lambda s: None, root=root)
        check("a Release that exists already is edited, never created twice", (fake.has("gh", "release", "edit", "v7.10.1"), fake.has("gh", "release", "create")), (True, False))
        fake = merged(**{"gh release": missing})
        d = act(p, passed, "O/.github", run=fake, sleep=lambda s: None, root=root)
        check("the Release fails after v7 moved: still a release, with its error and what the watch needs",
              (d["do"], bool(d.get("error")), bool(d.get("moved_at")), fake.has("git", "-C", root, "push", "-f", "origin", "refs/tags/v7")), ("release", True, True, True))
        # C5: one scenario fails.
        fake = Fake()
        failing = passed[:1] + [{"id": "spec-to-draft", "ok": False, "why": ["no label autopilot"], "run": "https://github.com/o/t/actions/runs/9"}]
        d = act(p, failing, "O/.github", run=fake, root=root)
        bug = fake.named("fails scenario")
        check("C5: one fails → a bug", d["do"], "bug")
        check("C5: nothing tagged, v7 not moved, nothing released", [c for c in fake.calls if c[:1] == ("git",) or c[:2] in (("gh", "release"), ("gh", "pr"))], [])
        check("C5: the bug names the scenario and its run", bool(bug) and "spec-to-draft" in " ".join(bug[0]) and "https://github.com/o/t/actions/runs/9" in " ".join(bug[0]), True)
        check("C5: no result at all is a failure", decide(p, [])["do"], "bug")
        # C7: a `!`, the scenarios pass.
        fake = Fake()
        pb = plan(dict(nxt, bump="minor", next="7.11.0"), ["feat(autopilot)!: a required input"])
        d = act(pb, passed, "O/.github", run=fake, root=root)
        issue = [c for c in fake.calls if c[:3] == ("gh", "issue", "create")]
        check("C7: a breaking change whose scenarios pass → the release issue", d["do"], "issue")
        check("C7: the release issue is the Release form's", bool(issue) and ("--title", "Release 7.11.0") == issue[0][5:7] and "lane:release" in issue[0], True)
        check("C7: nothing tagged, nothing moved", [c for c in fake.calls if c[:1] == ("git",) or c[:2] == ("gh", "release")], [])
        # C6: a startup_failure within 30 minutes of the move.
        since = "2026-11-02T10:00:00Z"
        runs = [{"id": 1, "created_at": "2026-11-02T10:05:00Z", "conclusion": "success", "html_url": "u1"},
                {"id": 2, "created_at": "2026-11-02T10:12:00Z", "conclusion": "startup_failure", "html_url": "https://github.com/O/a/actions/runs/2"},
                {"id": 3, "created_at": "2026-11-02T10:45:00Z", "conclusion": "startup_failure", "html_url": "late"}]
        check("C6: the first engine failure within 30 minutes", first_failure(runs, central, since)["id"], 2)
        check("C6: one after 30 minutes is not the release's", first_failure(runs[2:], central, since), None)
        own = {"conclusion": "failure", "referenced_workflows": [{"path": "O/.github/.github/workflows/issue-triage.yml@v7"}],
               "failed_jobs": [{"name": "triage / classify", "steps": ["The organisation's configuration (#197)"]}]}
        check("C6: an engine job failing in one of the engine's own steps is the engine's", engine_failure(own, central), True)
        check("C6: a failure in the repository's own job is not", engine_failure(dict(own, failed_jobs=[{"name": "build", "steps": ["Set up job"]}]), central), False)
        check("C6: the product's test failing inside an engine job is the product's, never a rollback",
              engine_failure(dict(own, failed_jobs=[{"name": "checks / tests", "steps": ["PHPUnit"]}]), central), False)
        quiet = Fake({"properties/values": json.dumps([{"repository_full_name": "O/a", "properties": [{"property_name": "dx-adopted", "value": "true"}]}]),
                      "repos/O/a/actions/runs?": json.dumps([dict(own, id=5, created_at="2026-11-02T10:05:00Z", failed_jobs=None)]),
                      "runs/5/jobs": json.dumps([{"name": "checks / tests", "steps": ["PHPUnit"]}])})
        check("C6: a red test in an adopted repository moves nothing back",
              (watch(dict(p, version="v7.10.1", previous="v7.10.0"), "O/.github", central, "O", "dx-adopted", "2026-11-02T10:00:00Z", run=Fake(), read=quiet, sleep=lambda s: None, every=1800, root=root)), None)
        props = json.dumps([{"repository_full_name": "O/a", "properties": [{"property_name": "dx-adopted", "value": "true"}]},
                            {"repository_full_name": "O/b", "properties": [{"property_name": "dx-adopted", "value": "false"}]}])
        reader = Fake({"properties/values": props, "repos/O/a/actions/runs?": json.dumps(runs[:2])})
        fake = Fake({"gh release view": json.dumps({"body": "notes"})})
        moved_p = dict(p, version="v7.10.1", previous="v7.10.0")
        bad = watch(moved_p, "O/.github", central, "O", "dx-adopted", since, run=fake, sleep=lambda s: None, root=root, read=reader)
        check("C6: the watch reads only the adopted repositories", (bool(reader.named("repos/O/a/")), bool(reader.named("repos/O/b/"))), (True, False))
        check("C6: the other repositories are only read, with the read token; every write is this repository's",
              (all(c[:2] == ("gh", "api") and "-X" not in c for c in reader.calls), all("repos/O/a" not in " ".join(c) for c in fake.calls)), (True, True))
        check("C6: v7 points at the previous release again", (fake.has("git", "-C", root, "tag", "-f", "v7", "v7.10.0^{commit}"), fake.has("git", "-C", root, "push", "-f", "origin", "refs/tags/v7")), (True, True))
        made = [c for c in fake.calls if c[:3] == ("gh", "issue", "create")]
        check("C6: a bug with the run's link", bool(made) and "https://github.com/O/a/actions/runs/2" in " ".join(made[0]), True)
        edit = [c for c in fake.calls if c[:3] == ("gh", "release", "edit")]
        check("C6: the release says so", bool(edit) and "moved back to v7.10.0" in " ".join(edit[0]) and bad["id"] == 2, True)
        two = (json.dumps([{"repository_full_name": "O/a", "properties": [{"property_name": "dx-adopted", "value": "true"}]}]) + "\n"
               + json.dumps([{"repository_full_name": "O/c", "properties": [{"property_name": "dx-adopted", "value": "true"}]}]) + "\n")
        check("C6: two pages of properties are both read", adopted("O", "dx-adopted", Fake({"properties/values": two})), ["O/a", "O/c"])
        check("C6: two pages of runs are both read", [r["id"] for r in runs_since("O/a", since, Fake({"actions/runs?": json.dumps(runs[:1]) + "\n" + json.dumps(runs[1:]) + "\n"}))], [1, 2, 3])
        check("C6: every list is read with --paginate", all("--paginate" in c for c in reader.calls), True)
        broken = Fake({"properties/values": lambda argv: (_ for _ in ()).throw(RuntimeError("HTTP 502"))})
        err = _raises(lambda: watch(moved_p, "O/.github", central, "O", "dx-adopted", since, run=Fake(), read=broken, sleep=lambda s: None, every=1800, root=root))
        check("C6: a read that keeps failing is an error, never a quiet half hour", "could not read" in str(err), True)
        flaky = iter([RuntimeError("HTTP 502")])

        def once(argv):
            e = next(flaky, None)
            if e:
                raise e
            return props
        fake = Fake({"gh release view": json.dumps({"body": "notes"})})
        bad = watch(moved_p, "O/.github", central, "O", "dx-adopted", since, run=fake, sleep=lambda s: None, root=root,
                    read=Fake({"properties/values": once, "repos/O/a/actions/runs?": json.dumps(runs[:2])}))
        check("C6: a read that fails once is tried again at the next poll", (bad or {}).get("id"), 2)
        fake = Fake({"properties/values": props, "repos/O/a/actions/runs?": json.dumps(runs[:1])})
        check("C6: a quiet half hour moves nothing", (watch(moved_p, "O/.github", central, "O", "dx-adopted", since, run=fake, sleep=lambda s: None, every=600, root=root), fake.has("git")), (None, False))
    check_workflow(check)
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    import argparse
    ap = argparse.ArgumentParser(prog="release-lane.py")
    ap.add_argument("mode", choices=("plan", "candidate", "decide", "act", "watch"))
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
        print(json.dumps(dict(plan(nxt, subjects), sha=sh("git", "rev-parse", "HEAD").strip())))
        return 0
    if a.mode == "candidate":
        print(candidate(central, load(a.plan)["major"] if a.plan else "v7"))
        return 0
    if a.mode == "decide":
        print(json.dumps(decide(load(a.plan), results_of(a.results))))
        return 0
    if a.mode == "act":
        d = act(load(a.plan), results_of(a.results), a.repo, lane_run=a.run)
        print(json.dumps(d))
        if d.get("error"):
            print(f"::error::{d['error']}", file=sys.stderr)
        return 1 if d.get("error") else 0
    if a.mode == "watch":
        conf = org.load()
        p = {"version": a.version, "previous": a.previous, "major": f"v{a.version.lstrip('v').split('.')[0]}"}
        # GH_READ_TOKEN reads every repository's runs; GH_TOKEN writes here.
        token = os.environ.get("GH_READ_TOKEN") or os.environ.get("GH_TOKEN", "")
        read_env = dict(os.environ, GH_TOKEN=token)

        def read(*argv, input=None):
            return sh(*argv, input=input, env=read_env)
        bad = watch(p, a.repo, central, a.org or org.ORG, a.property or str(conf.get("adopted-property") or "dx-adopted"), a.since,
                    minutes=a.minutes, every=a.every, read=read)
        print(json.dumps({"rolled_back": bool(bad), "run": (bad or {}).get("html_url", "")}))
        return 0
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
