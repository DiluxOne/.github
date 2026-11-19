"""The review set's flag cases point at a line, and the line must match (#844).

C1: `review-eval.py check` clones each case's repository and refuses, by its
name, a flag case whose line the commit that fixed it did not change. The
repository here is a local one, in place of GitHub (DX_EVAL_GIT).

C2: a review that flags another line of the same file has missed the case.
"""
import importlib.util
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/review-eval.py"


def load():
    spec = importlib.util.spec_from_file_location("review_eval", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(repo, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout.strip()


def a_repo(tmp_path):
    """o/r: a.php of five lines at `head`; `fix` changes its line 3 alone."""
    repo = tmp_path / "git" / "o" / "r"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    (repo / "a.php").write_text("one\ntwo\nthree\nfour\nfive\n")
    git(repo, "add", "a.php")
    git(repo, "commit", "-q", "-m", "head")
    head = git(repo, "rev-parse", "HEAD")
    (repo / "a.php").write_text("one\ntwo\nTHREE\nfour\nfive\n")
    git(repo, "commit", "-q", "-am", "fix")
    fix = git(repo, "rev-parse", "HEAD")
    return head, fix


def case(id_, head, fix, line, path="a.php"):
    return {"id": id_, "repo": "o/r", "pr": 1, "title": "t", "base": head, "head": head, "expect": "flag", "path": path, "line": line, "fix": fix}


def run_check(tmp_path, cases):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases))
    env = {**os.environ, "DX_EVAL_GIT": str(tmp_path / "git")}
    return subprocess.run(["python3", str(SCRIPT), "check", str(path)], capture_output=True, text=True, env=env)


def test_a_case_whose_line_its_fix_changed_passes(tmp_path):
    head, fix = a_repo(tmp_path)
    out = run_check(tmp_path, [case("o/r#1:flag", head, fix, 3), {"id": "o/r#2:clean", "repo": "o/r", "pr": 2, "expect": "clean", "base": head, "head": head}])
    assert out.returncode == 0, out.stderr
    assert "o/r#1:flag" not in out.stderr


def test_a_case_whose_line_its_fix_did_not_change_is_refused_by_name(tmp_path):
    head, fix = a_repo(tmp_path)
    out = run_check(tmp_path, [case("o/r#1:flag", head, fix, 3), case("o/r#4:flag", head, fix, 4)])
    assert out.returncode == 1
    assert f"o/r#4:flag: line 4 of a.php was not changed by {fix}" in out.stderr
    assert "o/r#1:flag" not in out.stderr


def test_a_case_with_no_line_or_no_fix_is_refused_by_name(tmp_path):
    head, fix = a_repo(tmp_path)
    no_line = case("o/r#5:flag", head, fix, 3)
    del no_line["line"]
    no_fix = case("o/r#6:flag", head, fix, 3)
    del no_fix["fix"]
    out = run_check(tmp_path, [no_line, no_fix])
    assert out.returncode == 1
    assert "o/r#5:flag" in out.stderr and "o/r#6:flag" in out.stderr


def test_a_line_inside_a_changed_hunk_counts_and_an_addition_after_it_does_not():
    mod = load()
    assert hasattr(mod, "line_changed"), "no line_changed in review-eval.py"
    diff = "@@ -3,2 +3,2 @@\n-x\n-y\n+X\n+Y\n@@ -9,0 +10,1 @@\n+z\n"
    assert [mod.line_changed(diff, n) for n in (2, 3, 4, 5, 9, 10)] == [False, True, True, False, False, False]
    assert mod.line_changed("@@ -7 +7 @@\n-a\n+b\n", 7) is True


def test_collect_picks_the_first_commit_after_head_that_changed_the_line():
    mod = load()
    assert hasattr(mod, "first_fix"), "no first_fix in review-eval.py"
    diffs = {"c2": "@@ -8,1 +8,1 @@\n", "c3": "@@ -2,3 +2,1 @@\n", "c4": "@@ -3,1 +3,1 @@\n"}
    assert mod.first_fix(["c2", "c3", "c4"], 3, lambda c: diffs[c]) == "c3"
    assert mod.first_fix(["c2"], 3, lambda c: diffs[c]) is None



def test_a_review_that_flags_another_line_of_the_same_file_missed_the_case():
    mod = load()
    c = {"expect": "flag", "path": "a.php", "line": 3}
    assert mod.verdict(c, {"findings": [{"severity": "major", "file": "a.php", "line": 3}]}) is True
    assert mod.verdict(c, {"findings": [{"severity": "major", "file": "a.php", "line": 4}]}) is False
    assert mod.verdict(c, {"findings": [{"severity": "blocker", "file": "a.php"}]}) is False
    assert mod.verdict(c, {"findings": [{"severity": "major", "file": "a.php", "line": "3"}]}) is True
