#!/usr/bin/env python3
"""The approval a release needs before anything is published (#134, #82).

A release is a person's decision: the issue "Release X.Y.Z" that a person
accepted (#82, scripts/release-issue.py verify). That is the approval, and
no environment reviewer is needed for it. Before it, the approval was the
environment's required reviewers, which a private repository below GitHub
Enterprise cannot have at all (the API answers 422 on the Team plan), so
there the deploy job once ran with nobody deciding (#134). They still count
for a repository that has them and no release issue yet. This script
decides, from what GitHub says, whether this run may hand its version to the
deploy job, and says in the summary why not when it may not.

Environment:
  PRIVATE       true when the repository is private (github.event.repository.private)
  MODE          approve (a person approves) or auto (the policy said
                `release.<bump>: auto` and the run goes through the caller's
                auto-environment, which has no reviewers by design): auto
                passes the gate, the policy already decided
  DRY_RUN       true in a rehearsal: it passes the gate (nothing is
                published) and the summary says what would have been refused
  RELEASE_ISSUE_FILE  the answer of scripts/release-issue.py verify for this
                version, as a file; missing, empty or not JSON when it was not
                read
  ENVIRONMENT_FILE  the answer of GET /repos/{r}/environments/{name}, as a
                file; missing, empty or not JSON when the read failed
  WAITING_FILE  the answer of GET /repos/{r}/actions/runs?status=waiting (and
                pending), as a file, for the "queued behind" notice; optional
  RUN_ID        this run's id (left out of that notice)
  VERSION       the version computed, for the summary
  GITHUB_OUTPUT where go=true|false and why=<one line> are written

Prints the Markdown for the summary. Exit 0 always: the workflow reads `go`.

The rule:
  - a release issue for this version, accepted by a person, whose title
    still names it: deploy (environment reviewers, if any, approve too);
  - otherwise the environment's required reviewers, as before #82: with
    them, deploy, and they approve;
  - rules read and no reviewers: nothing deploys, and the summary says to
    open and accept the release issue;
  - rules that could not be read (the caller grants no `actions: read`): a
    private repository deploys nothing (below Enterprise it can have no
    reviewer, and this is the case that published with nobody deciding); a
    public one deploys as before, with a warning that asks for the
    permission so the rules are checked next time.
Nothing here needs more than the caller grants: without `issues: read` the
release issue is not read and the reviewers decide, as before; without
`actions: read` the check is as safe as it can be, never stricter than the
old behaviour for a public repository, never looser for a private one.
"""
import json
import os
import sys


def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError, TypeError):
        return None


def reviewers_of(environment):
    """The logins of the environment's required reviewers, [] when the rule
    is not there; None when `environment` is not an answer at all."""
    if not isinstance(environment, dict) or "protection_rules" not in environment:
        return None
    out = []
    for rule in environment.get("protection_rules") or []:
        if rule.get("type") != "required_reviewers":
            continue
        for r in rule.get("reviewers") or []:
            who = (r.get("reviewer") or {}).get("login") or (r.get("reviewer") or {}).get("slug") or ""
            out.append(who)
    return out


def decide(private, reviewers, mode="approve", dry_run=False, issue=None):
    """(go, why). `issue` is release-issue.py verify's answer, or None when
    it was not read."""
    if mode == "auto":
        return True, "the policy says this bump releases without a person (release.<bump>: auto, through the auto-environment)"
    if isinstance(issue, dict) and issue.get("ok") is True:
        why = f"{issue.get('why')}, is the approval"
        if reviewers:
            why += f"; the environment's required reviewers ({', '.join(reviewers)}) approve the deployment too (remove them once every release goes through its issue)"
        return True, why
    go, why = _decide(private, reviewers)
    if not go:
        why = f"{issue_why(issue)}, and {why}"
        if dry_run:
            return True, f"a rehearsal, which publishes nothing; a real release here would have been refused: {why}"
    return go, why


def issue_why(issue):
    if not isinstance(issue, dict):
        return "the release issue was not read"
    return issue.get("why") or "no release issue approves it"


def _decide(private, reviewers):
    if reviewers is None:
        if private:
            return False, ("the environment's protection rules could not be read (the caller's release job grants no `actions: read`), and a "
                           "private repository below GitHub Enterprise can have no required reviewer, so nothing deploys")
        return True, ("the environment's protection rules could not be read (grant `actions: read` to the caller's release job so they are "
                      "checked); a public repository deploys as before, and its reviewers, if any, approve")
    if reviewers:
        return True, f"the environment's required reviewers ({', '.join(reviewers)}) approve the deployment"
    if private:
        return False, "the environment has no required reviewer either (a private repository below GitHub Enterprise cannot have one)"
    return False, "the environment has no required reviewer either"


