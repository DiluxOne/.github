#!/usr/bin/env python3
"""The approval a release needs before anything may reach wordpress.org (#134).

plugin-release-wp.yml is built on the environment's required reviewers: a
push to main with a version pending waits for a person. It never checked that
the environment has one, and a private repository below GitHub Enterprise
cannot have one at all (required reviewers and wait timers are Enterprise
features for private repositories; the API answers 422 on the Team plan), so
there the deploy job ran with nobody deciding. This script decides, from what
GitHub says, whether this run may hand its version to the deploy job, and
says in the summary why not when it may not.

Environment:
  PRIVATE       true when the repository is private (github.event.repository.private)
  MODE          approve (a person approves) or auto (the policy said
                `release.<bump>: auto` and the run goes through the caller's
                auto-environment, which has no reviewers by design): auto
                passes the gate, the policy already decided
  DRY_RUN       true in a rehearsal: it passes the gate (nothing is
                published) and the summary says what would have been refused
  ENVIRONMENT_FILE  the answer of GET /repos/{r}/environments/{name}, as a
                file; missing, empty or not JSON when the read failed
  WAITING_FILE  the answer of GET /repos/{r}/actions/runs?status=waiting (and
                pending), as a file, for the "queued behind" notice; optional
  RUN_ID        this run's id (left out of that notice)
  VERSION       the version computed, for the summary
  GITHUB_OUTPUT where go=true|false and why=<one line> are written

Prints the Markdown for the summary. Exit 0 always: the workflow reads `go`.

The rule:
  - the environment has required reviewers: deploy; they approve, as before;
  - the rules were read and there are none: nothing deploys, and the
    summary says to add a reviewer (or, below Enterprise, to make the
    repository public first);
  - the rules could not be read (the caller grants no `actions: read`): a
    private repository deploys nothing (below Enterprise it can have no
    reviewer, and this is the case that published with nobody deciding); a
    public one deploys as before, with a warning that asks for the
    permission so the rules are checked next time.
Nothing here needs more than the caller already grants: without
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


def decide(private, reviewers, mode="approve", dry_run=False):
    """(go, why)."""
    if mode == "auto":
        return True, "the policy says this bump releases without a person (release.<bump>: auto, through the auto-environment)"
    go, why = _decide(private, reviewers)
    if not go and dry_run:
        return True, f"a rehearsal, which publishes nothing; a real release here would have been refused: {why}"
    return go, why


def _decide(private, reviewers):
    if reviewers is None:
        if private:
            return False, ("the environment's protection rules could not be read (the caller's release job grants no `actions: read`), and a "
                           "private repository below GitHub Enterprise can have no required reviewer, so nothing deploys; make the repository "
                           "public and add a required reviewer, or grant the permission so the rules are checked")
        return True, ("the environment's protection rules could not be read (grant `actions: read` to the caller's release job so they are "
                      "checked); a public repository deploys as before, and its reviewers, if any, approve")
    if reviewers:
        return True, f"the environment's required reviewers ({', '.join(reviewers)}) approve the deployment"
    if private:
        return False, ("the environment has no required reviewer, and a private repository below GitHub Enterprise cannot have one: nothing "
                       "deploys from here; make the repository public, then add a required reviewer to the environment")
    return False, "the environment has no required reviewer, so nobody would approve this deployment: add one to the environment, then push again"


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
        lines.append(f"## Not released\n\n{version} is the version to release, but {why}.")
    if behind:
        lines.append("")
        lines.append("**Queued behind:** this workflow releases one at a time, and these runs still wait for an approval; approve or cancel them, or this run's deployment waits behind them:")
        for rid, url, created, status in behind:
            lines.append(f"- [run {rid}]({url}), {status} since {created}")
    return "\n".join(lines) + "\n"


def main():
    private = os.environ.get("PRIVATE", "").strip().lower() == "true"
    reviewers = reviewers_of(read_json(os.environ.get("ENVIRONMENT_FILE", "")))
    go, why = decide(private, reviewers, os.environ.get("MODE", "approve"), os.environ.get("DRY_RUN", "").strip().lower() == "true")
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
    check("reviewers are read", reviewers_of(with_rev), ["soydiloreto"])
    check("no rule, no reviewers", reviewers_of(without), [])
    check("not an answer: unknown", (reviewers_of(None), reviewers_of({}), reviewers_of({"message": "Resource not accessible by integration"})), (None, None, None))
    # C1: no reviewer, nothing deploys.
    go, why = decide(False, [])
    check("C1: a public repository without a required reviewer does not deploy", go, False)
    check("C1: and the summary says to add one", "add one to the environment" in why, True)
    go, why = decide(True, [])
    check("C1: a private repository without one does not deploy either", go, False)
    check("C1: and the summary says to make it public first", "make the repository public" in why, True)
    # C2: with a reviewer, as before.
    check("C2: with a required reviewer the deployment goes on and waits for them", decide(False, ["soydiloreto"]), (True, "the environment's required reviewers (soydiloreto) approve the deployment"))
    check("C2: in a private repository too (Enterprise)", decide(True, ["soydiloreto"])[0], True)
    # Unreadable rules: never looser for a private repository, never stricter for a public one.
    go, why = decide(True, None)
    check("unreadable rules: a private repository deploys nothing, and the summary names the permission", (go, "actions: read" in why), (False, True))
    go, why = decide(False, None)
    check("unreadable rules: a public repository deploys as before, asking for the permission", (go, "actions: read" in why), (True, True))
    # The policy's auto path and a rehearsal pass the gate.
    check("auto: the policy decided, no reviewer is asked for", decide(True, [], "auto")[0], True)
    go, why = decide(False, [], "approve", True)
    check("dry run: passes, and says what a real release would have met", (go, why.startswith("a rehearsal"), "add one to the environment" in why), (True, True, True))
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
    check("not released: the summary names the version and why", summary(False, "why", "1.0.0", []).startswith("## Not released\n\n1.0.0 is the version to release, but why."), True)
    # main() end to end, through files and GITHUB_OUTPUT.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        env_path, out_path = os.path.join(tmp, "env.json"), os.path.join(tmp, "out")
        json.dump(without, open(env_path, "w"))
        open(out_path, "w").close()
        saved = dict(os.environ)
        os.environ.update({"PRIVATE": "true", "ENVIRONMENT_FILE": env_path,
                           "WAITING_FILE": os.path.join(tmp, "none"), "RUN_ID": "1", "GITHUB_OUTPUT": out_path, "VERSION": "1.0.0"})
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main()
        os.environ.clear()
        os.environ.update(saved)
        outputs = dict(l.split("=", 1) for l in open(out_path).read().split("\n") if "=" in l)
        check("main: go=false reaches GITHUB_OUTPUT and the summary says Not released", (outputs.get("go"), buf.getvalue().startswith("## Not released")), ("false", True))
    print("all tests passed" if not failed else f"{failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(self_test() if sys.argv[1:] == ["--test"] else main())
