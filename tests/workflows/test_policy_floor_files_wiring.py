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


def test_an_unlistable_change_is_a_high_floor_not_a_failed_job(tmp_path):
    """C3: with pr-files.py the step no longer exits on an empty or partial
    list; policy.py's reason for an empty one reaches the summary's
    `Policy floor` line."""
    step = policy_step()
    run = step["run"]
    assert run.rstrip().endswith("python3 .dx-central/scripts/policy.py")
    assert step["env"]["HEAD"] == "${{ github.event.pull_request.head.sha }}"
    assert "no changed files could be listed" in (ROOT / "scripts/policy.py").read_text(encoding="utf-8")
    summary = [s for s in review_steps() if "Policy floor: $FLOOR ($REASONS)" in s.get("run", "")]
    assert summary, "no step prints the floor's reasons"
    for s in summary:
        assert s["env"]["REASONS"] == "${{ steps.policy.outputs.reasons }}"
        assert s["env"]["FLOOR"] == "${{ steps.policy.outputs.floor }}"
    # The files API still lists nothing: the step hands policy.py no files
    # and goes on, never a failed job.
    r = run_step(tmp_path, with_pr_files=True, listed=[], total="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FILES=" in r.stdout.splitlines()


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


def test_an_older_central_ref_falls_back_to_the_listing_of_before(tmp_path):
    """C5: without pr-files.py the step says so and reads the files API
    once; a list shorter than the pull request's total fails the step, and
    a rename hands policy.py both its paths."""
    r = run_step(tmp_path / "partial", with_pr_files=False, listed=[{"filename": "docs/new.md"}], total="2")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "::notice::No pr-files.py at this central-ref" in r.stdout
    assert "listed 1 of the pull request's 2 changed files" in r.stdout
    assert "FILES=" not in r.stdout
    r = run_step(tmp_path / "rename", with_pr_files=False, listed=[{"filename": "docs/new.md", "previous_filename": "docs/old.md"}], total="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FILES=docs/new.md,docs/old.md" in r.stdout


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


def run_step(tmp, with_pr_files, listed=None, total="1"):
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
    listed = [{"filename": "docs/new.md"}] if listed is None else listed
    (stub / "files.json").write_text(json.dumps([listed]), encoding="utf-8")
    (stub / "total").write_text(f"{total}\n", encoding="utf-8")
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
