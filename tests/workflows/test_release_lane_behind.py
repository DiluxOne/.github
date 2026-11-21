"""#925 C3: main moves while the lane is in its release step. The release
pull request reads BEHIND: the lane brings it up to date (`gh pr
update-branch`), follows its new head, waits for the checks at that head
and merges with `--match-head-commit` of it. The merge's parent is then the
new main, which no scenario played: by the rule the Spec chose (E), vX.Y.Z
and vN point at the commit the scenarios tried (the plan's sha), once the
merge's diff is CHANGELOG.md alone. A head moved by anyone else still
stops it. `run` is release-lane.py's Fake."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("release_lane_925_c3", ROOT / "scripts/release-lane.py")
lane = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lane)

PLAN = dict(lane.plan({"last": "7.10.0", "next": "7.10.1", "bump": "patch", "pending": True},
                      ["fix(autopilot): a stuck draft goes on (#600)"]), sha="p1")


def behind_run(changed="CHANGELOG.md\n", moved_by_lane=True):
    """A release pull request #700 at h1, BEHIND main (p2); once the lane
    asks for update-branch (or, when not MOVED_BY_LANE, at once on its
    second read) its head is h2, whose required check is pending on its
    first read and passes on the next. Merged as abc123, onto p2."""
    fake, reads = lane.Fake(), []

    def view(argv):
        reads.append(1)
        if fake.has("gh", "pr", "merge"):
            return json.dumps({"mergedAt": "2026-11-21T10:00:00Z", "mergeCommit": {"oid": "abc123"}, "state": "MERGED", "headRefOid": "h2"})
        updated = fake.has("gh", "pr", "update-branch") if moved_by_lane else len(reads) > 1
        return json.dumps({"mergedAt": None, "state": "OPEN", "headRefOid": "h2" if updated else "h1",
                           "mergeStateStatus": "BLOCKED" if updated else "BEHIND",
                           "statusCheckRollup": [{"name": "ci", "status": "COMPLETED"}]})
    checks_at_h2 = []

    def checks(argv):
        if not fake.has("gh", "pr", "update-branch"):
            return json.dumps([{"name": "ci", "bucket": "pass"}])
        checks_at_h2.append(1)
        bucket = "pending" if len(checks_at_h2) == 1 else "pass"
        if bucket == "pending":
            err = RuntimeError("gh pr checks: exit 8")
            err.stdout, err.stderr = json.dumps([{"name": "ci", "bucket": "pending"}]), ""
            raise err
        return json.dumps([{"name": "ci", "bucket": "pass"}])

    def release_view(argv):
        raise RuntimeError("release not found")
    fake.answers = {"rev-parse origin/main": "p1\n", "rev-parse abc123^": "p2\n", "gh pr list": "[]",
                    "gh pr create": "https://github.com/O/.github/pull/700\n",
                    "gh pr view": view, "gh pr checks": checks, "diff --name-only": changed,
                    "changelog.py build": "# Changelog\n", "changelog.py notes": "notes\n", "gh release view": release_view}
    return fake


def index(fake, *prefix):
    return [i for i, c in enumerate(fake.calls) if c[:len(prefix)] == prefix]


def tags(fake):
    return [c for c in fake.calls if c[3:4] == ("tag",)]


def test_merge_when_checked_updates_a_behind_pull_request_and_merges_its_new_head():
    fake = behind_run()
    sha = lane.merge_when_checked("O/.github", "700", run=fake, sleep=lambda s: None, minutes=5)
    assert sha == "abc123"
    updates = index(fake, "gh", "pr", "update-branch")
    merges = [fake.calls[i] for i in index(fake, "gh", "pr", "merge")]
    assert len(updates) == 1 and "700" in fake.calls[updates[0]]
    assert merges == [("gh", "pr", "merge", "700", "--repo", "O/.github", "--squash", "--match-head-commit", "h2")]
    # The checks at the new head were read, pending then passing, before the merge.
    merge_at = index(fake, "gh", "pr", "merge")[0]
    after = [i for i in index(fake, "gh", "pr", "checks") if updates[0] < i < merge_at]
    assert len(after) >= 2


def test_release_updates_it_and_tags_the_commit_the_scenarios_tried(tmp_path):
    fake = behind_run()
    root = str(tmp_path)
    out = lane.release(PLAN, "O/.github", run=fake, sleep=lambda s: None, minutes=5, root=root)
    assert out.get("version") == "v7.10.1" and "error" not in out
    assert fake.has("gh", "pr", "update-branch", "700")
    assert fake.has("gh", "pr", "merge", "700", "--repo", "O/.github", "--squash", "--match-head-commit", "h2")
    assert fake.has("git", "-C", root, "tag", "v7.10.1", "p1")
    assert fake.has("git", "-C", root, "tag", "-f", "v7", "p1^{commit}")
    assert not fake.has("git", "-C", root, "tag", "v7.10.1", "abc123")
    assert fake.has("gh", "release", "create", "v7.10.1")


def test_a_merge_onto_a_moved_main_that_is_not_its_changelog_alone_tags_nothing(tmp_path):
    fake = behind_run(changed="CHANGELOG.md\nscripts/autopilot.py\n")
    try:
        lane.release(PLAN, "O/.github", run=fake, sleep=lambda s: None, minutes=5, root=str(tmp_path))
        raised = ""
    except RuntimeError as err:
        raised = str(err)
    assert "nothing tagged" in raised
    assert tags(fake) == []


def test_a_head_moved_by_anyone_else_still_stops_the_lane():
    """Not behind, its check pending, then a head the lane did not ask for."""
    fake, reads = lane.Fake(), []

    def view(argv):
        reads.append(1)
        return json.dumps({"mergedAt": None, "state": "OPEN", "headRefOid": "h1" if len(reads) == 1 else "h2",
                           "mergeStateStatus": "BLOCKED", "statusCheckRollup": [{"name": "ci", "status": "IN_PROGRESS"}]})
    fake.answers = {"gh pr view": view, "gh pr checks": json.dumps([{"name": "ci", "bucket": "pending"}])}
    try:
        lane.merge_when_checked("O/.github", "700", run=fake, sleep=lambda s: None, minutes=5)
        raised = ""
    except RuntimeError as err:
        raised = str(err)
    assert "changed head" in raised
    assert not fake.has("gh", "pr", "merge") and not fake.has("gh", "pr", "update-branch")


def test_main_still_where_the_scenarios_tried_tags_the_merge_commit_as_before(tmp_path):
    fake = behind_run()
    fake.answers["rev-parse abc123^"] = "p1\n"
    root = str(tmp_path)
    lane.release(PLAN, "O/.github", run=fake, sleep=lambda s: None, minutes=5, root=root)
    assert fake.has("git", "-C", root, "tag", "v7.10.1", "abc123")
