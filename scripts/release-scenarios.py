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
that covers it. A scenario: `id`, `covers` (pairs `<workflow>:<event>`,
transitions `next_step:<action>`, `next_step:wait:<for>`,
`next_step:merge-main:<how>`, `sweep_step:<what>`), `before` (issues it
opens first and keeps open until it ends, each `{issue: {...}}`), `opens`
(an `issue` or a `pull` with its `title`, `body` (a name of `bodies:` or the
text), `labels`, and `fork: true` for one from a fork; a pull's `{issue}` in
its body is the number of the issue it opens first, its `issue:` or a
complete feature), `steps` (each one of
`comment`, `label`, `unlabel`, `edit`, `push`, `dispatch`, `wait`) and
`expect` (`labels`, `absent`, `comments` (markers), `pull` (`closes`,
`branch`, `title`, patterns), `check` (name: conclusion), `merged`,
`waiting`).

  release-scenarios.py coverage [ROOT]
        fails naming every pair and transition with no scenario, every
        scenario that covers what is neither, and every scenario whose
        `expect` cannot hold against its own setup (`preconditions`: a
        dispatch of a workflow the test repository cannot run on demand
        among them). Every other pair a shipped caller wires is held to the
        engine statically, by scripts/caller-contract.py check
  release-scenarios.py run --repo OWNER/NAME [--ref v7-next] [--only ID ...]
                           [--out FILE] [--minutes N]
        plays them in the test repository with the test identity's token
        (GH_TOKEN), polls until each one's `expect` holds or its time is
        up, cleans up (its pack's `cleanup: after-run`) and writes the
        Markdown table of results (scenario, pass or fail, run link) to
        FILE (and stdout); exits 1 when one fails
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


def coverage(scenarios, wanted):
    """What has no scenario, and what a scenario covers that is not wanted:
    ["... has no scenario"]. Pure."""
    covered, out, seen = set(), [], set()
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
    for w in sorted(wanted - covered):
        kind = "the transition" if w.startswith(("next_step:", "sweep_step:")) else "the pair"
        out.append(f"{kind} {w} has no scenario in {SCENARIOS}")
    return out


CORE_LABEL, CORE_MARK = "autopilot:core-wait", "<!-- dx-autopilot-core -->"


def preconditions(scenarios, bodies, pack, can_dispatch=(), passes=None):
    """Every scenario whose `expect` its own setup can never make hold
    (#563): a pull's `closes` with no `{issue}` in its body (a fixed number
    is another object's), a wait on the core with no open issue before it
    or a test repository whose fixed change touches no core, a `dispatch` of
    a workflow the test repository cannot run on demand (`can_dispatch`),
    and an issue that should await acceptance whose body the schema refuses
    (`passes(body)`: the triage would call it `incomplete`). Pure."""
    import fnmatch
    out = []
    for s in scenarios:
        sid, expect, opens = s.get("id") or "?", s.get("expect") or {}, s.get("opens") or {}
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
        if CORE_LABEL in (expect.get("labels") or []) or CORE_MARK in (expect.get("comments") or []):
            first = [b.get("issue") or {} for b in s.get("before") or []]
            if not any("accepted" in (i.get("labels") or []) for i in first):
                out.append(f"scenario {sid}: expects a wait on the core, but opens no accepted issue before it whose pull request stays open")
            fixed = str((pack.get("fixed-change") or {}).get("file") or "").replace("{n}", "1").replace("{id}", "c1")
            if not any(fnmatch.fnmatchcase(fixed, g) for g in pack.get("core") or []):
                out.append(f"scenario {sid}: expects a wait on the core, but the test repository's fixed change ({fixed or 'none'}) touches no core of its pack")
    return out


# Playing them.

def body_of(value, bodies):
    return bodies.get(value, value) if isinstance(value, str) else ""


def holds(expect, seen):
    """What of `expect` does not hold in `seen` (labels, comments, pull,
    checks, merged, waiting): [] when it all does. Pure."""
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
        got = (seen.get("checks") or {}).get(name)
        if got != conclusion:
            out.append(f"check {name} is {got or 'missing'}, not {conclusion}")
    for key in ("merged", "waiting"):
        if key in expect and bool(seen.get(key)) != bool(expect[key]):
            out.append(f"{key} is {bool(seen.get(key))}")
    return out


def table(results):
    """The Markdown table of results. Pure."""
    lines = ["| Scenario | Result | Run |", "| --- | --- | --- |"]
    for r in results:
        why = f" ({'; '.join(r['why'])})" if r.get("why") else ""
        lines.append(f"| `{r['id']}` | {'pass' if r['ok'] else 'fail'}{why} | {r.get('run') or ''} |")
    return "\n".join(lines) + "\n"


def gh(*args, input=None):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, input=input)
    if out.returncode:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {out.stderr.strip()}")
    return out.stdout


