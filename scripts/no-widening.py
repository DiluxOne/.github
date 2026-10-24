#!/usr/bin/env python3
"""Whether a change widens the organisation's autonomy (#397): a permission,
a lane or a limit.

The golden rule keeps the paths that govern autonomy (`constitution` in
policy/autonomy.yml) with a person. One exception: a reproduced bug's fix
(the `bugfix-reproduced` lane, `constitution-merge`) may merge on its own in
those paths, and only when it widens nothing. This says so, from git alone,
comparing the change's base (the merge base) with its head; never from the
review's words. Anything it cannot tell counts as widening, and so
does any other change to a protected path: a script, a rule, a review
profile, a workflow's steps are code and words whose meaning no check can
compare, so a person reads them (fails closed). Only the policies below are
data it reads whole; a reproduced bug's fix elsewhere in the constitution
is still accepted and worked by the autopilot, and a person merges it.

What widens:
  policy/autonomy.yml, .github/autonomy.yml
    a lane added; a lane that accepted by a person accepting by policy; a
    lane switched on; a repository a lane covers added; `merge`, `ceiling`
    or `constitution-merge` raised (or added); a lane's `origin` or `type`
    changed; the autopilot switched on; more rounds, runs or budget; a
    protected path (`constitution`) or a `person-merges` label removed;
    `autopilot-mode` raised to full; `planned-release` set to auto; a
    security patch's limits raised or a forbidden path removed; any other
    key added or changed
  policy/review-policy.default.yml, .github/review-policy.yml
    a `high-risk` path removed; a `low-risk-eligible` or `docs-paths` path
    or a `trusted-authors` login added; `auto-merge` switched on; a larger
    `max-changed-lines-untrusted`; the issue gate changed
  .github/workflows/*.y*ml, workflow-templates/*.y*ml
    a token permission raised in any job (its own, or the workflow's it
    falls back on; none at all is every permission), a new job or workflow
    with a permission its file did not grant before, a job (or the
    workflow's own `env`) that passes or reads a secret it did not, all of
    them through toJSON(secrets) included, a new `pull_request_target` or
    `workflow_run` trigger
  any other protected path (`constitution` of the policy in force:
    ORG_AUTONOMY, default policy/autonomy.yml next to this script, made
    stricter by REPO_AUTONOMY, the repository's .github/autonomy.yml), a
    workflow's steps included
    any change: code can widen autonomy without moving any of the points
    above, and no check can read what code means

  no-widening.py check BASE HEAD   in a clone that has both commits: one
                                   line per widening, exit 1; nothing, exit
                                   0; exit 2 when it could not tell
  no-widening.py --test            self-test
"""
import fnmatch
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


autonomy = _load("autonomy", "autonomy.py")

LEVELS = ["none", "low", "medium", "high"]
PERM = {"none": 0, "read": 1, "write": 2}
AUTONOMY = ("policy/autonomy.yml", ".github/autonomy.yml")
REVIEW = ("policy/review-policy.default.yml", ".github/review-policy.yml")
WORKFLOW = re.compile(r"^(\.github/workflows|workflow-templates)/[^/]+\.ya?ml$")
# Every scope GitHub's token has: what a job with no permissions at all may get.
ALL = "*"
def level(value):
    return LEVELS.index(value) if value in LEVELS else len(LEVELS)


def raised(base, head):
    """True when the level `head` is above `base` (an unknown one is above all)."""
    return level(head) > level(base)


def as_list(value):
    return [v for v in value if isinstance(v, (str, int))] if isinstance(value, list) else []


