#!/usr/bin/env python3
"""The review's evaluation set: a change to the review is scored first (#234).

The cases are real pull requests of the organisation's public repositories
(a private one's code would show in this public repository's logs):

  flag   the commit where the review raised a blocker or major that was
         then fixed: its thread's `line` of `path` and its `hunk` (at
         most NEAR (10) lines on each side of the line), a line of
         which `fix`, the first later commit of the pull request to
         change one, changed (`fixed`, the lines it changed there). A
         thread that is only outdated or resolved, its hunk never changed,
         is no case (#844), nor one whose fix is a docs, ci, chore, style
         or test commit, or docs alone (#847). The review must raise a
         blocker or major in the file again, inside `hunk` or within NEAR
         lines of `fixed` (#930): a farther line is a miss.
  clean  the last commit of a merged pull request on which the review left
         no thread at all. The review must not block it.

Each case is reviewed again, with the rules as they stand in the checkout,
the way production reviews a pull request (#930): the brief for its pull
request in full mode (scripts/review-brief.sh, with the per-file diffs, the
policy's floor, model and effort, and the criteria of the issue it closes,
GH_TOKEN, read), then claude-review.yml's own review step (its `prompt`
and `claude_args`, read from the workflow at run time, so the two cannot
drift; an expression in them the evaluation does not fill in fails the run
by its name), then its verify step (scripts/review-verify.py), and the
verified output is scored. Only earlier threads and a previous verdict are
left out (they would hand the answer over), and nothing is posted. PLAYS
(3) times, each on a fresh checkout, and
scored on its median: found, or blocked, when 2 of 3 plays say so (a play
that could not be reviewed is dropped; fewer than 2 reviewed is
unreviewed). The set holds at least MIN_CASES (10) cases of each kind, or
it is neither run nor scored (#844). The score is the share of `flag` cases
found and of `clean` cases blocked; review-eval.yml fails a change to the
review whose score is worse than evals/review/baseline.json by more than
one case on either side, or that finds fewer flag cases than the floor,
whatever the baseline (#930): `review-eval.found-floor` of
policy/review-policy.default.yml, a share of them rounded up and never
fewer than one, so a review that finds none always fails. No baseline is
written below the floor.

  review-eval.py collect [N]   write evals/review/cases.json: N cases of each
                               kind (default 10), from the review's threads
                               (GH_TOKEN, read)
  review-eval.py check [FILE]  validate the set (default cases.json): exit 1
                               naming each flag case whose line its fix did
                               not change (git, the public repositories)
  review-eval.py run [--play N]
                               check the set, then review every case, all
                               the plays or play N alone; results on stdout
                               (JSON) (the Claude Code CLI, git, the checkout,
                               GH_TOKEN to read the criteria)
  review-eval.py score FILE... the results in the FILEs (one per play, or a
                               whole run) against the baseline: a table on
                               stdout, exit 1 when worse
  review-eval.py baseline FILE...
                               write the results as the baseline (a whole
                               run of every play alone)
  review-eval.py --test        self-test
"""
import importlib.util
import json
import math
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
import org  # noqa: E402  the organisation, from org.yml (#191)

CASES = os.path.join(ROOT, "evals", "review", "cases.json")
BASELINE = os.path.join(ROOT, "evals", "review", "baseline.json")
POLICY = os.path.join(ROOT, "policy", "review-policy.default.yml")
POLICY_NAME = "policy/review-policy.default.yml"
SLACK = 1
# A set of at least MIN_CASES of each kind, each case reviewed PLAYS times
# and scored on its median (C3, #844): one odd answer moves no case.
MIN_CASES = 10
PLAYS = 3

QUERY = """
query($q: String!) {
  search(query: $q, type: ISSUE, first: 50) {
    nodes { ... on PullRequest {
      number title baseRefOid headRefOid isCrossRepository
      commits(first: 100) { nodes { commit { oid } } }
      reviewThreads(first: 50) { nodes {
        isResolved isOutdated path originalLine diffSide resolvedBy { login }
        comments(first: 1) { nodes { author { login } body diffHunk originalCommit { oid } } }
      } }
    } }
  }
}
"""


def is_review(t):
    c = ((t.get("comments") or {}).get("nodes") or [{}])[0] or {}
    return (c.get("author") or {}).get("login") == org.APP and "AI review" in (c.get("body") or "")


def line_changed(diff, line):
    """Whether `git diff -U0` text changes the old file's line: it falls in
    a `-a,b` hunk with b >= 1 (a hunk of additions alone changes none)."""
    for m in re.finditer(r"^@@ -(\d+)(?:,(\d+))? \+", diff or "", re.M):
        start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
        if count >= 1 and start <= line < start + count:
            return True
    return False


def first_fix(commits, line, diff_of):
    """The first of commits (those after the case's head, in order) whose
    diff from head, diff_of(commit), changes line; None when none does."""
    for c in commits:
        if line_changed(diff_of(c), line):
            return c
    return None


def thread_hunk(diff_hunk):
    """The head-side lines (first, last) of a review thread's hunk, from
    its `@@ -a,b +c,d @@` header; None when it has none."""
    m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff_hunk or "")
    if not m:
        return None
    start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
    return (start, start + count - 1) if count >= 1 else None


# A thread's hunk is the diff's around its line, which for a new or rewritten
# file is the whole file; only NEAR lines on each side of the line count,
# so a later edit elsewhere in the file is no fix of the thread.
NEAR = 10


def near(hunk, line):
    """hunk (first, last) cut to NEAR lines on each side of line."""
    return (max(hunk[0], line - NEAR), min(hunk[1], line + NEAR))


def fix_hunks(diff, hunk):
    """The head-side lines [first, last] of each `git diff -U0` hunk that
    changes a line of hunk (first, last): what the fix changed there. An
    addition alone (`-a,0`) is at line a, the one it follows."""
    out = []
    for m in re.finditer(r"^@@ -(\d+)(?:,(\d+))? \+", diff or "", re.M):
        start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
        lo, hi = (start, start + count - 1) if count >= 1 else (max(start, 1), max(start, 1))
        if lo <= hunk[1] and hi >= hunk[0]:
            out.append([lo, hi])
    return out