def open_issue(repo, spec, bodies, default, run=gh):
    url = run("issue", "create", "--repo", repo, "--title", spec.get("title", default), "--body-file", "-",
              *sum((["--label", l] for l in spec.get("labels") or []), []), input=body_of(spec.get("body"), bodies)).strip()
    return url.rstrip("/").rsplit("/", 1)[-1]


def play(s, repo, ref, bodies, run=gh, sleep=time.sleep, minutes=20):
    """One scenario in `repo`: opens what it opens (its `before` first),
    takes its steps, polls until its `expect` holds or `minutes` pass, then
    cleans up. Returns {id, ok, why, run}."""
    opens, made, closes = s.get("opens") or {}, [], None
    what = "pr" if "pull" in opens else "issue"
    spec = opens.get("pull") or opens.get("issue") or {}
    try:
        for first in s.get("before") or []:
            made.append(("issue", open_issue(repo, first.get("issue") or {}, bodies, f"{s['id']}: before", run)))
        if what == "issue":
            url = open_issue(repo, spec, bodies, s["id"], run)
        else:
            text = body_of(spec.get("body"), bodies)
            if "{issue}" in text:
                closes = open_issue(repo, spec.get("issue") or {"title": spec.get("title", s["id"]), "body": "complete-feature"}, bodies, s["id"], run)
                made.append(("issue", closes))
                text = text.replace("{issue}", closes)
            branch, target = f"scenario/{s['id']}", repo
            if spec.get("fork"):
                # From the test identity's fork, which runs with no secrets.
                run("repo", "fork", repo, "--clone=false", "--default-branch-only")
                target = f"{run('api', 'user', '--jq', '.login').strip()}/{repo.split('/', 1)[1]}"
            run("api", f"repos/{target}/git/refs", "-f", f"ref=refs/heads/{branch}", "-f", f"sha={run('api', f'repos/{target}/commits/HEAD', '--jq', '.sha').strip()}")
            run("api", "-X", "PUT", f"repos/{target}/contents/scenarios/{s['id']}.md", "-f", f"message=test: scenario {s['id']}",
                "-f", f"branch={branch}", "-f", f"content={__import__('base64').b64encode(s['id'].encode()).decode()}")
            head = f"{target.split('/', 1)[0]}:{branch}" if target != repo else branch
            url = run("pr", "create", "--repo", repo, "--head", head, "--title", spec.get("title", f"test: {s['id']}"),
                      "--body-file", "-", input=text).strip()
        number = url.rstrip("/").rsplit("/", 1)[-1]
        made.append((what, number))
        for step in s.get("steps") or []:
            (verb, arg), = step.items()
            if verb == "comment":
                run(what, "comment", number, "--repo", repo, "--body", str(arg))
            elif verb in ("label", "unlabel"):
                run(what, "edit", number, "--repo", repo, f"--{'add' if verb == 'label' else 'remove'}-label", str(arg))
            elif verb == "edit":
                run(what, "edit", number, "--repo", repo, "--body-file", "-", input=body_of(arg, bodies))
            elif verb == "dispatch":
                run("workflow", "run", str(arg), "--repo", repo, "--ref", "main")
            elif verb == "push":
                run("api", "-X", "PUT", f"repos/{repo}/contents/scenarios/{s['id']}-{arg}.md", "-f", f"message=test: {arg}",
                    "-f", f"branch=scenario/{s['id']}", "-f", "content=eA==")
            elif verb == "wait":
                sleep(int(arg))
        deadline, why = minutes * 60, ["not played"]
        while True:
            seen = observe(repo, what, number, run)
            if closes:
                seen["closes"] = closes
            why = holds(s.get("expect") or {}, seen)
            if not why or deadline <= 0:
                break
            sleep(30)
            deadline -= 30
        return {"id": s["id"], "ok": not why, "why": why, "run": seen.get("run", "")}
    except (RuntimeError, ValueError) as e:
        return {"id": s["id"], "ok": False, "why": [str(e)], "run": ""}
    finally:
        cleanup(repo, made, run)


