#!/usr/bin/env python3
"""What the engine posts is held to what a person's is (#694): every issue
and pull request the engine opens is checked, before it is posted, by the
script that checks a person's, so none is born `incomplete` or with a wrong
title, branch or `Closes #`.

  - an issue: scripts/issue-schema.py check (G1), as the triage reads a
    person's issue;
  - a release issue (the Release form's, which G1 skips): its title
    `Release X.Y.Z` and its `lane:release` label (policy/issue-schema.yml
    `release`);
  - a pull request: scripts/conventions.sh (its title and its branch, as
    the conventions check reads a person's), and `Closes #N` in its body
    when it closes the issue N.

  engine-post.py check issue [--title T] < BODY
  engine-post.py check release --title T [--label L ...] < BODY
  engine-post.py check pull --title T --branch B [--closes N] < BODY
        prints what is wrong, one line each; exit 1 when anything is
  engine-post.py --test     one case per writer: the release lane's bug,
        its watch's bug and its release pull request (release-lane.py), the
        release issue (release-issue.py), the nightly review's bug
        (nightly-review.py), the autopilot's draft pull request
        (autopilot.py), a decision's sub-issue (decision.py), the triage's
        rewrite (issue-schema.py shape-check), and the release scenarios'
        fixtures (tests/release/scenarios.yml)

The writers import it (`load()`) and call `refuse(...)`, which raises
before anything is posted.
"""
import argparse
import importlib.util
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RELEASE_TITLE = re.compile(r"^Release \d+\.\d+\.\d+$")


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def issue(body):
    """What G1 finds wrong with an issue's body: [] when it passes."""
    return [str(e) for e in module("issue_schema", "issue-schema.py").check(body or "", "prd")["errors"]]


def release(title, labels):
    """What is wrong with a release issue: its title and its label."""
    sch = module("issue_schema", "issue-schema.py").schema()["release"]
    out = []
    if not RELEASE_TITLE.match(str(title or "")):
        out.append(f"the release issue's title is not `{sch['title']}X.Y.Z`: {title!r}")
    if sch["label"] not in (labels or []):
        out.append(f"the release issue has no `{sch['label']}` label")
    return out


def pull(title, branch, body, closes=None):
    """What the conventions check finds wrong with a pull request's title and
    branch (scripts/conventions.sh, as it reads a person's), and a body that
    does not say `Closes #<closes>`."""
    env = dict(os.environ, BRANCH=str(branch or ""), TITLE=str(title or ""), BODY=str(body or ""), BASE="", HEAD_REF="",
               AUTHOR_TYPE="Bot", SECTIONS="", LABELS="", COMMENTS_FILE="", MAX_LINES="", TRUSTED="", PRE_PR="", KIND="")
    with tempfile.TemporaryDirectory() as empty:
        got = subprocess.run(["bash", os.path.join(HERE, "conventions.sh")], cwd=empty, env=env, capture_output=True, text=True)
    out = [line.split("::error::", 1)[1] for line in got.stdout.splitlines() if "::error::" in line]
    if got.returncode and not out:
        out.append(f"the conventions check failed: {(got.stderr or got.stdout).strip()[-300:]}")
    if closes and not re.search(rf"(?m)\bCloses #{re.escape(str(closes))}\b", str(body or "")):
        out.append(f"the pull request's body does not say Closes #{closes}")
    return out


def refuse(what, *args, **kwargs):
    """Raises RuntimeError, naming what is wrong, when the `what` ("issue",
    "release" or "pull") the engine is about to post would not pass; else
    returns. What a writer calls before it posts."""
    wrong = {"issue": issue, "release": release, "pull": pull}[what](*args, **kwargs)
    if wrong:
        raise RuntimeError(f"the engine's {what} would not pass its own checks, so it is not posted: " + "; ".join(wrong))