def queued_behind(waiting, run_id):
    """The other runs still waiting for an approval: they hold the
    one-release-at-a-time group, so this run's deployment queues behind them."""
    runs = (waiting or {}).get("workflow_runs") or [] if isinstance(waiting, dict) else []
    return [(r.get("id"), r.get("html_url", ""), r.get("created_at", ""), r.get("status", ""))
            for r in runs if str(r.get("id")) != str(run_id) and r.get("status") in ("waiting", "pending")]


def summary(go, why, version, behind):
    lines = []
    if go:
        lines.append(f"**Approval:** {why}.")
    else:
        lines.append(f"## Not released\n\n{version} is the version to release, but {why}.\n\n"
                     f"**To release it:** open the issue `Release {version}` (the Release form) and accept it (`accepted`): a person's acceptance "
                     f"is the approval, and the release pull request it opens publishes {version} once it merges. If `main` already says {version}, "
                     f"re-run this workflow once the issue is accepted.")
    if behind:
        lines.append("")
        lines.append("**Queued behind:** this workflow releases one at a time, and these runs still wait for an approval; approve or cancel them, or this run's deployment waits behind them:")
        for rid, url, created, status in behind:
            lines.append(f"- [run {rid}]({url}), {status} since {created}")
    return "\n".join(lines) + "\n"