def observe(repo, what, number, run=gh):
    fields = "labels,comments,body,state" + (",mergedAt,statusCheckRollup,headRefName,title" if what == "pr" else ",closedByPullRequestsReferences")
    view = json.loads(run(what, "view", number, "--repo", repo, "--json", fields) or "{}")
    seen = {"number": number, "labels": [l.get("name") for l in view.get("labels") or []],
            "comments": [c.get("body", "") for c in view.get("comments") or []]}
    if what == "pr":
        seen["pull"] = {"body": view.get("body"), "branch": view.get("headRefName"), "title": view.get("title")}
        seen["merged"] = bool(view.get("mergedAt"))
        seen["checks"] = {c.get("name"): (c.get("conclusion") or "").lower() for c in view.get("statusCheckRollup") or []}
    else:
        pulls = json.loads(run("pr", "list", "--repo", repo, "--search", f"Closes #{number} in:body", "--json", "number,body,headRefName,title", "--limit", "1") or "[]")
        if pulls:
            seen["pull"] = {"body": pulls[0].get("body"), "branch": pulls[0].get("headRefName"), "title": pulls[0].get("title")}
    seen["waiting"] = any(l in seen["labels"] for l in ("needs-human", "autopilot:waiting", "awaiting-acceptance"))
    runs = json.loads(run("run", "list", "--repo", repo, "--limit", "1", "--json", "url") or "[]")
    seen["run"] = runs[0]["url"] if runs else ""
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
    dropped. Pure."""
    return re.sub(r"^(\s+uses: " + re.escape(central) + r"/\.github/workflows/[\w.-]+\.yml)@\S+([ \t]+#[^\n]*)?$", rf"\1@{ref}", text, flags=re.M)


def point_callers(repo, ref, run=gh, central=None):
    """The test repository's callers at `ref` (`v7-next` while the lane
    tries a candidate, `v7` once the installer plays them), so what plays
    is that ref's engine. Returns the callers it rewrote."""
    import base64
    if central is None:
        sys.path.insert(0, HERE)
        import org
        central = org.CENTRAL
    moved = []
    for f in json.loads(run("api", f"repos/{repo}/contents/.github/workflows") or "[]"):
        if not str(f.get("name", "")).endswith(".yml"):
            continue
        got = json.loads(run("api", f"repos/{repo}/contents/.github/workflows/{f['name']}") or "{}")
        text = base64.b64decode(got.get("content") or "").decode()
        new = at_ref(text, central, ref)
        if new != text:
            run("api", "-X", "PUT", f"repos/{repo}/contents/.github/workflows/{f['name']}", "-f", f"message=ci: the engine at {ref}",
                "-f", f"content={base64.b64encode(new.encode()).decode()}", "-f", f"sha={got.get('sha', '')}")
            moved.append(f["name"])
    return moved


def run_all(conf, repo, ref, only=(), run=gh, sleep=time.sleep, minutes=20, central=None):
    bodies = conf.get("bodies") or {}
    point_callers(repo, ref, run, central)
    return [play(s, repo, ref, bodies, run, sleep, minutes) for s in conf.get("scenarios") or [] if not only or s["id"] in only]


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


def problems(conf, root=ROOT):
    """What `coverage` names: every played pair and transition with no
    scenario, and every scenario its setup cannot make hold."""
    pack = test_pack(root)
    return (coverage(conf.get("scenarios") or [], played(root, pack) | transitions(root))
            + preconditions(conf.get("scenarios") or [], conf.get("bodies") or {}, pack, dispatchable(root, pack), schema_passes(root)))


