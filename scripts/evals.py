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
             leaves (the same sandboxes): the production's loop, the work,
             then the review (local-review.sh) and its fix rounds up to
             policy/autonomy.yml's `autopilot-rounds` (#840)
  review     flag or clean, as #234 and #847 have it: a known bug is
             found again inside the lines its fix changed, a clean pull
             request is not blocked, each case played 3 times and scored
             on its median. The review is run by its own workflow,
             review-eval.yml, through scripts/review-eval.py, whose
             commands evals.py runs for it (collect, run, score,
             baseline): its set, grade, plays and gate are that script's,
             exactly, and evals.yml never runs it
  reply      a model judges, with the case's rubric (the outcome is words):
             the thread is resolved, and no further change is asked

A step's score is the share of cases that pass (the review's: bugs found
and clean pull requests blocked, review-eval.py's). evals.yml replays each case in a job of
its own (`matrix`, `run STEP CASE`), so every case gets its job's whole
time, and merges a step's results (`merge`). It fails a change whose score
is worse than the step's baseline by more than one case (a model does not
answer the same twice), by rate (passed / cases), so a set that grows or
shrinks is compared fairly. A case left not replayed is the runner's failure,
never the step's score: it fails the check with the case's name. The
slack is none when the baseline itself is not above it (1 of 6 still fails
at 0), for every step but the review, whose gate is review-eval.yml's
exactly (a slack of one case on each count, and the found floor of
policy/review-policy.default.yml's `review-eval.found-floor` whatever its
baseline, #930).
A step never baselined (not in BASELINED) whose baseline is missing or
pending passes with a warning and prints the whole run's results, what
`baseline` reads, between the lines `--- baseline STEP ---` and
`--- end ---`, for a person to commit. A baselined step's missing or
pending baseline, or any unreadable, invalid or wrongly shaped one, fails
the check: it could not tell.

  evals.py steps FILE...       the steps whose paths the files touch, one per
                               line (only those with a set that evals.yml
                               runs: never the review, which review-eval.yml
                               runs); no file at all fails (the list could
                               not be read)
  evals.py collect STEP [N]    write evals/STEP/cases.json: N cases (default
                               6; the review's, N of each kind). repro, spec
                               and autopilot from this checkout's git history
                               (the reproduced bugs; the accepted issues whose
                               merged pull request changed tests); review:
                               `review-eval.py collect N`, from its threads
                               on GitHub (GH_TOKEN, read)
  evals.py run STEP [CASE]     replay every case, or the one whose id is
                               CASE; results on stdout (JSON) (the Claude
                               Code CLI, git, the checkout); review:
                               `review-eval.py run [--play N]`
  evals.py validate [STEP...]  every case of evals/spec/ and evals/autopilot/
                               (or STEP's) passes on its merged fix, fails on
                               an assertion at its base, and asserts no
                               literal of 30 characters or more of the fix's
                               added lines; exit 1 naming each case that does
                               not, with the check it fails (#840)
  evals.py matrix [STEP...]    the replay jobs of the steps (args or stdin):
                               [{step, case, n, minutes}] on stdout (JSON)
  evals.py merge STEP FILE...  the step's results from its jobs' FILEs, in
                               the cases' order; a case none has, not
                               replayed
  evals.py score STEP FILE     the results in FILE against the baseline: a
                               table on stdout, exit 1 when worse (review:
                               `review-eval.py score FILE...`, one per play)
  evals.py baseline STEP FILE  write the results in FILE as the baseline
                               (spec, autopilot: only from a run of every
                               case of the set, each valid by `validate`)
                               (review: `review-eval.py baseline FILE...`)
  evals.py --test              self-test (offline)
"""
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import org  # noqa: E402  the organisation, from org.yml (#191)

EVALS = os.path.join(ROOT, "evals")
SLACK = 1
# The steps that have had a whole run's baseline: theirs must be there and
# read, or the check fails (could not tell); only a step not yet in this
# list may run with no baseline, or a pending one, and pass with a warning.
BASELINED = ("review", "spec", "autopilot")
# A Spec names the files it changes: at least this share of the files the
# merged pull request changed (tests and the changelog aside).
RECALL = 0.5
# A smaller change is a fairer case: no more files than this.
MAX_FILES = 20
# What counts for every step: its model and AI settings.
COMMON = ("policy/autonomy.yml",)
# The runner and its workflow count for every step evals.yml runs: a change
# to them is scored too.
RUNNER = ("scripts/evals.py", ".github/workflows/evals.yml")
# The steps another workflow runs, with its runner: the review's is
# review-eval.yml, through review-eval.py (#234, #847), which evals.py
# runs for it and evals.yml never does.
ELSEWHERE = {"review": (".github/workflows/review-eval.yml", "review-eval.py")}
REVIEW_PATHS = (
    "review-profiles/**",
    "kinds/*/review-profile.md",
    "kinds/*/rules.yml",
    "policy/review-policy.default.yml",
    "scripts/review-brief.sh",
    "scripts/local-review.sh",
    "scripts/review-verify.py",
    "scripts/review-count.py",
    "scripts/review-eval.py",
    "scripts/policy.py",
    ".github/workflows/claude-review.yml",
)
TEST_FILE = re.compile(r"tests/(?:repro/(?:.+/)?|workflows/)test_[^/]+\.py")
REPRO_SUBJECT = re.compile(r"the bug reproduced from #(\d+)")
PR_OF = re.compile(r"\(#(\d+)\)\s*$")
CLOSES = re.compile(r"\bCloses #(\d+)")
TYPE_OF = {"feat": "Feature", "fix": "Bug", "docs": "Docs"}


_LOADED = {}
# The helpers the grades and replays load: loaded once, before any agent
# runs (preload), so what an agent leaves on disk is never what grades it.
HELPERS = {"issue_schema": "issue-schema.py", "test_first": "test-first.py", "autopilot": "autopilot.py"}


def _load(name, file):
    if name not in _LOADED:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _LOADED[name] = mod
    return _LOADED[name]


def preload():
    for name, file in HELPERS.items():
        _load(name, file)


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


def review_eval():
    """scripts/review-eval.py, the review's runner: its grade, score and gate."""
    return _load("review_eval", ELSEWHERE["review"][1])


def verdict(case, review):
    """The review's grade, review-eval.py's: True, False, or None."""
    return review_eval().verdict(case, review)


def grade_reply(case, got):
    """The judge's answer, {resolved, more_asked}, read with the case's rubric."""
    if not isinstance(got, dict) or not isinstance(got.get("resolved"), bool):
        return None
    return got["resolved"] and not got.get("more_asked", False)


# Each step: the paths that count for it (with COMMON and evals/<step>/**),
# the fields its cases carry, whether a model judges it, its grade, and the
# minutes one case may take (then it is not replayed: one case never holds
# the run; the autopilot's is a whole work round).
STEPS = {
    "triage": {"paths": (".github/workflows/issue-triage.yml", "scripts/triage-brief.sh"),
               "fields": ("issue",), "judge": False, "grade": grade_triage, "minutes": 8},
    "repro": {"paths": (".github/workflows/issue-repro.yml", "scripts/repro-ways.py"),
              "fields": ("issue", "base", "test"), "judge": False, "grade": grade_repro, "minutes": 15},
    "spec": {"paths": (".github/workflows/autopilot.yml", "scripts/autopilot.py"),
             "fields": ("issue", "title", "body", "base", "merge", "type", "files"), "judge": False, "grade": grade_spec, "minutes": 15},
    "autopilot": {"paths": (".github/workflows/autopilot.yml", "scripts/autopilot.py"),
                  "fields": ("issue", "title", "body", "base", "merge", "tests"), "judge": False, "grade": grade_autopilot, "minutes": 50},
    "review": {"paths": REVIEW_PATHS, "fields": ("pr", "title", "base", "head"), "judge": False, "grade": verdict, "minutes": 15},
    "reply": {"paths": (".github/workflows/review-reply.yml",),
              "fields": ("pr", "thread", "rubric"), "judge": True, "grade": grade_reply, "minutes": 10},
}


def matches(path, pattern):
    """A glob as a workflow's `paths:` reads it: `**` any depth, `*` one
    segment."""
    rx = re.escape(pattern).replace(r"\*\*", "\0").replace(r"\*", "[^/]*").replace("\0", ".*")
    return re.fullmatch(rx, path) is not None


def paths_of(step):
    return list(STEPS[step]["paths"]) + list(COMMON) + ([] if step in ELSEWHERE else list(RUNNER)) + [f"evals/{step}/**"]


def all_paths(steps=None):
    """Every path that counts for STEPS (default: those evals.yml runs,
    every step but ELSEWHERE's), once: evals.yml's `paths:`."""
    out = []
    for step in steps or [s for s in STEPS if s not in ELSEWHERE]:
        out += [p for p in paths_of(step) if p not in out]
    return out


def has_set(step, root=ROOT):
    return os.path.isfile(os.path.join(root, "evals", step, "cases.json"))


def steps_of(files, with_set=False, root=ROOT):
    """The steps whose paths FILES touch, in the table's order; with_set:
    only those with a set (the others' sets are still to come)."""
    return [s for s in STEPS if any(matches(f, p) for f in files for p in paths_of(s)) and (not with_set or has_set(s, root))]


def steps_here(files, root=ROOT):
    """The steps evals.yml runs for FILES: those with a set, but ELSEWHERE's."""
    return [s for s in steps_of(files, with_set=True, root=root) if s not in ELSEWHERE]


def score(step, results):
    if step == "review":
        return review_eval().score(results)
    run = [r for r in results if r["ok"] is not None]
    return {"passed": sum(1 for r in run if r["ok"]), "cases": len(run), "unrun": len(results) - len(run)}


def slack(n):
    """The slack below a baseline that passed N cases: SLACK, or none when N
    is not above it (a baseline that passed one case or none, with a slack
    of one, could never fail)."""
    return SLACK if n > SLACK else 0


def worse(step, now, base):
    """Why the score is worse than the baseline by more than its slack, or ''."""
    why = []
    if step == "review":
        # review-eval.yml's gate, exactly: review-eval.py's (a slack of one
        # case on each count, whatever the baseline; the scaling is the others').
        return review_eval().worse(now, base)
    # By rate (passed / cases), so a change that adds or removes cases is
    # compared fairly: below (baseline passed - slack) / baseline cases, the
    # slack still one case of the baseline's set (none when the baseline
    # passed one case or none).
    floor = base["passed"] - slack(base["passed"]) if base.get("cases") else 0
    if floor > 0 and (now["passed"] * base["cases"] < floor * now["cases"] or not now["cases"]):
        why.append(f"{now['passed']} of {now['cases']} cases passed, the baseline {base['passed']} of {base['cases']}")
    return "; ".join(why)


def read_baseline(step, path, now):
    """(baseline, '') for a score of NOW's shape; (None, '') for a step not in
    BASELINED whose file is missing or pending (its first run); otherwise
    (None, why): unreadable, not JSON, the wrong shape, or a BASELINED step's
    missing or pending, which fails the check."""
    try:
        with open(path, encoding="utf-8") as fh:
            base = json.load(fh)
    except FileNotFoundError:
        base = {"pending": "missing"}
    except (OSError, ValueError) as e:
        return None, f"evals/{step}/baseline.json is unreadable or not JSON ({e})"
    if isinstance(base, dict) and set(base) == set(now) and all(isinstance(v, int) for v in base.values()):
        return base, ""
    if isinstance(base, dict) and set(base) == {"pending"}:
        if step in BASELINED:
            return None, f"{step} has had a baseline, and evals/{step}/baseline.json is {'missing' if base['pending'] == 'missing' else 'pending'}"
        return None, ""
    return None, f"evals/{step}/baseline.json is neither a score of {sorted(now)} nor pending"


def unreplayed(step, results):
    """The cases the runner left not replayed, by name: that fails the
    runner (the review's are review-eval.py's to judge)."""
    return [] if step in ELSEWHERE else [r["id"] for r in results if r["ok"] is None]


# A replay job's time: the step's limit for its one case, and the job's own
# (the checkout, the CLI, the case's tests).
JOB_MINUTES = 30


def load_cases(step, root=ROOT):
    with open(os.path.join(root, "evals", step, "cases.json"), encoding="utf-8") as fh:
        return json.load(fh)


# The longest a job of GitHub's hosted runners may run.
MAX_JOB_MINUTES = 360


def job_minutes(step):
    """A replay job's time: the step's for one case, and the job's own; the
    autopilot's, its work and each of the production's rounds (a review and
    a fix), within a hosted job's limit."""
    if step != "autopilot":
        return STEPS[step]["minutes"] + JOB_MINUTES
    rounds = eval_rounds()
    # One review more than the rounds: the slack that keeps the last round's
    # check (its review and fix must fit before the job's end) from failing
    # on the seconds the work itself took past its own budget.
    return min(MAX_JOB_MINUTES, STEPS[step]["minutes"] * (1 + rounds) + STEPS["review"]["minutes"] * (rounds + 1) + JOB_MINUTES)


def matrix(steps, root=ROOT):
    """One replay job per case of each step: the matrix evals.yml runs."""
    return [{"step": s, "case": c["id"], "n": n, "minutes": job_minutes(s)}
            for s in steps for n, c in enumerate(load_cases(s, root))]


def merge(cases, parts):
    """The results of the step's jobs, in its cases' order; a case no job
    gave is not replayed (its job ran out of time, or never ran)."""
    got = {r["id"]: r for part in parts for r in part}
    return [got.get(c["id"]) or {"id": c["id"], "expect": c["expect"] if isinstance(c["expect"], str) else "record", "ok": None}
            for c in cases]


def table(step, results, now, base):
    out = ["| Case | Expects | Result |", "| --- | --- | --- |"]
    if step == "review":
        return review_eval().table(results, now, base)
    for r in results:
        res = "could not replay" if r["ok"] is None else ("as expected" if r["ok"] else "**failed**")
        out.append(f"| {r['id']} | {r['expect']} | {res} |")
    out += ["", f"{step}: {now['passed']} of {now['cases']} cases passed (baseline {base.get('passed', '?')} of {base.get('cases', '?')}); "
            f"{now['unrun']} not replayed."]
    return "\n".join(out)


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


# Replaying a case: a checkout of its repository at its base, the step's
# own prompt and arguments (read from its workflow, so a change to them is
# what is measured), the Claude Code CLI, and the grade's evidence.

# What the replay may hand the model: never a token.
SECRET_ENV = ("GH_TOKEN", "GITHUB_TOKEN")
# What of the organisation's checkout a replayed step sees as .dx-central.
CENTRAL_PARTS = ("scripts", "policy", "kinds", "rules", "review-profiles", "design-systems", "org.yml", "repos.yml", "labels.yml", "agents-block.md")


# The model's keys: the agent's and the review's CLI need them, git never
# does (#840).
MODEL_ENV = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
# Git with no hooks and no system or global config: what an agent planted
# around its tree never runs (the tree's own config is never read by the
# review either: it reads a clone, review_round).
GIT_SAFE = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": "/dev/null",
            "GIT_CONFIG_KEY_1": "core.fsmonitor", "GIT_CONFIG_VALUE_1": "false"}


def git_env(keep_model=False):
    """The environment git runs in: no token, no model key (unless the
    review's CLI, which runs it, needs it), hooks and outside config off."""
    drop = SECRET_ENV + (() if keep_model else MODEL_ENV)
    return {**{k: v for k, v in os.environ.items() if k not in drop}, **GIT_SAFE}


def git(repo_dir, *args):
    return subprocess.run(["git", "-C", repo_dir, "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", *args],
                          capture_output=True, text=True, env=git_env())


def clone_of(case, work, *refs):
    """The case's repository, cloned once per run, with REFS fetched."""
    clone = os.path.join(work, case["repo"].replace("/", "_"))
    if not os.path.isdir(clone):
        if subprocess.run(["git", "clone", "-q", "--no-checkout", f"https://github.com/{case['repo']}", clone]).returncode != 0:
            return None
    for ref in refs:
        if git(clone, "cat-file", "-e", ref + "^{commit}").returncode != 0:
            git(clone, "fetch", "-q", "origin", ref)
    return clone


def checkout(case, work):
    """(tree, its base commit) for the agent: the case's base as one commit
    in a repository of its own, so no history after the base (the merged
    change, the case's answer) is there to read; None when it cannot be had."""
    clone = clone_of(case, work, case["base"])
    if not clone:
        return None
    tree = os.path.join(work, "trees", re.sub(r"[^A-Za-z0-9._-]", "_", case["id"]))
    os.makedirs(tree)
    archive = subprocess.run(["git", "-C", clone, "archive", case["base"]], capture_output=True)
    if archive.returncode != 0 or git(tree, "init", "-q").returncode != 0:
        return None
    if subprocess.run(["tar", "-x", "-C", tree], input=archive.stdout).returncode != 0:
        return None
    base = commit_all(tree, f"the base of {case['id']}")
    copy_central(os.path.join(tree, ".dx-central"))
    return tree, base


def copy_central(dest, root=ROOT):
    """The step's helpers and brief, under .dx-central as in its workflow:
    this checkout's, so the change under evaluation is what runs; only what
    the steps read, never its tests nor its sets (the answers). A copy, never
    a link: what the agent writes there stays in its tree (#830)."""
    os.makedirs(dest, exist_ok=True)
    for name in CENTRAL_PARTS:
        src, to = os.path.join(root, name), os.path.join(dest, name)
        if os.path.lexists(to):
            continue
        if os.path.isdir(src):
            shutil.copytree(src, to, symlinks=False, ignore=shutil.ignore_patterns("__pycache__"))
        elif os.path.isfile(src):
            shutil.copyfile(src, to)


def fingerprint(root=ROOT):
    """A hash of every file of this checkout's parts the runner executes
    after an agent (.dx-central's parts and the workflows)."""
    h = hashlib.sha256()
    for name in (*CENTRAL_PARTS, ".github"):
        top = os.path.join(root, name)
        paths = [top] if not os.path.isdir(top) else sorted(os.path.join(d, f) for d, _, fs in os.walk(top) for f in fs)
        for path in paths:
            h.update(path.encode() + b"\0")
            try:
                h.update(os.readlink(path).encode() if os.path.islink(path) else open(path, "rb").read())
            except OSError:
                h.update(b"-")
    return h.hexdigest()


def issue_of(case):
    """The case's issue, {title, body}, as pinned in the case when it was
    collected; never read from GitHub at replay, where an edit to an old
    issue would change the case and its score. A case without them is
    refused by name (it is then not replayed)."""
    title, body = case.get("title"), case.get("body")
    if not (isinstance(title, str) and title.strip() and isinstance(body, str) and body.strip()):
        print(f"  {case.get('id')}: no pinned issue title and body, not replayed", file=sys.stderr)
        return None
    return {"title": title, "body": body}


def pin_issue(case):
    """CASE with its issue's title and body, read once from GitHub when the
    case is collected; the replay reads them from the case alone."""
    got = json.loads(gh("issue", "view", str(case["issue"]), "--repo", case["repo"], "--json", "title,body"))
    return {**case, "title": got.get("title") or "", "body": got.get("body") or ""}


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


def ask(prompt, args, cwd, step, root=ROOT):
    """The Claude Code CLI on PROMPT in CWD with ARGS, within the step's
    minutes; its JSON result, or None (no answer, or the CLI's error: a bad
    token, a rate limit, which is "could not replay", never a failed case).
    An agent that changed this checkout stops the whole run (SystemExit, not
    caught per case): what runs next, with the keys, would be its code."""
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
    before = fingerprint(root)
    try:
        got = subprocess.run(["claude", "-p", prompt, *args, "--output-format", "json"], cwd=cwd, env=env,
                             capture_output=True, text=True, timeout=STEPS[step]["minutes"] * 60)
        result = json.loads(got.stdout)
    except (subprocess.TimeoutExpired, ValueError):
        result = None
    finally:
        if fingerprint(root) != before:
            raise SystemExit(f"evals.py: the {step} agent changed {root}; the run stops, nothing of it is graded")
    if not isinstance(result, dict) or result.get("is_error"):
        return None
    return result


def commit_all(tree, message):
    git(tree, "add", "-A", "--", ".", ":!.dx-central", ":!.dx-io")
    git(tree, "-c", "user.name=evals", "-c", "user.email=evals@localhost", "commit", "-q", "--allow-empty", "-m", message)
    return git(tree, "rev-parse", "HEAD").stdout.strip()


def run_test(tree, case, base, test, ref, test_ref, out_dir, title):
    """TEST as committed at TEST_REF, run against REF's tree, through the
    way's sandbox (test-first.py); its outcome, or None."""
    tf = _load("test_first", "test-first.py")
    plan = tf.plan(tree, ROOT, title, base, test_ref, case["repo"].split("/")[-1], str(case["issue"]),
                   at_base=case["repo"] == f"{org.ORG}/.github")
    entry = next((t for t in plan.get("tests") or [] if t["test"] == test), None)
    if not entry:
        return None
    return tf.run_one(tree, ROOT, entry, ref, test_ref, out_dir)


def autopilot_args(step_id, budget):
    return claude_args("autopilot.yml", step_id, step_id, {f"needs.prep.outputs.budget-{step_id} || '3'": budget,
                                                           f"needs.prep.outputs.budget-{step_id} || (needs.prep.outputs.mode == 'fix' && '10' || '20')": budget})


def replay_spec(case, work):
    got = checkout(case, work)
    issue = issue_of(case) if got else None
    if not issue:
        return None
    tree = got[0]
    ap = _load("autopilot", "autopilot.py")
    prd = ap.schema.part_text(issue.get("body") or "", "prd")
    prompt = ap.prompt_spec(case["repo"], case["issue"], prd, None, case.get("type", ""))
    os.makedirs(os.path.join(tree, ".dx-io"), exist_ok=True)
    try:
        args = autopilot_args("spec", "3")
    except KeyError as e:
        print(f"  {case['id']}: {e}", file=sys.stderr)
        return None
    if ask(prompt, args, tree, "spec") is None:
        return None
    try:
        spec = open(os.path.join(tree, ".dx-io", "spec.md"), encoding="utf-8").read()
    except OSError:
        return {"body": prd + "\n"}
    return {"body": prd + "\n\n" + spec}


def replay_autopilot(case, work):
    got = checkout(case, work)
    issue = issue_of(case) if got else None
    if not issue:
        return None
    tree = got[0]
    ap = _load("autopilot", "autopilot.py")
    body = issue.get("body") or ""
    prd = ap.schema.part_text(body, "prd")
    io = os.path.join(tree, ".dx-io")
    os.makedirs(io, exist_ok=True)
    with open(os.path.join(io, "spec.md"), "w", encoding="utf-8") as fh:
        fh.write(ap.schema.part_text(body, "spec") + "\n")
    # The draft the production opens (#840): its branch, title and body,
    # which the review reads as the pull request's.
    issue_type = case.get("type") or TYPE_OF.get(case["title"].split(":", 1)[0].split("(", 1)[0].rstrip("!").strip().lower(), "Task")
    draft = ap.draft(str(case["issue"]), issue_type, case["title"], body)
    branch = draft["branch"]
    with open(os.path.join(io, "pr.md"), "w", encoding="utf-8") as fh:
        fh.write(draft["body"] + "\n")
    git(tree, "checkout", "-q", "-b", branch)
    prompt = ap.prompt_work(case["repo"], case["issue"], 0, branch, prd, ap.left_criteria(body, ""), False)
    try:
        args = autopilot_args("work", "20")
    except KeyError as e:
        print(f"  {case['id']}: {e}", file=sys.stderr)
        return None
    if ask(prompt, args, tree, "autopilot") is None:
        return None
    head = commit_all(tree, "chore: what the agent left")
    # The production's loop (#840): the review, then a fix round on what it
    # blocks, up to EVAL_ROUNDS (#941); graded on the tree it leaves.
    rounds = eval_rounds()
    try:
        fix_args = autopilot_args("work", "10")
    except KeyError as e:
        print(f"  {case['id']}: {e}", file=sys.stderr)
        return None
    # Each round within the job's time: one that could not finish there
    # leaves the case not replayed, by name, never graded half done.
    import time
    ends = time.monotonic() + (job_minutes("autopilot") - JOB_MINUTES - STEPS["autopilot"]["minutes"]) * 60
    for rnd in range(1, rounds + 1):
        if time.monotonic() + (STEPS["autopilot"]["minutes"] + STEPS["review"]["minutes"]) * 60 > ends:
            print(f"  {case['id']}: no time left for fix round {rnd} of {rounds} in the job", file=sys.stderr)
            return None
        review = review_round(tree, got[1], draft["title"], os.path.join(io, "pr.md"))
        if review is None:
            return None
        blocking, findings = review
        if not blocking:
            break
        with open(os.path.join(io, "review.md"), "w", encoding="utf-8") as fh:
            fh.write(findings)
        if ask(ap.prompt_fix(case["repo"], 0, rnd, rounds), fix_args, tree, "autopilot") is None:
            return None
        head = commit_all(tree, f"chore: what fix round {rnd} left")
    # Only now the merged commit comes in, for its tests: the agent is done.
    clone = clone_of(case, work, case["merge"])
    if not clone:
        return None
    return merged_tests(tree, case, clone, head, os.path.join(work, "out", case["id"].replace("/", "_")))


# The replay's fix rounds (#941): one review and at most one fix round, not
# the production's `autopilot-rounds`. Whether a change made the step worse
# shows in the first round; every further round multiplied the cost of a
# replay without telling much more.
EVAL_ROUNDS = 1


def eval_rounds(root=ROOT):
    """The replay's fix rounds: EVAL_ROUNDS, never more than the
    production's `autopilot-rounds` (max_rounds)."""
    return min(EVAL_ROUNDS, max_rounds(root))


def max_rounds(root=ROOT):
    """The production's limit of review rounds, policy/autonomy.yml's
    `autopilot-rounds`, read from this checkout before any agent runs."""
    import yaml
    with open(os.path.join(root, "policy", "autonomy.yml"), encoding="utf-8") as fh:
        return int(yaml.safe_load(fh)["autopilot-rounds"])


def review_round(tree, base, title, body_file, root=ROOT):
    """The production's review of the agent's branch, as the autopilot's own
    pre-review runs it and the pull request's review reads it (the same
    brief, profile and policy: local-review.sh, the change's own); (blocking,
    findings) or None when it gave no verdict. An agent that changed this
    checkout stops the whole run, as in ask."""
    # The review, whose CLI holds the model key, never runs git in the tree
    # the agent wrote, whose .git may hold a hook or a config of its own: it
    # reads a fresh clone of its commits (made without the key), with no
    # hooks and no outside config, under the tree's own name.
    review = os.path.join(os.path.dirname(os.path.abspath(tree)), "review", os.path.basename(os.path.abspath(tree)))
    shutil.rmtree(review, ignore_errors=True)
    os.makedirs(os.path.dirname(review), exist_ok=True)
    if git(os.path.dirname(review), "clone", "-q", "--no-hardlinks", os.path.abspath(tree), review).returncode != 0:
        return None
    git(review, "remote", "remove", "origin")
    env = git_env(keep_model=True)
    findings = os.path.join(review, ".git", "dx-review", "findings.md")
    before = fingerprint(root)
    try:
        got = subprocess.run(["bash", os.path.join(root, "scripts", "local-review.sh"), "--base", base, "--title", title, "--body-file", body_file, "--full"],
                             cwd=review, env=env, capture_output=True, text=True, timeout=STEPS["review"]["minutes"] * 60)
    except subprocess.TimeoutExpired:
        return None
    finally:
        if fingerprint(root) != before:
            raise SystemExit(f"evals.py: the review of the autopilot's work changed {root}; the run stops, nothing of it is graded")
    if got.returncode not in (0, 1) or not os.path.isfile(findings):
        return None
    with open(findings, encoding="utf-8") as fh:
        return got.returncode == 1, fh.read()


def merged_tests(tree, case, clone, head, out):
    """The merged pull request's tests, as merged, against the agent's tree
    (HEAD): {test: outcome}, or None when the merge cannot be fetched. The
    plan diffs the case's real base with the merge, both of the fetched
    history: the tree's own one-commit base shares no commit with it, and
    `base...merge` needs a merge base (#830)."""
    if git(tree, "fetch", "-q", clone, case["merge"]).returncode != 0:
        return None
    return {t: run_test(tree, case, case["base"], t, head, case["merge"], os.path.join(out, str(i)), "feat: replay") for i, t in enumerate(case["tests"])}


# Validating the cases (#840): a case measures the task only if it passes
# on its merged fix, fails on an assertion at its base, and asserts none of
# the fix's own literals (a test that greps the fix's sentences passes for
# whoever copies them, and fails for any other right answer).

# A literal this long, in the fix's added lines and in what the case
# asserts, is the fix's own text, not its behaviour.
LITERAL = 30
QUOTED = re.compile(r"\"((?:[^\"\\\n]|\\.){%d,})\"|'((?:[^'\\\n]|\\.){%d,})'" % (LITERAL, LITERAL))
# The steps whose cases `validate` holds to the rule.
VALIDATED = ("spec", "autopilot")


def literals(text, n=LITERAL):
    """The quoted strings of TEXT of N characters or more."""
    return {a or b for a, b in QUOTED.findall(text or "") if len(a or b) >= n}


def added_lines(diff, exclude):
    """The `+` lines of a unified DIFF, the files of EXCLUDE (the case's own
    tests) left out: the merged fix's added text, one line each."""
    out, skip = [], False
    for line in (diff or "").splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            skip = (path[2:] if path.startswith("b/") else path) in exclude
        elif line.startswith("+") and not skip:
            out.append(line[1:])
    return "\n".join(out)


def asserted_literals(path, text, n=LITERAL):
    """The literals of N characters or more that the test at PATH asserts:
    in Python, the strings inside its assert statements (a path it opens or
    a fixture it builds asserts nothing); in any other file, or one Python
    cannot parse, every quoted string."""
    if path.endswith(".py"):
        import ast
        try:
            tree = ast.parse(text or "")
        except SyntaxError:
            return literals(text, n)
        return {c.value for a in ast.walk(tree) if isinstance(a, ast.Assert)
                for c in ast.walk(a) if isinstance(c, ast.Constant) and isinstance(c.value, str) and len(c.value) >= n}
    return literals(text, n)


def leaks(asserted, added):
    """The literals of ASSERTED (a set) that the fix's ADDED lines carry:
    the fix's own words, asserted."""
    return sorted(x for x in asserted if x in added)


def spec_answer(case):
    """The merged issue's real PRD and Spec, as replay_spec hands them to
    the grade; and its PRD alone, the base's (no `Spec: files`)."""
    schema = _load("issue_schema", "issue-schema.py")
    body = case.get("body") or ""
    prd = schema.part_text(body, "prd")
    return prd + "\n\n" + schema.part_text(body, "spec"), prd + "\n"


def check_case(step, case, facts):
    """What makes CASE invalid, one `<check>: <why>` each (merge, base,
    literal), from its FACTS: for autopilot {merge, base: {test: outcome},
    added, tests_text: {test: text at merge}}; for spec {added}."""
    problems = []
    if step == "spec":
        merged, prd = spec_answer(case)
        if grade_spec(case, {"body": merged}) is not True:
            problems.append("merge: the merged issue's own Spec does not pass the grade")
        if grade_spec(case, {"body": prd}) is not False:
            problems.append("base: the PRD alone does not fail the grade")
        # A spec case asserts the files the Spec names: a string literal of
        # the fix's added lines that is in one of them is the fix's text.
        files = "\n".join(case.get("files") or [])
        asserted = {x for x in literals(facts.get("added") or "") if x in files}
    else:
        at_merge, at_base = facts.get("merge") or {}, facts.get("base") or {}
        not_passing = [f"{t} ({at_merge.get(t)})" for t in case["tests"] if at_merge.get(t) != "passed"]
        if not_passing:
            problems.append("merge: does not pass on its merged fix: " + ", ".join(not_passing))
        # "reproduced": the test ran and failed on an assertion; broken (an
        # error, a collection error) or no outcome is no measure.
        broken = [f"{t} ({at_base.get(t)})" for t in case["tests"] if at_base.get(t) not in ("reproduced", "passed")]
        if broken:
            problems.append("base: breaks at its base without failing an assertion: " + ", ".join(broken))
        elif not any(at_base.get(t) == "reproduced" for t in case["tests"]):
            problems.append("base: every test passes at its base, so none fails on an assertion")
        asserted = set().union(*(asserted_literals(t, (facts.get("tests_text") or {}).get(t) or "") for t in case["tests"]))
    leaked = leaks(asserted, facts.get("added") or "")
    if leaked:
        problems.append("literal: asserts the merged fix's own text: " + "; ".join(repr(x[:60]) for x in leaked[:3]))
    return problems


def facts_of(step, case, work):
    """What check_case reads, from the case's repository at its base and its
    merge (the tests run through test-first.py's sandbox, as merged_tests
    runs them); None when it cannot be had."""
    clone = clone_of(case, work, case["base"], case["merge"])
    if not clone:
        return None
    diff = git(clone, "diff", case["base"], case["merge"])
    if diff.returncode != 0:
        return None
    # The case's own tests and their fixtures (every file under tests/, as
    # collect leaves them out of a spec case's files): what they quote is
    # no fix's text.
    changed = git(clone, "diff", "--name-only", case["base"], case["merge"]).stdout.split()
    added = added_lines(diff.stdout, {f for f in changed if f.startswith("tests/")})
    if step == "spec":
        return {"added": added}
    out = os.path.join(work, "validate", re.sub(r"[^A-Za-z0-9._-]", "_", case["id"]))
    at = {}
    for ref in ("merge", "base"):
        at[ref] = {t: run_test(clone, case, case["base"], t, case[ref], case["merge"], os.path.join(out, ref, str(i)), "feat: validate")
                   for i, t in enumerate(case["tests"])}
    texts = {t: git(clone, "show", f"{case['merge']}:{t}").stdout for t in case["tests"]}
    return {**at, "added": added, "tests_text": texts}


def validate(step, cases, work):
    """[(case id, its first problem)] for every case of STEP's set that is
    not valid; a case whose facts cannot be had is not valid either."""
    if cases:
        preload()
    bad = []
    for c in cases:
        try:
            got = facts_of(step, c, work)
        except Exception as e:  # one case never stops the check: it is invalid, by name
            got, why = None, f"{type(e).__name__}: {e}"
        else:
            why = "its repository, base or merge could not be had"
        problems = check_case(step, c, got) if got is not None else [f"facts: {why}"]
        print(f"  {c['id']}: " + ("valid" if not problems else "; ".join(problems)), file=sys.stderr)
        if problems:
            bad.append((c["id"], problems[0]))
    return bad


# Triage's and reply's replays come with their sets (from GitHub), and
# repro's with its set, in their own issue (#735's follow-up).
# The review's is review-eval.py's (ELSEWHERE).
REPLAYS = {"spec": replay_spec, "autopilot": replay_autopilot}


def run(step, cases, work):
    results = []
    if step in REPLAYS and cases:
        preload()
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
            out.append({**base, "merge": c["sha"], "type": TYPE_OF.get(kind, "Task"), "files": rest, "expect": "named"})
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
    if step not in ("repro", "spec", "autopilot"):
        raise SystemExit(f"evals.py: {step}'s cases come from GitHub, which `collect` does not read yet; add them to evals/{step}/cases.json by hand")
    # This checkout is the organisation's public .github repository.
    if step == "repro":
        return cases_from_commits(step, f"{org.ORG}/.github", git_commits(root), n)
    # The set's own cases first, as they are pinned, then every candidate
    # of the history, and only the valid ones, up to N (#840): a case that
    # does not measure the task never enters the set, and none enters twice.
    import itertools
    import tempfile
    preload()
    work, out = tempfile.mkdtemp(prefix="dx-collect-"), []
    try:
        mine = load_cases(step, root)
    except FileNotFoundError:
        mine = []
    seen = {c["id"] for c in mine}
    history = (c for c in cases_from_commits(step, f"{org.ORG}/.github", git_commits(root), 10 ** 6) if c["id"] not in seen)
    for c in itertools.chain(mine, history):
        if len(out) >= n:
            break
        c = c if c["id"] in seen else pin_issue(c)
        got = facts_of(step, c, work)
        kept = rewritten(step, c, got) if got is not None else None
        print(f"  {c['id']}: " + ("kept" if kept else "not valid, left out"), file=sys.stderr)
        if kept:
            out.append(kept)
    return out


def rewritten(step, case, facts):
    """CASE made valid from its FACTS, or None: an autopilot case keeps the
    merged tests that are valid alone (they pass on the fix, fail on an
    assertion at the base, and assert none of its literals); a spec case is
    valid as it is, or not at all."""
    if step == "autopilot":
        case = {**case, "tests": [t for t in case["tests"] if not check_case(step, {**case, "tests": [t]}, facts)]}
        if not case["tests"]:
            return None
    return case if not check_case(step, case, facts) else None


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    # The mapping (C2): each step's paths, the common ones, none for the rest.
    check("steps: a step's workflow is its step", steps_of([".github/workflows/issue-repro.yml"]), ["repro"])
    check("steps: autopilot.yml and autopilot.py count for spec and autopilot", (steps_of([".github/workflows/autopilot.yml"]), steps_of(["scripts/autopilot.py"])),
          (["spec", "autopilot"], ["spec", "autopilot"]))
    check("steps: the review's paths, as review-eval.yml listed them", [steps_of([p]) for p in ("review-profiles/general.md", "kinds/x/review-profile.md", "kinds/x/rules.yml", "scripts/local-review.sh", ".github/workflows/claude-review.yml")],
          [["review"]] * 5)
    check("steps: policy/autonomy.yml counts for every step", steps_of(["policy/autonomy.yml"]), list(STEPS))
    import contextlib
    import io
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        stdin, sys.stdin = sys.stdin, io.StringIO("\n")
        try:
            empty = main(["steps"])
        finally:
            sys.stdin = stdin
    check("steps: no changed file fails (the list could not be read), never selects nothing", empty, 1)
    check("steps: a set counts for its step alone", (steps_of(["evals/review/cases.json"]), steps_of(["evals/spec/baseline.json"])), (["review"], ["spec"]))
    check("steps: an unrelated path runs nothing", steps_of(["README.md", "scripts/sync-repos.py", "evals/README.md", "kinds/x/pack.yml"]), [])
    check("steps: a glob's * stays in one folder", (matches("kinds/a/b/rules.yml", "kinds/*/rules.yml"), matches("review-profiles/a/b.md", "review-profiles/**")), (False, True))
    check("steps: every path once in the union, the review's not in it", (len(all_paths()) == len(set(all_paths())), set(all_paths()) & set(REVIEW_PATHS)), (True, set()))

    # The review (#234, #847): review-eval.py's grade, score and gate, run
    # through it, never a copy of them.
    re_ = review_eval()
    case_f = {"expect": "flag", "path": "a.php", "line": 10, "fixed": [[9, 11]]}
    found = {"findings": [{"severity": "major", "file": "a.php", "line": 10}]}
    elsewhere = {"findings": [{"severity": "major", "file": "a.php", "line": 40}]}
    check("review verdict: review-eval.py's (inside the lines the fix changed, not just its file)",
          (verdict(case_f, found), verdict(case_f, elsewhere), verdict({"expect": "clean"}, found), verdict(case_f, None)),
          (re_.verdict(case_f, found), re_.verdict(case_f, elsewhere), re_.verdict({"expect": "clean"}, found), None))
    check("review verdict: another line of the file is a miss", verdict(case_f, elsewhere), False)
    plays = [{"id": "1", "expect": "flag", "plays": [True, True, False]}, {"id": "2", "expect": "clean", "plays": [False, False, True]}]
    now = score("review", plays)
    check("review score and table: review-eval.py's, on its plays' median", (now, table("review", plays, now, {})), (re_.score(plays), re_.table(plays, now, {})))
    rbase = {"found": 1, "flag": 6, "blocked": 0, "clean": 6, "unreviewed": 0, "plays": re_.PLAYS}
    check("review worse: review-eval.py's gate, its found floor whatever the baseline (#930)",
          ("below the floor" in worse("review", {**rbase, "found": 0}, rbase), worse("review", {**rbase, "found": 0}, {**rbase, "found": 2}) == re_.worse({**rbase, "found": 0}, {**rbase, "found": 2})), (True, True))
    check("review: run elsewhere (review-eval.yml), never by evals.yml", (steps_here(["review-profiles/general.md"]), steps_of(["review-profiles/general.md"], with_set=True), unreplayed("review", [{"id": "r", "ok": None}])),
          ([], ["review"], []))
    check("review: the runner's own files count for the steps evals.yml runs, not the review's", (steps_of(["scripts/evals.py"]), steps_of(["policy/autonomy.yml"])),
          ([s for s in STEPS if s not in ELSEWHERE], list(STEPS)))
    check("review: the commands go to review-eval.py", (review_args(["collect", "review", "10"]), review_args(["run", "review", "--play", "2"]),
          review_args(["score", "review", "a", "b"]), review_args(["baseline", "review", "a"]), review_args(["matrix", "review"]), review_args(["run", "spec"])),
          (["collect", "10"], ["run", "--play", "2"], ["score", "a", "b"], ["baseline", "a"], None, None))

    # Every other step's grade.
    t = {"expect": {"category": "duplicate", "duplicate_of": 12, "exists_in_pro": False}}
    check("triage: the record's category, duplicate_of and exists_in_pro", (
        grade_triage(t, {"category": "duplicate", "duplicate_of": 12, "layer": "logic"}), grade_triage(t, {"category": "duplicate", "duplicate_of": 13}),
        grade_triage(t, {"category": "duplicate", "duplicate_of": 12, "exists_in_pro": True}), grade_triage(t, {"category": "enhancement"}),
        grade_triage({"expect": {"category": "enhancement"}}, {"category": "enhancement", "duplicate_of": 0}), grade_triage(t, None)),
        (True, False, False, False, True, None))
    r = {"test": "tests/repro/test_issue_7.py"}
    check("repro: the test fails at the base on an assertion; broken or passing is not; no run is unknown", (
        grade_repro(r, {"wrote": True, "outcome": "reproduced"}), grade_repro(r, {"wrote": True, "outcome": "broken"}), grade_repro(r, {"wrote": True, "outcome": "passed"}),
        grade_repro(r, {"wrote": False}), grade_repro(r, {"wrote": True, "outcome": "limit"}), grade_repro(r, None)),
        (True, False, False, False, None, None))
    prd = ("### Problem\n\nNo dark mode.\n\n### Scope\n\n- A toggle.\n\n### Out of scope\n\n- Themes.\n\n### Acceptance criteria\n\n"
           "- C1: Given a visitor, when they press the toggle, then the page turns dark.\n\n### Criticality\n\nNormal\n\n")
    spec = prd + "### Spec: approach\n\nA class.\n\n### Spec: files\n\n- header.php\n- assets/dark.css\n\n### Spec: tests\n\n- C1 → tests/e2e/toggle.spec.ts\n"
    c = {"type": "Bug", "files": ["header.php", "assets/dark.css", "footer.php"]}
    check("spec: the schema passes and the Spec names enough of the merged files", (
        grade_spec(c, {"body": spec}), grade_spec({**c, "files": ["a.php", "b.php", "header.php"]}, {"body": spec}),
        grade_spec(c, {"body": prd}), grade_spec({**c, "type": "Feature"}, {"body": spec}), grade_spec(c, None)),
        (True, False, False, False, None))
    check("spec: only the Spec's files section names a file", files_named(spec.replace("- header.php\n", "") + "\nheader.php\n", ["header.php"]), [])
    a = {"tests": ["tests/a.py", "tests/b.py"]}
    check("autopilot: every test of the merged pull request passes", (
        grade_autopilot(a, {"tests/a.py": "passed", "tests/b.py": "passed"}), grade_autopilot(a, {"tests/a.py": "passed", "tests/b.py": "reproduced"}),
        grade_autopilot(a, {"tests/a.py": "passed", "tests/b.py": "limit"}), grade_autopilot(a, {"tests/a.py": "passed"}), grade_autopilot(a, {})),
        (True, False, None, None, None))
    check("reply: the judge says resolved, with no further change asked", (
        grade_reply({}, {"resolved": True, "more_asked": False}), grade_reply({}, {"resolved": True, "more_asked": True}),
        grade_reply({}, {"resolved": False}), grade_reply({}, {"resolved": "yes"})), (True, False, False, None))

    # The score of every other step, and its gate.
    res = [{"id": "1", "expect": "passed", "ok": True}, {"id": "2", "expect": "passed", "ok": False}, {"id": "3", "expect": "passed", "ok": None}]
    now = score("autopilot", res)
    check("score: passed, cases replayed, not replayed", now, {"passed": 1, "cases": 2, "unrun": 1})
    check("worse: by rate, so a set of another size is compared fairly",
          (worse("spec", {"passed": 10, "cases": 12, "unrun": 0}, {"passed": 5, "cases": 6}), bool(worse("spec", {"passed": 6, "cases": 12, "unrun": 0}, {"passed": 5, "cases": 6}))), ("", True))
    check("worse: one case of slack", (worse("spec", now, {"passed": 2, "cases": 2}), worse("spec", now, {"passed": 3, "cases": 3}).startswith("1 of 2 cases passed")), ("", True))
    check("worse: a baseline not above the slack has none (1 of 6, then 0 of 6, fails)",
          (worse("autopilot", {"passed": 0, "cases": 6, "unrun": 0}, {"passed": 1, "cases": 6, "unrun": 0}).startswith("0 of 6"),
           worse("autopilot", {"passed": 1, "cases": 6, "unrun": 0}, {"passed": 1, "cases": 6, "unrun": 0})), (True, ""))
    import tempfile
    d = tempfile.mkdtemp(prefix="dx-eval-test-")
    def base_of(step, text):
        f = os.path.join(d, "baseline.json")
        if text is None:
            if os.path.exists(f):
                os.remove(f)
        else:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(text)
        b, why = read_baseline(step, f, now)
        return (b, bool(why))
    check("baseline: a score is read; missing or pending only for a step never baselined",
          (base_of("repro", json.dumps({"passed": 1, "cases": 2, "unrun": 0})), base_of("repro", None), base_of("repro", '{"pending": "first run"}')),
          (({"passed": 1, "cases": 2, "unrun": 0}, False), (None, False), (None, False)))
    check("baseline: corrupt, wrong keys, or a baselined step's missing or pending, cannot tell (fails)",
          [base_of(s, t)[1] for s, t in (("repro", "{not json"), ("repro", '{"found": 1}'), ("repro", "[1]"),
                                         ("autopilot", '{"pending": "x"}'), ("spec", None))], [True] * 5)
    shutil.rmtree(d, ignore_errors=True)
    check("unreplayed: a case not replayed fails the runner by its name", unreplayed("spec", res), ["3"])
    check("merge: the cases' order, a case no job gave not replayed",
          merge([{"id": "1", "expect": "passed"}, {"id": "2", "expect": {"category": "bug"}}, {"id": "3", "expect": "passed"}], [[res[2]], [res[0]]]),
          [res[0], {"id": "2", "expect": "record", "ok": None}, res[2]])
    m = matrix(["spec"])
    check("matrix: one job per case of the step, each with its step's time and the job's",
          ([x["case"] for x in m] == [c["id"] for c in load_cases("spec")], {x["minutes"] for x in m}, [x["n"] for x in m] == list(range(len(m)))),
          (True, {STEPS["spec"]["minutes"] + JOB_MINUTES}, True))
    check("table: says what failed", "**failed**" in table("repro", res, now, {}) and "could not replay" in table("repro", res, now, {}), True)
    check("run: a step with no replay yet leaves every case unreplayed", [[r["ok"] for r in run(s, [{"id": "x", "expect": "resolved"}], "/nonexistent")] for s in ("repro", "reply")], [[None], [None]])
    check("steps: a step with no set is listed by its paths, never run", (steps_of([".github/workflows/issue-repro.yml"]), steps_of([".github/workflows/issue-repro.yml"], with_set=True)), (["repro"], []))

    # Validating a case (#840): on its fix, on an assertion at its base, none
    # of the fix's literals asserted.
    long_ = "a sentence of the fix, long enough to count"
    diff = f'+++ b/s.py\n+M = "{long_}"\n+++ b/tests/t.py\n+assert "a literal only the test adds, long enough" in x\n'
    check("validate: the fix's added lines, its tests left out", (long_ in added_lines(diff, {"tests/t.py"}), "only the test" in added_lines(diff, {"tests/t.py"})), (True, False))
    check("validate: the literals a Python test asserts, not those it opens",
          asserted_literals("t.py", f'open("{long_}")\nassert x == "{"y" * 30}"\n'), {"y" * 30})
    ac = {"id": "a", "tests": ["t.py"]}
    fa = lambda b, m="passed", text="assert f() == 0\n": {"base": {"t.py": b}, "merge": {"t.py": m}, "added": added_lines(diff, {"tests/t.py"}), "tests_text": {"t.py": text}}
    check("validate: an autopilot case's checks", [[p.split(":")[0] for p in check_case("autopilot", ac, f)] for f in (
          fa("reproduced"), fa("broken"), fa("passed"), fa("reproduced", "reproduced"), fa("reproduced", text=f'assert "{long_}" in out\n'))],
          [[], ["base"], ["base"], ["merge"], ["literal"]])
    check("validate: a case is rewritten to its valid tests, or left out", (rewritten("autopilot", ac, fa("reproduced")), rewritten("autopilot", ac, fa("broken"))), (ac, None))
    sc = {"type": "Bug", "files": ["header.php", "assets/dark.css"], "body": spec}
    check("validate: a spec case passes on its own Spec, and fails on its PRD alone", (check_case("spec", sc, {"added": ""}), [p.split(":")[0] for p in check_case("spec", {**sc, "files": ["x.php"]}, {"added": ""})]),
          ([], ["merge"]))

    # Collecting from git: the reproduced bugs, the accepted issues.
    commits = [{"sha": "m1", "parent": "p1", "subject": "fix: the bug reproduced from #41 (#42)", "body": "Closes #43.", "files": ["scripts/a.py", "tests/repro/test_issue_41.py"]},
               {"sha": "m2", "parent": "p2", "subject": "feat(x)!: b (#45)", "body": "Closes #44.", "files": ["scripts/b.py", "tests/workflows/test_b.py", "CHANGELOG.md"]},
               {"sha": "m3", "parent": "p3", "subject": "fix: c (#46)", "body": "Closes #47.", "files": [f"s/{i}" for i in range(MAX_FILES)] + ["tests/workflows/test_c.py"]},
               {"sha": "m4", "parent": "", "subject": "fix: d (#48)", "body": "Closes #49.", "files": ["s/d", "tests/workflows/test_d.py"]}]
    check("collect: a reproduced bug's test, at the commit before its fix", [(c["issue"], c["base"], c["test"]) for c in cases_from_commits("repro", "o/r", commits, 6)],
          [(41, "p1", "tests/repro/test_issue_41.py")])
    check("collect: an accepted issue's change, not too big, with its parent", [(c["issue"], c["type"], c["files"]) for c in cases_from_commits("spec", "o/r", commits, 6)],
          [(44, "Feature", ["scripts/b.py"])])
    check("collect: N at most", len(cases_from_commits("autopilot", "o/r", commits * 3, 2)), 2)
    check("claude_args: the workflow's arguments, its expressions filled", ("--allowedTools" in claude_args("issue-repro.yml", "write", "claude_way",
          {"steps.policy.outputs.model": "m", "steps.policy.outputs.effort": "e", "steps.way.outputs.dir": "tests/repro"}),
          "Write(tests/repro/**),Edit(tests/repro/**)" in " ".join(claude_args("issue-repro.yml", "write", "claude_way", {"steps.policy.outputs.model": "m", "steps.policy.outputs.effort": "e", "steps.way.outputs.dir": "tests/repro"}))),
          (True, True))
    try:
        claude_args("issue-repro.yml", "write", "claude_way", {})
        unknown = "no error"
    except KeyError:
        unknown = "KeyError"
    check("claude_args: an expression it does not know fails the case, never a guess", unknown, "KeyError")
    check("checkout: the replay's .dx-central holds no test and no set", [p for p in CENTRAL_PARTS if p.startswith(("tests", "evals", "."))], [])
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root, dest, bin_dir = os.path.join(d, "root"), os.path.join(d, "tree", ".dx-central"), os.path.join(d, "bin")
        os.makedirs(os.path.join(root, "scripts", "__pycache__"))
        os.makedirs(bin_dir)
        open(os.path.join(root, "scripts", "a.py"), "w").write("A = 1\n")
        open(os.path.join(root, "org.yml"), "w").write("org: x\n")
        copy_central(dest, root)
        links = [os.path.join(dp, f) for dp, ds, fs in os.walk(dest) for f in fs + ds if os.path.islink(os.path.join(dp, f))]
        open(os.path.join(dest, "scripts", "a.py"), "w").write("A = 2\n")
        check("checkout: .dx-central is a copy, not links; what the agent writes there stays in its tree",
              (links, open(os.path.join(root, "scripts", "a.py")).read(), os.path.isfile(os.path.join(dest, "org.yml")), os.path.exists(os.path.join(dest, "scripts", "__pycache__"))),
              ([], "A = 1\n", True, False))
        fake = os.path.join(bin_dir, "claude")
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = bin_dir + os.pathsep + old_path
        try:
            def answer(text):
                open(fake, "w").write("#!/bin/sh\n" + text)
                os.chmod(fake, 0o755)
                try:
                    return ask("p", [], d, "spec", root)
                except SystemExit as e:
                    return "stopped" if "changed" in str(e) else str(e)
            check("ask: the CLI's answer; its error (a bad token, a limit) or no JSON is could-not-replay", (
                answer("echo '{\"result\": \"ok\"}'\n"), answer("echo '{\"is_error\": true, \"result\": \"401\"}'\n"), answer("echo oops\n")),
                ({"result": "ok"}, None, None))
            check("ask: an agent that writes to the runner's checkout stops the run",
                  answer(f"echo 'A = 3' > {root}/scripts/a.py; echo '{{}}'\n"), "stopped")
        finally:
            os.environ["PATH"] = old_path
    preload()
    check("preload: the grades' helpers are loaded once, before any agent", (set(_LOADED) >= set(HELPERS), _load("issue_schema", "issue-schema.py") is _LOADED["issue_schema"]), (True, True))
    spec_args, work_args = autopilot_args("spec", "3"), autopilot_args("work", "20")

    def flag(args, name):
        return args[args.index(name) + 1] if name in args else None
    check("claude_args: the autopilot's budgets are known",
          (flag(spec_args, "--max-budget-usd"), flag(work_args, "--max-budget-usd"), (flag(spec_args, "--model") or "").startswith("claude-"),
           (flag(work_args, "--model") or "").startswith("claude-"), "--max-turns" in work_args),
          ("3", "20", True, True, True))
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def review_args(argv):
    """review-eval.py's arguments for a review command of evals.py, or None
    (not the review's, or a command review-eval.py has no counterpart of)."""
    if len(argv) < 2 or argv[1] not in ELSEWHERE or argv[0] not in ("collect", "run", "score", "baseline"):
        return None
    return [argv[0], *argv[2:]]


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if len(argv) >= 2 and argv[1] in ELSEWHERE and argv[0] in ("collect", "run", "matrix", "merge", "score", "baseline"):
        args = review_args(argv)
        if args is None:
            print(f"evals.py: {argv[1]} is run by {ELSEWHERE[argv[1]][0]}, one job per play; it has no `{argv[0]}` here", file=sys.stderr)
            return 1
        return subprocess.run([sys.executable, os.path.join(HERE, ELSEWHERE[argv[1]][1]), *args]).returncode
    if argv[:1] == ["steps"]:
        files = argv[1:] or [line.strip() for line in sys.stdin if line.strip()]
        if not files:
            # pr-files.py prints nothing when it could not list the files,
            # and evals.yml only starts when one matched its `paths:`: no
            # file is "could not tell", never "no step touched".
            print("::error::evals.py steps: no changed files, could not tell which steps to evaluate", file=sys.stderr)
            return 1
        print("\n".join(steps_here(files)))
        return 0
    if argv[:1] == ["collect"] and len(argv) in (2, 3) and argv[1] in STEPS:
        cases = collect(argv[1], int(argv[2]) if len(argv) == 3 else 6)
        path = os.path.join(EVALS, argv[1], "cases.json")
        write_json(path, cases)
        print(f"{len(cases)} cases in {path}")
        return 0
    if argv[:1] == ["run"] and len(argv) in (2, 3) and argv[1] in STEPS:
        import tempfile
        cases = load_cases(argv[1])
        if len(argv) == 3:
            cases = [c for c in cases if c["id"] == argv[2]]
            if not cases:
                print(f"evals.py: {argv[1]} has no case {argv[2]}", file=sys.stderr)
                return 1
        print(json.dumps(run(argv[1], cases, tempfile.mkdtemp(prefix="dx-eval-")), indent=2))
        return 0
    if argv[:1] == ["validate"] and all(s in STEPS for s in argv[1:]):
        import tempfile
        bad = []
        # A step whose cases the rule does not cover yet (#735's follow-up)
        # is said, never validated by another's rule.
        for step in argv[1:]:
            if step not in VALIDATED:
                print(f"{step}: its cases are not validated yet (evals.py VALIDATED).")
        for step in [s for s in argv[1:] if s in VALIDATED] if len(argv) > 1 else VALIDATED:
            bad += validate(step, load_cases(step), tempfile.mkdtemp(prefix="dx-validate-"))
        for case_id, why in bad:
            print(f"{case_id}: {why}")
            print(f"::error::{case_id} is not a valid case: {why}", file=sys.stderr)
        if not bad:
            print("Every case is valid: it passes on its merged fix, fails on an assertion at its base, and asserts none of the fix's own literals.")
        return 1 if bad else 0
    if argv[:1] == ["matrix"]:
        steps = argv[1:] or [line.strip() for line in sys.stdin if line.strip()]
        if any(s not in STEPS or s in ELSEWHERE or not has_set(s) for s in steps):
            print(f"evals.py: not a step with a set: {steps}", file=sys.stderr)
            return 1
        print(json.dumps(matrix(steps)))
        return 0
    if argv[:1] == ["merge"] and len(argv) >= 2 and argv[1] in STEPS:
        parts = []
        for f in argv[2:]:
            with open(f, encoding="utf-8") as fh:
                parts.append(json.load(fh))
        print(json.dumps(merge(load_cases(argv[1]), parts), indent=2))
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
            if step in VALIDATED:
                # #840: only from a run of the whole set, every case valid
                # and replayed.
                import tempfile
                cases = load_cases(step)
                left = sorted({c["id"] for c in cases} - {r["id"] for r in results})
                if left:
                    print(f"evals.py: the run left out {', '.join(left)}; a baseline is written only from a run of every case of the set", file=sys.stderr)
                    return 1
                bad = validate(step, cases, tempfile.mkdtemp(prefix="dx-validate-"))
                if bad:
                    print("evals.py: a baseline is written only from a set whose every case is valid; not valid: "
                          + "; ".join(f"{i} ({why})" for i, why in bad), file=sys.stderr)
                    return 1
            write_json(baseline, now)
            print(json.dumps(now))
            return 0
        base, broken = read_baseline(step, baseline, now)
        missing = unreplayed(step, results)
        if missing:
            # The runner's failure, not the step's: no score is read from it.
            print(table(step, results, now, base or {}))
            print(f"\n**The runner did not replay** {len(missing)} of {len(results)} cases of {step}, so it is not scored: "
                  + ", ".join(f"`{m}`" for m in missing) + ".")
            return 1
        if broken:
            # Could not tell: a gate that cannot read its baseline fails.
            print(table(step, results, now, {}))
            print(f"\n**The baseline could not be read:** {broken}. The check fails; it never passes quietly.")
            print(f"::error::{broken}", file=sys.stderr)
            return 1
        if base is None:
            # No baseline yet: no gate, said aloud, and this run proposes one.
            print(table(step, results, now, {}))
            print(f"\n**No baseline** for {step} at evals/{step}/baseline.json: this run passes with a warning. "
                  f"Its whole results follow; saved as FILE, `evals.py baseline {step} FILE` writes the baseline.\n")
            print("```")
            print(f"--- baseline {step} ---")
            print(json.dumps(results, indent=2))
            print("--- end ---")
            print("```")
            print(f"::warning::No baseline for {step}: the run passes, and proposes its results as the baseline (between '--- baseline {step} ---' and '--- end ---').", file=sys.stderr)
            return 0
        print(table(step, results, now, base))
        why = worse(step, now, base)
        if why:
            print(f"\n**Worse than the baseline:** {why}.")
        return 1 if why else 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
