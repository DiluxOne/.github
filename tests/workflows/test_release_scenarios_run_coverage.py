"""#843 C3: the release lane's coverage counts the workflow pairs the
scenarios' runs triggered, never what a scenario's `covers:` says. `play`
reads, once at the end, the test repository's runs created since it started
and keeps those that belong to the scenario (a title ending `[<id>]` or the
title of the pull request it observed, or its branch or that pull request's),
each mapped through the caller at its `path` and its event to
`<reusable workflow>:<event>` pairs, in its row's `triggered`; merge's table
names the pairs no row triggered, as a warning that fails nothing. The gh
calls are a fake."""
import datetime
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("release_scenarios_c3", ROOT / "scripts/release-scenarios.py")
scen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scen)

SCENARIO = {"id": "issue-complete", "covers": ["issue-repro.yml:issues", "review-reply.yml:issue_comment"],
            "opens": {"issue": {"title": "feat: a complete issue", "body": "b"}}, "expect": {"labels": ["awaiting-acceptance"]}}
RUNS = [
    # The scenario's issue, by its title: issues.yml on `issues`.
    {"path": ".github/workflows/issues.yml", "event": "issues", "display_title": "feat: a complete issue [issue-complete]",
     "head_branch": "main"},
    # The autopilot's pull request it observed, by its branch.
    {"path": ".github/workflows/test-pull-request.yml", "event": "pull_request", "display_title": "feat: the autopilot's",
     "head_branch": "feat/12-a-complete-issue"},
    # Another scenario's run: not this one's.
    {"path": ".github/workflows/pull-request-comments.yml", "event": "issue_comment", "display_title": "fix: x [other]",
     "head_branch": "main"},
]


def fake():
    calls = []

    def gh(*args, input=None):
        calls.append(args)
        if args[:2] == ("issue", "create"):
            return "https://github.com/o/t/issues/9\n"
        if args[:2] == ("issue", "view"):
            return json.dumps({"labels": [{"name": "awaiting-acceptance"}], "comments": [], "closedByPullRequestsReferences": [{"number": 12}]})
        if args[:2] == ("pr", "view"):
            return json.dumps({"number": 12, "headRefName": "feat/12-a-complete-issue", "title": "feat: the autopilot's", "comments": []})
        if args[:1] == ("api",) and "actions/runs?created=" in " ".join(args):
            # Created now: between the scenario's start and its end.
            at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return json.dumps([dict(r, created_at=at) for r in RUNS])
        return ""
    return gh, calls


def wanted_pairs(rows):
    return scen.played(str(ROOT), scen.test_pack())


def test_play_records_the_pairs_its_runs_triggered_not_its_covers():
    gh, calls = fake()
    row = scen.play(SCENARIO, "o/t", "v7-next", {"b": "a body"}, gh, lambda s: None, 1)
    assert row["ok"] is True
    reads = [c for c in calls if c[:1] == ("api",) and "actions/runs?created=" in " ".join(c)]
    assert len(reads) == 1, "the runs are read once, at the end"
    triggered = row.get("triggered")
    assert triggered is not None
    want = sorted({"issue-triage.yml:issues", "issue-accepted.yml:issues", "issue-claim.yml:issues", "issue-repro.yml:issues", "waiting-update.yml:issues"}
                  | {p for p in wanted_pairs([]) if p.endswith(":pull_request")})
    assert sorted(triggered) == want
    # What `covers:` says and no run triggered is not counted.
    assert "review-reply.yml:issue_comment" not in triggered
    # Another scenario's run is not this one's.
    assert not any(p.endswith(":issue_comment") for p in triggered)


def test_coverage_counts_the_triggered_pairs_never_covers(tmp_path):
    rows = [{"id": "a", "ok": True, "why": [], "run": "", "covers": ["x.yml:issues", "y.yml:pull_request"], "triggered": ["x.yml:issues"]},
            {"id": "b", "ok": False, "why": ["no"], "run": "", "triggered": ["z.yml:issue_comment"]}]
    run_coverage = getattr(scen, "run_coverage", None)
    assert callable(run_coverage), "release-scenarios.py has no run_coverage"
    assert run_coverage(rows, {"x.yml:issues", "y.yml:pull_request", "z.yml:issue_comment"}) == ["y.yml:pull_request"]
    # Transitions and flows are no workflow pair: never named by it.
    assert run_coverage(rows, {"next_step:start", "flow:x", "x.yml:issues"}) == []


def test_merge_names_the_pairs_no_scenario_triggered_and_fails_nothing(tmp_path):
    gs = [{"id": "issue-complete", "scenarios": ["issue-complete"]}]
    triggered = sorted(wanted_pairs([]) - {"issue-repro.yml:issues"})
    for name, rows in (("move", []), ("back", []), ("issue-complete", [{"id": "issue-complete", "ok": True, "why": [], "run": "", "triggered": triggered}])):
        d = tmp_path / "scenarios" / f"scenarios-{name}"
        d.mkdir(parents=True)
        (d / "results.md").write_text(f"<!-- dx-scenarios {json.dumps(rows)} -->\n")
    out = tmp_path / "results.md"
    got = subprocess.run([sys.executable, str(ROOT / "scripts/release-scenarios.py"), "merge", "--dir", str(tmp_path / "scenarios"), "--groups", json.dumps(gs),
                          "--job", "move=success", "--job", "play=success", "--job", "back=success", "--out", str(out)], capture_output=True, text=True, cwd=ROOT)
    assert got.returncode == 0, got.stdout + got.stderr
    assert "Pairs no scenario triggered: `issue-repro.yml:issues`" in got.stdout
    assert "Pairs no scenario triggered: `issue-repro.yml:issues`" in out.read_text()
