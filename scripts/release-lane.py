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
  release-lane.py decide --plan F --results F [--run URL]
        from the plan and the scenarios' results (scripts/release-scenarios.py
        run): `release`, `bug` (one failed: nothing tagged, nothing moved,
        and one filing per scenario that failed after its retry, #843, in
        the issue schema's sections so G1 passes it, #694, with its
        class, `classify`: an `engine` failure a bug, a `harness` or an
        `infrastructure` one a Task, each with the scenario's mark) or
        `issue` (a `!`: the release issue for a person, nothing tagged); JSON.
        `act` names too, as a warning that fails nothing (#843), the pairs
        no scenario's runs triggered, which merge recorded
  release-lane.py act --plan F --results F --repo R [--run URL]
        does what `decide` says, and names in a Flaky line (on stderr and
        in GITHUB_STEP_SUMMARY, #843) each scenario that failed, then
        passed on its retry, which fails nothing. A failure is a comment on
        its scenario's open report (the lane's mark and the scenario's),
        else a new issue (#843). A release, only while main is still the
        plan's `sha` (else `none`): the release pull request (CHANGELOG.md
        from scripts/changelog.py build, its commit made through the API
        with GH_TOKEN by scripts/api-commit.py, so GitHub signs it, #780),
        merged by the lane itself once its required checks pass and every
        other check finished (`gh pr merge --squash --match-head-commit`,
        never auto-merge, which never merges a CHANGELOG.md-only pull
        request, `risk:high`, #798), `vX.Y.Z` tagged at its
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
        err = RuntimeError(f"{' '.join(argv[:3])}: {(out.stderr or out.stdout).strip()}")
        # What it printed, kept: `gh pr checks` exits 8 or 1 with its JSON.
        err.stdout, err.stderr = out.stdout, out.stderr
        raise err
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

def visible(text):
    """`text` with its HTML comments shown, never hidden: a scenario's why
    may quote a marker. Pure."""
    return str(text).replace("<!--", "&lt;!--").replace("-->", "--&gt;")


# The lane's run, as GitHub names it: the reproduction of a bug it opens
# (#699 C6), named in the `bugfix-reproduced` lane's mark.
RUN_URL = re.compile(r"^https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/actions/runs/[0-9]+$")
REPRO_LANE = "bugfix-reproduced"


def bug_body(happened, reproduce, problem, scope, criterion, criticality="Critical", lane_run="", scenario="", task=False):
    """A bug the lane opens itself (#694), in the issue schema's sections
    (policy/issue-schema.yml): its mark first, the report's (What happened?,
    Steps to reproduce), then the PRD's (Problem, Scope, Out of scope,
    Acceptance criteria, Criticality), so G1 passes it and it goes the
    reproduced-bug way, never `incomplete`. Pure."""
    # With the lane's run (#699 C6), the `bugfix-reproduced` lane's mark
    # after the lane's own: the lane accepts it by policy, that run its
    # reproduction (policy/autonomy.yml origin, the Problem's line).
    lane = f"<!-- dx-lane: {REPRO_LANE} run: {lane_run} -->\n" if lane_run else ""
    # #843: the scenario's own mark after the lane's, first in What
    # happened? (the schema allows only its own marks before the first
    # heading), which finds its open report; a Task's body starts with its
    # first heading, the lane's mark under it, so the triage, which takes a
    # body that starts with the mark as a bug (issue-triage.yml `nightly`),
    # leaves it to a person.
    mine = f"{scenario_mark(scenario)}\n" if scenario else ""
    head, under = ("", f"{MARK}\n{mine}") if task else (f"{MARK}\n{lane}", mine)
    return (f"{head}### What happened?\n\n{under}{happened}\n\n### Steps to reproduce\n\n{reproduce}\n\n### Problem\n\n{problem}\n\n### Scope\n\n"
            + "".join(f"- {item}\n" for item in scope)
            + "\n### Out of scope\n\n- Changing the gates or what they check.\n\n### Acceptance criteria\n\n"
            + f"- C1: {criterion}\n\n### Criticality\n\n{criticality}\n")


# What failed a scenario (#843), each row's `class`, set where the row is
# made (scripts/release-scenarios.py): the engine's own behaviour, the
# player (its code, its fixtures, a precondition that did not hold before
# the engine acted, the callers' move), or GitHub (failing or rate limited
# until the scenario's time ran out, a job cancelled or past its timeout, a
# run held or never started).
CLASSES = ("engine", "harness", "infrastructure")
# How each class is filed: its title, its Type, and what its PRD says.
FILED = {
    "engine": ("fix: release scenario {sid} fails", "Bug"),
    "harness": ("test: release scenario {sid} fails in the harness", "Task"),
    "infrastructure": ("ci: release scenario {sid} fails on infrastructure", "Task"),
}
WHERE = {
    "engine": "in what the engine did: its `until` or `expect` did not hold, or could no longer hold",
    "harness": "in the harness, not in what the engine did: scripts/release-scenarios.py, the scenario's fixtures in tests/release/scenarios.yml, "
               "or a precondition of the scenario that did not hold before the engine acted",
    "infrastructure": "on GitHub's side, not in what the engine did: GitHub failing or rate limited until the scenario's time ran out, "
                      "a job cancelled or past its timeout, or a run GitHub held or never started",
}
FIX = {
    "engine": "The cause of the failure above, in the engine, fixed with a test that would have caught it.",
    "harness": "The cause of the failure above, in scripts/release-scenarios.py or the scenario's fixtures, fixed with a test that would have caught it.",
    "infrastructure": "What made the scenario fail on GitHub's side (its limits, its polling, the job's time), made to hold, or the scenario made to wait it out.",
}


def classify(row):
    """The class of a failing row (#843): its `class`, or `engine` for a
    row with none (an older results file), so a failure is never hidden as
    someone else's. Pure."""
    c = str(row.get("class") or "")
    return c if c in CLASSES else "engine"


def scenario_mark(sid):
    """The mark of a scenario's report (#843): its open report is found by
    it, and the lane's next failure of it comments there. Pure."""
    return f"<!-- dx-lane-scenario: {re.sub(r'[^A-Za-z0-9._-]', '-', str(sid))} -->"


def filing(p, r, lane_run=""):
    """The report of one scenario that failed after its retry (#843): its
    class, title, Type and body, in the issue schema's sections, so G1
    passes it. Only an engine failure is a bug: its body starts with the
    lane's mark (the triage's bug) and carries the `bugfix-reproduced`
    lane's, with the lane's run as its reproduction; a harness or an
    infrastructure failure is a Task, the lane's mark under its first
    heading. Pure."""
    sid, cls = str(r.get("id")), classify(r)
    title, kind = FILED[cls]
    bug = cls == "engine"
    run = lane_run if bug and RUN_URL.match(lane_run or "") else ""
    why = visible("; ".join(str(w) for w in r.get("why") or []) or "failed")
    tries = f" (it failed on each of its {r['attempts']} attempts)" if isinstance(r.get("attempts"), int) and r["attempts"] > 1 else ""
    body = bug_body(
        f"Class: {cls}\n\nThe release lane tried {p['version']} at `{p['major']}-next` in the test repository, and the scenario `{sid}` failed{tries}, {WHERE[cls]}. "
        f"Nothing was tagged and `{p['major']}` did not move.\n\n- `{sid}`: {why} ({r.get('run') or 'no run'})"
        + (f"\n\nThe lane's run: {lane_run}" if lane_run else ""),
        f"Run the release lane (.github/workflows/release-lane.yml) on {p['version']}'s candidate: it plays every scenario of tests/release/scenarios.yml "
        f"in the test repository at `{p['major']}-next` (scripts/release-scenarios.py play), `{sid}` among them.",
        f"The release candidate {p['version']} fails the release scenario `{sid}` {WHERE[cls]}, so the lane releases nothing and `{p['major']}` stays where it is."
        + (f"\nReproduced by: {lane_run} scenario `{sid}`." if run else ""),
        [FIX[cls]],
        f"Given {p['version']}'s candidate with the fix, when the release lane plays `{sid}` in the test repository, then it passes and the lane releases it.",
        lane_run=run, scenario=sid, task=not bug)
    return {"scenario": sid, "class": cls, "type": kind, "title": title.format(sid=sid), "body": body,
            "run": str(r.get("run") or ""), "why": why}


def decide(p, results, lane_run=""):
    """What the lane does, from its plan and the scenarios' results, and the
    lane's run (`lane_run`) a bug names: `bug` with one filing per scenario
    that failed after its retry (#843, `filing`), the first's also at the
    top (`scenario`, `run`, `title`, `body`). Pure."""
    if not p.get("release"):
        return {"do": "none", "why": p.get("why", "")}
    failed = [r for r in results if not r.get("ok")]
    if not results:
        failed = [{"id": "(none ran)", "why": ["no scenario result"], "run": "", "class": "harness"}]
    if failed:
        filings = [filing(p, r, lane_run) for r in failed]
        first = filings[0]
        return {"do": "bug", "scenario": first["scenario"], "run": first["run"], "title": first["title"], "body": first["body"], "filings": filings}
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
    pr = release_pull(p)
    engine_post().refuse("pull", pr["title"], pr["branch"], pr["body"])
    branch = pr["branch"]
    # An earlier lane's release pull request of this version, still open
    # (#925): its own is reused (the push below replaces its commit); one
    # someone else opened stops the lane before anything is pushed.
    stale = own_open_pull(repo, branch, run)
    run("git", "-C", root, "checkout", "-B", branch, planned)
    log = run("python3", os.path.join(HERE, "changelog.py"), "build", "--next", version, "--head", planned)
    with open(os.path.join(root, "CHANGELOG.md"), "w", encoding="utf-8") as fh:
        fh.write(log)
    run("git", "-C", root, "commit", "-qam", f"chore: release {version}")
    # The ruleset refuses an unsigned commit on any branch (#610, #780): the
    # commit is made again through the API with GH_TOKEN (scripts/api-
    # commit.py), which GitHub signs, onto the planned commit, which is main
    # on GitHub. It runs from the checkout, as candidate() does.
    run(sys.executable, os.path.join(HERE, "api-commit.py"), "push", branch, "--onto", "HEAD~1", "--force")
    if stale:
        number = str(stale)
        run("gh", "pr", "edit", number, "--repo", repo, "--title", pr["title"], "--body", pr["body"])
    else:
        url = run("gh", "pr", "create", "--repo", repo, "--base", "main", "--head", branch, "--title", pr["title"], "--body", pr["body"]).strip()
        number = url.rstrip("/").rsplit("/", 1)[-1]
    sha = merge_when_checked(repo, number, run, sleep, minutes)
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


def lane_logins():
    """The logins the App opens pull requests as (scripts/org.py)."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import org
    return {org.APP, f"app/{org.APP}", org.BOT}


def own_open_pull(repo, branch, run=sh):
    """The number of the lane's own open release pull request of BRANCH
    (#925: one an earlier lane left, with the lane's MARK, opened by the
    App), or None when none is open. Raises, closing nothing, on one open
    there that is not the lane's."""
    pulls = json.loads(run("gh", "pr", "list", "--repo", repo, "--head", branch, "--state", "open", "--json", "number,body,author") or "[]")
    mine = lane_logins()
    for pull in pulls:
        author = pull.get("author") or {}
        login = author.get("login", "") if isinstance(author, dict) else str(author)
        if MARK not in str(pull.get("body") or "") or login not in mine:
            raise RuntimeError(f"#{pull.get('number')} is open on {branch} and is not the release lane's: nothing pushed, closed or tagged; close it or let it merge, then dispatch the lane")
    return pulls[0]["number"] if pulls else None


DONE = ("COMPLETED", "SUCCESS", "FAILURE", "ERROR")


def required_checks(repo, number, run=sh):
    """The release pull request's required checks, [{name, bucket}]: none
    while GitHub reports none yet, and what `gh pr checks` prints even when
    it exits non-zero (8 while one is pending, 1 when one failed)."""
    try:
        out = run("gh", "pr", "checks", number, "--repo", repo, "--required", "--json", "name,bucket")
    except RuntimeError as err:
        printed = getattr(err, "stdout", "") or ""
        if printed.strip():
            return json.loads(printed)
        text = (getattr(err, "stderr", "") or "") + str(err)
        if "no required checks reported" in text or "no checks reported" in text:
            return []
        raise
    return json.loads(out or "[]")


def merge_when_checked(repo, number, run=sh, sleep=time.sleep, minutes=60):
    """The release pull request merged by the lane itself, never by
    auto-merge (#798: it changes only CHANGELOG.md, which the review floors
    to `risk:high`, and the auto-merge decision never merges that): once
    its required checks pass at the head first seen and every other check
    there finished, `gh pr merge --squash --match-head-commit`, once, which
    merges or queues in the merge queue and never goes past either; then
    waited for until it merged. Returns the merge commit. Raises on a
    required check that fails or is cancelled, a pull request that closes,
    a head that moves, or `minutes` running out, naming what it waited on."""
    head, waited, queued, why, settled = "", 0, False, "its checks did not finish", None
    while True:
        view = json.loads(run("gh", "pr", "view", number, "--repo", repo, "--json", "mergedAt,mergeCommit,state,headRefOid,statusCheckRollup") or "{}")
        if view.get("mergedAt"):
            return (view.get("mergeCommit") or {}).get("oid", "")
        if view.get("state") == "CLOSED":
            raise RuntimeError(f"the release pull request #{number} closed unmerged: nothing tagged")
        seen = view.get("headRefOid") or ""
        head = head or seen
        if seen and seen != head:
            raise RuntimeError(f"the release pull request #{number} changed head ({seen[:12]}, not {head[:12]}): nothing tagged")
        if not queued and head:
            required = required_checks(repo, number, run)
            bad = [c.get("name") for c in required if c.get("bucket") in ("fail", "cancel")]
            if bad:
                raise RuntimeError(f"the release pull request #{number} failed its required check {bad[0]}: nothing tagged")
            rollup = view.get("statusCheckRollup") or []
            pending = [c.get("name") or c.get("context") for c in rollup if (c.get("status") or c.get("state") or "").upper() not in DONE]
            pending += [c.get("name") for c in required if c.get("bucket") not in ("pass", "skipping")]
            # No required check reported may only mean GitHub has not
            # registered them yet: a finished rollup is trusted then only
            # when the next poll finds the same one, still with none.
            done = sorted(str(c.get("name") or c.get("context")) for c in rollup) if rollup and not pending else None
            if done is not None and (required or done == settled):
                run("gh", "pr", "merge", number, "--repo", repo, "--squash", "--match-head-commit", head)
                queued, why = True, "it did not merge from the merge queue"
            else:
                settled = done if not required else None
                why = (f"its check {pending[0]} did not finish" if pending
                       else "it reported no required check yet" if done is not None else "it reported no check")
        if waited >= minutes * 60:
            raise RuntimeError(f"the release pull request #{number} did not merge in {minutes} minutes: {why}; nothing tagged")
        sleep(30)
        waited += 30


def release_pull(p):
    """The release pull request's title, branch and body. Pure."""
    version, major = p["version"], p["major"]
    return {"title": f"chore: release {version}", "branch": f"chore/release-{version}",
            "body": f"{MARK}\nThe release lane's release of {version}: every release scenario passed at `{major}-next`.\n"}


def engine_post():
    """scripts/engine-post.py (#694): what the engine posts is checked first."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("engine_post", os.path.join(HERE, "engine-post.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


def open_bug(repo, title, body, run=sh, kind="Bug"):
    """A bug the lane opens itself (#694), checked first (scripts/engine-
    post.py: it passes G1, never `incomplete`), with the Type Bug and its
    mark first, so the triage and the reproduction take it as a person's
    bug (issue-triage.yml `nightly`, issue-repro.yml NIGHTLY). A Task
    (#843: a harness or an infrastructure failure) carries the mark too,
    never first, so the triage leaves it to a person. Returns its URL."""
    engine_post().refuse("issue", body)
    if kind == "Bug" and not body.startswith(MARK):
        raise RuntimeError("the lane's bug does not start with its mark: the triage would never see it")
    if kind != "Bug" and (body.startswith(MARK) or MARK not in body):
        raise RuntimeError("the lane's task must carry its mark, never first: the triage would take it as a bug")
    return run("gh", "api", f"repos/{repo}/issues", "-f", f"title={title}", "-f", f"body={body}", "-f", f"type={kind}", "--jq", ".html_url").strip()


def open_issues(repo, run=sh):
    """The open issues of `repo`, as the issues API lists them (pull
    requests among them). Raises RuntimeError or ValueError."""
    pages_ = json.loads(run("gh", "api", f"repos/{repo}/issues?state=open&per_page=100", "--paginate", "--slurp") or "[]")
    return [i for page in pages_ for i in (page if isinstance(page, list) else [page]) if isinstance(i, dict)]


def report_of(issues, sid):
    """The number of the open report of the scenario `sid` (#843): an issue
    whose body carries the lane's mark and that scenario's, or None. Pure."""
    mine = [i["number"] for i in issues if not i.get("pull_request") and MARK in (i.get("body") or "") and scenario_mark(sid) in (i.get("body") or "")]
    return min(mine) if mine else None


def file_reports(p, filings, repo, run=sh, lane_run=""):
    """Each filing (#843) as a comment on its scenario's open report, or a
    new issue (a Bug for an engine failure, else a Task). Returns (filed,
    warnings): [{scenario, class, issue, how}]; a list that cannot be read
    files new issues, so no failure goes unsaid."""
    warnings = []
    try:
        issues = open_issues(repo, run)
    except (RuntimeError, ValueError) as err:
        issues = []
        warnings.append(f"The open failure reports could not be listed, so each failure opens its own: {err}")
    filed = []
    for f in filings:
        n = report_of(issues, f["scenario"])
        if n is not None:
            body = (f"{MARK}\nThe release lane's candidate {p['version']} fails this scenario again.\n\nClass: {f['class']}\n\n"
                    f"- `{f['scenario']}`: {f['why']} ({f['run'] or 'no run'})" + (f"\n\nThe lane's run: {lane_run}" if lane_run else ""))
            run("gh", "issue", "comment", str(n), "--repo", repo, "--body", body)
            filed.append({"scenario": f["scenario"], "class": f["class"], "issue": n, "how": "commented"})
        else:
            url = open_bug(repo, f["title"], f["body"], run, f["type"])
            filed.append({"scenario": f["scenario"], "class": f["class"], "issue": url, "how": "opened"})
            # A second row of the same id in this run (the move's and the
            # back's `callers`) comments on the one just opened.
            number = url.rstrip("/").rsplit("/", 1)[-1]
            if number.isdigit():
                issues.append({"number": int(number), "body": f["body"]})
    return filed, warnings


# A candidate's failure report, as decide() titled it before #843.
REPORT = re.compile(r"^fix: release candidate v(\d+)\.(\d+)\.(\d+) fails scenario ")
# A scenario's report, as `filing` titles it (#843), with no version: a
# release means every scenario passed, so each open one no longer holds.
SCENARIO_REPORT = re.compile(r"^(fix: release scenario \S+ fails|test: release scenario \S+ fails in the harness|ci: release scenario \S+ fails on infrastructure)$")
SCENARIO_MARK = re.compile(r"<!-- dx-lane-scenario: [^>]* -->")


def stale_reports(issues, version):
    """The numbers of the open issues (as the issues API lists them) that
    are the lane's report of a candidate's failure (its mark first, its
    title) for a version at or below `version`, the one just released
    (#832). A rollback's bug and the breaking release's issue are other
    titles. A scenario's report (#843, `filing`: its title, the lane's mark
    and the scenario's in its body) is stale at any release. Pure."""
    released = tuple(int(n) for n in version.lstrip("v").split("."))
    out = []
    for i in issues:
        title, body = i.get("title") or "", i.get("body") or ""
        if i.get("pull_request"):
            continue
        m = REPORT.match(title)
        if m and body.startswith(MARK) and tuple(int(n) for n in m.groups()) <= released:
            out.append(i["number"])
        elif SCENARIO_REPORT.match(title) and MARK in body and SCENARIO_MARK.search(body):
            out.append(i["number"])
    return sorted(out)


def close_reports(repo, version, run=sh, lane_run=""):
    """Closes, as completed, the reports stale_reports() finds once
    `version` is released, each with a comment naming it. Returns (closed,
    warnings): nothing here fails a release."""
    try:
        issues = open_issues(repo, run)
    except (RuntimeError, ValueError) as err:
        return [], [f"The open failure reports could not be listed, so none was closed: {err}"]
    comment = (f"Released as {version}, which passed every scenario: this candidate's failure no longer holds a release."
               + (f"\n\nThe lane's run: {lane_run}" if lane_run else ""))
    closed, warnings = [], []
    for n in stale_reports(issues, version):
        try:
            run("gh", "issue", "close", str(n), "--repo", repo, "--reason", "completed", "--comment", comment)
            closed.append(n)
        except RuntimeError as err:
            warnings.append(f"#{n}, a failure report {version} supersedes, could not be closed: {err}")
    return closed, warnings


def flaky_line(results):
    """The scenarios that failed, then passed on their retry (#843): one
    line naming each and its first failure, or "" when none. Pure."""
    rows = [r for r in results if r.get("ok") and r.get("flaky")]
    if not rows:
        return ""
    named = []
    for r in rows:
        first = visible("; ".join(str(w) for w in r.get("first_why") or []) or "failed")
        named.append(f"`{r.get('id')}` (it failed first: {first}, then passed on its retry)")
    return "Flaky: " + "; ".join(named)


def untriggered(text):
    """The pairs no scenario's runs triggered (#843), as scripts/release-
    scenarios.py merge records them in its results file, or []. Pure."""
    m = re.search(r"<!-- dx-untriggered (.*) -->", text or "")
    try:
        got = json.loads(m.group(1)) if m else []
    except ValueError:
        return []
    return [str(p) for p in got] if isinstance(got, list) else []


def act(p, results, repo, run=sh, sleep=time.sleep, root=".", lane_run=""):
    d = decide(p, results, lane_run)
    if flaky_line(results):
        # #843: a flaky scenario fails nothing, and the summary names it.
        d["flaky"] = flaky_line(results)
    if d["do"] == "bug":
        # #843: one report per scenario, or a comment on its open one.
        d["filed"], warnings = file_reports(p, d["filings"], repo, run, lane_run)
        if warnings:
            d["warnings"] = warnings
    elif d["do"] == "issue":
        ri = release_issue(p["version"][1:], d["why"], lane_run)
        engine_post().refuse("release", ri["title"], ri["labels"])
        run("gh", "issue", "create", "--repo", repo, "--title", ri["title"], "--body", ri["body"], *sum((["--label", l] for l in ri["labels"]), []))
    elif d["do"] == "release":
        d.update(release(p, repo, run, sleep, root=root))
        # #832: its tag moved, so the earlier candidates' reports no longer hold.
        if d.get("moved_at"):
            d["closed"], warnings = close_reports(repo, d["version"], run, lane_run)
            if warnings:
                d["warnings"] = warnings
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
    bug = rollback_bug(p, link)
    open_bug(repo, bug["title"], bug["body"], run)
    body = json.loads(run("gh", "release", "view", p["version"], "--repo", repo, "--json", "body") or "{}").get("body", "")
    run("gh", "release", "edit", p["version"], "--repo", repo, "--notes",
        f"> {major} moved back to {p['previous']}: this release failed in a repository ({link}).\n\n{body}")


def rollback_bug(p, link):
    """The watch's bug, in the issue schema's sections (#694). Pure."""
    major, version, previous = p["major"], p["version"], p["previous"]
    return {"title": f"fix: {version} failed in a repository; {major} is back at {previous}",
            "body": bug_body(f"Within 30 minutes of `{major}` moving to {version}, a run failed on the engine: {link}\n\n`{major}` points at {previous} again.",
                             f"Read the run {link}: it failed in one of the engine's own steps of an engine job (scripts/release-lane.py ENGINE_STEPS), or never started.",
                             f"{version} fails in an adopted repository, so the release lane moved `{major}` back to {previous} and every repository runs the previous release.",
                             [f"The cause of the failure in {link}, in the engine, fixed with a test that would have caught it, so the next release does not fail there."],
                             f"Given the fix, when the next release reaches the adopted repositories, then no run fails in the engine's own steps and `{major}` stays.")}


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
    # C8 (#694): the triage and the reproduction take the lane's bug (its
    # mark first, the bot's) as they take the nightly review's.
    triage = yaml.safe_load(open(os.path.join(ROOT, ".github", "workflows", "issue-triage.yml"), encoding="utf-8"))["jobs"]
    repro = yaml.safe_load(open(os.path.join(ROOT, ".github", "workflows", "issue-repro.yml"), encoding="utf-8"))["jobs"]
    nightly_env = [st.get("env", {}).get("NIGHTLY", "") for job in repro.values() for st in job.get("steps") or [] if "NIGHTLY" in (st.get("env") or {})]
    check("C8: workflow: the triage's bot-bug job and the reproduction take an issue that starts with the lane's mark",
          (f"startsWith(github.event.issue.body, '{MARK[:-4].strip()}')" in str(triage["nightly"]["if"]), len(nightly_env) > 0 and all(f"startsWith(github.event.issue.body, '{MARK[:-4].strip()}')" in e for e in nightly_env),
           "vars.DX_BOT_LOGIN" in str(triage["nightly"]["if"])), (True, True, True))
    watch_tokens = tokens("watch")
    writes = [t for t in watch_tokens if any(v == "write" for k, v in t.items() if k.startswith("permission-"))]
    check("workflow: the watch's write token is this repository's alone", bool(writes) and all(t.get("repositories") for t in writes), True)
    wide = [t for t in watch_tokens if not t.get("repositories")]
    check("workflow: the watch's installation-wide token only reads", bool(wide) and all(v in ("read",) for t in wide for k, v in t.items() if k.startswith("permission-")), True)
    check("workflow: the watch runs once v7 moved, even when act failed after", "always()" in str(jobs.get("watch", {}).get("if")), True)
    # The move and back jobs wait on the callers pull request's checks with
    # the token each passes as DX_CALLERS_TOKEN: that token reads them (#627).
    used, minted = [], []
    for job in ("move", "back"):
        steps = jobs.get(job, {}).get("steps") or []
        mine = {st.get("id"): st.get("with") or {} for st in steps if "create-github-app-token" in str(st.get("uses"))}
        minted += list(mine.values()) or [{}]
        waits = [(st.get("env") or {}).get("DX_CALLERS_TOKEN") for st in steps if re.search(r"release-scenarios\.py (move|back)\b", str(st.get("run")))]
        used += [mine.get(m.group(1)) if (m := re.fullmatch(r"\$\{\{ steps\.([\w-]+)\.outputs\.token \}\}", str(w))) else None for w in waits] or [None]
    check("workflow: the waits on the callers pull request, move's and back's, each use a token of its own job (#627)", len(used) == 2 and all(t is not None for t in used), True)
    check("workflow: the waits' tokens read the checks and the statuses (#627)",
          [(t or {}).get("permission-checks") == "read" and (t or {}).get("permission-statuses") == "read" for t in used], [True, True])
    check("workflow: the waits' tokens are the test repository's alone (#627)",
          [(t or {}).get("repositories") for t in used], ["${{ steps.test.outputs.repo }}"] * 2)
    check("workflow: every App token of the move and back jobs asks for checks: read and statuses: read (#627)",
          all(t.get("permission-checks") == "read" and t.get("permission-statuses") == "read" for t in minted), True)
    # The test identity (#739): the move job checks DX_TEST_LOGIN against
    # its token's owner before the callers move, so nothing plays when it differs.
    msteps = jobs.get("move", {}).get("steps") or []
    at = lambda pattern: next((i for i, st in enumerate(msteps) if re.search(pattern, str(st.get("run")))), None)
    guard, moving = at(r"org\.py test-identity --check"), at(r"release-scenarios\.py move\b")
    genv = (msteps[guard].get("env") or {}) if guard is not None else {}
    check("#739 workflow: move checks DX_TEST_LOGIN against DX_TEST_TOKEN's owner before the callers move",
          (guard is not None and moving is not None and guard < moving, genv.get("GH_TOKEN"), genv.get("DX_TEST_LOGIN")),
          (True, "${{ secrets.DX_TEST_TOKEN }}", "${{ vars.DX_TEST_LOGIN }}"))
    # The groups play at once, each in its job, between the move and the back.
    play = jobs.get("play", {})
    check("workflow: play is a matrix over the move job's groups, and one group's failure cancels no other's",
          ((play.get("strategy") or {}).get("matrix"), (play.get("strategy") or {}).get("fail-fast")),
          ({"group": "${{ fromJSON(needs.move.outputs.groups) }}"}, False))
    check("#707 workflow: play runs on GitHub's runners, never DX_RUNNER_HEAVY, where the test repository's jobs it waits for run",
          play.get("runs-on"), "ubuntu-latest")
    needs = lambda job: [jobs.get(job, {}).get("needs")] if isinstance(jobs.get(job, {}).get("needs"), str) else jobs.get(job, {}).get("needs") or []
    check("workflow: play needs move, and plays only once the callers moved", ("move" in needs("play"), play.get("if")), (True, "needs.move.outputs.moved == 'true'"))
    psteps = play.get("steps") or []
    check("workflow: play mints no App token: the test identity's tokens alone (#694: its fork token, for the scenario from a fork)",
          ([st for st in psteps if "create-github-app-token" in str(st.get("uses"))], [v for st in psteps for k, v in (st.get("env") or {}).items() if "token" in str(v).lower() or "TOKEN" in k]),
          ([], ["${{ secrets.DX_TEST_TOKEN }}", "${{ secrets.DX_TEST_FORK_TOKEN }}"]))
    check("workflow: back needs play and runs under always(), so the callers come back whatever the groups did",
          ("play" in needs("back"), "always()" in str(jobs.get("back", {}).get("if"))), (True, True))
    check("workflow: act reads the move, the play and the back jobs", {"move", "play", "back"} <= set(needs("act")), True)
    # bash sets these itself: a step's `env:` of one of them reaches its
    # script as bash's value, never the workflow's (GROUPS is the user's
    # group ids).
    special = {"GROUPS", "UID", "EUID", "PPID", "BASHPID", "RANDOM", "SECONDS", "LINENO", "HOSTNAME", "PWD", "OLDPWD", "SHELLOPTS", "BASH_VERSION"}
    check("workflow: no step's env names a variable bash sets itself",
          sorted({k for job in jobs.values() for st in job.get("steps") or [] for k in st.get("env") or {} if k in special}), [])
    # The play job has half an hour, its play step (20 minutes, above every
    # scenario's limit of 15: #694) stops before it, and the bug names those
    # two numbers (#690).
    play_step = next((st for st in psteps if st.get("id") == "play"), {})
    env = next((st.get("env") or {} for st in jobs.get("act", {}).get("steps") or [] if st.get("id") == "act"), {})
    job_t, play_t = play.get("timeout-minutes") or 0, play_step.get("timeout-minutes") or 0
    check("C3: workflow: the play job has 30 minutes, its play step 20, and the bug names both (#690, #694)",
          (job_t == 30, play_t == 20, str(env.get("SCENARIOS_TIMEOUT")), str(env.get("PLAY_TIMEOUT"))), (True, True, str(job_t), str(play_t)))

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

    reports = [{"number": 1, "title": "fix: release candidate v7.9.0 fails scenario a", "body": MARK + "\n"},
               {"number": 2, "title": "fix: release candidate v7.100.0 fails scenario a", "body": MARK + "\n"},
               {"number": 3, "title": "fix: release candidate v7.9.1 fails scenario a", "body": "no mark\n"},
               {"number": 4, "title": "fix: v7.9.0 rolled back after a failure in o/r", "body": MARK + "\n"}]
    check("#832: a release supersedes the marked reports of candidates at or below it, compared as numbers",
          (stale_reports(reports, "v7.10.1"), stale_reports(reports, "v7.100.0")), ([1], [1, 2]))
    f = Fake({"issues?state=open": json.dumps([reports]), "gh issue close": lambda a: (_ for _ in ()).throw(RuntimeError("HTTP 403"))})
    closed, warned = close_reports("O/.github", "v7.10.1", f, "https://run")
    check("#832: a close that fails is a warning, never an error", (closed, len(warned)), ([], 1))

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
            # Open with its checks green at h1 until the lane merges it.
            fake = Fake()

            def view(argv):
                if fake.has("gh", "pr", "merge"):
                    return json.dumps({"mergedAt": "2026-11-02T10:00:00Z", "mergeCommit": {"oid": "abc123"}, "state": "MERGED", "headRefOid": "h1"})
                return json.dumps({"mergedAt": None, "state": "OPEN", "headRefOid": "h1", "statusCheckRollup": [{"name": "ci", "status": "COMPLETED"}]})
            fake.answers = {"rev-parse origin/main": main + "\n", "rev-parse abc123^": parent + "\n",
                            "gh pr create": "https://github.com/O/.github/pull/700\n",
                            "gh pr view": view, "gh pr checks": json.dumps([{"name": "ci", "bucket": "pass"}]),
                            "changelog.py build": "# Changelog\n", "changelog.py notes": "notes\n", **more}
            return fake
        fake = merged(**{"gh release view": missing})
        d = act(p, passed, "O/.github", run=fake, sleep=lambda s: None, root=root)
        check("C4: all pass → release", d["do"], "release")
        check("C4: the release is built from the commit the scenarios tried", (fake.has("git", "-C", root, "checkout", "-B", "chore/release-v7.10.1", "p1"), bool([c for c in fake.named("changelog.py") if "build" in c and c[-1] == "p1"])), (True, True))
        check("C4: the release pull request is merged", fake.has("gh", "pr", "merge", "700"), True)
        merges = [c for c in fake.calls if c[:3] == ("gh", "pr", "merge")]
        want = ("gh", "pr", "merge", "700", "--repo", "O/.github", "--squash", "--match-head-commit", "h1")
        auto = "--" + "auto"
        check("#798: the lane merges it itself, once, at the head it saw, never by auto-merge",
              (merges, any(auto in c for c in fake.calls)), ([want], False))
        first_merge = next(i for i, c in enumerate(fake.calls) if c[:3] == ("gh", "pr", "merge"))
        check("#798: the merge comes only after its required checks were read",
              any(c[:3] == ("gh", "pr", "checks") and "--required" in c for c in fake.calls[:first_merge]), True)
        check("C4: no branch is pushed with git from release() (#780)", [c for c in fake.calls if c[:1] == ("git",) and "push" in c and any(a.startswith("refs/heads/") or a.startswith("HEAD:") for a in c)], [])
        check("C4: the release commit goes through the API, signed (#780)", [list(c[2:]) for c in fake.calls if c[1:2] and c[1].endswith("api-commit.py")], [["push", "chore/release-v7.10.1", "--onto", "HEAD~1", "--force"]])
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
        # #798: the release pull request's checks, before and while it merges.

        def opened(checks, rollup=None, head=lambda n: "h1", state="OPEN", merge_at=None):
            fake, views = Fake(), []

            def view(argv):
                views.append(1)
                if merge_at is not None and fake.has("gh", "pr", "merge") and len(views) >= merge_at:
                    return json.dumps({"mergedAt": "2026-11-02T10:00:00Z", "mergeCommit": {"oid": "abc123"}, "state": "MERGED"})
                return json.dumps({"mergedAt": None, "state": state, "headRefOid": head(len(views)),
                                   "statusCheckRollup": rollup if rollup is not None else [{"name": "ci", "status": "COMPLETED"}]})
            fake.answers = {"rev-parse origin/main": "p1\n", "rev-parse abc123^": "p1\n",
                            "gh pr create": "https://github.com/O/.github/pull/700\n",
                            "gh pr view": view, "gh pr checks": checks,
                            "changelog.py build": "# Changelog\n", "changelog.py notes": "notes\n", "gh release view": missing}
            return fake

        def tagged(fake):
            return [c for c in fake.calls if c[3:4] == ("tag",) or c[:2] == ("gh", "release")]

        def exits(code, stdout):
            def raise_(argv):
                err = RuntimeError(f"gh pr checks: exit {code}")
                err.stdout, err.stderr = stdout, ""
                raise err
            return raise_
        pending_then_pass = iter([exits(8, json.dumps([{"name": "ci", "bucket": "pending"}])), lambda argv: json.dumps([{"name": "ci", "bucket": "pass"}])])
        fake = opened(lambda argv: next(pending_then_pass)(argv), merge_at=3)
        d = act(p, passed, "O/.github", run=fake, sleep=lambda s: None, root=root)
        merges = [c for c in fake.calls if c[:3] == ("gh", "pr", "merge")]
        check("#798: a pending required check (exit 8) is waited for, then merged once, and released",
              (d["do"], len(merges), fake.has("git", "-C", root, "tag", "v7.10.1", "abc123")), ("release", 1, True))
        fake = opened(exits(1, json.dumps([{"name": "ci", "bucket": "fail"}])))
        err = _raises(lambda: act(p, passed, "O/.github", run=fake, sleep=lambda s: None, root=root))
        check("#798: a failed required check raises, naming it, merges and tags nothing",
              ("required check ci" in str(err), fake.has("gh", "pr", "merge"), tagged(fake)), (True, False, []))
        fake = opened(json.dumps([{"name": "ci", "bucket": "cancel"}]))
        err = _raises(lambda: act(p, passed, "O/.github", run=fake, sleep=lambda s: None, root=root))
        check("#798: a cancelled required check raises, merges and tags nothing", ("required check ci" in str(err), fake.has("gh", "pr", "merge"), tagged(fake)), (True, False, []))
        fake = opened(json.dumps([]), state="CLOSED")
        err = _raises(lambda: act(p, passed, "O/.github", run=fake, sleep=lambda s: None, root=root))
        check("#798: a closed release pull request raises, tags nothing", ("closed unmerged" in str(err), fake.has("gh", "pr", "merge"), tagged(fake)), (True, False, []))
        fake = opened(json.dumps([{"name": "ci", "bucket": "pending"}]), head=lambda n: "h1" if n == 1 else "h2")
        err = _raises(lambda: act(p, passed, "O/.github", run=fake, sleep=lambda s: None, root=root))
        check("#798: a head that moves raises, merges and tags nothing", ("changed head" in str(err), fake.has("gh", "pr", "merge"), tagged(fake)), (True, False, []))
        fake = opened(json.dumps([{"name": "ci", "bucket": "pass"}]), rollup=[{"name": "lint", "status": "IN_PROGRESS"}])
        err = _raises(lambda: release(p, "O/.github", run=fake, sleep=lambda s: None, minutes=1, root=root))
        check("#798: a check still running holds the merge; the budget out raises naming it, tags nothing",
              ("did not merge in 1 minutes" in str(err), "lint" in str(err), fake.has("gh", "pr", "merge"), tagged(fake)), (True, True, False, []))
        fake = opened(json.dumps([{"name": "ci", "bucket": "pass"}]))
        err = _raises(lambda: release(p, "O/.github", run=fake, sleep=lambda s: None, minutes=1, root=root))
        check("#798: queued but never merged: one merge call, the timeout says the merge queue, tags nothing",
              (len([c for c in fake.calls if c[:3] == ("gh", "pr", "merge")]), "merge queue" in str(err), tagged(fake)), (1, True, []))
        # No required check reported yet: a finished rollup waits one poll.
        late = iter([lambda argv: json.dumps([]), lambda argv: json.dumps([{"name": "ci", "bucket": "pending"}]),
                     lambda argv: json.dumps([{"name": "ci", "bucket": "pass"}])])
        fake = opened(lambda argv: next(late)(argv), rollup=[{"name": "lint", "status": "COMPLETED"}], merge_at=4)
        d = act(p, passed, "O/.github", run=fake, sleep=lambda s: None, root=root)
        merges = [i for i, c in enumerate(fake.calls) if c[:3] in (("gh", "pr", "merge"), ("gh", "pr", "checks"))]
        check("#800: no required check yet and a finished rollup: no merge until the required one registers and passes",
              (d["do"], [fake.calls[i][2] for i in merges]), ("release", ["checks", "checks", "checks", "merge"]))
        fake = opened(json.dumps([]), rollup=[{"name": "lint", "status": "COMPLETED"}], merge_at=3)
        d = act(p, passed, "O/.github", run=fake, sleep=lambda s: None, root=root)
        steps = [c[2] for c in fake.calls if c[:3] in (("gh", "pr", "merge"), ("gh", "pr", "checks"))]
        check("#800: none required, the same finished rollup on two polls: merged once, on the second",
              (d["do"], steps), ("release", ["checks", "checks", "merge"]))
        grown = iter([[{"name": "lint", "status": "COMPLETED"}], [{"name": "lint", "status": "COMPLETED"}, {"name": "pipeline", "status": "COMPLETED"}]])
        fake = opened(json.dumps([]), rollup=[], merge_at=99)
        rollups = []

        def view(argv):
            rollups.append(1)
            r = next(grown, None) or [{"name": "lint", "status": "COMPLETED"}, {"name": "pipeline", "status": "COMPLETED"}]
            if fake.has("gh", "pr", "merge"):
                return json.dumps({"mergedAt": "2026-11-02T10:00:00Z", "mergeCommit": {"oid": "abc123"}, "state": "MERGED"})
            return json.dumps({"mergedAt": None, "state": "OPEN", "headRefOid": "h1", "statusCheckRollup": r})
        fake.answers["gh pr view"] = view
        d = act(p, passed, "O/.github", run=fake, sleep=lambda s: None, root=root)
        check("#800: a rollup that grows between polls is not settled: merged only once it stays the same",
              (d["do"], len(rollups)), ("release", 4))
        bot = sorted(lane_logins())[0]
        check("#925: the lane's own open release pull request is reused; none open, none",
              (own_open_pull("O/.github", "chore/release-v7.10.1", Fake({"gh pr list": json.dumps([{"number": 690, "body": MARK, "author": {"login": bot}}])})),
               own_open_pull("O/.github", "chore/release-v7.10.1", Fake({"gh pr list": "[]"}))), (690, None))
        check("#925: one open without the mark, or opened by a person, stops the lane, naming it",
              ["#691" in str(_raises(lambda: own_open_pull("O/.github", "b", Fake({"gh pr list": json.dumps([{"number": 691, "body": body, "author": {"login": who}}])}))))
               for body, who in (("notes", bot), (MARK, "ana"))], [True, True])
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
        bug = fake.named("release scenario spec-to-draft fails")
        check("C5: one fails → a bug", d["do"], "bug")
        check("C5: nothing tagged, v7 not moved, nothing released", [c for c in fake.calls if c[:1] == ("git",) or c[:2] in (("gh", "release"), ("gh", "pr"))], [])
        check("C5: the bug names the scenario and its run", bool(bug) and "spec-to-draft" in " ".join(bug[0]) and "https://github.com/o/t/actions/runs/9" in " ".join(bug[0]), True)
        check("C5: no result at all is a failure", decide(p, [])["do"], "bug")
        opened = [c for c in fake.calls if c[:3] == ("gh", "api", "repos/O/.github/issues")]
        check("C8: the bug is opened with the Type Bug and starts with its mark",
              (len(opened), "type=Bug" in opened[0], next(a for a in opened[0] if a.startswith("body=")).startswith("body=" + MARK + "\n")), (1, True, True))
        refused = Fake()
        err = _raises(lambda: open_bug("O/.github", "fix: x", "Not the schema's.", refused))
        check("C7: a bug the schema would refuse is never posted, and says why", (refused.has("gh", "issue", "create"), "would not pass its own checks" in str(err)), (False, True))
        schema = lambda body: subprocess.run([sys.executable, os.path.join(HERE, "issue-schema.py"), "check"], input=body, capture_output=True, text=True)
        quoting = failing + [{"id": "issue-complete", "ok": False, "why": ["no comment with <!-- dx-board -->"], "run": ""}]
        for how, d in (("with the lane's run", decide(p, quoting, "https://github.com/O/.github/actions/runs/7")), ("with none", decide(p, failing)), ("of no result", decide(p, []))):
            got = schema(d["body"])
            check(f"C4: the bug's body, {how}, passes issue-schema.py check", (got.returncode, got.stdout if got.returncode else ""), (0, ""))
        d = decide(p, quoting, "https://github.com/O/.github/actions/runs/7")
        check("#843 C4: one report per failing scenario, each starting with the lane's mark, naming its scenario and the lane's run, and hiding no marker it quotes (its three marks aside: the lane's, the scenario's, #699's)",
              ([f["scenario"] for f in d["filings"]], [f["body"].startswith(MARK + "\n") for f in d["filings"]], [f"`{f['scenario']}`" in f["body"] for f in d["filings"]],
               ["actions/runs/7" in f["body"] for f in d["filings"]], [f["body"].count("<!--") for f in d["filings"]]),
              (["spec-to-draft", "issue-complete"], [True, True], [True, True], [True, True], [3, 3]))
        check("#843: a row with no class is the engine's, never hidden as someone else's", (classify({"id": "x"}), classify({"class": "harness"}), classify({"class": "nope"})), ("engine", "harness", "engine"))
        check("#699 C6: the bug names the lane's run as its reproduction: the bugfix-reproduced lane's mark, and the Problem's line",
              (d["body"].split("\n")[1], "\nReproduced by: https://github.com/O/.github/actions/runs/7 scenario `spec-to-draft`." in d["body"],
               "dx-lane:" in decide(p, failing)["body"], "Reproduced by:" in decide(p, failing, "not a run")["body"]),
              ("<!-- dx-lane: bugfix-reproduced run: https://github.com/O/.github/actions/runs/7 -->", True, False, False))
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
        made = [c for c in fake.calls if c[:3] == ("gh", "api", "repos/O/.github/issues")]
        check("C6: a bug with the run's link, of Type Bug", bool(made) and "https://github.com/O/a/actions/runs/2" in " ".join(made[0]) and "type=Bug" in made[0], True)
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
    twice = Fake({"issues?state=open": json.dumps([[]]), "repos/O/.github/issues": "https://github.com/O/.github/issues/77\n"})
    rows = [{"id": "callers", "ok": False, "why": ["not moved"], "run": "", "class": "harness"}, {"id": "callers", "ok": False, "why": ["not back"], "run": "", "class": "harness"}]
    filed, _ = file_reports(p, decide(p, rows)["filings"], "O/.github", twice)
    check("#843: two rows of one scenario in a run open one report and comment on it", [(f["how"], f["issue"]) for f in filed],
          [("opened", "https://github.com/O/.github/issues/77"), ("commented", 77)])
    check("#843: the pairs no scenario triggered, read from the results file", (untriggered("x\n<!-- dx-untriggered [\"a.yml:issues\"] -->\n"), untriggered("none"), untriggered("<!-- dx-untriggered nope -->")),
          (["a.yml:issues"], [], []))
    check("#843: a flaky scenario is named with its first failure, and fails nothing",
          (flaky_line([{"id": "a", "ok": True, "flaky": True, "first_why": ["no <!-- x -->"]}, {"id": "b", "ok": False, "flaky": True}]), decide(p, [{"id": "a", "ok": True, "flaky": True}])["do"]),
          ("Flaky: `a` (it failed first: no &lt;!-- x --&gt;, then passed on its retry)", "release"))
    check_workflow(check)
    import copy
    import yaml
    real = yaml.safe_load(open(os.path.join(ROOT, ".github", "workflows", "release-lane.yml"), encoding="utf-8"))

    def broken(change):
        """The names check_workflow fails on a copy of release-lane.yml
        that `change` broke."""
        wf = copy.deepcopy(real)
        change(wf["jobs"])
        names = []
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "release-lane.yml")
            with open(path, "w", encoding="utf-8") as fh:
                yaml.safe_dump(wf, fh)
            check_workflow(lambda name, got, want=True: names.append(name) if got != want else None, path)
        return names
    app = {"uses": "actions/create-github-app-token@x", "id": "app", "with": {}}
    for how, change, word in (
            ("fail-fast", lambda j: j["play"]["strategy"].update({"fail-fast": True}), "matrix"),
            ("one runner for every group", lambda j: j["play"].update({"runs-on": "self-hosted"}), "DX_RUNNER_HEAVY"),
            ("play before the move", lambda j: j["play"].update({"needs": ["plan"]}), "play needs move"),
            ("an App token in play", lambda j: j["play"]["steps"].insert(0, app), "no App token"),
            ("back only when play passed", lambda j: j["back"].update({"if": "needs.move.result != 'skipped'"}), "always()"),
            ("back before play", lambda j: j["back"].update({"needs": ["plan", "move"]}), "back needs play"),
            ("back's token without statuses", lambda j: next(s for s in j["back"]["steps"] if s.get("id") == "back")["with"].pop("permission-statuses"), "statuses"),
            ("move's token for every repository", lambda j: next(s for s in j["move"]["steps"] if s.get("id") == "app")["with"].pop("repositories"), "alone"),
            ("act's groups in bash's GROUPS", lambda j: next(s for s in j["act"]["steps"] if s.get("id") == "act")["env"].update({"GROUPS": "x"}), "bash sets")):
        names = broken(change)
        check(f"C1: check_workflow fails a release-lane.yml with {how}", any(word in n for n in names), True)
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
        print(json.dumps(decide(load(a.plan), results_of(a.results), a.run)))
        return 0
    if a.mode == "act":
        d = act(load(a.plan), results_of(a.results), a.repo, lane_run=a.run)
        missing = untriggered(open(a.results, encoding="utf-8").read() if a.results and os.path.exists(a.results) else "")
        if missing:
            # #843: a pair no scenario's runs triggered is named, and fails nothing.
            d["untriggered"] = missing
        print(json.dumps(d))
        if missing:
            print(f"::warning::Pairs no scenario triggered: {', '.join(missing)}", file=sys.stderr)
        if d.get("flaky"):
            # stdout stays the JSON the workflow reads: the Flaky line goes
            # to the log as a warning and to the lane's summary (#843).
            print(f"::warning::{d['flaky']}", file=sys.stderr)
            if os.environ.get("GITHUB_STEP_SUMMARY"):
                with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
                    fh.write(f"\n{d['flaky']}\n")
        for w in d.get("warnings", []):
            print(f"::warning::{w}", file=sys.stderr)
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
