#!/usr/bin/env python3
"""The release scenarios (#563): what the release lane plays in the test
repository (org.yml `test-repo`, kind engine-test) at `v7-next` before `v7`
moves, as data in tests/release/scenarios.yml.

Every pair of a reusable workflow and an event the test repository's
callers wire (its pack's `callers` among workflow-templates/*.yml, and
org-pull-request.yml, the organisation's required workflow), but a
`schedule` no scenario can cause, and every
transition of the autopilot's state machine (scripts/autopilot.py:
`next_step`'s BOT_ACTIONS, its waits on PERSON_DECISIONS and BOT_WAITS, the
MERGE_HOWS of `merge-main`, and what `sweep_step` returns), has a scenario
that covers it, but a transition the file's `statically:` names with the
test that holds it, which no scenario can cause there (#707). A scenario: `id`, `covers` (pairs `<workflow>:<event>`,
transitions `next_step:<action>`, `next_step:wait:<for>`,
`next_step:merge-main:<how>`, `sweep_step:<what>`), `before` (issues it
opens first and keeps open until it ends, each `{issue: {...}}`, and files
of its own it lands on main first, each `{lands: <name>, says: <text>}`:
scenarios/<id>/<name>.md, through a docs pull request of the scenario that
merges, unless main says it already: #707), `opens`
(an `issue` or a `pull` with its `title`, `body` (a name of `bodies:` or the
text), `labels`, and `fork: true` for one from a fork; a pull's `{issue}` in
its body is the number of the issue it opens first, its `issue:` or a
complete feature; an issue's `type`, else the Type its body's form gives,
`types:` of the file, and its `comments`, posted before its labels: a
`/claim` before `accepted`), `steps` (each one of
`comment`, `label`, `unlabel`, `edit`, `push`, `dispatch`, and `until`,
an `expect` polled every 50 seconds (#726: every scenario at once shares
the test identity's 5000 requests an hour) on its issue or pull request, or with
`of: before` on its first `before` issue, never a fixed wait: #694; a
`comment` or a `label` with `of: before` acts on that issue too, #713; a
file is written in a commit GitHub signs, `createCommitOnBranch` (#709); a
`push: <name>` writes scenarios/<id>/<name>.md on the head branch of the
pull request it observes, the autopilot's for an issue, and `conflict`
then lands that file, otherwise, on main, `behind` only a file of its own
there, through a docs pull request of the scenario that merges: #698),
`minutes` (its limit, 10 by default, 15 at most) and
`expect` (`labels`, `absent`, `comments` (markers), `pull` (`closes`,
`branch`, `title`, patterns; `false` for none that closes it, #713), `check` (name: conclusion, the name a
check run's caller's job or its own: `check_named`, #709), `merged`,
`waiting`). Every scenario is a group of its own (`groups`, #694), and
the lane plays the groups at once, one job each, on GitHub's runners,
never DX_RUNNER_HEAVY, where the test repository's own jobs run
(`lane_problems`, #707): each writes only under
its own directory of the test repository, scenarios/<id>/, and only
core-one-at-a-time's is its core (#709: `core_problems`). A poll
finds an issue's pull request from the issue's own references, never a
search (#698: the search API's 30 a minute, shared by every scenario at
once), and a `gh` that fails for a while (a rate limit, a 5xx) is retried
after GitHub's back-off within the scenario's limit, then named.

  release-scenarios.py coverage [ROOT]
        fails naming every pair and transition with no scenario, every
        scenario that covers what is neither, and every scenario whose
        `expect` cannot hold against its own setup (`preconditions`: a
        dispatch of a workflow the test repository cannot run on demand
        among them; #707: a bug's verdict in a test repository with no way
        to reproduce it, and the lane's `play` job on DX_RUNNER_HEAVY;
        #713: one that reads the autopilot's result on an issue it opens
        accepted, accepts before the triage's verdict or waits for no
        seal after it, or comments /claim after the acceptance,
        `autopilot_problems`; a body the schema refuses, a decision's
        too, or a Bug's without a field bug_report.yml requires).
        Every other pair a shipped caller wires is held to the
        engine statically, by scripts/caller-contract.py check; and
        what is wrong with the groups (`partition`): a scenario in no
        group or in two, two scenarios that could write to the same
        part of the test repository's core, a scenario that writes under
        it but expects no wait on it (#709), a group id unfit for an
        artifact name
  release-scenarios.py plan
        prints each scenario's limit in minutes and how often it polls,
        [{id, minutes, poll}] as JSON; exits 1 naming a fixed wait or a
        limit past 15 minutes (#694)
  release-scenarios.py groups
        prints the groups, [{id, scenarios}] as JSON, the release lane's
        `play` matrix; exits 1 naming what `partition` finds
  release-scenarios.py move --repo OWNER/NAME --moved MOVED --out FILE
                            [--ref v7-next] [--minutes N]
        the callers moved to the ref, as `run` does (with
        DX_CALLERS_TOKEN), what moved written to MOVED as soon as the
        pointing is over, and to FILE the failing `callers` row when they
        did not reach it (exits 1 then: no group plays)
  release-scenarios.py play --repo OWNER/NAME --group ID --out FILE
                            [--ref v7-next] [--minutes N]
        the group's scenarios, one after another in its order, with the
        test identity's token (GH_TOKEN) alone, the callers already at the
        ref, each one first deleting its leftover `scenario/<id>` branch
        and closing the issues and pull requests an earlier run of it left
        (the `dx-scenario: <id>` mark first in every body it opens), and
        again after (#694); their table to FILE; exits 1 when one fails
  release-scenarios.py merge --dir DIR --groups JSON --job NAME=RESULT ...
                             --out FILE [--run URL] [--minutes N]
                             [--play-minutes M]
        one table, to FILE (and stdout), from the scenarios-<name>/results.md
        under DIR (`move`, `back` and every group's): each group's rows of
        its own scenarios, and a failing row, with URL, for a group whose
        file is missing (its job failed, timed out or was cancelled), a
        scenario with no row, and a job whose RESULT is not success (a play
        job's naming its timeout of N minutes, and its play step's of M,
        #690); exits 1 when a row fails
  release-scenarios.py run --repo OWNER/NAME [--ref v7-next] [--only ID ...]
                           [--out FILE] [--minutes N]
        moves the test repository's callers to the ref through a pull
        request (opened with DX_CALLERS_TOKEN, the bot's, when set: its
        rulesets refuse a write to main) that the lane merges itself,
        through the merge queue once its checks pass, after checking from
        GitHub that it changes nothing but the engine's ref in those
        callers (one that does is closed unmerged), and once it
        merged plays them there with the test identity's token
        (GH_TOKEN), polls until each one's `expect` holds or its time is
        up, cleans up (its pack's `cleanup: after-run`) and writes the
        Markdown table of results (scenario, pass or fail, run link) to
        FILE (and stdout), then puts the callers back the same way; a
        pull request that does not merge is a failing `callers` row;
        exits 1 when one fails. With --moved MOVED, what moved is written
        to MOVED as soon as the pointing is over, before the first
        scenario plays ([] when it failed cleanly), and left for `back`
  release-scenarios.py back --repo OWNER/NAME --moved MOVED [--ref v7-next]
                            [--out FILE] [--minutes N]
        puts back the callers `run --moved` left at the ref (with
        DX_CALLERS_TOKEN, minted after the scenarios: an App token lasts
        an hour) and adds a failing `callers` row to FILE if they do not
        come back, or if MOVED is missing or unreadable (a run cancelled
        or killed while pointing: could not tell, never "nothing moved");
        exits 1 when a row of FILE fails
  release-scenarios.py --test
"""
import ast
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCENARIOS = os.path.join("tests", "release", "scenarios.yml")
CALLERS = ("workflow-templates/*.yml", ".github/workflows/org-pull-request.yml")


def load_yaml(path):
    import yaml
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def caller_events(doc):
    on = doc.get(True, doc.get("on"))
    if isinstance(on, str):
        return [on]
    return [e for e in (on or []) if e != "workflow_call"]


def job_events(cond, events):
    """The caller's events that can reach a job, from its `if:`: when it
    compares `github.event_name ==` to some and has no other way in (a
    ref), those and the ones it names with `!=`; else every event."""
    cond = str(cond or "")
    equal = set(re.findall(r"github\.event_name\s*==\s*'([a-z_]+)'", cond))
    if not equal or "github.ref_name" in cond:
        return list(events)
    named = set(re.findall(r"github\.event_name\s*!=\s*'([a-z_]+)'", cond)) | equal
    return [e for e in events if e in named]


def pairs(root=ROOT, callers=CALLERS):
    """{"<reusable workflow>:<event>"} the callers (globs) wire."""
    out = set()
    for pattern in callers:
        for path in sorted(glob.glob(os.path.join(root, pattern))):
            doc = load_yaml(path)
            events = caller_events(doc)
            jobs = doc.get("jobs") or {}
            reach = {}
            for name in jobs:
                reach[name] = job_events(jobs[name].get("if"), events)
            for name, job in jobs.items():
                needs = job.get("needs") or []
                for need in [needs] if isinstance(needs, str) else needs:
                    reach[name] = [e for e in reach[name] if e in reach.get(need, events)]
                m = re.search(r"/\.github/workflows/([^@/]+\.yml)@", str(job.get("uses") or ""))
                if m:
                    out |= {f"{m.group(1)}:{e}" for e in reach[name]}
    return out


# What no scenario can cause in its few minutes: the daily run comes when it
# comes. A scheduled pair is held to the engine statically.
UNPLAYABLE = ("schedule",)


def test_callers(pack):
    """The test repository's callers, as globs: its pack's `callers` among
    the shipped ones, and org-pull-request.yml, which runs everywhere."""
    return tuple(f"workflow-templates/{c}" for c in pack.get("callers") or []) + (".github/workflows/org-pull-request.yml",)


def played(root, pack):
    """The pairs a scenario plays (#563): those the test repository's
    callers wire, with an event a scenario can cause. Every other pair a
    shipped caller wires is held to the engine by scripts/caller-contract.py
    check, which needs no run."""
    return {p for p in pairs(root, test_callers(pack)) if p.rsplit(":", 1)[1] not in UNPLAYABLE}


def dispatchable(root, pack):
    """The test repository's callers a scenario can dispatch: its own, with
    `workflow_dispatch`."""
    out = set()
    for pattern in test_callers(pack)[:-1]:
        for path in glob.glob(os.path.join(root, pattern)):
            if "workflow_dispatch" in caller_events(load_yaml(path)):
                out.add(os.path.basename(path))
    return out


