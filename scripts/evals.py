#!/usr/bin/env python3
"""Every AI step is measured (#735): one evaluation set per step, one runner.

A change to a step's AI (its workflow, the prompts it reads, its model in
policy/autonomy.yml, its set) is scored before it merges. Each step has its
set under evals/<step>/: cases.json, real cases from the organisation's
public repositories (a private one's code would show in this public
repository's logs), and baseline.json, the score of the last whole run.
Each case is replayed with the step as it stands in the checkout and graded
deterministically wherever a grade exists:

  triage     the verdict's category, duplicate_of and exists_in_pro equal
             the case's record
  repro      the test the step writes fails at the case's base on an
             assertion (the "Test first" rule, through scripts/test-first.py
             and the way's sandbox: repro-run.sh or repro-sandbox.sh)
  spec       the PRD and the Spec pass the issue schema (G3), and the Spec's
             files name at least half of the files the merged pull request
             changed
  autopilot  the merged pull request's tests pass on the tree the step
             leaves (the same sandboxes)
  review     flag or clean, as #234 has it: a known bug is found on its
             file again, a clean pull request is not blocked
  reply      a model judges, with the case's rubric (the outcome is words):
             the thread is resolved, and no further change is asked

A step's score is the share of cases that pass (the review's: bugs found
and clean pull requests blocked). evals.yml fails a change whose score is
worse than the step's baseline by more than one case (a model does not
answer the same twice), or with more than one case that could not be
replayed. A step whose baseline is pending fails until `baseline` writes
it from a whole run: no baseline is no gate, and never passes quietly.

  evals.py steps FILE...       the steps whose paths the files touch, one per
                               line (only those with a set)
  evals.py collect STEP [N]    write evals/STEP/cases.json: N cases (default
                               6; the review's, N of each kind). repro, spec
                               and autopilot from this checkout's git history
                               (the reproduced bugs; the accepted issues whose
                               merged pull request changed tests); review
                               from its threads on GitHub (GH_TOKEN, read)
  evals.py run STEP            replay every case; results on stdout (JSON)
                               (the Claude Code CLI, git, gh, the checkout)
  evals.py score STEP FILE     the results in FILE against the baseline: a
                               table on stdout, exit 1 when worse
  evals.py baseline STEP FILE  write the results in FILE as the baseline
  evals.py --test              self-test (offline)
"""
import fnmatch
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import org  # noqa: E402  the organisation, from org.yml (#191)

EVALS = os.path.join(ROOT, "evals")
SLACK = 1
# A Spec names the files it changes: at least this share of the files the
# merged pull request changed (tests and the changelog aside).
RECALL = 0.5
# A smaller change is a fairer case: no more files than this.
MAX_FILES = 20
# What counts for every step: its model and AI settings.
COMMON = ("policy/autonomy.yml",)
REVIEW_PATHS = (
    "review-profiles/**",
    "kinds/*/review-profile.md",
    "kinds/*/rules.yml",
    "policy/review-policy.default.yml",
    "scripts/review-brief.sh",
    "scripts/local-review.sh",
    "scripts/review-verify.py",
    "scripts/review-count.py",
    ".github/workflows/claude-review.yml",
)
TEST_FILE = re.compile(r"tests/(?:repro/(?:.+/)?|workflows/)test_[^/]+\.py")
REPRO_SUBJECT = re.compile(r"the bug reproduced from #(\d+)")
PR_OF = re.compile(r"\(#(\d+)\)\s*$")
CLOSES = re.compile(r"\bCloses #(\d+)")
TYPE_OF = {"feat": "Feature", "fix": "Bug", "docs": "Docs"}


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The grades: (case, what the replay gave) -> True, False, or None when the
# case could not be replayed.

def grade_triage(case, got):
    if not isinstance(got, dict) or not got.get("category"):
        return None
    want = case["expect"]
    dup = got.get("duplicate_of") if isinstance(got.get("duplicate_of"), int) and got.get("duplicate_of") > 0 else None
    return (got["category"] == want.get("category") and dup == want.get("duplicate_of")
            and bool(got.get("exists_in_pro")) == bool(want.get("exists_in_pro")))


