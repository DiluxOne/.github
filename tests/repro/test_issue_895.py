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


# Still failing after #898: the review step's KIND is the policy's kind, empty
# for DiluxOne/diluxone-test (it declares none), so the exception keyed on the
# kind never applied. The step finds the fixed change the way G7 does
# (`autopilot.py fixed`, by the repository being org.yml's test repository)
# and passes its pattern with --fixed.
AUTOPILOT = ROOT / "scripts" / "autopilot.py"
WORKFLOW = ROOT / ".github" / "workflows" / "claude-review.yml"


def fixed_pattern(repository):
    env = {"PATH": "/usr/bin:/bin", "GITHUB_REPOSITORY": repository}
    out = subprocess.run(["python3", str(AUTOPILOT), "fixed"], env=env, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def step_type(repo, timeline, repository, title=TITLE):
    """The step's real inputs: an empty KIND, the title, and the pattern
    `autopilot.py fixed` prints for REPOSITORY."""
    return subprocess.run(
        ["bash", str(SCRIPT), "test", BOT, str(timeline), "", "--diff", "", "base", "head", "--title", title,
         "--fixed", fixed_pattern(repository)],
        cwd=repo, capture_output=True, text=True)


def test_the_test_repository_with_an_empty_kind_keeps_feat(tmp_path):
    repo, timeline = repo_with(tmp_path, FIXED)
    assert fixed_pattern("DiluxOne/diluxone-test") == "scenarios/{scenario}/{n}.test.md"
    out = step_type(repo, timeline, "DiluxOne/diluxone-test")
    assert out.stdout.strip() == "feat", out.stderr


def test_the_test_repository_with_another_file_keeps_the_reviews_type(tmp_path):
    repo, timeline = repo_with(tmp_path, FIXED + ["src/app.py"])
    out = step_type(repo, timeline, "DiluxOne/diluxone-test")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "test"


def test_another_repository_keeps_the_reviews_type(tmp_path):
    repo, timeline = repo_with(tmp_path, FIXED)
    assert fixed_pattern("DiluxOne/plugin") == ""
    out = step_type(repo, timeline, "DiluxOne/plugin")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "test"


def test_both_review_steps_pass_the_fixed_pattern():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("bound+=(--fixed") == 2
    assert text.count("autopilot.py fixed") >= 2
