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
        sleep(30)
        waited += 30


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
            changes.append((name, text, new, got.get("sha", "")))
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
    for name, _, new, sha in changes:
        run("api", "-X", "PUT", f"repos/{repo}/contents/.github/workflows/{name}", "-f", f"message={title}",
            "-f", f"branch={branch}", "-f", f"content={base64.b64encode(new.encode()).decode()}", "-f", f"sha={sha}")
    url = run("pr", "create", "--repo", repo, "--base", base, "--head", branch, "--title", title, "--body-file", "-",
              input=f"The release lane's scenarios (scripts/release-scenarios.py): {title[4:]}.\n").strip()
    number = url.rstrip("/").rsplit("/", 1)[-1]
    try:
        pull = json.loads(run("api", f"repos/{repo}/pulls/{number}") or "{}")
        base_sha, head = pull["base"]["sha"], pull["head"]["sha"]
        differs = not_only_ref(repo, number, base_sha, head, [name for name, _, _, _ in changes], central, run)
        if differs:
            raise RuntimeError(f"the pull request {url} that moves them changes more than the engine's ref, so the lane does not merge it: {differs}")
        merge_when_checked(repo, number, url, head, run, sleep, minutes)
    except (RuntimeError, ValueError):
        try:
            run("pr", "close", number, "--repo", repo, "--delete-branch")
        except RuntimeError:
            pass
        raise
    return [{"name": name, "before": text} for name, text, _, _ in changes]


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
    try:
        moved = point_callers(repo, ref, callers, central, sleep=sleep, minutes=minutes)
    except (RuntimeError, ValueError) as e:
        if record:
            record([])
        return [{"id": "callers", "ok": False, "why": [f"the callers did not reach {ref}: {e}"], "run": ""}]
    if record:
        record(moved)
    if moved_out is not None:
        moved_out.extend(moved)
    results = []
    try:
        for s in conf.get("scenarios") or []:
            if not only or s["id"] in only:
                results.append(play(s, repo, ref, bodies, run, sleep, minutes))
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


DEFAULTS = ("main", "master")


def _lead(node):
    """A string argument's text, or an f-string's text with its values as
    `{}`; None for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
    return None


def default_writes(source):
    """Every `PUT` to a `contents/` path in `source` that does not name a
    branch other than the default (`branch=` missing, or `branch=main`):
    ["line N: ..."]. A default branch is protected by its rulesets, so
    nothing here writes one. Pure."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        texts = [_lead(a) for a in node.args]
        if "PUT" not in texts or not any(t and "contents/" in t for t in texts):
            continue
        branches = [t.split("=", 1)[1] for t in texts if t and t.startswith("branch=")]
        if not branches or any(b in DEFAULTS for b in branches):
            out.append(f"line {node.lineno}: a PUT to contents/ that writes the default branch ({'branch=' + branches[0] if branches else 'no branch='})")
    return out


