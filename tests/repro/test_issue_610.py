"""#610: the release lane's candidate commit is unsigned and refused.

The organisation's ruleset "org: signed commits" refuses any commit that is
not verified, on every branch. The "Candidate at v7-next" step of
release-lane.yml runs `release-lane.py candidate`, so the commit is made there:
it must go through the API with the App's token (scripts/api-commit.py, which
GitHub signs), never `git commit` and `git push` of a commit made in the
runner.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CALLER = """on:
  workflow_call:
jobs:
  a:
    uses: O/.github/.github/workflows/autopilot.yml@v7
"""


def load_release_lane():
    spec = importlib.util.spec_from_file_location("release_lane", ROOT / "scripts" / "release-lane.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_candidate_is_not_a_commit_made_and_pushed_from_the_runner(tmp_path):
    lane = load_release_lane()
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "caller.yml").write_text(CALLER, encoding="utf-8")
    calls = []

    def record(*argv, input=None, env=None):
        calls.append(argv)
        return ""

    lane.candidate("O/.github", "v7", root=str(tmp_path), run=record)

    words = [[str(a) for a in call] for call in calls]
    commits = [call for call in words if "commit" in call and "git" in call[:1]]
    branch_pushes = [call for call in words if call[:1] == ["git"] and "push" in call and any(a.startswith("HEAD:refs/heads/") for a in call)]
    assert not commits, f"the candidate is committed in the runner, unsigned: {commits}"
    assert not branch_pushes, f"the candidate's commit is pushed from the runner, unsigned: {branch_pushes}"
