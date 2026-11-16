"""Issue #780: the release lane's release commit is refused, unsigned.

`release()` in scripts/release-lane.py must put the release pull request's
branch on GitHub through scripts/api-commit.py (GitHub signs that commit),
never with `git push` (the organisation's ruleset refuses an unsigned commit).
Nothing runs: `release()` gets a recording fake in place of `git` and `gh`.
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLANNED = "a" * 40


def lane():
    spec = importlib.util.spec_from_file_location("release_lane", ROOT / "scripts" / "release-lane.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_release_branch_is_made_through_api_commit_and_never_pushed_with_git(tmp_path):
    mod = lane()
    calls = []
    answers = {
        "rev-parse origin/main": PLANNED + "\n",
        f"rev-parse {'b' * 40}^": PLANNED + "\n",
        "gh pr create": "https://github.com/O/.github/pull/700\n",
        "gh pr view": json.dumps({"mergedAt": "2026-11-16T10:00:00Z", "mergeCommit": {"oid": "b" * 40}, "state": "MERGED"}),
        "changelog.py build": "# Changelog\n",
        "changelog.py notes": "notes\n",
    }

    def fake(*argv, input=None, env=None):
        calls.append([str(a) for a in argv])
        line = " ".join(str(a) for a in argv)
        for key, value in answers.items():
            if key in line:
                return value
        return ""

    plan = {"release": True, "version": "v7.14.0", "previous": "v7.13.0", "major": "v7", "breaking": False, "sha": PLANNED}
    mod.release(plan, "O/.github", run=fake, sleep=lambda s: None, root=str(tmp_path))

    branch = "chore/release-v7.14.0"
    git_pushes_of_the_branch = [
        c for c in calls
        if c[0] == "git" and "push" in c and any(a == f"refs/heads/{branch}" or a.endswith(f":refs/heads/{branch}") or a == branch for a in c)
    ]
    assert git_pushes_of_the_branch == [], "the release commit is pushed with git, unsigned"

    api = [c for c in calls if any(a.endswith("api-commit.py") for a in c)]
    assert any("push" in c and branch in c and "--onto" in c for c in api), "the branch is not made by api-commit.py push --onto"