def self_test():
    failed = 0

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
    real = load_yaml(os.path.join(ROOT, SCENARIOS))
    check("C2: every pair the test repository plays, and every transition, has its scenario; every scenario can hold", problems(real), [])
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
          (preconditions([pr_fixed], {"pull": "Closes #1"}, pack), preconditions([pr_fixed], {"pull": "Closes #{issue}"}, pack)),
          (["scenario p: expects its pull request to close an issue, but its body names no `{issue}` it opens"], []))
    check("preconditions: a wait on the core needs an accepted issue before it, and a fixed change on the core",
          (len(preconditions([core_alone], {}, pack)), len(preconditions([dict(core_alone, before=[{"issue": {"labels": ["accepted"]}}])], {}, dict(pack, core=["scripts/*"]))),
           preconditions([dict(core_alone, before=[{"issue": {"labels": ["accepted"]}}])], {}, pack)), (1, 1, []))
    check("holds: a pull scenario's closes is the issue it opened, never its own number",
          (holds({"pull": {"closes": True}}, {"number": "12", "closes": "11", "pull": {"body": "Closes #11"}}),
           holds({"pull": {"closes": True}}, {"number": "12", "closes": "1", "pull": {"body": "Closes #11"}})), ([], ["the pull request does not say Closes #1"]))
    covered = {c for s in real.get("scenarios") or [] for c in s.get("covers") or []}
    check("#585: a caller that does not grant what the engine asks has its scenario", any(s["id"] == "caller-permission-585" for s in real["scenarios"]), True)
    check("the pairs are read from the real callers", {"issue-triage.yml:issues", "claude-review.yml:pull_request", "autopilot.yml:pull_request"} <= covered, True)
    seen = {"number": "4", "labels": ["autopilot", "awaiting-acceptance"], "comments": ["<!-- dx-x -->"], "pull": {"body": "Closes #4", "branch": "feat/4-x", "title": "feat: x"}, "checks": {"g": "success"}, "merged": False}
    check("holds: what holds is nothing", holds({"labels": ["autopilot"], "comments": ["<!-- dx-x -->"], "pull": {"closes": True, "branch": "^feat/4-"}, "check": {"g": "success"}, "merged": False}, seen), [])
    check("holds: what does not is named", holds({"labels": ["accepted"], "absent": ["autopilot"], "merged": True}, seen), ["no label accepted", "label autopilot still there", "merged is False"])
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
    res = run_all(scen, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=1, central="O/.github")
    check("run: a scenario whose expect holds passes, one whose does not fails, named", [(r["id"], r["ok"], r["why"]) for r in res], [("a", True, []), ("b", False, ["no label accepted"])])
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
    check("run: a pull scenario opens the issue its pull request closes, and passes on it", (got["ok"], [a[:2] for a, _ in pcalls_][:1], ("issue", "close", "11", "--repo", "o/t") in [a for a, _ in pcalls_]), (True, [("issue", "create")], True))
    first = []
    play({"id": "c", "before": [{"issue": {"title": "first", "labels": ["accepted"]}}], "opens": {"issue": {"title": "second"}}, "expect": {}},
         "o/t", "v7-next", {}, lambda *a, input=None: first.append(a) or ("https://github.com/o/t/issues/9\n" if a[:2] == ("issue", "create") else "{}" if a[:2] == ("issue", "view") else "[]"), lambda s: None, 1)
    check("run: `before` opens its issue first and closes it only after", ([a[5] for a in first if a[:2] == ("issue", "create")], first.index(("issue", "close", "9", "--repo", "o/t")) > 2), (["first", "second"], True))
    import base64
    caller = "jobs:\n  t:\n    uses: O/.github/.github/workflows/issue-triage.yml@abc123 # v7\n"
    check("at_ref: a pinned call moves to the ref tried", at_ref(caller, "O/.github", "v7-next"), "jobs:\n  t:\n    uses: O/.github/.github/workflows/issue-triage.yml@v7-next\n")
    pcalls = []

    def pfake(*args, input=None):
        pcalls.append(args)
        if args[-1] == "repos/o/t/contents/.github/workflows":
            return json.dumps([{"name": "issues.yml"}])
        if args[-1].endswith("issues.yml"):
            return json.dumps({"content": base64.b64encode(caller.encode()).decode(), "sha": "s1"})
        return ""
    check("run: the test repository's callers call the ref tried", (point_callers("o/t", "v7-next", pfake, "O/.github"), any(c[:3] == ("api", "-X", "PUT") for c in pcalls)), (["issues.yml"], True))
    check("run: the table names each scenario, its result and its run", table(res).splitlines()[2], "| `a` | pass | https://github.com/o/t/actions/runs/1 |")
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
        a = p.parse_args(argv[1:])
        results = run_all(load_yaml(os.path.join(ROOT, SCENARIOS)), a.repo, a.ref, a.only, minutes=a.minutes)
        text = table(results)
        sys.stdout.write(text)
        if a.out:
            with open(a.out, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.write(f"\n<!-- dx-scenarios {json.dumps(results)} -->\n")
        return 0 if all(r["ok"] for r in results) else 1
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