def put_default(calls):
    """The recorded `gh` calls that write a contents path on the default
    branch. Pure."""
    return [c for c in calls if tuple(c[:3]) == ("api", "-X", "PUT") and "/contents/" in str(c[3])
            and not any(str(x).startswith("branch=") and str(x)[7:] not in DEFAULTS for x in c[4:])]


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
    check("at_ref: a call already at the ref keeps its pin's comment", at_ref(caller.replace("abc123", "v7-next"), "O/.github", "v7-next"), caller.replace("abc123", "v7-next"))

    def repo_fake(merges=True, pending=1, tamper=None):
        """A test repository with issues.yml at `@abc123 # v7`, whose pull
        requests' required check is pending for `pending` polls then
        passes, and which merge (their branch's callers reach main) on the
        view after the lane queues them, or close unmerged (`merges` False),
        or never merge (None). `tamper(st, branch)`, when given, changes the
        branch after the lane wrote it, before the pull request opens."""
        st = {"main": {"issues.yml": caller}, "branches": {}, "prs": {}, "polls": {}, "queued": set(), "calls": [], "files": None}

        def at(number, side):
            pr = st["prs"][number]
            return pr["base"] if side == "base" else st["branches"][pr["head"]]

        def fake(*args, input=None):
            st["calls"].append(args)
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
            if args[:3] == ("api", "-X", "PUT") and "/contents/.github/workflows/" in args[3]:
                f = dict(x.split("=", 1) for x in args[4:] if "=" in x)
                st["branches"][f["branch"]][args[3].rsplit("/", 1)[1]] = base64.b64decode(f["content"]).decode()
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
    got = run_all(one, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=1, central="O/.github")
    calls = st["calls"]
    writes = [c for c in calls if c[:3] == ("api", "-X", "PUT")]
    check("C1: the callers move on ci/callers-v7-next, created from main's head",
          ("api", "repos/o/t/git/refs", "-f", "ref=refs/heads/ci/callers-v7-next", "-f", "sha=h1") in calls, True)
    check("C1: @v7-next is written there, not on main",
          ("branch=ci/callers-v7-next" in writes[0], "issue-triage.yml@v7-next\n" in base64.b64decode(next(x for x in writes[0] if x.startswith("content=")).split("=", 1)[1]).decode()), (True, True))
    queue = ("pr", "merge", "20", "--repo", "o/t", "--squash", "--match-head-commit", "head-20")
    check("#623 C1: a pull request is opened, and the lane enables no auto-merge",
          (calls.index(next(c for c in calls if c[:2] == ("pr", "create"))) < calls.index(queue), [c for c in calls if "--auto" in c]), (True, []))
    checks = [i for i, c in enumerate(calls) if c[:3] == ("pr", "checks", "20")]
    check("#623 C1: it waits for the required checks, then queues it at the head they passed on",
          (len(checks) >= 2, all("--required" in calls[i] for i in checks), checks[-1] < calls.index(queue), sum(1 for c in calls if c[:3] == ("pr", "merge", "20"))), (True, True, True, 1))
    check("C1: the first scenario plays only after the pull request merged",
          (calls.index(("merged", "20")) < calls.index(next(c for c in calls if c[:2] == ("issue", "create"))), [r["id"] for r in got], got[0]["ok"]), (True, ["a"], True))
    check("C1: the callers are put back, pin and comment, through a second merged pull request",
          (st["main"]["issues.yml"], ("merged", "21") in calls, "branch=ci/callers-v7-next-back" in writes[1]), (caller, True, True))
    check("#623 C1: on the way back too, it waits for the checks and queues it itself, with no auto-merge",
          (calls.index(next(c for c in calls if c[:3] == ("pr", "checks", "21"))) < calls.index(("pr", "merge", "21", "--repo", "o/t", "--squash", "--match-head-commit", "head-21"))
           < calls.index(("merged", "21")), [c for c in calls if "--auto" in c]), (True, []))
    st, fake = repo_fake()
    st["main"]["issues.yml"] = at_ref(caller, "O/.github", "v7-next")
    run_all(one, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=1, central="O/.github")
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
        got = run_all(one, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=1, central="O/.github")
        check(f"#623 C2: a pull request with {how} under .github/workflows is never merged, plays no scenario, is closed, and is one failing callers row naming it",
              (any(c[:2] in (("pr", "merge"), ("issue", "create")) or c[0] == "merged" for c in st["calls"]), ("pr", "close", "20", "--repo", "o/t", "--delete-branch") in st["calls"],
               [(r["id"], r["ok"]) for r in got], "https://github.com/o/t/pull/20" in got[0]["why"][0], st["main"]["issues.yml"]),
              (False, True, [("callers", False)], True, caller))
    st, fake = repo_fake(tamper=another_line)
    got = run_all(one, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=1, central="O/.github")
    check("#623 C2: the failing row names the file and the line that differ",
          got[0]["why"], ["the callers did not reach v7-next: the pull request https://github.com/o/t/pull/20 that moves them changes more than the engine's ref, "
                          "so the lane does not merge it: .github/workflows/issues.yml line 4: 'permissions: write-all'"])
    st, fake = repo_fake()
    failing = lambda *a, input=None: json.dumps([{"name": "gate", "bucket": "fail"}]) if a[:2] == ("pr", "checks") else fake(*a, input=input)
    got = run_all(one, "o/t", "v7-next", run=failing, sleep=lambda s: None, minutes=1, central="O/.github")
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
        got = run_all(one, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=1, central="O/.github")
        check(f"C1: a pull request that {how} plays no scenario and gives one failing callers row",
              (any(c[:2] == ("issue", "create") for c in st["calls"]), [(r["id"], r["ok"]) for r in got], st["main"]["issues.yml"]), (False, [("callers", False)], caller))
    st, fake = repo_fake()
    moved = []
    got = run_all(one, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=1, central="O/.github", moved_out=moved)
    check("#622: with moved_out the scenarios play at the ref and the callers are left there for put_back",
          ([r["id"] for r in got], [m["name"] for m in moved], ("merged", "21") in st["calls"], "issue-triage.yml@v7-next\n" in st["main"]["issues.yml"]), (["a"], ["issues.yml"], False, True))
    fresh = []
    check("#622: put_back, with the runner given it (a token minted after the scenarios), puts them back",
          (put_back("o/t", "v7-next", moved, lambda *a, input=None: fresh.append(a) or fake(*a, input=input), "O/.github", lambda s: None, 1), st["main"]["issues.yml"], any(c[:2] == ("pr", "create") for c in fresh)), ([], caller, True))
    check("#623 C1: put_back queues its pull request itself, at its head, once its checks passed",
          ([c for c in fresh if c[:2] == ("pr", "merge")], [c for c in fresh if "--auto" in c], any(c[:2] == ("pr", "checks") for c in fresh)),
          ([("pr", "merge", "21", "--repo", "o/t", "--squash", "--match-head-commit", "head-21")], [], True))
    check("#622: put_back with nothing moved does nothing", put_back("o/t", "v7-next", [], lambda *a, input=None: 1 / 0), [])
    st, fake = repo_fake()
    moved = []
    run_all(one, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=1, central="O/.github", moved_out=moved)

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
        path = os.path.join(d, "moved.json")
        st, fake = repo_fake()
        seen = []

        def plays(*a, input=None):
            if a[:2] == ("issue", "create") and not seen:
                seen.append(read_moved(path, "v7-next"))
            return fake(*a, input=input)
        run_all(one, "o/t", "v7-next", run=plays, sleep=lambda s: None, minutes=1, central="O/.github", moved_out=[], record=lambda m: write_moved(m, path))
        check("#622: what moved is written before the first scenario plays",
              [([m["name"] for m in got], rows) for got, rows in seen], [(["issues.yml"], [])])
        st, fake = repo_fake(False)
        run_all(one, "o/t", "v7-next", run=fake, sleep=lambda s: None, minutes=1, central="O/.github", moved_out=[], record=lambda m: write_moved(m, path))
        check("#622: a pointing that fails cleanly writes nothing moved", read_moved(path, "v7-next"), ([], []))
        check("#622: a missing moved file is one failing callers row",
              [(r["id"], r["ok"]) for r in read_moved(os.path.join(d, "gone.json"), "v7-next")[1]], [("callers", False)])
        for bad in ("{not json", '{"a": 1}', '[{"name": "x"}]'):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(bad)
            check(f"#622: an unreadable moved file ({bad}) is one failing callers row",
                  [(r["id"], r["ok"]) for r in read_moved(path, "v7-next")[1]], [("callers", False)])
    own = open(os.path.abspath(__file__), encoding="utf-8").read()
    check("C2: nothing in this script writes a default branch through the contents API", default_writes(own), [])
    check("C2: a PUT to contents/ on main, or with no branch, is named",
          default_writes('run("api", "-X", "PUT", f"repos/{r}/contents/x", "-f", "branch=main")\nrun("api", "-X", "PUT", f"repos/{r}/contents/{p}", "-f", "content=x")\n'),
          ["line 1: a PUT to contents/ that writes the default branch (branch=main)", "line 2: a PUT to contents/ that writes the default branch (no branch=)"])
    st, fake = repo_fake()
    recorded = []
    run_all({"scenarios": [{"id": "p", "opens": {"pull": {"title": "t", "body": "x"}}, "steps": [{"push": "more"}], "expect": {}}]}, "o/t", "v7-next",
            run=lambda *a, input=None: recorded.append(a) or fake(*a, input=input), sleep=lambda s: None, minutes=1, central="O/.github")
    check("C2: every contents PUT run_all, play and point_callers make names a branch, never main",
          (len([c for c in recorded if c[:3] == ("api", "-X", "PUT")]) >= 4, put_default(recorded)), (True, []))
    check("C2: a recorded PUT on main is named", len(put_default([("api", "-X", "PUT", "repos/o/t/contents/x", "-f", "branch=main"), ("api", "-X", "PUT", "repos/o/t/contents/y")])), 2)
    check("callers_gh: the ambient token when DX_CALLERS_TOKEN is not set", callers_gh() is gh if not os.environ.get("DX_CALLERS_TOKEN") else True, True)
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
        p.add_argument("--moved", default="")
        a = p.parse_args(argv[1:])
        moved = [] if a.moved else None
        record = (lambda m: write_moved(m, a.moved)) if a.moved else None
        results = run_all(load_yaml(os.path.join(ROOT, SCENARIOS)), a.repo, a.ref, a.only, minutes=a.minutes, moved_out=moved, record=record)
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