def autonomy_widens(base, head, where):
    base, head = base if isinstance(base, dict) else {}, head if isinstance(head, dict) else {}
    out = []
    say = lambda what: out.append(f"{where}: {what}")
    known = {"autopilot", "autopilot-rounds", "autopilot-runs", "budgets-usd", "constitution", "person-merges",
             "autopilot-mode", "planned-release", "security-patch", "lanes"}
    if head.get("autopilot") is True and base.get("autopilot") is not True:
        say("the autopilot switched on")
    for key in ("autopilot-rounds", "autopilot-runs"):
        if key in head and (key not in base or not isinstance(head[key], int) or head[key] > base.get(key, 0)):
            if head.get(key) != base.get(key):
                say(f"{key} raised")
    hb, bb = head.get("budgets-usd") or {}, base.get("budgets-usd") or {}
    for key, value in (hb.items() if isinstance(hb, dict) else []):
        if key not in bb or not isinstance(value, (int, float)) or value > bb[key]:
            if value != bb.get(key):
                say(f"budgets-usd.{key} raised")
    for key in ("constitution", "person-merges"):
        gone = [p for p in as_list(base.get(key)) if p not in as_list(head.get(key))]
        if gone:
            say(f"{key}: {', '.join(map(str, gone))} removed")
    modes = {"guided": 0, "full": 1}
    hm, bm = head.get("autopilot-mode") or {}, base.get("autopilot-mode") or {}
    for key in ("default", "ceiling"):
        h, b = (hm or {}).get(key), (bm or {}).get(key, "guided")
        if h is not None and modes.get(h, 2) > modes.get(b, 0):
            say(f"autopilot-mode.{key} raised to {h}")
    if head.get("planned-release", "confirm") != "confirm" and base.get("planned-release", "confirm") == "confirm":
        say("planned-release set to auto")
    hs, bs = head.get("security-patch") or {}, base.get("security-patch") or {}
    for key in ("max-files", "max-lines"):
        if hs.get(key) is not None and hs.get(key) != bs.get(key) and (not isinstance(hs.get(key), int) or bs.get(key) is None or hs[key] > bs[key]):
            say(f"security-patch.{key} raised")
    gone = [p for p in as_list(bs.get("forbidden")) if p not in as_list(hs.get("forbidden"))]
    if gone:
        say(f"security-patch.forbidden: {', '.join(gone)} removed")
    for key in sorted((set(head) | set(base)) - known, key=str):
        if head.get(key) != base.get(key):
            say(f"{key} changed")
    blanes, hlanes = base.get("lanes") or {}, head.get("lanes") or {}
    for name, lane in (hlanes.items() if isinstance(hlanes, dict) else []):
        old = blanes.get(name) if isinstance(blanes, dict) else None
        if not isinstance(old, dict):
            say(f"lanes.{name} added")
            continue
        lane = lane if isinstance(lane, dict) else {}
        if lane.get("accept") != old.get("accept") and lane.get("accept") != "human":
            say(f"lanes.{name}.accept set to {lane.get('accept')}")
        if lane.get("enabled", True) is not False and old.get("enabled", True) is False:
            say(f"lanes.{name} switched on")
        new = [r for r in as_list(lane.get("repositories")) if r not in as_list(old.get("repositories"))]
        if new:
            say(f"lanes.{name}.repositories: {', '.join(map(str, new))} added")
        for part in ("merge", "ceiling", "constitution-merge"):
            h, b = lane.get(part), old.get(part)
            if h is None:
                continue
            for key in ("max-risk", "max-complexity"):
                hv = (h or {}).get(key) if isinstance(h, dict) else "?"
                bv = (b or {}).get(key, "none") if isinstance(b, dict) else "none"
                if raised(bv, hv):
                    say(f"lanes.{name}.{part}.{key} raised to {hv}")
        for key in sorted((set(lane) | set(old)) - {"description", "evidence", "accept", "enabled", "repositories", "merge", "ceiling", "constitution-merge"}):
            if lane.get(key) != old.get(key):
                say(f"lanes.{name}.{key} changed")
    return out


def review_widens(base, head, where):
    base, head = base if isinstance(base, dict) else {}, head if isinstance(head, dict) else {}
    out = []
    gone = [p for p in as_list(base.get("high-risk")) if p not in as_list(head.get("high-risk"))]
    if gone:
        out.append(f"{where}: high-risk {', '.join(map(str, gone))} removed")
    for key in ("low-risk-eligible", "docs-paths", "trusted-authors"):
        new = [p for p in as_list(head.get(key)) if p not in as_list(base.get(key))]
        if new:
            out.append(f"{where}: {key} {', '.join(map(str, new))} added")
    if head.get("auto-merge") is True and base.get("auto-merge") is not True:
        out.append(f"{where}: auto-merge switched on")
    h, b = head.get("max-changed-lines-untrusted"), base.get("max-changed-lines-untrusted")
    if h != b and h is not None and (not isinstance(h, int) or b is None or h > b):
        out.append(f"{where}: max-changed-lines-untrusted raised")
    if head.get("issue-gate") != base.get("issue-gate"):
        out.append(f"{where}: the issue gate changed")
    return out