def grade_repro(case, got):
    if not isinstance(got, dict):
        return None
    if not got.get("wrote"):
        return False
    outcome = got.get("outcome")
    if outcome in (None, "", "limit"):
        return None
    return outcome == "reproduced"


def files_named(spec_text, files):
    """The files of the list that the Spec's `### Spec: files` names."""
    schema = _load("issue_schema", "issue-schema.py")
    sections, _ = schema.parse(spec_text)
    named = "\n".join(t for h, t in sections if h == "Spec: files")
    return [f for f in files if f in named]


def grade_spec(case, got):
    if not isinstance(got, dict) or not got.get("body"):
        return None
    schema = _load("issue_schema", "issue-schema.py")
    if not schema.check(got["body"], "spec", issue_type=case.get("type"))["ok"]:
        return False
    files = case["files"]
    return bool(files) and len(files_named(got["body"], files)) >= RECALL * len(files)


def grade_autopilot(case, got):
    if not isinstance(got, dict) or not got:
        return None
    if any(got.get(t) in (None, "", "limit") for t in case["tests"]):
        return None
    return all(got.get(t) == "passed" for t in case["tests"])


def verdict(case, review):
    """Whether the review did what the case expects. review is
    local-review.sh's last.json, or None when it gave none."""
    if not isinstance(review, dict):
        return None
    serious = [f for f in review.get("findings") or [] if isinstance(f, dict)
               and f.get("severity") in ("blocker", "major") and not f.get("pre_existing")]
    if case["expect"] == "flag":
        return any(f.get("file") == case["path"] for f in serious)
    return not serious


def grade_reply(case, got):
    """The judge's answer, {resolved, more_asked}, read with the case's rubric."""
    if not isinstance(got, dict) or not isinstance(got.get("resolved"), bool):
        return None
    return got["resolved"] and not got.get("more_asked", False)


# Each step: the paths that count for it (with COMMON and evals/<step>/**),
# the fields its cases carry, whether a model judges it, and its grade.
STEPS = {
    "triage": {"paths": (".github/workflows/issue-triage.yml", "scripts/triage-brief.sh"),
               "fields": ("issue",), "judge": False, "grade": grade_triage},
    "repro": {"paths": (".github/workflows/issue-repro.yml", "scripts/repro-ways.py", "scripts/repro-brief.sh"),
              "fields": ("issue", "base", "test"), "judge": False, "grade": grade_repro},
    "spec": {"paths": (".github/workflows/autopilot.yml", "scripts/autopilot.py"),
             "fields": ("issue", "base", "type", "files"), "judge": False, "grade": grade_spec},
    "autopilot": {"paths": (".github/workflows/autopilot.yml", "scripts/autopilot.py"),
                  "fields": ("issue", "base", "merge", "tests"), "judge": False, "grade": grade_autopilot},
    "review": {"paths": REVIEW_PATHS, "fields": ("pr", "title", "base", "head"), "judge": False, "grade": verdict},
    "reply": {"paths": (".github/workflows/review-reply.yml",),
              "fields": ("pr", "thread", "rubric"), "judge": True, "grade": grade_reply},
}


def matches(path, pattern):
    """A glob as a workflow's `paths:` reads it: `**` any depth, `*` one
    segment."""
    rx = re.escape(pattern).replace(r"\*\*", "\0").replace(r"\*", "[^/]*").replace("\0", ".*")
    return re.fullmatch(rx, path) is not None


def paths_of(step):
    return list(STEPS[step]["paths"]) + list(COMMON) + [f"evals/{step}/**"]


def all_paths():
    """Every path that counts for a step, once: evals.yml's `paths:`."""
    out = []
    for step in STEPS:
        out += [p for p in paths_of(step) if p not in out]
    return out


def has_set(step, root=ROOT):
    return os.path.isfile(os.path.join(root, "evals", step, "cases.json"))


