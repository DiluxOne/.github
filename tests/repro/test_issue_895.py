"""#895: in the test repository (engine-test, `autopilot: fixed-change`), the
review typed a scenario's pull request `test` because its diff was made only
of the fixed change's files (scenarios/conventions-fix/<n>.test.md and the
pushed marker retitled.md), and the "Correct the title's type" step renamed
`feat: ...` to `test: ...`, so the scenario's `expect` (title `^feat`) could
not hold. scripts/review-type.sh must keep the title's own type for such a
pull request, and still give the review's type for any other.
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "review-type.sh"
TITLE = "feat: a greeting, retitled [conventions-fix]"
BOT = "dilux-bot[bot]"


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


def repo_with(tmp_path, files):
    """A repository whose branch `base` is empty and `head` adds FILES."""
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    git(repo, "branch", "-q", "base")
    git(repo, "checkout", "-q", "-b", "head")
    for name in files:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "head")
    timeline = tmp_path / "timeline.json"
    timeline.write_text(json.dumps([]), encoding="utf-8")
    return repo, timeline


def review_type(repo, timeline, kind, title=TITLE):
    return subprocess.run(
        ["bash", str(SCRIPT), "test", BOT, str(timeline), "", "--diff", kind, "base", "head", "--title", title],
        cwd=repo, capture_output=True, text=True)


FIXED = ["scenarios/conventions-fix/7.test.md", "scenarios/conventions-fix/retitled.md"]


def test_the_fixed_change_keeps_the_titles_type(tmp_path):
    repo, timeline = repo_with(tmp_path, FIXED)
    out = review_type(repo, timeline, "engine-test")
    assert out.stdout.strip() == "feat", out.stderr


def test_a_file_outside_the_fixed_change_keeps_the_reviews_type(tmp_path):
    repo, timeline = repo_with(tmp_path, FIXED + ["src/app.py"])
    out = review_type(repo, timeline, "engine-test")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "test"


def test_a_kind_without_a_fixed_change_keeps_the_reviews_type(tmp_path):
    repo, timeline = repo_with(tmp_path, FIXED)
    out = review_type(repo, timeline, "")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "test"