def perms(value):
    """A permissions block as {scope: 0|1|2}; None (no block at all) is every
    scope, written."""
    if value is None:
        return {ALL: 2}
    if value == "write-all":
        return {ALL: 2}
    if value == "read-all":
        return {ALL: 1}
    if isinstance(value, dict):
        return {str(k): PERM.get(str(v), 3) for k, v in value.items()}
    return {ALL: 3}


def above(head, base):
    """The scopes `head` grants above `base`."""
    out = []
    for scope, lvl in head.items():
        have = base.get(scope, base.get(ALL, 0))
        if lvl > have:
            out.append(scope)
    return out


def secrets_of(job):
    text = json.dumps(job, sort_keys=True)
    names = set(re.findall(r"secrets\s*(?:\.\s*|\[\s*\\?['\"])([A-Za-z_][A-Za-z0-9_]*)", text))
    if re.search(r"toJSON\s*\(\s*secrets\s*\)", text, re.I):
        names.add("(every secret)")
    passed = job.get("secrets") if isinstance(job, dict) else None
    if passed == "inherit":
        names.add("(inherit)")
    elif isinstance(passed, dict):
        names |= {f"(passes {k})" for k in passed}
    return names


def triggers(wf):
    on = wf.get("on", wf.get(True)) if isinstance(wf, dict) else None
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(x) for x in on}
    if isinstance(on, dict):
        return {str(x) for x in on}
    return set()


def workflow_widens(base, head, where):
    """base is None for a new file; head None for a removed one."""
    if head is None:
        return []
    out = []
    head = head if isinstance(head, dict) else {}
    old = base if isinstance(base, dict) else None
    for t in sorted(triggers(head) - (triggers(old) if old else set())):
        if t in ("pull_request_target", "workflow_run"):
            out.append(f"{where}: a new {t} trigger")
    hwf = head.get("permissions") if "permissions" in head else None
    bwf = (old.get("permissions") if "permissions" in old else None) if old else {}
    # The file's own grant: a new file grants nothing yet; one with no block grants every scope.
    file_grant = perms(bwf) if old is not None else {}
    if old is not None and "permissions" in head and above(perms(hwf), perms(bwf)):
        out.append(f"{where}: the workflow's permissions raised ({', '.join(above(perms(hwf), perms(bwf)))})")
    new_env = sorted(secrets_of({"env": head.get("env")}) - (secrets_of({"env": old.get("env")}) if old else set()))
    if new_env:
        out.append(f"{where}: the workflow's env reads {', '.join(new_env)}")
    bjobs = (old.get("jobs") or {}) if old else {}
    for name, job in (head.get("jobs") or {}).items():
        job = job if isinstance(job, dict) else {}
        eff = perms(job["permissions"]) if "permissions" in job else perms(hwf if "permissions" in head else None)
        prev = bjobs.get(name)
        if isinstance(prev, dict):
            beff = perms(prev["permissions"]) if "permissions" in prev else perms(bwf if old and "permissions" in old else None)
        else:
            beff = file_grant
        up = above(eff, beff)
        if up:
            out.append(f"{where}: job {name} gets {', '.join(sorted(up))} it did not have")
        new = sorted(secrets_of(job) - (secrets_of(prev) if isinstance(prev, dict) else set()))
        if new:
            out.append(f"{where}: job {name} reads or passes {', '.join(new)}")
    return out


def git(*args):
    run = subprocess.run(["git", *args], capture_output=True, text=True)
    if run.returncode != 0:
        raise RuntimeError(run.stderr.strip()[:200] or f"git {args[0]} failed")
    return run.stdout


def at(ref, path):
    """The YAML at REF:PATH as data; None when the file is not there."""
    run = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, text=True)
    if run.returncode != 0:
        if "does not exist" in run.stderr or "exists on disk, but not in" in run.stderr:
            return None
        raise RuntimeError(run.stderr.strip()[:200])
    return autonomy.parse_text(run.stdout)


