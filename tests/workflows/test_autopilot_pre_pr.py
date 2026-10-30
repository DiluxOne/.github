"""The autopilot checks before it marks a pull request ready (#479 C2): its
work step has the base its local review and `make pre-pr` read, its prompt
runs the local review's checks and then `make pre-pr` (through `autopilot.py
check`) before `finish ready`, and a change that breaks a test `make pre-pr`
runs is refused until that test passes again at the head."""
import contextlib
import importlib.util
import io
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def autopilot():
    spec = importlib.util.spec_from_file_location("autopilot", ROOT / "scripts/autopilot.py")
    ap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ap)
    return ap


def work_step():
    wf = yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))
    return next(s for s in wf["jobs"]["work"]["steps"] if s.get("id") == "work")


def test_the_work_step_gets_the_base_and_the_io_the_checks_read():
    env = work_step()["env"]
    assert env["DX_BASE"] == "${{ steps.task.outputs.base }}"
    assert env["DX_IO"].endswith("/.dx-io")


def test_the_prompt_reviews_then_runs_make_pre_pr_then_finishes():
    ap = autopilot()
    pw = ap.prompt_work("o/r", "7", "8", "feat/7-x", "x", [("C1", "a", None)], False, notes=("wordpress-plugin", ()))
    review = pw.index("scripts/local-review.sh --base \"$DX_BASE\"")
    check = pw.index(f"{ap.HELPER} check")
    ready = pw.index(f"{ap.HELPER} finish ready")
    assert review < check < ready
    assert "make pre-pr" in pw[check:ready]
    assert "refuses unless `make pre-pr` passed at HEAD" in pw


def git(d, *args):
    subprocess.run(["git", "-C", str(d), *args], check=True, capture_output=True,
                   env=dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))


def test_a_broken_test_is_refused_until_fixed_at_the_head(tmp_path, monkeypatch):
    ap = autopilot()
    repo, io_dir = tmp_path / "repo", tmp_path / "io"
    repo.mkdir()
    io_dir.mkdir()
    git(repo, "init", "-q")
    (repo / "Makefile").write_text("pre-pr:\n\t@sh test.sh\n")
    (repo / "test.sh").write_text("exit 0\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "chore: base")
    monkeypatch.chdir(repo)
    head = lambda: ap.git_out("rev-parse", "HEAD")
    quiet = contextlib.redirect_stdout(io.StringIO())
    # The change breaks the test make pre-pr runs.
    (repo / "test.sh").write_text("echo broken >&2; exit 1\n")
    git(repo, "commit", "-qam", "feat: the change (C1)")
    with quiet:
        assert ap.run_pre_pr(str(io_dir)) != 0
    assert "failed at HEAD" in ap.pre_pr_refusal(True, ap.read_mark(str(io_dir)), head())
    # Fixed and committed: still refused until make pre-pr runs at that head.
    (repo / "test.sh").write_text("exit 0\n")
    git(repo, "commit", "-qam", "fix: the test again")
    assert "not at HEAD" in ap.pre_pr_refusal(True, ap.read_mark(str(io_dir)), head())
    with contextlib.redirect_stdout(io.StringIO()):
        assert ap.run_pre_pr(str(io_dir)) == 0
    assert ap.pre_pr_refusal(True, ap.read_mark(str(io_dir)), head()) == ""
