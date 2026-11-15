"""The policy floor's file list (#768): claude-review.yml's "Policy floor
(deterministic)" step lists the files through scripts/pr-files.py, which
waits for a files API that lags behind a new pull request, and a list it
still cannot read reaches the review as a high floor, never a failed job."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def review_steps():
    wf = yaml.safe_load((ROOT / ".github/workflows/claude-review.yml").read_text(encoding="utf-8"))
    return wf["jobs"]["review"]["steps"]


def policy_step():
    return next(s for s in review_steps() if s.get("name") == "Policy floor (deterministic)")


def new_path(run):
    """The step's script where pr-files.py is there: up to its `else`."""
    start = run.index("if [ -f .dx-central/scripts/pr-files.py ]; then")
    return run[start:run.index("\nelse\n", start)]


def test_an_unlistable_change_is_a_high_floor_not_a_failed_job():
    """C3: with pr-files.py the step no longer exits on an empty or partial
    list; policy.py's reason for an empty one reaches the summary's
    `Policy floor` line."""
    step = policy_step()
    run = step["run"]
    branch = new_path(run)
    assert 'CHANGED_FILES="$(python3 .dx-central/scripts/pr-files.py)"' in branch
    assert "exit 1" not in branch and "LISTED" not in branch
    assert run.rstrip().endswith("python3 .dx-central/scripts/policy.py")
    assert step["env"]["HEAD"] == "${{ github.event.pull_request.head.sha }}"
    assert "no changed files could be listed" in (ROOT / "scripts/policy.py").read_text(encoding="utf-8")
    summary = [s for s in review_steps() if "Policy floor: $FLOOR ($REASONS)" in s.get("run", "")]
    assert summary, "no step prints the floor's reasons"
    for s in summary:
        assert s["env"]["REASONS"] == "${{ steps.policy.outputs.reasons }}"
        assert s["env"]["FLOOR"] == "${{ steps.policy.outputs.floor }}"


def test_the_bound_is_data_not_the_workflow():
    """C4: the bound is `files-wait` in the organisation's default policy,
    which the step hands the script; the step itself has no retry count or
    sleep."""
    import re
    default = yaml.safe_load((ROOT / "policy/review-policy.default.yml").read_text(encoding="utf-8"))
    assert set(default["files-wait"]) == {"reads", "seconds"}
    step = policy_step()
    assert step["env"]["DEFAULT_POLICY"] == ".dx-central/policy/review-policy.default.yml"
    run = step["run"]
    assert "sleep" not in run and not re.search(r"\bseq\b|\bfor\b|\bwhile\b|\buntil\b", run)
    assert "files-wait" in (ROOT / "scripts/pr-files.py").read_text(encoding="utf-8")


def test_an_older_central_ref_falls_back_to_the_listing_of_before():
    """C5: pr-files.py runs only where the central-ref has it; without it
    the step says so and keeps the files API's single read and its count
    check, as before."""
    run = policy_step()["run"]
    guard = "if [ -f .dx-central/scripts/pr-files.py ]; then"
    assert run.count("python3 .dx-central/scripts/pr-files.py") == 1 and run.index(guard) < run.index("python3 .dx-central/scripts/pr-files.py")
    fallback = run[run.index("\nelse\n", run.index(guard)):run.index("\nfi\n", run.index(guard))]
    assert "::notice::No pr-files.py at this central-ref; listing the files once, as before." in fallback
    assert 'gh api "repos/$GITHUB_REPOSITORY/pulls/$PR/files" --paginate --slurp' in fallback
    assert 'gh pr view "$PR" --repo "$GITHUB_REPOSITORY" --json changedFiles --jq .changedFiles' in fallback
    assert 'if [ "$LISTED" != "$TOTAL" ]; then' in fallback and "exit 1" in fallback
    assert "jq -r '.[][] | .filename, (.previous_filename // empty)'" in fallback


GH_STUB = """#!/bin/sh
case "$1 $2" in
  "api "*) cat "$STUB/files.json" ;;
  "pr view") cat "$STUB/total" ;;
  *) exit 2 ;;
esac
"""

# policy.py's stand-in: what the step hands it, and load_yaml for pr-files.py.
POLICY_STUB = """import os
def load_yaml(path):
    return {}
if __name__ == "__main__":
    print("FILES=" + ",".join(os.environ.get("CHANGED_FILES", "").split()))
"""


def run_step(tmp, with_pr_files):
    """The step's script, in a checkout whose head adds docs/new.md, with a
    stub `gh` whose files API lists it."""
    import json
    import os
    import shutil
    import subprocess

    work, stub = tmp / "work", tmp / "stub"
    (work / ".dx-central/scripts").mkdir(parents=True)
    stub.mkdir()
    git = lambda *a: subprocess.run(["git", "-C", str(work), *a], check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base")
    base = git("rev-parse", "HEAD")
    (work / "docs").mkdir()
    (work / "docs/new.md").write_text("new\n", encoding="utf-8")
    git("add", "docs/new.md")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "head")
    head = git("rev-parse", "HEAD")
    (work / ".dx-central/scripts/policy.py").write_text(POLICY_STUB, encoding="utf-8")
    if with_pr_files:
        shutil.copy(ROOT / "scripts/pr-files.py", work / ".dx-central/scripts/pr-files.py")
    (stub / "gh").write_text(GH_STUB, encoding="utf-8")
    (stub / "gh").chmod(0o755)
    (stub / "files.json").write_text(json.dumps([[{"filename": "docs/new.md"}]]), encoding="utf-8")
    (stub / "total").write_text("1\n", encoding="utf-8")
    env = dict(os.environ, PATH=f"{stub}{os.pathsep}{os.environ['PATH']}", STUB=str(stub), RUNNER_TEMP=str(tmp),
               GITHUB_REPOSITORY="DiluxOne/example", PR="1", BASE=base, HEAD=head,
               DEFAULT_POLICY=".dx-central/policy/review-policy.default.yml")
    return subprocess.run(["bash", "-c", policy_step()["run"]], cwd=work, env=env, capture_output=True, text=True)


def test_the_step_without_pr_files_lists_the_files_and_passes(tmp_path):
    """C5: run with main's scripts (no pr-files.py), the step lists the
    files once, says so, and exits 0."""
    r = run_step(tmp_path, with_pr_files=False)
    assert r.returncode == 0, r.stderr
    assert "FILES=docs/new.md" in r.stdout
    assert "::notice::No pr-files.py at this central-ref" in r.stdout


def test_the_step_with_pr_files_lists_the_files_through_it(tmp_path):
    r = run_step(tmp_path, with_pr_files=True)
    assert r.returncode == 0, r.stderr
    assert "FILES=docs/new.md" in r.stdout
    assert "No pr-files.py" not in r.stdout