def steps_of(files, with_set=False, root=ROOT):
    """The steps whose paths FILES touch, in the table's order; with_set:
    only those with a set (the others' sets are still to come)."""
    return [s for s in STEPS if any(matches(f, p) for f in files for p in paths_of(s)) and (not with_set or has_set(s, root))]


def score(step, results):
    if step == "review":
        flag = [r for r in results if r["expect"] == "flag" and r["ok"] is not None]
        clean = [r for r in results if r["expect"] == "clean" and r["ok"] is not None]
        return {"found": sum(1 for r in flag if r["ok"]), "flag": len(flag),
                "blocked": sum(1 for r in clean if not r["ok"]), "clean": len(clean),
                "unreviewed": sum(1 for r in results if r["ok"] is None)}
    run = [r for r in results if r["ok"] is not None]
    return {"passed": sum(1 for r in run if r["ok"]), "cases": len(run), "unrun": len(results) - len(run)}


def worse(step, now, base):
    """Why the score is worse than the baseline by more than SLACK, or ''."""
    why = []
    if step == "review":
        if base.get("flag") and now["found"] < base["found"] - SLACK:
            why.append(f"it found {now['found']} of {now['flag']} known bugs, the baseline {base['found']} of {base['flag']}")
        if now["blocked"] > base.get("blocked", 0) + SLACK:
            why.append(f"it blocked {now['blocked']} of {now['clean']} clean pull requests, the baseline {base.get('blocked', 0)}")
        if now["unreviewed"] > SLACK:
            why.append(f"{now['unreviewed']} cases could not be reviewed")
        return "; ".join(why)
    if base.get("cases") and now["passed"] < base["passed"] - SLACK:
        why.append(f"{now['passed']} of {now['cases']} cases passed, the baseline {base['passed']} of {base['cases']}")
    if now["unrun"] > SLACK:
        why.append(f"{now['unrun']} cases could not be replayed")
    return "; ".join(why)


def table(step, results, now, base):
    out = ["| Case | Expects | Result |", "| --- | --- | --- |"]
    for r in results:
        if step == "review":
            res = "could not review" if r["ok"] is None else ("as expected" if r["ok"] else "**missed**" if r["expect"] == "flag" else "**blocked**")
        else:
            res = "could not replay" if r["ok"] is None else ("as expected" if r["ok"] else "**failed**")
        out.append(f"| {r['id']} | {r['expect']} | {res} |")
    if step == "review":
        out += ["", f"Found {now['found']} of {now['flag']} known bugs (baseline {base.get('found', '?')} of {base.get('flag', '?')}); "
                f"blocked {now['blocked']} of {now['clean']} clean pull requests (baseline {base.get('blocked', '?')}); {now['unreviewed']} not reviewed."]
    else:
        out += ["", f"{step}: {now['passed']} of {now['cases']} cases passed (baseline {base.get('passed', '?')} of {base.get('cases', '?')}); "
                f"{now['unrun']} not replayed."]
    return "\n".join(out)


# The review's cases from GitHub (#234): its threads on the public
# repositories' merged pull requests.
QUERY = """
query($q: String!) {
  search(query: $q, type: ISSUE, first: 50) {
    nodes { ... on PullRequest {
      number title baseRefOid headRefOid isCrossRepository
      reviewThreads(first: 50) { nodes {
        isResolved isOutdated path resolvedBy { login }
        comments(first: 1) { nodes { author { login } body originalCommit { oid } } }
      } }
    } }
  }
}
"""


def is_review(t):
    c = ((t.get("comments") or {}).get("nodes") or [{}])[0] or {}
    return (c.get("author") or {}).get("login") == org.APP and "AI review" in (c.get("body") or "")


