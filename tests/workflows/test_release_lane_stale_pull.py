"""#925 C2: an open release pull request `chore/release-vX` an earlier lane
left does not stop the lane from releasing vX. release() lists the open
pull requests of its branch before it pushes: its own (the lane's mark,
opened by the App) is reused, edited and merged, with no `gh pr create`;
one without the mark (a person's) is an error before anything is pushed,
and nothing is closed or tagged. `run` is release-lane.py's Fake."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("release_lane_925_c2", ROOT / "scripts/release-lane.py")
lane = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lane)
import org  # noqa: E402

PLAN = dict(lane.plan({"last": "7.10.0", "next": "7.10.1", "bump": "patch", "pending": True},
                      ["fix(autopilot): a stuck draft goes on (#600)"]), sha="p1")


def lane_run(open_pulls):
    """A fake run: main at the planned commit, `gh pr list --head
    chore/release-v7.10.1` giving OPEN_PULLS, a pull request whose checks
    pass at h1 and that merges as abc123, onto p1, once merged."""
    fake = lane.Fake()

    def view(argv):
        if fake.has("gh", "pr", "merge"):
            return json.dumps({"mergedAt": "2026-11-21T10:00:00Z", "mergeCommit": {"oid": "abc123"}, "state": "MERGED", "headRefOid": "h1"})
        return json.dumps({"mergedAt": None, "state": "OPEN", "headRefOid": "h1", "mergeStateStatus": "CLEAN",
                           "statusCheckRollup": [{"name": "ci", "status": "COMPLETED"}]})

    def release_view(argv):
        raise RuntimeError("release not found")
    fake.answers = {"rev-parse origin/main": "p1\n", "rev-parse abc123^": "p1\n",
                    "gh pr list": json.dumps(open_pulls),
                    "gh pr create": "https://github.com/O/.github/pull/700\n",
                    "gh pr view": view, "gh pr checks": json.dumps([{"name": "ci", "bucket": "pass"}]),
                    "diff --name-only": "CHANGELOG.md\n",
                    "changelog.py build": "# Changelog\n", "changelog.py notes": "notes\n", "gh release view": release_view}
    return fake


def tags(fake):
    return [c for c in fake.calls if c[3:4] == ("tag",)]


def test_the_lane_s_own_open_pull_request_is_reused_merged_and_tagged(tmp_path):
    mine = {"number": 690, "body": lane.MARK + "\nThe release lane's release of v7.10.1: …\n", "author": {"login": f"app/{org.APP}", "is_bot": True}}
    fake = lane_run([mine])
    out = lane.release(PLAN, "O/.github", run=fake, sleep=lambda s: None, minutes=1, root=str(tmp_path))
    assert out.get("version") == "v7.10.1" and "error" not in out
    lists = [c for c in fake.calls if c[:3] == ("gh", "pr", "list")]
    assert lists and "chore/release-v7.10.1" in lists[0] and "open" in lists[0]
    assert not fake.has("gh", "pr", "create")
    assert fake.has("gh", "pr", "edit", "690")
    assert fake.has("gh", "pr", "merge", "690")
    assert fake.has("git", "-C", str(tmp_path), "tag", "v7.10.1", "abc123")
    assert not fake.has("gh", "pr", "close")


def test_one_without_the_lane_s_mark_is_an_error_before_anything_is_pushed(tmp_path):
    theirs = {"number": 691, "body": "My own release notes.\n", "author": {"login": "ana", "is_bot": False}}
    fake = lane_run([theirs])
    try:
        lane.release(PLAN, "O/.github", run=fake, sleep=lambda s: None, minutes=1, root=str(tmp_path))
        raised = ""
    except RuntimeError as err:
        raised = str(err)
    assert "#691" in raised
    assert not fake.has("gh", "pr", "close") and not fake.has("gh", "pr", "merge") and not fake.has("gh", "pr", "create")
    assert tags(fake) == []
    assert [c for c in fake.calls if c[1:2] and str(c[1]).endswith("api-commit.py")] == []


def test_the_mark_from_anyone_but_the_app_is_not_the_lane_s(tmp_path):
    copied = {"number": 692, "body": lane.MARK + "\n", "author": {"login": "ana", "is_bot": False}}
    fake = lane_run([copied])
    try:
        lane.release(PLAN, "O/.github", run=fake, sleep=lambda s: None, minutes=1, root=str(tmp_path))
        raised = ""
    except RuntimeError as err:
        raised = str(err)
    assert "#692" in raised and tags(fake) == [] and not fake.has("gh", "pr", "merge")


def test_with_none_open_it_opens_its_own_as_before(tmp_path):
    fake = lane_run([])
    out = lane.release(PLAN, "O/.github", run=fake, sleep=lambda s: None, minutes=1, root=str(tmp_path))
    assert out.get("version") == "v7.10.1"
    assert fake.has("gh", "pr", "create") and fake.has("gh", "pr", "merge", "700")