def _tuple(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return [ast.literal_eval(e) for e in node.value.elts]
    return []


def transitions(root=ROOT):
    """Every transition of the state machine, from scripts/autopilot.py's
    own tuples (read, never imported)."""
    tree = ast.parse(open(os.path.join(root, "scripts", "autopilot.py"), encoding="utf-8").read())
    out = {f"next_step:{a}" for a in _tuple(tree, "BOT_ACTIONS")}
    out |= {f"next_step:wait:{w}" for w in _tuple(tree, "PERSON_DECISIONS") + _tuple(tree, "BOT_WAITS")}
    out |= {f"next_step:merge-main:{h}" for h in _tuple(tree, "MERGE_HOWS")}
    out |= {f"sweep_step:{s}" for s in _tuple(tree, "SWEEP_STEPS")}
    return out


def coverage(scenarios, wanted, statically=None):
    """What has no scenario, and what a scenario covers that is not wanted:
    ["... has no scenario"]. `statically` (the file's `statically:`, #707)
    names each transition no scenario can cause in the test repository,
    with what holds it instead: it is covered by that, never by a scenario
    as well, and must be a transition with its reason. Pure."""
    covered, out, seen = set(), [], set()
    statically = statically or {}
    for w, why in sorted(statically.items()):
        if not str(w).startswith(("next_step:", "sweep_step:")) or w not in wanted:
            out.append(f"statically: {w} is no transition of the state machine")
        elif not str(why or "").strip():
            out.append(f"statically: {w} says no test that holds it")
    for s in scenarios:
        sid = s.get("id") or "?"
        if sid in seen:
            out.append(f"scenario {sid}: its id is used twice")
        seen.add(sid)
        # A case the PRD lists may cover no pair or transition of its own
        # (a stop, a hint): it still opens something and expects something.
        for part in ("opens", "expect"):
            if not s.get(part):
                out.append(f"scenario {sid}: says no `{part}`")
        for c in s.get("covers") or []:
            covered.add(c)
            if c not in wanted:
                out.append(f"scenario {sid}: covers {c}, which no caller wires and no transition is")
            elif c in statically:
                out.append(f"scenario {sid}: covers {c}, which `statically:` says no scenario can cause")
    for w in sorted(wanted - covered - set(statically)):
        kind = "the transition" if w.startswith(("next_step:", "sweep_step:")) else "the pair"
        out.append(f"{kind} {w} has no scenario in {SCENARIOS}")
    return out


CORE_LABEL, CORE_MARK = "autopilot:core-wait", "<!-- dx-autopilot-core -->"


def needed_type(title):
    """The issue Type a pull request titled `title` must close
    (scripts/issue-gate.sh needed_types): Feature for a feat or any `!`,
    Bug for a fix, None for any other type. Pure."""
    m = re.match(r"^([a-z]+)(\([^)]*\))?(!?): ", str(title or ""))
    if not m:
        return None
    return "Feature" if m.group(3) or m.group(1) == "feat" else "Bug" if m.group(1) == "fix" else None


def type_of(spec, types):
    """The Type an issue `spec` opens with: its own `type`, else its body's
    form's (`types:` of the file), else none. Pure."""
    if spec.get("type"):
        return spec["type"]
    return (types or {}).get(spec["body"]) if isinstance(spec.get("body"), str) else None


# The pull request template's sections the conventions check asks of a
# person's description (scripts/conventions.sh SECTIONS).
SECTIONS = ("What changes", "Why")


def empty_sections(body, sections=SECTIONS):
    """The `sections` that `body` leaves missing or empty, read as
    scripts/conventions.sh `section` reads them: the text under the `## `
    heading that names it, comments aside. Pure."""
    out = []
    for h in sections:
        on, text = False, []
        for line in str(body or "").split("\n"):
            if line.startswith("## "):
                on = h in line
                continue
            if on:
                text.append(line)
        if not re.sub(r"<!--.*?-->|\s", "", "\n".join(text)):
            out.append(h)
    return out


DRAFT_KINDS = {"Bug": "fix", "Feature": "feat", "Docs": "docs"}


BUG_VERDICTS = ("bug:confirmed", "bug:unconfirmed")


def preconditions(scenarios, bodies, pack, can_dispatch=(), passes=None, types=None, repro=None):
    """Every scenario whose `expect` its own setup can never make hold
    (#563): a pull's `closes` with no `{issue}` in its body (a fixed number
    is another object's), a wait on the core with no open issue before it
    or a test repository whose fixed change touches no core, a `dispatch` of
    a workflow the test repository cannot run on demand (`can_dispatch`),
    an issue that should await acceptance whose body the schema refuses
    (`passes(body)`: the triage would call it `incomplete`), and (#698) a
    pull request the conventions check fails for a person: one that closes
    an issue it does not open accepted, whose body leaves a template section
    empty, or whose title's type the closed issue's Type refuses (`types`,
    each body's form's), and an issue whose Type makes the autopilot name
    its draft otherwise than its `expect` (scripts/autopilot.py TYPES), and
    (#707) a bug's verdict (`bug:confirmed`, `bug:unconfirmed`) expected in a
    test repository with no way to reproduce it (`repro` False: repos.yml
    and its pack declare none, so the bug gets `repro:no-way`), or a
    confirmed bug's issue expected to have a pull request that closes it
    (the reproduction's fix closes the lane's own issue, never the
    report). Pure."""
    import fnmatch
    out = []
    for s in scenarios:
        sid, expect, opens = s.get("id") or "?", s.get("expect") or {}, s.get("opens") or {}
        verdicts = [v for v in BUG_VERDICTS if v in (expect.get("labels") or [])]
        if verdicts and repro is False:
            out.append(f"scenario {sid}: expects {', '.join(verdicts)}, but the test repository has no way to reproduce a bug "
                       f"(repos.yml and its pack declare none), so it gets repro:no-way")
        if "bug:confirmed" in verdicts and "issue" in opens and (expect.get("pull") or {}).get("closes"):
            out.append(f"scenario {sid}: expects bug:confirmed and a pull request that closes its issue, but the reproduction's fix closes "
                       f"the issue the bugfix-reproduced lane opens, never the report")
        if "pull" in opens and "{issue}" in body_of(opens["pull"].get("body"), bodies):
            pull, closed = opens["pull"], opens["pull"].get("issue") or {}
            if "accepted" not in (closed.get("labels") or []):
                out.append(f"scenario {sid}: its pull request closes an issue it does not open accepted (its `issue:` with `labels: [accepted]`), so the accepted-issue gate fails it")
            for h in empty_sections(body_of(pull.get("body"), bodies)):
                out.append(f"scenario {sid}: its pull request's body has no `{h}` section, which the conventions check asks of a person's")
            need, got = needed_type(pull.get("title")), type_of(closed or {"body": "complete-feature"}, types)
            if need and got != need:
                out.append(f"scenario {sid}: its pull request is titled for a {need}, but the issue it closes is {('a ' + got) if got else 'an issue with no Type'}, which the accepted-issue gate refuses")
        if "issue" in opens and str((expect.get("pull") or {}).get("branch") or "").startswith("^"):
            kind = DRAFT_KINDS.get(type_of(opens["issue"], types) or "", "chore")
            want = re.match(r"\^([a-z]+)", str(expect["pull"]["branch"]))
            if want and want.group(1) != kind:
                out.append(f"scenario {sid}: expects the autopilot's branch {expect['pull']['branch']}, but its issue's Type ({type_of(opens['issue'], types) or 'none'}) makes it {kind}/")
        for step in s.get("steps") or []:
            if isinstance(step, dict) and "dispatch" in step and str(step["dispatch"]) not in can_dispatch:
                out.append(f"scenario {sid}: dispatches {step['dispatch']}, which the test repository has not, or not with workflow_dispatch "
                           f"(its pack's `callers`: {', '.join(sorted(can_dispatch)) or 'none dispatchable'})")
        if passes and "issue" in opens and ("awaiting-acceptance" in (expect.get("labels") or []) or "incomplete" in (expect.get("absent") or [])):
            if not passes(body_of(opens["issue"].get("body"), bodies)):
                out.append(f"scenario {sid}: expects its issue to await acceptance, but its body does not pass the issue schema")
        if "pull" in opens and (expect.get("pull") or {}).get("closes"):
            if "{issue}" not in body_of(opens["pull"].get("body"), bodies):
                out.append(f"scenario {sid}: expects its pull request to close an issue, but its body names no `{{issue}}` it opens")
        if waits_on_core(s):
            first = [b.get("issue") or {} for b in s.get("before") or []]
            later = any(isinstance(st, dict) and st.get("of") == "before" and st.get("label") == "accepted" for st in s.get("steps") or [])
            if not (later and first) and not any("accepted" in (i.get("labels") or []) for i in first):
                out.append(f"scenario {sid}: expects a wait on the core, but opens no accepted issue before it whose pull request stays open")
            fixed = str((pack.get("fixed-change") or {}).get("file") or "").replace("{n}", "1").replace("{id}", "c1").replace("{scenario}", sid)
            if not any(fnmatch.fnmatchcase(fixed, g) for g in pack.get("core") or []):
                out.append(f"scenario {sid}: expects a wait on the core, but the test repository's fixed change ({fixed or 'none'}) touches no core of its pack")
    return out


# Playing them.

def body_of(value, bodies):
    return bodies.get(value, value) if isinstance(value, str) else ""


def check_named(name, checks):
    """The conclusion of the check run `name` names among `checks` ({check
    run name: conclusion}, "" while it runs), None when none matches (#709):
    GitHub names a reusable workflow's check after its caller's job and its
    own, "conventions / Conventions (branch, title, commits)", so `name`
    matches a check named exactly that, else one whose own name (after the
    last ` / `) is it or starts with it and ` (`, else one whose caller's
    job (before it) is it, case aside: the closest kind that matches, its
    first that ended. Pure."""
    want, ranked = str(name).lower(), {}
    for got, conclusion in (checks or {}).items():
        full = str(got or "").lower()
        caller, _, job = full.rpartition(" / ")
        rank = 0 if full == want else 1 if job == want or job.startswith(want + " (") else 2 if caller == want else None
        if rank is not None:
            ranked.setdefault(rank, []).append(conclusion or "")
    for rank in sorted(ranked):
        return next((c for c in ranked[rank] if c), "")
    return None


def saw(seen):
    """What a row that fails saw (#707), so the lane's bug names the cause
    (a seal refused, a label taken off) and not only what was missing: its
    labels, and the first line of the newest comment of the bot's that is
    not a marker. Table-safe: no `|`, no backtick. Pure."""
    labels = ", ".join(sorted(seen.get("labels") or [])) or "none"
    line = ""
    for text in reversed(seen.get("said") or []):
        line = next((x.strip() for x in str(text).split("\n") if x.strip() and not re.fullmatch(r"\s*<!--.*?-->\s*", x)), "")
        if line:
            break
    line = re.sub(r"[|`]", "'", line)[:160]
    return f"saw labels {labels}; the bot's newest comment: {line or 'none'}"


def holds(expect, seen):
    """What of `expect` does not hold in `seen` (labels, comments, pull,
    checks, merged, waiting): [] when it all does, else ending with what it
    saw (`saw`, #707). Pure."""
    out = []
    labels = set(seen.get("labels") or [])
    for label in expect.get("labels") or []:
        if label not in labels:
            out.append(f"no label {label}")
    for label in expect.get("absent") or []:
        if label in labels:
            out.append(f"label {label} still there")
    text = "\n".join(seen.get("comments") or [])
    for marker in expect.get("comments") or []:
        if marker not in text:
            out.append(f"no comment with {marker}")
    pull = seen.get("pull") or {}
    if expect.get("pull") is False and pull:
        out.append(f"a pull request closes it ({pull.get('number') or pull.get('branch') or '?'})")
    for key, pattern in (expect.get("pull") or {}).items():
        if key == "closes":
            # The issue it should close: the one a pull scenario opened for
            # it, else the scenario's own issue.
            want = seen.get("closes") or seen.get("number")
            if not re.search(rf"Closes #{re.escape(str(want))}\b", pull.get("body") or ""):
                out.append(f"the pull request does not say Closes #{want}")
        elif not re.search(str(pattern), str(pull.get(key) or "")):
            out.append(f"the pull request's {key} is not {pattern}")
    for name, conclusion in (expect.get("check") or {}).items():
        got = check_named(name, seen.get("checks"))
        if got is None:
            out.append(f"check {name} is missing, not {conclusion} (its checks: {', '.join(sorted(seen.get('checks') or {})) or 'none'})")
        elif got != conclusion:
            out.append(f"check {name} is {got or 'still running'}, not {conclusion}")
    for key in ("merged", "waiting"):
        if key in expect and bool(seen.get(key)) != bool(expect[key]):
            out.append(f"{key} is {bool(seen.get(key))}")
    return out + [saw(seen)] if out else out


# Every wait polls its state (#694): never a fixed sleep. Every scenario
# polls at once with the test identity's token (#726), which GitHub allows
# RATE_LIMIT requests an hour: `poll_budget` stays under it.
POLL = 50
RATE_LIMIT = 5000
# A scenario's limit, in minutes: its own `minutes`, or LIMIT; none past
# MAX_LIMIT, which the play step's timeout-minutes in release-lane.yml
# (20) stays above.
LIMIT, MAX_LIMIT = 10, 15
RUNNING = ("queued", "in_progress", "waiting", "requested", "pending")


def hopeless(expect, seen, settled=False):
    """What of `expect` can no longer hold in `seen` (#694), so the
    scenario stops at once instead of waiting out its limit: a pull request
    merged that should not be, or closed unmerged that should merge, a check
    that ended with another conclusion and, once the test repository has
    settled (`settled`: no run queued or in progress on two polls in a row,
    so the job that would remove it has finished), an `absent` label still
    there, and (#709) a check expected of a pull request whose run GitHub
    holds for a maintainer's approval (`held`: a fork's, `action_required`),
    which nothing in the scenario can release. [] when it still may hold.
    Pure."""
    out = []
    if "merged" in expect:
        if not expect["merged"] and seen.get("merged"):
            out.append("it merged")
        elif expect["merged"] and not seen.get("merged") and str(seen.get("state") or "").upper() == "CLOSED":
            out.append("it closed unmerged")
    for name, conclusion in (expect.get("check") or {}).items():
        got = check_named(name, seen.get("checks"))
        if got and got != conclusion:
            out.append(f"check {name} ended {got}, not {conclusion}")
    if expect.get("check") and seen.get("held"):
        out.append(f"the fork's run waits for approval to run workflows from forks ({', '.join(seen['held'])})")
    if settled:
        labels = set(seen.get("labels") or [])
        out += [f"label {label} stays, with nothing left running" for label in expect.get("absent") or [] if label in labels]
    return out


def limit(s):
    """The scenario's limit in minutes (its `minutes`, or LIMIT). Pure."""
    return int(s.get("minutes") or LIMIT)


def scenario_plan(scenarios):
    """What the lane plays (#694): each scenario's id, its limit in minutes
    and how often it polls, [{id, minutes, poll}]. Pure."""
    return [{"id": s.get("id"), "minutes": limit(s), "poll": POLL} for s in scenarios]


def poll_budget(scenarios):
    """The `gh` calls an hour every scenario polling at once makes (#726):
    each one's calls a poll, as `observe` makes them (2 for an issue: its
    view and the runs; 3 for a pull request: its view, the runs of its head
    and the runs), every POLL seconds. Pure."""
    return sum((3 if "pull" in (s.get("opens") or {}) else 2) * 3600 // POLL for s in scenarios)


def timing(scenarios):
    """What is wrong with the plan's waits (#694): a fixed `wait` step
    (every wait is an `until` that polls its state), an `until` that names
    no expectation, a limit past MAX_LIMIT minutes, and (#726) polls that,
    every scenario at once, pass the test identity's RATE_LIMIT. Pure."""
    out = []
    for s in scenarios:
        sid = s.get("id") or "?"
        for step in s.get("steps") or []:
            if isinstance(step, dict) and "wait" in step:
                out.append(f"scenario {sid}: waits a fixed {step['wait']} seconds; wait `until` the state it waits for, polled every {POLL} seconds")
            if isinstance(step, dict) and "until" in step and not {k: v for k, v in (step["until"] or {}).items() if k != "of"}:
                out.append(f"scenario {sid}: an `until` with no expectation")
        if limit(s) > MAX_LIMIT:
            out.append(f"scenario {sid}: its limit is {limit(s)} minutes, past {MAX_LIMIT}")
    if poll_budget(scenarios) > RATE_LIMIT:
        out.append(f"the plan's {len(scenarios)} scenarios poll GitHub {poll_budget(scenarios)} times an hour, every {POLL} seconds, past the test identity's {RATE_LIMIT}")
    return out


def table(results):
    """The Markdown table of results. Pure."""
    lines = ["| Scenario | Result | Run |", "| --- | --- | --- |"]
    for r in results:
        why = f" ({'; '.join(r['why'])})" if r.get("why") else ""
        lines.append(f"| `{r['id']}` | {'pass' if r['ok'] else 'fail'}{why} | {r.get('run') or ''} |")
    return "\n".join(lines) + "\n"


class GhError(RuntimeError):
    """A `gh` that exited non-zero, with what it printed: `gh pr checks`
    exits 8 while a check is pending and 1 when one failed, JSON and all."""

    def __init__(self, message, code=1, stdout="", stderr=""):
        super().__init__(message)
        self.code, self.stdout, self.stderr = code, stdout, stderr


def gh(*args, input=None, token=None):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, input=input,
                         env=dict(os.environ, GH_TOKEN=token) if token else None)
    if out.returncode:
        raise GhError(f"gh {' '.join(args[:3])}: {out.stderr.strip()}", out.returncode, out.stdout, out.stderr)
    return out.stdout


def scenario_mark(sid):
    """The mark every body a scenario opens carries (#694), so a later run
    finds and closes what this one left behind. Pure."""
    return f"<!-- dx-scenario: {sid} -->"


def marked(text, sid):
    """`text` with the scenario's mark first: before the first section, where
    the issue schema reads an organisation's marker (scripts/issue-schema.py
    MARKER), and a line that names the scenario (#709: the mark is a
    comment, which the triage does not see, so two scenarios' issues with the
    same text would read as duplicates): the first line of its first `### `
    section, since the schema refuses any other text before it, else right
    after the mark. Pure."""
    line = f"Scenario: {sid}."
    m = re.search(r"^### .*\n", text, re.M)
    if m:
        return f"{scenario_mark(sid)}\n{text[:m.end()]}\n{line}\n{text[m.end():]}"
    return f"{scenario_mark(sid)}\n{line}\n{text}"


# A title its form fixes, which a suffix would break (#709): the Release
# form's, the version alone (scripts/engine-post.py RELEASE_TITLE).
FIXED_TITLE = re.compile(r"^Release \d+\.\d+\.\d+$")


def issue_text(spec, bodies, default, sid=None):
    """The title and body the issue `spec` opens with: with `sid`, its title
    ends with `[<sid>]` (a suffix: the `type:` before it is what the
    conventions check and `needed_type` read), but a title its form fixes
    (`FIXED_TITLE`), and its body is `marked` (#709). Pure."""
    title, text = str(spec.get("title", default)), body_of(spec.get("body"), bodies)
    if not sid:
        return title, text
    return (title if FIXED_TITLE.match(title) else f"{title} [{sid}]"), marked(text, sid)


def pull_issue(spec, sid):
    """The issue a pull request `spec` of scenario `sid` closes, opened first:
    its `issue:`, else a complete feature with its title. Pure."""
    return spec.get("issue") or {"title": spec.get("title", sid), "body": "complete-feature"}


def land_issue(sid, arg):
    """The accepted, claimed Docs issue the pull request that lands scenario
    `sid`'s `push: arg` on main closes (#698). Pure."""
    return {"title": f"docs: the scenario {sid} lands {arg} on main", "body": "task", "type": "Docs", "labels": ["accepted"], "comments": ["/claim"]}


def opened_issues(s, bodies):
    """Every issue scenario `s` opens, as (spec, default title), in the order
    `play` opens them: its `before` (a `lands`, #707, the Docs issue of its
    pull request to main), its own or its pull request's, and one per `push`
    that lands on main. Pure."""
    sid, opens = s.get("id") or "?", s.get("opens") or {}
    out = [(land_issue(sid, b["lands"]), sid) if "lands" in b else (b.get("issue") or {}, f"{sid}: before") for b in s.get("before") or []]
    if "issue" in opens:
        out.append((opens["issue"], sid))
    elif "pull" in opens and "{issue}" in body_of(opens["pull"].get("body"), bodies):
        out.append((pull_issue(opens["pull"], sid), sid))
    return out + [(land_issue(sid, st["push"]), sid) for st in s.get("steps") or [] if isinstance(st, dict) and st.get("push") in LANDS]


def open_issue(repo, spec, bodies, default, run=gh, sid=None, types=None):
    """The issue `spec` opened, with the Type its form would give it
    (`type_of`, #698), its title and body as `issue_text` writes them: its
    number. Its `comments` (a `/claim`) are posted before its labels, so a
    claim comes before its acceptance."""
    title, text = issue_text(spec, bodies, default, sid)
    kind, labels, first = type_of(spec, types), spec.get("labels") or [], spec.get("comments") or []
    url = run("issue", "create", "--repo", repo, "--title", title, "--body-file", "-", *(["--type", kind] if kind else []),
              *sum((["--label", l] for l in ([] if first else labels)), []), input=text).strip()
    number = url.rstrip("/").rsplit("/", 1)[-1]
    for c in first:
        run("issue", "comment", number, "--repo", repo, "--body", str(c))
    if first and labels:
        run("issue", "edit", number, "--repo", repo, *sum((["--add-label", l] for l in labels), []))
    return number


def fresh_branch(target, branch, run=gh):
    """`branch` in `target` made anew from its head (#694): a leftover of an
    earlier run deleted first (none is a 404, which is fine), so creating it
    never fails with 422 "Reference already exists"."""
    try:
        run("api", "-X", "DELETE", f"repos/{target}/git/refs/heads/{branch}")
    except RuntimeError:
        pass
    run("api", f"repos/{target}/git/refs", "-f", f"ref=refs/heads/{branch}", "-f", f"sha={run('api', f'repos/{target}/commits/HEAD', '--jq', '.sha').strip()}")


def branch_of(s):
    """The branch a scenario pushes to (#694): `<type>/scenario-<id>`, its
    title's type (the conventions check refuses any other branch), `test`
    for a title with none. Pure."""
    spec = (s.get("opens") or {}).get("pull") or (s.get("opens") or {}).get("issue") or {}
    m = re.match(r"^([a-z]+)(\([^)]*\))?!?: ", str(spec.get("title") or ""))
    return f"{m.group(1) if m else 'test'}/scenario-{s.get('id')}"


def has_branch(target, branch, run=gh):
    try:
        run("api", f"repos/{target}/git/ref/heads/{branch}", "--jq", ".ref")
        return True
    except RuntimeError:
        return False


# The bugfix-reproduced lane's issue for a confirmed report (scripts/
# repro-lane.py), which the App opens with no scenario's mark (#707).
LANE_ISSUE = re.compile(r"^The bug reproduced from #(\d+)$")


def lane_leftovers(repo, mark, run=gh):
    """Every open bugfix-reproduced lane issue in `repo` whose report
    carries `mark` closed (#707: a confirmed bug's, which `clear`'s search
    of the mark cannot find). A failure here never stops a scenario."""
    try:
        found = json.loads(run("issue", "list", "--repo", repo, "--state", "open", "--label", "lane:bugfix-reproduced",
                               "--json", "number,title", "--limit", "50") or "[]")
    except (RuntimeError, ValueError):
        return
    for item in found:
        m = LANE_ISSUE.match(str(item.get("title") or ""))
        if not m:
            continue
        try:
            if mark in str(json.loads(run("issue", "view", m.group(1), "--repo", repo, "--json", "body") or "{}").get("body") or ""):
                run("issue", "close", str(item["number"]), "--repo", repo)
        except (RuntimeError, ValueError):
            pass


def clear(repo, sid, run=gh, branch=None, lands=()):
    """What scenario `sid` left in `repo`, before it plays and after (#694):
    its branches deleted (`scenario/<id>`, which earlier runs left,
    `branch`, its own now, and those of the pull requests its pushes and
    its `before`'s `lands` put on main through, `landing`), and every open
    issue and pull request whose body carries its mark closed. A failure
    here never stops a scenario: what it cannot clear, the next run
    clears. A confirmed bug's lane issue, whose report carries the mark, is
    closed too (`lane_leftovers`, #707)."""
    for name in dict.fromkeys([f"scenario/{sid}"] + ([branch] if branch else []) + [landing(sid, a) for a in (*LANDS, *lands)]):
        try:
            run("api", "-X", "DELETE", f"repos/{repo}/git/refs/heads/{name}")
        except RuntimeError:
            pass  # none left: a 404
    mark = scenario_mark(sid)
    lane_leftovers(repo, mark, run)
    for what in ("issue", "pr"):
        try:
            found = json.loads(run(what, "list", "--repo", repo, "--state", "open", "--search", f'"dx-scenario: {sid}" in:body',
                                   "--json", "number,body", "--limit", "50") or "[]")
        except (RuntimeError, ValueError):
            continue
        for item in found:
            if mark not in str(item.get("body") or ""):
                continue  # the search matched another scenario's, or none
            try:
                if what == "issue":
                    run("issue", "close", str(item["number"]), "--repo", repo)
                else:
                    run("pr", "close", str(item["number"]), "--repo", repo, "--delete-branch")
            except RuntimeError:
                pass


# What `fork-without-secrets` needs (#694): the test identity's own token
# that may create its fork (DX_TEST_TOKEN is scoped to the test repository
# alone, so GitHub answers its fork with 403).
FORK_SECRET = "DX_TEST_FORK_TOKEN"
FORK_NEEDS = (f"a scenario from a fork needs {FORK_SECRET}, a token of the test identity that may fork the test repository: a fine-grained token "
              "with Administration and Contents read and write on the test identity's own repositories (or a classic one with public_repo), "
              "a secret of the `release` environment")


def fork_gh():
    """The runner a fork's calls go through: the test identity's fork token
    (FORK_SECRET), or None when it is not set."""
    token = os.environ.get(FORK_SECRET)
    return (lambda *args, input=None: gh(*args, input=input, token=token)) if token else None


# What a `push` lands on main besides its head branch (#698): `conflict`
# the same file, with other content, and `behind` a file of its own,
# through a pull request of the scenario that merges (`landing`), since the
# test repository's rulesets refuse a write to main.
LANDS = ("conflict", "behind")


def landing(sid, arg):
    """The branch of the pull request that lands scenario `sid`'s `push:
    arg` on main: a docs one, its file Markdown under the scenario's own
    directory. Pure."""
    return f"docs/scenario-{sid}-{arg}"


COMMIT = ("mutation($input: CreateCommitOnBranchInput!) "
          "{ createCommitOnBranch(input: $input) { commit { oid } } }")


def commit_files(target, branch, files, headline, run=gh):
    """`files` ({path: text}) written on `branch` of `target` in one commit,
    through the GraphQL mutation `createCommitOnBranch` (#709): GitHub signs
    it, so the signed-commits ruleset takes it, and no file's sha is needed.
    The branch's head is read first, its `expectedHeadOid`; a branch that
    moved in between (the autopilot pushed on it) is read again and the
    commit made on its new head, up to `MOVED` times."""
    import base64
    for left in range(MOVED, 0, -1):
        head = run("api", f"repos/{target}/git/ref/heads/{branch}", "--jq", ".object.sha").strip()
        query = {"query": COMMIT, "variables": {"input": {
            "branch": {"repositoryNameWithOwner": target, "branchName": branch}, "expectedHeadOid": head, "message": {"headline": headline},
            "fileChanges": {"additions": [{"path": path, "contents": base64.b64encode(text.encode()).decode()} for path, text in files.items()]}}}}
        try:
            run("api", "graphql", "--input", "-", input=json.dumps(query))
            return
        except RuntimeError as e:
            if left == 1 or not re.search(r"expected branch to point to", str(e), re.I):
                raise


# How many times `commit_files` reads a branch that moved under it again.
MOVED = 3


def write_file(target, branch, path, content, run=gh):
    """`path` written on `branch` of `target` with `content`, in a commit of
    its own (`commit_files`)."""
    commit_files(target, branch, {path: content}, f"test: {path}", run)


# A `gh` that failed for a while, not for good (#698): a rate limit (the
# primary's 403 or 429, the secondary's), or GitHub's own 5xx.
TRANSIENT = re.compile(r"rate limit|HTTP 429|HTTP 5\d\d|abuse detection|timed out|connection reset|unexpected EOF", re.I)


def transient(e):
    """Whether the GhError `e` is worth retrying (`TRANSIENT`). Pure."""
    return isinstance(e, GhError) and bool(TRANSIENT.search(f"{e} {e.stderr}"))


def backoff(e, tries, now=None):
    """The seconds to wait before retrying the transient `e`, the `tries`-th
    time: GitHub's `retry-after`, else until its `x-ratelimit-reset`, else
    POLL doubled each time, at most 120. Pure but for `now`."""
    text = f"{e} {getattr(e, 'stderr', '')}"
    m = re.search(r"retry-after:?\s*(\d+)", text, re.I)
    if m:
        return max(1, int(m.group(1)))
    m = re.search(r"x-ratelimit-reset:?\s*(\d+)", text, re.I)
    if m:
        return max(1, int(m.group(1)) - int(time.time() if now is None else now))
    return min(POLL * 2 ** tries, 120)


def play(s, repo, ref, bodies, run=gh, sleep=time.sleep, minutes=20, fork=None, types=None):
    """One scenario in `repo`: clears what an earlier run of it left
    (`clear`), opens what it opens (its `before` first), takes its steps,
    polls until its `expect` holds or `minutes` pass, then cleans up and
    clears again. Returns {id, ok, why, run}."""
    opens, made, closes = s.get("opens") or {}, [], None
    what = "pr" if "pull" in opens else "issue"
    spec = opens.get("pull") or opens.get("issue") or {}
    sid, own = s["id"], branch_of(s)
    left = [min(minutes, limit(s)) * 60]

    def look(on):
        """`on` observed, a transient `gh` error (#698: a rate limit, a
        5xx) retried after its back-off within the scenario's time, never a
        failure at once: (what was seen, None), or (None, why) once its time
        ran out with `gh` still failing."""
        tries = 0
        while True:
            try:
                return observe(repo, on[0], on[1], run), None
            except GhError as e:
                if not transient(e):
                    raise
                if left[0] <= 0:
                    return None, f"{str(e).split(': ', 1)[0]} rate limited or failing at GitHub until the scenario's time ran out: {str(e).split(': ', 1)[-1][:200]}"
                wait = min(backoff(e, tries), max(left[0], 1))
                sleep(wait)
                left[0] -= wait
                tries += 1

    def poll(expect, on, closes):
        """`on` (what, number) observed every POLL seconds until `expect`
        holds ([]), can no longer hold (#694: `hopeless`), or the
        scenario's time is up: (what was seen, why not)."""
        idle, last = False, {}
        while True:
            seen, failing = look(on)
            if failing:
                return last, [failing]
            last = seen
            if closes:
                seen["closes"] = closes
            why = holds(expect, seen)
            if not why:
                return seen, []
            lost = hopeless(expect, seen, idle and seen.get("idle"))
            if lost:
                return seen, why + [f"it can no longer hold: {'; '.join(lost)}"]
            if left[0] <= 0:
                return seen, why
            idle = seen.get("idle")
            sleep(POLL)
            left[0] -= POLL

    def land(arg, path, content=None):
        """`path` landed on main (#698), with other content than any push
        wrote on the head (or `content`, #707): an accepted, claimed Docs
        issue of the scenario and a docs pull request that closes it, polled
        until it merged (the auto-merge of a low-risk change). [] once it
        did, else why not."""
        n = open_issue(repo, land_issue(sid, arg), bodies, sid, run, sid, types)
        made.append(("issue", n))
        branch = landing(sid, arg)
        fresh_branch(repo, branch, run)
        write_file(repo, branch, path, f"{arg} on main\n" if content is None else content, run)
        body = body_of("pull", bodies).replace("{issue}", n) if "{issue}" in body_of("pull", bodies) else f"Closes #{n}"
        got = run("pr", "create", "--repo", repo, "--head", branch, "--title", f"docs: the scenario {sid} lands {arg} on main",
                  "--body-file", "-", input=marked(body, sid)).strip()
        made.append(("pr", got.rstrip("/").rsplit("/", 1)[-1]))
        seen, why = poll({"merged": True}, ("pr", made[-1][1]), None)
        return [f"push {arg}: its pull request to main {got}: {w}" for w in why]
    lands = [str(b["lands"]) for b in s.get("before") or [] if "lands" in b]
    befores = []
    try:
        clear(repo, sid, run, own, lands)
        for first in s.get("before") or []:
            if "lands" in first:
                # #707: a file of the scenario's own on main before its issue
                # opens (the greeting a bug's reproduction reads), landed
                # only when main does not say it already.
                path, content = f"scenarios/{sid}/{first['lands']}.md", f"{first.get('says', '')}\n"
                try:
                    there = text_at(repo, path, "main", run)
                except (RuntimeError, ValueError):
                    there = None  # not there yet: a 404
                if there != content:
                    why = land(str(first["lands"]), path, content)
                    if why:
                        return {"id": sid, "ok": False, "why": [w.replace("push ", "before: lands ", 1) for w in why], "run": ""}
                continue
            befores.append(open_issue(repo, first.get("issue") or {}, bodies, f"{sid}: before", run, sid, types))
            made.append(("issue", befores[-1]))
        if what == "issue":
            url = f"/{open_issue(repo, spec, bodies, sid, run, sid, types)}"
        else:
            text = body_of(spec.get("body"), bodies)
            if "{issue}" in text:
                closes = open_issue(repo, pull_issue(spec, sid), bodies, sid, run, sid, types)
                made.append(("issue", closes))
                text = text.replace("{issue}", closes)
            branch, target = own, repo
            writes = run
            if spec.get("fork"):
                # From the test identity's fork, which runs with no secrets,
                # made and written with its fork token (#694).
                # `fork`: its runner, False for none; None reads FORK_SECRET.
                writes = fork_gh() if fork is None else (fork or None)
                if writes is None:
                    raise RuntimeError(FORK_NEEDS)
                writes("repo", "fork", repo, "--clone=false", "--default-branch-only")
                target = f"{writes('api', 'user', '--jq', '.login').strip()}/{repo.split('/', 1)[1]}"
            fresh_branch(target, branch, writes)
            write_file(target, branch, f"scenarios/{sid}/pull.md", sid, writes)
            head = f"{target.split('/', 1)[0]}:{branch}" if target != repo else branch
            url = run("pr", "create", "--repo", repo, "--head", head, "--title", spec.get("title", f"test: {sid}"),
                      "--body-file", "-", input=marked(text, sid)).strip()
        number = url.rstrip("/").rsplit("/", 1)[-1]
        made.append((what, number))
        for step in s.get("steps") or []:
            (verb, arg), = ((k, v) for k, v in step.items() if k != "of")
            # #713: `of: before` takes a comment or a label on the first
            # issue it opened before it (its acceptance after its triage).
            kind, target = ("issue", befores[0]) if step.get("of") == "before" and befores else (what, number)
            if verb == "comment":
                run(kind, "comment", target, "--repo", repo, "--body", str(arg))
            elif verb in ("label", "unlabel"):
                run(kind, "edit", target, "--repo", repo, f"--{'add' if verb == 'label' else 'remove'}-label", str(arg))
            elif verb == "edit":
                run(what, "edit", number, "--repo", repo, "--body-file", "-", input=marked(body_of(arg, bodies), sid))
            elif verb == "dispatch":
                run("workflow", "run", str(arg), "--repo", repo, "--ref", "main")
            elif verb == "push":
                # #698: on the head branch of the pull request it observes
                # (an issue's, the autopilot's), never a branch of its own
                # no pull request reads; `behind` writes none there.
                path = f"scenarios/{sid}/{arg}.md"
                if arg != "behind":
                    head = own
                    if what == "issue":
                        seen, failing = look((what, number))
                        head = ((seen or {}).get("pull") or {}).get("branch")
                        if not head:
                            return {"id": sid, "ok": False, "why": [failing or f"push {arg}: no pull request closes #{number} to push to"], "run": (seen or {}).get("run", "")}
                    write_file(repo, head, path, f"{arg} on the pull request\n", run)
                if arg in LANDS:
                    why = land(arg, path)
                    if why:
                        return {"id": sid, "ok": False, "why": why, "run": ""}
            elif verb == "until":
                # #694: polled every POLL seconds, never a fixed wait: on
                # the scenario's own issue or pull request, or with `of:
                # before` on the first issue it opened before it.
                want = {k: v for k, v in (arg or {}).items() if k != "of"}
                on = (("issue", befores[0]) if (arg or {}).get("of") == "before" and befores else (what, number))
                seen, why = poll(want, on, None if on[1] != number else closes)
                if why:
                    return {"id": sid, "ok": False, "why": [f"until {json.dumps(want, sort_keys=True)}: {w}" for w in why], "run": seen.get("run", "")}
            elif verb == "wait":
                # Refused by `timing`; never slept.
                raise ValueError(f"a fixed wait of {arg} seconds: wait `until` a state")
        seen, why = poll(s.get("expect") or {}, (what, number), closes)
        return {"id": sid, "ok": not why, "why": why, "run": seen.get("run", "")}
    except (RuntimeError, ValueError) as e:
        return {"id": sid, "ok": False, "why": [str(e)], "run": ""}
    finally:
        cleanup(repo, made, run)
        clear(repo, sid, run, own, lands)


def bot_login(login):
    """Whether `login` is the organisation's App, as either API names it
    (dilux-bot, dilux-bot[bot], app/dilux-bot)."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import org
    name = str(login or "").removeprefix("app/").removesuffix("[bot]")
    return bool(name) and name in {str(org.APP), str(org.BOT).removesuffix("[bot]")}


def observe(repo, what, number, run=gh):
    fields = "labels,comments,body,state" + (",mergedAt,statusCheckRollup,headRefName,headRefOid,title" if what == "pr" else ",closedByPullRequestsReferences")
    # A `gh` that fails raises GhError; `play` retries a transient one.
    view = json.loads(run(what, "view", number, "--repo", repo, "--json", fields) or "{}")
    seen = {"number": number, "labels": [l.get("name") for l in view.get("labels") or []],
            "comments": [c.get("body", "") for c in view.get("comments") or []], "state": view.get("state"),
            # The bot's own comments, oldest first (#707: `saw`).
            "said": [c.get("body", "") for c in view.get("comments") or [] if bot_login((c.get("author") or {}).get("login"))]}
    if what == "pr":
        seen["pull"] = {"body": view.get("body"), "branch": view.get("headRefName"), "title": view.get("title")}
        seen["merged"] = bool(view.get("mergedAt"))
        seen["checks"] = {c.get("name"): (c.get("conclusion") or "").lower() for c in view.get("statusCheckRollup") or []}
        # #709: a run on its head that GitHub holds for a maintainer's
        # approval (a fork's): it never reports until a person allows it.
        seen["held"] = []
        if view.get("headRefOid"):
            head = json.loads(run("run", "list", "--repo", repo, "--commit", str(view["headRefOid"]), "--json", "url,status,conclusion") or "[]")
            seen["held"] = [str(r.get("url") or "") for r in head if "action_required" in (str(r.get("status") or "").lower(), str(r.get("conclusion") or "").lower())]
    else:
        # #698: the pull request that closes it, from the issue's own
        # references (the newest), never a search per poll: the search API
        # allows 30 a minute, which every scenario at once shares.
        refs = [r.get("number") for r in view.get("closedByPullRequestsReferences") or []
                if f"github.com/{repo}/pull/".lower() in str(r.get("url") or f"github.com/{repo}/pull/").lower()]
        refs = [r for r in refs if isinstance(r, int)]
        if refs:
            pull = json.loads(run("pr", "view", str(max(refs)), "--repo", repo, "--json", "number,body,headRefName,title") or "{}")
            seen["pull"] = {"body": pull.get("body"), "branch": pull.get("headRefName"), "title": pull.get("title"), "number": pull.get("number")}
    seen["waiting"] = any(l in seen["labels"] for l in ("needs-human", "autopilot:waiting", "awaiting-acceptance"))
    runs = json.loads(run("run", "list", "--repo", repo, "--limit", "20", "--json", "url,status") or "[]")
    seen["run"] = runs[0]["url"] if runs else ""
    # Nothing queued or in progress in the test repository (#694: `hopeless`).
    seen["idle"] = not any(str(r.get("status") or "").lower() in RUNNING for r in runs)
    return seen


def cleanup(repo, made, run=gh):
    """`cleanup: after-run`: its issues closed and locked, its pull requests
    closed and their branches deleted. A failure here never hides a
    result."""
    for what, number in made:
        try:
            if what == "issue":
                run("issue", "close", number, "--repo", repo)
                run("issue", "lock", number, "--repo", repo)
            else:
                run("pr", "close", number, "--repo", repo, "--delete-branch")
        except RuntimeError:
            pass


def at_ref(text, central, ref):
    """A caller's calls of the engine at `ref`, its pinned version's comment
    dropped; a call already at `ref` stays as it is, comment and all. Pure."""
    def to(m):
        return m.group(0) if m.group(2) == ref else f"{m.group(1)}@{ref}"
    return re.sub(USES.format(re.escape(central)), to, text, flags=re.M)


USES = r"^(\s+uses: {}/\.github/workflows/[\w.-]+\.yml)@(\S+)([ \t]+#[^\n]*)?$"


def only_ref(before, after, central):
    """What differs between a caller's `before` and `after` other than the
    engine's ref: None when both have the same lines and every line that
    differs is, on both sides, a call of the same engine workflow (the
    calls `at_ref` rewrites) with only its ref and its pin's comment
    changed, else the first line that differs ("line N: ..."). Pure."""
    one, two = before.split("\n"), after.split("\n")
    uses = re.compile(USES.format(re.escape(central)))
    for i in range(max(len(one), len(two))):
        b, a = (one[i] if i < len(one) else None), (two[i] if i < len(two) else None)
        if b == a:
            continue
        mb, ma = uses.match(b or ""), uses.match(a or "")
        if not (mb and ma and mb.group(1) == ma.group(1)):
            return f"line {i + 1}: {(a if a is not None else b).strip()!r}"
    return None


def callers_gh():
    """The runner `point_callers` writes with: the bot's token
    (DX_CALLERS_TOKEN, the App's, scoped to the test repository) when it is
    set, else the ambient one."""
    token = os.environ.get("DX_CALLERS_TOKEN")
    return (lambda *args, input=None: gh(*args, input=input, token=token)) if token else gh


def text_at(repo, path, sha, run=gh):
    """A file's text at a commit."""
    import base64
    from urllib.parse import quote
    got = json.loads(run("api", f"repos/{repo}/contents/{quote(path)}?ref={sha}") or "{}")
    return base64.b64decode(got.get("content") or "").decode()


def not_only_ref(repo, number, base, head, names, central, run=gh):
    """What the pull request `number` really changes, read from GitHub
    (every page of its files, and each one's text at `base` and `head`),
    other than the engine's ref in the callers the lane wrote (`names`,
    under .github/workflows/): None when nothing, else the first file and
    line that differ."""
    pages = json.loads(run("api", "--paginate", "--slurp", f"repos/{repo}/pulls/{number}/files") or "[]")
    files = [f for page in pages for f in (page if isinstance(page, list) else [page])]
    wanted = {f".github/workflows/{n}" for n in names}
    for f in files:
        path, status = str(f.get("filename") or ""), f.get("status")
        if path not in wanted:
            return f"{path} ({status}) is not a caller the lane wrote"
        if status != "modified":
            return f"{path} is {status}" + (f" from {f.get('previous_filename')}" if f.get("previous_filename") else "")
    missing = sorted(wanted - {str(f.get("filename") or "") for f in files})
    if missing:
        return f"{missing[0]} is not changed by it"
    for f in files:
        differs = only_ref(text_at(repo, f["filename"], base, run), text_at(repo, f["filename"], head, run), central)
        if differs:
            return f"{f['filename']} {differs}"
    return None


DONE = ("COMPLETED", "SUCCESS", "FAILURE", "ERROR")


def required_checks(repo, number, run=gh):
    """The head's required checks, [{name, bucket}]: none yet while GitHub
    reports none (a pull request just opened), whatever `gh pr checks`
    exits with while one is pending (8) or failed (1)."""
    try:
        return json.loads(run("pr", "checks", number, "--repo", repo, "--required", "--json", "name,bucket") or "[]")
    except GhError as e:
        if e.stdout.strip():
            return json.loads(e.stdout)
        if "no required checks reported" in e.stderr or "no checks reported" in e.stderr:
            return []
        raise


def merge_when_checked(repo, number, url, head, run=gh, sleep=time.sleep, minutes=20):
    """The lane's own callers pull request merged by the lane, never by
    auto-merge (the auto-merge decision never merges a change to
    .github/workflows): once its required checks pass at `head` and every
    other check there finished (so nothing turns anything off after it is
    queued), queued with `gh pr merge --squash --match-head-commit`, which
    goes through the merge queue and never past it, then waited for until
    it merged. Raises, naming the pull request and the check, on a required
    check that fails or is cancelled, a pull request that closes, a head
    that moves, or `minutes` running out."""
    waited, queued, why = 0, False, "its checks did not finish"
    while True:
        view = json.loads(run("pr", "view", number, "--repo", repo, "--json", "mergedAt,state,headRefOid,statusCheckRollup") or "{}")
        if view.get("mergedAt"):
            return
        if view.get("state") == "CLOSED":
            raise RuntimeError(f"the pull request {url} that moves them closed unmerged")
        if view.get("headRefOid") and view["headRefOid"] != head:
            raise RuntimeError(f"the pull request {url} that moves them changed head ({view['headRefOid']}, not {head})")
        if not queued:
            required = required_checks(repo, number, run)
            bad = [c.get("name") for c in required if c.get("bucket") in ("fail", "cancel")]
            if bad:
                raise RuntimeError(f"the pull request {url} that moves them failed its required check {bad[0]}")
            rollup = view.get("statusCheckRollup") or []
            pending = [c.get("name") or c.get("context") for c in rollup if (c.get("status") or c.get("state") or "").upper() not in DONE]
            pending += [c.get("name") for c in required if c.get("bucket") not in ("pass", "skipping")]
            if rollup and not pending:
                run("pr", "merge", number, "--repo", repo, "--squash", "--match-head-commit", head)
                queued, why = True, "it did not merge from the merge queue"
            else:
                why = f"its check {pending[0]} did not finish" if pending else "it reported no check"
        if waited >= minutes * 60:
            raise RuntimeError(f"the pull request {url} that moves them did not merge in {minutes} minutes: {why}")
        sleep(POLL)
        waited += POLL


def point_callers(repo, ref, run=gh, central=None, back=None, sleep=time.sleep, minutes=20):
    """The test repository's callers at `ref` (`v7-next` while the lane
    tries a candidate, `v7` once the installer plays them), so what plays
    is that ref's engine; with `back` ({name: text}), those callers put back
    as they were. Never written on the default branch, which its rulesets
    protect: the change goes on `ci/callers-<ref>`, through a pull request
    the lane merges itself (`merge_when_checked`: the merge queue, once its
    checks pass; auto-merge never merges a change to .github/workflows),
    and it returns once that merged. Nothing to change opens nothing. Returns what it moved,
    each caller's `name` and its text `before`."""
    import base64
    if central is None:
        sys.path.insert(0, HERE)
        import org
        central = org.CENTRAL
    changes = []
    for f in json.loads(run("api", f"repos/{repo}/contents/.github/workflows") or "[]"):
        name = str(f.get("name", ""))
        if not name.endswith(".yml") or (back is not None and name not in back):
            continue
        got = json.loads(run("api", f"repos/{repo}/contents/.github/workflows/{name}") or "{}")
        text = base64.b64decode(got.get("content") or "").decode()
        new = back[name] if back is not None else at_ref(text, central, ref)
        if new != text:
            changes.append((name, text, new))
    if not changes:
        return []
    base = run("api", f"repos/{repo}", "--jq", ".default_branch").strip()
    branch = f"ci/callers-{ref}" + ("-back" if back is not None else "")
    try:
        run("api", "-X", "DELETE", f"repos/{repo}/git/refs/heads/{branch}")
    except RuntimeError:
        pass  # no leftover
    head = run("api", f"repos/{repo}/git/ref/heads/{base}", "--jq", ".object.sha").strip()
    run("api", f"repos/{repo}/git/refs", "-f", f"ref=refs/heads/{branch}", "-f", f"sha={head}")
    title = f"ci: the engine's callers {'back from' if back is not None else 'at'} {ref}"
    commit_files(repo, branch, {f".github/workflows/{name}": new for name, _, new in changes}, title, run)
    url = run("pr", "create", "--repo", repo, "--base", base, "--head", branch, "--title", title, "--body-file", "-",
              input=f"The release lane's scenarios (scripts/release-scenarios.py): {title[4:]}.\n").strip()
    number = url.rstrip("/").rsplit("/", 1)[-1]
    try:
        pull = json.loads(run("api", f"repos/{repo}/pulls/{number}") or "{}")
        base_sha, head = pull["base"]["sha"], pull["head"]["sha"]
        differs = not_only_ref(repo, number, base_sha, head, [name for name, _, _ in changes], central, run)
        if differs:
            raise RuntimeError(f"the pull request {url} that moves them changes more than the engine's ref, so the lane does not merge it: {differs}")
        merge_when_checked(repo, number, url, head, run, sleep, minutes)
    except (RuntimeError, ValueError):
        try:
            run("pr", "close", number, "--repo", repo, "--delete-branch")
        except RuntimeError:
            pass
        raise
    return [{"name": name, "before": text} for name, text, _ in changes]


def put_back(repo, ref, moved, callers=gh, central=None, sleep=time.sleep, minutes=20):
    """The callers `point_callers` moved (`moved`) put back from `ref`,
    through another merged pull request: [] once they are, else one failing
    `callers` row that says why."""
    if not moved:
        return []
    try:
        point_callers(repo, ref, callers, central, back={m["name"]: m["before"] for m in moved}, sleep=sleep, minutes=minutes)
    except (RuntimeError, ValueError) as e:
        return [{"id": "callers", "ok": False, "why": [f"the callers were not put back from {ref}: {e}"], "run": ""}]
    return []


def write_moved(moved, path):
    """What moved written to `path`, for `back`."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(moved, fh)


def read_moved(path, ref):
    """What `run --moved` wrote to `path`, and the rows that say why it could
    not be read: a missing or unreadable file is "could not tell", never
    "nothing moved" (a run cancelled or killed while pointing writes none),
    so it is one failing `callers` row."""
    try:
        with open(path, encoding="utf-8") as fh:
            moved = json.load(fh)
        if not isinstance(moved, list) or not all(isinstance(m, dict) and "name" in m and "before" in m for m in moved):
            raise ValueError("not a list of moved callers")
        return moved, []
    except (OSError, ValueError) as e:
        return [], [{"id": "callers", "ok": False, "why": [f"could not read what moved to {ref}, the callers may be left there: {e}"], "run": ""}]


def move_callers(repo, ref, callers=gh, central=None, sleep=time.sleep, minutes=20, record=None):
    """The test repository's callers moved to `ref` (`point_callers`):
    (what moved, []) once they are, else ([], one failing `callers` row that
    says why). `record`, when given, is called with what moved as soon as
    the pointing is over ([] when it failed cleanly)."""
    try:
        moved = point_callers(repo, ref, callers, central, sleep=sleep, minutes=minutes)
    except (RuntimeError, ValueError) as e:
        if record:
            record([])
        return [], [{"id": "callers", "ok": False, "why": [f"the callers did not reach {ref}: {e}"], "run": ""}]
    if record:
        record(moved)
    return moved, []


GROUP_ID = re.compile(r"[a-z0-9-]+")
# The artifacts the lane names after them besides the groups' (scenarios-*).
NOT_GROUPS = ("move", "back")


def groups(scenarios):
    """The groups the lane plays at once, one job each (release-lane.yml
    `play`): every scenario in its own, named by its id (#694: each writes
    under its own directory, `core_writes`, so none waits on another). [{id,
    scenarios}]. Pure."""
    return [{"id": s.get("id"), "scenarios": [s.get("id")]} for s in scenarios]


def core_writes(s, pack):
    """The core paths scenario `s` can write in the test repository: its
    fixed change's file (`{scenario}` its id), its pull request's file and
    its pushes, as globs of their directory. Pure."""
    sid = s.get("id") or "?"
    fixed = str((pack.get("fixed-change") or {}).get("file") or "")
    out = {fixed.replace("{scenario}", sid).replace("{n}", "*").replace("{id}", "*")} if fixed else set()
    return out | {f"scenarios/{sid}/*"}


def partition(scenarios, gs, pack=None):
    """What is wrong with the groups `gs` of `scenarios`: a scenario in no
    group or in two, a group that plays no scenario of the file, a group id
    unfit for an artifact name (`^[a-z0-9-]+$`, nor `move` or `back`) or used
    twice, and (#694) two scenarios that could write to the same part of the
    test repository's core (`pack`'s, scripts/org.py core_key), which would
    wait on each other's change, and (#709) any that writes under it but
    expects no wait on it (`core_problems`). Pure."""
    out, where, ids = [], {}, [s.get("id") or "?" for s in scenarios]
    seen = set()
    for g in gs:
        gid = str(g.get("id"))
        if not GROUP_ID.fullmatch(gid) or gid in NOT_GROUPS:
            out.append(f"group {gid}: its id is unfit for an artifact name (^[a-z0-9-]+$, nor {' or '.join(NOT_GROUPS)})")
        if gid in seen:
            out.append(f"group {gid}: its id is used twice")
        seen.add(gid)
        for sid in g.get("scenarios") or []:
            where.setdefault(sid, []).append(gid)
    for sid in ids:
        if not where.get(sid):
            out.append(f"scenario {sid}: in no group")
        elif len(where[sid]) > 1:
            out.append(f"scenario {sid}: in {len(where[sid])} groups ({', '.join(where[sid])})")
    for sid in where:
        if sid not in ids:
            out.append(f"group {', '.join(where[sid])}: plays {sid}, which is no scenario of {SCENARIOS}")
    if pack is not None:
        owner = {}
        for s in scenarios:
            sid = s.get("id") or "?"
            for path in sorted(core_writes(s, pack)):
                key = org_key(path, pack)
                if key is None:
                    continue
                if key in owner and owner[key] != sid:
                    out.append(f"scenario {sid}: writes {path}, on the core {key or 'of the test repository'} scenario {owner[key]} writes too, so one would wait on the other")
                    break
                owner.setdefault(key, sid)
        out += core_problems(scenarios, pack)
    return out


def waits_on_core(s):
    """Whether scenario `s` expects to wait on the core (`autopilot:core-wait`
    or its comment's mark). Pure."""
    expect = s.get("expect") or {}
    return CORE_LABEL in (expect.get("labels") or []) or CORE_MARK in (expect.get("comments") or [])


SEAL = "<!-- dx-prd-seal -->"


def needs_autopilot(want):
    """Whether the expectation `want`, on an issue, needs the autopilot's
    result (#713): its seal, the `autopilot` or core-wait label, its comment
    on the core, or its pull request. Pure."""
    want = want or {}
    return (any(m in (want.get("comments") or []) for m in (SEAL, CORE_MARK))
            or any(l in (want.get("labels") or []) for l in ("autopilot", CORE_LABEL)) or bool(want.get("pull")))


def autopilot_problems(scenarios):
    """Every scenario that reads the autopilot's result on an issue (its own,
    or with `of: before` its first `before` one: `needs_autopilot`; a
    release issue's pull request is the release's) too
    early (#713): one that opens that issue `accepted` (the autopilot then
    reads a body the triage had not answered, unsealed), takes no `label:
    accepted` step, takes it before an `until` the triage's verdict
    (`awaiting-acceptance`), or waits for no seal (`until` the
    `dx-prd-seal` comment) after it, before its expectation. And every
    scenario whose `/claim` comes after its issue's acceptance (the
    autopilot has started then, and the claim is refused). Pure."""
    out = []
    for s in scenarios:
        sid, opens, steps = s.get("id") or "?", s.get("opens") or {}, [st for st in s.get("steps") or [] if isinstance(st, dict)]
        if "issue" not in opens:
            continue
        first = ((s.get("before") or [{}])[0] or {}).get("issue")
        for of, spec in (("own", opens["issue"]), ("before", first)):
            # A release issue's pull request is the release's (issue-accepted.yml), never the autopilot's.
            if spec is None or "lane:release" in (spec.get("labels") or []):
                continue
            on = [st for st in steps if ((st.get("until") or {}).get("of") if "until" in st else st.get("of")) == ("before" if of == "before" else None)]
            wants = [st["until"] for st in on if "until" in st] + ([s.get("expect")] if of == "own" else [])
            name = "its issue" if of == "own" else "its `before` issue"
            accepted = next((i for i, st in enumerate(on) if st.get("label") == "accepted"), None)
            claim = next((i for i, st in enumerate(on) if str(st.get("comment") or "").startswith("/claim")), None)
            if claim is not None and ("accepted" in (spec.get("labels") or []) or (accepted is not None and accepted < claim)):
                out.append(f"scenario {sid}: comments /claim on {name} after it is accepted, when the autopilot has started and the claim is refused")
            if not any(needs_autopilot(w) for w in wants):
                continue
            if "accepted" in (spec.get("labels") or []):
                out.append(f"scenario {sid}: opens {name} accepted, before the triage answered it, so the autopilot reads it unsealed; "
                           f"open it plain, wait `until` awaiting-acceptance, then take `label: accepted`")
                continue
            if accepted is None:
                out.append(f"scenario {sid}: expects the autopilot's result on {name}, which it never accepts (`label: accepted`)")
                continue
            if not any("awaiting-acceptance" in ((st.get("until") or {}).get("labels") or []) for st in on[:accepted]):
                out.append(f"scenario {sid}: accepts {name} before the triage's verdict (no `until` awaiting-acceptance before its `label: accepted`)")
            if not any(SEAL in ((st.get("until") or {}).get("comments") or []) for st in on[accepted + 1:]):
                out.append(f"scenario {sid}: reads the autopilot's result on {name} with no `until` its seal ({SEAL}) after its `label: accepted`")
    return out


def core_problems(scenarios, pack):
    """Every scenario that writes under the test repository's core (`pack`'s
    `core`) but expects no wait on it (#709): its fixed change would make its
    issue wait on another's open pull request (scripts/autopilot.py
    core_busy), so only the one scenario that expects `autopilot:core-wait`
    writes there. Pure."""
    out = []
    for s in scenarios:
        if waits_on_core(s):
            continue
        for path in sorted(core_writes(s, pack)):
            if org_key(path, pack) is not None:
                out.append(f"scenario {s.get('id') or '?'}: writes {path}, under the test repository's core ({', '.join(pack.get('core') or [])}), "
                           f"but expects no wait on it, so its issue could wait on another's change")
                break
    return out


def play_group(conf, gid, repo, ref, run=gh, sleep=time.sleep, minutes=20):
    """The scenarios of the group `gid` (one, #694), in its order, at
    `ref` (the callers already there), with the test identity's token (the
    ambient GH_TOKEN): their rows, or one failing row when `gid` is no
    group."""
    scenarios = conf.get("scenarios") or []
    group = next((g for g in groups(scenarios) if g["id"] == gid), None)
    if group is None:
        return [{"id": gid, "ok": False, "why": [f"{gid} is no group of {SCENARIOS}"], "run": ""}]
    by_id = {s.get("id"): s for s in scenarios}
    return [play(by_id[sid], repo, ref, conf.get("bodies") or {}, run, sleep, minutes, types=conf.get("types") or {}) for sid in group["scenarios"]]


def run_all(conf, repo, ref, only=(), run=gh, sleep=time.sleep, minutes=20, central=None, callers=None, moved_out=None, record=None):
    """Every scenario at `ref`: the callers moved there first (a merged pull
    request, or no scenario plays and one failing `callers` row says why),
    and put back after, through another; a failure to put them back is a
    failing `callers` row too, so nothing is released over a test repository
    left at `ref`. With `moved_out` (a list), what moved goes there and is
    not put back: the caller does that with `put_back`, with a token minted
    after the scenarios (an App's lasts an hour, the scenarios can take
    longer). `record`, when given, is called with what moved as soon as the
    pointing is over ([] when it failed cleanly), before the first scenario
    plays: a run killed after that still leaves the record `back` reads."""
    bodies = conf.get("bodies") or {}
    callers = callers or (callers_gh() if run is gh else run)
    moved, rows = move_callers(repo, ref, callers, central, sleep, minutes, record)
    if rows:
        return rows
    if moved_out is not None:
        moved_out.extend(moved)
    results = []
    try:
        for s in conf.get("scenarios") or []:
            if not only or s["id"] in only:
                results.append(play(s, repo, ref, bodies, run, sleep, minutes, types=conf.get("types") or {}))
    finally:
        if moved_out is None:
            results.extend(put_back(repo, ref, moved, callers, central, sleep, minutes))
    return results


def write_results(results, out):
    """The table of `results` to stdout, and to `out` with the record the
    lane's next job reads."""
    text = table(results)
    sys.stdout.write(text)
    if out:
        # The job's --out may name a directory no step made (#693).
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.write(f"\n<!-- dx-scenarios {json.dumps(results)} -->\n")


def read_results(path):
    """The results `write_results` wrote to `path`; [] when there are none."""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return []
    m = re.search(r"<!-- dx-scenarios (.*) -->", text)
    return json.loads(m.group(1)) if m else []


def merge(gs, files, jobs, run="", minutes=0, play_minutes=0):
    """One table of every scenario's result, from what the lane's jobs
    wrote (`files`: {"move"|"back"|<group id>: rows, or None for a file
    that is missing}) and how they ended (`jobs`: {name: result}): the
    move's rows, each group's rows of its own scenarios in its order (a row
    for a scenario of another group is ignored), the back's rows, then a
    failing row, with `run`, for each group whose file is missing (its job
    failed before it wrote it, timed out or was cancelled), each scenario
    with no row in its group's file, a missing move or back file, no groups
    at all, and each job whose result is not `success`. `minutes` and
    `play_minutes`, the play job's timeout-minutes and its play step's, are
    named in the rows a timeout may explain (#690): GitHub cancels a job
    past its own without cancelling the run, and fails a step past its own.
    Pure."""
    rows = []
    timeout = f" (its play step at {play_minutes} minutes, its job at {minutes}: timeout-minutes in release-lane.yml)" if minutes else ""

    def fail(rid, why):
        rows.append({"id": rid, "ok": False, "why": [why], "run": run})

    def own(r):
        return {"id": str(r.get("id")), "ok": r.get("ok") is True, "why": [str(w) for w in r.get("why") or []], "run": str(r.get("run") or "")}
    if files.get("move") is None:
        fail("move", "the move job left no results")
    else:
        rows += [own(r) for r in files["move"] if isinstance(r, dict)]
    if not gs:
        fail("groups", "no groups of scenarios to read: none played")
    for g in gs:
        got = files.get(g["id"])
        if got is None:
            # A play job that was skipped is its own failing row below.
            if jobs.get("play") != "skipped":
                fail(g["id"], f"the group {g['id']} left no results: its play job failed before it wrote them, timed out{timeout} or was cancelled")
            continue
        by_id = {}
        for r in got:
            if isinstance(r, dict) and r.get("id") in g["scenarios"]:
                by_id.setdefault(r["id"], own(r))
        for sid in g["scenarios"]:
            if sid in by_id:
                rows.append(by_id[sid])
            else:
                fail(sid, f"no result in the results of its group {g['id']}")
    if files.get("back") is None:
        fail("back", "the back job left no results: the callers may be left at the ref")
    else:
        rows += [own(r) for r in files["back"] if isinstance(r, dict)]
    for name, result in jobs.items():
        if result == "success":
            continue
        if name == "play" and minutes and result == "cancelled":
            fail(name, f"a play job ran past its timeout of {minutes} minutes and was cancelled (timeout-minutes in release-lane.yml)")
        elif name == "play" and play_minutes and result == "failure":
            fail(name, f"a play job ended in failure: a step that broke, or its play step past its timeout of {play_minutes} minutes (timeout-minutes in release-lane.yml)")
        else:
            fail(name, f"the {name} job ended in {result or 'nothing'}")
    return rows


def read_groups(text):
    """The groups the move job printed (`groups`), or [] when they cannot
    be read or a group id is unfit for an artifact name (it names a
    directory)."""
    try:
        gs = json.loads(text or "")
    except ValueError:
        return []
    ok = isinstance(gs, list) and all(isinstance(g, dict) and isinstance(g.get("id"), str) and GROUP_ID.fullmatch(g["id"]) and g["id"] not in NOT_GROUPS
                                     and isinstance(g.get("scenarios"), list) for g in gs)
    return gs if ok else []


def merge_dir(path, gs, jobs, run="", minutes=0, play_minutes=0):
    """`merge` of the artifacts downloaded under `path`, each in its own
    directory (`scenarios-<name>/results.md`)."""
    files = {}
    for name in ["move", "back"] + [g["id"] for g in gs]:
        f = os.path.join(path, f"scenarios-{name}", "results.md")
        files[name] = read_results(f) if os.path.exists(f) else None
    return merge(gs, files, jobs, run, minutes, play_minutes)


DEFAULTS = ("main", "master")


def _lead(node):
    """A string argument's text, or an f-string's text with its values as
    `{}`; None for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
    return None


def default_commits(source):
    """What in `source` writes a file otherwise than `createCommitOnBranch`
    on a branch of its own (#709): any `PUT` to a `contents/` path (the
    contents API's commits are unsigned, and the signed-commits ruleset
    refuses them), and any `branchName` that is not a variable (a literal
    names a fixed branch, the default one among them, which its rulesets
    protect): ["line N: ..."]. Pure."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            texts = [_lead(a) for a in node.args]
            if "PUT" in texts and any(t and "contents/" in t for t in texts):
                out.append(f"line {node.lineno}: a PUT to contents/, not createCommitOnBranch")
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "branchName" and not isinstance(v, ast.Name):
                    out.append(f"line {node.lineno}: a createCommitOnBranch whose branchName is not a branch variable ({ast.unparse(v)})")
    return out


def wrong_writes(calls):
    """The recorded `gh` calls (args, input) that write a file otherwise
    than `createCommitOnBranch` on a named branch other than the default:
    a contents `PUT`, or a commit with no branch or the default one.
    Pure."""
    out = []
    for args, given in calls:
        if tuple(args[:3]) == ("api", "-X", "PUT") and "/contents/" in str(args[3]):
            out.append(args)
        elif tuple(args[:2]) == ("api", "graphql"):
            branch = ((json.loads(given or "{}").get("variables") or {}).get("input") or {}).get("branch") or {}
            if not branch.get("branchName") or branch["branchName"] in DEFAULTS:
                out.append(args)
    return out


def commits(calls):
    """The commits among recorded `gh` calls (args, input): [(repository,
    branch, [paths], {path: text})]. Pure."""
    import base64
    out = []
    for args, given in calls:
        if tuple(args[:2]) == ("api", "graphql") and "createCommitOnBranch" in str(given):
            got = json.loads(given)["variables"]["input"]
            adds = got["fileChanges"]["additions"]
            out.append((got["branch"]["repositoryNameWithOwner"], got["branch"]["branchName"], [a["path"] for a in adds],
                        {a["path"]: base64.b64decode(a["contents"]).decode() for a in adds}))
    return out


def org_key(path, pack):
    """The part of the test repository's core `path` touches
    (scripts/org.py core_key)."""
    sys.path.insert(0, HERE)
    import org
    return org.core_key(path, pack.get("core") or [])


def test_pack(root=ROOT):
    sys.path.insert(0, os.path.join(root, "scripts"))
    import org
    return org.test_pack(root=root)


def schema_passes(root=ROOT):
    """Whether a body passes the issue schema's PRD stage (G1), as the
    triage reads it (scripts/issue-schema.py)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("issue_schema", os.path.join(root, "scripts", "issue-schema.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return lambda body: bool(mod.check(body, "prd")["ok"])


BUG_FORM = os.path.join(".github", "ISSUE_TEMPLATE", "bug_report.yml")


def form_required(form):
    """The labels of the fields an issue form (`form`, read) requires: the
    `### ` sections a body opened from it has. Pure."""
    return [str((f.get("attributes") or {}).get("label")) for f in (form or {}).get("body") or []
            if isinstance(f, dict) and f.get("type") != "markdown" and (f.get("validations") or {}).get("required")]


def missing_fields(body, fields):
    """The `fields` (### headings) `body` leaves missing or empty. Pure."""
    found, on = {}, None
    for line in str(body or "").split("\n"):
        if line.startswith("### "):
            on = line[4:].strip()
            found.setdefault(on, "")
        elif on is not None:
            found[on] += line
    return [f for f in fields if not re.sub(r"<!--.*?-->|\s", "", found.get(f, ""))]


def fixture_problems(conf, issue_check, pull_check, release_check=None, bug_fields=()):
    """What a person's check would find wrong with the scenarios' own
    fixtures (#694, scripts/engine-post.py): every issue body a scenario
    opens or edits to that should await acceptance, as G1 reads it
    (`issue_check(body)`), a decision's too (#713), and every pull request
    it opens, its title, its branch and its `Closes #` as the conventions
    check reads them (`pull_check(title, branch, body, closes)`), a release
    issue's title and label (`release_check(title, labels)`), and (#713) a
    Bug's body that leaves out a field the bug report form requires
    (`bug_fields`, `form_required` of bug_report.yml), which the triage
    asks for (`needs-info`). Pure but for the checks."""
    bodies, out = conf.get("bodies") or {}, []
    known = {b for b in bodies if b not in ("incomplete", "release")}
    for s in conf.get("scenarios") or []:
        sid, opens = s.get("id") or "?", s.get("opens") or {}
        specs = [b.get("issue") or {} for b in s.get("before") or []] + ([opens["issue"]] if "issue" in opens else [])
        if "pull" in opens:
            specs.append((opens["pull"].get("issue") or {"body": "complete-feature"}))
            text = body_of(opens["pull"].get("body"), bodies).replace("{issue}", "1")
            for wrong in pull_check(opens["pull"].get("title", f"test: {sid}"), branch_of(s), marked(text, sid), "1" if "{issue}" in body_of(opens["pull"].get("body"), bodies) else None):
                out.append(f"scenario {sid}: its pull request: {wrong}")
        specs += [{"body": st["edit"]} for st in s.get("steps") or [] if isinstance(st, dict) and "edit" in st]
        for spec in specs:
            name = spec.get("body")
            if name == "release" and release_check:
                for wrong in release_check(spec.get("title", ""), spec.get("labels") or []):
                    out.append(f"scenario {sid}: its release issue: {wrong}")
            if name in known:
                for wrong in issue_check(marked(body_of(name, bodies), sid)):
                    out.append(f"scenario {sid}: its body `{name}`: {wrong}")
            if type_of(spec, conf.get("types") or {}) == "Bug":
                for field in missing_fields(body_of(name, bodies), bug_fields):
                    out.append(f"scenario {sid}: its Bug body `{name}` has no `{field}`, which the bug report form requires")
    return out


def passes_mark(body, root=ROOT):
    """Whether `body` with a scenario's mark first passes the issue schema
    (#694: the mark is one of its markers)."""
    sys.path.insert(0, os.path.join(root, "scripts"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("issue_schema", os.path.join(root, "scripts", "issue-schema.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    good = load_yaml(os.path.join(root, SCENARIOS))["bodies"]["complete-feature"]
    return bool(mod.check(marked(good, "p"), "prd")["ok"]) and bool(body)


def engine_post(root=ROOT):
    import importlib.util
    spec = importlib.util.spec_from_file_location("engine_post", os.path.join(root, "scripts", "engine-post.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_repro(root=ROOT):
    """Whether the test repository has a way to reproduce a `logic` bug
    (#707): its pack's, or repos.yml's for it (scripts/repro-ways.py
    declares), unless repos.yml says `repro: false`."""
    import importlib.util
    sys.path.insert(0, os.path.join(root, "scripts"))
    import org
    spec = importlib.util.spec_from_file_location("repro_ways", os.path.join(root, "scripts", "repro-ways.py"))
    ways = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ways)
    conf = ways.read(os.path.join(root, "repos.yml"))
    name = org.test_repo(org.load(os.path.join(root, "org.yml")))
    return not ways.by_design(conf, name) and bool(ways.declares(conf, name, {}, os.path.join(root, "kinds")))


LANE = os.path.join(".github", "workflows", "release-lane.yml")


def lane_problems(lane):
    """What is wrong with the release lane's jobs (`lane`, release-lane.yml
    read; #707): a `play` job whose `runs-on` can name DX_RUNNER_HEAVY (or
    any self-hosted runner), where the test repository's own jobs run, so
    the play jobs that wait for them hold the runners they need. Pure."""
    play = ((lane or {}).get("jobs") or {}).get("play") or {}
    runs = json.dumps(play.get("runs-on"))
    if "DX_RUNNER_HEAVY" in runs or "self-hosted" in runs:
        return [f"{LANE}: the `play` job runs on {play.get('runs-on')}, where the test repository's own jobs run: "
                "its jobs that wait for them would hold those runners; it runs on ubuntu-latest"]
    return []


def problems(conf, root=ROOT):
    """What `coverage` names: every played pair and transition with no
    scenario, every scenario its setup cannot make hold, what is wrong
    with the groups (`partition`), and with the lane's `play` job
    (`lane_problems`, #707)."""
    pack = test_pack(root)
    scenarios = conf.get("scenarios") or []
    return (coverage(scenarios, played(root, pack) | transitions(root), conf.get("statically") or {})
            + preconditions(scenarios, conf.get("bodies") or {}, pack, dispatchable(root, pack), schema_passes(root), conf.get("types") or {},
                            test_repro(root))
            + lane_problems(load_yaml(os.path.join(root, LANE)))
            + partition(scenarios, groups(scenarios), pack)
            + timing(scenarios)
            + autopilot_problems(scenarios)
            + fixture_problems(conf, engine_post(root).issue, engine_post(root).pull, engine_post(root).release,
                               form_required(load_yaml(os.path.join(root, BUG_FORM)))))


def self_test():
    failed = 0
    NONE = "saw labels none; the bot's newest comment: none"

    def check(name, got, want=True):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    check("job_events: an `if:` that names its events keeps those", job_events("github.event_name == 'issues' || github.event_name == 'schedule'", ["issues", "issue_comment", "schedule"]), ["issues", "schedule"])
    check("job_events: no `if:` is every event", job_events("", ["a", "b"]), ["a", "b"])
    check("job_events: a ref is another way in", job_events("github.event_name == 'schedule' || github.ref_name == x", ["schedule", "workflow_dispatch"]), ["schedule", "workflow_dispatch"])
    check("job_events: `!=` excludes nothing", job_events("github.event.action != 'dequeued'", ["pull_request", "merge_group"]), ["pull_request", "merge_group"])
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, "workflow-templates"))
        os.makedirs(os.path.join(root, "scripts"))
        open(os.path.join(root, "workflow-templates", "x.yml"), "w").write(
            "on:\n  issues:\n  schedule:\njobs:\n  a:\n    if: github.event_name == 'issues'\n    uses: O/.github/.github/workflows/triage.yml@v7\n"
            "  b:\n    uses: O/.github/.github/workflows/claim.yml@v7\n")
        open(os.path.join(root, "scripts", "autopilot.py"), "w").write(
            'BOT_ACTIONS = ("spec", "draft")\nPERSON_DECISIONS = ("accept",)\nBOT_WAITS = ()\nMERGE_HOWS = ("clean",)\nSWEEP_STEPS = ("update",)\n')
        wanted = pairs(root) | transitions(root)
        check("pairs: each job's workflow with the events that reach it", pairs(root), {"triage.yml:issues", "claim.yml:issues", "claim.yml:schedule"})
        check("transitions: from autopilot.py's tuples", transitions(root), {"next_step:spec", "next_step:draft", "next_step:wait:accept", "next_step:merge-main:clean", "sweep_step:update"})
        some = [{"id": "s1", "covers": ["triage.yml:issues", "claim.yml:issues", "claim.yml:schedule", "next_step:spec", "next_step:wait:accept", "next_step:merge-main:clean", "sweep_step:update"], "opens": {"issue": {}}, "expect": {"labels": ["x"]}}]
        got = coverage(some, wanted)
        check("C2: a transition with no scenario fails, named", got, [f"the transition next_step:draft has no scenario in {SCENARIOS}"])
        some[0]["covers"].remove("claim.yml:schedule")
        some[0]["covers"].append("next_step:draft")
        check("C2: a pair with no scenario fails, named", coverage(some, wanted), [f"the pair claim.yml:schedule has no scenario in {SCENARIOS}"])
        some[0]["covers"] += ["claim.yml:schedule", "gone.yml:push"]
        check("C2: a scenario covering what nothing wires is named", coverage(some, wanted), ["scenario s1: covers gone.yml:push, which no caller wires and no transition is"])
        some[0]["covers"].remove("gone.yml:push")
        check("#707: a transition `statically:` holds needs no scenario", coverage([{**some[0], "covers": [c for c in some[0]["covers"] if c != "next_step:draft"]}], wanted, {"next_step:draft": "autopilot.py --test"}), [])
        check("#707: `statically:` names only transitions, each with what holds it, and none a scenario covers too",
              coverage(some, wanted, {"next_step:draft": "autopilot.py --test", "next_step:gone": "x", "claim.yml:schedule": "x", "next_step:spec": " "}),
              ["statically: claim.yml:schedule is no transition of the state machine", "statically: next_step:gone is no transition of the state machine",
               "statically: next_step:spec says no test that holds it", "scenario s1: covers next_step:spec, which `statically:` says no scenario can cause",
               "scenario s1: covers next_step:draft, which `statically:` says no scenario can cause",
               "scenario s1: covers claim.yml:schedule, which `statically:` says no scenario can cause"])
    import importlib.util
    spec = importlib.util.spec_from_file_location("receipts_seal", os.path.join(HERE, "receipts.py"))
    receipts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(receipts)
    check("#715: the seal the scenarios wait for is the mark the board carries", SEAL, receipts.SEAL_MARK)
    sys.path[:] = [p for p in sys.path if p != HERE]
    bot_login("x"), bot_login("y")
    check("#707: bot_login puts the scripts' directory on sys.path once, however often it is called", sys.path.count(HERE), 1)
    real = load_yaml(os.path.join(ROOT, SCENARIOS))
    check("#707: next_step:fix, the review's fix round, is held statically: no scenario claims it by name",
          ("next_step:fix" in (real.get("statically") or {}), [s["id"] for s in real.get("scenarios") or [] if "next_step:fix" in (s.get("covers") or [])]), (True, []))
    check("C2: every pair the test repository plays, and every transition, has its scenario; every scenario can hold", problems(real), [])
    fx = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]
    gs = groups(fx)
    check("C2: groups: every scenario is its own group, named by its id, in the file's order",
          gs, [{"id": i, "scenarios": [i]} for i in "abcd"])
    check("C2: partition: the groups of groups() are a partition", partition(fx, gs), [])
    for how, bad, want in (
            ("a scenario in no group", gs[:3], ["scenario d: in no group"]),
            ("a scenario in two", gs + [{"id": "e", "scenarios": ["b"]}], ["scenario b: in 2 groups (b, e)"]),
            ("a group that plays no scenario", gs + [{"id": "x", "scenarios": ["gone"]}], [f"group x: plays gone, which is no scenario of {SCENARIOS}"])):
        check(f"C2: partition fails for {how}", partition(fx, bad), want)
    check("C2: partition fails for a group id unfit for an artifact name, or the move's or the back's, or used twice",
          [len(partition([{"id": i}], groups([{"id": i}]))) for i in ("Has Space", "move", "back", "ok-1")] + [len(partition([{"id": "a"}], [{"id": "a", "scenarios": ["a"]}, {"id": "a", "scenarios": []}]))],
          [1, 1, 1, 0, 1])
    real_groups = groups(real["scenarios"])
    rpack = test_pack()
    check("C2: the real file: every scenario is its own group, and none says serial",
          ([g["scenarios"] for g in real_groups] == [[s["id"]] for s in real["scenarios"]], [s["id"] for s in real["scenarios"] if "serial" in s]), (True, []))
    check("C2: the real file: no two scenarios write to the same core path of the test repository", partition(real["scenarios"], real_groups, rpack), [])
    check("C2: each scenario writes under its own directory, its fixed change too, and only core-one-at-a-time's is the core (#709)",
          (sorted(core_writes({"id": "x"}, rpack)), {org_key(p, rpack) for p in core_writes({"id": "x"}, rpack)}, {org_key(p, rpack) for p in core_writes({"id": "core-one-at-a-time"}, rpack)}),
          (["scenarios/x/*", "scenarios/x/*.md"], {None}, {""}))
    shared = {"fixed-change": {"file": "scenarios/{n}.md"}, "core": ["scenarios/*"]}
    check("C2: partition fails when two scenarios could write to the same core path (a fixed change outside their own directory)",
          partition([{"id": "a", "expect": {"labels": [CORE_LABEL]}}, {"id": "b", "expect": {"labels": [CORE_LABEL]}}], groups([{"id": "a"}, {"id": "b"}]), shared),
          ["scenario b: writes scenarios/*.md, on the core of the test repository scenario a writes too, so one would wait on the other"])
    per_dir = {"fixed-change": {"file": "scenarios/{scenario}/{n}.md"}, "core": ["scenarios/*/**"]}
    check("#709 C1: core_problems names a scenario that writes under the core but expects no wait on it, and partition with it",
          (core_problems([{"id": "a", "expect": {}}, {"id": "w", "expect": {"labels": [CORE_LABEL]}}], per_dir), partition([{"id": "a"}], groups([{"id": "a"}]), per_dir),
           core_problems(real["scenarios"], rpack)),
          (["scenario a: writes scenarios/a/*, under the test repository's core (scenarios/*/**), but expects no wait on it, so its issue could wait on another's change"],
           ["scenario a: writes scenarios/a/*, under the test repository's core (scenarios/*/**), but expects no wait on it, so its issue could wait on another's change"], []))
    sys.path.insert(0, HERE)
    import autopilot as _ap
    fixed709 = rpack["fixed-change"]["file"]
    issues709, n709 = [], 100
    for s in real["scenarios"]:
        for _ in (s.get("before") or []) + [s.get("opens")]:
            n709 += 1
            issues709.append((s["id"], n709, fixed709.replace("{scenario}", s["id"]).replace("{n}", str(n709)).replace("{id}", "C1")))
    busy709 = {sid for sid, n, path in issues709 if _ap.core_busy([path], rpack["core"], [{"number": m, "files": [q]} for _, m, q in issues709 if m != n], mine=n)}
    check("#709 C1: from the real pack, with every scenario's fixed change open at once, only core-one-at-a-time can wait on the core", busy709, {"core-one-at-a-time"})
    plan_real = scenario_plan(real["scenarios"])
    check("C3: the real plan: no fixed wait, every wait an `until`, polling every 50 seconds, each limit 15 minutes or less",
          (timing(real["scenarios"]), {p["poll"] for p in plan_real}, max(p["minutes"] for p in plan_real) <= 15, len(plan_real) == len(real["scenarios"]),
           [st for s in real["scenarios"] for st in s.get("steps") or [] if "wait" in st]), ([], {50}, True, True, []))
    check("#726: the real plan, every scenario polling at once, stays under the test identity's rate limit; a plan of many scenarios is refused",
          (poll_budget(real["scenarios"]) < RATE_LIMIT, poll_budget([{"opens": {"issue": {}}}, {"opens": {"pull": {}}}]),
           timing([{"id": f"s{i}", "opens": {"pull": {}}} for i in range(30)])),
          (True, 360, ["the plan's 30 scenarios poll GitHub 6480 times an hour, every 50 seconds, past the test identity's 5000"]))
    check("C3: timing names a fixed wait, an empty `until` and a limit past 15 minutes",
          timing([{"id": "w", "steps": [{"wait": 60}, {"until": {"of": "before"}}], "minutes": 16}]),
          ["scenario w: waits a fixed 60 seconds; wait `until` the state it waits for, polled every 50 seconds", "scenario w: an `until` with no expectation",
           "scenario w: its limit is 16 minutes, past 15"])
    check("C3: the play step's 20 minutes stay above every scenario's limit", MAX_LIMIT < 20, True)
    check("C3: hopeless: merged when it should not, closed unmerged, a check that ended otherwise, an absent label once settled",
          (hopeless({"merged": False}, {"merged": True}), hopeless({"merged": True}, {"merged": False, "state": "CLOSED"}), hopeless({"merged": True}, {"state": "OPEN"}),
           hopeless({"check": {"c": "success"}}, {"checks": {"c": "failure"}}), hopeless({"check": {"c": "success"}}, {"checks": {"c": ""}}),
           hopeless({"absent": ["incomplete"]}, {"labels": ["incomplete"]}), hopeless({"absent": ["incomplete"]}, {"labels": ["incomplete"]}, True)),
          (["it merged"], ["it closed unmerged"], [], ["check c ended failure, not success"], [], [], ["label incomplete stays, with nothing left running"]))
    rollup709 = {"conventions / Docs (links and names)": "failure", "conventions / Conventions (branch, title, commits)": "success", "review / Claude review": ""}
    check("#709 C4: `conventions` names the reusable workflow's check, by its caller's job or its own name, never its sibling's",
          (check_named("conventions", rollup709), check_named("Conventions", {"Conventions (branch, title, commits)": "success"}), check_named("review", rollup709),
           check_named("conventions", {"conventions": "failure", "conventions / Conventions (x)": "success"}), check_named("docs", {"conventions / Docs (links and names)": "failure"}),
           check_named("conventions", {"other / Lint": "success"})), ("success", "success", "", "failure", "failure", None))
    check("#709 C4: holds sees the conventions check report under its real name; a missing one names the checks it saw",
          (holds({"check": {"conventions": "success"}}, {"checks": rollup709}), holds({"check": {"conventions": "success"}}, {"checks": {"other / Lint": "success"}})),
          ([], ["check conventions is missing, not success (its checks: other / Lint)", "saw labels none; the bot's newest comment: none"]))
    check("#709 C4: a fork's run held for approval (action_required) is named by hopeless at once",
          (hopeless({"check": {"conventions": "success"}, "merged": False}, {"checks": {}, "held": ["https://github.com/o/t/actions/runs/5"]}), hopeless({"merged": False}, {"held": ["u"]})),
          (["the fork's run waits for approval to run workflows from forks (https://github.com/o/t/actions/runs/5)"], []))

    def held_fake(*a, input=None):
        if a[:3] == ("pr", "view", "3"):
            return json.dumps({"headRefOid": "abc", "statusCheckRollup": [{"name": "conventions / Conventions (branch, title, commits)", "conclusion": None}]})
        if a[:2] == ("run", "list") and "--commit" in a:
            return json.dumps([{"url": "https://github.com/o/t/actions/runs/5", "status": "completed", "conclusion": "action_required"}] if a[a.index("--commit") + 1] == "abc" else [])
        return "[]"
    def lane709(*a, input=None):
        """The test repository as the candidate meets it: every check under
        its real name, the reusable workflow's after its caller's job."""
        if a[:2] == ("issue", "create"):
            return "https://github.com/o/t/issues/11\n"
        if a[:2] == ("pr", "create"):
            return "https://github.com/o/t/pull/12\n"
        if a[:3] == ("pr", "view", "12"):
            return json.dumps({"state": "OPEN", "headRefOid": "h", "body": "Closes #11", "statusCheckRollup": [
                {"name": "conventions / Conventions (branch, title, commits)", "conclusion": "SUCCESS"}, {"name": "conventions / Docs (links and names)", "conclusion": "SUCCESS"}]})
        return "me\n" if a[-1:] == (".login",) else "h\n" if a[-1:] in ((".sha",), (".object.sha",)) else "[]"
    by709 = {s["id"]: s for s in real["scenarios"]}
    got709 = [play(by709[i], "o/t", "v7-next", real["bodies"], lane709, lambda s: None, 1, fork=lane709, types=real["types"]) for i in ("fork-without-secrets", "review-changes-asked")]
    check("#709 C5: the real fork-without-secrets and review-changes-asked pass once the conventions check reports under its real name",
          [(r["id"], r["ok"], r["why"]) for r in got709], [("fork-without-secrets", True, []), ("review-changes-asked", True, [])])
    seen709 = observe("o/t", "pr", "3", held_fake)
    check("#709 C4: observe records the run on the pull request's head GitHub holds for approval", (seen709["held"], seen709["checks"]),
          (["https://github.com/o/t/actions/runs/5"], {"conventions / Conventions (branch, title, commits)": ""}))

    def polled(views, runs=lambda n: [{"url": "u", "status": "in_progress"}]):
        """A test repository whose issue 9 shows `views[i]` on its i-th
        view (the last one after), and the sleeps play takes."""
        st = {"views": 0, "sleeps": [], "calls": []}

        def fake(*a, input=None):
            st["calls"].append(a)
            if a[:2] == ("issue", "create"):
                return "https://github.com/o/t/issues/9\n"
            if a[:2] == ("issue", "view"):
                st["views"] += 1
                return json.dumps(views[min(st["views"], len(views)) - 1])
            if a[:2] == ("run", "list"):
                return json.dumps(runs(st["views"]))
            return "[]"
        return st, fake
    st, fake = polled([{"labels": []}, {"labels": []}, {"labels": [{"name": "claimed"}]}, {"labels": [{"name": "done"}]}])
    got = play({"id": "u", "opens": {"issue": {"title": "t"}}, "steps": [{"until": {"labels": ["claimed"]}}, {"comment": "/unclaim"}], "expect": {"labels": ["done"]}},
               "o/t", "v7-next", {}, fake, st["sleeps"].append, 10)
    comment = st["calls"].index(next(c for c in st["calls"] if c[:2] == ("issue", "comment")))
    check("C3: an `until` polls every 50 seconds until its state holds, then the next step goes on",
          (got["ok"], st["sleeps"], comment > [i for i, c in enumerate(st["calls"]) if c[:2] == ("issue", "view")][2]), (True, [50, 50], True))
    st, fake = polled([{"labels": []}])
    got = play({"id": "u", "opens": {"issue": {"title": "t"}}, "steps": [{"until": {"labels": ["claimed"]}}, {"comment": "x"}], "expect": {}}, "o/t", "v7-next", {}, fake, st["sleeps"].append, 1)
    check("C3: an `until` that never holds fails at the scenario's limit, named, and takes no further step",
          (got["ok"], got["why"], len(st["sleeps"]), any(c[:2] == ("issue", "comment") for c in st["calls"])), (False, ['until {"labels": ["claimed"]}: no label claimed', f'until {{"labels": ["claimed"]}}: {NONE}'], 2, False))
    st, fake = polled([{"labels": [{"name": "incomplete"}]}], runs=lambda n: [{"url": "u", "status": "completed"}])
    got = play({"id": "u", "opens": {"issue": {"title": "t"}}, "expect": {"labels": ["awaiting-acceptance"], "absent": ["incomplete"]}}, "o/t", "v7-next", {}, fake, st["sleeps"].append, 15)
    check("C3: a scenario stops as soon as its expectation can no longer hold, not at its limit",
          (got["ok"], st["sleeps"], got["why"][-1]), (False, [50], "it can no longer hold: label incomplete stays, with nothing left running"))
    st, fake = polled([{"labels": []}])
    got = play({"id": "u", "opens": {"issue": {"title": "t"}}, "minutes": 2, "expect": {"labels": ["x"]}}, "o/t", "v7-next", {}, fake, st["sleeps"].append, 20)
    check("C3: a scenario's own limit bounds its polls (2 minutes: 3 polls of 50 seconds)", (got["ok"], len(st["sleeps"]), set(st["sleeps"])), (False, 3, {50}))
    st, fake = polled([{"labels": []}])
    got = play({"id": "u", "opens": {"issue": {"title": "t"}}, "steps": [{"wait": 300}], "expect": {}}, "o/t", "v7-next", {}, fake, st["sleeps"].append, 1)
    check("C3: a fixed wait is never slept", (got["ok"], st["sleeps"]), (False, []))
    forked, fork_in = [], []
    got = play({"id": "f", "opens": {"pull": {"title": "docs: x", "body": "b", "fork": True}}, "expect": {}}, "o/t", "v7-next", {"b": "x"},
               lambda *a, input=None: forked.append(("test",) + a) or ("https://github.com/o/t/pull/3\n" if a[:2] == ("pr", "create") else "{}" if a[:2] == ("pr", "view") else "[]"),
               lambda s: None, 1, fork=lambda *a, input=None: forked.append(("fork",) + a) or fork_in.append((a, input)) or ("me\n" if a[-1] == ".login" else "s\n"))
    check("C9: a scenario from a fork forks and writes its fork with the fork token, and opens its pull request with the test identity's",
          (got["ok"], [c[0] for c in forked if c[1:3] == ("repo", "fork")], [c[0] for c in forked if c[1:3] == ("pr", "create")],
           [c[0] for c in forked if c[1:3] == ("api", "graphql")], [c[:3] for c in commits(fork_in)]), (True, ["fork"], ["test"], ["fork"], [("me/t", "docs/scenario-f", ["scenarios/f/pull.md"])]))
    forked = []
    got = play({"id": "f", "opens": {"pull": {"title": "docs: x", "body": "b", "fork": True}}, "expect": {}}, "o/t", "v7-next", {"b": "x"},
               lambda *a, input=None: forked.append(a) or "[]", lambda s: None, 1, fork=False)
    check("C9: with no fork token, the fork's scenario fails at once naming the permission it lacks, and never forks",
          (got["ok"], got["why"], [c for c in forked if c[:2] == ("repo", "fork")]), (False, [FORK_NEEDS], []))
    lane = load_yaml(os.path.join(ROOT, ".github", "workflows", "release-lane.yml"))["jobs"]
    pstep = next(st for st in lane["play"]["steps"] if st.get("id") == "play")
    check("C9: the limits the 20-minute run relies on: every scenario at once, each under the play step's 20 minutes, polled every 50 seconds",
          ("max-parallel" in (lane["play"].get("strategy") or {}), max(limit(s) for s in real["scenarios"]) < pstep["timeout-minutes"] <= 20, POLL,
           pstep["env"].get(FORK_SECRET)), (False, True, 50, "${{ secrets.DX_TEST_FORK_TOKEN }}"))
    titles = []

    def ordered(*a, input=None):
        if a[:2] == ("issue", "create"):
            titles.append(a[a.index("--title") + 1])
            return "https://github.com/o/t/issues/9\n"
        return "{}" if a[:2] == ("issue", "view") else "[]"
    conf3 = {"scenarios": [{"id": "a", "opens": {"issue": {"title": "a"}}, "expect": {}}, {"id": "b", "opens": {"issue": {"title": "b"}}, "expect": {}}]}
    rows = play_group(conf3, "b", "o/t", "v7-next", ordered, lambda s: None, 1)
    check("C2: play_group plays its group's one scenario, and no other", ([r["id"] for r in rows], titles), (["b"], ["b [b]"]))
    check("C2: play_group on no group is one failing row", [(r["id"], r["ok"]) for r in play_group(conf3, "gone", "o/t", "v7-next", ordered, lambda s: None, 1)], [("gone", False)])
    rpack = test_pack()
    check("#563: the test repository's callers are shipped ones", all(os.path.exists(os.path.join(ROOT, "workflow-templates", c)) for c in rpack["callers"]) and rpack["callers"] != [], True)
    check("#563: a pair no caller of the test repository wires is not played, nor a scheduled one: caller-contract.py holds them",
          ({"plugin-checks-wp.yml:pull_request", "issue-triage.yml:schedule"} & played(ROOT, rpack), "issue-triage.yml:issues" in played(ROOT, rpack)), (set(), True))
    check("#563: a dispatch of a workflow the test repository has not is named",
          preconditions([{"id": "d", "steps": [{"dispatch": "nightly-review.yml"}], "opens": {}, "expect": {}}], {}, rpack, dispatchable(ROOT, rpack)),
          [f"scenario d: dispatches nightly-review.yml, which the test repository has not, or not with workflow_dispatch (its pack's `callers`: {', '.join(sorted(dispatchable(ROOT, rpack))) or 'none dispatchable'})"])
    check("#563: a caller without workflow_dispatch is not dispatchable", "issues.yml" in dispatchable(ROOT, rpack), False)
    passes = schema_passes()
    check("#563: an issue that should await acceptance with a body the schema refuses is named",
          preconditions([{"id": "b", "opens": {"issue": {"body": "x"}}, "expect": {"labels": ["awaiting-acceptance"]}}], {"x": real["bodies"]["complete-feature"].replace("Normal", "Low")}, rpack, (), passes),
          ["scenario b: expects its issue to await acceptance, but its body does not pass the issue schema"])
    pack = {"fixed-change": {"file": "scenarios/{n}-{id}.md"}, "core": ["scenarios/*"]}
    pr_fixed = {"id": "p", "opens": {"pull": {"body": "pull"}}, "expect": {"pull": {"closes": True}}}
    core_alone = {"id": "c", "opens": {"issue": {"labels": ["accepted"]}}, "expect": {"labels": [CORE_LABEL]}}
    check("preconditions: a pull request that closes a fixed number never holds; one that closes the issue it opens does",
          (preconditions([pr_fixed], {"pull": "Closes #1"}, pack),
           preconditions([dict(pr_fixed, opens={"pull": {"body": "pull", "issue": {"body": "f", "labels": ["accepted"]}}})], {"pull": "## What changes\n\nX.\n\n## Why\n\nCloses #{issue}"}, pack)),
          (["scenario p: expects its pull request to close an issue, but its body names no `{issue}` it opens"], []))
    old_pull = {"id": "q", "opens": {"pull": {"title": "feat: x", "body": "pull"}}, "expect": {"pull": {"closes": True}}}
    check("#698 preconditions: a pull request that closes an issue it does not open accepted, a body without the template's sections, a title its issue's Type refuses",
          preconditions([old_pull], {"pull": "A change.\n\nCloses #{issue}"}, pack, types={"complete-feature": "Task"}),
          ["scenario q: its pull request closes an issue it does not open accepted (its `issue:` with `labels: [accepted]`), so the accepted-issue gate fails it",
           "scenario q: its pull request's body has no `What changes` section, which the conventions check asks of a person's",
           "scenario q: its pull request's body has no `Why` section, which the conventions check asks of a person's",
           "scenario q: its pull request is titled for a Feature, but the issue it closes is a Task, which the accepted-issue gate refuses"])
    check("#698 preconditions: a docs pull request closes any Type; a fix needs a Bug; a breaking change a Feature",
          (needed_type("docs: x"), needed_type("ci: x"), needed_type("fix(a): x"), needed_type("refactor!: x"), needed_type("feat: x"), needed_type("x")),
          (None, None, "Bug", "Feature", "Feature", None))
    check("#698 preconditions: an issue with no Type (as `gh issue create` opens it) makes the autopilot's draft a chore, not the feat its `expect` names",
          (preconditions([{"id": "d", "opens": {"issue": {"body": "f"}}, "expect": {"pull": {"branch": "^feat/[0-9]+-"}}}], {}, pack, types={}),
           preconditions([{"id": "d", "opens": {"issue": {"body": "f"}}, "expect": {"pull": {"branch": "^feat/[0-9]+-"}}}], {}, pack, types={"f": "Feature"})),
          (["scenario d: expects the autopilot's branch ^feat/[0-9]+-, but its issue's Type (none) makes it chore/"], []))
    check("#698 empty_sections: read as conventions.sh reads them, a comment is empty",
          (empty_sections("## 📝 What changes\n\nA.\n\n## 💡 Why\n\n<!-- say why -->\n"), empty_sections(real["bodies"]["pull"])), (["Why"], []))
    check("preconditions: a wait on the core needs an accepted issue before it, and a fixed change on the core",
          (len(preconditions([core_alone], {}, pack)), len(preconditions([dict(core_alone, before=[{"issue": {"labels": ["accepted"]}}])], {}, dict(pack, core=["scripts/*"]))),
           preconditions([dict(core_alone, before=[{"issue": {"labels": ["accepted"]}}])], {}, pack)), (1, 1, []))
    check("holds: a pull scenario's closes is the issue it opened, never its own number",
          (holds({"pull": {"closes": True}}, {"number": "12", "closes": "11", "pull": {"body": "Closes #11"}}),
           holds({"pull": {"closes": True}}, {"number": "12", "closes": "1", "pull": {"body": "Closes #11"}})), ([], ["the pull request does not say Closes #1", NONE]))
    # #707: what v7.14.0's candidate failed on, each refused from now on.
    lane_doc = load_yaml(os.path.join(ROOT, LANE))
    heavy = {"jobs": {"play": {"runs-on": "${{ vars.DX_RUNNER_HEAVY != '' && fromJSON(vars.DX_RUNNER_HEAVY) || 'ubuntu-latest' }}"}}}
    check("#707: the play job never runs on DX_RUNNER_HEAVY (nor self-hosted), where the test repository's jobs it waits for run",
          (lane_problems(lane_doc), lane_doc["jobs"]["play"]["runs-on"], len(lane_problems(heavy)), len(lane_problems({"jobs": {"play": {"runs-on": ["self-hosted", "linux"]}}}))),
          ([], "ubuntu-latest", 1, 1))
    bugs = [s for s in real["scenarios"] if s["id"] in ("bug-reproduced", "bug-not-reproduced")]
    check("#707: a bug scenario's verdict is refused in a test repository with no way to reproduce it, and holds with one",
          ([p.split(":")[0] for p in preconditions(bugs, real["bodies"], rpack, repro=False)], preconditions(bugs, real["bodies"], rpack, repro=True), test_repro()),
          (["scenario bug-reproduced", "scenario bug-not-reproduced"], [], True))
    check("#707: a confirmed bug's issue expected to have a pull request that closes it is refused: the lane's fix closes its own issue",
          preconditions([{"id": "b", "opens": {"issue": {"body": "bug"}}, "expect": {"labels": ["bug:confirmed"], "pull": {"closes": True}}}], {}, rpack, repro=True),
          ["scenario b: expects bug:confirmed and a pull request that closes its issue, but the reproduction's fix closes the issue the bugfix-reproduced lane opens, never the report"])
    check("#707: the bug that reproduces lands the greeting its fixed test reads, under its own directory, and its body names it",
          ([b for b in bugs[0].get("before") or [] if "lands" in b], "scenarios/bug-reproduced/greeting.md" in real["bodies"][bugs[0]["opens"]["issue"]["body"]],
           [b for b in bugs[1].get("before") or [] if "lands" in b]), ([{"lands": "greeting", "says": "helo"}], True, []))
    check("#707 saw: a failing row names its labels and the bot's newest comment's first line that is no marker, table-safe",
          (saw({"labels": ["b", "a"], "said": ["old", "<!-- dx-board -->\n\nThe seal | was `refused`.\nmore"]}), saw({})),
          ("saw labels a, b; the bot's newest comment: The seal ' was 'refused'.", NONE))
    bot = str(sys.modules["org"].APP)
    viewed = lambda *a, input=None: json.dumps({"labels": [], "comments": [{"author": {"login": bot}, "body": "<!-- m -->\nMine."}, {"author": {"login": "someone"}, "body": "Theirs."},
                                                                           {"author": {"login": f"app/{bot}"}, "body": "Mine too."}]}) if a[:2] == ("issue", "view") else "[]"
    check("#707 observe: the bot's comments are its own, as either API names the App, never a person's",
          observe("o/t", "issue", "3", viewed)["said"], ["<!-- m -->\nMine.", "Mine too."])
    covered = {c for s in real.get("scenarios") or [] for c in s.get("covers") or []}
    check("#585: a caller that does not grant what the engine asks has its scenario", any(s["id"] == "caller-permission-585" for s in real["scenarios"]), True)
    check("the pairs are read from the real callers", {"issue-triage.yml:issues", "claude-review.yml:pull_request", "autopilot.yml:pull_request"} <= covered, True)
    seen = {"number": "4", "labels": ["autopilot", "awaiting-acceptance"], "comments": ["<!-- dx-x -->"], "pull": {"body": "Closes #4", "branch": "feat/4-x", "title": "feat: x"}, "checks": {"g": "success"}, "merged": False}
    check("holds: what holds is nothing", holds({"labels": ["autopilot"], "comments": ["<!-- dx-x -->"], "pull": {"closes": True, "branch": "^feat/4-"}, "check": {"g": "success"}, "merged": False}, seen), [])
    check("holds: what does not is named, and what it saw (#707)", holds({"labels": ["accepted"], "absent": ["autopilot"], "merged": True}, seen),
          ["no label accepted", "label autopilot still there", "merged is False", "saw labels autopilot, awaiting-acceptance; the bot's newest comment: none"])
    calls = []

    def fake(*args, input=None):
        calls.append(args)
        if args[:2] == ("issue", "create"):
            return "https://github.com/o/t/issues/9\n"
        if args[:2] == ("issue", "view"):
            return json.dumps({"labels": [{"name": "awaiting-acceptance"}], "comments": []})
        if args[:2] == ("run", "list"):
            return json.dumps([{"url": "https://github.com/o/t/actions/runs/1"}])
        return "[]"
    scen = {"scenarios": [{"id": "a", "covers": [], "opens": {"issue": {"title": "t", "body": "b"}}, "steps": [{"label": "x"}], "expect": {"labels": ["awaiting-acceptance"]}},
                          {"id": "b", "covers": [], "opens": {"issue": {"title": "t"}}, "expect": {"labels": ["accepted"]}}], "bodies": {"b": "body"}}
    res = run_all(scen, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=3, central="O/.github")
    check("run: a scenario whose expect holds passes, one whose does not fails, named", [(r["id"], r["ok"], r["why"]) for r in res], [("a", True, []), ("b", False, ["no label accepted", "saw labels awaiting-acceptance; the bot's newest comment: none"])])
    check("run: its issues are closed and locked after it", sum(1 for c in calls if c[:2] in (("issue", "close"), ("issue", "lock"))), 4)
    pcalls_ = []

    def prfake(*args, input=None):
        pcalls_.append((args, input))
        if args[:2] == ("issue", "create"):
            return "https://github.com/o/t/issues/11\n"
        if args[:2] == ("pr", "create"):
            return "https://github.com/o/t/pull/12\n"
        if args[:2] == ("pr", "view"):
            return json.dumps({"body": [i for a, i in pcalls_ if a[:2] == ("pr", "create")][0]})
        if args[-1:] == (".sha",):
            return "s\n"
        return "[]"
    got = play({"id": "p", "opens": {"pull": {"title": "feat: x", "body": "pull"}}, "expect": {"pull": {"closes": True}}}, "o/t", "v7-next", {"pull": "Closes #{issue}", "complete-feature": "f"}, prfake, lambda s: None, 1)
    check("run: a pull scenario opens the issue its pull request closes, and passes on it",
          (got["ok"], [a[:2] for a, _ in pcalls_ if a[0] in ("issue", "pr") and a[1] == "create"][:1], ("issue", "close", "11", "--repo", "o/t") in [a for a, _ in pcalls_]), (True, [("issue", "create")], True))
    check("#694: every body a scenario opens carries its mark first, and still passes the issue schema",
          ([i.startswith(scenario_mark("p") + "\n") for a, i in pcalls_ if a[1:2] == ("create",)], passes_mark("f")), ([True, True], True))

    def leftover(state):
        """A test repository where an earlier run left `scenario/p` and one
        open issue with p's mark (and one with another's): creating a ref
        that exists is the 422 GitHub answers."""
        def fake(*a, input=None):
            state["calls"].append(a)
            if a[:3] == ("api", "-X", "DELETE"):
                ref = a[3].split("/git/refs/heads/", 1)[1]
                if ref not in state["branches"]:
                    raise GhError("gh api: HTTP 404: Not Found", 1, "", "HTTP 404")
                state["branches"].discard(ref)
                return ""
            if a[:2] == ("api", "repos/o/t/git/refs"):
                ref = a[3].split("refs/heads/", 1)[1]
                if ref in state["branches"]:
                    raise GhError("gh api: HTTP 422: Reference already exists", 1, "", "HTTP 422")
                state["branches"].add(ref)
                return "{}"
            if a[0] == "api" and "/git/ref/heads/" in a[1]:
                if a[1].split("/git/ref/heads/", 1)[1] not in state["branches"]:
                    raise GhError("gh api: HTTP 404: Not Found", 1, "", "HTTP 404")
                return "refs/heads/x\n"
            if a[:2] == ("issue", "view"):
                return "{}"
            if a[:2] == ("issue", "list"):
                return json.dumps([{"number": 3, "body": scenario_mark("p") + "\nold"}, {"number": 4, "body": scenario_mark("p-2") + "\nother"}])
            if a[:2] == ("issue", "create"):
                return "https://github.com/o/t/issues/11\n"
            if a[:2] == ("pr", "create"):
                return "https://github.com/o/t/pull/12\n"
            if a[:2] == ("pr", "view"):
                return json.dumps({"body": "Closes #11"})
            if a[-1:] == (".sha",):
                return "s\n"
            return "[]"
        return fake
    st694 = {"calls": [], "branches": {"scenario/p"}}
    got = play({"id": "p", "opens": {"pull": {"title": "feat: x", "body": "pull"}}, "expect": {"pull": {"closes": True}}}, "o/t", "v7-next",
               {"pull": "Closes #{issue}", "complete-feature": "f"}, leftover(st694), lambda s: None, 1)
    calls694 = st694["calls"]
    delete = ("api", "-X", "DELETE", "repos/o/t/git/refs/heads/scenario/p")
    create = next(c for c in calls694 if c[:2] == ("api", "repos/o/t/git/refs"))
    check("C1: play deletes a leftover scenario branch before it makes it, and no 422 happens",
          (calls694.index(delete) < calls694.index(create), got["ok"], got["why"], "scenario/p" in st694["branches"]), (True, True, [], False))
    check("C1: play closes the open issue an earlier run of it left (its mark), before it opens anything, and no other scenario's",
          (calls694.index(("issue", "close", "3", "--repo", "o/t")) < calls694.index(next(c for c in calls694 if c[:2] == ("issue", "create"))),
           ("issue", "close", "4", "--repo", "o/t") in calls694), (True, False))
    check("C1: after it plays, its branch is deleted again and its leftovers looked for again",
          (calls694[-1][:2], sum(1 for c in calls694 if c == delete) >= 2), (("pr", "list"), True))
    lcalls = []

    def lanefake(*a, input=None):
        lcalls.append(a)
        if a[:2] == ("issue", "list"):
            return json.dumps([{"number": 20, "title": "The bug reproduced from #5"}, {"number": 21, "title": "The bug reproduced from #6"},
                               {"number": 22, "title": "fix: the bug reproduced from #5"}])
        if a[:3] == ("issue", "view", "5"):
            return json.dumps({"body": scenario_mark("bug-reproduced") + "\nthe report"})
        if a[:3] == ("issue", "view", "6"):
            return json.dumps({"body": scenario_mark("bug-reproduced-2") + "\nanother's"})
        return ""
    lane_leftovers("o/t", scenario_mark("bug-reproduced"), lanefake)
    check("#707: clear closes the open lane issue a confirmed bug of the scenario opened (its report's mark), and no other",
          [c[2] for c in lcalls if c[:2] == ("issue", "close")], ["20"])
    check("#707: the lane issues are listed by their label, open, never searched",
          [c for c in lcalls if c[:2] == ("issue", "list")][0][3:9], ("o/t", "--state", "open", "--label", "lane:bugfix-reproduced", "--json"))

    def pushed(merges=True, pull=True):
        """A test repository whose issue 9 is closed by the autopilot's pull
        request 12 (head `feat/9-x`, unless `pull` is False), and whose
        scenario pull request 14 to main merges (or never, `merges`)."""
        st = {"calls": [], "io": []}

        def fake(*a, input=None):
            st["calls"].append(a)
            st["io"].append((a, input))
            if a[:2] == ("issue", "create"):
                return f"https://github.com/o/t/issues/{9 if sum(1 for c in st['calls'] if c[:2] == ('issue', 'create')) == 1 else 13}\n"
            if a[:2] == ("issue", "view"):
                return json.dumps({"labels": [], "closedByPullRequestsReferences": [{"number": 12, "repository": {"nameWithOwner": "o/t"}}] if pull else []})
            if a[:3] == ("pr", "view", "12"):
                return json.dumps({"number": 12, "body": "Closes #9", "headRefName": "feat/9-x", "title": "feat: x"})
            if a[:3] == ("pr", "view", "14"):
                return json.dumps({"mergedAt": "2026-11-08T00:00:00Z" if merges else None, "state": "OPEN", "body": "Closes #13"})
            if a[:2] == ("pr", "create"):
                return "https://github.com/o/t/pull/14\n"
            if a[0] == "api" and "/contents/" in a[1] and "?ref=" in a[1]:
                raise GhError("gh api: HTTP 404: Not Found", 1, "", "HTTP 404")
            if a[-1:] == (".sha",):
                return "s\n"
            return "[]"
        return st, fake
    puts = lambda st: [(c[1], c[2][0]) for c in commits(st["io"])]
    st, fake = pushed()
    got = play({"id": "p", "opens": {"issue": {"title": "feat: x", "body": "f"}}, "steps": [{"push": "conflict"}], "expect": {}}, "o/t", "v7-next",
               {"f": "f", "task": "t", "pull": "## Why\n\nCloses #{issue}"}, fake, lambda s: None, 1)
    check("#698: a push lands on the head branch of the pull request it observes, then the same file lands on main through a scenario pull request that merged",
          (got["ok"], got["why"], puts(st)),
          (True, [], [("feat/9-x", "scenarios/p/conflict.md"), ("docs/scenario-p-conflict", "scenarios/p/conflict.md")]))
    created = [c for c in st["calls"] if c[:2] == ("issue", "create")][1]
    claim = st["calls"].index(("issue", "comment", "13", "--repo", "o/t", "--body", "/claim"))
    check("#698: the pull request to main closes a Docs issue it claims before it accepts it, and lands from a docs branch",
          (created[created.index("--type") + 1], "--label" in created, claim < st["calls"].index(("issue", "edit", "13", "--repo", "o/t", "--add-label", "accepted")),
           [c[c.index("--head") + 1] for c in st["calls"] if c[:2] == ("pr", "create")]), ("Docs", False, True, ["docs/scenario-p-conflict"]))
    st, fake = pushed()
    got = play({"id": "p", "opens": {"issue": {"title": "feat: x", "body": "f"}}, "steps": [{"push": "behind"}], "expect": {}}, "o/t", "v7-next",
               {"f": "f", "task": "t", "pull": "Closes #{issue}"}, fake, lambda s: None, 1)
    check("#698: `behind` writes nothing on the head, only its own file on main", (got["ok"], puts(st)), (True, [("docs/scenario-p-behind", "scenarios/p/behind.md")]))
    st, fake = pushed(merges=False)
    got = play({"id": "p", "opens": {"issue": {"title": "feat: x", "body": "f"}}, "steps": [{"push": "behind"}], "expect": {}}, "o/t", "v7-next",
               {"f": "f", "task": "t", "pull": "Closes #{issue}"}, fake, lambda s: None, 1)
    check("#698: a pull request to main that does not merge fails the scenario, named", (got["ok"], got["why"][-2]),
          (False, "push behind: its pull request to main https://github.com/o/t/pull/14: merged is False"))
    # #707: a `before` that lands a file of the scenario's own on main.
    st, fake = pushed()
    lander = {"id": "bug-x", "before": [{"lands": "greeting", "says": "helo"}], "opens": {"issue": {"title": "fix: x", "body": "f"}}, "expect": {}}
    got = play(lander, "o/t", "v7-next", {"f": "f", "task": "t", "pull": "## Why\n\nCloses #{issue}"}, fake, lambda s: None, 1)
    landed = commits(st["io"])
    check("#707: a `before` lands its file on main, with what it says, through a docs pull request that merged, before the scenario's issue opens",
          (got["ok"], puts(st), landed[0][3].get("scenarios/bug-x/greeting.md") if landed else None,
           st["calls"].index(next(c for c in st["calls"] if c[:2] == ("pr", "create"))) < [i for i, c in enumerate(st["calls"]) if c[:2] == ("issue", "create")][1],
           sum(1 for c in st["calls"] if c == ("api", "-X", "DELETE", "repos/o/t/git/refs/heads/docs/scenario-bug-x-greeting")) >= 2),
          (True, [("docs/scenario-bug-x-greeting", "scenarios/bug-x/greeting.md")], "helo\n", True, True))
    st, fake = pushed()

    def already(*a, input=None):
        if a[0] == "api" and a[1] == "repos/o/t/contents/scenarios/bug-x/greeting.md?ref=main":
            return json.dumps({"content": __import__("base64").b64encode(b"helo\n").decode()})
        return fake(*a, input=input)
    got = play(lander, "o/t", "v7-next", {"f": "f"}, already, lambda s: None, 1)
    check("#707: a `before` whose file main says already lands nothing", (got["ok"], puts(st), [c for c in st["calls"] if c[:2] == ("pr", "create")]), (True, [], []))
    st, fake = pushed(merges=False)
    got = play(lander, "o/t", "v7-next", {"f": "f", "task": "t", "pull": "Closes #{issue}"}, fake, lambda s: None, 1)
    check("#707: a `before` whose pull request never merges fails the scenario, named, and opens no issue of its own",
          (got["ok"], got["why"][0], sum(1 for c in st["calls"] if c[:2] == ("issue", "create"))),
          (False, "before: lands greeting: its pull request to main https://github.com/o/t/pull/14: merged is False", 1))
    st, fake = pushed(pull=False)
    got = play({"id": "p", "opens": {"issue": {"title": "feat: x", "body": "f"}}, "steps": [{"push": "conflict"}], "expect": {}}, "o/t", "v7-next", {"f": "f"}, fake, lambda s: None, 1)
    check("#698: a push with no pull request to push to fails, named, and writes nothing", (got["ok"], got["why"], puts(st)), (False, ["push conflict: no pull request closes #9 to push to"], []))
    st, fake = pushed()
    got = play({"id": "p", "opens": {"pull": {"title": "feat: x", "body": "pull", "issue": {"body": "f"}}}, "steps": [{"push": "secret"}], "expect": {}}, "o/t", "v7-next",
               {"f": "f", "pull": "Closes #{issue}"}, fake, lambda s: None, 1)
    check("#698: a pull scenario's push lands on its own pull request's head", puts(st)[-1], ("feat/scenario-p", "scenarios/p/secret.md"))

    def searchless(fail=0, retry="retry-after: 30"):
        """Issue 9, closed by pull request 12, whose view fails `fail`
        times with a rate limit first; any search raises."""
        st = {"calls": [], "sleeps": [], "fails": fail}

        def fake(*a, input=None):
            st["calls"].append(a)
            if "--search" in a and a[:2] == ("pr", "list"):
                raise GhError("gh pr list --repo: HTTP 403: API rate limit exceeded", 1, "", "HTTP 403")
            if a[:2] == ("issue", "create"):
                return "https://github.com/o/t/issues/9\n"
            if a[:2] == ("issue", "view"):
                if st["fails"]:
                    st["fails"] -= 1
                    raise GhError("gh issue view 9: HTTP 403: API rate limit exceeded for user", 1, "", f"HTTP 403: API rate limit exceeded\n{retry}")
                return json.dumps({"labels": [], "closedByPullRequestsReferences": [{"number": 11}, {"number": 12}, {"number": 30, "url": "https://github.com/x/y/pull/30"}]})
            if a[:3] == ("pr", "view", "12"):
                return json.dumps({"number": 12, "body": "Closes #9", "headRefName": "feat/9-x", "title": "feat: x"})
            return "[]"
        return st, fake
    st, fake = searchless()
    got = play({"id": "s", "opens": {"issue": {"title": "feat: x", "body": "f"}}, "expect": {"pull": {"closes": True, "branch": "^feat/"}}}, "o/t", "v7-next", {"f": "f"}, fake, st["sleeps"].append, 1)
    check("#698: observe finds the issue's pull request from its references (the newest of its repository), with no search per poll",
          (got["ok"], [c for c in st["calls"] if c[:2] == ("pr", "list") and "Closes" in " ".join(map(str, c))], ("pr", "view", "12", "--repo", "o/t", "--json", "number,body,headRefName,title") in st["calls"]),
          (True, [], True))
    st, fake = searchless(fail=2)
    got = play({"id": "s", "opens": {"issue": {"title": "feat: x", "body": "f"}}, "expect": {"pull": {"closes": True}}}, "o/t", "v7-next", {"f": "f"}, fake, st["sleeps"].append, 1)
    check("#698: a rate-limited `gh` is retried after GitHub's retry-after, then the scenario holds", (got["ok"], st["sleeps"]), (True, [30, 30]))
    st, fake = searchless(fail=99, retry="")
    got = play({"id": "s", "minutes": 2, "opens": {"issue": {"title": "feat: x", "body": "f"}}, "expect": {"pull": {"closes": True}}}, "o/t", "v7-next", {"f": "f"}, fake, st["sleeps"].append, 20)
    check("#698: one rate-limited until the scenario's time runs out fails then, naming it, backing off within its limit",
          (got["ok"], got["why"][0].startswith("gh issue view 9 rate limited"), sum(st["sleeps"]), st["sleeps"][:3]), (False, True, 120, [50, 70]))
    st = {"n": 0}

    def broken(*a, input=None):
        if a[:2] == ("issue", "view"):
            raise GhError("gh issue view 9: HTTP 404: Not Found", 1, "", "HTTP 404")
        return "https://github.com/o/t/issues/9\n" if a[:2] == ("issue", "create") else "[]"
    got = play({"id": "s", "opens": {"issue": {"title": "t"}}, "expect": {"labels": ["x"]}}, "o/t", "v7-next", {}, broken, lambda s: st.__setitem__("n", st["n"] + 1), 1)
    check("#698: a `gh` error that is not transient still fails at once", (got["ok"], st["n"]), (False, 0))
    check("#698 backoff: retry-after, then the reset, then POLL doubled up to 120",
          (backoff(GhError("x", stderr="Retry-After: 7"), 0), backoff(GhError("x", stderr="x-ratelimit-reset: 1060"), 0, now=1000), backoff(GhError("x"), 0), backoff(GhError("x"), 5)),
          (7, 60, 50, 120))
    check("#698 transient: a rate limit, a secondary one, a 5xx; not a 404",
          [transient(GhError(m)) for m in ("gh api: HTTP 429", "You have exceeded a secondary rate limit", "gh api: HTTP 502: Bad Gateway", "gh api: HTTP 404: Not Found")] + [transient(RuntimeError("rate limit"))],
          [True, True, True, False, False])
    opened = []
    open_issue("o/t", {"title": "t", "body": "f", "labels": ["accepted"]}, {"f": "x"}, "d", lambda *a, input=None: opened.append(a) or "https://github.com/o/t/issues/5\n", "s", {"f": "Feature"})
    check("#698 open_issue: the Type its body's form gives, its labels with it when it posts no comment first",
          (opened[0][opened[0].index("--type") + 1], opened[0][-2:], len(opened)), ("Feature", ("--label", "accepted"), 1))
    check("#694: a scenario's branch is its title's type, so the conventions check takes it; one with no type is test/",
          (branch_of({"id": "p", "opens": {"pull": {"title": "docs(x): a"}}}), branch_of({"id": "q", "opens": {"issue": {"title": "something"}}})), ("docs/scenario-p", "test/scenario-q"))
    first = []
    play({"id": "c", "before": [{"issue": {"title": "first", "labels": ["accepted"]}}], "opens": {"issue": {"title": "second"}}, "expect": {}},
         "o/t", "v7-next", {}, lambda *a, input=None: first.append(a) or ("https://github.com/o/t/issues/9\n" if a[:2] == ("issue", "create") else "{}" if a[:2] == ("issue", "view") else "[]"), lambda s: None, 1)
    check("run: `before` opens its issue first and closes it only after", ([a[5] for a in first if a[:2] == ("issue", "create")], first.index(("issue", "close", "9", "--repo", "o/t")) > 2), (["first [c]", "second [c]"], True))
    check("#709 C2: a `before` that lands a file opens the Docs issue of its pull request to main, never an empty one",
          issue_text(*opened_issues(lander, {})[0][:1], {"task": "t"}, opened_issues(lander, {})[0][1], "bug-x")[0],
          issue_text(land_issue("bug-x", "greeting"), {"task": "t"}, "bug-x", "bug-x")[0])
    texts709 = [(s["id"],) + issue_text(spec, real["bodies"], default, s["id"]) for s in real["scenarios"] for spec, default in opened_issues(s, real["bodies"])]
    check("#709 C2: every issue a scenario opens names its scenario in its title (but the Release form's, the version alone) and in its body",
          ([sid for sid, title, body in texts709 if not (title.endswith(f" [{sid}]") or FIXED_TITLE.match(title)) or f"\nScenario: {sid}.\n" not in body + "\n"],
           [title for sid, title, _ in texts709 if FIXED_TITLE.match(title)], len(texts709) > len(real["scenarios"])), ([], ["Release 0.0.1"], True))
    check("#709 C2: no two scenarios open an issue with the same title or the same body",
          [(a[0], b[0]) for i, a in enumerate(texts709) for b in texts709[i + 1:] if a[0] != b[0] and (a[1] == b[1] or a[2] == b[2])], [])
    check("#709 C2: the scenarios that shared a title and body before, now differ in both",
          [(t, b) for sid, t, b in texts709 if sid == "issue-complete"] != [(t, b) for sid, t, b in texts709 if sid == "accepted-spec"], True)
    check("#709 C2: the id is a suffix, so the title's type still reads, and the autopilot's title from it still matches its scenario's pattern",
          (needed_type(issue_text({"title": "feat: a greeting"}, {}, "x", "accepted-spec")[0]), bool(re.search(r"^feat(\(.+\))?: ", issue_text({"title": "feat: x"}, {}, "x", "s")[0]))), ("Feature", True))
    made709 = []
    open_issue("o/t", {"title": "feat: x", "body": "f"}, {"f": "text"}, "d", lambda *a, input=None: made709.append((a, input)) or "https://github.com/o/t/issues/5\n", "s")
    check("#709 C2: open_issue opens what issue_text writes", (made709[0][0][made709[0][0].index("--title") + 1], made709[0][1]), ("feat: x [s]", f"{scenario_mark('s')}\nScenario: s.\ntext"))
    check("#709 C2: in a body with sections, the scenario's line opens the first one, where the issue schema takes it",
          marked("### Problem\n\nNone.\n", "s"), f"{scenario_mark('s')}\n### Problem\n\nScenario: s.\n\nNone.\n")
    import base64
    caller = "jobs:\n  t:\n    uses: O/.github/.github/workflows/issue-triage.yml@abc123 # v7\n"
    check("at_ref: a pinned call moves to the ref tried", at_ref(caller, "O/.github", "v7-next"), "jobs:\n  t:\n    uses: O/.github/.github/workflows/issue-triage.yml@v7-next\n")
    check("at_ref: a call already at the ref keeps its pin's comment", at_ref(caller.replace("abc123", "v7-next"), "O/.github", "v7-next"), caller.replace("abc123", "v7-next"))

    def repo_fake(merges=True, pending=1, tamper=None):
        """A test repository with issues.yml at `@abc123 # v7`, whose pull
        requests' required check is pending for `pending` polls then
        passes, and which merge (their branch's callers reach main) on the
        view after the lane queues them, or close unmerged (`merges` False),
        or never merge (None). `tamper(st, branch)`, when given, changes the
        branch after the lane wrote it, before the pull request opens."""
        st = {"main": {"issues.yml": caller}, "branches": {}, "prs": {}, "polls": {}, "queued": set(), "calls": [], "io": [], "files": None}

        def at(number, side):
            pr = st["prs"][number]
            return pr["base"] if side == "base" else st["branches"][pr["head"]]

        def fake(*args, input=None):
            st["calls"].append(args)
            st["io"].append((args, input))
            path = str(args[-1])
            if path == "repos/o/t/contents/.github/workflows":
                return json.dumps([{"name": n} for n in st["main"]])
            if args[0] == "api" and "/contents/.github/workflows/" in path and args[1] != "-X":
                name, _, ref = path.split("/contents/.github/workflows/", 1)[1].partition("?ref=")
                files = at(ref.split("-")[1], ref.split("-")[0]) if ref else st["main"]
                if name not in files:
                    raise GhError("gh api: HTTP 404: Not Found", 1, "", "HTTP 404")
                return json.dumps({"content": base64.b64encode(files[name].encode()).decode(), "sha": "s1"})
            if args[-2:] == ("--jq", ".default_branch"):
                return "main\n"
            if args[-2:] == ("--jq", ".object.sha"):
                return "h1\n"
            if args[:3] == ("api", "repos/o/t/git/refs", "-f"):
                st["branches"][args[3].split("refs/heads/", 1)[1]] = dict(st["main"])
            for _, branch, _, files in commits([(args, input)]):
                for name, text in files.items():
                    st["branches"][branch][name.rsplit("/", 1)[1]] = text
            if args[:2] == ("pr", "create"):
                n = str(20 + len(st["prs"]))
                head = args[args.index("--head") + 1]
                if tamper:
                    tamper(st, head)
                st["prs"][n] = {"head": head, "base": dict(st["main"])}
                return f"https://github.com/o/t/pull/{n}\n"
            m = re.fullmatch(r"repos/o/t/pulls/(\d+)(/files)?", path)
            if args[0] == "api" and m:
                n = m.group(1)
                if not m.group(2):
                    return json.dumps({"head": {"sha": f"head-{n}"}, "base": {"sha": f"base-{n}"}})
                if st["files"] is not None:
                    return json.dumps([st["files"]])
                base, head = at(n, "base"), at(n, "head")
                return json.dumps([[{"filename": f".github/workflows/{k}", "status": "added" if k not in base else "removed" if k not in head else "modified"}
                                    for k in sorted(set(base) | set(head)) if base.get(k) != head.get(k)]])
            if args[:2] == ("pr", "checks"):
                st["polls"][args[2]] = st["polls"].get(args[2], 0) + 1
                return json.dumps([{"name": "gate", "bucket": "pending" if st["polls"][args[2]] <= pending else "pass"}])
            if args[:2] == ("pr", "merge"):
                st["queued"].add(args[2])
            if args[:2] == ("pr", "view") and args[2] in st["prs"]:
                n = args[2]
                if merges is False:
                    return json.dumps({"state": "CLOSED"})
                if merges and n in st["queued"]:
                    st["main"] = dict(st["branches"][st["prs"][n]["head"]])
                    st["calls"].append(("merged", n))
                    return json.dumps({"mergedAt": "2026-11-02T10:00:00Z", "state": "MERGED"})
                done = st["polls"].get(n, 0) >= pending
                return json.dumps({"state": "OPEN", "headRefOid": f"head-{n}",
                                   "statusCheckRollup": [{"name": "gate", "status": "COMPLETED" if done else "IN_PROGRESS", "conclusion": "SUCCESS" if done else ""}]})
            if args[:2] == ("issue", "create"):
                return "https://github.com/o/t/issues/9\n"
            if args[:2] == ("issue", "view"):
                return json.dumps({"labels": [{"name": "awaiting-acceptance"}], "comments": []})
            return "[]"
        return st, fake
    one = {"scenarios": [{"id": "a", "covers": [], "opens": {"issue": {"title": "t"}}, "expect": {"labels": ["awaiting-acceptance"]}}]}
    st, fake = repo_fake()
    got = run_all(one, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=3, central="O/.github")
    calls = st["calls"]
    writes = commits(st["io"])
    check("C1: the callers move on ci/callers-v7-next, created from main's head",
          ("api", "repos/o/t/git/refs", "-f", "ref=refs/heads/ci/callers-v7-next", "-f", "sha=h1") in calls, True)
    check("C1: @v7-next is written there, not on main, in one commit made on the branch's head",
          (writes[0][:3], "issue-triage.yml@v7-next\n" in writes[0][3][".github/workflows/issues.yml"],
           json.loads(next(i for a, i in st["io"] if a[:2] == ("api", "graphql")))["variables"]["input"]["expectedHeadOid"]),
          (("o/t", "ci/callers-v7-next", [".github/workflows/issues.yml"]), True, "h1"))
    queue = ("pr", "merge", "20", "--repo", "o/t", "--squash", "--match-head-commit", "head-20")
    check("#623 C1: a pull request is opened, and the lane enables no auto-merge",
          (calls.index(next(c for c in calls if c[:2] == ("pr", "create"))) < calls.index(queue), [c for c in calls if "--auto" in c]), (True, []))
    checks = [i for i, c in enumerate(calls) if c[:3] == ("pr", "checks", "20")]
    check("#623 C1: it waits for the required checks, then queues it at the head they passed on",
          (len(checks) >= 2, all("--required" in calls[i] for i in checks), checks[-1] < calls.index(queue), sum(1 for c in calls if c[:3] == ("pr", "merge", "20"))), (True, True, True, 1))
    check("C1: the first scenario plays only after the pull request merged",
          (calls.index(("merged", "20")) < calls.index(next(c for c in calls if c[:2] == ("issue", "create"))), [r["id"] for r in got], got[0]["ok"]), (True, ["a"], True))
    check("C1: the callers are put back, pin and comment, through a second merged pull request",
          (st["main"]["issues.yml"], ("merged", "21") in calls, writes[1][1] == "ci/callers-v7-next-back"), (caller, True, True))
    check("#623 C1: on the way back too, it waits for the checks and queues it itself, with no auto-merge",
          (calls.index(next(c for c in calls if c[:3] == ("pr", "checks", "21"))) < calls.index(("pr", "merge", "21", "--repo", "o/t", "--squash", "--match-head-commit", "head-21"))
           < calls.index(("merged", "21")), [c for c in calls if "--auto" in c]), (True, []))
    st, fake = repo_fake()
    st["main"]["issues.yml"] = at_ref(caller, "O/.github", "v7-next")
    run_all(one, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=3, central="O/.github")
    check("C1: callers already at the ref open no pull request", any(c[:2] == ("pr", "create") for c in st["calls"]), False)
    moved_to = at_ref(caller, "O/.github", "v7-next")
    check("#623 C1: only_ref passes a change of the engine's ref and its pin's comment, both ways",
          (only_ref(caller, moved_to, "O/.github"), only_ref(moved_to, caller, "O/.github"), only_ref(caller, caller, "O/.github")), (None, None, None))
    check("#623 C2: only_ref names the line that differs, another `uses:` or any other",
          (only_ref(caller, caller.replace("issue-triage.yml@abc123", "claim.yml@v7-next"), "O/.github"),
           only_ref(caller, caller.replace("O/.github/", "E/.github/").replace("@abc123 # v7", "@v7-next"), "O/.github"),
           only_ref(caller, moved_to.replace("  t:", "  x:"), "O/.github"),
           only_ref(caller, moved_to + "  run: curl x | sh\n", "O/.github")),
          ("line 3: 'uses: O/.github/.github/workflows/claim.yml@v7-next # v7'", "line 3: 'uses: E/.github/.github/workflows/issue-triage.yml@v7-next'",
           "line 2: 'x:'", "line 4: 'run: curl x | sh'"))

    def another_line(st, branch):
        st["branches"][branch]["issues.yml"] += "permissions: write-all\n"

    def another_file(st, branch):
        st["branches"][branch]["evil.yml"] = "on: push\n"

    def another_caller(st, branch):
        st["branches"][branch]["other.yml"] = "x"
        st["main"]["other.yml"] = "y"

    def renamed(st, branch):
        st["files"] = [{"filename": ".github/workflows/issues.yml", "status": "renamed", "previous_filename": ".github/workflows/old.yml"}]
    for how, tamper in (("another line", another_line), ("an added file", another_file), ("a file the lane did not write", another_caller), ("a renamed file", renamed)):
        st, fake = repo_fake(tamper=tamper)
        got = run_all(one, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=3, central="O/.github")
        check(f"#623 C2: a pull request with {how} under .github/workflows is never merged, plays no scenario, is closed, and is one failing callers row naming it",
              (any(c[:2] in (("pr", "merge"), ("issue", "create")) or c[0] == "merged" for c in st["calls"]), ("pr", "close", "20", "--repo", "o/t", "--delete-branch") in st["calls"],
               [(r["id"], r["ok"]) for r in got], "https://github.com/o/t/pull/20" in got[0]["why"][0], st["main"]["issues.yml"]),
              (False, True, [("callers", False)], True, caller))
    st, fake = repo_fake(tamper=another_line)
    got = run_all(one, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=3, central="O/.github")
    check("#623 C2: the failing row names the file and the line that differ",
          got[0]["why"], ["the callers did not reach v7-next: the pull request https://github.com/o/t/pull/20 that moves them changes more than the engine's ref, "
                          "so the lane does not merge it: .github/workflows/issues.yml line 4: 'permissions: write-all'"])
    st, fake = repo_fake()
    failing = lambda *a, input=None: json.dumps([{"name": "gate", "bucket": "fail"}]) if a[:2] == ("pr", "checks") else fake(*a, input=input)
    got = run_all(one, "o/t", "v7-next", run=failing, sleep=lambda s: None, minutes=3, central="O/.github")
    check("#623 C1: a required check that fails is never queued, plays no scenario, and names the pull request and the check",
          (any(c[:2] in (("pr", "merge"), ("issue", "create")) for c in st["calls"]), [(r["id"], r["ok"]) for r in got],
           "https://github.com/o/t/pull/20" in got[0]["why"][0] and "gate" in got[0]["why"][0], ("pr", "close", "20", "--repo", "o/t", "--delete-branch") in st["calls"]),
          (False, [("callers", False)], True, True))

    def pending8(*a, input=None):
        raise GhError("gh pr checks 20: exit 8", 8, json.dumps([{"name": "gate", "bucket": "pending"}]), "")

    def none_yet(*a, input=None):
        raise GhError("gh pr checks 20", 1, "", "no required checks reported on the 'ci/callers-v7-next' branch")
    check("#623 C1: `gh pr checks` exiting 8 while a check is pending, or 1 before any is reported, is read, not raised",
          (required_checks("o/t", "20", pending8), required_checks("o/t", "20", none_yet)), ([{"name": "gate", "bucket": "pending"}], []))
    for how, merges in (("closes unmerged", False), ("never merges", None)):
        st, fake = repo_fake(merges)
        got = run_all(one, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=3, central="O/.github")
        check(f"C1: a pull request that {how} plays no scenario and gives one failing callers row",
              (any(c[:2] == ("issue", "create") for c in st["calls"]), [(r["id"], r["ok"]) for r in got], st["main"]["issues.yml"]), (False, [("callers", False)], caller))
    st, fake = repo_fake()
    moved = []
    got = run_all(one, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=3, central="O/.github", moved_out=moved)
    check("#622: with moved_out the scenarios play at the ref and the callers are left there for put_back",
          ([r["id"] for r in got], [m["name"] for m in moved], ("merged", "21") in st["calls"], "issue-triage.yml@v7-next\n" in st["main"]["issues.yml"]), (["a"], ["issues.yml"], False, True))
    fresh = []
    check("#622: put_back, with the runner given it (a token minted after the scenarios), puts them back",
          (put_back("o/t", "v7-next", moved, lambda *a, input=None: fresh.append(a) or fake(*a, input=input), "O/.github", lambda s: None, 3), st["main"]["issues.yml"], any(c[:2] == ("pr", "create") for c in fresh)), ([], caller, True))
    check("#623 C1: put_back queues its pull request itself, at its head, once its checks passed",
          ([c for c in fresh if c[:2] == ("pr", "merge")], [c for c in fresh if "--auto" in c], any(c[:2] == ("pr", "checks") for c in fresh)),
          ([("pr", "merge", "21", "--repo", "o/t", "--squash", "--match-head-commit", "head-21")], [], True))
    check("#622: put_back with nothing moved does nothing", put_back("o/t", "v7-next", [], lambda *a, input=None: 1 / 0), [])
    st, fake = repo_fake()
    moved = []
    run_all(one, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=3, central="O/.github", moved_out=moved)

    def expired(*a, input=None):
        raise RuntimeError("gh api repos/o/t/contents/.github/workflows: HTTP 401: Bad credentials")
    check("#622: callers that do not come back are one failing callers row",
          [(r["id"], r["ok"]) for r in put_back("o/t", "v7-next", moved, expired, "O/.github", lambda s: None, 1)], [("callers", False)])
    import contextlib
    import io
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "results.md")
        with contextlib.redirect_stdout(io.StringIO()):
            write_results([{"id": "a", "ok": True, "why": [], "run": ""}], out)
        check("#622: back reads the run's results and adds its row to them",
              read_results(out) + [{"id": "callers", "ok": False, "why": ["x"], "run": ""}], [{"id": "a", "ok": True, "why": [], "run": ""}, {"id": "callers", "ok": False, "why": ["x"], "run": ""}])
        check("#622: no results file reads as none", read_results(os.path.join(d, "none.md")), [])
        nested = os.path.join(d, "back", "results.md")
        with contextlib.redirect_stdout(io.StringIO()):
            write_results([{"id": "callers", "ok": True, "why": [], "run": ""}], nested)
        check("#693: results are written into a directory nothing made yet",
              read_results(nested), [{"id": "callers", "ok": True, "why": [], "run": ""}])
        path = os.path.join(d, "moved.json")
        st, fake = repo_fake()
        seen = []

        def plays(*a, input=None):
            if a[:2] == ("issue", "create") and not seen:
                seen.append(read_moved(path, "v7-next"))
            return fake(*a, input=input)
        run_all(one, "o/t", "v7-next", run=plays, sleep=lambda s: None, minutes=3, central="O/.github", moved_out=[], record=lambda m: write_moved(m, path))
        check("#622: what moved is written before the first scenario plays",
              [([m["name"] for m in got], rows) for got, rows in seen], [(["issues.yml"], [])])
        st, fake = repo_fake(False)
        run_all(one, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=3, central="O/.github", moved_out=[], record=lambda m: write_moved(m, path))
        check("#622: a pointing that fails cleanly writes nothing moved", read_moved(path, "v7-next"), ([], []))
        check("#622: a missing moved file is one failing callers row",
              [(r["id"], r["ok"]) for r in read_moved(os.path.join(d, "gone.json"), "v7-next")[1]], [("callers", False)])
        for bad in ("{not json", '{"a": 1}', '[{"name": "x"}]'):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(bad)
            check(f"#622: an unreadable moved file ({bad}) is one failing callers row",
                  [(r["id"], r["ok"]) for r in read_moved(path, "v7-next")[1]], [("callers", False)])
    own = open(os.path.abspath(__file__), encoding="utf-8").read()
    check("#709 C3: no PUT to contents/ is left in this script, and every createCommitOnBranch names its branch from a variable", default_commits(own), [])
    check("#709 C3: a PUT to contents/, and a commit on a fixed branch, are named",
          default_commits('run("api", "-X", "PUT", f"repos/{r}/contents/x", "-f", f"branch={b}")\nq = {"branchName": "main"}\nq = {"branchName": branch}\n'),
          ["line 1: a PUT to contents/, not createCommitOnBranch", "line 2: a createCommitOnBranch whose branchName is not a branch variable ('main')"])
    st, fake = repo_fake()
    recorded = []
    run_all({"scenarios": [{"id": "p", "opens": {"pull": {"title": "t", "body": "x"}}, "steps": [{"push": "more"}], "expect": {}}]}, "o/t", "v7-next",
            run=lambda *a, input=None: recorded.append((a, input)) or fake(*a, input=input), sleep=lambda s: None, minutes=3, central="O/.github")
    check("#709 C3: every write run_all, play and point_callers make is a createCommitOnBranch on a named branch, never main, and none a contents PUT",
          ([c[1] for c in commits(recorded)], wrong_writes(recorded), [a for a, _ in recorded if a[:3] == ("api", "-X", "PUT")],
           len(commits(recorded)) == sum(1 for a, _ in recorded if a[:2] == ("api", "graphql"))),
          (["ci/callers-v7-next", "test/scenario-p", "test/scenario-p", "ci/callers-v7-next-back"], [], [], True))
    heads, tries = iter(["h1", "h2", "h3"]), []

    def racing(*a, input=None):
        if a[:2] == ("api", "graphql"):
            tries.append(json.loads(input)["variables"]["input"]["expectedHeadOid"])
            if len(tries) == 1:
                raise RuntimeError('gh api graphql: Expected branch to point to "h1" but it did not. Pull and try again.')
            return "{}"
        return next(heads) + "\n"
    commit_files("o/t", "feat/9-x", {"a.md": "a"}, "test: a", racing)
    check("#709: a branch that moved between reading its head and committing is read again, and the commit made on its new head", tries, ["h1", "h2"])

    def broken(*a, input=None):
        if a[:2] == ("api", "graphql"):
            tries.append(input)
            raise RuntimeError("gh api graphql: HTTP 422: something else")
        return "h1\n"
    tries = []
    try:
        commit_files("o/t", "feat/9-x", {"a.md": "a"}, "test: a", broken)
        raised = None
    except RuntimeError as e:
        raised = str(e)
    check("#709: any other failure of the commit is raised at once, not retried", (raised, len(tries)), ("gh api graphql: HTTP 422: something else", 1))
    check("#709 C3: a recorded contents PUT, a commit on main and one with no branch are named",
          len(wrong_writes([(("api", "-X", "PUT", "repos/o/t/contents/x", "-f", "branch=b"), None),
                            (("api", "graphql", "--input", "-"), json.dumps({"variables": {"input": {"branch": dict(branchName="main")}}})),
                            (("api", "graphql", "--input", "-"), json.dumps({"variables": {"input": {}}}))])), 3)
    check("callers_gh: the ambient token when DX_CALLERS_TOKEN is not set", callers_gh() is gh if not os.environ.get("DX_CALLERS_TOKEN") else True, True)
    check("run: the table names each scenario, its result and its run", table(res).splitlines()[2], "| `a` | pass | https://github.com/o/t/actions/runs/1 |")
    import importlib.util
    spec = importlib.util.spec_from_file_location("release_lane", os.path.join(HERE, "release-lane.py"))
    lane = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lane)
    plan = {"release": True, "version": "v7.15.0", "major": "v7"}
    lane_run = "https://github.com/O/.github/actions/runs/1"
    mgs = [{"id": "serial", "scenarios": ["a", "c"]}, {"id": "b", "scenarios": ["b"]}]
    passed = lambda *ids: [{"id": i, "ok": True, "why": [], "run": f"r-{i}"} for i in ids]
    done = {"move": "success", "play": "success", "back": "success"}
    with tempfile.TemporaryDirectory() as d:
        def lay(files):
            """The artifacts as act downloads them, under a fresh directory."""
            root = tempfile.mkdtemp(dir=d)
            for name, rows in files.items():
                if rows is not None:
                    os.makedirs(os.path.join(root, f"scenarios-{name}"))
                    with contextlib.redirect_stdout(io.StringIO()):
                        write_results(rows, os.path.join(root, f"scenarios-{name}", "results.md"))
            return root
        every = {"move": [], "serial": passed("a", "c"), "b": passed("b"), "back": []}
        whole = merge_dir(lay(every), mgs, done, lane_run)
        check("C3: every group passing is one passing table, every scenario's row in the groups' order",
              ([(r["id"], r["ok"]) for r in whole], lane.decide(plan, whole)["do"]), ([("a", True), ("c", True), ("b", True)], "release"))
        for how, files, jobs, want in (
                ("a group's missing file (its job timed out)", dict(every, b=None), dict(done, play="failure"), {"b", "play"}),
                ("a play job that ended in failure with all rows passing", every, dict(done, play="failure"), {"play"}),
                ("a missing scenario row", dict(every, serial=passed("a")), done, {"c"}),
                ("a row from another group in place of its own", dict(every, b=passed("a")), done, {"b"}),
                ("a back job that left nothing", dict(every, back=None), dict(done, back="cancelled"), {"back"}),
                ("a move that failed, and no group played", {"move": [{"id": "callers", "ok": False, "why": ["x"], "run": ""}]}, dict(done, play="skipped", back="success"), {"callers", "play", "back"})):
            rows = merge_dir(lay(files), mgs, jobs, lane_run)
            bad = {r["id"] for r in rows if not r["ok"]}
            check(f"C3: merge gives a failing row for {how}, with the lane's run, and decide releases nothing",
                  (bad, all(r["run"] == lane_run for r in rows if not r["ok"] and r["id"] != "callers"), lane.decide(plan, rows)["do"]), (want, True, "bug"))
        mixed = merge(mgs, {"move": [], "serial": passed("a", "c") + [{"id": "b", "ok": False, "why": ["planted"], "run": ""}], "b": passed("b"), "back": []}, done)
        check("C3: merge ignores a row a group wrote for another group's scenario", [(r["id"], r["ok"]) for r in mixed], [("a", True), ("c", True), ("b", True)])
        check("C3: no groups to read is a failing row; a group id unfit for a directory reads as none",
              ([r["id"] for r in merge([], {"move": [], "back": []}, done) if not r["ok"]], read_groups('[{"id": "../x", "scenarios": []}]'), read_groups("not json"), read_groups(json.dumps(mgs))),
              (["groups"], [], [], mgs))
        # #690: a play job past its timeout-minutes ends cancelled, a play
        # step past its own fails it: the rows name the minutes.
        why = lambda rows: {r["id"]: r["why"][0] for r in rows if not r["ok"]}
        timed = why(merge(mgs, dict(every, b=None), dict(done, play="cancelled"), lane_run, minutes=300, play_minutes=240))
        check("merge: a cancelled play job ran past its timeout, with its minutes",
              ("timeout of 300 minutes and was cancelled" in timed["play"], "240 minutes" in timed["b"] and "300" in timed["b"]), (True, True))
        check("merge: a failed play job may be its play step's timeout",
              "its play step past its timeout of 240 minutes" in why(merge(mgs, every, dict(done, play="failure"), lane_run, minutes=300, play_minutes=240))["play"], True)
        check("merge: with no minutes, a job's row says how it ended", why(merge(mgs, every, dict(done, back="cancelled"), lane_run))["back"], "the back job ended in cancelled")
        out = os.path.join(d, "merged.md")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = main(["merge", "--dir", lay(dict(every, b=None)), "--groups", json.dumps(mgs), "--job", "move=success", "--job", "play=failure", "--job", "back=success", "--run", lane_run, "--out", out])
        check("C3: merge's command writes the table release-lane.py reads, and exits 1 on a failing row",
              (rc, [r["id"] for r in read_results(out) if not r["ok"]], lane.decide(plan, read_results(out))["scenario"]), (1, ["b", "play"], "b"))
    # #713: the autopilot's result read once it is there.
    def sealing():
        """A test repository whose triage answers issue 9 on its second view
        (`awaiting-acceptance`), whose acceptance after that seals it a view
        later and has the autopilot label it two views after the seal, and
        an acceptance before the triage never seals (the autopilot calls it
        unsealed); a `/claim` before the acceptance claims it, after it is
        refused."""
        st = {"labels": [], "comments": [], "views": 0, "calls": [], "at": None}

        def fake(*a, input=None):
            st["calls"].append(a)
            if a[:2] == ("issue", "create"):
                st["labels"] += [a[i + 1] for i, x in enumerate(a) if x == "--label"]
                if "accepted" in st["labels"]:
                    st["at"] = "early"
                return "https://github.com/o/t/issues/9\n"
            if a[:2] == ("issue", "edit") and "--add-label" in a:
                label = a[a.index("--add-label") + 1]
                st["labels"].append(label)
                if label == "accepted":
                    st["at"] = st["views"] if "awaiting-acceptance" in st["labels"] else "early"
                return ""
            if a[:2] == ("issue", "comment"):
                text = a[a.index("--body") + 1]
                if text == "/claim":
                    if "accepted" in st["labels"]:
                        st["comments"].append("the claim is refused: the autopilot is already on it")
                    else:
                        st["labels"].append("claimed")
                elif text == "/unclaim" and "claimed" in st["labels"]:
                    st["labels"].remove("claimed")
                return ""
            if a[:2] == ("issue", "view"):
                st["views"] += 1
                if st["views"] == 2 and "awaiting-acceptance" not in st["labels"]:
                    st["labels"].append("awaiting-acceptance")
                    if st["at"] == "early":
                        st["comments"].append("The autopilot did not run: the issue's PRD is not the one sealed when it was accepted (unsealed).")
                if isinstance(st["at"], int) and st["views"] == st["at"] + 1:
                    st["comments"].append(f"{SEAL}\nsealed")
                if isinstance(st["at"], int) and st["views"] == st["at"] + 3:
                    st["labels"].append("autopilot")
                return json.dumps({"labels": [{"name": l} for l in st["labels"]], "comments": [{"body": c, "author": {"login": "dilux-bot"}} for c in st["comments"]]})
            return "[]"
        return st, fake
    by713 = {s["id"]: s for s in real["scenarios"]}
    st, fake = sealing()
    got = play(by713["accepted-spec"], "o/t", "v7-next", real["bodies"], fake, lambda s: None, 15, types=real["types"])
    check("#713 C2: the real accepted-spec, against a repository that seals only after the triage, passes once the autopilot labels it",
          (got["ok"], got["why"], st["at"] >= 2, "autopilot" in st["labels"]), (True, [], True, True))
    st, fake = sealing()
    early = dict(by713["accepted-spec"], steps=[{"label": "accepted"}], minutes=1)
    got = play(early, "o/t", "v7-next", real["bodies"], fake, lambda s: None, 1, types=real["types"])
    check("#713 C2: accepted before the triage, as it was, it is never sealed and fails", (got["ok"], st["at"], any(SEAL in c for c in st["comments"])), (False, "early", False))
    check("#713 C2: and autopilot_problems names it, as every scenario that reads the autopilot's result too early",
          [p.split(": ", 1)[1].split(" (")[0].split(",")[0] for p in autopilot_problems([
              early,
              dict(by713["spec-to-draft"], opens={"issue": dict(by713["spec-to-draft"]["opens"]["issue"], labels=["accepted"])}),
              dict(by713["ready-behind-main"], steps=[{"until": {"labels": ["awaiting-acceptance"]}}, {"label": "accepted"}, {"until": {"pull": {"closes": True}}}]),
              dict(by713["core-one-at-a-time"], before=[{"issue": {"title": "t", "body": "complete-feature", "labels": ["accepted"]}}]),
              dict(by713["stop-hint-continue"], steps=[{"until": {"pull": {"closes": True}}}])])],
          ["accepts its issue before the triage's verdict", "reads the autopilot's result on its issue with no `until` its seal",
           "opens its issue accepted", "reads the autopilot's result on its issue with no `until` its seal",
           "opens its `before` issue accepted", "expects the autopilot's result on its issue"])
    reads = [s["id"] for s in real["scenarios"] if "issue" in (s.get("opens") or {}) and "lane:release" not in (s["opens"]["issue"].get("labels") or [])
             and any(needs_autopilot(w) for w in [s.get("expect")] + [st_["until"] for st_ in s.get("steps") or [] if "until" in st_])]
    check("#713 C2: the real file: every scenario that reads the autopilot's result waits for it, each within 15 minutes",
          (autopilot_problems(real["scenarios"]), sorted(reads), {limit(by713[i]) for i in reads}),
          ([], sorted(["accepted-spec", "spec-to-draft", "core-one-at-a-time", "decision-sub-issues", "prd-edited-after-acceptance", "question-answered", "stop-hint-continue", "draft-in-conflict", "ready-behind-main"]), {15}))
    check("#713 C2: core-one-at-a-time accepts its `before` issue after its triage, and waits for its seal",
          (by713["core-one-at-a-time"]["before"][0]["issue"].get("labels"), [p for p in autopilot_problems([by713["core-one-at-a-time"]])],
           preconditions([by713["core-one-at-a-time"]], real["bodies"], rpack)), (None, [], []))
    # #713 C3: the claim before the acceptance.
    claim = by713["claim-and-release"]
    order = [next(iter(k for k in st_ if k != "of")) + ":" + str(next(v for k, v in st_.items() if k != "of")) for st_ in claim["steps"]]
    check("#713 C3: the real claim-and-release opens its issue plain and comments /claim before it is accepted, still covering the wait on a claim",
          ("accepted" in (claim["opens"]["issue"].get("labels") or []), order.index("comment:/claim") < order.index("label:accepted"), "next_step:wait:claim" in claim["covers"]),
          (False, True, True))
    st, fake = sealing()
    got = play(claim, "o/t", "v7-next", real["bodies"], fake, lambda s: None, 15, types=real["types"])
    acts = [c[c.index("--body") + 1] if c[1] == "comment" else c[c.index("--add-label") + 1] for c in st["calls"]
            if c[:2] == ("issue", "comment") or (c[:2] == ("issue", "edit") and "--add-label" in c)]
    check("#713 C3: played, /claim goes before accepted, and the claim is not refused", (got["ok"], acts, any("refused" in c for c in st["comments"])),
          (True, ["/claim", "accepted", "/unclaim"], False))
    check("#713 C3: autopilot_problems refuses a /claim after the acceptance",
          [p.split(": ", 1)[1][:30] for p in autopilot_problems([dict(claim, steps=[{"label": "accepted"}, {"comment": "/claim"}]),
                                                               dict(claim, opens={"issue": dict(claim["opens"]["issue"], labels=["accepted"])})])],
          ["comments /claim on its issue a"] * 2)
    # #713 C4: a writer's release is refused, in issue-accepted.yml's words.
    rel = by713["release-issue"]["expect"]
    with open(os.path.join(ROOT, ".github", "workflows", "issue-accepted.yml"), encoding="utf-8") as fh:
        refusal = [l for l in fh if "only a person with the admin or maintain role approves a release" in l]
    check("#713 C4: release-issue expects the refusal a writer gets, the very words issue-accepted.yml says, and no pull request",
          (rel.get("pull"), [m for m in rel.get("comments") or [] if not (refusal and m in refusal[0])], len(refusal)), (False, [], 1))
    seen713 = {"labels": ["accepted", "lane:release"], "comments": ["**No release pull request:** x accepted this issue with the role write on the repository"]}
    check("#713 C4: holds: the refusal and no pull request pass; a pull request that closes it fails, named",
          (holds(rel, seen713), holds(rel, dict(seen713, pull={"number": 5, "title": "chore: release 0.0.1"}))[0]), ([], "a pull request closes it (5)"))
    # #713 C5: the bodies the triage would refuse or ask about.
    post = engine_post()
    fields = form_required(load_yaml(os.path.join(ROOT, BUG_FORM)))
    check("#713 C5: the bug report form's required fields, read from bug_report.yml", fields, ["What happened?", "Steps to reproduce", "Version"])
    check("#713 C5: the decision and bug bodies pass issue-schema.py, and each bug body has every field the form requires",
          ({n: post.issue(marked(real["bodies"][n], n)) for n in ("decision", "bug", "bug-not-reproduced")},
           {n: missing_fields(real["bodies"][n], fields) for n in ("bug", "bug-not-reproduced")}),
          ({n: [] for n in ("decision", "bug", "bug-not-reproduced")}, {n: [] for n in ("bug", "bug-not-reproduced")}))
    check("#713 C5: the decision names only the test repository", "### Repositories\n\nname: diluxone-test\n" in real["bodies"]["decision"], True)
    old = dict(real, bodies=dict(real["bodies"], decision="### Decision\n\nTwo.\n", **{"bug-not-reproduced": real["bodies"]["bug-not-reproduced"].split("### Version")[0] + "### Problem" + real["bodies"]["bug-not-reproduced"].split("### Problem", 1)[1]}))
    got = fixture_problems(old, post.issue, post.pull, post.release, fields)
    check("#713 C5: fixture_problems names a decision the schema refuses, and a Bug body without the form's Version",
          (any(p.startswith("scenario decision-sub-issues: its body `decision`:") for p in got),
           "scenario bug-not-reproduced: its Bug body `bug-not-reproduced` has no `Version`, which the bug report form requires" in got),
          (True, True))
    dec = by713["decision-sub-issues"]
    check("#713 C5: decision-sub-issues opens its decision plain and accepts it after its triage",
          (dec["opens"]["issue"].get("labels"), dec["steps"][:2]), (None, [{"until": {"labels": ["awaiting-acceptance"]}}, {"label": "accepted"}]))
    check("#713 C5: decision-sub-issues expects what a decision gets in the test repository, accepted and sealed, waiting until its seal",
          (dec["steps"][2:], dec["expect"]), ([{"until": {"comments": [SEAL]}}], {"labels": ["accepted"], "comments": [SEAL]}))
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv[:1] == ["coverage"] and len(argv) <= 2:
        root = argv[1] if len(argv) == 2 else ROOT
        conf = load_yaml(os.path.join(root, SCENARIOS))
        out = problems(conf, root)
        for line in out:
            print(line)
        if not out:
            print(f"every pair and transition has its scenario ({len(conf.get('scenarios') or [])} scenarios)")
        return 1 if out else 0
    if argv[:1] == ["run"]:
        import argparse
        p = argparse.ArgumentParser(prog="release-scenarios.py run")
        p.add_argument("--repo", required=True)
        p.add_argument("--ref", default="v7-next")
        p.add_argument("--only", nargs="*", default=[])
        p.add_argument("--out", default="")
        p.add_argument("--minutes", type=int, default=20)
        p.add_argument("--moved", default="")
        a = p.parse_args(argv[1:])
        moved = [] if a.moved else None
        record = (lambda m: write_moved(m, a.moved)) if a.moved else None
        results = run_all(load_yaml(os.path.join(ROOT, SCENARIOS)), a.repo, a.ref, a.only, minutes=a.minutes, moved_out=moved, record=record)
        write_results(results, a.out)
        return 0 if all(r["ok"] for r in results) else 1
    if argv[:1] == ["plan"] and len(argv) == 1:
        scenarios = load_yaml(os.path.join(ROOT, SCENARIOS)).get("scenarios") or []
        wrong = timing(scenarios)
        for line in wrong:
            print(line, file=sys.stderr)
        print(json.dumps(scenario_plan(scenarios), separators=(",", ":")))
        return 1 if wrong else 0
    if argv[:1] == ["groups"] and len(argv) == 1:
        scenarios = load_yaml(os.path.join(ROOT, SCENARIOS)).get("scenarios") or []
        gs, wrong = groups(scenarios), partition(scenarios, groups(scenarios), test_pack())
        for line in wrong:
            print(line, file=sys.stderr)
        if wrong:
            return 1
        print(json.dumps(gs, separators=(",", ":")))
        return 0
    if argv[:1] in (["move"], ["play"]):
        import argparse
        p = argparse.ArgumentParser(prog=f"release-scenarios.py {argv[0]}")
        p.add_argument("--repo", required=True)
        p.add_argument("--ref", default="v7-next")
        p.add_argument("--out", default="")
        p.add_argument("--minutes", type=int, default=20)
        if argv[0] == "move":
            p.add_argument("--moved", required=True)
        else:
            p.add_argument("--group", required=True)
        a = p.parse_args(argv[1:])
        if argv[0] == "move":
            results = move_callers(a.repo, a.ref, callers_gh(), minutes=a.minutes, record=lambda m: write_moved(m, a.moved))[1]
        else:
            results = play_group(load_yaml(os.path.join(ROOT, SCENARIOS)), a.group, a.repo, a.ref, minutes=a.minutes)
        write_results(results, a.out)
        return 0 if all(r["ok"] for r in results) else 1
    if argv[:1] == ["merge"]:
        import argparse
        p = argparse.ArgumentParser(prog="release-scenarios.py merge")
        p.add_argument("--dir", required=True)
        p.add_argument("--groups", default="")
        p.add_argument("--job", action="append", default=[])
        p.add_argument("--run", default="")
        p.add_argument("--out", required=True)
        p.add_argument("--minutes", type=int, default=0)
        p.add_argument("--play-minutes", type=int, default=0)
        a = p.parse_args(argv[1:])
        jobs = dict(j.split("=", 1) if "=" in j else (j, "") for j in a.job)
        results = merge_dir(a.dir, read_groups(a.groups), jobs, a.run, a.minutes, a.play_minutes)
        write_results(results, a.out)
        return 0 if all(r["ok"] for r in results) else 1
    if argv[:1] == ["back"]:
        import argparse
        p = argparse.ArgumentParser(prog="release-scenarios.py back")
        p.add_argument("--repo", required=True)
        p.add_argument("--ref", default="v7-next")
        p.add_argument("--moved", required=True)
        p.add_argument("--out", default="")
        p.add_argument("--minutes", type=int, default=20)
        a = p.parse_args(argv[1:])
        moved, unread = read_moved(a.moved, a.ref)
        results = (read_results(a.out) if a.out else []) + unread + put_back(a.repo, a.ref, moved, callers_gh(), minutes=a.minutes)
        write_results(results, a.out)
        return 0 if all(r["ok"] for r in results) else 1
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
