"""The review set's flag cases point at a line, and the line must match (#844).

C1: `review-eval.py check` clones each case's repository and refuses, by its
name, a flag case whose line the commit that fixed it did not change. The
repository here is a local one, in place of GitHub (DX_EVAL_GIT).

C2: a review that flags another line of the same file has missed the case.
"""
import importlib.util
import inspect
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



def test_a_review_that_flags_a_far_line_of_the_same_file_missed_the_case():
    mod = load()
    c = {"expect": "flag", "path": "a.php", "line": 3}
    assert mod.verdict(c, {"findings": [{"severity": "major", "file": "a.php", "line": 3}]}) is True
    assert mod.verdict(c, {"findings": [{"severity": "major", "file": "a.php", "line": 14}]}) is False
    assert mod.verdict(c, {"findings": [{"severity": "blocker", "file": "a.php"}]}) is False
    assert mod.verdict(c, {"findings": [{"severity": "major", "file": "a.php", "line": "3"}]}) is True


# The maintainer's answer on #847: the case's line is the review thread's,
# the fix must change that thread's hunk, a docs/ci/chore/style/test fix is
# no bug, and a finding counts inside the hunk the fix changed.

def a_typed_repo(tmp_path, subject, path="a.php"):
    """o/r: path of ten lines at `head`; `fix` (subject) changes its line 3."""
    repo = tmp_path / "git" / "o" / "r"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    (repo / path).write_text("".join(f"l{n}\n" for n in range(1, 11)))
    git(repo, "add", path)
    git(repo, "commit", "-q", "-m", "head")
    head = git(repo, "rev-parse", "HEAD")
    (repo / path).write_text("".join(("L3\n" if n == 3 else f"l{n}\n") for n in range(1, 11)))
    git(repo, "commit", "-q", "-am", subject)
    return head, git(repo, "rev-parse", "HEAD")


def test_the_thread_hunk_is_read_from_its_header_on_the_head_side():
    mod = load()
    assert hasattr(mod, "thread_hunk"), "no thread_hunk in review-eval.py"
    assert mod.thread_hunk("@@ -1,4 +2,6 @@ def f():\n a\n+b\n") == (2, 7)
    assert mod.thread_hunk("@@ -5 +5 @@\n-a\n+b\n") == (5, 5)
    assert mod.thread_hunk("") is None


def test_the_fix_must_change_a_line_of_the_thread_hunk():
    mod = load()
    assert hasattr(mod, "fix_hunks") and hasattr(mod, "first_fix_in"), "no fix_hunks or first_fix_in in review-eval.py"
    diff = "@@ -3,2 +3,1 @@\n@@ -20,0 +20,2 @@\n"
    assert mod.fix_hunks(diff, (1, 8)) == [[3, 4]]
    assert mod.fix_hunks(diff, (18, 25)) == [[20, 20]]
    assert mod.fix_hunks(diff, (6, 15)) == []
    diffs = {"c2": "@@ -30 +30 @@\n", "c3": "@@ -4 +4 @@\n"}
    assert mod.first_fix_in(["c2", "c3"], (1, 8), lambda c: diffs[c]) == ("c3", [[4, 4]])
    assert mod.first_fix_in(["c2"], (1, 8), lambda c: diffs[c]) is None


def test_collect_takes_the_thread_line_and_its_hunk():
    mod = load()
    bot = {"login": mod.org.APP}
    pr = {"number": 1, "title": "fix: a", "baseRefOid": "b", "headRefOid": "h", "isCrossRepository": False,
          "commits": {"nodes": [{"commit": {"oid": x}} for x in ("c1", "c2")]},
          "reviewThreads": {"nodes": [{"isOutdated": True, "path": "s.py", "originalLine": 12, "diffSide": "RIGHT", "resolvedBy": None,
                                       "comments": {"nodes": [{"author": bot, "body": "x AI review", "diffHunk": "@@ -8,3 +10,5 @@\n", "originalCommit": {"oid": "c1"}}]}}]}}
    assert len(inspect.signature(mod.cases_from).parameters) == 4, "cases_from does not take the fix finder"
    seen = []
    flag, _ = mod.cases_from("o/r", [pr], 5, lambda pr, head, path, hunk, after: seen.append((path, hunk)) or ("c2", [[11, 12]]))
    assert seen == [("s.py", (10, 14))]
    assert [(c["path"], c["line"], c["hunk"], c["fix"], c["fixed"]) for c in flag] == [("s.py", 12, [10, 14], "c2", [[11, 12]])]
    left = json.loads(json.dumps(pr))
    left["reviewThreads"]["nodes"][0]["diffSide"] = "LEFT"
    assert mod.cases_from("o/r", [left], 5, lambda *a: ("c2", [[11, 12]]))[0] == []
    outside = json.loads(json.dumps(pr))
    outside["reviewThreads"]["nodes"][0]["originalLine"] = 30
    assert mod.cases_from("o/r", [outside], 5, lambda *a: ("c2", [[11, 12]]))[0] == []


def test_a_case_whose_fix_did_not_change_its_thread_hunk_is_refused_by_name(tmp_path):
    head, fix = a_typed_repo(tmp_path, "fix: the third line")
    ok = {**case("o/r#1:flag", head, fix, 2), "hunk": [1, 4], "fixed": [[3, 3]]}
    out_of = {**case("o/r#2:flag", head, fix, 6), "hunk": [5, 8], "fixed": [[3, 3]]}
    out = run_check(tmp_path, [ok, out_of])
    assert out.returncode == 1
    assert f"o/r#2:flag: the hunk 5-8 of a.php was not changed by {fix}" in out.stderr
    assert "o/r#1:flag" not in out.stderr


