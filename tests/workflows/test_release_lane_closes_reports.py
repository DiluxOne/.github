"""#832 C5: an open failure report for an earlier candidate (the lane's own
"fix: release candidate vX.Y.Z fails scenario …" issue, with its mark) is
closed as completed, with a comment naming the released version, once a
later version is released and its tag moved. A later candidate's report, a
rollback's bug and the breaking release's issue stay open, and a close that
fails is a warning, never a failed release. scripts/release-lane.py's act,
with its own fake gh and git."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("release_lane_c5", ROOT / "scripts/release-lane.py")
lane = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lane)

RUN = "https://github.com/O/.github/actions/runs/42"
PASSED = [{"id": "issue-complete", "ok": True, "why": [], "run": "https://github.com/o/t/actions/runs/1"}]


def plan(version="v7.10.1"):
    nxt = {"last": "7.10.0", "next": version[1:], "bump": "patch", "pending": True}
    return dict(lane.plan(nxt, ["fix(autopilot): a stuck draft goes on (#600)"]), sha="p1")


def issue(number, title, mark=True, login="dilux-bot[bot]"):
    return {"number": number, "title": title, "body": (lane.MARK + "\n### What happened?\n" if mark else "### What happened?\n"), "user": {"login": login}}


OPEN = [
    issue(11, "fix: release candidate v7.10.0 fails scenario spec-to-draft"),   # earlier: closed
    issue(12, "fix: release candidate v7.10.1 fails scenario issue-complete"),  # this one's, failed before: closed
    issue(13, "fix: release candidate v7.11.0 fails scenario spec-to-draft"),   # later: stays
    issue(14, "fix: v7.9.0 rolled back after a failure in o/r"),                # a rollback's bug: stays
    issue(15, "fix: release candidate v7.9.2 fails scenario x", mark=False),    # no mark: stays
    issue(16, "chore: release v8.0.0"),                                         # the breaking release's issue: stays
]


def fake(issues=OPEN, close_fails=False):
    f = lane.Fake()

    def missing(argv):
        raise RuntimeError("release not found")

    def view(argv):
        if f.has("gh", "pr", "merge"):
            return json.dumps({"mergedAt": "2026-11-02T10:00:00Z", "mergeCommit": {"oid": "abc123"}, "state": "MERGED", "headRefOid": "h1"})
        return json.dumps({"mergedAt": None, "state": "OPEN", "headRefOid": "h1", "statusCheckRollup": [{"name": "ci", "status": "COMPLETED"}]})

    def listing(argv):
        # As `gh api --paginate --slurp` gives it: one list per page.
        return json.dumps([issues])

    def close(argv):
        if close_fails:
            raise RuntimeError("gh issue close: HTTP 403")
        return ""
    f.answers = {"rev-parse origin/main": "p1\n", "rev-parse abc123^": "p1\n",
                 "gh pr create": "https://github.com/O/.github/pull/700\n",
                 "gh pr view": view, "gh pr checks": json.dumps([{"name": "ci", "bucket": "pass"}]),
                 "changelog.py build": "# Changelog\n", "changelog.py notes": "notes\n", "gh release view": missing,
                 "gh issue close": close, "issues?state=open": listing}
    return f


def closes(f):
    return [c for c in f.calls if c[:3] == ("gh", "issue", "close")]


def test_a_release_closes_the_reports_of_earlier_candidates_naming_the_version(tmp_path):
    f = fake()
    d = lane.act(plan(), PASSED, "O/.github", run=f, sleep=lambda s: None, root=str(tmp_path), lane_run=RUN)
    assert d["do"] == "release" and d.get("moved_at") and not d.get("error")
    closed = closes(f)
    assert [c[3] for c in closed] == ["11", "12"]
    for c in closed:
        assert "--repo" in c and c[c.index("--repo") + 1] == "O/.github"
        assert c[c.index("--reason") + 1] == "completed"
        comment = c[c.index("--comment") + 1]
        assert "Released as v7.10.1, which passed every scenario: this candidate's failure no longer holds a release." in comment
        assert RUN in comment
    # Only after the tag moved.
    first = next(i for i, c in enumerate(f.calls) if c[:3] == ("gh", "issue", "close"))
    assert any(c[:6] == ("git", "-C", str(tmp_path), "push", "-f", "origin") for c in f.calls[:first])
    assert d.get("closed") == [11, 12]


def test_versions_compare_as_numbers():
    issues = [issue(21, "fix: release candidate v7.9.0 fails scenario a"), issue(22, "fix: release candidate v7.100.0 fails scenario a")]
    assert lane.stale_reports(issues, "v7.10.1") == [21]


def test_nothing_is_closed_when_the_release_does_not_move_the_tag(tmp_path):
    f = fake()
    f.answers["rev-parse origin/main"] = "p2\n"  # main moved since the plan: nothing released
    d = lane.act(plan(), PASSED, "O/.github", run=f, sleep=lambda s: None, root=str(tmp_path), lane_run=RUN)
    assert d["do"] == "none" and closes(f) == []


def test_nothing_is_closed_when_a_scenario_fails(tmp_path):
    f = fake()
    failed = [{"id": "issue-complete", "ok": False, "why": ["x"], "run": "r"}]
    lane.act(plan(), failed, "O/.github", run=f, sleep=lambda s: None, root=str(tmp_path), lane_run=RUN)
    assert closes(f) == []


def test_a_close_that_fails_is_a_warning_never_a_failed_release(tmp_path, capsys):
    f = fake(close_fails=True)
    d = lane.act(plan(), PASSED, "O/.github", run=f, sleep=lambda s: None, root=str(tmp_path), lane_run=RUN)
    assert d["do"] == "release" and not d.get("error")
    assert any("#11" in w for w in d.get("warnings", []))


def test_a_listing_that_fails_is_a_warning_too(tmp_path):
    f = fake()

    def broken(argv):
        raise RuntimeError("gh api: HTTP 502")
    f.answers["issues?state=open"] = broken
    d = lane.act(plan(), PASSED, "O/.github", run=f, sleep=lambda s: None, root=str(tmp_path), lane_run=RUN)
    assert d["do"] == "release" and not d.get("error") and d.get("warnings") and closes(f) == []