def first_fix_in(commits, hunk, diff_of):
    """The first of commits (those after the case's head, in order) whose
    diff from head changes a line of the thread's hunk, with what it
    changed there: (commit, fix_hunks); None when none does."""
    for c in commits:
        got = fix_hunks(diff_of(c), hunk)
        if got:
            return c, got
    return None


# A commit of these types fixes no bug a review should find, nor does one
# that changes docs alone (the maintainer, #847).
NOT_FIX = ("docs", "ci", "chore", "style", "test")
DOC_EXT = (".md", ".mdx", ".rst", ".adoc")
DOC_NAMES = ("readme", "changelog", "license", "contributing")
# A file of DOC_NAMES is docs with no extension or a text one, never as code
# (license.php is code).
NAME_EXT = ("", ".txt") + DOC_EXT


def is_doc(path):
    base = os.path.basename(path).lower()
    stem, ext = os.path.splitext(base)
    return path.split("/")[0] == "docs" or base.endswith(DOC_EXT) or (stem in DOC_NAMES and ext in NAME_EXT)


def not_a_fix(subject, files):
    """Whether a commit is no bug's fix: its Conventional Commit type is one
    of NOT_FIX, or every file it changes is docs. A subject or file list
    that could not be read (None) is no proof of a fix: it is not one."""
    if subject is None or files is None:
        return True
    m = re.match(r"(\w+)(?:\([^)]*\))?!?:", subject or "")
    return bool(m and m.group(1).lower() in NOT_FIX) or bool(files and all(is_doc(f) for f in files))


def git_url(repo):
    # DX_EVAL_GIT stands in for GitHub in the tests: a directory of o/r.
    return f"{os.environ.get('DX_EVAL_GIT', 'https://github.com')}/{repo}"


class Clones:
    """One clone per repository, to read the cases' commits."""

    def __init__(self, work):
        self.work, self.dirs = work, {}

    def git(self, repo, *args):
        d = self.dirs.get(repo)
        if d is None:
            d = os.path.join(self.work, repo.replace("/", "_"))
            if subprocess.run(["git", "clone", "-q", "--no-checkout", git_url(repo), d], capture_output=True).returncode != 0:
                d = ""
            self.dirs[repo] = d
        if not d:
            return None
        return subprocess.run(["git", "-C", d, *args], capture_output=True, text=True)

    def has(self, repo, pr, *oids):
        """Whether every oid is a commit of the clone, fetched when not."""
        def ok():
            return all((self.git(repo, "cat-file", "-e", o + "^{commit}") or subprocess.CompletedProcess([], 1)).returncode == 0 for o in oids)
        if ok():
            return True
        # The pull request's ref first (its commits after a squash merge),
        # then the commits themselves.
        if pr is not None:
            self.git(repo, "fetch", "-q", "origin", f"refs/pull/{pr}/head")
        if not ok():
            self.git(repo, "fetch", "-q", "origin", *oids)
        return ok()

    def subject(self, repo, oid):
        """oid's subject; None when it cannot be read."""
        out = self.git(repo, "log", "-1", "--format=%s", oid)
        return out.stdout.strip() if out is not None and out.returncode == 0 else None

    def files(self, repo, oid):
        """The files oid changes from its first parent (all, for a root);
        None when they cannot be read."""
        out = self.git(repo, "diff", "--name-only", oid + "^", oid)
        if out is None or out.returncode != 0:
            out = self.git(repo, "diff-tree", "--root", "-r", "--no-commit-id", "--name-only", oid)
        return out.stdout.split() if out is not None and out.returncode == 0 else None

    def diff(self, repo, a, b, path):
        out = self.git(repo, "diff", "-U0", a, b, "--", path)
        return out.stdout if out is not None and out.returncode == 0 else ""


def refused(cases, clones):
    """Why each flag case is refused, by its name: no line or fix, the fix
    did not change its thread's hunk (its line, for a case with no hunk) or
    not the lines the case says (C1, #844), or it is no bug's fix (#847)."""
    why = []
    for c in cases:
        if c.get("expect") != "flag":
            continue
        line, fix = c.get("line"), c.get("fix")
        if not isinstance(line, int) or isinstance(line, bool) or not fix or not c.get("path"):
            why.append(f"{c.get('id')}: no line, path or fix")
        elif not clones.has(c["repo"], c.get("pr"), c["head"], fix):
            why.append(f"{c['id']}: {c['head']} or {fix} cannot be read from {c['repo']}")
        else:
            hunk = near(c.get("hunk") or [line, line], line)
            got = fix_hunks(clones.diff(c["repo"], c["head"], fix, c["path"]), hunk) if hunk[0] <= line <= hunk[1] else []
            if not got:
                where = f"the hunk {hunk[0]}-{hunk[1]}" if c.get("hunk") else f"line {line}"
                why.append(f"{c['id']}: {where} of {c['path']} was not changed by {fix}")
            elif c.get("fixed") is not None and c["fixed"] != got:
                why.append(f"{c['id']}: its fixed lines {c['fixed']} are not those {fix} changed in the hunk, {got}")
            elif None in (subject := clones.subject(c["repo"], fix), files := clones.files(c["repo"], fix)):
                why.append(f"{c['id']}: the subject or files of {fix} cannot be read from {c['repo']}")
            elif not_a_fix(subject, files):
                why.append(f"{c['id']}: {fix} is not a bug's fix (a {', '.join(NOT_FIX)} commit, or docs alone)")
    return why