def cases_from(repo, prs, n):
    """Up to n `flag` and n `clean` cases from one repository's pull requests."""
    flag, clean = [], []
    for pr in prs:
        # Only a branch of the repository itself: a fork's code never runs
        # where the review's key is (#234).
        if pr.get("isCrossRepository") is not False:
            continue
        threads = [t for t in ((pr.get("reviewThreads") or {}).get("nodes") or [])]
        fixed = [t for t in threads if is_review(t) and (((t.get("resolvedBy") or {}).get("login") == org.APP) or t.get("isOutdated"))]
        if fixed:
            t = fixed[0]
            head = (((t.get("comments") or {}).get("nodes") or [{}])[0].get("originalCommit") or {}).get("oid")
            if head and len(flag) < n:
                flag.append({"id": f"{repo}#{pr['number']}:flag", "repo": repo, "pr": pr["number"], "title": pr.get("title") or "",
                             "base": pr.get("baseRefOid"), "head": head, "expect": "flag", "path": t.get("path")})
        elif not any(is_review(t) for t in threads) and len(clean) < n:
            clean.append({"id": f"{repo}#{pr['number']}:clean", "repo": repo, "pr": pr["number"], "title": pr.get("title") or "",
                          "base": pr.get("baseRefOid"), "head": pr.get("headRefOid"), "expect": "clean"})
    return flag, clean


def pick(per_repo, n):
    """n of each kind, taken round the repositories so no one dominates."""
    out = {"flag": [], "clean": []}
    for kind, i in (("flag", 0), ("clean", 1)):
        pools = [list(v[i]) for v in per_repo.values()]
        while len(out[kind]) < n and any(pools):
            for p in pools:
                if p and len(out[kind]) < n:
                    out[kind].append(p.pop(0))
    return sorted(out["flag"] + out["clean"], key=lambda c: c["id"])


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def public_repos():
    import yaml
    with open(os.path.join(ROOT, "repos.yml"), encoding="utf-8") as fh:
        names = sorted(((yaml.safe_load(fh) or {}).get("repos") or {}).keys())
    listed = {r["name"]: r for r in json.loads(gh("repo", "list", org.ORG, "--limit", "500", "--json", "name,visibility,isArchived"))}
    return [n for n in names if (listed.get(n) or {}).get("visibility") == "PUBLIC" and not listed[n].get("isArchived")]


def collect_review(n):
    per_repo = {}
    for name in public_repos():
        full = f"{org.ORG}/{name}"
        out = gh("api", "graphql", "-f", f"query={QUERY}", "-f", f"q=repo:{full} is:pr is:merged commenter:app/{org.APP}")
        prs = json.loads(out)["data"]["search"]["nodes"]
        per_repo[full] = cases_from(full, prs, n)
    return pick(per_repo, n)


# Replaying a case: a checkout of its repository at its base, the step's
# own prompt and arguments (read from its workflow, so a change to them is
# what is measured), the Claude Code CLI, and the grade's evidence.

# What the replay may hand the model: never a token.
SECRET_ENV = ("GH_TOKEN", "GITHUB_TOKEN")
CASE_MINUTES = 15


def git(repo_dir, *args):
    return subprocess.run(["git", "-C", repo_dir, *args], capture_output=True, text=True)


def checkout(case, work, *refs):
    """A fresh worktree of the case's repository at its base, with REFS
    fetched; None when it cannot be had."""
    repo_dir = os.path.join(work, case["repo"].replace("/", "_"))
    if not os.path.isdir(repo_dir):
        if subprocess.run(["git", "clone", "-q", "--no-checkout", f"https://github.com/{case['repo']}", repo_dir]).returncode != 0:
            return None
    for ref in (case["base"], *refs):
        if git(repo_dir, "cat-file", "-e", ref + "^{commit}").returncode != 0:
            git(repo_dir, "fetch", "-q", "origin", ref)
    tree = os.path.join(work, "trees", re.sub(r"[^A-Za-z0-9._-]", "_", case["id"]))
    if git(repo_dir, "worktree", "add", "-q", "-f", "--detach", tree, case["base"]).returncode != 0:
        return None
    # The step's helpers and brief live under .dx-central, as in its
    # workflow: this checkout's, so the change under evaluation is what runs.
    os.makedirs(os.path.join(tree, ".dx-central"), exist_ok=True)
    for name in os.listdir(ROOT):
        if name not in (".git", ".dx-central", ".dx-io"):
            dest = os.path.join(tree, ".dx-central", name)
            if not os.path.lexists(dest):
                os.symlink(os.path.join(ROOT, name), dest)
    return tree