def main():
    private = os.environ.get("PRIVATE", "").strip().lower() == "true"
    reviewers = reviewers_of(read_json(os.environ.get("ENVIRONMENT_FILE", "")))
    issue = read_json(os.environ.get("RELEASE_ISSUE_FILE", ""))
    go, why = decide(private, reviewers, os.environ.get("MODE", "approve"), os.environ.get("DRY_RUN", "").strip().lower() == "true",
                     issue if isinstance(issue, dict) else None)
    # One line: `why` may quote an issue's title, and GITHUB_OUTPUT takes one
    # key per line.
    why = " ".join(why.split())
    if go and reviewers is None:
        print(f"::warning::{why}", file=sys.stderr)
    behind = queued_behind(read_json(os.environ.get("WAITING_FILE", "")), os.environ.get("RUN_ID", ""))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"go={'true' if go else 'false'}\nwhy={why}\n")
    sys.stdout.write(summary(go, why, os.environ.get("VERSION", "the version"), behind))
    return 0


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        ok = got == want
        failed += 0 if ok else 1
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": got {got!r}, want {want!r}"))

    with_rev = {"protection_rules": [{"type": "branch_policy"}, {"type": "required_reviewers", "reviewers": [{"type": "User", "reviewer": {"login": "soydiloreto"}}]}]}
    without = {"protection_rules": [{"id": 1, "type": "branch_policy"}], "deployment_branch_policy": {"custom_branch_policies": True}}
    accepted = {"ok": True, "version": "1.0.0", "issue": 7, "by": "soydiloreto", "at": "2026-10-15T10:00:00Z",
                "why": "issue #7 `Release 1.0.0`, accepted by soydiloreto at 2026-10-15T10:00:00Z"}
    missing = {"ok": False, "version": "1.0.0", "why": "no issue titled `Release 1.0.0` with the `lane:release` label exists"}
    unreadable = {"ok": False, "unreadable": True, "version": "1.0.0", "why": "the release issues could not be read (x); the caller's release job needs `issues: read`"}
    check("reviewers are read", reviewers_of(with_rev), ["soydiloreto"])
    check("no rule, no reviewers", reviewers_of(without), [])
    check("not an answer: unknown", (reviewers_of(None), reviewers_of({}), reviewers_of({"message": "Resource not accessible by integration"})), (None, None, None))
    # #82: a release issue a person accepted is the approval, with no reviewer at all.
    go, why = decide(True, [], issue=accepted)
    check("#82: an accepted release issue releases a private repository with no reviewer (Team plan)", (go, "accepted by soydiloreto" in why), (True, True))
    check("#82: and a public one", decide(False, [], issue=accepted)[0], True)
    check("#82: and one whose environment rules could not be read", decide(True, None, issue=accepted)[0], True)
    go, why = decide(False, ["x"], issue=accepted)
    check("#82: reviewers left on the environment approve too, and the summary says so", (go, "approve the deployment too" in why), (True, True))
    go, why = decide(True, [], issue=missing)
    check("#82: no release issue and no reviewer: nothing deploys, saying both", (go, "Release 1.0.0" in why, "no required reviewer" in why), (False, True, True))
    go, why = decide(False, [], issue=unreadable)
    check("#82: release issues that could not be read approve nothing, and name the permission", (go, "issues: read" in why), (False, True))
    check("#82: an answer that is not ok never approves, whatever it says", decide(True, [], issue={"ok": False, "why": "issue #7 is the approval"})[0], False)
    check("#82: a truthy answer that is not a verdict never approves", decide(True, [], issue={"ok": "yes"})[0], False)
    # C1 (#134): no reviewer and no release issue, nothing deploys.
    go, why = decide(False, [])
    check("C1: a public repository without a required reviewer or a release issue does not deploy", go, False)
    check("C1: and it says the release issue was not read", "release issue was not read" in why, True)
    go, why = decide(True, [])
    check("C1: a private repository without one does not deploy either", go, False)
    check("C1: and says it cannot have a reviewer", "cannot have one" in why, True)
    # C2: with a reviewer, as before.
    check("C2: with a required reviewer the deployment goes on and waits for them", decide(False, ["soydiloreto"]), (True, "the environment's required reviewers (soydiloreto) approve the deployment"))
    check("C2: also when there is no release issue for it", decide(False, ["soydiloreto"], issue=missing)[0], True)
    check("C2: in a private repository too (Enterprise)", decide(True, ["soydiloreto"])[0], True)
    # Unreadable rules: never looser for a private repository, never stricter for a public one.
    go, why = decide(True, None)
    check("unreadable rules: a private repository deploys nothing, and the summary names the permission", (go, "actions: read" in why), (False, True))
    go, why = decide(False, None)
    check("unreadable rules: a public repository deploys as before, asking for the permission", (go, "actions: read" in why), (True, True))
    # The policy's auto path and a rehearsal pass the gate.
    check("auto: the policy decided, no reviewer is asked for", decide(True, [], "auto")[0], True)
    go, why = decide(False, [], "approve", True, missing)
    check("dry run: passes, and says what a real release would have met", (go, why.startswith("a rehearsal"), "Release 1.0.0" in why), (True, True, True))
    check("dry run: with a reviewer it says nothing special", decide(False, ["x"], "approve", True), (True, "the environment's required reviewers (x) approve the deployment"))
    # C3: queued behind.
    waiting = {"workflow_runs": [{"id": 37071887680, "html_url": "https://github.com/o/r/actions/runs/37071887680", "created_at": "2026-10-02T22:19:45Z", "status": "waiting"},
                                 {"id": 99, "html_url": "u", "created_at": "x", "status": "waiting"},
                                 {"id": 5, "html_url": "u5", "created_at": "y", "status": "completed"}]}
    behind = queued_behind(waiting, "99")
    check("C3: the other waiting runs are named, this one and the finished ones are not", [b[0] for b in behind], [37071887680])
    text = summary(True, "ok", "1.0.0", behind)
    check("C3: the summary links the run and says since when", ("actions/runs/37071887680" in text, "since 2026-10-02T22:19:45Z" in text, "approve or cancel" in text), (True, True, True))
    check("C3: no waiting runs, no notice", "Queued behind" in summary(True, "ok", "1.0.0", []), False)
    check("C3: an unreadable list is no list", queued_behind(None, "1"), [])
    text = summary(False, "why", "1.0.0", [])
    check("not released: the summary names the version and why", text.startswith("## Not released\n\n1.0.0 is the version to release, but why."), True)
    check("not released: and says how to release it", "open the issue `Release 1.0.0`" in text, True)
    # main() end to end, through files and GITHUB_OUTPUT.
    import contextlib
    import io
    import tempfile

    def run(files):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "out")
            open(out_path, "w").close()
            env = {"PRIVATE": "true", "WAITING_FILE": os.path.join(tmp, "none"), "RUN_ID": "1", "GITHUB_OUTPUT": out_path, "VERSION": "1.0.0",
                   "ENVIRONMENT_FILE": os.path.join(tmp, "none"), "RELEASE_ISSUE_FILE": os.path.join(tmp, "none")}
            for key, obj in files.items():
                env[key] = os.path.join(tmp, key)
                with open(env[key], "w") as fh:
                    json.dump(obj, fh)
            saved = dict(os.environ)
            os.environ.update(env)
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    main()
            finally:
                os.environ.clear()
                os.environ.update(saved)
            outputs = dict(l.split("=", 1) for l in open(out_path).read().split("\n") if "=" in l)
            return outputs.get("go"), buf.getvalue()

    go, text = run({"ENVIRONMENT_FILE": without})
    check("main: go=false reaches GITHUB_OUTPUT and the summary says Not released", (go, text.startswith("## Not released")), ("false", True))
    go, text = run({"ENVIRONMENT_FILE": without, "RELEASE_ISSUE_FILE": accepted})
    check("main: the release issue's verdict is read from its file and releases", (go, "accepted by soydiloreto" in text), ("true", True))
    go, text = run({"ENVIRONMENT_FILE": without, "RELEASE_ISSUE_FILE": ["not", "a", "verdict"]})
    check("main: a file that is not a verdict approves nothing", go, "false")
    go, text = run({"ENVIRONMENT_FILE": without, "RELEASE_ISSUE_FILE": dict(missing, why="title `x\ngo=true`")})
    check("main: a title with a line break cannot add an output", go, "false")
    print("all tests passed" if not failed else f"{failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(self_test() if sys.argv[1:] == ["--test"] else main())