def cases_from(repo, prs, n, fix_of=None):
    """Up to n `flag` and n `clean` cases from one repository's pull requests.
    fix_of(pr, head, path, hunk, commits) is (the commit after head that
    changed a line of the thread's hunk, the lines it changed there), or
    None: a thread whose hunk no commit changed is not a flag case, nor one
    whose fix is no bug's fix (#844, #847). The case's line is the thread's
    own, on the head it reviewed."""
    flag, clean = [], []
    for pr in prs:
        # Only a branch of the repository itself: a fork's code never runs
        # where the review's key is (#234).
        if pr.get("isCrossRepository") is not False:
            continue
        threads = [t for t in ((pr.get("reviewThreads") or {}).get("nodes") or [])]
        fixed = [t for t in threads if is_review(t) and (((t.get("resolvedBy") or {}).get("login") == org.APP) or t.get("isOutdated"))]
        if fixed:
            commits = [((x or {}).get("commit") or {}).get("oid") for x in ((pr.get("commits") or {}).get("nodes") or [])]
            for t in fixed:
                first = ((t.get("comments") or {}).get("nodes") or [{}])[0] or {}
                head = (first.get("originalCommit") or {}).get("oid")
                line, hunk = t.get("originalLine"), thread_hunk(first.get("diffHunk"))
                # A thread on the base's side (LEFT) is no line of the head.
                if (not head or not isinstance(line, int) or head not in commits or len(flag) >= n
                        or t.get("diffSide") == "LEFT" or not hunk or not hunk[0] <= line <= hunk[1]):
                    continue
                after = [c for c in commits[commits.index(head) + 1:] if c]
                hunk = near(hunk, line)
                got = fix_of(pr, head, t.get("path"), hunk, after) if fix_of else None
                if got:
                    flag.append({"id": f"{repo}#{pr['number']}:flag", "repo": repo, "pr": pr["number"], "title": pr.get("title") or "",
                                 "base": pr.get("baseRefOid"), "head": head, "expect": "flag", "path": t.get("path"), "line": line,
                                 "hunk": list(hunk), "fix": got[0], "fixed": got[1]})
                    break
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


def collect(n):
    per_repo = {}
    clones = Clones(tempfile.mkdtemp(prefix="dx-collect-"))
    for name in public_repos():
        full = f"{org.ORG}/{name}"
        out = gh("api", "graphql", "-f", f"query={QUERY}", "-f", f"q=repo:{full} is:pr is:merged commenter:app/{org.APP}")
        prs = json.loads(out)["data"]["search"]["nodes"]

        def fix_of(pr, head, path, hunk, after, full=full):
            if not clones.has(full, pr["number"], head, *after):
                return None
            got = first_fix_in(after, hunk, lambda c: clones.diff(full, head, c, path))
            if not got or not_a_fix(clones.subject(full, got[0]), clones.files(full, got[0])):
                return None
            return got
        per_repo[full] = cases_from(full, prs, n, fix_of)
    return pick(per_repo, n)


def check(cases):
    """The set's validation: 0, or 1 with each refused case on stderr."""
    why = refused(cases, Clones(tempfile.mkdtemp(prefix="dx-check-")))
    for w in why:
        print(f"review-eval.py: {w}", file=sys.stderr)
    return 1 if why else 0


def as_line(v):
    """A finding's line as an int, or None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    return int(v) if isinstance(v, str) and v.strip().isdigit() else None


def verdict(case, review):
    """Whether the review did what the case expects. review is
    the verified review output, or None when it gave none."""
    if not isinstance(review, dict):
        return None
    serious = [f for f in review.get("findings") or [] if isinstance(f, dict)
               and f.get("severity") in ("blocker", "major") and not f.get("pre_existing")]
    if case["expect"] == "flag":
        # In the case's file, inside the hunk the fix changed or within NEAR
        # lines of the lines it changed (#930: #811 was missed 9 lines
        # away); another file, a finding with no line or a farther one is a
        # miss (C2, #844, #847). A case with no `fixed` has its line alone.
        if as_line(case.get("line")) is None:
            return False
        return any(f.get("file") == case["path"] and near_fix(case, as_line(f.get("line"))) for f in serious)
    return not serious


def fixed_lines(case):
    """The case's fixed line ranges, or its line alone when it has none."""
    line = as_line(case.get("line"))
    return case.get("fixed") or ([[line, line]] if line is not None else [])


def away(case, n):
    """How many lines n is from the case's fixed lines (0 inside them)."""
    return min(max(lo - n, n - hi, 0) for lo, hi in fixed_lines(case))


def near_fix(case, n):
    """Whether line n counts for the case: inside the fix's hunk, or within
    NEAR lines of its fixed lines (#930)."""
    if n is None or not fixed_lines(case):
        return False
    hunk = case.get("hunk")
    if isinstance(hunk, (list, tuple)) and len(hunk) == 2 and hunk[0] <= n <= hunk[1]:
        return True
    return away(case, n) <= NEAR


def reason(case, review):
    """Why the review found a flag case or not, from its verified output
    (#930 C3): found; a blocker or major in the case's file outside the
    fixed lines, with how far; one there the verifier rejected; no finding
    in the file; not reviewed. '' for a clean case."""
    if case.get("expect") != "flag":
        return ""
    if not isinstance(review, dict):
        return "not reviewed"
    if verdict(case, review):
        return "found"
    fixed = fixed_lines(case)
    mine = [f for f in review.get("findings") or [] if isinstance(f, dict) and f.get("file") == case.get("path") and not f.get("pre_existing")]
    if any(f.get("rejected") and near_fix(case, as_line(f.get("line"))) for f in mine):
        return "rejected by verification"
    kept = [as_line(f.get("line")) for f in mine if f.get("severity") in ("blocker", "major")]
    far = [away(case, n) for n in kept if n is not None and fixed]
    if far:
        d = min(far)
        return f"outside the fixed lines, {d} line{'' if d == 1 else 's'} away"
    if kept:
        return "outside the fixed lines, with no line"
    if any(f.get("rejected") for f in mine):
        return "rejected by verification"
    return "no finding in the file"


# Each play's reason, by case id, as run_case leaves it (#930 C3).
WHY = {}


def review_workflow():
    # DX_EVAL_REVIEW_WORKFLOW stands in for claude-review.yml in the tests.
    return os.environ.get("DX_EVAL_REVIEW_WORKFLOW") or os.path.join(ROOT, ".github", "workflows", "claude-review.yml")


def review_steps(path=None):
    """The review's and the verifier's `prompt` and `claude_args`, read from
    claude-review.yml's steps of id `claude` and `verify` (#930 C1): the
    evaluation plays what production runs, and cannot drift from it."""
    import yaml
    with open(path or review_workflow(), encoding="utf-8") as fh:
        wf = yaml.safe_load(fh) or {}
    found = {}
    for job in (wf.get("jobs") or {}).values():
        for s in (job or {}).get("steps") or []:
            if isinstance(s, dict) and s.get("id") in ("claude", "verify"):
                w = s.get("with") or {}
                found["review" if s["id"] == "claude" else "verify"] = {"prompt": str(w.get("prompt") or ""), "args": str(w.get("claude_args") or "")}
    missing = [k for k in ("review", "verify") if not found.get(k, {}).get("prompt") or not found[k]["args"]]
    if missing:
        raise ValueError(f"{path or review_workflow()} has no {' or '.join(missing)} step with a prompt and claude_args")
    return found