def issue_of(case):
    """The case's issue, {title, body}, read from GitHub (public)."""
    try:
        return json.loads(gh("issue", "view", str(case["issue"]), "--repo", case["repo"], "--json", "title,body"))
    except (subprocess.CalledProcessError, ValueError):
        return None


def workflow_step(workflow, job, step_id):
    import yaml
    with open(os.path.join(ROOT, ".github", "workflows", workflow), encoding="utf-8") as fh:
        wf = yaml.safe_load(fh)
    return next(s for s in wf["jobs"][job]["steps"] if s.get("id") == step_id)


def claude_args(workflow, job, step_id, values):
    """The step's `claude_args`, as its workflow has them, with its
    expressions filled from VALUES; one it does not know is an error (the
    case is then not replayed), never a guess."""
    import shlex
    text = workflow_step(workflow, job, step_id)["with"]["claude_args"]

    def fill(m):
        if m.group(1) not in values:
            raise KeyError(f"{workflow} {step_id}: no value for ${{{{ {m.group(1)} }}}}")
        return values[m.group(1)]
    return shlex.split(re.sub(r"\$\{\{\s*(.*?)\s*\}\}", fill, text))


def ask(prompt, args, cwd):
    """The Claude Code CLI on PROMPT in CWD with ARGS; its JSON result, or
    None."""
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
    try:
        got = subprocess.run(["claude", "-p", prompt, *args, "--output-format", "json"], cwd=cwd, env=env,
                             capture_output=True, text=True, timeout=CASE_MINUTES * 60)
        return json.loads(got.stdout)
    except (subprocess.TimeoutExpired, ValueError):
        return None


def policy_model(tree):
    """The model and effort the step's policy gives (policy.py, high floor)."""
    out = os.path.join(tree, ".dx-io", "policy.out")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    env = {**os.environ, "DEFAULT_POLICY": os.path.join(ROOT, "policy", "review-policy.default.yml"),
           "REPO_POLICY": os.path.join(tree, ".github", "review-policy.yml"), "POLICY_LEVEL": "high", "GITHUB_OUTPUT": out}
    subprocess.run([sys.executable, os.path.join(HERE, "policy.py")], cwd=tree, env=env, capture_output=True, text=True)
    pairs = dict(line.split("=", 1) for line in open(out, encoding="utf-8").read().splitlines() if "=" in line) if os.path.exists(out) else {}
    return pairs.get("model", ""), pairs.get("effort", "")


def commit_all(tree, message):
    git(tree, "add", "-A", "--", ".", ":!.dx-central", ":!.dx-io")
    git(tree, "-c", "user.name=evals", "-c", "user.email=evals@localhost", "commit", "-q", "--allow-empty", "-m", message)
    return git(tree, "rev-parse", "HEAD").stdout.strip()


def run_test(tree, case, test, ref, test_ref, out_dir, title):
    """TEST as committed at TEST_REF, run against REF's tree, through the
    way's sandbox (test-first.py); its outcome, or None."""
    tf = _load("test_first", "test-first.py")
    plan = tf.plan(tree, ROOT, title, case["base"], test_ref, case["repo"].split("/")[-1], str(case["issue"]),
                   at_base=case["repo"] == f"{org.ORG}/.github")
    entry = next((t for t in plan.get("tests") or [] if t["test"] == test), None)
    if not entry:
        return None
    return tf.run_one(tree, ROOT, entry, ref, test_ref, out_dir)