def load():
    """This module, for a writer: `load().refuse("issue", body)`."""
    return module("engine_post", "engine-post.py")


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    # The check itself.
    check("pull: a title and a branch a person's would pass, and Closes #", pull("fix: the greeting", "fix/12-the-greeting", "Closes #12", 12), [])
    bad = pull("Fix the greeting.", "scenario/x", "No reference", 12)
    check("pull: a wrong title, a wrong branch and no Closes # are each named",
          (len(bad), any("Branch" in b for b in bad), any("Conventional Commit" in b for b in bad), bad[-1]), (3, True, True, "the pull request's body does not say Closes #12"))
    check("issue: a body the schema refuses is named", bool(issue("Something should be better.")), True)
    check("release: a title and a label the Release form gives", (release("Release 7.15.0", ["lane:release"]), len(release("release 7", []))), ([], 2))
    try:
        refuse("issue", "nothing")
        check("refuse: raises before anything is posted", "no error", "RuntimeError")
    except RuntimeError as e:
        check("refuse: raises before anything is posted, naming what is wrong", "would not pass its own checks" in str(e), True)

    # C7, one case per writer.
    lane = module("release_lane", "release-lane.py")
    p = {"release": True, "version": "v7.15.0", "previous": "v7.14.0", "major": "v7", "breaking": False, "sha": "a" * 40}
    bug = lane.decide(p, [{"id": "spec-to-draft", "ok": False, "why": ["no label autopilot"], "run": "https://github.com/o/t/actions/runs/9"}], "https://github.com/O/.github/actions/runs/1")
    check("C7: release-lane.py's bug passes the issue schema", issue(bug["body"]), [])
    check("C7: release-lane.py's watch bug passes the issue schema", issue(lane.rollback_bug(p, "https://github.com/O/a/actions/runs/2")["body"]), [])
    rel = lane.release_pull(p)
    check("C7: release-lane.py's release pull request passes the conventions check", pull(rel["title"], rel["branch"], rel["body"]), [])
    ri = module("release_issue", "release-issue.py").engine_issue("7.15.0", "feat!: x", "https://github.com/O/.github/actions/runs/1")
    check("C7: release-issue.py's release issue has the Release form's title and label", release(ri["title"], ri["labels"]), [])
    nightly = module("nightly_review", "nightly-review.py")
    found = nightly.bugs([], [{"severity": "major", "security": False, "file": "a.php", "line": 3, "title": "It breaks", "detail": "Steps..."}], "o/r")
    check("C7: nightly-review.py's bug passes the issue schema", issue(found[0]["issue_body"]), [])
    ap = module("autopilot", "autopilot.py")
    prd = ("### Problem\n\nNo greeting.\n\n### Scope\n\n- A greeting.\n\n### Out of scope\n\n- Else.\n\n### Acceptance criteria\n\n"
           "- C1: Given it, when read, then it greets.\n\n### Criticality\n\nNormal\n")
    for issue_type, title in (("Feature", "A greeting"), ("Bug", "fix(core): the greeting says helo"), ("Task", "Docs: the greeting")):
        d = ap.draft(12, issue_type, title, prd + "\n### Spec: approach\n\nWrite it.\n")
        check(f"C7: autopilot.py's draft pull request ({issue_type}) passes the conventions check and closes its issue", pull(d["title"], d["branch"], d["body"], 12), [])
    dec = module("decision", "decision.py")
    check("C7: decision.py's sub-issue passes the issue schema", issue(dec.child_body(prd + "\n### Repositories\n\nall\n", "O/.github#5", "app")), [])
    schema = module("issue_schema", "issue-schema.py")
    with tempfile.TemporaryDirectory() as d:
        old, new = os.path.join(d, "old.md"), os.path.join(d, "new.md")
        with open(old, "w") as fh:
            fh.write("It should greet.\n")
        with open(new, "w") as fh:
            fh.write(prd)
        shaped = schema.shape_check(open(old).read(), open(new).read())
        check("C7: the triage's rewrite, once shape-check takes it as ready, passes the issue schema", (shaped["ok"], shaped["ready"], issue(prd)), (True, True, []))
    scen = module("release_scenarios", "release-scenarios.py")
    conf = scen.load_yaml(os.path.join(ROOT, scen.SCENARIOS))
    check("C7: the release scenarios' fixtures pass what a person's would", scen.fixture_problems(conf, issue, pull, release), [])
    bad_conf = {"bodies": {"pull": "No reference."}, "scenarios": [{"id": "x", "opens": {"pull": {"title": "a change", "body": "pull"}}}]}
    check("C7: a scenario's pull request with no type and no Closes # is named before it is posted",
          [w.split(": ", 2)[1] for w in scen.fixture_problems(bad_conf, issue, pull, release)][:1], ["its pull request"])
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    p = argparse.ArgumentParser(prog="engine-post.py")
    p.add_argument("check", choices=("check",))
    p.add_argument("what", choices=("issue", "release", "pull"))
    p.add_argument("--title", default="")
    p.add_argument("--branch", default="")
    p.add_argument("--closes", default="")
    p.add_argument("--label", action="append", default=[])
    a = p.parse_args(argv)
    body = sys.stdin.read()
    if a.what == "issue":
        wrong = issue(body)
    elif a.what == "release":
        wrong = release(a.title, a.label)
    else:
        wrong = pull(a.title, a.branch, body, a.closes or None)
    for line in wrong:
        print(line)
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
