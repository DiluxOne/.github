"""Issue #798: the release lane leaves its own release pull request to auto-merge.

The CHANGELOG.md floor makes every release pull request `risk:high`, and the
auto-merge decision turns auto-merge off on it, so `release()` in
scripts/release-lane.py must merge it itself, never with `--auto`, once it read
from GitHub its files, its head and the head's parent, and its required checks;
and one it gives up on must be closed with a comment that says why, with
nothing tagged. Nothing runs: `release()` gets a recording fake in place of
`git` and `gh`.
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLANNED = "a" * 40
MERGE = "b" * 40
HEAD = "c" * 40
BRANCH = "chore/release-v7.15.0"


def lane():
    spec = importlib.util.spec_from_file_location("release_lane", ROOT / "scripts" / "release-lane.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake(files=("CHANGELOG.md",), head=HEAD):
    """A release pull request labelled `risk:high`: auto-merge, if the lane
    asks for it, never merges it (it stays open), as on GitHub."""
    calls = []
    state = {"merged": False}
    answers = {
        "rev-parse origin/main": PLANNED + "\n",
        f"rev-parse {MERGE}^": PLANNED + "\n",
        "api-commit.py push": f"{BRANCH} is at {HEAD} on GitHub, signed by GitHub.\n",
        "gh pr create": "https://github.com/O/.github/pull/700\n",
        f"commits/{HEAD}": json.dumps({"sha": HEAD, "parents": [{"sha": PLANNED}]}),
        "gh pr checks": json.dumps([{"name": "review", "bucket": "pass"}]),
        "changelog.py build": "# Changelog\n",
        "changelog.py notes": "notes\n",
    }

    def run(*argv, input=None, env=None):
        argv = [str(a) for a in argv]
        calls.append(argv)
        if argv[:3] == ["gh", "pr", "merge"] and "--auto" not in argv:
            state["merged"] = True
        if argv[:3] == ["gh", "pr", "view"]:
            return json.dumps({"headRefOid": head, "baseRefName": "main", "files": [{"path": f} for f in files],
                               "labels": [{"name": "risk:high"}], "state": "MERGED" if state["merged"] else "OPEN",
                               "mergedAt": "2026-11-17T10:00:00Z" if state["merged"] else None,
                               "mergeCommit": {"oid": MERGE} if state["merged"] else None})
        line = " ".join(argv)
        for key, value in answers.items():
            if key in line:
                return value
        return ""
    return run, calls


PLAN = {"release": True, "version": "v7.15.0", "previous": "v7.14.1", "major": "v7", "breaking": False, "sha": PLANNED}


def test_a_risk_high_release_pull_request_is_merged_by_the_lane_never_by_auto_merge(tmp_path):
    run, calls = fake()
    try:
        lane().release(PLAN, "O/.github", run=run, sleep=lambda s: None, minutes=1, root=str(tmp_path))
    except RuntimeError:
        pass
    merges = [c for c in calls if c[:3] == ["gh", "pr", "merge"]]
    assert [c for c in merges if "--auto" in c] == [], "the lane waits on auto-merge, which never merges a risk:high pull request"
    assert merges == [["gh", "pr", "merge", "700", "--repo", "O/.github", "--squash", "--match-head-commit", HEAD]]
    assert ["git", "-C", str(tmp_path), "tag", "v7.15.0", MERGE] in calls, "v7.15.0 is not tagged at the merge commit"


@pytest.mark.parametrize("files,head,why", [
    (("CHANGELOG.md", ".github/x.yml"), HEAD, "`.github/x.yml`"),
    (("CHANGELOG.md",), "d" * 40, "not the lane's commit"),
])
def test_a_release_pull_request_given_up_on_is_closed_and_nothing_is_tagged(tmp_path, files, head, why):
    run, calls = fake(files, head)
    with pytest.raises(RuntimeError):
        lane().release(PLAN, "O/.github", run=run, sleep=lambda s: None, minutes=1, root=str(tmp_path))
    assert [c for c in calls if c[:3] == ["gh", "pr", "merge"]] == []
    closed = [c for c in calls if c[:4] == ["gh", "pr", "close", "700"]]
    assert len(closed) == 1 and why in closed[0][closed[0].index("--comment") + 1]
    assert [c for c in calls if c[3:4] == ["tag"]] == []