# The expressions of the review's and the verifier's steps the evaluation
# fills in; any other fails the run by its name (#930 C1).
KNOWN = ("github.repository", "github.event.pull_request.number", "steps.scope.outputs.model",
         "steps.scope.outputs.effort", "steps.policy.outputs.budget || '3'", "steps.verify-task.outputs.prompt")


def fill(text, values):
    """text with each `${{ expr }}` replaced by values[expr]; ValueError
    naming the first expression values does not know."""
    def one(m):
        expr = m.group(1).strip()
        if expr not in values:
            raise ValueError(f"the review's workflow uses ${{{{ {expr} }}}}, which the evaluation does not fill in")
        return str(values[expr])
    return re.sub(r"\$\{\{(.*?)\}\}", one, text, flags=re.S)


def check_steps(steps):
    """'' when every expression of steps is one the evaluation fills, else why."""
    dummy = {k: "x" for k in KNOWN}
    try:
        for s in steps.values():
            fill(s["prompt"], dummy)
            fill(s["args"], dummy)
    except ValueError as e:
        return str(e)
    return ""


def claude_bin():
    # DX_EVAL_CLAUDE stands in for the Claude Code CLI in the tests.
    return os.environ.get("DX_EVAL_CLAUDE") or "claude"


# One case never holds the run: its review and verification have CASE_SECONDS
# (15 minutes) between them, so a play of 20 cases fits the job's 350.
CASE_SECONDS = 900