def protected_paths():
    """The constitution in force: the organisation's, with the repository's own."""
    org = autonomy.load(os.environ.get("ORG_AUTONOMY") or os.path.join(HERE, "..", "policy", "autonomy.yml"))
    repo = autonomy.load(os.environ.get("REPO_AUTONOMY") or "")
    return autonomy.merge(org, repo if isinstance(repo, dict) else {}).get("constitution") or []


def check(base, head, protected=None):
    protected = protected_paths() if protected is None else protected
    fork = git("merge-base", base, head).strip()
    changed = [p for p in git("diff", "--name-only", "--no-renames", fork, head).splitlines() if p]
    out = []
    for path in changed:
        if path in AUTONOMY:
            out += autonomy_widens(at(fork, path), at(head, path), path)
            continue
        if path in REVIEW:
            out += review_widens(at(fork, path), at(head, path), path)
            continue
        if WORKFLOW.match(path):
            out += workflow_widens(at(fork, path), at(head, path), path)
        if any(fnmatch.fnmatch(path, p) for p in protected):
            out.append(f"{path}: a protected path that is code or words, which no check can read; a person reads what it changes")
    return out


def self_test():
    failed = 0

    def ok(name, got, want):
        nonlocal failed
        if got == want:
            print(f"ok   {name}")
        else:
            print(f"FAIL {name}: got {got!r}, want {want!r}")
            failed = 1

    org = autonomy.load(os.path.join(HERE, "..", "policy", "autonomy.yml"))
    import copy
    w = lambda change: autonomy_widens(org, change(copy.deepcopy(org)) or None, "p")

    def setter(fn):
        def go(p):
            fn(p)
            return p
        return go
    ok("the policy as it is widens nothing", autonomy_widens(org, copy.deepcopy(org), "p"), [])
    ok("a lane added widens", w(setter(lambda p: p["lanes"].__setitem__("x", {"accept": "policy"}))), ["p: lanes.x added"])
    ok("a lane's merge raised widens", w(setter(lambda p: p["lanes"]["bugfix-reproduced"]["merge"].__setitem__("max-risk", "high"))), ["p: lanes.bugfix-reproduced.merge.max-risk raised to high"])
    ok("a lane's merge lowered does not", w(setter(lambda p: p["lanes"]["bugfix-reproduced"]["merge"].__setitem__("max-risk", "low"))), [])
    ok("a ceiling added widens", w(setter(lambda p: p["lanes"]["platform"].__setitem__("ceiling", {"max-risk": "high", "max-complexity": "medium"}))),
       ["p: lanes.platform.ceiling.max-risk raised to high", "p: lanes.platform.ceiling.max-complexity raised to medium"])
    ok("a human lane accepting by policy widens", w(setter(lambda p: p["lanes"]["human-issue"].__setitem__("accept", "policy"))), ["p: lanes.human-issue.accept set to policy"])
    ok("a repository added to a lane widens", w(setter(lambda p: p["lanes"]["platform"]["repositories"].append("x"))), ["p: lanes.platform.repositories: x added"])
    ok("a lane's origin changed widens", w(setter(lambda p: p["lanes"]["platform"]["origin"]["workflows"].append("x.yml"))), ["p: lanes.platform.origin changed"])
    ok("a protected path removed widens", w(setter(lambda p: p["constitution"].remove("scripts/**"))), ["p: constitution: scripts/** removed"])
    ok("a protected path added does not", w(setter(lambda p: p["constitution"].append("x/**"))), [])
    ok("a person-merges label removed widens", w(setter(lambda p: p.__setitem__("person-merges", []))), ["p: person-merges: security removed"])
    ok("more budget widens", w(setter(lambda p: p["budgets-usd"].__setitem__("autopilot-work", 50))), ["p: budgets-usd.autopilot-work raised"])
    ok("more rounds widen", w(setter(lambda p: p.__setitem__("autopilot-rounds", 9))), ["p: autopilot-rounds raised"])
    ok("a lane switched off does not", w(setter(lambda p: p["lanes"]["platform"].__setitem__("enabled", False))), [])
    ok("a lane removed does not", w(setter(lambda p: p["lanes"].pop("platform"))), [])
    ok("a description reworded does not", w(setter(lambda p: p["lanes"]["platform"].__setitem__("description", "x"))), [])
    ok("constitution-merge raised widens", w(setter(lambda p: p["lanes"]["bugfix-reproduced"]["constitution-merge"].__setitem__("max-complexity", "high"))),
       ["p: lanes.bugfix-reproduced.constitution-merge.max-complexity raised to high"])
    ok("a new top-level key widens", w(setter(lambda p: p.__setitem__("anything", 1))), ["p: anything changed"])
    rp = {"high-risk": [".github/**"], "low-risk-eligible": ["tests/**"], "trusted-authors": ["a"], "auto-merge": False, "max-changed-lines-untrusted": 600}
    ok("the review policy: a high-risk path removed widens", review_widens(rp, {**rp, "high-risk": []}, "r"), ["r: high-risk .github/** removed"])
    ok("the review policy: a safe path or a trusted author added widens", review_widens(rp, {**rp, "low-risk-eligible": ["tests/**", "scripts/**"], "trusted-authors": ["a", "b"]}, "r"),
       ["r: low-risk-eligible scripts/** added", "r: trusted-authors b added"])
    ok("the review policy: auto-merge on widens", review_widens(rp, {**rp, "auto-merge": True}, "r"), ["r: auto-merge switched on"])
    ok("the review policy: a high-risk path added does not", review_widens(rp, {**rp, "high-risk": [".github/**", "x"]}, "r"), [])
    wf = {"on": {"pull_request": None}, "permissions": {"contents": "read"},
          "jobs": {"a": {"runs-on": "x", "steps": []}, "b": {"permissions": {"contents": "read", "issues": "write"}, "steps": [{"env": {"T": "${{ secrets.X }}"}}]}}}
    ok("a workflow as it is widens nothing", workflow_widens(wf, copy.deepcopy(wf), "w"), [])
    up = copy.deepcopy(wf)
    up["jobs"]["a"]["permissions"] = {"contents": "write"}
    ok("a job's permission raised widens", workflow_widens(wf, up, "w"), ["w: job a gets contents it did not have"])
    down = copy.deepcopy(wf)
    down["jobs"]["b"]["permissions"] = {"contents": "read"}
    ok("a job's permission lowered does not", workflow_widens(wf, down, "w"), [])
    new = copy.deepcopy(wf)
    del new["permissions"]
    ok("a workflow with no permissions block grants every scope: widens", workflow_widens(wf, new, "w"), ["w: job a gets * it did not have"])
    added = copy.deepcopy(wf)
    added["jobs"]["c"] = {"permissions": {"contents": "read"}, "steps": []}
    ok("a new job within the file's grant does not widen", workflow_widens(wf, added, "w"), [])
    added["jobs"]["c"]["permissions"] = {"contents": "read", "pull-requests": "write"}
    ok("a new job above the file's grant widens", workflow_widens(wf, added, "w"), ["w: job c gets pull-requests it did not have"])
    sec = copy.deepcopy(wf)
    sec["jobs"]["a"]["secrets"] = "inherit"
    ok("a job that starts passing secrets widens", workflow_widens(wf, sec, "w"), ["w: job a reads or passes (inherit)"])
    sec = copy.deepcopy(wf)
    sec["jobs"]["a"]["steps"] = [{"run": "echo ${{ secrets.Y }}"}]
    ok("a job that starts reading a secret widens", workflow_widens(wf, sec, "w"), ["w: job a reads or passes Y"])
    ok("a new workflow file with any permission widens", workflow_widens(None, wf, "w"), ["w: job a gets contents it did not have", "w: job b gets contents, issues it did not have", "w: job b reads or passes X"])
    trig = copy.deepcopy(wf)
    trig["on"]["pull_request_target"] = None
    ok("a pull_request_target trigger widens", workflow_widens(wf, trig, "w"), ["w: a new pull_request_target trigger"])
    ok("a removed workflow widens nothing", workflow_widens(wf, None, "w"), [])
    ok("PyYAML's `on: true` key is read as the triggers", triggers({True: {"push": None}}), {"push"})
    for how, step_run in (("secrets['Y']", "echo ${{ secrets['Y'] }}"), ("toJSON(secrets)", "echo '${{ toJSON(secrets) }}'")):
        sec = copy.deepcopy(wf)
        sec["jobs"]["a"]["steps"] = [{"run": step_run}]
        ok(f"a job that starts reading {how} widens", bool(workflow_widens(wf, sec, "w")), True)
    sec = copy.deepcopy(wf)
    sec["env"] = {"T": "${{ secrets.Z }}"}
    ok("the workflow's env reading a secret widens", "w: the workflow's env reads Z" in workflow_widens(wf, sec, "w"), True)

    # check() on a real repository: the merge base against the head.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        g = lambda *a: subprocess.run(["git", "-C", d, "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                      check=True, capture_output=True, text=True).stdout.strip()
        g("init", "-q", "-b", "main")
        os.makedirs(os.path.join(d, "policy"))
        os.makedirs(os.path.join(d, ".github", "workflows"))
        write = lambda p, t: open(os.path.join(d, p), "w").write(t)
        write("policy/autonomy.yml", "autopilot: true\nlanes:\n  a: {accept: policy, repositories: [x], merge: {max-risk: low, max-complexity: low}}\n")
        write(".github/workflows/w.yml", "on: [push]\npermissions: {contents: read}\njobs:\n  j: {runs-on: x, steps: []}\n")
        write("scripts.txt", "x\n")
        g("add", "-A")
        g("commit", "-qm", "base")
        base = g("rev-parse", "HEAD")
        g("checkout", "-q", "-b", "fix")
        write("scripts.txt", "fixed\n")
        write("policy/autonomy.yml", "autopilot: true\nlanes:\n  a: {accept: policy, repositories: [x], merge: {max-risk: low, max-complexity: low}, description: fixed}\n")
        g("commit", "-qam", "fix")
        fix = g("rev-parse", "HEAD")
        cwd = os.getcwd()
        os.chdir(d)
        try:
            ok("check: a fix that widens nothing", check(base, fix, []), [])
            prot = ["policy/**", ".github/**", "scripts/**", "kinds/**", "rules/**", "org.yml"]
            ok("check: a fix in the policy it reads whole, widening nothing", check(base, fix, prot), [])
            for path in ("scripts/repro-run.sh", "kinds/x/pack.yml", "rules/x.md", "policy/other.yml"):
                os.makedirs(os.path.dirname(os.path.join(d, path)), exist_ok=True)
                write(path, "changed\n")
            write("src.txt", "fixed\n")
            g("add", "-A")
            g("commit", "-qm", "code")
            ok("check: any other protected path is code or words, a person's; a path outside the constitution is not",
               check(base, g("rev-parse", "HEAD"), prot), [f"{p}: a protected path that is code or words, which no check can read; a person reads what it changes"
                                                         for p in ("kinds/x/pack.yml", "policy/other.yml", "rules/x.md", "scripts/repro-run.sh")])
            g("reset", "-q", "--hard", fix)
            write(".github/workflows/w.yml", "on: [push]\npermissions: {contents: write}\njobs:\n  j: {runs-on: x, steps: []}\n")
            g("commit", "-qam", "widen")
            ok("check: a fix that raises a workflow's permission", check(base, g("rev-parse", "HEAD"), []),
               [".github/workflows/w.yml: the workflow's permissions raised (contents)", ".github/workflows/w.yml: job j gets contents it did not have"])
            ok("check: a workflow is code too: its steps are a person's when it is protected", check(base, g("rev-parse", "HEAD"), [".github/**"])[-1],
               ".github/workflows/w.yml: a protected path that is code or words, which no check can read; a person reads what it changes")
            # main moves on (a lane removed there): measured from the merge
            # base, the branch does not read as adding it back.
            g("checkout", "-q", "main")
            write("policy/autonomy.yml", "autopilot: true\nlanes: {}\n")
            g("commit", "-qam", "main narrows")
            ok("check: from the merge base, main's own change is not the branch's", check(g("rev-parse", "HEAD"), fix, []), [])
            ok("check: the constitution in force is the policy's", "scripts/**" in protected_paths(), True)
        finally:
            os.chdir(cwd)
    if not failed:
        print("all tests passed")
    return failed


def main(argv):
    if argv[:1] == ["--test"]:
        return self_test()
    if argv[:1] == ["check"] and len(argv) == 3:
        try:
            found = check(argv[1], argv[2])
        except (RuntimeError, ValueError, OSError) as err:
            print(f"could not tell: {err}")
            return 2
        for line in found:
            print(line)
        return 1 if found else 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