def test_a_case_whose_fix_hunk_is_not_the_one_recorded_is_refused_by_name(tmp_path):
    head, fix = a_typed_repo(tmp_path, "fix: the third line")
    out = run_check(tmp_path, [{**case("o/r#3:flag", head, fix, 2), "hunk": [1, 4], "fixed": [[2, 4]]}])
    assert out.returncode == 1
    assert "o/r#3:flag: its fixed lines" in out.stderr


def test_the_fix_type_and_a_docs_only_fix_drop_a_case():
    mod = load()
    assert hasattr(mod, "not_a_fix"), "no not_a_fix in review-eval.py"
    for s in ("docs(readme): say where", "ci: pre-pr runs strict", "chore: x", "style: y", "test: z", "docs!: w"):
        assert mod.not_a_fix(s, ["a.php"]), s
    assert mod.not_a_fix("fix: a", ["README.md", "docs/x.php", "readme.txt"])
    assert not mod.not_a_fix("fix: a", ["README.md", "a.php"])
    assert not mod.not_a_fix("feat(x)!: b", ["a.php"])
    assert not mod.not_a_fix("a commit that says nothing", ["a.php"])


def test_check_refuses_a_case_whose_fix_is_docs_by_name(tmp_path):
    head, fix = a_typed_repo(tmp_path, "docs(readme): say where the translations come from", "readme.txt")
    out = run_check(tmp_path, [{**case("o/r#26:flag", head, fix, 3, "readme.txt"), "hunk": [1, 5], "fixed": [[3, 3]]}])
    assert out.returncode == 1
    assert f"o/r#26:flag: {fix} is not a bug's fix" in out.stderr


def test_a_finding_counts_in_the_fix_hunk_or_near_the_fixed_lines_and_not_farther():
    # #930: within NEAR (10) lines of the fixed lines, or inside the hunk.
    mod = load()
    c = {"expect": "flag", "path": "s.py", "line": 12, "hunk": [10, 26], "fixed": [[20, 24]]}
    find = lambda **f: mod.verdict(c, {"findings": [{"severity": "major", **f}]})
    for n in (10, 12, 19, 20, 24, 25, 34):
        assert find(file="s.py", line=n) is True, n
    assert find(file="s.py", line=9) is False
    assert find(file="s.py", line=35) is False
    assert find(file="t.py", line=22) is False


# Review 4 of #847: a near miss of a doc name, an unreadable fix, and a
# thread hunk as wide as the file.

def test_a_doc_name_with_a_code_extension_is_code():
    mod = load()
    assert mod.is_doc("LICENSE") and mod.is_doc("readme.txt") and mod.is_doc("CHANGELOG.md")
    assert not mod.is_doc("license.php")
    assert not mod.is_doc("src/contributing.py")
    assert not mod.not_a_fix("fix: the licence check", ["license.php"])


def test_an_unreadable_fix_subject_or_file_list_is_no_fix():
    mod = load()
    assert mod.not_a_fix(None, ["a.php"]) is True
    assert mod.not_a_fix("fix: a", None) is True


def test_check_refuses_a_case_whose_fix_cannot_be_read_by_name(tmp_path, monkeypatch):
    mod = load()
    head, fix = a_typed_repo(tmp_path, "fix: the third line")
    monkeypatch.setenv("DX_EVAL_GIT", str(tmp_path / "git"))
    clones = mod.Clones(str(tmp_path / "work"))
    monkeypatch.setattr(clones, "subject", lambda repo, oid: None)
    why = mod.refused([{**case("o/r#7:flag", head, fix, 2), "hunk": [1, 4], "fixed": [[3, 3]]}], clones)
    assert why == [f"o/r#7:flag: the subject or files of {fix} cannot be read from o/r"]


def test_a_whole_file_thread_hunk_is_cut_to_the_lines_near_the_thread():
    mod = load()
    assert hasattr(mod, "near"), "no near in review-eval.py"
    assert mod.near((1, 300), 150) == (150 - mod.NEAR, 150 + mod.NEAR)
    assert mod.near((5, 8), 7) == (5, 8)
    bot = {"login": mod.org.APP}
    pr = {"number": 1, "title": "fix: a", "baseRefOid": "b", "headRefOid": "h", "isCrossRepository": False,
          "commits": {"nodes": [{"commit": {"oid": x}} for x in ("c1", "c2")]},
          "reviewThreads": {"nodes": [{"isOutdated": True, "path": "new.py", "originalLine": 150, "diffSide": "RIGHT", "resolvedBy": None,
                                       "comments": {"nodes": [{"author": bot, "body": "x AI review", "diffHunk": "@@ -0,0 +1,300 @@\n", "originalCommit": {"oid": "c1"}}]}}]}}
    seen = []
    mod.cases_from("o/r", [pr], 5, lambda pr, head, path, hunk, after: seen.append(hunk) or None)
    assert seen == [(150 - mod.NEAR, 150 + mod.NEAR)]
    # A later edit at line 3 of the new file is no fix of a thread at 150.
    assert mod.fix_hunks("@@ -3 +3 @@\n", seen[0]) == []