def ask(prompt, args, cwd, timeout):
    """One `claude -p` with production's args; its structured output, or None."""
    if timeout <= 0:
        return None
    try:
        # The model gets its key, never the GitHub token the play reads the
        # criteria with.
        env = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN")}
        out = subprocess.run([claude_bin(), "-p", prompt, *shlex.split(args), "--output-format", "json"], cwd=cwd, env=env,
                             stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        got = json.loads(out.stdout or "null")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    got = got.get("structured_output") if isinstance(got, dict) else None
    if isinstance(got, str):
        try:
            got = json.loads(got)
        except ValueError:
            return None
    return got if isinstance(got, dict) else None


def pr_text(repo, pr):
    """The pull request's description and the acceptance criteria of the one
    issue it closes, as claude-review.yml's brief step reads them (GH_TOKEN,
    read); no criteria when it closes no single issue. RuntimeError when
    they cannot be read: never a review on a brief that lost them."""
    if not os.environ.get("GH_TOKEN"):
        raise RuntimeError(f"{repo}#{pr}: no GH_TOKEN to read its description and criteria")
    try:
        got = json.loads(gh("pr", "view", str(pr), "--repo", repo, "--json", "body,closingIssuesReferences"))
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        raise RuntimeError(f"{repo}#{pr}: cannot read the pull request: {e}")
    body = got.get("body") or ""
    closes = [i.get("number") for i in got.get("closingIssuesReferences") or []]
    if len(closes) != 1:
        return body, ""
    try:
        issue = gh("issue", "view", str(closes[0]), "--repo", repo, "--json", "body", "--jq", ".body")
        crit = subprocess.run(["python3", os.path.join(HERE, "issue-schema.py"), "criteria"], input=issue, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as e:
        raise RuntimeError(f"{repo}#{pr}: cannot read issue #{closes[0]}: {e}")
    if crit.returncode != 0:
        raise RuntimeError(f"{repo}#{pr}: cannot read the criteria of issue #{closes[0]}: {crit.stderr.strip()}")
    return body, crit.stdout


def policy_of(case, repo_dir, work):
    """policy.py's outputs for the case, as claude-review.yml's policy step
    computes them: the repository's policy from the base, the files the
    pull request changes; None when policy.py fails."""
    git = lambda *a: subprocess.run(["git", "-C", repo_dir, *a], capture_output=True, text=True)
    repo_policy = os.path.join(work, "repo-policy.yml")
    shown = git("show", f"{case['base']}:.github/review-policy.yml")
    with open(repo_policy, "w", encoding="utf-8") as fh:
        fh.write(shown.stdout if shown.returncode == 0 else "")
    names = git("diff", "--name-status", "-M", f"{case['base']}...{case['head']}").stdout
    changed = "\n".join(p for line in names.splitlines() for p in line.split("\t")[1:])
    out = os.path.join(work, "policy.out")
    open(out, "w").close()
    env = {**os.environ, "DEFAULT_POLICY": os.path.join(ROOT, "policy", "review-policy.default.yml"), "REPO_POLICY": repo_policy,
           "CHANGED_FILES": changed, "GITHUB_OUTPUT": out, "GITHUB_REPOSITORY": case["repo"], "PR": str(case["pr"])}
    # A policy that cannot be computed reviews nothing, as production's
    # policy step fails its job: never a review on a guessed floor.
    if subprocess.run(["python3", os.path.join(HERE, "policy.py")], cwd=repo_dir, env=env, capture_output=True, text=True).returncode != 0:
        return None
    got = {}
    with open(out, encoding="utf-8") as fh:
        for line in fh:
            k, _, v = line.rstrip("\n").partition("=")
            got[k] = v
    return got


def play_review(case, repo_dir, work, steps):
    """Production's review of the case's checkout: the brief for its pull
    request in full mode (scripts/review-brief.sh, as the brief step builds
    it), the review step's prompt and args, then the verify step's
    (scripts/review-verify.py prompt and apply). The verified output, or
    None when the review gave none. No earlier threads or verdict (they
    would hand the answer over), and nothing is posted."""
    deadline = time.monotonic() + CASE_SECONDS
    pol = policy_of(case, repo_dir, work)
    if pol is None:
        return None
    model = pol.get("model") or "claude-sonnet-5-5"
    effort = pol.get("effort") or "medium"
    body, criteria = pr_text(case["repo"], case["pr"])
    crit = os.path.join(work, "criteria.md")
    with open(crit, "w", encoding="utf-8") as fh:
        fh.write(criteria)
    central = os.path.join(repo_dir, ".dx-central")
    os.makedirs(central, exist_ok=True)
    env = {**os.environ, "REPO": case["repo"], "TITLE": case.get("title") or "", "BODY": body, "BASE": case["base"], "HEAD": case["head"],
           "PR": str(case["pr"]), "MODE": "full", "RANGE": "", "LAST": "", "FLOOR": pol.get("floor") or "high", "REASONS": pol.get("reasons") or "",
           "PROFILE": "general", "KIND": pol.get("kind") or "", "CRITERIA": crit, "CENTRAL": ROOT, "WORK": work,
           "OUT": ".dx-central/brief.md", "DIFF_DIR": ".dx-central/diff"}
    for k in ("PREVIOUS_JSON", "OPEN_THREADS", "SETTLED_THREADS"):
        env.pop(k, None)
    if subprocess.run(["bash", os.path.join(HERE, "review-brief.sh")], cwd=repo_dir, env=env, capture_output=True, text=True).returncode != 0:
        return None
    values = {"github.repository": case["repo"], "github.event.pull_request.number": case["pr"], "steps.scope.outputs.model": model,
              "steps.scope.outputs.effort": effort, "steps.policy.outputs.budget || '3'": pol.get("budget") or "3"}
    review = ask(fill(steps["review"]["prompt"], values), fill(steps["review"]["args"], values), repo_dir, deadline - time.monotonic())
    if review is None:
        return None
    verify = subprocess.run(["python3", os.path.join(HERE, "review-verify.py"), "prompt"], input=json.dumps(review), capture_output=True, text=True)
    verdicts = None
    if verify.returncode == 0 and verify.stdout.strip():
        values["steps.verify-task.outputs.prompt"] = verify.stdout
        # Out of time, no answer: it rejects nothing, as in production.
        verdicts = ask(fill(steps["verify"]["prompt"], values), fill(steps["verify"]["args"], values), repo_dir, deadline - time.monotonic())
    return verify_apply(review, verdicts)


def verify_apply(review, verdicts):
    """scripts/review-verify.py's apply: the review with the rejected ones demoted."""
    sys.path.insert(0, HERE)
    spec = importlib.util.spec_from_file_location("review_verify", os.path.join(HERE, "review-verify.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.apply(review, verdicts)


def run_case(case, central, work, steps=None):
    """Review one case as production does; True, False, or None when it
    could not be reviewed."""
    steps = steps or review_steps()
    os.makedirs(work, exist_ok=True)
    repo_dir = os.path.join(work, case["repo"].replace("/", "_"))
    git = lambda *a: subprocess.run(["git", "-C", repo_dir, *a], capture_output=True, text=True)
    if not os.path.isdir(repo_dir):
        if subprocess.run(["git", "clone", "-q", git_url(case["repo"]), repo_dir], capture_output=True).returncode != 0:
            return None
    git("fetch", "-q", "origin", f"refs/pull/{case['pr']}/head", case["base"])
    if git("cat-file", "-e", case["head"] + "^{commit}").returncode != 0:
        git("fetch", "-q", "origin", case["head"])
    # A clean tree for each case: the last case's brief and diffs go.
    git("clean", "-qfdx")
    if git("checkout", "-q", "-f", "-B", f"eval/{case['pr']}", case["head"]).returncode != 0:
        return None
    case_work = tempfile.mkdtemp(prefix="dx-case-", dir=work)
    review = play_review(case, repo_dir, case_work, steps)
    WHY[case["id"]] = reason(case, review)
    return verdict(case, review)


def short(items):
    """Why the set is too small to score, or '': fewer than MIN_CASES flag
    or clean cases (items are cases or results)."""
    why = [f"{sum(1 for c in items if c.get('expect') == k)} {k} cases, fewer than {MIN_CASES}"
           for k in ("flag", "clean") if sum(1 for c in items if c.get("expect") == k) < MIN_CASES]
    return "; ".join(why)


def unplayed(results):
    """The cases not played PLAYS times, by name."""
    return [r.get("id") for r in results if len(r.get("plays") or []) != PLAYS]


def merge(runs):
    """The plays of several runs (one per play, --play N) case by case."""
    out, at = [], {}
    for run in runs:
        for r in run:
            if r["id"] not in at:
                at[r["id"]] = {"id": r["id"], "expect": r["expect"], "plays": [], "why": []}
                out.append(at[r["id"]])
            plays = list(r.get("plays") or [])
            at[r["id"]]["plays"] += plays
            # Each play's reason; a run from before #930 has none.
            why = list(r.get("why") or [])
            at[r["id"]]["why"] += (why + [""] * len(plays))[:len(plays)]
    return out


def median(r):
    """A case's result over its plays: True (as expected), False, or None
    when fewer than 2 plays were reviewed. A flag case is found, and a
    clean one blocked, when 2 plays say so (2 of 3)."""
    played = [p for p in r.get("plays") or [] if p is not None]
    if len(played) < 2:
        return None
    if r["expect"] == "flag":
        return sum(1 for p in played if p) >= 2
    return sum(1 for p in played if not p) < 2


def score(results):
    ok = [(r["expect"], median(r)) for r in results]
    flag = [m for e, m in ok if e == "flag" and m is not None]
    clean = [m for e, m in ok if e == "clean" and m is not None]
    return {"found": sum(1 for m in flag if m), "flag": len(flag),
            "blocked": sum(1 for m in clean if not m), "clean": len(clean),
            "unreviewed": sum(1 for _, m in ok if m is None), "plays": PLAYS}


def found_share(path=None):
    """The policy's `review-eval.found-floor`, the share of the flag cases
    the review must find whatever the baseline (#930 C2). A policy that
    cannot be read, or that holds no share there, raises ValueError: the
    gate fails by name, never on a floor guessed at one case."""
    import yaml
    path = path or POLICY
    try:
        with open(path, encoding="utf-8") as fh:
            pol = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as e:
        raise ValueError(f"review-eval.found-floor: cannot read {path}: {e}")
    got = ((pol.get("review-eval") if isinstance(pol, dict) else None) or {})
    got = got.get("found-floor") if isinstance(got, dict) else None
    if not isinstance(got, (int, float)) or isinstance(got, bool) or not 0 <= got <= 1:
        raise ValueError(f"review-eval.found-floor of {path} is not a share of 0 to 1: {got!r}")
    return got


def found_floor(flag, share):
    """The fewest flag cases of FLAG the review must find: SHARE of them,
    rounded up, never fewer than one, so a review that finds none fails."""
    return max(1, math.ceil(round(share * flag, 9)))


def below_floor(now, share=None):
    """Why the score finds fewer flag cases than the floor, or ''."""
    need = found_floor(now["flag"], found_share() if share is None else share)
    if now["found"] < need:
        return f"it found {now['found']} of {now['flag']} known bugs, below the floor of {need} (review-eval.found-floor, {POLICY_NAME})"
    return ""


def worse(now, base, share=None):
    """Why the score is worse than the baseline by more than SLACK, or below
    the found floor whatever the baseline, or ''."""
    why = [w for w in [below_floor(now, share)] if w]
    if base.get("flag") and now["found"] < base["found"] - SLACK:
        why.append(f"it found {now['found']} of {now['flag']} known bugs, the baseline {base['found']} of {base['flag']}")
    if now["blocked"] > base.get("blocked", 0) + SLACK:
        why.append(f"it blocked {now['blocked']} of {now['clean']} clean pull requests, the baseline {base.get('blocked', 0)}")
    if now["unreviewed"] > SLACK:
        why.append(f"{now['unreviewed']} cases could not be reviewed")
    return "; ".join(why)


def play_reason(r, i):
    """The reason of play i of a result: the one it kept, else what its
    result says."""
    why = (r.get("why") or [])
    if i < len(why) and why[i]:
        return why[i]
    p = (r.get("plays") or [None])[i]
    return "not reviewed" if p is None else ("found" if p else "missed") if r.get("expect") == "flag" else ""


def reasons(r):
    """A flag case's reasons over its plays, each once with how many plays
    gave it: 'found (2), no finding in the file (1)'."""
    if r.get("expect") != "flag":
        return ""
    seen = {}
    for i in range(len(r.get("plays") or [])):
        w = play_reason(r, i)
        seen[w] = seen.get(w, 0) + 1
    return ", ".join(f"{w} ({n})" for w, n in seen.items())


def table(results, now, base):
    out = ["| Case | Expects | Plays | Result | Why |", "| --- | --- | --- | --- | --- |"]
    words = {"flag": ("found", "missed"), "clean": ("clean", "blocked")}
    for r in results:
        yes, no = words.get(r["expect"], ("as expected", "not"))
        plays = ", ".join("not reviewed" if p is None else yes if p else no for p in r.get("plays") or [])
        m = median(r)
        res = "could not review" if m is None else ("as expected" if m else "**missed**" if r["expect"] == "flag" else "**blocked**")
        out.append(f"| {r['id']} | {r['expect']} | {plays} | {res} | {reasons(r)} |")
    out += ["", f"Found {now['found']} of {now['flag']} known bugs (baseline {base.get('found', '?')} of {base.get('flag', '?')}); "
            f"blocked {now['blocked']} of {now['clean']} clean pull requests (baseline {base.get('blocked', '?')}); {now['unreviewed']} not reviewed."]
    return "\n".join(out)


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    bot = {"login": org.APP}
    first = lambda oid: {"nodes": [{"author": bot, "body": "x\n<sub>🤖 AI review · m (Anthropic)</sub>", "diffHunk": "@@ -4,3 +5,4 @@\n", "originalCommit": {"oid": oid}}]}
    commits = lambda *o: {"nodes": [{"commit": {"oid": x}} for x in o]}
    prs = [{"number": 1, "title": "fix: a", "baseRefOid": "b1", "headRefOid": "h1", "isCrossRepository": False, "commits": commits("c0", "c1", "c2", "h1"),
            "reviewThreads": {"nodes": [{"isOutdated": True, "path": "a.php", "originalLine": 7, "resolvedBy": None, "comments": first("c1")}]}},
           {"number": 2, "title": "feat: b", "baseRefOid": "b2", "headRefOid": "h2", "isCrossRepository": False, "reviewThreads": {"nodes": []}},
           {"number": 3, "title": "fix: c", "baseRefOid": "b3", "headRefOid": "h3", "isCrossRepository": False, "reviewThreads": {"nodes": [{"isOutdated": False, "path": "c.php", "resolvedBy": {"login": "me"}, "comments": first("c3")}]}}]
    seen = []
    fix_of = lambda pr, head, path, hunk, after: seen.append((head, path, hunk, after)) or ("c2", [[6, 6]])
    flag, clean = cases_from("o/r", prs, 5, fix_of)
    check("cases: a fixed finding is a flag case at the commit it was raised on, with its line, hunk and fix", [(c["pr"], c["head"], c["path"], c["line"], c["hunk"], c["fix"], c["fixed"]) for c in flag], [(1, "c1", "a.php", 7, [5, 8], "c2", [[6, 6]])])
    check("cases: the fix is looked for in the thread's hunk among the commits after head", seen, [("c1", "a.php", (5, 8), ["c2", "h1"])])
    check("thread_hunk: the head side of the header", (thread_hunk("@@ -1,4 +2,6 @@ x"), thread_hunk("@@ -5 +5 @@"), thread_hunk("@@ -5,1 +5,0 @@"), thread_hunk(None)), ((2, 7), (5, 5), None, None))
    check("fix_hunks: the fix's hunks that touch the thread's; an addition at the line it follows", (fix_hunks("@@ -3,2 +3,1 @@\n@@ -20,0 +20,2 @@\n", (1, 8)), fix_hunks("@@ -20,0 +20,2 @@\n", (18, 25)), fix_hunks("@@ -3 +3 @@\n", (5, 9))), ([[3, 4]], [[20, 20]], []))
    check("first_fix_in: the first commit that changed the hunk", first_fix_in(["x", "y"], (1, 4), {"x": "@@ -9 +9 @@", "y": "@@ -3 +3 @@"}.get), ("y", [[3, 3]]))
    check("not_a_fix: docs, ci, chore, style, test, or docs alone", [not_a_fix(*a) for a in (("docs(readme): x", ["a.php"]), ("ci: x", ["a.php"]), ("fix: x", ["readme.txt", "docs/a.php", "A.md"]), ("fix: x", ["a.php", "A.md"]), ("feat!: x", ["a.php"]))], [True, True, True, False, False])
    check("near: a whole-file hunk is cut to NEAR lines around the line", (near((1, 300), 150), near((5, 8), 7)), ((150 - NEAR, 150 + NEAR), (5, 8)))
    check("is_doc: a doc name as code is code", [is_doc(f) for f in ("LICENSE", "readme.txt", "CHANGELOG.md", "license.php", "contributing.py")], [True, True, True, False, False])
    check("not_a_fix: an unreadable subject or file list is no fix", (not_a_fix(None, ["a.php"]), not_a_fix("fix: x", None)), (True, True))
    check("cases: a thread whose line no commit changed is not a flag case", cases_from("o/r", prs[:1], 5, lambda *a: None), ([], []))
    check("line_changed: inside a -a,b hunk; never an addition alone", [line_changed("@@ -3,2 +3,1 @@\n@@ -9,0 +9,1 @@\n", n) for n in (2, 3, 4, 5, 9)], [False, True, True, False, False])
    check("first_fix: the first commit that changed the line", first_fix(["x", "y"], 3, {"x": "@@ -5 +5 @@", "y": "@@ -3 +3 @@"}.get), "y")
    check("cases: a pull request with no thread is clean at its last commit; a dismissed one is neither", [(c["pr"], c["head"]) for c in clean], [(2, "h2")])
    fork = [{"number": 9, "title": "x", "baseRefOid": "b", "headRefOid": "h", "isCrossRepository": True, "reviewThreads": {"nodes": []}},
            {"number": 8, "title": "y", "baseRefOid": "b", "headRefOid": "h", "reviewThreads": {"nodes": []}}]
    check("cases: never a fork's pull request, nor one that does not say", cases_from("o/r", fork, 5), ([], []))
    picked = pick({"o/a": ([{"id": "a1"}, {"id": "a2"}], []), "o/b": ([{"id": "b1"}], [])}, 2)
    check("pick: round the repositories", [c["id"] for c in picked], ["a1", "b1"])
    case_f = {"expect": "flag", "path": "a.php", "line": 3}
    check("verdict: inside the fix's hunk or within NEAR lines of its fixed lines, never farther", [verdict({"expect": "flag", "path": "a.php", "line": 30, "hunk": [25, 35], "fixed": [[40, 42]]}, {"findings": [{"severity": "major", "file": "a.php", "line": n}]}) for n in (24, 26, 30, 41, 52, 53)], [False, True, True, True, True, False])
    check("verdict: flag found on its line", verdict(case_f, {"findings": [{"severity": "major", "file": "a.php", "line": 3}]}), True)
    check("verdict: a case with no line finds nothing", verdict({"expect": "flag", "path": "a.php"}, {"findings": [{"severity": "major", "file": "a.php"}]}), False)
    check("verdict: a line of the file farther than NEAR, or no line, is missed", (verdict(case_f, {"findings": [{"severity": "major", "file": "a.php", "line": 14}]}), verdict(case_f, {"findings": [{"severity": "major", "file": "a.php"}]})), (False, False))
    check("verdict: flag missed (a minor, another file, a pre-existing one)", verdict(case_f, {"findings": [{"severity": "minor", "file": "a.php"}, {"severity": "major", "file": "b.php"}, {"severity": "blocker", "file": "a.php", "pre_existing": True}]}), False)
    check("verdict: clean kept clean; clean blocked", (verdict({"expect": "clean"}, {"findings": [{"severity": "minor"}]}), verdict({"expect": "clean"}, {"findings": [{"severity": "major"}]})), (True, False))
    check("verdict: no review is unknown", verdict(case_f, None), None)
    res = [{"id": "1", "expect": "flag", "plays": [True, True, False]}, {"id": "2", "expect": "flag", "plays": [False, True, False]},
           {"id": "3", "expect": "clean", "plays": [False, False, True]}, {"id": "4", "expect": "clean", "plays": [None, None, True]}]
    now = score(res)
    check("score: each case's median; found, blocked, unreviewed", now, {"found": 1, "flag": 2, "blocked": 1, "clean": 1, "unreviewed": 1, "plays": PLAYS})
    check("median: 2 reviewed plays that split find no bug and block nothing", (median({"expect": "flag", "plays": [True, None, False]}), median({"expect": "clean", "plays": [True, None, False]})), (False, True))
    check("merge: the plays of each run, case by case", merge([[{"id": "1", "expect": "flag", "plays": [True]}], [{"id": "1", "expect": "flag", "plays": [False], "why": ["no finding in the file"]}]]), [{"id": "1", "expect": "flag", "plays": [True, False], "why": ["", "no finding in the file"]}])
    rc = {"expect": "flag", "path": "a.php", "line": 5, "fixed": [[5, 6]]}
    check("reason: found, outside with its distance, rejected, none in the file, not reviewed",
          [reason(rc, r) for r in ({"findings": [{"severity": "major", "file": "a.php", "line": 6}]}, {"findings": [{"severity": "major", "file": "a.php", "line": 19}]},
                                   {"findings": [{"severity": "minor", "file": "a.php", "line": 5, "rejected": "w"}]}, {"findings": [{"severity": "major", "file": "b.php", "line": 5}]}, None)],
          ["found", "outside the fixed lines, 13 lines away", "rejected by verification", "no finding in the file", "not reviewed"])
    check("reasons: each once, with its plays", reasons({"expect": "flag", "plays": [True, False, None], "why": ["found", "no finding in the file", ""]}), "found (1), no finding in the file (1), not reviewed (1)")
    check("short: fewer than MIN_CASES of a kind", (short(res), short([{"expect": k} for k in ("flag", "clean") for _ in range(MIN_CASES)])), (f"2 flag cases, fewer than {MIN_CASES}; 2 clean cases, fewer than {MIN_CASES}", ""))
    check("unplayed: a case not played PLAYS times", unplayed(res + [{"id": "5", "expect": "flag", "plays": [True]}]), ["5"])
    check("found_floor: a share of the flag cases, rounded up, never below one", [found_floor(f, sh) for f, sh in ((10, 0.3), (10, 0), (11, 0.3), (0, 0.3))], [3, 1, 4, 1])
    check("worse: below the floor whatever the baseline", ("below the floor of 3" in worse({**now, "found": 2, "flag": 10}, {"found": 0, "flag": 10, "blocked": 0}, 0.3), bool(worse({**now, "found": 0, "flag": 10}, {"found": 0, "flag": 10, "blocked": 0}, 0))), (True, True))
    check("worse: at the floor and the baseline is not worse", worse({**now, "found": 3, "flag": 10}, {"found": 3, "flag": 10, "blocked": 0}, 0.3), "")
    check("worse: within one case of the baseline is not worse", worse(now, {"found": 2, "flag": 2, "blocked": 0}), "")
    check("worse: two fewer bugs found is", worse({**now, "found": 0}, {"found": 2, "flag": 2, "blocked": 0}).startswith("it found 0 of 2"), True)
    check("worse: two more clean ones blocked is", "it blocked 2" in worse({**now, "blocked": 2}, {"found": 1, "flag": 2, "blocked": 0}), True)
    check("worse: more than one case unreviewed is", ("could not be reviewed" in worse({"found": 1, "flag": 1, "blocked": 0, "clean": 8, "unreviewed": 2}, {"found": 1, "flag": 1}), worse({"found": 1, "flag": 1, "blocked": 0, "clean": 9, "unreviewed": 1}, {"found": 1, "flag": 1})), (True, ""))
    check("table: says what was missed, and each play", ("**missed**" in table(res, now, {}), "| 1 | flag | found, found, missed | as expected | found (2), missed (1) |" in table(res, now, {})), (True, True))
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv[:1] == ["collect"]:
        cases = collect(int(argv[1]) if len(argv) > 1 else MIN_CASES)
        os.makedirs(os.path.dirname(CASES), exist_ok=True)
        with open(CASES, "w", encoding="utf-8") as fh:
            json.dump(cases, fh, indent=2)
            fh.write("\n")
        print(f"{len(cases)} cases in {CASES}")
        return 0
    if argv[:1] == ["check"] and len(argv) <= 2:
        with open(argv[1] if len(argv) == 2 else CASES, encoding="utf-8") as fh:
            return check(json.load(fh))
    if argv[:1] == ["run"] and (len(argv) == 1 or (len(argv) == 3 and argv[1] == "--play" and argv[2] in [str(n) for n in range(1, PLAYS + 1)])):
        # The review's workflow is read first: an expression the evaluation
        # does not fill in fails the run by its name, before any review.
        try:
            steps = review_steps()
        except (OSError, ValueError) as e:
            print(f"review-eval.py: {e}", file=sys.stderr)
            return 1
        why = check_steps(steps)
        if why:
            print(f"review-eval.py: {why}", file=sys.stderr)
            return 1
        with open(CASES, encoding="utf-8") as fh:
            cases = json.load(fh)
        # A set that does not hold is refused before any paid review (#844).
        if short(cases):
            print(f"review-eval.py: the set has {short(cases)}", file=sys.stderr)
            return 1
        if check(cases):
            return 1
        plays = [int(argv[2])] if len(argv) == 3 else list(range(1, PLAYS + 1))
        results = [{"id": c["id"], "expect": c["expect"], "plays": [], "why": []} for c in cases]
        for n in plays:
            # Each play on its own clones: a fresh checkout and last.json.
            work = tempfile.mkdtemp(prefix=f"dx-eval-{n}-")
            for c, r in zip(cases, results):
                WHY.pop(c["id"], None)
                try:
                    ok = run_case(c, ROOT, work)
                except RuntimeError as e:
                    # Criteria it cannot read stop the play by name (#930).
                    print(f"review-eval.py: {e}", file=sys.stderr)
                    return 1
                why = WHY.pop(c["id"], None)
                if why is None:
                    why = "not reviewed" if ok is None and c["expect"] == "flag" else ""
                print(f"  play {n}, {c['id']}: {ok}{' (' + why + ')' if why else ''}", file=sys.stderr)
                r["plays"].append(ok)
                r["why"].append(why)
        print(json.dumps(results, indent=2))
        return 0
    if argv[:1] in (["score"], ["baseline"]) and len(argv) >= 2:
        runs = []
        for f in argv[1:]:
            with open(f, encoding="utf-8") as fh:
                runs.append(json.load(fh))
        results = merge(runs)
        if short(results):
            print(f"review-eval.py: the set has {short(results)}; it is not scored", file=sys.stderr)
            return 1
        if unplayed(results):
            print(f"review-eval.py: not played {PLAYS} times: {', '.join(unplayed(results))}", file=sys.stderr)
            return 1
        now = score(results)
        # A floor that cannot be read fails by name, never a guessed one.
        try:
            share = found_share()
        except ValueError as e:
            print(f"review-eval.py: {e}", file=sys.stderr)
            return 1
        if argv[0] == "baseline":
            if now["unreviewed"]:
                print(f"review-eval.py: {now['unreviewed']} cases were not reviewed; a baseline is written only from a whole run", file=sys.stderr)
                return 1
            # A baseline below the floor would gate nothing (#930 C2).
            low = below_floor(now, share)
            if low:
                print(f"review-eval.py: {low}; no baseline is written below it", file=sys.stderr)
                return 1
            with open(BASELINE, "w", encoding="utf-8") as fh:
                json.dump(now, fh, indent=2)
                fh.write("\n")
            print(json.dumps(now))
            return 0
        try:
            with open(BASELINE, encoding="utf-8") as fh:
                base = json.load(fh)
            # A baseline of another number of plays is not comparable.
            if base.get("plays") != PLAYS:
                raise ValueError("plays")
        except (OSError, ValueError):
            # No baseline is no gate: that fails, it never passes quietly.
            print(table(results, now, {}))
            print(f"\n**No baseline** of {PLAYS} plays at {BASELINE}: write one with `review-eval.py baseline`.")
            return 1
        print(table(results, now, base))
        why = worse(now, base, share)
        if why:
            print(f"\n**Worse than the baseline:** {why}.")
        return 1 if why else 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