def replay_repro(case, work):
    tree = checkout(case, work)
    issue = issue_of(case) if tree else None
    if not issue:
        return None
    rw = _load("repro_ways", "repro-ways.py")
    os.environ.setdefault("REPO", case["repo"].split("/")[-1])
    way = rw.resolve(tree, ROOT, case.get("layer") or "logic", str(case["issue"]))
    if not way.get("way") or way.get("fixed"):
        return None
    env = {**os.environ, "GITHUB_REPOSITORY": case["repo"], "NUMBER": str(case["issue"]), "TITLE": issue.get("title") or "",
           "BODY": issue.get("body") or "", "LABEL": "", "SENDER_LOGIN": "", "SANDBOX": way["sandbox"], "LAYER": way["layer"],
           "TEST": way["test"], "NOUN": way["noun"], "CENTRAL": ".dx-central"}
    os.makedirs(os.path.join(tree, os.path.dirname(way["test"])), exist_ok=True)
    brief = subprocess.run(["bash", os.path.join(HERE, "repro-brief.sh")], cwd=tree, env=env, capture_output=True, text=True)
    if brief.returncode != 0:
        return None
    with open(os.path.join(tree, ".dx-central", "brief.md"), "w", encoding="utf-8") as fh:
        fh.write(brief.stdout)
    prompt = rw.prompt(way["sandbox"], case["repo"], case["issue"], way["layer"], way["noun"], way["test"])
    model, effort = policy_model(tree)
    step = "claude" if way["sandbox"] == "php-unit" else "claude_way"
    try:
        args = claude_args("issue-repro.yml", "write", step, {"steps.policy.outputs.model": model, "steps.policy.outputs.effort": effort,
                                                             "steps.way.outputs.dir": way["dir"]})
    except KeyError as e:
        print(f"  {case['id']}: {e}", file=sys.stderr)
        return None
    if ask(prompt, args, tree) is None:
        return None
    if not os.path.isfile(os.path.join(tree, way["test"])):
        return {"wrote": False}
    written = commit_all(tree, f"test: the reproduction of #{case['issue']}")
    outcome = run_test(tree, case, way["test"], case["base"], written, os.path.join(work, "out", case["id"].replace("/", "_")), "fix: replay")
    return {"wrote": True, "outcome": outcome}


def autopilot_args(step_id, budget):
    return claude_args("autopilot.yml", step_id, step_id, {f"needs.prep.outputs.budget-{step_id} || '3'": budget,
                                                           f"needs.prep.outputs.budget-{step_id} || (needs.prep.outputs.mode == 'fix' && '10' || '20')": budget})


def replay_spec(case, work):
    tree = checkout(case, work)
    issue = issue_of(case) if tree else None
    if not issue:
        return None
    ap = _load("autopilot", "autopilot.py")
    prd = ap.schema.part_text(issue.get("body") or "", "prd")
    prompt = ap.prompt_spec(case["repo"], case["issue"], prd, None, case.get("type", ""))
    os.makedirs(os.path.join(tree, ".dx-io"), exist_ok=True)
    try:
        args = autopilot_args("spec", "3")
    except KeyError as e:
        print(f"  {case['id']}: {e}", file=sys.stderr)
        return None
    if ask(prompt, args, tree) is None:
        return None
    try:
        spec = open(os.path.join(tree, ".dx-io", "spec.md"), encoding="utf-8").read()
    except OSError:
        return {"body": prd + "\n"}
    return {"body": prd + "\n\n" + spec}


