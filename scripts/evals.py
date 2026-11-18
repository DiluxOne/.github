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


def score(step, results):
    if step == "review":
        flag = [r for r in results if r["expect"] == "flag" and r["ok"] is not None]
        clean = [r for r in results if r["expect"] == "clean" and r["ok"] is not None]
        return {"found": sum(1 for r in flag if r["ok"]), "flag": len(flag),
                "blocked": sum(1 for r in clean if not r["ok"]), "clean": len(clean),
                "unreviewed": sum(1 for r in results if r["ok"] is None)}
    run = [r for r in results if r["ok"] is not None]
    return {"passed": sum(1 for r in run if r["ok"]), "cases": len(run), "unrun": len(results) - len(run)}


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
        return _load("review_eval_github", "review-eval.py").collect(n)
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
    if argv[:1] == ["collect"] and len(argv) in (2, 3) and argv[1] in STEPS:
        cases = collect(argv[1], int(argv[2]) if len(argv) == 3 else 6)
        path = os.path.join(EVALS, argv[1], "cases.json")
        write_json(path, cases)
        print(f"{len(cases)} cases in {path}")
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
