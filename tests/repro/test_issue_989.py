"""#989: the Claims daily run failed in every repository on each day a
Dependabot pull request was open. Its one search read `statusCheckRollup`
for every open pull request with a token that asked for neither
`checks: read` nor `statuses: read`, so GitHub refused the whole query and
the run wrote nothing. The token must ask for both, every open pull request
must be read on its own, and one GitHub cannot read is left out with a
warning naming it, never failing the run.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
NOW = "2026-11-20T09:00:00Z"
FORBIDDEN = {"data": {"repository": {"pullRequest": None}},
             "errors": [{"type": "FORBIDDEN", "path": ["repository", "pullRequest", "commits"],
                         "locations": [{"line": 4, "column": 7}],
                         "message": "Resource not accessible by integration"}]}

# The stub `gh`: it logs every call (one JSON line) and answers from the
# pull requests in $STUB ({"prs": {number: node}, "unreadable": [number]}).
GH = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["CALLS"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\n")
stub = json.load(open(os.environ["STUB"], encoding="utf-8"))
prs, unreadable = stub["prs"], [str(n) for n in stub["unreadable"]]
forbidden = json.dumps(stub["forbidden"])
def refuse():
    print(forbidden)
    print("gh: Resource not accessible by integration", file=sys.stderr)
    sys.exit(1)
if args[:2] == ["api", "graphql"]:
    query = next(a for a in args if a.startswith("query="))
    fields = dict(a.split("=", 1) for a in args[2:] if "=" in a and not a.startswith("query="))
    if "search(" in query:
        # GitHub refuses the whole search when one node's field is unreadable.
        if "commits(" in query and unreadable:
            refuse()
        nodes = [prs[n] if "commits(" in query else {"number": prs[n]["number"]} for n in prs]
        print(json.dumps({"data": {"search": {"nodes": nodes}}}))
    elif "pullRequest(" in query:
        n = fields.get("number", "")
        if n in unreadable:
            refuse()
        print(json.dumps({"data": {"repository": {"pullRequest": prs[n]}}}))
    else:
        print(json.dumps({"data": {}}))
elif args[:2] == ["issue", "list"] and "run:claims" in args:
    print("5")
elif args[:1] == ["api"] and args[1].endswith("/comments"):
    print("[[]]")
'''


def node(number, login, typename, changes=False, created="2026-11-01T09:00:00Z"):
    return {"number": number, "createdAt": created, "reviewDecision": "CHANGES_REQUESTED" if changes else "REVIEW_REQUIRED",
            "author": {"__typename": typename, "login": login},
            "latestReviews": {"nodes": [{"state": "CHANGES_REQUESTED", "submittedAt": created}] if changes else []},
            "commits": {"nodes": [{"commit": {"committedDate": created, "authors": {"nodes": [{"user": {"login": login}}]},
                                              "statusCheckRollup": {"state": "SUCCESS"}}}]},
            "closingIssuesReferences": {"nodes": [{"number": 40 + number}]},
            "comments": {"nodes": []}}


def run_daily(tmp_path, prs, unreadable=()):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(GH, encoding="utf-8")
    (bin_dir / "gh").chmod(0o755)
    stub = tmp_path / "stub.json"
    stub.write_text(json.dumps({"prs": {str(p["number"]): p for p in prs}, "unreadable": list(unreadable), "forbidden": FORBIDDEN}), encoding="utf-8")
    calls = tmp_path / "calls"
    calls.touch()
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "CALLS": str(calls), "STUB": str(stub), "NOW": NOW,
           "GITHUB_REPOSITORY": "o/r", "GITHUB_OUTPUT": str(tmp_path / "out"), "REPO_AUTONOMY": str(tmp_path / "none.yml")}
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "claim.py"), "daily"], env=env, capture_output=True, text=True)
    return done, [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]


def pull_reads(calls):
    return [dict(a.split("=", 1) for a in c[2:] if "=" in a and not a.startswith("query=")).get("number")
            for c in calls if c[:2] == ["api", "graphql"] and any(a.startswith("query=") and "pullRequest(" in a for a in c)]


def test_the_daily_token_reads_checks_and_statuses():
    wf = yaml.safe_load((ROOT / ".github/workflows/issue-claim.yml").read_text(encoding="utf-8"))
    bot = next(s for s in wf["jobs"]["daily"]["steps"] if s.get("id") == "bot")["with"]
    assert bot.get("permission-checks") == "read", "the daily token cannot read a pull request's check runs (statusCheckRollup)"
    assert bot.get("permission-statuses") == "read", "the daily token cannot read a pull request's commit statuses (statusCheckRollup)"


def test_a_dependabot_pull_request_is_read_on_its_own_and_the_run_succeeds(tmp_path):
    done, calls = run_daily(tmp_path, [node(7, "dependabot[bot]", "Bot")])
    assert done.returncode == 0, done.stdout + done.stderr
    assert pull_reads(calls) == ["7"], "the Dependabot pull request is not read on its own"
    assert "#7" not in "".join(l for l in done.stdout.splitlines() if l.startswith(("::warning::", "::error::")))