def replay_autopilot(case, work):
    tree = checkout(case, work, case["merge"])
    issue = issue_of(case) if tree else None
    if not issue:
        return None
    ap = _load("autopilot", "autopilot.py")
    body = issue.get("body") or ""
    prd = ap.schema.part_text(body, "prd")
    io = os.path.join(tree, ".dx-io")
    os.makedirs(io, exist_ok=True)
    with open(os.path.join(io, "spec.md"), "w", encoding="utf-8") as fh:
        fh.write(ap.schema.part_text(body, "spec") + "\n")
    branch = f"eval/{case['issue']}"
    git(tree, "checkout", "-q", "-b", branch)
    prompt = ap.prompt_work(case["repo"], case["issue"], 0, branch, prd, ap.left_criteria(body, ""), False)
    try:
        args = autopilot_args("work", "20")
    except KeyError as e:
        print(f"  {case['id']}: {e}", file=sys.stderr)
        return None
    if ask(prompt, args, tree) is None:
        return None
    head = commit_all(tree, "chore: what the agent left")
    out = os.path.join(work, "out", case["id"].replace("/", "_"))
    # The merged pull request's tests, as merged, against the agent's tree.
    return {t: run_test(tree, case, t, head, case["merge"], os.path.join(out, str(i)), "feat: replay") for i, t in enumerate(case["tests"])}


