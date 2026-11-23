#!/usr/bin/env python3
"""The release scenarios (#563): what the release lane plays in the test
repository (org.yml `test-repo`, kind engine-test) at `v7-next` before `v7`
moves, as data in tests/release/scenarios.yml.

Every pair of a reusable workflow and an event the test repository's
callers wire (its pack's `callers` among workflow-templates/*.yml, its
pull-request pipeline test-pull-request.yml among them: the required
workflow, org-pull-request.yml, runs at `v7` everywhere else, #748), but a
`schedule` no scenario can cause, and every
transition of the autopilot's state machine (scripts/autopilot.py:
`next_step`'s BOT_ACTIONS, its waits on PERSON_DECISIONS and BOT_WAITS, the
MERGE_HOWS of `merge-main`, and what `sweep_step` returns), has a scenario
that covers it, but a transition the file's `statically:` names with the
test that holds it, which no scenario can cause there (#707). A scenario: `id`, `covers` (pairs `<workflow>:<event>`,
transitions `next_step:<action>`, `next_step:wait:<for>`,
`next_step:merge-main:<how>`, `sweep_step:<what>`, and the steps of the
flow no person moves, `flow:<name>`, one per name of the file's `flows:`
(#699), each played with no label moved by hand but the acceptance, its
`expect`'s `hands`, `hands_problems`), `before` (issues it
opens first and keeps open until it ends, each `{issue: {...}}`, and files
of its own it lands on main first, each `{lands: <name>, says: <text>}`:
scenarios/<id>/<name>.md, through a docs pull request of the scenario that
merges, unless main says it already: #707), `opens`
(an `issue` or a `pull` with its `title`, `body` (a name of `bodies:` or the
text), `labels`, and `fork: true` for one from a fork; a pull's `{issue}` in
its body is the number of the issue it opens first, its `issue:` or a
complete feature, and its `{files}` the files of its diff, one
`` - `path` `` line each (#760: `pull_files`); an issue's `type`, else the Type its body's form gives,
`types:` of the file, and its `comments`, posted before its labels: a
`/claim` before `accepted`), `steps` (each one of
`comment`, `label`, `unlabel`, `edit`, `push`, `dispatch`, `retitle` (the
title of the pull request it observes, an issue's the autopilot's, #699),
and `until`,
an `expect` polled every 75 seconds (#726: every scenario at once shares
the test identity's 5000 requests an hour, #878: with their setup, cleanup
and retry) on its issue or pull request, or with
`of: before` on its first `before` issue, never a fixed wait: #694; a
`comment` or a `label` with `of: before` acts on that issue too, #713; a
file is written in a commit GitHub signs, `createCommitOnBranch` (#709); a
`push: <name>` writes scenarios/<id>/<name>.md on the head branch of the
pull request it observes, the autopilot's for an issue, and `conflict`
then lands that file, otherwise, on main, `behind` only a file of its own
there, through a docs pull request of the scenario that merges: #698;
every text it writes there, and scenarios/<id>/pull.md a pull's, carries
the run's id, `run_mark`, so none is what an earlier run merged into main,
which would leave its pull request with no diff: #778, `scenario_text`;
a `before`'s file says its `says` alone),
`minutes` (its limit, 10 by default, 15 at most) and
`expect` (`labels`, `absent`, `comments` (markers), `count` ({marker:
n}, how many comments carry it, #696), `pull` (`closes`,
`branch`, `title`, `draft`, `waits` (whom its board says it waits on,
#699), patterns; `false` for none that closes it, #713), `check` (name: conclusion, the name a
check run's caller's job or its own: `check_named`, #709), `merged`,
`waiting`, `state` (OPEN or CLOSED, #696: a bug's issue its merged fix
closed), and (#699) `hands` (the labels a person may add or remove: any
other label event of anyone but the bot, on its issue or its pull
request, fails it), `bot_labeled` (labels the bot added) and `rerun` (a
run on the pull request's head ran again), read from the label events
once the rest holds). A `push: token` writes a fake token (#699 C5).
Every scenario is a group of its own (`groups`, #694), and
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
        too, or a Bug's without a field bug_report.yml requires; #760: a
        pull request whose description would not name every file of its
        diff, its body with no `{files}`; #764: one that expects a
        `risk:<level>` label no path it changes gets as its floor for kind
        engine-test, the organisation's patterns and the kind's
        surface.yml `high-risk` matched as scripts/policy.py matches them,
        `risk_problems`; #696: a path docs/model.md describes, or a
        setting that changes one, with no row in docs/paths.md, a row
        that names no scenario, or one that names a scenario that is not
        here, `paths`).
        Every other pair a shipped caller wires is held to the
        engine statically, by scripts/caller-contract.py check; and
        what is wrong with the groups (`partition`): a scenario in no
        group or in two, two scenarios that could write to the same
        part of the test repository's core, a scenario that writes under
        it but expects no wait on it (#709), a group id unfit for an
        artifact name; and (#748, `pipeline_problems`) a pack with no
        caller that wires the pull-request pipeline's jobs on
        pull_request and merge_group, org-pull-request.yml among its
        callers, and an engine call in one of them the lane cannot move
  release-scenarios.py plan
        prints each scenario's limit in minutes and how often it polls,
        [{id, minutes, poll}] as JSON; exits 1 naming a fixed wait or a
        limit past 15 minutes (#694)
  release-scenarios.py groups [--passed FILE]
        prints the groups, [{id, scenarios}] as JSON, the release lane's
        `play` matrix; exits 1 naming what `partition` finds. With
        --passed, the scenarios FILE names dropped, then empty groups (#929)
  release-scenarios.py passed --repo R --sha MAIN --next V7NEXT --out FILE
                              [--run-id ID]
        what passed on this candidate before (#929): the completed earlier
        runs of release-lane.yml (GH_TOKEN, `actions: read`), newest
        first, up to EARLIER_RUNS, until the first whose
        `scenarios-results` artifact has the key (MAIN, V7NEXT); its
        passing scenarios, each with the run it first passed in, written
        to FILE as [{id, in}] ([] for a new candidate, or when they cannot
        be read); exit 0
  release-scenarios.py move --repo OWNER/NAME --moved MOVED --out FILE
                            [--ref v7-next] [--minutes N] [--record-only]
        the callers moved to the ref, as `run` does (with
        DX_CALLERS_TOKEN), what moved written to MOVED as soon as the
        pointing is over, and to FILE the failing `callers` row when they
        did not reach it, or (#748, `at_candidate`) one for each pipeline
        there that would still run off the ref: its default branch still
        requiring org-pull-request.yml (a `workflows` rule), or a
        .github/workflows/*.yml calling the engine off the ref (exits 1
        then: no group plays, and `back` puts back what moved). MOVED
        names too every caller already at the ref, with its text before
        the lane's pull request that moved it there (#929, `leftovers`),
        so `back` puts back the ref from before any lane. With
        --record-only (#929: nothing left to play), no caller moves and
        MOVED records those alone
  release-scenarios.py play --repo OWNER/NAME --group ID --out FILE
                            [--ref v7-next] [--minutes N]
        the group's scenarios, one after another in its order, with the
        test identity's token (GH_TOKEN) alone, the callers already at the
        ref, each one first deleting its leftover `scenario/<id>` branch
        and closing the issues and pull requests an earlier run of it left
        (the `dx-scenario: <id>` mark first in every body it opens), and
        again after (#694); a scenario that failed is played once more
        (#843, `retried`) within what is left of N minutes, the player's
        own deadline below the play step's timeout (#878), less the first
        attempt's own time (RETRY_ALLOWANCE minutes at least) and a poll,
        and passing then is `flaky`, its row
        `pass (flaky: <first why>)`, which fails nothing; with less than
        a minute left it is not, and says so; a transient `gh` error is
        retried within it (#878, `patient`); their table to FILE, written
        before the first attempt and after each, a scenario not ended yet
        a failing `infrastructure` row (ENDED), and again on a SIGTERM
        or SIGINT, so a step killed in the middle still leaves it; exits
        1 when one fails. Each row keeps in `triggered` (#843) the pairs
        its runs triggered (`run_triggered`, read once at its end). A
        failing row says its `class` (#843, CLASSES:
        engine, harness or infrastructure), which release-lane.py files
        each its own way
  release-scenarios.py merge --dir DIR --groups JSON --job NAME=RESULT ...
                             --out FILE [--run URL] [--minutes N]
                             [--play-minutes M]
        one table, to FILE (and stdout), from the scenarios-<name>-a<N>/results.md
        under DIR (`move`, `back` and every group's): each group's rows of
        its own scenarios, and a failing row, with URL, for a group whose
        file is missing (its job failed, timed out or was cancelled), a
        scenario with no row, and a job whose RESULT is not success (a play
        job's naming its timeout of N minutes, and its play step's of M,
        #690), then the pairs no row's runs triggered (#843,
        `run_coverage`: "Pairs no scenario triggered: …", a warning that
        fails nothing, never counting `covers:`, which `coverage` reads as
        each scenario's plan); exits 1 when a row fails. With --passed FILE
        (what `passed` wrote, #929), a passing row `pass (in <run>)` for
        each scenario that passed on the same candidate, so it still counts.
        Each name's latest attempt is read (#929: a re-run's over the
        first's), and a play job that failed adds no row of its own when
        a group's row failed: its job fails on it, so a re-run replays it
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
        up, cleans up (its pack's `cleanup: after-run`; a pull request in
        the merge queue is closed only once it leaves it, #936) and writes the
        Markdown table of results (scenario, pass or fail, run link) to
        FILE (and stdout), then puts the callers back the same way; a
        pull request that does not merge is a failing `callers` row;
        exits 1 when one fails. With --moved MOVED, what moved is written
        to MOVED as soon as the pointing is over, before the first
        scenario plays ([] when it failed cleanly), and left for `back`
  release-scenarios.py back --repo OWNER/NAME (--moved MOVED | --moved-dir DIR)
                            [--ref v7-next] [--out FILE] [--minutes N]
        puts back the callers `run --moved` left at the ref (with
        DX_CALLERS_TOKEN, minted after the scenarios: an App token lasts
        an hour) and adds a failing `callers` row to FILE if they do not
        come back, or if MOVED is missing or unreadable (a run cancelled
        or killed while pointing: could not tell, never "nothing moved");
        exits 1 when a row of FILE fails. With --moved-dir, every
        attempt's record under DIR (#929, `read_moved_dir`), each caller
        put back as the earliest attempt that recorded it found it
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


REQUIRED = ".github/workflows/org-pull-request.yml"


def test_callers(pack):
    """The test repository's callers, as globs: its pack's `callers` among
    the shipped ones. The required workflow, org-pull-request.yml, runs
    everywhere else, at `v7`: there, its pipeline is test-pull-request.yml's
    (#748), which the lane moves to the candidate."""
    return tuple(f"workflow-templates/{c}" for c in pack.get("callers") or [])


def engine_calls(text, central):
    """The lines of a caller that call the engine (`uses:` of a workflow of
    `central`), as (number, line). Pure."""
    pat = re.compile(r"^\s*-?\s*uses:\s*['\"]?" + re.escape(central) + r"/\.github/workflows/")
    return [(i, line) for i, line in enumerate(text.split("\n"), 1) if pat.match(line)]


def unmovable(text, central):
    """The engine calls of a caller `at_ref` would not move (one that does
    not match USES: quoted, with no ref, a step's), as "line N: ...". Pure."""
    uses = re.compile(USES.format(re.escape(central)))
    return [f"line {i}: {line.strip()!r}" for i, line in engine_calls(text, central) if not uses.match(line)]


def off_ref(text, central, ref):
    """The engine calls of a caller not at `ref`, as "line N: ...". Pure."""
    uses = re.compile(USES.format(re.escape(central)))
    return [f"line {i}: {line.strip()!r}" for i, line in engine_calls(text, central) if not ((m := uses.match(line)) and m.group(2) == ref)]


def pipeline_problems(root, pack, central):
    """What would leave a pipeline of the test repository at `v7` while the
    lane plays the candidate (#748), statically: no caller of its pack's
    that wires the pull-request pipeline's jobs on `pull_request` and
    `merge_group` (every pair org-pull-request.yml wires), org-pull-request.yml
    among its callers (the required workflow, whose calls are hard-wired to
    `@v7`), and an engine call in one of its callers `at_ref` would not move.
    Each names the file. Pure but for reading the files."""
    out, callers = [], test_callers(pack)
    named = [c for c in pack.get("callers") or [] if os.path.basename(str(c)) == os.path.basename(REQUIRED)]
    if named:
        out.append(f"kinds/engine-test/pack.yml `callers` names {named[0]}, the required workflow, which runs at `v7` with its calls hard-wired: "
                   "the test repository runs the pipeline from test-pull-request.yml, which the lane moves")
    want, have = pairs(root, (REQUIRED,)), pairs(root, callers)
    events = {e for pattern in callers for path in glob.glob(os.path.join(root, pattern)) for e in caller_events(load_yaml(path))}
    gaps = sorted(want - have) + [f"`{e}`" for e in ("pull_request", "merge_group") if e not in events]
    if gaps:
        out.append(f"kinds/engine-test/pack.yml `callers` has no caller that wires the pull-request pipeline ({', '.join(gaps[:4])}"
                   f"{', …' if len(gaps) > 4 else ''}): its pull requests would run no candidate's pipeline; add test-pull-request.yml")
    for pattern in callers:
        for path in sorted(glob.glob(os.path.join(root, pattern))):
            for line in unmovable(open(path, encoding="utf-8").read(), central):
                out.append(f"{os.path.relpath(path, root)} {line}: an engine call the lane cannot move to the candidate (`uses: {central}/.github/workflows/<name>.yml@<ref>`)")
    return out


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
    for pattern in test_callers(pack):
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


# What `statically:` may hold instead of a scenario: a transition, or a
# step of the flow (#699, `flows`).
STATIC = ("next_step:", "sweep_step:", "flow:")


def flows(conf):
    """The steps of the flow no person moves (#699): `flow:<name>` for each
    of the file's `flows:`. Pure."""
    return {f"flow:{k}" for k in (conf.get("flows") or {})}


def coverage(scenarios, wanted, statically=None):
    """What has no scenario, and what a scenario covers that is not wanted:
    ["... has no scenario"]. `statically` (the file's `statically:`, #707)
    names each transition (or step of the flow, #699) no scenario can cause
    in the test repository, with what holds it instead: it is covered by
    that, never by a scenario as well, and must be a transition or a flow
    with its reason. Pure."""
    covered, out, seen = set(), [], set()
    statically = statically or {}
    for w, why in sorted(statically.items()):
        if not str(w).startswith(STATIC) or w not in wanted:
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
        kind = "the flow" if w.startswith("flow:") else "the transition" if w.startswith(("next_step:", "sweep_step:")) else "the pair"
        out.append(f"{kind} {w} has no scenario in {SCENARIOS}")
    return out


# The labels a person may add or remove in a scenario that plays a step of
# the flow (#699): the acceptance, which is a maintainer's decision; every
# other label is the bot's to move.
HANDS = ("accepted",)
LABEL_VERBS = ("label", "unlabel")


def hands_problems(scenarios):
    """Every scenario that covers a `flow:` and moves a label by hand
    (#699): it says no `hands` in its `expect` (the labels a person may add
    or remove, which `holds` reads from the label events), names one past
    HANDS, or takes a `label`/`unlabel` step, or opens something labelled,
    with a label its `hands` does not name. Pure."""
    out = []
    for s in scenarios:
        if not any(str(c).startswith("flow:") for c in s.get("covers") or []):
            continue
        sid, hands = s.get("id") or "?", (s.get("expect") or {}).get("hands")
        if not isinstance(hands, list):
            out.append(f"scenario {sid}: plays a step of the flow with no `hands` in its `expect`, so a label a person moved would not fail it")
            continue
        out += [f"scenario {sid}: its `hands` names {h}, which is the bot's to move (a person may move only {', '.join(HANDS)})" for h in hands if h not in HANDS]
        opens = s.get("opens") or {}
        spec = opens.get("issue") or opens.get("pull") or {}
        moved = [l for l in (spec.get("labels") or []) + ((spec.get("issue") or {}).get("labels") or [])]
        moved += [str(st[v]) for st in s.get("steps") or [] if isinstance(st, dict) for v in LABEL_VERBS if v in st]
        out += [f"scenario {sid}: moves the label {l} by hand, which its `hands` does not name" for l in moved if l not in hands]
    return out


# The autopilot's comment on an issue that waits for the core (#563): its
# wait itself is on the issue's board (`core_wait`, #802), no label.
CORE_MARK = "<!-- dx-autopilot-core -->"


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


# A bug's verdict, as labels (#801): confirmed, or found nothing. Where it
# waits otherwise is on the issue's board, never a label.
BUG_VERDICTS = ("bug:confirmed", "needs-info")


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
    (#707) a bug's verdict (`bug:confirmed`, or `needs-info` when it found
    nothing, #801) expected in a test repository with no way to reproduce
    it (`repro` False: repos.yml and its pack declare none, so the bug gets
    `needs-human`), or a
    confirmed bug's issue expected to have a pull request that closes it
    (the reproduction's fix closes the lane's own issue, never the
    report), and (#760) a pull request whose description, `pull_text` of
    its body, would not name every file of its diff (`pull_files`), its
    body with no `{files}` among them, or the one it lands on main
    through, of the `pull` body, and (#881) an issue or a pull request
    whose body names another scenario's file (`scenarios/<other>/`): the
    triage reads it as that scenario's report, a `duplicate`. Pure."""
    import fnmatch
    out = []
    for s in scenarios:
        sid, expect, opens = s.get("id") or "?", s.get("expect") or {}, s.get("opens") or {}
        for kind in ("issue", "pull"):
            if kind in opens:
                body = body_of((opens[kind] or {}).get("body"), bodies)
                for other in sorted(set(re.findall(r"scenarios/([A-Za-z0-9_-]+)/", body)) - {sid}):
                    out.append(f"scenario {sid}: its {kind}'s body names scenarios/{other}/, another scenario's file, "
                               f"so the triage reads it as that scenario's report (a duplicate)")
        # #696: `count` is {marker: how many comments carry it}.
        count = expect.get("count")
        if count is not None and (not isinstance(count, dict) or not count
                                  or any(not isinstance(n, int) or isinstance(n, bool) or n < 0 for n in count.values())):
            out.append(f"scenario {sid}: its expect's count is not {{marker: a whole number}}")
        verdicts = [v for v in BUG_VERDICTS if v in (expect.get("labels") or [])]
        if verdicts and repro is False:
            out.append(f"scenario {sid}: expects {', '.join(verdicts)}, but the test repository has no way to reproduce a bug "
                       f"(repos.yml and its pack declare none), so it gets needs-human")
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
        if "pull" in opens:
            # #760: a description that names none of its diff is never merged by policy.
            body = body_of(opens["pull"].get("body"), bodies)
            if "{files}" not in body:
                out.append(f"scenario {sid}: its pull request's body has no `{{files}}`, so its description names none of the files it changes")
            else:
                missing = unnamed(pull_text(body, "1", pull_files(s)), pull_files(s))
                if missing:
                    out.append(f"scenario {sid}: its pull request's description does not name {', '.join(missing)}, which it changes")
        lands = any("lands" in b for b in s.get("before") or []) or any(isinstance(st, dict) and st.get("push") in LANDS for st in s.get("steps") or [])
        if lands and "{issue}" in bodies.get("pull", "") and "{files}" not in bodies["pull"]:
            out.append(f"scenario {sid}: the `pull` body has no `{{files}}`, so the pull request it lands on main through names none of the files it changes")
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


def pull_files(s):
    """The files the pull request scenario `s` opens adds or edits (#760),
    its diff, in order and once each: scenarios/<id>/pull.md, written when
    it opens, then scenarios/<id>/<name>.md for each `push: <name>` but
    `behind`, written on its head. [] for a scenario that opens none.
    Pure."""
    if "pull" not in (s.get("opens") or {}):
        return []
    sid, out = s.get("id"), [f"scenarios/{s.get('id')}/pull.md"]
    for step in s.get("steps") or []:
        if isinstance(step, dict) and "push" in step and str(step["push"]) != "behind":
            path = f"scenarios/{sid}/{step['push']}.md"
            if path not in out:
                out.append(path)
    return out


def pull_text(body, issue, files):
    """A scenario pull request's description (#760): `body` with `{issue}`
    the number of the issue it closes and `{files}` one `` - `path` `` line
    per file of its diff. Pure."""
    return body.replace("{issue}", str(issue)).replace("{files}", "\n".join(f"- `{f}`" for f in files))


def unnamed(text, files):
    """The files of `files` the description `text` does not name (as
    `` `path` ``). Pure."""
    return [f for f in files if f"`{f}`" not in text]


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
        elif not re.search(str(pattern), "" if pull.get(key) is None else str(pull.get(key))):
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
    # #696: how many comments carry a marker (a stop said once, never twice).
    for marker, n in (expect.get("count") or {}).items():
        got = sum(1 for c in seen.get("comments") or [] if marker in str(c))
        if got != n:
            out.append(f"{got} comments with {marker}, not {n}")
    # #696: the issue's or the pull request's state (CLOSED once its fix merged).
    if "state" in expect and str(seen.get("state") or "").upper() != str(expect["state"]).upper():
        out.append(f"its state is {seen.get('state') or 'unknown'}, not {expect['state']}")
    # #699: the label events, read once the rest holds (`EVENT_KEYS`).
    out += by_hand(expect, seen)
    if "bot_labeled" in expect:
        added = {e.get("label") for e in seen.get("label_events") or [] if e.get("bot") and e.get("event") == "labeled"}
        out += [f"the bot never added {label}" for label in expect.get("bot_labeled") or [] if label not in added]
    if expect.get("rerun") and not seen.get("rerun"):
        out.append("no run on its head ran again")
    return out + [saw(seen)] if out else out


# The keys of `expect` read from the label events (#699), which `play`
# reads only once the rest of its `expect` holds.
EVENT_KEYS = ("hands", "bot_labeled")


def by_hand(expect, seen):
    """Each label a person added or removed that `expect`'s `hands` does
    not allow (#699), from `seen`'s label events: ["<who> added the label
    <l> by hand"]. A person is an actor that is no bot at all (`person`):
    another App such as github-actions[bot] moves no label by hand, though
    it is not the bot `bot_labeled` asks for. [] without `hands`. Pure."""
    if "hands" not in expect:
        return []
    allowed = set(expect.get("hands") or [])
    return [f"{e.get('actor') or 'someone'} {'added' if e.get('event') == 'labeled' else 'removed'} the label {e.get('label')} by hand"
            for e in seen.get("label_events") or [] if e.get("person", not e.get("bot")) and e.get("label") not in allowed]


# Every wait polls its state (#694): never a fixed sleep. Every scenario
# polls at once with the test identity's token (#726), which GitHub allows
# RATE_LIMIT requests an hour: `call_budget`, its polls with (#878) every
# scenario's setup, cleanup and retry, stays under it at 75 seconds.
POLL = 75
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
    for marker, n in (expect.get("count") or {}).items():
        got = sum(1 for c in seen.get("comments") or [] if marker in str(c))
        if isinstance(n, int) and got > n:
            out.append(f"{got} comments with {marker} already, past {n}")
    # #699: a label a person moved stays moved.
    out += by_hand(expect, seen)
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


def heads(want):
    """Whether the expectation `want` reads the runs on a pull request's
    head (#699): a `check` (#709: one GitHub holds for approval) or a
    `rerun`. Pure."""
    return bool((want or {}).get("check") or (want or {}).get("rerun"))


def poll_budget(scenarios):
    """The `gh` calls an hour every scenario polling at once makes (#726):
    each one's calls a poll, as `observe` makes them (2 for an issue: its
    view and the runs; for a pull request 2, and 3 when it waits on a check
    or a re-run, `heads`: its view, the runs of its head and the runs; one
    more for an `expect` with `bot_labeled`, whose label events are read
    each poll once the rest holds, #699), every POLL seconds. Pure."""
    def calls(s):
        wants = [s.get("expect") or {}] + [st.get("until") or {} for st in s.get("steps") or [] if isinstance(st, dict)]
        n = 3 if "pull" in (s.get("opens") or {}) and any(heads(w) for w in wants) else 2
        return n + (1 if "bot_labeled" in (s.get("expect") or {}) else 0)
    return sum(calls(s) * 3600 // POLL for s in scenarios)


# The attempts a scenario can take in a play step (#843: one retry).
ATTEMPTS = 2


def setup_calls(s, bodies=None):
    """The `gh` calls one attempt of the scenario `s` makes besides its
    polls (#878), as `_play` makes them: its `clear` before and after (its
    branches deleted, the lane's leftovers and the two searches), each
    issue it opens (its creation, comments and labels) and its cleanup (the
    view, the pull request that closes it, its close and lock), its pull
    request (its branch, its file, its creation, from a fork its fork and
    login), each land on main (its branch, its file, its pull request, its
    close), each step, and the read of the runs it triggered. Every pull
    request its cleanup closes is read first (#936: `queued`); the polls
    of one still in the merge queue, QUEUE_LEAVE / QUEUE_POLL at most per
    cleanup, are rare and bounded in time, and not counted. Pure."""
    sid, opens, bodies = s.get("id") or "?", s.get("opens") or {}, bodies or {}
    lands = [str(b["lands"]) for b in s.get("before") or [] if isinstance(b, dict) and "lands" in b]
    cleared = len(dict.fromkeys([f"scenario/{sid}", branch_of(s)] + [landing(sid, a) for a in (*LANDS, *lands)])) + 3
    n = 2 * cleared + 2
    for spec, _ in opened_issues(s, bodies):
        first = spec.get("comments") or []
        n += 1 + len(first) + (1 if first and spec.get("labels") else 0) + 4 + 1
    landed = len(lands) + sum(1 for st in s.get("steps") or [] if isinstance(st, dict) and st.get("push") in LANDS)
    n += 8 * landed + len(lands)
    if "pull" in opens:
        n += 8 + (2 if (opens.get("pull") or {}).get("fork") else 0)
    for st in s.get("steps") or []:
        if not isinstance(st, dict):
            continue
        verb = next((k for k in st if k != "of"), None)
        looked = 3 if "issue" in opens and verb in ("retitle", "push") else 0
        n += looked + (2 if verb == "push" and st.get("push") != "behind" else 0 if verb in ("push", "until", "wait") else 1)
    return n


def call_budget(scenarios, bodies=None):
    """The `gh` calls an hour every scenario played at once makes (#878):
    its polls (`poll_budget`) and, for each of its ATTEMPTS, its setup and
    cleanup (`setup_calls`). Pure."""
    return poll_budget(scenarios) + sum(ATTEMPTS * setup_calls(s, bodies) for s in scenarios)


def timing(scenarios, bodies=None):
    """What is wrong with the plan's waits (#694): a fixed `wait` step
    (every wait is an `until` that polls its state), an `until` that names
    no expectation, a limit past MAX_LIMIT minutes, and (#726) polls that,
    every scenario at once, with (#878) the setup, cleanup and retry of
    each (`call_budget`), pass the test identity's RATE_LIMIT. Pure."""
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
    calls = call_budget(scenarios, bodies)
    if calls > RATE_LIMIT:
        out.append(f"the plan's {len(scenarios)} scenarios call GitHub {calls} times an hour, polling every {POLL} seconds, with their setup, cleanup and retry, past the test identity's {RATE_LIMIT}")
    return out


def table(results):
    """The Markdown table of results. Pure."""
    lines = ["| Scenario | Result | Run |", "| --- | --- | --- |"]
    for r in results:
        why = f" ({'; '.join(r['why'])})" if r.get("why") else ""
        if r.get("ok") and r.get("flaky"):
            # #843: it failed, then passed on its retry.
            why = f" (flaky: {'; '.join(r.get('first_why') or []) or 'failed once'})"
        if r.get("ok") and r.get("in"):
            # #929: a pass an earlier lane on the same candidate played.
            why = f" (in {r['in']})"
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


def lane_of(repo, report, run=gh):
    """The numbers of the open bugfix-reproduced lane issues in `repo` the
    engine opened from issue `report` (#985): labelled
    `lane:bugfix-reproduced` (listed, never searched) and titled exactly
    "The bug reproduced from #<report>", compared as a number, so #12 never
    matches #120. A read that fails, or a `report` that is no number, finds
    none."""
    try:
        report = int(report)
        found = json.loads(run("issue", "list", "--repo", repo, "--state", "open", "--label", "lane:bugfix-reproduced",
                               "--json", "number,title", "--limit", "50") or "[]")
    except (RuntimeError, ValueError):
        return []
    out = []
    for item in found if isinstance(found, list) else []:
        m = LANE_ISSUE.match(str(item.get("title") or "")) if isinstance(item, dict) else None
        if m and int(m.group(1)) == report and isinstance(item.get("number"), int):
            out.append(item["number"])
    return out


def close_issue(repo, number, run=gh, close=None):
    """Issue `number` in `repo` closed and locked, after the pull requests
    that close it went through `close` (#784, #985). Each step has its own
    try: a view that fails never keeps the issue open."""
    if close:
        try:
            view = json.loads(run("issue", "view", str(number), "--repo", repo, "--json", "closedByPullRequestsReferences") or "{}")
        except (RuntimeError, ValueError):
            view = {}
        for pull in closing_pulls(repo, view):
            close(pull)
    try:
        run("issue", "close", str(number), "--repo", repo)
        run("issue", "lock", str(number), "--repo", repo)
    except (RuntimeError, ValueError):
        pass


# The branch of the autopilot's pull request for a lane issue: `fix/<lane
# issue>-the-bug-reproduced-from-<report>` (#985).
LANE_BRANCH = re.compile(r"^fix/(\d+)-the-bug-reproduced-from-(\d+)$")


def lane_leftovers(repo, mark, run=gh, close=None):
    """Every open bugfix-reproduced lane issue in `repo` whose report
    carries `mark` closed and locked, after the pull requests that close it
    went through `close` (#707: a confirmed bug's, which `clear`'s search
    of the mark cannot find; #985). Then the orphans (#985): every open
    pull request on a lane branch (`LANE_BRANCH`) whose report carries
    `mark` goes through `close` too, which is how earlier runs left them
    (the lane issue closed, its pull request not); a pull request on any
    other branch is never touched. Each report is read once. `close` is
    `closer`'s, by default a new one. A failure here never stops a
    scenario."""
    close = close or closer(repo, run)
    reports, done = {}, set()

    def carries(report):
        if report not in reports:
            try:
                reports[report] = mark in str(json.loads(run("issue", "view", report, "--repo", repo, "--json", "body") or "{}").get("body") or "")
            except (RuntimeError, ValueError, AttributeError):
                reports[report] = False
        return reports[report]

    def shut(number):
        if number not in done:
            done.add(number)
            close(number)

    try:
        found = json.loads(run("issue", "list", "--repo", repo, "--state", "open", "--label", "lane:bugfix-reproduced",
                               "--json", "number,title", "--limit", "50") or "[]")
    except (RuntimeError, ValueError):
        found = []
    for item in found if isinstance(found, list) else []:
        m = LANE_ISSUE.match(str(item.get("title") or "")) if isinstance(item, dict) else None
        if m and isinstance(item.get("number"), int) and carries(str(int(m.group(1)))):
            close_issue(repo, item["number"], run, shut)
    try:
        pulls = json.loads(run("pr", "list", "--repo", repo, "--state", "open", "--json", "number,headRefName", "--limit", "100") or "[]")
    except (RuntimeError, ValueError):
        return
    for pull in pulls if isinstance(pulls, list) else []:
        m = LANE_BRANCH.match(str(pull.get("headRefName") or "")) if isinstance(pull, dict) else None
        if m and isinstance(pull.get("number"), int) and carries(str(int(m.group(2)))):
            shut(pull["number"])


# #936: the test repository's merge queue merges up to 3 pull requests in
# one group, and closing one that is queued knocks the others of its group
# out of the queue unmerged. Before `cleanup` and `clear` close a pull
# request, they wait for it to leave the queue: a poll every QUEUE_POLL
# seconds, QUEUE_LEAVE seconds at most per cleanup (inside PLAY_SPARE and
# RETRY_ALLOWANCE). One still queued when the wait runs out is left open
# (#997): the merge or the next run's `clear` settles it, and GitHub's queue
# drops an entry whose checks time out.
QUEUE_LEAVE = 120
QUEUE_POLL = 15
QUEUED = ("query($owner: String!, $name: String!, $number: Int!) "
          "{ repository(owner: $owner, name: $name) { pullRequest(number: $number) { state isInMergeQueue } } }")


def queued(repo, number, run=gh):
    """Pull request `number`'s (state, isInMergeQueue) in `repo`, from
    GraphQL (gh's `pr view --json` has no queue field); None when the read
    fails or is not JSON (#784: a failure never hides a result)."""
    owner, name = repo.split("/", 1)
    try:
        got = json.loads(run("api", "graphql", "-f", f"query={QUEUED}", "-F", f"owner={owner}", "-F", f"name={name}",
                             "-F", f"number={int(number)}") or "{}")
        pull = got["data"]["repository"]["pullRequest"]
        return str(pull.get("state") or ""), bool(pull.get("isInMergeQueue"))
    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError):
        return None


def queue_read(args):
    """Whether gh's `args` are `queued`'s read, the only GraphQL call here
    that is not a commit. Pure."""
    return tuple(args[:2]) == ("api", "graphql") and f"query={QUEUED}" in args


def closer(repo, run=gh, sleep=time.sleep, leave=None):
    """A `close(number)` for one cleanup: it waits while pull request
    `number` is in the merge queue (QUEUE_LEAVE seconds in all, shared by
    every pull request it closes), closes nothing once it merged, and closes
    it otherwise, `gh pr close --delete-branch`. One still in the queue
    when the wait runs out is never closed (#997: closing it knocks its
    merge group out unmerged); it, and a close that fails, are left for the
    merge or the next run's `clear`."""
    budget = {"left": QUEUE_LEAVE if leave is None else leave}

    def close(number):
        while True:
            read = queued(repo, number, run)
            if read and read[0] == "MERGED":
                return
            if not read or not read[1]:
                break
            if budget["left"] < QUEUE_POLL:
                return  # #997: still queued, left open
            sleep(QUEUE_POLL)
            budget["left"] -= QUEUE_POLL
        try:
            run("pr", "close", str(number), "--repo", repo, "--delete-branch")
        except RuntimeError:
            pass
    return close


def clear(repo, sid, run=gh, branch=None, lands=(), sleep=time.sleep):
    """What scenario `sid` left in `repo`, before it plays and after (#694):
    its branches deleted (`scenario/<id>`, which earlier runs left,
    `branch`, its own now, and those of the pull requests its pushes and
    its `before`'s `lands` put on main through, `landing`), and every open
    issue and pull request whose body carries its mark closed. A failure
    here never stops a scenario: what it cannot clear, the next run
    clears. A confirmed bug's lane issue, whose report carries the mark, is
    closed and locked too, with the pull requests that close it, and so is
    every open pull request on a lane branch whose report carries it, which
    earlier runs left (`lane_leftovers`, #707, #985), with a wait of its
    own, so an orphan in the queue never spends the scenario's (#997). A
    pull request in the merge queue is closed once it leaves it, and left
    open if it is still there when the wait runs out (`closer`, #936,
    #997)."""
    close = closer(repo, run, sleep)
    for name in dict.fromkeys([f"scenario/{sid}"] + ([branch] if branch else []) + [landing(sid, a) for a in (*LANDS, *lands)]):
        try:
            run("api", "-X", "DELETE", f"repos/{repo}/git/refs/heads/{name}")
        except RuntimeError:
            pass  # none left: a 404
    mark = scenario_mark(sid)
    lane_leftovers(repo, mark, run, closer(repo, run, sleep))
    for what in ("issue", "pr"):
        try:
            found = json.loads(run(what, "list", "--repo", repo, "--state", "open", "--search", f'"dx-scenario: {sid}" in:body',
                                   "--json", "number,body", "--limit", "50") or "[]")
        except (RuntimeError, ValueError):
            continue
        for item in found:
            if mark not in str(item.get("body") or ""):
                continue  # the search matched another scenario's, or none
            if what == "pr":
                close(item["number"])
                continue
            try:
                run("issue", "close", str(item["number"]), "--repo", repo)
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


# How many times `patient` retries a transient `gh` error (#878).
GH_TRIES = 3


def patient(run, sleep=None, deadline=None, clock=None):
    """`run` retrying a transient `gh` error (#878, `transient`) after its
    `backoff`, up to GH_TRIES times and never past `deadline` (on `clock`):
    a rate limit or a 5xx in a scenario's setup or cleanup is waited out,
    not a failure at once. Any other error, or one past its tries or the
    deadline, is raised as it came."""
    sleep = sleep or time.sleep
    clock = clock or time.monotonic

    def call(*args, **kw):
        tries = 0
        while True:
            try:
                return run(*args, **kw)
            except GhError as e:
                wait = backoff(e, tries)
                if not transient(e) or tries >= GH_TRIES or (deadline is not None and clock() + wait > deadline):
                    raise
                sleep(wait)
                tries += 1
    return call


def run_mark(env=None, now=None, rand=None):
    """The id of this run of the lane (#778), which every text `play` writes
    under scenarios/<id>/ carries: `GITHUB_RUN_ID-GITHUB_RUN_ATTEMPT` in the
    lane (a re-run of the same run differs too), else, run locally, the
    time with a random suffix. Pure but for `env`, `now` and `rand`."""
    env = os.environ if env is None else env
    if env.get("GITHUB_RUN_ID"):
        return f"{env['GITHUB_RUN_ID']}-{env.get('GITHUB_RUN_ATTEMPT') or '1'}"
    if rand is None:
        import secrets
        rand = secrets.token_hex(3)
    return f"local-{int(time.time() if now is None else now)}-{rand}"


def scenario_text(sid, name, where, run_id):
    """The text `play` writes in scenarios/<sid>/<name>.md on `where` (the
    pull request, or main), in the run `run_id` (#778): its own in each run,
    so no run writes what an earlier one merged into main, which would leave
    its pull request with no diff, and on the head another than on main, so
    `conflict` conflicts. Pure."""
    text = f"{name} on {where}, scenario {sid}, run {run_id}\n"
    # #699 C5: `token` carries one no service issues, which the test
    # repository's review profile blocks on. #882: it has a real
    # credential's shape, a live-style key of 32 base62 characters of its
    # own per run, with no "fake" in it: a value that reads as visibly fake
    # the review lists as a minor and never blocks on, so `settled-rerun`
    # had nothing to re-run. No prefix GitHub's secret scanning knows (no
    # ghp_, AKIA or sk_live_), so writing it is never refused.
    return text + (f"DX_API_TOKEN=dx_live_{live_key(sid, run_id)}\n" if name == "token" else "")


BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def live_key(sid, run_id, size=32):
    """SIZE base62 characters from a sha256 of the scenario `sid` and the
    run `run_id` (#882): high-entropy, its own per run. Pure."""
    import hashlib
    n = int.from_bytes(hashlib.sha256(f"{sid}\n{run_id}".encode()).digest(), "big")
    out = []
    for _ in range(size):
        n, r = divmod(n, 62)
        out.append(BASE62[r])
    return "".join(out)


# What failed a scenario (#843), a failing row's `class`, set where the row
# is made (scripts/release-lane.py files each its own way): `engine`, its
# `until` or `expect` did not hold, or could no longer, against what the
# engine did; `harness`, the player itself (an exception that is no `gh`
# error, a fixture or body missing, a group or a result missing, the
# callers' move, a `before` or a land that did not hold before the engine
# acted); `infrastructure`, GitHub failing or rate limited until the
# scenario's time ran out, a play job cancelled or past its timeout, a group
# that left no results, a run GitHub held or never started.
CLASSES = ("engine", "harness", "infrastructure")


def blocked(seen):
    """Whether what a poll saw is GitHub's doing, not the engine's (#843): a
    run on the head GitHub holds for approval, or a check that never
    started (`startup_failure`). Pure."""
    seen = seen or {}
    return bool(seen.get("held")) or "startup_failure" in (seen.get("checks") or {}).values()


def caller_pairs(root=ROOT, pack=None):
    """{caller's file name: its pairs} for the test repository's callers
    (#843), each file's `pairs` alone, so a run maps through the caller at
    its `path`. Pure but for reading the files."""
    out = {}
    for pattern in test_callers(test_pack(root) if pack is None else pack):
        for path in sorted(glob.glob(os.path.join(root, pattern))):
            out[os.path.basename(path)] = {p for p in pairs(root, (os.path.relpath(path, root),)) if p.rsplit(":", 1)[1] not in UNPLAYABLE}
    return out


def run_triggered(runs, sid, titles, branches, wired, start, end):
    """The pairs the runs of the test repository (as the runs API lists
    them: path, event, display_title, head_branch, created_at) triggered
    for the scenario `sid` (#843): those created between `start` and `end`
    (ISO times) that belong to it (a title that ends with `[<sid>]` or is
    one of `titles`, the pull requests it observed, or a head branch among
    `branches`, its own and theirs), each through the caller at its `path`
    (`wired`, `caller_pairs`) and its event. Sorted. Pure."""
    out = set()
    for r in runs:
        if not isinstance(r, dict):
            continue
        at = str(r.get("created_at") or "")
        if at and not (start <= at <= end):
            continue
        title, branch = str(r.get("display_title") or ""), str(r.get("head_branch") or "")
        if not (title.endswith(f"[{sid}]") or title in titles or branch in branches):
            continue
        name, event = os.path.basename(str(r.get("path") or "").split("@", 1)[0]), str(r.get("event") or "")
        out |= {p for p in wired.get(name, ()) if p.rsplit(":", 1)[1] == event}
    return sorted(out)


def run_coverage(rows, wanted):
    """The workflow pairs of `wanted` no row triggered (#843): counted from
    each row's `triggered`, what its runs did, never its `covers:`, which
    stays its plan (`coverage`). A transition or a step of the flow is no
    workflow pair, and is never named here. Sorted. Pure."""
    done = {p for r in rows if isinstance(r, dict) for p in r.get("triggered") or []}
    return sorted(w for w in wanted if not str(w).startswith(STATIC) and w not in done)


def runs_json(text):
    """The items of `gh api --paginate --jq` output, one JSON array per
    page: every page's, joined. Pure."""
    out, at, decoder = [], 0, json.JSONDecoder()
    text = text or ""
    while True:
        while at < len(text) and text[at].isspace():
            at += 1
        if at >= len(text):
            return out
        value, at = decoder.raw_decode(text, at)
        out.extend(value if isinstance(value, list) else [value])


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def play(s, repo, ref, bodies, run=gh, sleep=time.sleep, minutes=20, fork=None, types=None, run_id=None, wired=None):
    """`_play`, and then, once (#843), the runs of `repo` created since it
    started that belong to it, in its row's `triggered` (`run_triggered`,
    through `wired`, `caller_pairs` when None); a read that fails leaves
    no `triggered`, never a failure."""
    start, seen = now_iso(), {"titles": set(), "branches": {branch_of(s)}}
    row = _play(s, repo, ref, bodies, run, sleep, minutes, fork, types, run_id, seen)
    if seen.get("tidy") is not None:
        # #878: its cleanup failed: GitHub's when transient, else the
        # player's.
        e = seen["tidy"]
        row = {"id": s["id"], "ok": False, "why": list(row.get("why") or []) + [f"its cleanup failed: {e}"], "run": row.get("run", ""),
               "class": "infrastructure" if transient(e) else "harness"}
    end = now_iso()
    try:
        runs = runs_json(run("api", "--paginate", f"repos/{repo}/actions/runs?created=>={start}&per_page=100",
                             "--jq", "[.workflow_runs[] | {path, event, display_title, head_branch, created_at}]"))
        row["triggered"] = run_triggered(runs, s["id"], seen["titles"], seen["branches"], caller_pairs() if wired is None else wired, start, end)
    except (RuntimeError, ValueError, OSError):
        pass
    return row


def _play(s, repo, ref, bodies, run=gh, sleep=time.sleep, minutes=20, fork=None, types=None, run_id=None, observed=None):
    """One scenario in `repo`: clears what an earlier run of it left
    (`clear`), opens what it opens (its `before` first), takes its steps,
    polls until its `expect` holds or `minutes` pass, then cleans up and
    clears again. Every file it writes carries `run_id` (`run_mark` when
    None, #778: `scenario_text`) but a `before`'s, which says its `says`.
    Returns {id, ok, why, run}."""
    run_id = run_id or run_mark()
    opens, made, closes = s.get("opens") or {}, [], None
    what = "pr" if "pull" in opens else "issue"
    spec = opens.get("pull") or opens.get("issue") or {}
    sid, own = s["id"], branch_of(s)
    left = [min(minutes, limit(s)) * 60]
    # #843: set once `look` ran out of time with `gh` still failing.
    gone = [False]

    def failed(why, url, cls="engine", seen=None):
        """A failing row of its class: GitHub's (`infrastructure`) whatever
        the step when `gh` kept failing or a run was held or never
        started."""
        if gone[0] or blocked(seen):
            cls = "infrastructure"
        return {"id": sid, "ok": False, "why": why, "run": url, "class": cls}

    def look(on, want=None, closes=None):
        """`on` observed, a transient `gh` error (#698: a rate limit, a
        5xx) retried after its back-off within the scenario's time, never a
        failure at once: (what was seen, None), or (None, why) once its time
        ran out with `gh` still failing. The runs on a pull request's head
        only when `want` reads them (`heads`, #699), and its label events,
        and its pull request's, when `want` reads them (`EVENT_KEYS`) and
        the rest of it holds."""
        tries = 0
        rest = {k: v for k, v in (want or {}).items() if k not in EVENT_KEYS}
        while True:
            try:
                seen = observe(repo, on[0], on[1], run, heads(want))
                pull = seen.get("pull") or {}
                if observed is not None:
                    # #843: the pull requests it observed, whose runs are its.
                    observed["titles"] |= {str(pull["title"])} if pull.get("title") else set()
                    observed["branches"] |= {str(pull["branch"])} if pull.get("branch") else set()
                if closes:
                    seen["closes"] = closes
                if rest != (want or {}) and not holds(rest, seen):
                    pull = (seen.get("pull") or {}).get("number")
                    seen["label_events"] = label_events(repo, [on[1]] + ([str(pull)] if on[0] == "issue" and pull else []), run)
                return seen, None
            except GhError as e:
                if not transient(e):
                    raise
                if left[0] <= 0:
                    gone[0] = True
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
            seen, failing = look(on, expect, closes)
            if failing:
                return last, [failing]
            last = seen
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
        write_file(repo, branch, path, scenario_text(sid, arg, "main", run_id) if content is None else content, run)
        body = pull_text(body_of("pull", bodies) if "{issue}" in body_of("pull", bodies) else "{files}\n\nCloses #{issue}", n, [path])
        got = run("pr", "create", "--repo", repo, "--head", branch, "--title", f"docs: the scenario {sid} lands {arg} on main",
                  "--body-file", "-", input=marked(body, sid)).strip()
        made.append(("pr", got.rstrip("/").rsplit("/", 1)[-1]))
        seen, why = poll({"merged": True}, ("pr", made[-1][1]), None)
        return [f"push {arg}: its pull request to main {got}: {w}" for w in why]
    lands = [str(b["lands"]) for b in s.get("before") or [] if "lands" in b]
    befores = []
    try:
        clear(repo, sid, run, own, lands, sleep)
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
                        return failed([w.replace("push ", "before: lands ", 1) for w in why], "", "harness")
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
            # #760: its description names every file of its diff.
            text = pull_text(text, closes, pull_files(s))
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
            write_file(target, branch, f"scenarios/{sid}/pull.md", scenario_text(sid, "pull", "the pull request", run_id), writes)
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
            elif verb == "retitle":
                # #699: the title of the pull request it observes (an
                # issue's, the autopilot's), as a person would edit it.
                target = number
                if what == "issue":
                    seen, failing = look((what, number))
                    target = ((seen or {}).get("pull") or {}).get("number")
                    if not target:
                        return failed([failing or f"retitle: no pull request closes #{number} to retitle"], (seen or {}).get("run", ""), seen=seen)
                run("pr", "edit", str(target), "--repo", repo, "--title", str(arg))
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
                            return failed([failing or f"push {arg}: no pull request closes #{number} to push to"], (seen or {}).get("run", ""), seen=seen)
                    write_file(repo, head, path, scenario_text(sid, arg, "the pull request", run_id), run)
                if arg in LANDS:
                    why = land(arg, path)
                    if why:
                        # A land is the scenario's own setup (#843).
                        return failed(why, "", "harness")
            elif verb == "until":
                # #694: polled every POLL seconds, never a fixed wait: on
                # the scenario's own issue or pull request, or with `of:
                # before` on the first issue it opened before it.
                want = {k: v for k, v in (arg or {}).items() if k != "of"}
                on = (("issue", befores[0]) if (arg or {}).get("of") == "before" and befores else (what, number))
                seen, why = poll(want, on, None if on[1] != number else closes)
                if why:
                    return failed([f"until {json.dumps(want, sort_keys=True)}: {w}" for w in why], seen.get("run", ""), seen=seen)
            elif verb == "wait":
                # Refused by `timing`; never slept.
                raise ValueError(f"a fixed wait of {arg} seconds: wait `until` a state")
        seen, why = poll(s.get("expect") or {}, (what, number), closes)
        if why:
            return failed(why, seen.get("run", ""), seen=seen)
        return {"id": sid, "ok": True, "why": [], "run": seen.get("run", "")}
    except (RuntimeError, ValueError) as e:
        # #843: a transient `gh` error is GitHub's; any other exception
        # that is no `gh` error, the player's; another `gh` error is read
        # as the engine's, so no failure is hidden as someone else's.
        cls = "infrastructure" if transient(e) else "engine" if isinstance(e, GhError) else "harness"
        return failed([str(e)], "", cls)
    finally:
        # #878: an error that escapes the cleanup kills no process: `play`
        # makes it a failing row.
        try:
            cleanup(repo, made, run, sleep)
            clear(repo, sid, run, own, lands, sleep)
        except Exception as e:  # noqa: BLE001 - any error, a row
            if observed is None:
                raise
            observed["tidy"] = e


def bot_login(login):
    """Whether `login` is the organisation's App, as either API names it
    (dilux-bot, dilux-bot[bot], app/dilux-bot)."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import org
    name = str(login or "").removeprefix("app/").removesuffix("[bot]")
    return bool(name) and name in {str(org.APP), str(org.BOT).removesuffix("[bot]")}


def observe(repo, what, number, run=gh, head_runs=True):
    """What a poll sees of the issue or pull request `number`: its labels,
    comments, state and, for a pull request (its own, or the one that closes
    the issue), its body, branch, title, whether it is a draft and whom its
    board says it waits on (#699); with `head_runs`, the runs on its head:
    those GitHub holds (#709) and whether one ran again (#699: `rerun`)."""
    fields = "labels,comments,body,state" + (",mergedAt,statusCheckRollup,headRefName,headRefOid,title,isDraft" if what == "pr" else ",closedByPullRequestsReferences")
    # A `gh` that fails raises GhError; `play` retries a transient one.
    view = json.loads(run(what, "view", number, "--repo", repo, "--json", fields) or "{}")
    seen = {"number": number, "labels": [l.get("name") for l in view.get("labels") or []],
            "comments": [c.get("body", "") for c in view.get("comments") or []], "state": view.get("state"),
            # The bot's own comments, oldest first (#707: `saw`).
            "said": [c.get("body", "") for c in view.get("comments") or [] if bot_login((c.get("author") or {}).get("login"))]}
    if what == "pr":
        seen["pull"] = {"body": view.get("body"), "branch": view.get("headRefName"), "title": view.get("title"), "number": number,
                        "draft": bool(view.get("isDraft")), "waits": waits_role(seen["said"])}
        seen["merged"] = bool(view.get("mergedAt"))
        seen["checks"] = {c.get("name"): (c.get("conclusion") or "").lower() for c in view.get("statusCheckRollup") or []}
        # #709: a run on its head that GitHub holds for a maintainer's
        # approval (a fork's): it never reports until a person allows it.
        seen["held"], seen["rerun"] = [], False
        if view.get("headRefOid") and head_runs:
            head = json.loads(run("run", "list", "--repo", repo, "--commit", str(view["headRefOid"]), "--json", "url,status,conclusion,attempt") or "[]")
            seen["held"] = [str(r.get("url") or "") for r in head if "action_required" in (str(r.get("status") or "").lower(), str(r.get("conclusion") or "").lower())]
            # #699 C5: a run on the same head that ran again (a re-run).
            seen["rerun"] = any(int(r.get("attempt") or 1) > 1 for r in head)
    else:
        # #698: the pull request that closes it, from the issue's own
        # references (the newest), never a search per poll: the search API
        # allows 30 a minute, which every scenario at once shares.
        refs = closing_pulls(repo, view)
        if refs:
            pull = json.loads(run("pr", "view", str(max(refs)), "--repo", repo, "--json", "number,body,headRefName,title,isDraft,comments") or "{}")
            said = [c.get("body", "") for c in pull.get("comments") or [] if bot_login((c.get("author") or {}).get("login"))]
            seen["pull"] = {"body": pull.get("body"), "branch": pull.get("headRefName"), "title": pull.get("title"), "number": pull.get("number"),
                            "draft": bool(pull.get("isDraft")), "waits": waits_role(said)}
    # #802: the autopilot's question waits on the item's board (`asked`).
    seen["waiting"] = any(l in seen["labels"] for l in ("needs-human", "awaiting-acceptance")) or bool(board_state(seen["said"]).get("asked"))
    runs = json.loads(run("run", "list", "--repo", repo, "--limit", "20", "--json", "url,status") or "[]")
    seen["run"] = runs[0]["url"] if runs else ""
    # Nothing queued or in progress in the test repository (#694: `hopeless`).
    seen["idle"] = not any(str(r.get("status") or "").lower() in RUNNING for r in runs)
    return seen


def waits_role(said):
    """Whom the pull request's board, among the bot's comments `said`, says
    it waits on (#699: its `waits`' role, scripts/waiting.py), or ""."""
    waits = board_state(said).get("waits")
    return str(waits.get("role") or "") if isinstance(waits, dict) else ""


def label_events(repo, numbers, run=gh):
    """The label events of the issues or pull requests `numbers` (#699),
    oldest first: [{event, label, actor, bot, person}], `bot` when
    dilux-bot moved it, `person` when no bot did (`person_actor`)."""
    out = []
    for n in numbers:
        text = run("api", f"repos/{repo}/issues/{n}/events", "--paginate", "--jq",
                   '.[] | select(.event == "labeled" or .event == "unlabeled") | {event, label: .label.name, actor: .actor.login, type: .actor.type}') or ""
        for line in text.splitlines():
            got = json.loads(line) if line.strip() else []
            for e in got if isinstance(got, list) else [got]:
                if isinstance(e, dict):
                    out.append({**e, "bot": bot_login(e.get("actor")), "person": person_actor(e.get("actor"), e.get("type"))})
    return out


def person_actor(login, kind=None):
    """Whether the actor `login` (of GitHub's `type` `kind`) is a person
    (#699): no bot of any App (dilux-bot, github-actions[bot], app/x,
    a `Bot` type). Pure."""
    name = str(login or "")
    if not name or str(kind or "") == "Bot" or name.endswith("[bot]") or name.startswith("app/") or bot_login(name):
        return False
    return True


def board_state(said):
    """The state on the bot's board among its comments `said` (#802,
    scripts/receipts.py parse_state); {} with none, or one edited by hand."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("receipts_board", os.path.join(HERE, "receipts.py"))
    receipts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(receipts)
    boards = [b for b in said or [] if str(b).startswith(receipts.BOARD)]
    state, intact = receipts.parse_state(boards[-1]) if boards else ({}, True)
    return state if intact else {}


def closing_pulls(repo, view):
    """The numbers of the pull requests in `repo` that close the issue
    `view` (its `closedByPullRequestsReferences`); one in another
    repository is never one of them. Pure."""
    found = (view.get("closedByPullRequestsReferences") if isinstance(view, dict) else None) or []
    refs = [r.get("number") for r in found if isinstance(r, dict)
            and f"github.com/{repo}/pull/".lower() in str(r.get("url") or f"github.com/{repo}/pull/").lower()]
    return [r for r in refs if isinstance(r, int)]


def cleanup(repo, made, run=gh, sleep=time.sleep):
    """`cleanup: after-run`: its issues closed and locked, its pull requests
    closed and their branches deleted, and so are the pull requests that
    close its issues (#784: the autopilot's, which carry no `dx-scenario`
    mark for `clear` to find, and which the next run's core scenario would
    wait on). A failure here never hides a result. A pull request in the
    merge queue is closed once it leaves it, and not at all once it merged
    or is still there when the wait runs out (`closer`, #936, #997). The issues the engine opened from its issues (#985:
    the reproduced bug's lane issue, `lane_of`) are handled the same way,
    their pull requests first, before the scenario's own issue."""
    close = closer(repo, run, sleep)
    for what, number in made:
        if what != "issue":
            close(number)
            continue
        # #985: the lane issue the reproduction opened from this one, and
        # the autopilot's pull request that closes it.
        for lane in lane_of(repo, number, run):
            close_issue(repo, lane, run, close)
        # #784: the pull requests that say `Closes #<issue>` for an issue
        # the scenario opened are the scenario's own.
        close_issue(repo, number, run, close)


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


def lane_title(ref, back=False):
    """The title of the lane's callers pull request (and so of its squashed
    commit, with ` (#N)`). Pure."""
    return f"ci: the engine's callers {'back from' if back else 'at'} {ref}"


def before_lane(repo, name, ref, base, run=gh):
    """The text caller `name` had before the last merged lane pull request
    that moved it to `ref` (#929): the parent of the newest commit of
    `base` that touched it titled `lane_title(ref)`, read at that commit.
    None when there is none (it is at `ref` by a person's hand)."""
    from urllib.parse import quote
    path = f".github/workflows/{name}"
    title = re.compile(re.escape(lane_title(ref)) + r"( \(#\d+\))?$")
    for c in json.loads(run("api", f"repos/{repo}/commits?sha={quote(base)}&path={quote(path)}&per_page=30") or "[]"):
        first = str(((c or {}).get("commit") or {}).get("message") or "").split("\n", 1)[0]
        parents = (c or {}).get("parents") or []
        if title.match(first) and parents:
            return text_at(repo, path, parents[0]["sha"], run)
    return None


def leftovers(repo, ref, at, run=gh, central=None, base=None):
    """The callers a lane left at `ref` (#929: a `back` that failed, a run
    killed while moving them), so `back` puts them where the lane found
    them: [{name, before}] of each caller in `at` ({name: text}, every
    engine call already at `ref`) whose text before the lane's pull request
    (`before_lane`) differs."""
    if not at:
        return []
    base = base or run("api", f"repos/{repo}", "--jq", ".default_branch").strip()
    out = []
    for name, text in at.items():
        prior = before_lane(repo, name, ref, base, run)
        if prior is not None and prior != text:
            out.append({"name": name, "before": prior})
    return out


def wait_merged(repo, number, url, run=gh, sleep=time.sleep, minutes=20):
    """The callers pull request another job opened (#929), waited for until
    it merged, never queued nor closed here: that job queues it. Raises,
    naming it, when it closes unmerged or `minutes` run out."""
    waited = 0
    while True:
        view = json.loads(run("pr", "view", number, "--repo", repo, "--json", "mergedAt,state") or "{}")
        if view.get("mergedAt"):
            return
        if view.get("state") == "CLOSED":
            raise RuntimeError(f"the pull request {url} that moves them, opened by another job, closed unmerged")
        if waited >= minutes * 60:
            raise RuntimeError(f"the pull request {url} that moves them, opened by another job, did not merge in {minutes} minutes")
        sleep(POLL)
        waited += POLL


# How many polls a callers branch with no pull request and the same head is
# another job's before it is a leftover to delete (#929).
STALE = 2


def point_callers(repo, ref, run=gh, central=None, back=None, sleep=time.sleep, minutes=20):
    """The test repository's callers at `ref` (`v7-next` while the lane
    tries a candidate, `v7` once the installer plays them), so what plays
    is that ref's engine; with `back` ({name: text}), those callers put back
    as they were. Never written on the default branch, which its rulesets
    protect: the change goes on `ci/callers-<ref>`, through a pull request
    the lane merges itself (`merge_when_checked`: the merge queue, once its
    checks pass; auto-merge never merges a change to .github/workflows),
    and it returns once that merged. Nothing to change opens nothing. Returns what it moved,
    each caller's `name` and its text `before`. Safe to call twice at once
    (#929: the play jobs of a re-run each move the callers again): when
    `ci/callers-<ref>` already has an open pull request, or its branch
    already exists (creating it is the lock), it waits for that one to
    merge (`wait_merged`) instead of deleting its branch, then reads the
    callers again; a branch with no pull request whose head stays the same
    for `STALE` polls is a leftover, deleted and made anew. Every caller it finds already at `ref` is
    returned too, with the text it had before the lane's pull request that
    moved it there (#929, `leftovers`), so `back` puts back the ref from
    before any lane."""
    import base64
    if central is None:
        sys.path.insert(0, HERE)
        import org
        central = org.CENTRAL
    branch = f"ci/callers-{ref}" + ("-back" if back is not None else "")

    at = {}

    def read():
        changes = []
        at.clear()
        for f in json.loads(run("api", f"repos/{repo}/contents/.github/workflows") or "[]"):
            name = str(f.get("name", ""))
            if not name.endswith(".yml") or (back is not None and name not in back):
                continue
            got = json.loads(run("api", f"repos/{repo}/contents/.github/workflows/{name}") or "{}")
            text = base64.b64decode(got.get("content") or "").decode()
            new = back[name] if back is not None else at_ref(text, central, ref)
            if new != text:
                changes.append((name, text, new))
            elif back is None and engine_calls(text, central) and not off_ref(text, central, ref):
                at[name] = text
        return changes
    changes = read()
    if not changes:
        return [] if back is not None else leftovers(repo, ref, at, run, central)
    base = run("api", f"repos/{repo}", "--jq", ".default_branch").strip()

    def branch_head():
        try:
            return run("api", f"repos/{repo}/git/ref/heads/{branch}", "--jq", ".object.sha").strip()
        except RuntimeError:
            return None  # gone: a 404
    # Creating the branch is the lock (#929): two play jobs of a re-run may
    # both find no pull request open, and only one creates the branch. The
    # other's 422 "Reference already exists" means another job started (its
    # pull request soon open: waited for, never a second) or a leftover of
    # a run that died. A branch is deleted only once it is stale: no pull
    # request and the same head for `STALE` polls.
    seen, waited, total = None, 0, 0
    while True:
        opened = json.loads(run("pr", "list", "--repo", repo, "--head", branch, "--state", "open", "--json", "number,url") or "[]")
        if opened:
            wait_merged(repo, str(opened[0]["number"]), str(opened[0].get("url") or opened[0]["number"]), run, sleep, minutes)
            changes = read()
            if not changes:
                return leftovers(repo, ref, at, run, central)
            seen, waited = None, 0
        if seen is None:
            head = run("api", f"repos/{repo}/git/ref/heads/{base}", "--jq", ".object.sha").strip()
            try:
                run("api", f"repos/{repo}/git/refs", "-f", f"ref=refs/heads/{branch}", "-f", f"sha={head}")
                break
            except RuntimeError as e:
                if not re.search(r"Reference already exists", f"{e} {getattr(e, 'stderr', '')}", re.I):
                    raise
            seen, waited = branch_head() or "", 0
        else:
            now = branch_head()
            if now is None:
                seen = None
                continue
            if now != seen:
                seen, waited = now, 0
            elif waited >= STALE * POLL:
                try:
                    run("api", "-X", "DELETE", f"repos/{repo}/git/refs/heads/{branch}")
                except RuntimeError:
                    pass  # gone already
                seen = None
                continue
        if total >= minutes * 60:
            raise RuntimeError(f"the branch {branch} that moves them was held by another job for {minutes} minutes, with no pull request")
        sleep(POLL)
        waited += POLL
        total += POLL
    title = lane_title(ref, back is not None)
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
    return [{"name": name, "before": text} for name, text, _ in changes] + (leftovers(repo, ref, at, run, central, base) if back is None else [])


def recorded_callers(repo, ref, run=gh, central=None):
    """What `back` must put back when no caller moves (#929, `move
    --record-only`): the callers a lane left at `ref` (`leftovers`)."""
    import base64
    central = central or central_of()
    at = {}
    for f in json.loads(run("api", f"repos/{repo}/contents/.github/workflows") or "[]"):
        name = str(f.get("name", ""))
        if not name.endswith(".yml"):
            continue
        got = json.loads(run("api", f"repos/{repo}/contents/.github/workflows/{name}") or "{}")
        text = base64.b64decode(got.get("content") or "").decode()
        if engine_calls(text, central) and not off_ref(text, central, ref):
            at[name] = text
    return leftovers(repo, ref, at, run, central)


def put_back(repo, ref, moved, callers=gh, central=None, sleep=time.sleep, minutes=20):
    """The callers `point_callers` moved (`moved`) put back from `ref`,
    through another merged pull request: [] once they are, else one failing
    `callers` row that says why."""
    if not moved:
        return []
    try:
        point_callers(repo, ref, callers, central, back={m["name"]: m["before"] for m in moved}, sleep=sleep, minutes=minutes)
    except (RuntimeError, ValueError) as e:
        return [{"id": "callers", "ok": False, "why": [f"the callers were not put back from {ref}: {e}"], "run": "", "class": "harness"}]
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
        return [], [{"id": "callers", "ok": False, "why": [f"could not read what moved to {ref}, the callers may be left there: {e}"], "run": "", "class": "harness"}]


def read_moved_dir(path, ref):
    """What every attempt's move recorded under `path` (#929: one directory
    per artifact, `scenarios-move-a<N>/moved.json`, or a moved.json there),
    each caller once, as the earliest attempt that recorded it found it,
    and the rows that say why none could be read (`read_moved`)."""
    found = []
    for d in sorted(os.listdir(path)) if os.path.isdir(path) else []:
        m = ATTEMPT.match(d)
        if m and m.group(1) == "move" and os.path.exists(os.path.join(path, d, "moved.json")):
            found.append((int(m.group(2) or 0), os.path.join(path, d, "moved.json")))
    if not found:
        return read_moved(os.path.join(path, "moved.json"), ref)
    moved, names = [], set()
    for _, f in sorted(found):
        got, rows = read_moved(f, ref)
        if rows:
            return [], rows
        for m in got:
            if m["name"] not in names:
                moved.append(m)
                names.add(m["name"])
    return moved, []


def at_candidate(repo, ref, run=gh, central=None):
    """What would still run a pipeline of the test repository off `ref` once
    its callers moved (#748), as failing `callers` rows, each naming it: its
    default branch's rules (`repos/{repo}/rules/branches/{default}`) still
    carrying a `workflows` rule for org-pull-request.yml (the required
    workflow, at `v7` with its calls hard-wired), and any
    .github/workflows/*.yml there that still calls the engine off `ref`."""
    import base64
    if central is None:
        central = central_of()
    why = []
    base = run("api", f"repos/{repo}", "--jq", ".default_branch").strip()
    pages = json.loads(run("api", "--paginate", "--slurp", f"repos/{repo}/rules/branches/{base}?per_page=100") or "[]")
    rules = [r for page in pages for r in (page if isinstance(page, list) else [page])] if isinstance(pages, list) else []
    for r in rules:
        for w in ((r.get("parameters") or {}).get("workflows") or []) if r.get("type") == "workflows" else []:
            if os.path.basename(str(w.get("path") or "")) == os.path.basename(REQUIRED):
                why.append(f"{repo}'s {base} still requires {REQUIRED} (a `workflows` rule of {r.get('ruleset_source') or 'a ruleset'}): its pull requests "
                           f"run the pipeline at `v7`, not {ref}; `sync-repos.py rulesets` leaves it out once it has test-pull-request.yml")
    for f in json.loads(run("api", f"repos/{repo}/contents/.github/workflows") or "[]"):
        name = str(f.get("name", ""))
        if not name.endswith(".yml"):
            continue
        got = json.loads(run("api", f"repos/{repo}/contents/.github/workflows/{name}") or "{}")
        for line in off_ref(base64.b64decode(got.get("content") or "").decode(), central, ref):
            why.append(f".github/workflows/{name} {line}: calls the engine off {ref} after the move")
    return [{"id": "callers", "ok": False, "why": [w], "run": "", "class": "harness"} for w in why]


def move_callers(repo, ref, callers=gh, central=None, sleep=time.sleep, minutes=20, record=None):
    """The test repository's callers moved to `ref` (`point_callers`):
    (what moved, []) once they are and nothing would run a pipeline there
    off `ref` (`at_candidate`, #748), else (what moved, the failing
    `callers` rows that say why; [] moved when the pointing failed).
    `record`, when given, is called with what moved as soon as the
    pointing is over ([] when it failed cleanly)."""
    try:
        moved = point_callers(repo, ref, callers, central, sleep=sleep, minutes=minutes)
    except (RuntimeError, ValueError) as e:
        if record:
            record([])
        return [], [{"id": "callers", "ok": False, "why": [f"the callers did not reach {ref}: {e}"], "run": "", "class": "harness"}]
    if record:
        record(moved)
    try:
        return moved, at_candidate(repo, ref, callers, central)
    except (RuntimeError, ValueError) as e:
        return moved, [{"id": "callers", "ok": False, "why": [f"could not tell whether every pipeline of {repo} runs at {ref}: {e}"], "run": "", "class": "harness"}]


GROUP_ID = re.compile(r"[a-z0-9-]+")
# The artifacts the lane names after them besides the groups' (scenarios-*).
NOT_GROUPS = ("move", "back", "results")
# The attempt an artifact's name ends with (#929): scenarios-<name>-a<N>.
ATTEMPT = re.compile(r"^scenarios-(.+?)(?:-a(\d+))?$")


def unfit_group(gid):
    """Why a group id cannot name an artifact the lane reads back (#929):
    "" when it can. One that ends like an attempt (`-a<N>`) or starts like
    another artifact (`move-`, `back-`, `results-`) would be read as
    another. Pure."""
    if not isinstance(gid, str) or not GROUP_ID.fullmatch(gid) or gid in NOT_GROUPS:
        return f"not ^[a-z0-9-]+$, or {' or '.join(NOT_GROUPS)}"
    if re.search(r"-a\d+$", gid) or any(gid.startswith(f"{n}-") for n in NOT_GROUPS):
        return f"it ends with -a<N>, an attempt, or starts with {', '.join(n + '-' for n in NOT_GROUPS)}"
    return ""


def groups(scenarios):
    """The groups the lane plays at once, one job each (release-lane.yml
    `play`): every scenario in its own, named by its id (#694: each writes
    under its own directory, `core_writes`, so none waits on another). [{id,
    scenarios}]. Pure."""
    return [{"id": s.get("id"), "scenarios": [s.get("id")]} for s in scenarios]


def drop_passed(gs, passed):
    """The groups `gs` with the scenarios of `passed` ([{id, in}], #929:
    what passed on the same candidate) dropped, then any group left empty.
    Pure."""
    done = {p.get("id") for p in passed or [] if isinstance(p, dict)}
    left = [dict(g, scenarios=[sid for sid in g["scenarios"] if sid not in done]) for g in gs]
    return [g for g in left if g["scenarios"]]


# The artifact a lane's act job leaves (#929): its merged table, and the key
# of the candidate it tried (main's sha, `v7-next`'s), in key.json.
RESULTS = "scenarios-results"
# How many of the lane's earlier runs `earlier_passes` reads, newest first.
EARLIER_RUNS = 10


def passes_of(rows, ids, url):
    """[{id, in}] of the scenarios among `ids` whose row in `rows` passed:
    each in the run it first passed in (its own `in`, else `url`). Pure."""
    out = []
    for r in rows:
        if isinstance(r, dict) and r.get("ok") is True and r.get("id") in ids and r["id"] not in {p["id"] for p in out}:
            out.append({"id": r["id"], "in": str(r.get("in") or url)})
    return out


# The events a run of the lane on main's own code comes from: a run on
# another event or branch (a dispatch from a branch whose release-lane.yml
# was changed) may have uploaded anything, so its passes never count.
LANE_EVENTS = ("workflow_run", "workflow_dispatch")


def main_run(r, repo, branch="main"):
    """Whether run `r` (the API's) is the lane on `repo`'s own `branch`.
    Pure."""
    head = (r.get("head_repository") or {}).get("full_name")
    return r.get("event") in LANE_EVENTS and r.get("head_branch") == branch and head in (None, repo)


def earlier_passes(repo, sha, nxt, run_id, ids, run=gh, limit=EARLIER_RUNS):
    """What passed on this candidate before (#929): the completed earlier
    runs of release-lane.yml in `repo` (not `run_id`), newest first, read
    until the first whose `scenarios-results` has the key (`sha`, `nxt`),
    and its passing rows of the scenarios `ids` (`passes_of`); a run of
    another event, branch or repository is never read (`main_run`). [] when
    none matches, or when the key is not whole: a new candidate plays
    everything. A run with no such artifact is skipped."""
    import tempfile
    if not sha or not nxt:
        return []
    got = json.loads(run("api", f"repos/{repo}/actions/workflows/release-lane.yml/runs?status=completed&per_page={limit + 1}") or "{}")
    runs = [r for r in (got.get("workflow_runs") or []) if str(r.get("id")) != str(run_id) and main_run(r, repo)][:limit]
    for r in runs:
        with tempfile.TemporaryDirectory() as d:
            try:
                run("run", "download", str(r["id"]), "--repo", repo, "--name", RESULTS, "--dir", d)
                with open(os.path.join(d, "key.json"), encoding="utf-8") as fh:
                    key = json.load(fh)
            except (RuntimeError, OSError, ValueError):
                continue
            if not isinstance(key, dict) or (key.get("sha"), key.get("next")) != (sha, nxt):
                continue
            return passes_of(read_results(os.path.join(d, "results.md")), set(ids), str(r.get("html_url") or r["id"]))
    return []


def read_passed(path):
    """The [{id, in}] `passed` wrote to `path`; [] when none."""
    try:
        with open(path, encoding="utf-8") as fh:
            got = json.load(fh)
    except (OSError, ValueError):
        return []
    return [p for p in got if isinstance(p, dict) and isinstance(p.get("id"), str) and isinstance(p.get("in"), str)] if isinstance(got, list) else []


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
    unfit for an artifact name (`unfit_group`: `^[a-z0-9-]+$`, nor `move`, `back` or `results`, nor read as an attempt's) or used
    twice, and (#694) two scenarios that could write to the same part of the
    test repository's core (`pack`'s, scripts/org.py core_key), which would
    wait on each other's change, and (#709) any that writes under it but
    expects no wait on it (`core_problems`). Pure."""
    out, where, ids = [], {}, [s.get("id") or "?" for s in scenarios]
    seen = set()
    for g in gs:
        gid = str(g.get("id"))
        if unfit_group(gid):
            out.append(f"group {gid}: its id is unfit for an artifact name (^[a-z0-9-]+$, nor {' or '.join(NOT_GROUPS)}: {unfit_group(gid)})")
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
    """Whether scenario `s` expects to wait on the core (its comment's
    mark). Pure."""
    expect = s.get("expect") or {}
    return CORE_MARK in (expect.get("comments") or [])


SEAL = "<!-- dx-prd-seal -->"


def needs_autopilot(want):
    """Whether the expectation `want`, on an issue, needs the autopilot's
    result (#713): its seal, the `autopilot` label, its comment on the
    core, or its pull request. Pure."""
    want = want or {}
    return (any(m in (want.get("comments") or []) for m in (SEAL, CORE_MARK))
            or "autopilot" in (want.get("labels") or []) or bool(want.get("pull")))


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


RISKS = ("low", "medium", "high")


def path_floor(path, high, low):
    """The floor scripts/policy.py gives a pull request that changes `path`
    alone: high when it matches `high`, low when it matches `low`, medium
    otherwise, with policy.py's own `matches` (#764). Pure."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import policy
    return "high" if policy.matches(path, high) else "low" if policy.matches(path, low) else "medium"


def risk_patterns(root=ROOT):
    """The high-risk and low-risk-eligible patterns a pull request of the
    test repository is weighed with (#764): the organisation's, and the
    kind engine-test's `high-risk` (kinds/engine-test/surface.yml)."""
    org = load_yaml(os.path.join(root, "policy", "review-policy.default.yml"))
    kind = load_yaml(os.path.join(root, "kinds", "engine-test", "surface.yml"))
    return (list(org.get("high-risk") or []) + list(kind.get("high-risk") or []), list(org.get("low-risk-eligible") or []))


def risk_problems(scenarios, high, low):
    """Every scenario that expects a `risk:<level>` label that no path it
    changes (`pull_files`) gets as its floor (`path_floor`, #764): the
    review's floor comes from the paths, so the label could never come from
    them. Pure."""
    out = []
    for s in scenarios:
        wants = [str(l).split(":", 1)[1] for l in ((s.get("expect") or {}).get("labels") or []) if str(l).startswith("risk:") and str(l).split(":", 1)[1] in RISKS]
        files = pull_files(s)
        floors = {f: path_floor(f, high, low) for f in files}
        for level in wants:
            if level not in floors.values():
                shown = ", ".join(f"{f} ({v})" for f, v in floors.items()) or "none"
                out.append(f"scenario {s.get('id') or '?'}: expects risk:{level}, but no path it changes has that floor for kind engine-test (its paths: {shown}); "
                           f"add the path to kinds/engine-test/surface.yml `high-risk`, or change the expectation")
    return out


def core_problems(scenarios, pack):
    """Every scenario that writes under the test repository's core (`pack`'s
    `core`) but expects no wait on it (#709): its fixed change would make its
    issue wait on another's open pull request (scripts/autopilot.py
    core_busy), so only the one scenario that expects the wait on the core
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


# The least minutes a retry leaves the play step for what is not its polls
# (#878): its clear, steps, cleanup and the read of its runs. The retry
# leaves the first attempt's own time for them when that is more.
RETRY_ALLOWANCE = 3
NOT_RETRIED = "not retried: no time left in the play step"


def retried(s, attempt, minutes, deadline=None, clock=None, slept=None):
    """The scenario `s` played by `attempt(minutes)`, and once more when it
    failed (#843): the retry is limited to `min(limit(s), minutes)` and,
    with a `deadline` (the player's end, on `clock`), to what is left of it
    less (#878) an allowance for what is not its polls, the first
    attempt's own time (its time on `clock` but what it slept, `slept`
    the seconds slept so far), RETRY_ALLOWANCE minutes at least, and one
    POLL its last poll may overrun by; with less than a minute it is not
    played, and the row says so. The row gains
    `attempts` (1 or 2) and, after a retry, `first_why` (the first
    attempt's why); `flaky: true` when the retry passed, which makes it
    `ok` with no `class`; failing on both, it keeps the first failure's
    `class`."""
    clock = clock or time.monotonic
    began, napped = (clock(), slept() if slept else 0) if deadline is not None else (0, 0)
    first = attempt(minutes)
    if first.get("ok"):
        return dict(first, attempts=1)
    budget = min(minutes, limit(s))
    if deadline is not None:
        now = clock()
        own = (now - began) - ((slept() - napped) if slept else 0)
        allowance = max(RETRY_ALLOWANCE * 60, own) + POLL
        budget = min(budget, (deadline - now - allowance) / 60)
    if budget < 1:
        return dict(first, attempts=1, why=list(first.get("why") or []) + [NOT_RETRIED])
    second = attempt(budget)
    out = dict(second, attempts=2, first_why=list(first.get("why") or []))
    if "triggered" in first or "triggered" in second:
        # #843: what either attempt's runs triggered.
        out["triggered"] = sorted(set(first.get("triggered") or []) | set(second.get("triggered") or []))
    # #843: the row's class comes from both attempts: passing on its retry
    # it is flaky and no failure's; failing on both, the first failure's.
    out.pop("class", None)
    if second.get("ok"):
        out["flaky"] = True
    elif first.get("class") or second.get("class"):
        out["class"] = first.get("class") or second.get("class")
    return out


# The row of a scenario the play step ended before (#878): what the group's
# file says until its attempt ends, and what a signal leaves.
ENDED = "the play step ended before the scenario did"


def ended(sid, why=()):
    """The failing `infrastructure` row of the scenario `sid` the play step
    ended before (#878, ENDED), after the `why` of an attempt that failed.
    Pure."""
    return {"id": sid, "ok": False, "why": list(why) + [ENDED], "run": "", "class": "infrastructure"}


def play_group(conf, gid, repo, ref, run=None, sleep=None, minutes=20, run_id=None, clock=None, record=None):
    """The scenarios of the group `gid` (one, #694), in its order, at
    `ref` (the callers already there), with the test identity's token (the
    ambient GH_TOKEN, `gh` when `run` is None): their rows, or one failing
    row when `gid` is no group. `minutes` is the player's own deadline, on
    `clock` (#878: below the play step's timeout, which release-lane.yml
    passes as `--minutes`): a scenario that failed is played once more
    within what is left of it (`retried`), and a transient `gh` error is
    retried within it (`patient`). `record`, when given, is called with
    the rows so far before the first attempt and after each, a scenario
    not played yet or still playing an `ended` row, so a step killed in the
    middle still leaves them. An error that escapes an attempt is its
    failing `harness` row, never the process's end."""
    sleep, clock = sleep or time.sleep, clock or time.monotonic
    scenarios = conf.get("scenarios") or []
    group = next((g for g in groups(scenarios) if g["id"] == gid), None)
    if group is None:
        return [{"id": gid, "ok": False, "why": [f"{gid} is no group of {SCENARIOS}"], "run": "", "class": "harness"}]
    by_id, run_id = {s.get("id"): s for s in scenarios}, run_id or run_mark()
    deadline = clock() + minutes * 60
    run = patient(gh if run is None else run, sleep, deadline, clock)
    slept = [0.0]

    def nap(seconds):
        slept[0] += seconds
        sleep(seconds)

    out = []

    def note(current=()):
        if record:
            done = {r["id"] for r in out} | {r["id"] for r in current}
            record(out + list(current) + [ended(sid) for sid in group["scenarios"] if sid not in done])

    note()
    for sid in group["scenarios"]:
        s = by_id[sid]

        def attempt(m, s=s):
            try:
                row = play(s, repo, ref, conf.get("bodies") or {}, run, nap, m, types=conf.get("types") or {}, run_id=run_id)
            except Exception as e:  # noqa: BLE001 - any error, a row
                row = {"id": s["id"], "ok": False, "why": [f"the player broke: {type(e).__name__}: {e}"], "run": "", "class": "harness"}
            note([row if row.get("ok") else ended(s["id"], row.get("why") or [])])
            return row

        out.append(retried(s, attempt, minutes, deadline, clock, lambda: slept[0]))
        note()
    return out


def play_watched(conf, gid, repo, ref, minutes, out):
    """`play_group` with its rows written to `out` before its first attempt
    and after each (#878), and again on a SIGTERM or SIGINT (GitHub signals
    a step past its timeout before it kills it), which then ends the
    process: a group always leaves its file. The handlers it set are put
    back. Its rows."""
    import signal
    rows = []

    def record(now):
        rows[:] = now
        if out:
            write_results(now, out, echo=False)

    def stop(signum, frame):
        if out:
            write_results(rows, out)
        raise SystemExit(128 + signum)

    before = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        return play_group(conf, gid, repo, ref, minutes=minutes, record=record)
    finally:
        for sig, handler in before.items():
            signal.signal(sig, handler)


def run_all(conf, repo, ref, only=(), run=gh, sleep=time.sleep, minutes=20, central=None, callers=None, moved_out=None, record=None, run_id=None):
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
        # What moved still goes back (#748: a pipeline off the ref plays no
        # scenario, but the callers did move).
        if moved_out is not None:
            moved_out.extend(moved)
            return rows
        return rows + put_back(repo, ref, moved, callers, central, sleep, minutes)
    if moved_out is not None:
        moved_out.extend(moved)
    results, run_id = [], run_id or run_mark()
    try:
        for s in conf.get("scenarios") or []:
            if not only or s["id"] in only:
                # #843: a failure is played once more (`retried`).
                results.append(retried(s, lambda m, s=s: play(s, repo, ref, bodies, run, sleep, m, types=conf.get("types") or {}, run_id=run_id), minutes))
    finally:
        if moved_out is None:
            results.extend(put_back(repo, ref, moved, callers, central, sleep, minutes))
    return results


def untriggered_line(missing):
    """The table's line naming the pairs no scenario's runs triggered
    (#843), a warning that fails nothing; "" when none. Pure."""
    return f"\nPairs no scenario triggered: {', '.join(f'`{p}`' for p in missing)}\n" if missing else ""


def write_results(results, out, untriggered=None, echo=True):
    """The table of `results` to stdout (but with `echo` false, #878: the
    rows a group writes while it plays), and to `out` with the record the
    lane's next job reads; with `untriggered` (#843, `run_coverage`), its
    line after the table and its own record, which release-lane.py act
    names as a warning."""
    text = table(results) + untriggered_line(untriggered)
    if echo:
        sys.stdout.write(text)
    if out:
        # The job's --out may name a directory no step made (#693).
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        # #878: whole or not at all, through a file of its own: a signal's
        # write never meets one it cut in the middle.
        import tempfile
        fd, part = tempfile.mkstemp(dir=os.path.dirname(out) or ".", prefix=".results-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.write(f"\n<!-- dx-scenarios {json.dumps(results)} -->\n")
                if untriggered:
                    fh.write(f"<!-- dx-untriggered {json.dumps(untriggered)} -->\n")
            os.replace(part, out)
        except BaseException:
            if os.path.exists(part):
                os.unlink(part)
            raise


def read_results(path):
    """The results `write_results` wrote to `path`; [] when there are none."""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return []
    m = re.search(r"<!-- dx-scenarios (.*) -->", text)
    return json.loads(m.group(1)) if m else []


def merge(gs, files, jobs, run="", minutes=0, play_minutes=0, passed=()):
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
    `passed` ([{id, in}], #929): a passing row, `in` its earlier run, for
    each scenario that passed on the same candidate and has no row here;
    with them, no groups left and a skipped play job fail nothing.
    Pure."""
    rows = []
    timeout = f" (its play step at {play_minutes} minutes, its job at {minutes}: timeout-minutes in release-lane.yml)" if minutes else ""

    def fail(rid, why, cls):
        rows.append({"id": rid, "ok": False, "why": [why], "run": run, "class": cls})

    def own(r, cls=None):
        out = {"id": str(r.get("id")), "ok": r.get("ok") is True, "why": [str(w) for w in r.get("why") or []], "run": str(r.get("run") or "")}
        # #843: a failing row's class, as its writer set it; a move's or a
        # back's row is the harness's.
        if not out["ok"]:
            c = r.get("class") if r.get("class") in CLASSES else cls
            if c:
                out["class"] = c
        # #843: the retry's keys, kept.
        if isinstance(r.get("attempts"), int):
            out["attempts"] = r["attempts"]
        if r.get("flaky") is True:
            out["flaky"] = True
        if isinstance(r.get("first_why"), list):
            out["first_why"] = [str(w) for w in r["first_why"]]
        if isinstance(r.get("triggered"), list):
            out["triggered"] = [str(p) for p in r["triggered"]]
        if out["ok"] and r.get("in"):
            out["in"] = str(r["in"])
        return out
    if files.get("move") is None:
        fail("move", "the move job left no results", "harness")
    else:
        rows += [own(r, "harness") for r in files["move"] if isinstance(r, dict)]
    passed = [p for p in passed or [] if isinstance(p, dict) and p.get("id")]
    if not gs and not passed:
        fail("groups", "no groups of scenarios to read: none played", "harness")
    first_group_row = len(rows)
    for g in gs:
        got = files.get(g["id"])
        if got is None:
            # A play job that was skipped is its own failing row below.
            if jobs.get("play") != "skipped":
                fail(g["id"], f"the group {g['id']} left no results: its play job failed before it wrote them, timed out{timeout} or was cancelled", "infrastructure")
            continue
        by_id = {}
        for r in got:
            if isinstance(r, dict) and r.get("id") in g["scenarios"]:
                by_id.setdefault(r["id"], own(r))
            elif isinstance(r, dict) and r.get("id") == "callers" and r.get("ok") is not True:
                # #929: a re-run play job's move of the callers that failed.
                rows.append(own(r, "harness"))
        for sid in g["scenarios"]:
            if sid in by_id:
                rows.append(by_id[sid])
            else:
                fail(sid, f"no result in the results of its group {g['id']}", "harness")
    group_failed = any(not r["ok"] for r in rows[first_group_row:])
    have = {r["id"] for r in rows}
    for p in passed:
        if p["id"] not in have:
            rows.append({"id": str(p["id"]), "ok": True, "why": [], "run": str(p.get("in") or ""), "in": str(p.get("in") or "")})
            have.add(p["id"])
    if files.get("back") is None:
        fail("back", "the back job left no results: the callers may be left at the ref", "harness")
    else:
        rows += [own(r, "harness") for r in files["back"] if isinstance(r, dict)]
    # #929: a play job fails when its group has a failing row, so the
    # re-run of the failed jobs replays it: that row is the failure, and a
    # failed play job adds none of its own then.
    for name, result in jobs.items():
        if result == "success" or (name == "play" and result == "skipped" and not gs and passed):
            continue
        if name == "play" and result == "failure" and group_failed:
            continue
        if name == "play" and minutes and result == "cancelled":
            fail(name, f"a play job ran past its timeout of {minutes} minutes and was cancelled (timeout-minutes in release-lane.yml)", "infrastructure")
        elif name == "play" and play_minutes and result == "failure":
            fail(name, f"a play job ended in failure: a step that broke, or its play step past its timeout of {play_minutes} minutes (timeout-minutes in release-lane.yml)", "infrastructure")
        else:
            fail(name, f"the {name} job ended in {result or 'nothing'}", "harness")
    return rows


def read_groups(text):
    """The groups the move job printed (`groups`), or [] when they cannot
    be read or a group id is unfit for an artifact name (it names a
    directory)."""
    try:
        gs = json.loads(text or "")
    except ValueError:
        return []
    ok = isinstance(gs, list) and all(isinstance(g, dict) and not unfit_group(g.get("id")) and isinstance(g.get("scenarios"), list) for g in gs)
    return gs if ok else []


def latest_attempts(path):
    """{name: directory} of the artifacts downloaded under `path`, each in
    its own directory, `scenarios-<name>-a<N>` (#929: a re-run's attempt
    over an earlier one's; one with no attempt is the first's), the
    latest attempt of each name kept."""
    best = {}
    for d in sorted(os.listdir(path)) if os.path.isdir(path) else []:
        m = ATTEMPT.match(d)
        if m and os.path.exists(os.path.join(path, d, "results.md")):
            n = int(m.group(2) or 0)
            if m.group(1) not in best or n >= best[m.group(1)][0]:
                best[m.group(1)] = (n, os.path.join(path, d))
    return {name: d for name, (_, d) in best.items()}


def merge_dir(path, gs, jobs, run="", minutes=0, play_minutes=0, passed=()):
    """`merge` of the artifacts downloaded under `path`, each in its own
    directory (`scenarios-<name>-a<N>/results.md`, the latest attempt of
    each, `latest_attempts`)."""
    files, found = {}, latest_attempts(path)
    for name in ["move", "back"] + [g["id"] for g in gs]:
        files[name] = read_results(os.path.join(found[name], "results.md")) if name in found else None
    return merge(gs, files, jobs, run, minutes, play_minutes, passed)


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
    a contents `PUT`, or a commit with no branch or the default one
    (`queued`'s read, #936, writes nothing). Pure."""
    out = []
    for args, given in calls:
        if tuple(args[:3]) == ("api", "-X", "PUT") and "/contents/" in str(args[3]):
            out.append(args)
        elif tuple(args[:2]) == ("api", "graphql") and not queue_read(args):
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


def stale_writes(writes, held, run_id):
    """The texts among `writes` (`commits`) under scenarios/ that would
    change nothing (#778): one some earlier state already `held` ({path:
    [texts]}: what the test repository's main held, another run's), so its
    pull request would have no diff, or one without `run_id`. Pure."""
    out = []
    for _, branch, _, files in writes:
        for path, text in files.items():
            if not path.startswith("scenarios/"):
                continue
            if text in (held.get(path) or ()):
                out.append(f"{branch}: {path} says what was there already: {text.strip()!r}")
            if run_id not in text:
                out.append(f"{branch}: {path} does not carry the run's id {run_id}: {text.strip()!r}")
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
            text = pull_text(body_of(opens["pull"].get("body"), bodies), "1", pull_files(s))
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


# The minutes the play step keeps past the player's deadline (#878): to
# write its results and exit before GitHub stops it.
PLAY_SPARE = 3


def lane_problems(lane):
    """What is wrong with the release lane's jobs (`lane`, release-lane.yml
    read; #707): a `play` job whose `runs-on` can name DX_RUNNER_HEAVY (or
    any self-hosted runner), where the test repository's own jobs run, so
    the play jobs that wait for them hold the runners they need; and (#878)
    a play step (its id `play`) that passes the player no `--minutes`, or
    one that leaves it less than PLAY_SPARE minutes of the step's
    timeout-minutes to write its results and exit. Pure."""
    play = ((lane or {}).get("jobs") or {}).get("play") or {}
    runs = json.dumps(play.get("runs-on"))
    if "DX_RUNNER_HEAVY" in runs or "self-hosted" in runs:
        return [f"{LANE}: the `play` job runs on {play.get('runs-on')}, where the test repository's own jobs run: "
                "its jobs that wait for them would hold those runners; it runs on ubuntu-latest"]
    step = next((s for s in play.get("steps") or [] if isinstance(s, dict) and s.get("id") == "play"), None)
    if step is None:
        return []
    m = re.search(r"--minutes\s+(\d+)", str(step.get("run") or ""))
    timeout = int(step.get("timeout-minutes") or 0)
    if not m:
        return [f"{LANE}: the play step passes release-scenarios.py play no --minutes: "
                f"the player's deadline must be below the step's {timeout} minutes"]
    if int(m.group(1)) > timeout - PLAY_SPARE:
        return [f"{LANE}: the play step passes --minutes {m.group(1)}, which leaves less than {PLAY_SPARE} "
                f"of its {timeout} minutes to write its results and exit"]
    return []


# The table of paths (#696): every path docs/model.md describes, and every
# setting that changes one, names the scenarios that play it.
PATHS_DOC = os.path.join("docs", "paths.md")
REQUIRED_PATHS = (
    # The paths.
    "A person's bug to its merge", "A reproduced bug merged by policy", "A feature accepted and built", "A claim and its release",
    "A stop answered", "An edit after acceptance and the new acceptance", "The release and its watch",
    # The settings that change them.
    "Acceptance by policy", "`who-decides`", "A claim", "Merge on its own or by a person", "Its `ceiling`")


def paths(table_text, scenario_ids, required=REQUIRED_PATHS):
    """What is wrong with the table of paths (#696, docs/paths.md): a row
    of `required` it lacks, a row that names no scenario (its cell, the
    ids in backticks), and an id it names that is no scenario of
    `scenario_ids`. [] when it all holds. Pure."""
    out, rows = [], {}
    for line in (table_text or "").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else []
        if len(cells) < 2 or re.fullmatch(r"[-: ]+", cells[0]) or cells[0] == "Path or setting":
            continue
        if cells[0] in rows:
            out.append(f"{PATHS_DOC}: {cells[0]} has two rows")
        rows[cells[0]] = rows.get(cells[0], []) + re.findall(r"`([a-z0-9-]+)`", cells[1])
    for name in required:
        if name not in rows:
            out.append(f"{PATHS_DOC} has no row for {name}")
    for name, ids in rows.items():
        if not ids:
            out.append(f"{PATHS_DOC}: {name} names no scenario")
        for i in ids:
            if i not in scenario_ids:
                out.append(f"{PATHS_DOC}: {name} names {i}, which is no scenario of {SCENARIOS}")
    return out


def paths_problems(conf, root=ROOT):
    """`paths` of the repository's table against its scenarios; one table
    that cannot be read is named."""
    try:
        with open(os.path.join(root, PATHS_DOC), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return [f"{PATHS_DOC} cannot be read: every path of docs/model.md names its scenarios there"]
    return paths(text, {s.get("id") for s in conf.get("scenarios") or []})


def central_of():
    sys.path.insert(0, HERE)
    import org
    return org.CENTRAL


def problems(conf, root=ROOT):
    """What `coverage` names: every played pair and transition with no
    scenario, every scenario its setup cannot make hold, what is wrong
    with the groups (`partition`), with the lane's `play` job
    (`lane_problems`, #707), and with the test repository's pipeline
    (`pipeline_problems`, #748), and every risk label the paths cannot
    give (`risk_problems`, #764), and every path or setting of the table of
    paths that names no scenario that exists (`paths`, #696)."""
    pack = test_pack(root)
    scenarios = conf.get("scenarios") or []
    return (coverage(scenarios, played(root, pack) | transitions(root) | flows(conf), conf.get("statically") or {})
            + hands_problems(scenarios)
            + preconditions(scenarios, conf.get("bodies") or {}, pack, dispatchable(root, pack), schema_passes(root), conf.get("types") or {},
                            test_repro(root))
            + lane_problems(load_yaml(os.path.join(root, LANE)))
            + pipeline_problems(root, pack, central_of())
            + partition(scenarios, groups(scenarios), pack)
            + timing(scenarios)
            + autopilot_problems(scenarios)
            + risk_problems(scenarios, *risk_patterns(root))
            + paths_problems(conf, root)
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
          (["scenarios/x/*", "scenarios/x/*.test.md"], {None}, {""}))
    shared = {"fixed-change": {"file": "scenarios/{n}.md"}, "core": ["scenarios/*"]}
    check("C2: partition fails when two scenarios could write to the same core path (a fixed change outside their own directory)",
          partition([{"id": "a", "expect": {"comments": [CORE_MARK]}}, {"id": "b", "expect": {"comments": [CORE_MARK]}}], groups([{"id": "a"}, {"id": "b"}]), shared),
          ["scenario b: writes scenarios/*.md, on the core of the test repository scenario a writes too, so one would wait on the other"])
    per_dir = {"fixed-change": {"file": "scenarios/{scenario}/{n}.md"}, "core": ["scenarios/*/**"]}
    check("#709 C1: core_problems names a scenario that writes under the core but expects no wait on it, and partition with it",
          (core_problems([{"id": "a", "expect": {}}, {"id": "w", "expect": {"comments": [CORE_MARK]}}], per_dir), partition([{"id": "a"}], groups([{"id": "a"}]), per_dir),
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
    check("C3: the real plan: no fixed wait, every wait an `until`, polling every 75 seconds, each limit 15 minutes or less",
          (timing(real["scenarios"], real["bodies"]), {p["poll"] for p in plan_real}, max(p["minutes"] for p in plan_real) <= 15, len(plan_real) == len(real["scenarios"]),
           [st for s in real["scenarios"] for st in s.get("steps") or [] if "wait" in st]), ([], {75}, True, True, []))
    check("#726 #878: the real plan, every scenario polling at once with its setup, cleanup and retry, stays under the test identity's rate limit; a plan of many scenarios is refused",
          (call_budget(real["scenarios"], real["bodies"]) < RATE_LIMIT, poll_budget([{"opens": {"issue": {}}}, {"opens": {"pull": {}}, "expect": {"check": {"c": "success"}}}]),
           timing([{"id": f"s{i}", "opens": {"pull": {}}, "expect": {"check": {"c": "success"}}} for i in range(30)])),
          (True, 240, ["the plan's 30 scenarios call GitHub 5760 times an hour, polling every 75 seconds, with their setup, cleanup and retry, past the test identity's 5000"]))
    check("#878: a scenario's setup calls: its clear twice, its issue and its cleanup, its pull request, its steps, a land on main",
          [setup_calls(s) for s in ({"id": "i", "opens": {"issue": {}}}, {"id": "p", "opens": {"pull": {}}},
                                    {"id": "p", "opens": {"pull": {}}, "steps": [{"comment": "x"}, {"until": {"labels": ["y"]}}, {"push": "conflict"}]})],
          [22, 24, 43])
    check("C3: timing names a fixed wait, an empty `until` and a limit past 15 minutes",
          timing([{"id": "w", "steps": [{"wait": 60}, {"until": {"of": "before"}}], "minutes": 16}]),
          ["scenario w: waits a fixed 60 seconds; wait `until` the state it waits for, polled every 75 seconds", "scenario w: an `until` with no expectation",
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
    check("C3: an `until` polls every 75 seconds until its state holds, then the next step goes on",
          (got["ok"], st["sleeps"], comment > [i for i, c in enumerate(st["calls"]) if c[:2] == ("issue", "view")][2]), (True, [75, 75], True))
    st, fake = polled([{"labels": []}])
    got = play({"id": "u", "opens": {"issue": {"title": "t"}}, "steps": [{"until": {"labels": ["claimed"]}}, {"comment": "x"}], "expect": {}}, "o/t", "v7-next", {}, fake, st["sleeps"].append, 1)
    check("C3: an `until` that never holds fails at the scenario's limit, named, and takes no further step",
          (got["ok"], got["why"], len(st["sleeps"]), any(c[:2] == ("issue", "comment") for c in st["calls"])), (False, ['until {"labels": ["claimed"]}: no label claimed', f'until {{"labels": ["claimed"]}}: {NONE}'], 1, False))
    st, fake = polled([{"labels": [{"name": "incomplete"}]}], runs=lambda n: [{"url": "u", "status": "completed"}])
    got = play({"id": "u", "opens": {"issue": {"title": "t"}}, "expect": {"labels": ["awaiting-acceptance"], "absent": ["incomplete"]}}, "o/t", "v7-next", {}, fake, st["sleeps"].append, 15)
    check("C3: a scenario stops as soon as its expectation can no longer hold, not at its limit",
          (got["ok"], st["sleeps"], got["why"][-1]), (False, [75], "it can no longer hold: label incomplete stays, with nothing left running"))
    st, fake = polled([{"labels": []}])
    got = play({"id": "u", "opens": {"issue": {"title": "t"}}, "minutes": 2, "expect": {"labels": ["x"]}}, "o/t", "v7-next", {}, fake, st["sleeps"].append, 20)
    check("C3: a scenario's own limit bounds its polls (2 minutes: 2 polls of 75 seconds)", (got["ok"], len(st["sleeps"]), set(st["sleeps"])), (False, 2, {75}))
    st, fake = polled([{"labels": []}])
    got = play({"id": "u", "opens": {"issue": {"title": "t"}}, "steps": [{"wait": 300}], "expect": {}}, "o/t", "v7-next", {}, fake, st["sleeps"].append, 1)
    check("C3: a fixed wait is never slept", (got["ok"], st["sleeps"]), (False, []))
    forked, fork_in = [], []
    got = play({"id": "f", "opens": {"pull": {"title": "docs: x", "body": "b", "fork": True}}, "expect": {}}, "o/t", "v7-next", {"b": "x"},
               lambda *a, input=None: forked.append(("test",) + a) or ("https://github.com/o/t/pull/3\n" if a[:2] == ("pr", "create") else "{}" if a[:2] == ("pr", "view") else "[]"),
               lambda s: None, 1, fork=lambda *a, input=None: forked.append(("fork",) + a) or fork_in.append((a, input)) or ("me\n" if a[-1] == ".login" else "s\n"))
    check("C9: a scenario from a fork forks and writes its fork with the fork token, and opens its pull request with the test identity's",
          (got["ok"], [c[0] for c in forked if c[1:3] == ("repo", "fork")], [c[0] for c in forked if c[1:3] == ("pr", "create")],
           [c[0] for c in forked if c[1:3] == ("api", "graphql") and not queue_read(c[1:])], [c[:3] for c in commits(fork_in)]), (True, ["fork"], ["test"], ["fork"], [("me/t", "docs/scenario-f", ["scenarios/f/pull.md"])]))
    forked = []
    got = play({"id": "f", "opens": {"pull": {"title": "docs: x", "body": "b", "fork": True}}, "expect": {}}, "o/t", "v7-next", {"b": "x"},
               lambda *a, input=None: forked.append(a) or "[]", lambda s: None, 1, fork=False)
    check("C9: with no fork token, the fork's scenario fails at once naming the permission it lacks, and never forks",
          (got["ok"], got["why"], [c for c in forked if c[:2] == ("repo", "fork")]), (False, [FORK_NEEDS], []))
    lane = load_yaml(os.path.join(ROOT, ".github", "workflows", "release-lane.yml"))["jobs"]
    pstep = next(st for st in lane["play"]["steps"] if st.get("id") == "play")
    check("C9: the limits the 20-minute run relies on: every scenario at once, each under the play step's 20 minutes, polled every 75 seconds",
          ("max-parallel" in (lane["play"].get("strategy") or {}), max(limit(s) for s in real["scenarios"]) < pstep["timeout-minutes"] <= 20, POLL,
           pstep["env"].get(FORK_SECRET)), (False, True, 75, "${{ secrets.DX_TEST_FORK_TOKEN }}"))
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
    core_alone = {"id": "c", "opens": {"issue": {"labels": ["accepted"]}}, "expect": {"comments": [CORE_MARK]}}
    import importlib.util
    _rs = importlib.util.spec_from_file_location("receipts_802", os.path.join(HERE, "receipts.py"))
    rc802 = importlib.util.module_from_spec(_rs)
    _rs.loader.exec_module(rc802)
    asked_board = f"{rc802.BOARD}\nrows\n" + rc802.state_block({"asked": "2026-11-01T00:00:00Z"})
    check("#802: the autopilot's question waits on the bot's board, never on a person's comment that looks like it, nor on one edited by hand",
          (bool(board_state(["x", asked_board]).get("asked")), board_state([]), board_state([asked_board.replace("2026", "2027")])), (True, {}, {}))
    check("preconditions: a pull request that closes a fixed number never holds; one that closes the issue it opens does",
          (preconditions([pr_fixed], {"pull": "{files}\n\nCloses #1"}, pack),
           preconditions([dict(pr_fixed, opens={"pull": {"body": "pull", "issue": {"body": "f", "labels": ["accepted"]}}})], {"pull": "## What changes\n\n{files}\n\n## Why\n\nCloses #{issue}"}, pack)),
          (["scenario p: expects its pull request to close an issue, but its body names no `{issue}` it opens"], []))
    old_pull = {"id": "q", "opens": {"pull": {"title": "feat: x", "body": "pull"}}, "expect": {"pull": {"closes": True}}}
    check("#698 preconditions: a pull request that closes an issue it does not open accepted, a body without the template's sections, a title its issue's Type refuses",
          preconditions([old_pull], {"pull": "{files}\n\nCloses #{issue}"}, pack, types={"complete-feature": "Task"}),
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
    borrowed = {"id": "copycat", "opens": {"issue": {"body": "borrowed"}}, "expect": {"labels": ["needs-info"]}}
    check("#881: a scenario whose body names another scenario's file is refused (the triage reads it as a duplicate), its own is not, and no real one does",
          ([p.split(":")[0] for p in preconditions([borrowed], {"borrowed": "Read `scenarios/someone-else/greeting.md`."}, rpack, repro=True)],
           preconditions([dict(borrowed, id="someone-else")], {"borrowed": "Read `scenarios/someone-else/greeting.md`."}, rpack, repro=True),
           [p for p in preconditions(real["scenarios"], real["bodies"], rpack, types=real.get("types") or {}, repro=True) if "another scenario's file" in p],
           [b for s in real["scenarios"] if s["id"] == "bug-by-person-merges" for b in [s["opens"]["issue"]["body"]]]),
          (["scenario copycat"], [], [], ["bug-by-person-merges"]))
    check("#707: the bug that reproduces lands the greeting its fixed test reads, under its own directory, and its body names it",
          ([b for b in bugs[0].get("before") or [] if "lands" in b], "scenarios/bug-reproduced/greeting.md" in real["bodies"][bugs[0]["opens"]["issue"]["body"]]),
          ([{"lands": "greeting", "says": "helo"}], True))
    # #764 C3: the bugs that do not reproduce land a file of their own that
    # shows no bug (#916: a notice, a footer, never another's greeting), and
    # their reports' steps read it; the fixed reproduction passes on them.
    import importlib.util
    import tempfile
    ways_spec = importlib.util.spec_from_file_location("repro_ways", os.path.join(HERE, "repro-ways.py"))
    ways = importlib.util.module_from_spec(ways_spec)
    ways_spec.loader.exec_module(ways)

    def repro_on(sid, says, name="greeting"):
        """kinds/engine-test/repro-fixed.py, as issue 7 of scenario `sid`
        gets it, run where scenarios/<sid>/<name>.md says `says`."""
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "scenarios", sid))
            with open(os.path.join(tmp, "scenarios", sid, f"{name}.md"), "w", encoding="utf-8") as fh:
                fh.write(f"{says}\n")
            ways.write_fixed(os.path.join(ROOT, "kinds", "engine-test", "repro-fixed.py"), os.path.join(tmp, "tests", "repro", "test_issue_7.py"), 7, scenario_mark(sid))
            return subprocess.run([sys.executable, "-I", os.path.join("tests", "repro", "test_issue_7.py")], cwd=tmp, capture_output=True, text=True).returncode
    for sid, name in (("bug-not-reproduced", "notice"), ("bug-by-person-merges", "footer")):
        unrepro = next(s for s in real["scenarios"] if s["id"] == sid)
        lands = [b for b in unrepro.get("before") or [] if "lands" in b]
        steps = real["bodies"][unrepro["opens"]["issue"]["body"]].split("### Steps to reproduce", 1)[1].split("###", 1)[0]
        check(f"#764 C3, #916: the real {sid} lands its own {name} saying something other than helo, its steps read it on main, and the fixed reproduction passes on it",
              ([b["lands"] for b in lands], [b["says"] for b in lands if "helo" not in str(b["says"]).split()], f"`scenarios/{sid}/{name}.md` on `main`" in steps,
               [repro_on(sid, b["says"], b["lands"]) for b in lands]),
              ([name], [lands[0]["says"]] if lands else ["?"], True, [0]))
    check("#764 C3: and the same reproduction fails where it says helo, as bug-reproduced lands it", repro_on("bug-reproduced", "helo"), 1)
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
    # #696 C1: a stop said once, never twice: how many comments carry it.
    stop696 = "<!-- dx-autopilot-stop -->"
    once = {**seen, "comments": [f"{stop696}\nStopped.", "**Acceptance withdrawn (G2):**", "<!-- dx-board -->"]}
    twice = {**once, "comments": once["comments"] + [f"{stop696}\nStopped again."]}
    check("#696 C1 holds: count, once is once; twice is named; none is named", (holds({"count": {stop696: 1}}, once), holds({"count": {stop696: 1}}, twice)[0],
          holds({"count": {stop696: 1}}, {**seen, "comments": []})[0]), ([], f"2 comments with {stop696}, not 1", f"0 comments with {stop696}, not 1"))
    check("#696 C1 hopeless: a marker past its count can no longer hold; under it still may", (hopeless({"count": {stop696: 1}}, twice), hopeless({"count": {stop696: 1}}, {**seen, "comments": []})),
          ([f"2 comments with {stop696} already, past 1"], []))
    check("#696 holds: state, the issue its merged fix closed", (holds({"state": "CLOSED"}, {**seen, "state": "CLOSED"}), holds({"state": "CLOSED"}, {**seen, "state": "OPEN"})[0]),
          ([], "its state is OPEN, not CLOSED"))
    bad696 = [{"id": "c1", "opens": {"issue": {"title": "x", "body": "complete-feature"}}, "expect": {"count": c}} for c in ({"m": -1}, {"m": "one"}, [], {}, {"m": True})]
    check("#696 C1 preconditions: count is {marker: a whole number}", [len(preconditions([b], real.get("bodies") or {}, {})) for b in bad696], [1, 1, 1, 1, 1])
    check("#696 C1 preconditions: a whole number holds", preconditions([{**bad696[0], "expect": {"count": {"m": 1}}}], real.get("bodies") or {}, {}), [])
    c1 = next((s for s in real["scenarios"] if s["id"] == "stop-edited-reaccepted-answered"), {})
    verbs696 = [next(k for k in st if k != "of") for st in c1.get("steps") or []]
    check("#696 C1: the scenario stops, is edited, answered and accepted again, in that order, and expects the stop once and no label left",
          (verbs696[-3:], verbs696.count("label"), "edit" in verbs696 and verbs696.index("edit") < verbs696.index("comment"),
           (c1.get("expect") or {}).get("count"), {"needs-human", "autopilot:continue"} <= set((c1.get("expect") or {}).get("absent") or []),
           "the fixed change asks first" in (real.get("bodies") or {}).get(c1.get("opens", {}).get("issue", {}).get("body"), "")),
          (["until", "comment", "label"], 2, True, {stop696: 1}, True, True))
    # #696 C2: the table of paths (docs/paths.md) names, for every path
    # docs/model.md describes and every setting that changes it, scenarios
    # that exist.
    ids696 = {s["id"] for s in real["scenarios"]}
    with open(os.path.join(ROOT, PATHS_DOC), encoding="utf-8") as fh:
        doc696 = fh.read()
    check("#696 C2 paths: docs/paths.md against tests/release/scenarios.yml: every path and setting has a row, and every row names scenarios that exist",
          paths(doc696, ids696), [])
    rows696 = "| Path or setting | Scenarios |\n| --- | --- |\n" + "".join(f"| {p} | `accepted-spec` |\n" for p in REQUIRED_PATHS)
    check("#696 C2 paths: a table with every row, each naming a scenario, holds", paths(rows696, {"accepted-spec"}), [])
    missing696 = rows696.replace(f"| {REQUIRED_PATHS[0]} | `accepted-spec` |\n", "")
    check("#696 C2 paths fixture: a missing row is named", paths(missing696, {"accepted-spec"}), [f"{PATHS_DOC} has no row for {REQUIRED_PATHS[0]}"])
    unknown696 = rows696.replace(f"| {REQUIRED_PATHS[1]} | `accepted-spec` |", f"| {REQUIRED_PATHS[1]} | `accepted-spec`, `no-such-scenario` |")
    check("#696 C2 paths fixture: an unknown scenario is named", paths(unknown696, {"accepted-spec"}),
          [f"{PATHS_DOC}: {REQUIRED_PATHS[1]} names no-such-scenario, which is no scenario of {SCENARIOS}"])
    empty696 = rows696.replace(f"| {REQUIRED_PATHS[2]} | `accepted-spec` |", f"| {REQUIRED_PATHS[2]} |  |")
    check("#696 C2 paths fixture: an empty cell is named", paths(empty696, {"accepted-spec"}), [f"{PATHS_DOC}: {REQUIRED_PATHS[2]} names no scenario"])
    dup696 = rows696 + f"| {REQUIRED_PATHS[0]} | `no-such-scenario` |\n"
    check("#696 C2 paths fixture: a row named twice is named, and neither row's scenarios is lost", paths(dup696, {"accepted-spec"}),
          [f"{PATHS_DOC}: {REQUIRED_PATHS[0]} has two rows", f"{PATHS_DOC}: {REQUIRED_PATHS[0]} names no-such-scenario, which is no scenario of {SCENARIOS}"])
    check("#696 C2 paths: the required rows are docs/model.md's paths and the settings that change them",
          {"A person's bug to its merge", "A reproduced bug merged by policy", "A feature accepted and built", "A claim and its release", "A stop answered",
           "An edit after acceptance and the new acceptance", "The release and its watch", "Acceptance by policy", "`who-decides`", "A claim",
           "Merge on its own or by a person", "Its `ceiling`"} == set(REQUIRED_PATHS), True)
    with tempfile.TemporaryDirectory() as root696:
        os.makedirs(os.path.join(root696, "docs"))
        open(os.path.join(root696, PATHS_DOC), "w").write(missing696)
        check("#696 C2 coverage reads the table: a row missing there fails `coverage`", paths_problems({"scenarios": [{"id": "accepted-spec"}]}, root696),
              [f"{PATHS_DOC} has no row for {REQUIRED_PATHS[0]}"])
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
    # #843: b failed, so it played twice: its issues of both attempts too.
    check("run: its issues are closed and locked after it", sum(1 for c in calls if c[:2] in (("issue", "close"), ("issue", "lock"))), 6)
    check("#843 run: a scenario that failed is played once more, one that passed once", [(r["id"], r.get("attempts"), r.get("flaky")) for r in res], [("a", 1, None), ("b", 2, None)])
    check("#843 class: an `expect` that does not hold is the engine's", [r.get("class") for r in res], [None, "engine"])
    waits = {"id": "w", "opens": {"issue": {"title": "t", "body": "b"}}, "steps": [{"wait": 5}], "expect": {"labels": ["x"]}}
    check("#843 class: the player's own exception (a fixed wait) is the harness's",
          play(waits, "o/t", "v7-next", {"b": "body"}, fake, lambda s: None, 1).get("class"), "harness")

    def busy(*args, input=None):
        if args[:2] == ("issue", "view"):
            raise GhError("gh issue view: HTTP 502", 1, "", "HTTP 502")
        return fake(*args, input=input)
    gone = play(scen["scenarios"][1], "o/t", "v7-next", scen["bodies"], busy, lambda s: None, 0)
    check("#843 class: GitHub failing until the scenario's time ran out is infrastructure's",
          (gone["ok"], gone.get("class"), "until the scenario's time ran out" in " ".join(gone["why"])), (False, "infrastructure", True))

    def denied(*args, input=None):
        if args[:2] == ("issue", "create"):
            raise GhError("gh issue create: HTTP 422 Validation Failed", 1, "", "")
        return fake(*args, input=input)
    check("#843 class: a `gh` error that is not GitHub failing is read as the engine's", play(scen["scenarios"][1], "o/t", "v7-next", scen["bodies"], denied, lambda s: None, 1).get("class"), "engine")
    check("#843 class: a run GitHub held or never started is infrastructure's", (blocked({"held": ["u"]}), blocked({"checks": {"a": "startup_failure"}}), blocked({"checks": {"a": "failure"}})), (True, True, False))
    clock, naps = iter([0, 15 * 60]), iter([0, 14 * 60])
    tried = []
    late = retried({"id": "c"}, lambda m: tried.append(m) or {"id": "c", "ok": False, "why": ["slow"], "run": ""}, 20, 20 * 60, lambda: next(clock), lambda: next(naps))
    check("#843 #878 retry: with less than a minute left in the player's time, past its allowance and a poll, a failure is not played again and says so",
          (tried, late["ok"], late["why"], late["attempts"]), ([20], False, ["slow", NOT_RETRIED], 1))
    clock, naps = iter([0, 5 * 60]), iter([0, 4 * 60])
    tried = []
    again = retried({"id": "c", "minutes": 15}, lambda m: tried.append(m) or {"id": "c", "ok": len(tried) > 1, "why": [] if len(tried) > 1 else ["fast"], "run": ""}, 20, 20 * 60, lambda: next(clock), lambda: next(naps))
    check("#843 #878 retry: the retry has what the player has left less RETRY_ALLOWANCE (the first attempt took 1 minute of its own) and a poll, at most the scenario's limit; passing, it is ok and flaky",
          (tried, again["ok"], again.get("flaky"), again["first_why"], table([again]).count("pass (flaky: fast)")), ([20, 10.75], True, True, ["fast"], 1))
    clock, naps = iter([0, 9 * 60]), iter([0, 3 * 60])
    tried = []
    retried({"id": "c", "minutes": 15}, lambda m: tried.append(m) or {"id": "c", "ok": False, "why": ["slow"], "run": ""}, 20, 20 * 60, lambda: next(clock), lambda: next(naps))
    check("#878 retry: a first attempt whose own time (its setup and cleanup) passes RETRY_ALLOWANCE leaves the retry that much more",
          tried, [20, 20 - 9 - 6 - POLL / 60])
    # #843: a retried row's class comes from both attempts.
    both = iter([{"id": "k", "ok": False, "why": ["slow"], "run": "", "class": "infrastructure"}, {"id": "k", "ok": False, "why": ["no"], "run": "", "class": "engine"}])
    check("#843 retry: failing on both attempts, the row keeps the first failure's class",
          retried({"id": "k"}, lambda m: next(both), 20).get("class"), "infrastructure")
    healed = iter([{"id": "k", "ok": False, "why": ["slow"], "run": "", "class": "engine"}, {"id": "k", "ok": True, "why": [], "run": "", "class": "harness"}])
    got = retried({"id": "k"}, lambda m: next(healed), 20)
    check("#843 retry: passing on its retry, the row is flaky and carries no failure's class",
          (got["ok"], got.get("flaky"), "class" in got), (True, True, False))
    ccalls = []

    def cfake(*args, input=None):
        ccalls.append(args)
        if args[:2] == ("issue", "view"):
            return json.dumps({"closedByPullRequestsReferences": [{"number": 12, "url": "https://github.com/o/t/pull/12"}, {"number": 30, "url": "https://github.com/x/y/pull/30"}]})
        return ""
    cleanup("o/t", [("issue", "5")], cfake)
    check("#784 cleanup: the pull request that closes its issue (no mark) is closed, one in another repository left alone, then the issue closed and locked",
          [c for c in ccalls if c[:1] in (("pr",), ("issue",)) and c[1] not in ("view", "list")],
          [("pr", "close", "12", "--repo", "o/t", "--delete-branch"), ("issue", "close", "5", "--repo", "o/t"), ("issue", "lock", "5", "--repo", "o/t")])
    lccalls = []

    def lcfake(*args, input=None):
        lccalls.append(args)
        if args[:2] == ("issue", "list"):
            return json.dumps([{"number": 20, "title": "The bug reproduced from #5"}, {"number": 30, "title": "The bug reproduced from #50"}])
        if args[:3] == ("issue", "view", "20"):
            return json.dumps({"closedByPullRequestsReferences": [{"number": 21, "url": "https://github.com/o/t/pull/21"}]})
        return ""
    cleanup("o/t", [("issue", "5")], lcfake)
    check("#985 cleanup: the lane issue the reproduction opened from its issue, its pull request first, then the report; another report's left alone",
          [c[:3] for c in lccalls if c[:2] in (("pr", "close"), ("issue", "close"), ("issue", "lock"))],
          [("pr", "close", "21"), ("issue", "close", "20"), ("issue", "lock", "20"), ("issue", "close", "5"), ("issue", "lock", "5")])
    check("#985 lane_of: compared as a number, #12 never matches #120",
          lane_of("o/t", "12", lambda *a, input=None: json.dumps([{"number": 1, "title": "The bug reproduced from #120"}, {"number": 2, "title": "The bug reproduced from #12"}])), [2])
    check("#985 lane_of: a read that fails finds none", lane_of("o/t", "5", lambda *a, input=None: "not json"), [])
    check("#985 lane_of: a report that is no number finds none", lane_of("o/t", "x", lambda *a, input=None: "[]"), [])
    check("#784 cleanup: a view that is not JSON never hides a result", cleanup("o/t", [("issue", "5")], lambda *a, input=None: "not json"), None)

    def vfake(answer):
        seen = []

        def fake(*args, input=None):
            seen.append(args)
            if args[:2] == ("issue", "view"):
                if answer is None:
                    raise RuntimeError("gh: HTTP 502")
                return answer
            return ""
        return seen, fake
    for name, answer in (("not JSON", "not json"), ("that fails", None)):
        seen, fake_ = vfake(answer)
        cleanup("o/t", [("issue", "5")], fake_)
        check(f"#784 cleanup: a view {name} still has the issue closed and locked",
              [c for c in seen if c[1] not in ("view", "list")], [("issue", "close", "5", "--repo", "o/t"), ("issue", "lock", "5", "--repo", "o/t")])
    for name, reads, closes, slept in (("leaves the queue unmerged", [("OPEN", True), ("OPEN", False)], 1, [QUEUE_POLL]),
                                       ("merges", [("OPEN", True), ("MERGED", False)], 0, [QUEUE_POLL]),
                                       ("never leaves", [("OPEN", True)], 0, [QUEUE_POLL] * (QUEUE_LEAVE // QUEUE_POLL))):
        qcalls, naps, answers = [], [], iter(reads + [reads[-1]] * 99)

        def qfake(*args, input=None):
            qcalls.append(args)
            if queue_read(args):
                state, inq = next(answers)
                return json.dumps({"data": {"repository": {"pullRequest": {"state": state, "isInMergeQueue": inq}}}})
            return ""
        cleanup("o/t", [("pr", "7")], qfake, naps.append)
        check(f"#936 cleanup: a pull request in the merge queue that {name} is closed {closes} time(s), after waiting for it",
              (sum(1 for c in qcalls if c[:2] == ("pr", "close")), naps), (closes, slept))
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
          ([c for c in calls694 if "actions/runs?created=" not in " ".join(c)][-1][:2], sum(1 for c in calls694 if c == delete) >= 2), (("pr", "list"), True))
    check("#843: the runs it triggered are read once, last", ("actions/runs?created=" in " ".join(calls694[-1]), sum(1 for c in calls694 if "actions/runs?created=" in " ".join(c))), (True, 1))
    wired843 = {"issues.yml": {"issue-triage.yml:issues", "issue-triage.yml:issue_comment"}, "test-pull-request.yml": {"conventions.yml:pull_request"}}
    runs843 = [{"path": ".github/workflows/issues.yml", "event": "issues", "display_title": "feat: x [s]", "head_branch": "main", "created_at": "2026-01-01T00:05:00Z"},
               {"path": ".github/workflows/issues.yml", "event": "issue_comment", "display_title": "feat: x [s]", "head_branch": "main", "created_at": "2026-01-01T00:20:00Z"},
               {"path": ".github/workflows/test-pull-request.yml@refs/heads/main", "event": "pull_request", "display_title": "feat: its pull", "head_branch": "feat/1-x", "created_at": "2026-01-01T00:06:00Z"},
               {"path": ".github/workflows/test-pull-request.yml", "event": "pull_request", "display_title": "fix: y [other]", "head_branch": "fix/scenario-other", "created_at": "2026-01-01T00:06:00Z"}]
    check("#843 run_triggered: its runs, by title or branch, within its time, through the caller at their path and their event",
          run_triggered(runs843, "s", {"feat: its pull"}, {"test/scenario-s"}, wired843, "2026-01-01T00:00:00Z", "2026-01-01T00:10:00Z"),
          ["conventions.yml:pull_request", "issue-triage.yml:issues"])
    check("#843 run_coverage: what no row triggered, never what `covers:` says, and no transition",
          run_coverage([{"covers": ["a:issues"], "triggered": ["b:issues"]}, {"id": "x"}], {"a:issues", "b:issues", "next_step:start"}), ["a:issues"])
    check("#843 retry: what either attempt triggered is kept",
          retried({"id": "t"}, lambda m: {"id": "t", "ok": m == 10, "why": [], "run": "", "triggered": ["a:issues"] if m == 20 else ["b:issues"]}, 20)["triggered"], ["a:issues", "b:issues"])
    check("#843 the table names the pairs no scenario triggered, a warning line", untriggered_line(["a:issues"]), "\nPairs no scenario triggered: `a:issues`\n")
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
    scalls = []

    def sweepfake(*a, input=None):
        scalls.append(a)
        if a[:2] == ("pr", "list"):
            return json.dumps([{"number": 40, "headRefName": "fix/30-the-bug-reproduced-from-4"}, {"number": 41, "headRefName": "fix/31-the-bug-reproduced-from-6"},
                               {"number": 42, "headRefName": "dependabot/x"}, {"number": 43, "headRefName": "chore/sync-callers"}])
        if a[:3] == ("issue", "view", "4"):
            return json.dumps({"body": scenario_mark("bug-reproduced") + "\nthe report"})
        if a[:3] == ("issue", "view", "6"):
            return json.dumps({"body": scenario_mark("bug-reproduced-2") + "\nanother's"})
        return "[]" if a[1:2] == ("list",) else ""
    lane_leftovers("o/t", scenario_mark("bug-reproduced"), sweepfake)
    check("#985: clear closes an earlier run's lane pull request whose report carries the mark, with its branch, and no other",
          [c for c in scalls if c[:2] == ("pr", "close")], [("pr", "close", "40", "--repo", "o/t", "--delete-branch")])
    check("#985: an open lane issue is locked too", [c[:3] for c in lcalls if c[:2] == ("issue", "lock")], [("issue", "lock", "20")])

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
          (got["ok"], [c for c in st["calls"] if c[:2] == ("pr", "list") and "Closes" in " ".join(map(str, c))], ("pr", "view", "12", "--repo", "o/t", "--json", "number,body,headRefName,title,isDraft,comments") in st["calls"]),
          (True, [], True))
    st, fake = searchless(fail=2)
    got = play({"id": "s", "opens": {"issue": {"title": "feat: x", "body": "f"}}, "expect": {"pull": {"closes": True}}}, "o/t", "v7-next", {"f": "f"}, fake, st["sleeps"].append, 1)
    check("#698: a rate-limited `gh` is retried after GitHub's retry-after, then the scenario holds", (got["ok"], st["sleeps"]), (True, [30, 30]))
    st, fake = searchless(fail=99, retry="")
    got = play({"id": "s", "minutes": 2, "opens": {"issue": {"title": "feat: x", "body": "f"}}, "expect": {"pull": {"closes": True}}}, "o/t", "v7-next", {"f": "f"}, fake, st["sleeps"].append, 20)
    check("#698: one rate-limited until the scenario's time runs out fails then, naming it, backing off within its limit",
          (got["ok"], got["why"][0].startswith("gh issue view 9 rate limited"), sum(st["sleeps"]), st["sleeps"][:3]), (False, True, 120, [75, 45]))
    st = {"n": 0}

    def broken(*a, input=None):
        if a[:2] == ("issue", "view"):
            raise GhError("gh issue view 9: HTTP 404: Not Found", 1, "", "HTTP 404")
        return "https://github.com/o/t/issues/9\n" if a[:2] == ("issue", "create") else "[]"
    got = play({"id": "s", "opens": {"issue": {"title": "t"}}, "expect": {"labels": ["x"]}}, "o/t", "v7-next", {}, broken, lambda s: st.__setitem__("n", st["n"] + 1), 1)
    check("#698: a `gh` error that is not transient still fails at once", (got["ok"], st["n"]), (False, 0))
    check("#698 backoff: retry-after, then the reset, then POLL doubled up to 120",
          (backoff(GhError("x", stderr="Retry-After: 7"), 0), backoff(GhError("x", stderr="x-ratelimit-reset: 1060"), 0, now=1000), backoff(GhError("x"), 0), backoff(GhError("x"), 5)),
          (7, 60, POLL, 120))
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
    # #748 C1: the test repository's pull-request caller, the shipped
    # template as it is, moves with the others.
    import yaml
    shipped = open(os.path.join(ROOT, "workflow-templates", "test-pull-request.yml"), encoding="utf-8").read()
    shipped = shipped.replace("DiluxOne/.github/", "O/.github/")
    st, fake = repo_fake()
    st["main"]["test-pull-request.yml"] = shipped
    moved, rows = move_callers("o/t", "v7-next", fake, "O/.github", lambda s: None, 3)
    jobs = yaml.safe_load(st["main"]["test-pull-request.yml"])["jobs"]
    check("#748 C1: after point_callers, every engine call of test-pull-request.yml's review, auto-merge and autopilot-fix jobs is at @v7-next",
          (rows, sorted(m["name"] for m in moved), {j: jobs[j]["uses"].rsplit("@", 1)[1] for j in ("review", "auto-merge", "autopilot-fix")}),
          ([], ["issues.yml", "test-pull-request.yml"], {"review": "v7-next", "auto-merge": "v7-next", "autopilot-fix": "v7-next"}))
    check("#748 C3: and put back after, as it was, with the others",
          (put_back("o/t", "v7-next", moved, fake, "O/.github", lambda s: None, 3), st["main"]["test-pull-request.yml"] == shipped, st["main"]["issues.yml"] == caller),
          ([], True, True))
    # #748 C4: what would leave a pipeline there at v7, refused and named.
    def rules_fake(rules, tamper=None):
        st, fake = repo_fake()
        st["main"]["test-pull-request.yml"] = shipped

        def with_rules(*a, input=None):
            if a[:3] == ("api", "--paginate", "--slurp") and a[3].startswith("repos/o/t/rules/branches/main"):
                return json.dumps([rules])
            got = fake(*a, input=input)
            if tamper and a[:2] == ("pr", "view") and st["main"].get("test-pull-request.yml", "").count("@v7-next") > 0:
                tamper(st)
            return got
        return st, with_rules
    required_rule = {"type": "workflows", "ruleset_source_type": "Organization", "ruleset_source": "DiluxOne", "ruleset_id": 3,
                     "parameters": {"workflows": [{"path": ".github/workflows/org-pull-request.yml", "repository_id": 1, "ref": "refs/tags/v7"}]}}
    st, fake = rules_fake([{"type": "pull_request"}, required_rule])
    got = run_all(one, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=3, central="O/.github")
    check("#748 C4: move refuses a test repository whose default branch still requires org-pull-request.yml, naming the rule, plays nothing, and puts the callers back",
          ([(r["id"], r["ok"]) for r in got], "org-pull-request.yml" in got[0]["why"][0] and "`workflows` rule" in got[0]["why"][0],
           any(c[:2] == ("issue", "create") for c in st["calls"]), st["main"]["test-pull-request.yml"] == shipped),
          ([("callers", False)], True, False, True))

    def left_behind(st):
        st["main"]["test-pull-request.yml"] = st["main"]["test-pull-request.yml"].replace("claude-review.yml@v7-next", "claude-review.yml@v7", 1)
    st, fake = rules_fake([{"type": "pull_request"}], left_behind)
    moved_rows = move_callers("o/t", "v7-next", fake, "O/.github", lambda s: None, 3)
    check("#748 C4: move refuses a caller still off the ref after the move, naming the file and the line",
          ([m["name"] for m in moved_rows[0]], [r["why"] for r in moved_rows[1]]),
          (["issues.yml", "test-pull-request.yml"],
           [[".github/workflows/test-pull-request.yml line " + str(st["main"]["test-pull-request.yml"].split("\n").index("    uses: O/.github/.github/workflows/claude-review.yml@v7") + 1)
             + ": 'uses: O/.github/.github/workflows/claude-review.yml@v7': calls the engine off v7-next after the move"]]))
    st, fake = rules_fake([{"type": "pull_request"}, dict(required_rule, parameters={"workflows": [{"path": ".github/workflows/other.yml"}]})])
    check("#748 C4: every caller at the ref and no required pull-request workflow left: move passes",
          move_callers("o/t", "v7-next", fake, "O/.github", lambda s: None, 3)[1], [])
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, "workflow-templates"))
        os.makedirs(os.path.join(root, ".github", "workflows"))
        open(os.path.join(root, REQUIRED), "w").write(
            "on:\n  pull_request:\n  merge_group:\njobs:\n  review:\n    if: github.event_name == 'pull_request'\n    uses: O/.github/.github/workflows/claude-review.yml@v7\n")
        open(os.path.join(root, "workflow-templates", "issues.yml"), "w").write("on:\n  issues:\njobs:\n  t:\n    uses: O/.github/.github/workflows/issue-triage.yml@v7\n")
        open(os.path.join(root, "workflow-templates", "test-pull-request.yml"), "w").write(open(os.path.join(root, REQUIRED)).read())
        open(os.path.join(root, "workflow-templates", "quoted.yml"), "w").write(
            "on:\n  issues:\njobs:\n  t:\n    uses: \"O/.github/.github/workflows/issue-triage.yml@v7\"\n")
        check("#748 C4: the pack's callers with test-pull-request.yml pass", pipeline_problems(root, {"callers": ["issues.yml", "test-pull-request.yml"]}, "O/.github"), [])
        got = pipeline_problems(root, {"callers": ["issues.yml"]}, "O/.github")
        check("#748 C4: a pack with no caller that wires the pull-request pipeline is refused, naming what it lacks",
              (len(got), "no caller that wires the pull-request pipeline" in got[0], "claude-review.yml:pull_request" in got[0], "`merge_group`" in got[0]), (1, True, True, True))
        got = pipeline_problems(root, {"callers": ["issues.yml", "test-pull-request.yml", "org-pull-request.yml"]}, "O/.github")
        check("#748 C4: org-pull-request.yml among the test repository's callers is refused, named", [l.split(",")[0] for l in got],
              ["kinds/engine-test/pack.yml `callers` names org-pull-request.yml"])
        got = pipeline_problems(root, {"callers": ["quoted.yml", "test-pull-request.yml"]}, "O/.github")
        check("#748 C4: an engine call the lane cannot move is refused, naming the file and the line",
              got, ["workflow-templates/quoted.yml line 5: 'uses: \"O/.github/.github/workflows/issue-triage.yml@v7\"': an engine call the lane cannot move to the candidate "
                    "(`uses: O/.github/.github/workflows/<name>.yml@<ref>`)"])
    check("#748 C4: the shipped pack passes", pipeline_problems(ROOT, test_pack(), central_of()), [])
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
              read_results(out) + [{"id": "callers", "ok": False, "why": ["x"], "run": "", "class": "harness"}], [{"id": "a", "ok": True, "why": [], "run": ""}, {"id": "callers", "ok": False, "why": ["x"], "run": "", "class": "harness"}])
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
           len(commits(recorded)) == sum(1 for a, _ in recorded if a[:2] == ("api", "graphql") and not queue_read(a))),
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
                # #929: the group's row is the failure; the failed play job adds none.
                ("a group's missing file (its job timed out)", dict(every, b=None), dict(done, play="failure"), {"b"}),
                ("a play job that ended in failure with all rows passing", every, dict(done, play="failure"), {"play"}),
                ("a missing scenario row", dict(every, serial=passed("a")), done, {"c"}),
                ("a row from another group in place of its own", dict(every, b=passed("a")), done, {"b"}),
                ("a back job that left nothing", dict(every, back=None), dict(done, back="cancelled"), {"back"}),
                ("a move that failed, and no group played", {"move": [{"id": "callers", "ok": False, "why": ["x"], "run": "", "class": "harness"}]}, dict(done, play="skipped", back="success"), {"callers", "play", "back"})):
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
              (rc, [r["id"] for r in read_results(out) if not r["ok"]], lane.decide(plan, read_results(out))["scenario"]), (1, ["b"], "b"))
    # #713: the autopilot's result read once it is there.
    def sealing(pull=True):
        """A test repository whose triage answers issue 9 on its second view
        (`awaiting-acceptance`), whose acceptance after that seals it a view
        later and, with `pull`, has the autopilot open its pull request 12
        that closes it two views after the seal, never labelling the issue
        `autopilot` (#764), and an acceptance before the triage never seals
        (the autopilot calls it unsealed); a `/claim` before the acceptance
        claims it, after it is refused."""
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
                if pull and isinstance(st["at"], int) and st["views"] == st["at"] + 3:
                    st["pull"] = 12
                refs = [{"number": st["pull"], "url": f"https://github.com/o/t/pull/{st['pull']}"}] if st.get("pull") else []
                return json.dumps({"labels": [{"name": l} for l in st["labels"]], "comments": [{"body": c, "author": {"login": "dilux-bot"}} for c in st["comments"]],
                                   "closedByPullRequestsReferences": refs})
            if a[:2] == ("pr", "view") and st.get("pull"):
                return json.dumps({"number": st["pull"], "body": "Closes #9", "headRefName": "feat/9-a-greeting", "title": "feat: a greeting"})
            return "[]"
        return st, fake
    by713 = {s["id"]: s for s in real["scenarios"]}
    st, fake = sealing()
    got = play(by713["accepted-spec"], "o/t", "v7-next", real["bodies"], fake, lambda s: None, 15, types=real["types"])
    check("#764 C1: the real accepted-spec, against a repository that seals only after the triage, passes once the autopilot opens its pull request, with no `autopilot` label",
          (got["ok"], got["why"], st["at"] >= 2, st.get("pull"), "autopilot" in st["labels"]), (True, [], True, 12, False))
    st, fake = sealing(pull=False)
    got = play(dict(by713["accepted-spec"], minutes=1), "o/t", "v7-next", real["bodies"], fake, lambda s: None, 1, types=real["types"])
    check("#764 C1: the same repository whose autopilot opens no pull request fails it, named",
          (got["ok"], any("does not say Closes #9" in w for w in got["why"]), any(SEAL in c for c in st["comments"])), (False, True, True))
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
          ([], sorted(["accepted-spec", "spec-to-draft", "core-one-at-a-time", "decision-sub-issues", "prd-edited-after-acceptance", "question-answered", "stop-hint-continue", "draft-in-conflict", "ready-behind-main", "bug-by-person-merges", "stop-answered", "stop-edited-reaccepted-answered",
                     "marker-g1-start", "conventions-fix"]), {15}))
    # #764 C2: high-risk-waits's floor is high from the path it changes.
    hrw = by713["high-risk-waits"]
    rhigh, rlow = risk_patterns()
    check("#764 C2: the real high-risk-waits expects risk:high and no merge, and its path gets the high floor",
          ("risk:high" in hrw["expect"].get("labels", []), hrw["expect"].get("merged"), pull_files(hrw), [path_floor(f, rhigh, rlow) for f in pull_files(hrw)], risk_problems([hrw], rhigh, rlow)),
          (True, False, ["scenarios/high-risk-waits/pull.md"], ["high"], []))
    # #764 C4: a risk label the paths it changes cannot give is named.
    def risky(sid, level, pushes=()):
        return {"id": sid, "opens": {"pull": {"title": "docs: x", "body": "pull"}}, "steps": [{"push": p} for p in pushes], "expect": {"labels": [f"risk:{level}"]}}
    fake_high, fake_low = ["kit/**", "scenarios/hot/**"], ["**/*.md"]
    check("#764 C4: risk_problems names a scenario that expects risk:high with no high path, and passes one with a path in the kind's high-risk",
          ([p.split(":")[0] for p in risk_problems([risky("cold", "high"), risky("hot", "high")], fake_high, fake_low)],
           "scenarios/cold/pull.md (low)" in "".join(risk_problems([risky("cold", "high")], fake_high, fake_low))),
          (["scenario cold"], True))
    check("#764 C4: and the same for risk:low and risk:medium",
          ([p.split(":")[0] for p in risk_problems([risky("hot", "low"), risky("cold", "low"), risky("cold", "medium"), risky("med", "medium")], fake_high, ["scenarios/cold/**"])],
           risk_problems([risky("mixed", "medium", ["x"])], fake_high, ["scenarios/mixed/pull.md"])),
          (["scenario hot", "scenario cold"], []))
    check("#764 C4: a scenario that expects no risk label is never named, and one that expects one but changes no path always is",
          [p.split(":")[0] for p in risk_problems([{"id": "a", "expect": {"labels": ["accepted"]}}, {"id": "b", "opens": {"issue": {}}, "expect": {"labels": ["risk:high"]}}], fake_high, fake_low)],
          ["scenario b"])
    check("#764 C4: the real file: problems() names nothing, and the kind engine-test's high-risk is what policy.py reads",
          (problems(real), risk_patterns()[0][-1:], load_yaml(os.path.join(ROOT, "kinds", "engine-test", "surface.yml")).get("high-risk")),
          ([], ["scenarios/high-risk-waits/**"], ["scenarios/high-risk-waits/**"]))
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
    # #760: a scenario pull request's description names every file of its diff.

    def described(io):
        """A test repository that records every `gh` call (args, input)."""
        def fake(*a, input=None):
            io.append((a, input))
            if a[:2] == ("issue", "create"):
                return "https://github.com/o/t/issues/11\n"
            if a[:2] == ("pr", "create"):
                return "https://github.com/o/t/pull/12\n"
            if a[:2] in (("pr", "view"), ("issue", "view")):
                return "{}"
            if a[-1:] in ((".sha",), (".login",)):
                return "me\n"
            return "[]"
        return fake
    pulls760 = [s for s in real["scenarios"] if "pull" in (s.get("opens") or {})]
    gaps760 = {}
    for s in pulls760:
        io = []
        play(s, "o/t", "v7-next", real["bodies"], described(io), lambda _: None, 1, fork=described(io), types=real.get("types") or {})
        made = [i for a, i in io if a[:2] == ("pr", "create")]
        gaps760[s["id"]] = unnamed(made[0] if made else "", pull_files(s)) or (not made and ["no pr create"]) or []
    check("#760 C1: every real scenario that opens a pull request names each file of pull_files in the description play passes to pr create",
          (len(pulls760) > 0, {k: v for k, v in gaps760.items() if v}), (True, {}))
    check("#760 C1: pull_files is pull.md, then each push but behind, once",
          (pull_files({"id": "p", "opens": {"pull": {}}, "steps": [{"push": "secret"}, {"push": "behind"}, {"push": "secret"}, {"label": "x"}]}),
           pull_files({"id": "i", "opens": {"issue": {}}, "steps": [{"push": "conflict"}]})), (["scenarios/p/pull.md", "scenarios/p/secret.md"], []))
    st, fake = pushed()
    play({"id": "p", "opens": {"issue": {"title": "feat: x", "body": "f"}}, "steps": [{"push": "conflict"}], "expect": {}}, "o/t", "v7-next",
         dict(real["bodies"], f="f"), fake, lambda s: None, 1)
    landed = [i for a, i in st["io"] if a[:2] == ("pr", "create")]
    check("#760 C1: the pull request land opens to main names the path it writes, with the real `pull` body",
          (len(landed), unnamed(landed[0] if landed else "", ["scenarios/p/conflict.md"])), (1, []))
    bare = {"id": "bare-760", "opens": {"pull": {"title": "docs: x", "body": "pull", "issue": {"body": "task", "labels": ["accepted"]}}}, "expect": {}}
    nofiles = "## What changes\n\nA change of the scenarios.\n\n## Why\n\nCloses #{issue}"
    lands760 = {"id": "lands-760", "opens": {"issue": {"body": "task"}}, "steps": [{"push": "behind"}], "expect": {}}
    check("#760 C2: preconditions names a scenario whose pull request's body has no {files}, and one that lands through such a `pull` body",
          (preconditions([bare], {"pull": nofiles}, rpack, types={}), preconditions([lands760], {"pull": nofiles}, rpack, types={})),
          (["scenario bare-760: its pull request's body has no `{files}`, so its description names none of the files it changes"],
           ["scenario lands-760: the `pull` body has no `{files}`, so the pull request it lands on main through names none of the files it changes"]))
    check("#760 C2: the real file's scenarios' descriptions name their changes",
          [p for p in preconditions(real["scenarios"], real["bodies"], rpack, dispatchable(ROOT, rpack), types=real.get("types") or {}) if "{files}" in p or "does not name" in p], [])
    check("#760 C2: coverage fails on a scenario whose pull request's description would name no change, naming it",
          any(p.startswith("scenario bare-760:") and "{files}" in p for p in problems(dict(real, scenarios=real["scenarios"] + [bare], bodies=dict(real["bodies"], pull=nofiles)))), True)
    diffs760 = {}
    for s in ({"id": "secret-760", "opens": {"pull": {"title": "feat: x", "body": "pull"}}, "steps": [{"push": "secret"}], "expect": {}},
              {"id": "plain-760", "opens": {"pull": {"title": "docs: x", "body": "pull"}}, "expect": {}}):
        io = []
        play(s, "o/t", "v7-next", real["bodies"], described(io), lambda _: None, 1)
        diff = [p for _, branch, paths, _ in commits(io) if branch == branch_of(s) for p in paths]
        made = [i for a, i in io if a[:2] == ("pr", "create")]
        diffs760[s["id"]] = (diff, unnamed(made[0] if made else "", diff))
    check("#760 C3: every path the faked createCommitOnBranch writes on the pull request's head, its diff, is named in the description its pr create received",
          diffs760, {"secret-760": (["scenarios/secret-760/pull.md", "scenarios/secret-760/secret.md"], []), "plain-760": (["scenarios/plain-760/pull.md"], [])})
    # #778: a scenario's change is its own in each run, never what an
    # earlier run merged into main, so its pull request has a diff.
    by778 = {s["id"]: s for s in real["scenarios"]}

    def replay778(s, run_id):
        """The commits `play` makes for the scenario `s`, its `until`s
        taken out (they only poll), in the run `run_id`."""
        st, fake = pushed()
        play(dict(s, steps=[x for x in s.get("steps") or [] if "until" not in x]), "o/t", "v7-next", real["bodies"], fake, lambda _: None, 1,
             fork=fake, types=real.get("types") or {}, run_id=run_id)
        return commits(st["io"])
    four778 = ("draft-in-conflict", "ready-behind-main", "merge-queue", "low-risk-merges")
    main778, stale778, wrote778 = {}, {}, {}
    for sid in four778:
        for _, branch, _, files in replay778(by778[sid], "7-1"):
            for path, text in files.items():
                main778.setdefault(path, []).append(text)
        now = replay778(by778[sid], "8-1")
        wrote778[sid] = sorted({p for _, _, paths, _ in now for p in paths})
        stale778[sid] = stale_writes(now, main778, "8-1")
    check("#778 C1: the four failing scenarios, replayed on a main that holds an earlier run's texts, each write what main does not hold",
          (wrote778, {k: v for k, v in stale778.items() if v}),
          ({"draft-in-conflict": ["scenarios/draft-in-conflict/conflict.md"], "ready-behind-main": ["scenarios/ready-behind-main/behind.md"],
            "merge-queue": ["scenarios/merge-queue/pull.md"], "low-risk-merges": ["scenarios/low-risk-merges/pull.md"]}, {}))
    conflict778 = [files for _, _, _, files in replay778(by778["draft-in-conflict"], "8-1")]
    check("#778 C1: draft-in-conflict still conflicts: the head and main get two texts of the same file",
          (len(conflict778), len({t for f in conflict778 for t in f.values()})), (2, 2))
    check("#778 C1: stale_writes names a text main held already, and one with no run id",
          stale_writes([("o/t", "b", ["scenarios/x/pull.md"], {"scenarios/x/pull.md": "x"})], {"scenarios/x/pull.md": ["x"]}, "8-1"),
          ["b: scenarios/x/pull.md says what was there already: 'x'", "b: scenarios/x/pull.md does not carry the run's id 8-1: 'x'"])
    check("#778 C1: run_mark is the lane's run id and attempt, else a local time with a random suffix, and play_group passes one to play",
          (run_mark({"GITHUB_RUN_ID": "42", "GITHUB_RUN_ATTEMPT": "2"}), run_mark({}, now=5, rand="ab")), ("42-2", "local-5-ab"))
    io778 = []
    play_group({"scenarios": [by778["low-risk-merges"]], "bodies": real["bodies"], "types": real.get("types") or {}}, "low-risk-merges",
               "o/t", "v7-next", described(io778), lambda _: None, 1, run_id="9-3")
    check("#778 C1: play_group writes with the run id it is given",
          ["run 9-3" in t for _, _, _, f in commits(io778) for t in f.values()], [True])

    def twice778():
        """Every real scenario played twice, in the runs 101-1 and 202-1:
        what stale_writes finds in each run's texts under scenarios/<id>/
        (a `before`'s file aside, which says its `says`), the second's held
        against the first's (what main held after it), and how many texts
        were written."""
        out, count = {}, 0
        for s in real["scenarios"]:
            fixed = {f"scenarios/{s['id']}/{b['lands']}.md" for b in s.get("before") or [] if "lands" in b}
            runs = [[(r, b, [p for p in ps if p not in fixed], {p: t for p, t in fs.items() if p not in fixed and p.startswith(f"scenarios/{s['id']}/")})
                     for r, b, ps, fs in replay778(s, run_id)] for run_id in ("101-1", "202-1")]
            held = {}
            for _, _, _, files in runs[0]:
                for path, text in files.items():
                    held.setdefault(path, []).append(text)
            count += sum(len(f) for run in runs for _, _, _, f in run)
            got = stale_writes(runs[0], {}, "101-1") + stale_writes(runs[1], held, "202-1")
            if got:
                out[s["id"]] = got
        return out, count
    stale_twice, count_twice = twice778()
    check("#778 C2: every real scenario played twice writes, in each run, texts that carry its run id and differ from the other run's and from main's",
          (count_twice > 10, stale_twice), (True, {}))
    writer778 = scenario_text
    try:
        globals()["scenario_text"] = lambda sid, name, where, run_id: f"{name} on {where}\n"
        stale_free, _ = twice778()
    finally:
        globals()["scenario_text"] = writer778
    check("#778 C2: with a writer that leaves the run id out, the same check fails on the four scenarios that failed v7.14.0",
          set(four778) <= set(stale_free), True)
    # #699: the steps of the flow no person moves, each played or held.
    wanted699 = {"flow:a", "flow:b", "next_step:spec"}
    s699 = {"id": "p", "covers": ["flow:a", "next_step:spec"], "opens": {"issue": {}}, "expect": {"hands": ["accepted"]}}
    check("#699 C7: a flow with no scenario fails, named; `statically:` may hold a flow, with its test",
          (coverage([s699], wanted699), coverage([s699], wanted699, {"flow:b": "x.py --test"}), coverage([s699], wanted699, {"flow:c": "x"})),
          ([f"the flow flow:b has no scenario in {SCENARIOS}"], [], ["statically: flow:c is no transition of the state machine", f"the flow flow:b has no scenario in {SCENARIOS}"]))
    check("#699 C7: a scenario of the flow says its `hands`, names only the acceptance, and moves no other label",
          hands_problems([{"id": "n", "covers": ["flow:a"], "expect": {}}, {"id": "w", "covers": ["flow:a"], "expect": {"hands": ["needs-human"]}},
                          {"id": "l", "covers": ["flow:a"], "opens": {"pull": {"issue": {"labels": ["accepted"]}}}, "steps": [{"label": "autopilot:continue"}, {"unlabel": "needs-human"}], "expect": {"hands": ["accepted"]}},
                          {"id": "x", "covers": ["next_step:spec"], "steps": [{"label": "risk:low"}], "expect": {}}, s699]),
          ["scenario n: plays a step of the flow with no `hands` in its `expect`, so a label a person moved would not fail it",
           "scenario w: its `hands` names needs-human, which is the bot's to move (a person may move only accepted)",
           "scenario l: moves the label autopilot:continue by hand, which its `hands` does not name", "scenario l: moves the label needs-human by hand, which its `hands` does not name"])
    ev699 = [{"event": "labeled", "label": "accepted", "actor": "tester", "bot": False}, {"event": "labeled", "label": "autopilot:continue", "actor": "dilux-bot[bot]", "bot": True}]
    hand699 = ev699 + [{"event": "unlabeled", "label": "needs-human", "actor": "tester", "bot": False}]
    check("#699 C7: holds reads the label events: a label a person moved past `hands` fails, and can no longer hold; the bot's label and a re-run hold",
          (holds({"hands": ["accepted"], "bot_labeled": ["autopilot:continue"], "rerun": True}, {"label_events": ev699, "rerun": True}),
           holds({"hands": ["accepted"]}, {"label_events": hand699})[:1], hopeless({"hands": ["accepted"]}, {"label_events": hand699}),
           holds({"bot_labeled": ["autopilot:continue"], "rerun": True}, {"label_events": ev699[:1]})[:2]),
          ([], ["tester removed the label needs-human by hand"], ["tester removed the label needs-human by hand"],
           ["the bot never added autopilot:continue", "no run on its head ran again"]))
    other699 = ev699 + [{"event": "labeled", "label": "risk:low", "actor": "github-actions[bot]", "bot": False, "person": False}]
    check("#699 C7: another App's label is no person's hand, nor the bot's; a person is no bot of any kind",
          (holds({"hands": ["accepted"]}, {"label_events": other699}), holds({"bot_labeled": ["risk:low"]}, {"label_events": other699})[:1],
           [person_actor(a, t) for a, t in (("tester", "User"), ("github-actions[bot]", "Bot"), ("github-actions[bot]", None), ("app/renovate", None), ("dilux-bot", None), ("", None), ("someone", "Bot"))]),
          ([], ["the bot never added risk:low"], [True, False, False, False, False, False, False]))
    check("#699 C7: the poll budget counts a head's runs only for a check or a re-run, and a poll of the label events for `bot_labeled`",
          [poll_budget([s]) // (3600 // POLL) for s in ({"opens": {"pull": {}}}, {"opens": {"pull": {}}, "expect": {"rerun": True}},
                                                        {"opens": {"pull": {}}, "steps": [{"until": {"check": {"c": "failure"}}}]}, {"opens": {"issue": {}}, "expect": {"bot_labeled": ["x"]}})],
          [2, 3, 3, 3])

    def fake699(log, board=None, attempt=1):
        def fake(*a, input=None):
            log.append(a)
            if a[:2] == ("issue", "create"):
                return "https://github.com/o/t/issues/9\n"
            if a[:2] == ("issue", "view"):
                return json.dumps({"labels": [{"name": "accepted"}], "comments": [], "state": "OPEN", "closedByPullRequestsReferences": [{"number": 12}]})
            if a[:3] == ("pr", "view", "12"):
                said = [{"body": board, "author": {"login": "dilux-bot[bot]"}}] if board else []
                return json.dumps({"number": 12, "body": "Closes #9", "headRefName": "feat/9-x", "title": "feat: x", "isDraft": False, "comments": said})
            if a[:1] == ("api",) and str(a[1]).endswith("/events"):
                return "\n".join(json.dumps({k: e[k] for k in ("event", "label", "actor")}) for e in ev699) + "\n"
            return "[]"
        return fake
    import importlib.util as _ilu
    _rs = _ilu.spec_from_file_location("receipts699", os.path.join(HERE, "receipts.py"))
    _rc = _ilu.module_from_spec(_rs)
    _rs.loader.exec_module(_rc)
    board699 = _rc.BOARD + "\n" + _rc.state_block({"waits": {"role": "the autopilot", "what": "fix the failed check"}})
    log699 = []
    got699 = play({"id": "s", "opens": {"issue": {"title": "feat: x", "body": "f"}},
                   "steps": [{"retitle": "x"}, {"until": {"pull": {"waits": "^the autopilot$", "draft": "^False$"}}}],
                   "expect": {"bot_labeled": ["autopilot:continue"], "hands": ["accepted"]}}, "o/t", "v7-next", {"f": "f"}, fake699(log699, board699), lambda s: None, 1)
    check("#699 C7: play retitles the issue's pull request, waits on its board's role, and reads the label events of the issue and its pull request",
          (got699["ok"], ("pr", "edit", "12", "--repo", "o/t", "--title", "x") in log699,
           sorted(a[1] for a in log699 if a[:1] == ("api",) and str(a[1]).endswith("/events"))),
          (True, True, ["repos/o/t/issues/12/events", "repos/o/t/issues/9/events"]))
    log699 = []
    play({"id": "s", "opens": {"issue": {"title": "feat: x", "body": "f"}}, "expect": {"labels": ["never"], "hands": ["accepted"]}}, "o/t", "v7-next", {"f": "f"}, fake699(log699), lambda s: None, 1)
    check("#699 C7: the label events are read only once the rest of the expectation holds",
          [a for a in log699 if a[:1] == ("api",) and str(a[1]).endswith("/events")], [])
    tok = [scenario_text("s", "token", "the pull request", r).splitlines()[1] for r in ("7-1", "7-2")]
    check("#699 C5, #882: a `token` push writes a live-shaped token of 32 base62 characters, with no fake in it, its own per run; any other the scenario's text alone",
          ([bool(re.fullmatch(r"DX_API_TOKEN=dx_live_[A-Za-z0-9]{32}", t)) and "fake" not in t for t in tok], tok[0] != tok[1],
           scenario_text("s", "note", "main", "7-1").count("\n")), ([True, True], True, 1))
    flows_real = flows(real)
    check("#699 C7: the real file: each step of the flow is played by a scenario that moves no label but the acceptance, or held by its test, C2, C4 (#919) and C6",
          (sorted(flows_real), sorted(c for s in real["scenarios"] for c in s.get("covers") or [] if c.startswith("flow:")),
           sorted(k for k in real.get("statically") or {} if k.startswith("flow:")), hands_problems(real["scenarios"])),
          (sorted(f"flow:{f}" for f in ("marker-g1-start", "edit-starts", "conventions-fix", "hint-no-needs-human", "settled-rerun", "release-bug-reproduced")),
           ["flow:conventions-fix", "flow:marker-g1-start", "flow:settled-rerun"], ["flow:edit-starts", "flow:hint-no-needs-human", "flow:release-bug-reproduced"], []))
    # #929 C1: what passed on the same candidate does not play again, and counts.
    gs929 = [{"id": "a", "scenarios": ["a"]}, {"id": "b", "scenarios": ["b"]}]
    rows929 = [{"id": "a", "ok": True, "run": "r1"}, {"id": "b", "ok": False, "run": "r2"}, {"id": "callers", "ok": True}, {"id": "c", "ok": True, "in": "lane-1"}]
    check("#929 C1: passes_of keeps the passing scenarios, each in the run it first passed in",
          passes_of(rows929, {"a", "b", "c"}, "lane-2"), [{"id": "a", "in": "lane-2"}, {"id": "c", "in": "lane-1"}])
    check("#929 C1: drop_passed drops them, then the groups left empty", drop_passed(gs929, [{"id": "a", "in": "x"}]), [{"id": "b", "scenarios": ["b"]}])
    m929 = merge([{"id": "b", "scenarios": ["b"]}], {"move": [], "back": [], "b": [{"id": "b", "ok": True}]}, {"move": "success", "play": "success", "back": "success"},
                 passed=[{"id": "a", "in": "lane-1"}])
    check("#929 C1: merge adds a passing row for an earlier pass, naming its run", ([(r["id"], r["ok"], r.get("in")) for r in m929], "pass (in lane-1)" in table(m929)),
          ([("b", True, None), ("a", True, "lane-1")], True))
    check("#929 C1: nothing left to play, a skipped play job and no groups fail nothing",
          [r["id"] for r in merge([], {"move": [], "back": []}, {"move": "success", "play": "skipped", "back": "success"}, passed=[{"id": "a", "in": "l"}]) if not r["ok"]], [])
    calls929 = []

    def lane_gh(*a, input=None):
        calls929.append(a)
        if a[0] == "api":
            lane = {"event": "workflow_run", "head_branch": "main", "head_repository": {"full_name": "o/r"}}
            return json.dumps({"workflow_runs": [dict(lane, id=9, html_url="u9"), dict(lane, id=6, event="pull_request"), dict(lane, id=5, head_branch="x"),
                                                 dict(lane, id=4, head_repository={"full_name": "f/r"}), dict(lane, id=8, html_url="u8"), dict(lane, id=7, html_url="u7")]})
        d = a[a.index("--dir") + 1]
        if a[2] == "8":
            raise GhError("no artifact", 1, "", "no valid artifacts")
        key = {"sha": "S", "next": "N" if a[2] == "7" else "OLD"}
        open(os.path.join(d, "key.json"), "w").write(json.dumps(key))
        write_results([{"id": "a", "ok": True, "run": ""}], os.path.join(d, "results.md"), echo=False)
        return ""
    check("#929 C1: earlier_passes reads main's own lane runs newest first, skips this run, another event's, branch's or repository's, and one with no artifact, and takes the first with the key",
          (earlier_passes("o/r", "S", "N", "9", ["a"], lane_gh), [a[2] for a in calls929 if a[:2] == ("run", "download")]), ([{"id": "a", "in": "u7"}], ["8", "7"]))
    check("#929 C1: no key, no earlier passes", earlier_passes("o/r", "S", "", "9", ["a"], lambda *a, input=None: 1 / 0), [])
    # #929 C2: a re-run's artifacts over the first's, and its moves.
    with tempfile.TemporaryDirectory() as d929:
        for name, rows in (("scenarios-b-a1", [{"id": "b", "ok": False}]), ("scenarios-b-a2", [{"id": "b", "ok": True}]), ("scenarios-move", []), ("scenarios-results", [])):
            write_results(rows, os.path.join(d929, name, "results.md"), echo=False)
        got = latest_attempts(d929)
        check("#929 C2: latest_attempts keeps each name's latest attempt, one with none the first's",
              {k: os.path.basename(v) for k, v in got.items()}, {"b": "scenarios-b-a2", "move": "scenarios-move", "results": "scenarios-results"})
        for n, moved in ((1, [{"name": "a.yml", "before": "first"}]), (2, [{"name": "a.yml", "before": "second"}, {"name": "b.yml", "before": "b"}])):
            os.makedirs(os.path.join(d929, "moves", f"scenarios-move-a{n}"))
            write_moved(moved, os.path.join(d929, "moves", f"scenarios-move-a{n}", "moved.json"))
        check("#929 C2: read_moved_dir puts each caller back as the earliest attempt found it",
              read_moved_dir(os.path.join(d929, "moves"), "v7-next"), ([{"name": "a.yml", "before": "first"}, {"name": "b.yml", "before": "b"}], []))
        check("#929 C2: read_moved_dir with no record is could-not-tell", [r["id"] for r in read_moved_dir(os.path.join(d929, "none"), "v7-next")[1]], ["callers"])
    check("#929 C2: a group id read as an attempt or another artifact is unfit", [bool(unfit_group(g)) for g in ("b", "b-a2", "move-x", "results", "spec-to-draft")],
          [False, True, True, True, False])
    m929 = merge([{"id": "b", "scenarios": ["b"]}], {"move": [], "back": [], "b": [{"id": "callers", "ok": False, "why": ["x"]}]}, {"move": "success", "play": "failure", "back": "success"})
    check("#929 C2: a re-run's failed move is its group's callers row, with the scenario's missing row, and no play row",
          [(r["id"], r["ok"]) for r in m929], [("callers", False), ("b", False)])
    base929 = base64.b64encode(b"jobs:\n  t:\n    uses: O/.github/.github/workflows/x.yml@v7\n").decode()
    log929, views = [], []

    def busy(*a, input=None):
        log929.append(a)
        if a[:2] == ("pr", "list"):
            return json.dumps([{"number": 31, "url": "https://github.com/o/t/pull/31"}])
        if a[:2] == ("pr", "view"):
            views.append(a)
            return json.dumps({"mergedAt": "x"} if len(views) > 1 else {"state": "OPEN"})
        if a[-1] == "repos/o/t/contents/.github/workflows":
            return json.dumps([{"name": "a.yml"}])
        if a[-1] == "repos/o/t/contents/.github/workflows/a.yml":
            at = len(views) > 1
            return json.dumps({"content": base64.b64encode(at_ref(base64.b64decode(base929).decode(), "O/.github", "v7-next").encode()).decode() if at else base929})
        return "[]"
    check("#929 C2: point_callers with another job's pull request open waits for it, deletes no branch, opens nothing",
          (point_callers("o/t", "v7-next", busy, "O/.github", sleep=lambda s: None, minutes=3), len(views),
           [a for a in log929 if a[:3] == ("api", "-X", "DELETE") or a[:2] in (("pr", "create"), ("pr", "merge"), ("pr", "close"))]), ([], 2, []))

    def racing(listed_after, creates_ok_after, heads=("old",)):
        """A fake where creating `ci/callers-v7-next` answers 422 until
        `creates_ok_after` creates, and its pull request is listed only
        from the `listed_after`th listing on (another job started first)."""
        log, n = [], {"list": 0, "create": 0, "head": 0}

        def fake(*a, input=None):
            log.append(a)
            merged = n["list"] > listed_after
            if a[:2] == ("pr", "list"):
                n["list"] += 1
                return json.dumps([{"number": 31, "url": "https://github.com/o/t/pull/31"}] if n["list"] > listed_after else [])
            if a[:2] == ("pr", "view"):
                return json.dumps({"mergedAt": "x"})
            if a[:2] == ("api", "repos/o/t/git/refs"):
                n["create"] += 1
                if n["create"] <= creates_ok_after:
                    raise GhError("gh api: HTTP 422: Reference already exists", 1, "", "HTTP 422")
                return "{}"
            if a[:2] == ("api", "repos/o/t/git/ref/heads/ci/callers-v7-next"):
                n["head"] += 1
                return heads[min(n["head"], len(heads)) - 1] + "\n"
            if a[:2] == ("api", "graphql"):
                raise RuntimeError("stop here")
            if a[-1] == "repos/o/t/contents/.github/workflows":
                return json.dumps([{"name": "a.yml"}])
            if a[-1] == "repos/o/t/contents/.github/workflows/a.yml":
                text = base64.b64decode(base929).decode()
                return json.dumps({"content": base64.b64encode((at_ref(text, "O/.github", "v7-next") if merged else text).encode()).decode()})
            if a[-2:] == ("--jq", ".default_branch"):
                return "main\n"
            if a[-2:] == ("--jq", ".object.sha"):
                return "basehead\n"
            return "[]"
        return fake, log

    def outcome(fake, log):
        try:
            got = point_callers("o/t", "v7-next", fake, "O/.github", sleep=lambda s: None, minutes=30)
        except RuntimeError as e:
            got = str(e)
        return (got, sum(a[:3] == ("api", "-X", "DELETE") for a in log), sum(a[:2] == ("api", "repos/o/t/git/refs") for a in log),
                sum(a[:2] == ("pr", "create") for a in log))
    check("#929 C2: point_callers whose branch another job just created (422, its pull request not listed yet) waits for that pull request, deletes nothing, opens nothing",
          outcome(*racing(listed_after=2, creates_ok_after=9)), ([], 0, 1, 0))
    check("#929 C2: a leftover branch that stays the same with no pull request is deleted once it is stale, then made anew",
          outcome(*racing(listed_after=99, creates_ok_after=1)), ("stop here", 1, 2, 0))
    check("#929 C2: a branch that moves while it waits is another job's, never deleted",
          outcome(*racing(listed_after=3, creates_ok_after=9, heads=("old", "new", "newer", "newest"))), ([], 0, 1, 0))
    # #929 C3: a caller an earlier lane left at the ref goes back to what it was before.
    v7_929 = "jobs:\n  t:\n    uses: O/.github/.github/workflows/x.yml@v7\n"
    next_929 = at_ref(v7_929, "O/.github", "v7-next")

    def history(title):
        def fake(*a, input=None):
            last = str(a[-1])
            if last == "repos/o/t/contents/.github/workflows":
                return json.dumps([{"name": "a.yml"}, {"name": "plain.yml"}])
            if "/contents/.github/workflows/" in last:
                text = v7_929 if last.endswith("?ref=c1") else (next_929 if "a.yml" in last else "on: push\n")
                return json.dumps({"content": base64.b64encode(text.encode()).decode()})
            if a[-2:] == ("--jq", ".default_branch"):
                return "main\n"
            if "/commits?" in last:
                return json.dumps([{"commit": {"message": "docs: other"}, "parents": [{"sha": "c0"}]},
                                   {"commit": {"message": f"{title}\n\nbody"}, "parents": [{"sha": "c1"}]}])
            return "[]"
        return fake
    check("#929 C3: point_callers records a caller already at the ref as it was before the lane's pull request, opening nothing",
          point_callers("o/t", "v7-next", history("ci: the engine's callers at v7-next (#41)"), "O/.github"), [{"name": "a.yml", "before": v7_929}])
    check("#929 C3: move --record-only records the same, moving nothing",
          recorded_callers("o/t", "v7-next", history("ci: the engine's callers at v7-next (#41)"), "O/.github"), [{"name": "a.yml", "before": v7_929}])
    check("#929 C3: with no lane pull request in its history (at the ref by hand, or another ref's), nothing is recorded",
          [point_callers("o/t", "v7-next", history(t), "O/.github") for t in ("ci: something else", "ci: the engine's callers at v7")], [[], []])
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
        conf = load_yaml(os.path.join(ROOT, SCENARIOS))
        scenarios = conf.get("scenarios") or []
        wrong = timing(scenarios, conf.get("bodies") or {})
        for line in wrong:
            print(line, file=sys.stderr)
        print(json.dumps(scenario_plan(scenarios), separators=(",", ":")))
        return 1 if wrong else 0
    if argv[:1] == ["groups"] and (len(argv) == 1 or (len(argv) == 3 and argv[1] == "--passed")):
        scenarios = load_yaml(os.path.join(ROOT, SCENARIOS)).get("scenarios") or []
        gs, wrong = groups(scenarios), partition(scenarios, groups(scenarios), test_pack())
        for line in wrong:
            print(line, file=sys.stderr)
        if wrong:
            return 1
        if len(argv) == 3:
            gs = drop_passed(gs, read_passed(argv[2]))
        print(json.dumps(gs, separators=(",", ":")))
        return 0
    if argv[:1] == ["passed"]:
        import argparse
        p = argparse.ArgumentParser(prog="release-scenarios.py passed")
        p.add_argument("--repo", required=True)
        p.add_argument("--sha", default="")
        p.add_argument("--next", default="")
        p.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
        p.add_argument("--out", required=True)
        a = p.parse_args(argv[1:])
        ids = [s.get("id") for s in load_yaml(os.path.join(ROOT, SCENARIOS)).get("scenarios") or []]
        try:
            got = earlier_passes(a.repo, a.sha, a.next, a.run_id, ids)
        except (RuntimeError, ValueError) as e:
            # Could not read them: every scenario plays, as on a new candidate.
            print(f"::warning::the earlier runs on this candidate could not be read, every scenario plays: {e}", file=sys.stderr)
            got = []
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(got, fh, separators=(",", ":"))
        print(f"{len(got)} scenario(s) passed on this candidate before: {', '.join(p['id'] for p in got) or 'none'}", file=sys.stderr)
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
            p.add_argument("--record-only", action="store_true")
        else:
            p.add_argument("--group", required=True)
        a = p.parse_args(argv[1:])
        if argv[0] == "move" and a.record_only:
            # #929: nothing left to play, so no caller moves; what `back`
            # puts back is recorded all the same.
            write_moved(recorded_callers(a.repo, a.ref, callers_gh()), a.moved)
            results = []
        elif argv[0] == "move":
            results = move_callers(a.repo, a.ref, callers_gh(), minutes=a.minutes, record=lambda m: write_moved(m, a.moved))[1]
        else:
            results = play_watched(load_yaml(os.path.join(ROOT, SCENARIOS)), a.group, a.repo, a.ref, a.minutes, a.out)
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
        p.add_argument("--passed", default="")
        a = p.parse_args(argv[1:])
        jobs = dict(j.split("=", 1) if "=" in j else (j, "") for j in a.job)
        results = merge_dir(a.dir, read_groups(a.groups), jobs, a.run, a.minutes, a.play_minutes, read_passed(a.passed) if a.passed else ())
        # #843: what the runs triggered, never what `covers:` says; a
        # warning that fails nothing.
        write_results(results, a.out, run_coverage(results, played(ROOT, test_pack())))
        return 0 if all(r["ok"] for r in results) else 1
    if argv[:1] == ["back"]:
        import argparse
        p = argparse.ArgumentParser(prog="release-scenarios.py back")
        p.add_argument("--repo", required=True)
        p.add_argument("--ref", default="v7-next")
        where = p.add_mutually_exclusive_group(required=True)
        where.add_argument("--moved")
        where.add_argument("--moved-dir")
        p.add_argument("--out", default="")
        p.add_argument("--minutes", type=int, default=20)
        a = p.parse_args(argv[1:])
        moved, unread = read_moved_dir(a.moved_dir, a.ref) if a.moved_dir else read_moved(a.moved, a.ref)
        results = (read_results(a.out) if a.out else []) + unread + put_back(a.repo, a.ref, moved, callers_gh(), minutes=a.minutes)
        write_results(results, a.out)
        return 0 if all(r["ok"] for r in results) else 1
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
