#!/usr/bin/env python3
"""The callers' contract, read statically before any run (#563, #585).

A reusable workflow's job gets no more than its caller grants: v7.9.0 asked
the callers for a permission they did not grant, and every repository's
`Issues` run ended in `startup_failure` (#585). This holds every reusable
workflow of .github/workflows to its shipped callers (workflow-templates/,
which `sync-repos.py callers` writes into every repository, and
org-pull-request.yml, the organisation's required workflow), and to the
reusable workflows that call it in turn:

  - each job's `permissions` (its own, else its workflow's) within what the
    calling job grants (its own, else its workflow's; a caller that names
    none grants the repository's default, which is not checked), through
    every nested call;
  - every input it marks required with no default, and every input the
    caller passes, declared and passed;
  - every secret it marks required, and every secret it reads that it does
    not declare, passed (or the caller's `secrets: inherit`).

And the App tokens of TOKENS (#619): a job there mints the App's token for
the scope it names and with exactly the permissions it names, never one for
the whole installation (`owner:`), so what its callers reach is no more
than it needs.

And this repository's own callers (its workflows that are not reusable,
org-pull-request.yml aside, which runs in the other repositories): every
call of its own engine uses one ref (#563 C10), so the caller and the
engine are never read from two commits (#589).

  caller-contract.py check [ROOT]   each problem, one per line, naming the
                                    workflow, the job and what is missing
                                    or wider
  caller-contract.py --test
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEVEL = {"none": 0, "read": 1, "write": 2}
SHIPPED = ("workflow-templates/*.yml", ".github/workflows/org-pull-request.yml")
ALL = ("actions", "attestations", "checks", "contents", "deployments", "discussions", "id-token", "issues", "models",
       "packages", "pages", "pull-requests", "repository-projects", "security-events", "statuses")
# workflow -> job -> the App token it may mint: its `repositories:` and its
# permissions, exactly (#619).
TOKENS = {
    "waiting-update.yml": {
        "update": {"repositories": "${{ github.event.repository.name }}",
                   "permissions": {"issues": "write", "pull-requests": "read", "checks": "read", "contents": "read", "metadata": "read"}},
    },
}
APP_TOKEN = "actions/create-github-app-token@"


def load(path):
    import yaml
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def on_of(doc):
    return doc.get(True, doc.get("on")) or {}


def reusable(doc):
    on = on_of(doc)
    return isinstance(on, dict) and "workflow_call" in on or on == "workflow_call" or (isinstance(on, list) and "workflow_call" in on)


def perms(value):
    """A `permissions:` as {scope: level}; None when it names none (the
    default, unknown here)."""
    if value is None:
        return None
    if value in ("read-all", "write-all"):
        return {p: value.split("-")[0] for p in ALL}
    if value == {} or value == "":
        return {}
    return {str(k): str(v) for k, v in dict(value).items()}


def within(asked, granted):
    """The scopes of `asked` above `granted`: ["issues: write (granted read)"]."""
    if granted is None:
        return []
    return [f"{scope}: {level} (granted {granted.get(scope, 'none')})" for scope, level in sorted((asked or {}).items())
            if LEVEL.get(level, 0) > LEVEL.get(granted.get(scope, "none"), 0)]


def narrow(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return {s: min(a.get(s, "none"), b.get(s, "none"), key=lambda l: LEVEL.get(l, 0)) for s in set(a) | set(b)}


def callee(uses, central):
    """The reusable workflow of this repository a `uses:` names, or ""."""
    uses = str(uses or "")
    m = re.fullmatch(r"\./\.github/workflows/([^@/]+\.ya?ml)", uses) or re.fullmatch(re.escape(central) + r"/\.github/workflows/([^@/]+\.ya?ml)@.+", uses)
    return m.group(1) if m else ""


def contract(name, doc, job, workflows, granted, central, seen=()):
    """What the call of `name` by `job` (a calling job, with its grant)
    misses: ["<workflow> job <job>: ..."]."""
    out = []
    call = (on_of(doc) or {}).get("workflow_call") or {}
    declared_in = (call.get("inputs") or {}) if isinstance(call, dict) else {}
    declared_sec = (call.get("secrets") or {}) if isinstance(call, dict) else {}
    passed = job.get("with") or {}
    where = f"{name}, called by {seen[-1] if seen else '?'}"
    for key, spec in declared_in.items():
        spec = spec or {}
        if spec.get("required") and "default" not in spec and key not in passed:
            out.append(f"{where}: input `{key}` is required and not passed")
    for key in passed:
        if key not in declared_in:
            out.append(f"{where}: input `{key}` is passed and not declared")
    secrets = job.get("secrets")
    if secrets != "inherit":
        given = set((secrets or {}).keys()) if isinstance(secrets, dict) else set()
        # A job with an `environment:` reads that environment's secrets,
        # the caller's own, which need no passing.
        import json
        text = json.dumps([doc.get("env"), [j for j in (doc.get("jobs") or {}).values() if not j.get("environment")]], default=str)
        read = set(re.findall(r"secrets\.([A-Za-z_][A-Za-z0-9_]*)", text)) - {"GITHUB_TOKEN"}
        for key, spec in declared_sec.items():
            if (spec or {}).get("required") and key not in given:
                out.append(f"{where}: secret `{key}` is required and not passed")
        for key in sorted(read - set(declared_sec) - given):
            out.append(f"{where}: secret `{key}` is read and not passed")
    top = perms(doc.get("permissions"))
    for jname, j in (doc.get("jobs") or {}).items():
        asked = perms(j.get("permissions")) if "permissions" in j else top
        for miss in within(asked, granted):
            out.append(f"{name} job `{jname}` (called by {seen[-1] if seen else '?'}): asks {miss}")
        inner = callee(j.get("uses"), central)
        if inner and inner in workflows and inner not in [s.split(" ")[0] for s in seen]:
            out += contract(inner, workflows[inner], j, workflows, narrow(asked, granted), central, seen + (f"{name} job `{jname}`",))
    return out


def check(root=ROOT, central=None):
    if central is None:
        sys.path.insert(0, HERE)
        import org
        central = org.CENTRAL
    paths = sorted(glob.glob(os.path.join(root, ".github", "workflows", "*.yml")))
    workflows = {os.path.basename(p): load(p) for p in paths}
    reusables = {n: d for n, d in workflows.items() if reusable(d)}
    out = []
    for pattern in SHIPPED:
        for path in sorted(glob.glob(os.path.join(root, pattern))):
            doc = load(path)
            top = perms(doc.get("permissions"))
            rel = os.path.relpath(path, root)
            for jname, job in (doc.get("jobs") or {}).items():
                name = callee(job.get("uses"), central)
                if not name:
                    continue
                if name not in reusables:
                    out.append(f"{rel} job `{jname}`: calls {name}, which is not a reusable workflow here")
                    continue
                granted = perms(job.get("permissions")) if "permissions" in job else top
                out += contract(name, reusables[name], job, reusables, granted, central, (f"{rel} job `{jname}`",))
    out += tokens(workflows)
    out += one_ref(workflows, central)
    return sorted(set(out))


def tokens(workflows, table=None):
    """#619: each job of `table` (TOKENS) mints its App token for its scope
    alone, with exactly its permissions; a workflow not here is not read."""
    out = []
    for name, jobs in sorted((TOKENS if table is None else table).items()):
        if name not in workflows:
            continue
        for jname, want in sorted(jobs.items()):
            where = f"{name} job `{jname}`"
            job = (workflows[name].get("jobs") or {}).get(jname)
            if job is None:
                out.append(f"{where}: is not there, and its App token is checked")
                continue
            steps = [s for s in job.get("steps") or [] if str(s.get("uses") or "").startswith(APP_TOKEN)]
            if not steps:
                out.append(f"{where}: mints no App token, and it must for {want['repositories']}")
            for step in steps:
                got = step.get("with") or {}
                if "owner" in got:
                    out.append(f"{where}: mints its App token for the whole installation (`owner:`), not for {want['repositories']} alone")
                if str(got.get("repositories", "")) != want["repositories"]:
                    out.append(f"{where}: mints its App token for `{got.get('repositories', 'every repository')}`, not for {want['repositories']} alone")
                asked = {k[len("permission-"):]: str(v) for k, v in got.items() if k.startswith("permission-")}
                for scope in sorted(set(asked) | set(want["permissions"])):
                    a, w = asked.get(scope, "none"), want["permissions"].get(scope, "none")
                    if LEVEL.get(a, 0) > LEVEL.get(w, 0):
                        out.append(f"{where}: its App token asks {scope}: {a}, more than it needs ({w})")
                    elif LEVEL.get(a, 0) < LEVEL.get(w, 0):
                        out.append(f"{where}: its App token asks {scope}: {a}, and it needs {w}")
    return out


def one_ref(workflows, central):
    """C10: every call of this repository's own engine from its own
    callers uses one ref (`./` is main)."""
    refs = {}
    for name, doc in workflows.items():
        if reusable(doc) or name == "org-pull-request.yml":
            continue
        for jname, job in (doc.get("jobs") or {}).items():
            uses = str(job.get("uses") or "")
            if not callee(uses, central):
                continue
            ref = "./" if uses.startswith("./") else uses.rsplit("@", 1)[1]
            refs.setdefault(ref, []).append(f"{name} job `{jname}`")
    if len(refs) <= 1:
        return []
    return [f"this repository calls its own engine at {len(refs)} refs: " + "; ".join(f"{ref} in {', '.join(where)}" for ref, where in sorted(refs.items()))]


def self_test():
    failed = 0

    def ok(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    import tempfile
    with tempfile.TemporaryDirectory() as root:
        wf = os.path.join(root, ".github", "workflows")
        os.makedirs(wf)
        os.makedirs(os.path.join(root, "workflow-templates"))
        open(os.path.join(wf, "triage.yml"), "w").write(
            "on:\n  workflow_call:\n    inputs:\n      url: {type: string, required: true}\n    secrets:\n      KEY: {required: true}\n"
            "permissions: {contents: read}\njobs:\n  classify:\n    permissions: {contents: read, issues: write, pull-requests: write}\n"
            "    runs-on: x\n    steps:\n      - run: echo \"${{ secrets.TOKEN }}\"\n")
        open(os.path.join(root, "workflow-templates", "issues.yml"), "w").write(
            "on: issues\npermissions: {contents: read}\njobs:\n  triage:\n    permissions: {contents: read, issues: write}\n"
            "    uses: O/.github/.github/workflows/triage.yml@v7\n    with: {other: 1}\n")
        got = check(root, "O/.github")
        ok("C3: a missing permission is named with the workflow and the job",
           "triage.yml job `classify` (called by workflow-templates/issues.yml job `triage`): asks pull-requests: write (granted none)" in got, True)
        ok("C3: a missing input is named with the workflow and its caller",
           "triage.yml, called by workflow-templates/issues.yml job `triage`: input `url` is required and not passed" in got, True)
        ok("C3: an input the workflow does not declare is named", "triage.yml, called by workflow-templates/issues.yml job `triage`: input `other` is passed and not declared" in got, True)
        ok("C3: a missing secret, required or read, is named",
           ("triage.yml, called by workflow-templates/issues.yml job `triage`: secret `KEY` is required and not passed" in got,
            "triage.yml, called by workflow-templates/issues.yml job `triage`: secret `TOKEN` is read and not passed" in got), (True, True))
        open(os.path.join(root, "workflow-templates", "issues.yml"), "w").write(
            "on: issues\npermissions: {contents: read}\njobs:\n  triage:\n    permissions: {contents: read, issues: write, pull-requests: write}\n"
            "    uses: O/.github/.github/workflows/triage.yml@v7\n    with: {url: x}\n    secrets: inherit\n")
        ok("C3: a caller that gives what the workflow asks passes", check(root, "O/.github"), [])
        # Nested: the inner workflow's job is bounded by the outer calling job.
        open(os.path.join(wf, "inner.yml"), "w").write("on: {workflow_call: {}}\njobs:\n  go:\n    permissions: {actions: write}\n    runs-on: x\n    steps: []\n")
        open(os.path.join(wf, "triage.yml"), "a").write("  more:\n    permissions: {contents: read}\n    uses: ./.github/workflows/inner.yml\n")
        ok("#585: a nested call asks no more than the outer caller grants",
           check(root, "O/.github"), ["inner.yml job `go` (called by triage.yml job `more`): asks actions: write (granted none)"])
        os.unlink(os.path.join(wf, "inner.yml"))
        open(os.path.join(wf, "triage.yml"), "w").write("on: {workflow_call: {}}\njobs:\n  a:\n    runs-on: x\n    steps: []\n")
        open(os.path.join(wf, "issues.yml"), "w").write("on: issues\njobs:\n  t:\n    uses: O/.github/.github/workflows/triage.yml@v7\n")
        open(os.path.join(wf, "pull-request.yml"), "w").write("on: pull_request\njobs:\n  t:\n    uses: ./.github/workflows/triage.yml\n")
        open(os.path.join(root, "workflow-templates", "issues.yml"), "w").write("on: issues\njobs:\n  t:\n    uses: O/.github/.github/workflows/triage.yml@v7\n")
        ok("C10: own callers at two refs fail, naming each", check(root, "O/.github"),
           ["this repository calls its own engine at 2 refs: ./ in pull-request.yml job `t`; v7 in issues.yml job `t`"])
        open(os.path.join(wf, "issues.yml"), "w").write("on: issues\njobs:\n  t:\n    uses: ./.github/workflows/triage.yml\n")
        ok("C10: own callers at one ref pass", check(root, "O/.github"), [])
        open(os.path.join(wf, "triage.yml"), "w").write("on: {workflow_call: {}}\njobs:\n  a:\n    environment: e\n    runs-on: x\n    steps:\n      - run: echo \"${{ secrets.SVN }}\"\n")
        open(os.path.join(root, "workflow-templates", "issues.yml"), "w").write("on: issues\njobs:\n  t:\n    uses: O/.github/.github/workflows/triage.yml@v7\n")
        ok("C3: an environment's secrets need no passing", check(root, "O/.github"), [])
    # #619: the App tokens of TOKENS, for their scope alone.
    want = {"w.yml": {"u": {"repositories": "${{ github.event.repository.name }}", "permissions": {"issues": "write", "metadata": "read"}}}}

    def token(**with_):
        return {"w.yml": {"jobs": {"u": {"steps": [{"uses": APP_TOKEN + "abc", "with": dict({"client-id": "x"}, **with_)}]}}}}
    good = {"repositories": "${{ github.event.repository.name }}", "permission-issues": "write", "permission-metadata": "read"}
    ok("#619: the token for the item's repository, with what it needs, passes", tokens(token(**good), want), [])
    ok("#619: an owner-wide token is named", tokens(token(**{k: v for k, v in good.items() if k != "repositories"}, owner="${{ github.repository_owner }}"), want),
       ["w.yml job `u`: mints its App token for the whole installation (`owner:`), not for ${{ github.event.repository.name }} alone",
        "w.yml job `u`: mints its App token for `every repository`, not for ${{ github.event.repository.name }} alone"])
    ok("#619: an extra permission-*: write is named", tokens(token(**good, **{"permission-contents": "write"}), want),
       ["w.yml job `u`: its App token asks contents: write, more than it needs (none)"])
    ok("#619: a permission it needs and does not ask is named", tokens(token(**dict(good, **{"permission-issues": "read"})), want),
       ["w.yml job `u`: its App token asks issues: read, and it needs write"])
    ok("#619: a job of the table that mints no token is named", tokens({"w.yml": {"jobs": {"u": {"steps": [{"run": "x"}]}}}}, want),
       ["w.yml job `u`: mints no App token, and it must for ${{ github.event.repository.name }}"])
    ok("#619: the shipped waiting job's token is exactly what it needs",
       tokens({"waiting-update.yml": load(os.path.join(ROOT, ".github", "workflows", "waiting-update.yml"))}), [])
    ok("C3, C10: the engine's workflows, its shipped callers and its own callers keep the contract", check(), [])
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv[:1] == ["check"] and len(argv) <= 2:
        out = check(argv[1] if len(argv) == 2 else ROOT)
        for line in out:
            print(line)
        if not out:
            print("every caller gives what the workflows it calls ask, every App token of TOKENS is for its scope alone, and this repository calls its engine at one ref")
        return 1 if out else 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