def replay_review(case, work):
    """The review again (local-review.sh, the same brief, profiles and
    model as the pull request's): its last.json, or None."""
    repo_dir = os.path.join(work, case["repo"].replace("/", "_") + "-review")
    if not os.path.isdir(repo_dir):
        if subprocess.run(["git", "clone", "-q", f"https://github.com/{case['repo']}", repo_dir]).returncode != 0:
            return None
    git(repo_dir, "fetch", "-q", "origin", f"refs/pull/{case['pr']}/head", case["base"])
    if git(repo_dir, "cat-file", "-e", case["head"] + "^{commit}").returncode != 0:
        git(repo_dir, "fetch", "-q", "origin", case["head"])
    if git(repo_dir, "checkout", "-q", "-B", f"eval/{case['pr']}", case["head"]).returncode != 0:
        return None
    state = os.path.join(repo_dir, ".git", "dx-review", "last.json")
    if os.path.exists(state):
        os.remove(state)
    try:
        # One case never holds the run: 15 minutes, then it is unreviewed.
        subprocess.run(["bash", os.path.join(HERE, "local-review.sh"), "--base", case["base"], "--full", "--title", case["title"]],
                       cwd=repo_dir, capture_output=True, text=True, timeout=CASE_MINUTES * 60)
    except subprocess.TimeoutExpired:
        return None
    try:
        with open(state, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# Triage's and reply's replays come with their sets (from GitHub).
REPLAYS = {"repro": replay_repro, "spec": replay_spec, "autopilot": replay_autopilot, "review": replay_review}


def run(step, cases, work):
    results = []
    for c in cases:
        try:
            got = REPLAYS[step](c, work) if step in REPLAYS else None
        except Exception as e:  # one case never stops the run: it is not replayed
            print(f"  {c['id']}: {type(e).__name__}: {e}", file=sys.stderr)
            got = None
        ok = STEPS[step]["grade"](c, got)
        print(f"  {c['id']}: {ok}", file=sys.stderr)
        results.append({"id": c["id"], "expect": c["expect"] if isinstance(c["expect"], str) else "record", "ok": ok})
    return results


# Collecting the cases from git: repro, spec and autopilot.

def cases_from_commits(step, repo, commits, n):
    """Up to n cases of STEP from first-parent commits, newest first:
    [{sha, parent, subject, body, files}]."""
    out = []
    for c in commits:
        if len(out) >= n:
            break
        subject, files = c["subject"], c["files"]
        pr = PR_OF.search(subject)
        repro = REPRO_SUBJECT.search(subject)
        if not pr or not c.get("parent"):
            continue
        if step == "repro":
            test = f"tests/repro/test_issue_{repro.group(1)}.py" if repro else ""
            if repro and test in files:
                out.append({"id": f"{repo}#{repro.group(1)}:repro", "repo": repo, "issue": int(repro.group(1)), "pr": int(pr.group(1)),
                            "base": c["parent"], "test": test, "expect": "reproduced"})
            continue
        closes = CLOSES.search(c.get("body") or "")
        kind = subject.split(":", 1)[0].split("(", 1)[0].rstrip("!")
        if repro or not closes or kind == "revert" or len(files) > MAX_FILES:
            continue
        tests = sorted(f for f in files if TEST_FILE.fullmatch(f))
        rest = sorted(f for f in files if f not in tests and not f.startswith("tests/") and f != "CHANGELOG.md" and not f.startswith("changelog.d/"))
        if not tests or not rest:
            continue
        issue = int(closes.group(1))
        base = {"id": f"{repo}#{issue}:{step}", "repo": repo, "issue": issue, "pr": int(pr.group(1)), "base": c["parent"]}
        if step == "spec":
            out.append({**base, "type": TYPE_OF.get(kind, "Task"), "files": rest, "expect": "named"})
        else:
            out.append({**base, "merge": c["sha"], "tests": tests, "expect": "passed"})
    return out


def git_commits(root, limit=400):
    log = subprocess.run(["git", "-C", root, "log", "--first-parent", f"-{limit}", "--format=%H%x00%P%x00%s%x00%b%x1e"],
                         check=True, capture_output=True, text=True).stdout
    out = []
    for rec in log.split("\x1e"):
        parts = rec.strip("\n").split("\x00")
        if len(parts) < 4:
            continue
        sha, parents, subject, body = parts
        parent = (parents.split() or [""])[0]
        files = subprocess.run(["git", "-C", root, "diff", "--name-only", parent, sha], capture_output=True, text=True).stdout.split() if parent else []
        out.append({"sha": sha, "parent": parent, "subject": subject, "body": body, "files": files})
    return out


def collect(step, n, root=ROOT):
    if step == "review":
        return collect_review(n)
    if step not in ("repro", "spec", "autopilot"):
        raise SystemExit(f"evals.py: {step}'s cases come from GitHub, which `collect` does not read yet; add them to evals/{step}/cases.json by hand")
    # This checkout is the organisation's public .github repository.
    return cases_from_commits(step, f"{org.ORG}/.github", git_commits(root), n)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def main(argv):
    if argv[:1] == ["steps"]:
        files = argv[1:] or [line.strip() for line in sys.stdin if line.strip()]
        print("\n".join(steps_of(files, with_set=True)))
        return 0
    if argv[:1] == ["collect"] and len(argv) in (2, 3) and argv[1] in STEPS:
        cases = collect(argv[1], int(argv[2]) if len(argv) == 3 else 6)
        path = os.path.join(EVALS, argv[1], "cases.json")
        write_json(path, cases)
        print(f"{len(cases)} cases in {path}")
        return 0
    if argv[:1] == ["run"] and len(argv) == 2 and argv[1] in STEPS:
        import tempfile
        with open(os.path.join(EVALS, argv[1], "cases.json"), encoding="utf-8") as fh:
            cases = json.load(fh)
        print(json.dumps(run(argv[1], cases, tempfile.mkdtemp(prefix="dx-eval-")), indent=2))
        return 0
    if argv[:1] in (["score"], ["baseline"]) and len(argv) == 3 and argv[1] in STEPS:
        step = argv[1]
        baseline = os.path.join(EVALS, step, "baseline.json")
        with open(argv[2], encoding="utf-8") as fh:
            results = json.load(fh)
        now = score(step, results)
        if argv[0] == "baseline":
            unrun = now.get("unreviewed", now.get("unrun"))
            if unrun:
                print(f"evals.py: {unrun} cases were not replayed; a baseline is written only from a whole run", file=sys.stderr)
                return 1
            write_json(baseline, now)
            print(json.dumps(now))
            return 0
        try:
            with open(baseline, encoding="utf-8") as fh:
                base = json.load(fh)
        except (OSError, ValueError):
            base = {}
        if set(base) != set(now):
            # No baseline is no gate: that fails, it never passes quietly.
            print(table(step, results, now, {}))
            print(f"\n**No baseline** for {step} at {baseline}: write one from a whole run with `evals.py baseline {step} FILE`.")
            return 1
        print(table(step, results, now, base))
        why = worse(step, now, base)
        if why:
            print(f"\n**Worse than the baseline:** {why}.")
        return 1 if why else 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
