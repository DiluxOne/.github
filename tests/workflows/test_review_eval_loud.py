"""The review's evaluation fails loudly where it used to guess (#930): a
policy it cannot read, or whose `review-eval.found-floor` is not a share,
fails the score instead of a floor of one case; criteria it cannot read
fail the case's review instead of a brief without them."""
import importlib.util
import io
import json
import subprocess
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def mod():
    spec = importlib.util.spec_from_file_location("review_eval", ROOT / "scripts" / "review-eval.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize("text", [None, "review-eval: [\n", "review-eval:\n  found-floor: high\n", "review-eval:\n  found-floor: 2\n",
                                  "review-eval:\n  found-floor: true\n", "other: 1\n", "- a\n"])
def test_an_unreadable_or_malformed_policy_fails(tmp_path, text):
    m = mod()
    path = tmp_path / "policy.yml"
    if text is not None:
        path.write_text(text)
    with pytest.raises(ValueError, match="found-floor"):
        m.found_share(str(path))


def test_a_share_is_read(tmp_path):
    m = mod()
    path = tmp_path / "policy.yml"
    path.write_text("review-eval:\n  found-floor: 0.3\n")
    assert m.found_share(str(path)) == 0.3


def test_score_fails_by_name_on_a_malformed_policy(tmp_path, monkeypatch):
    m = mod()
    pol = tmp_path / "policy.yml"
    pol.write_text("review-eval:\n  found-floor: high\n")
    monkeypatch.setattr(m, "POLICY", str(pol))
    base = tmp_path / "baseline.json"
    base.write_text(json.dumps({"found": 3, "flag": 10, "blocked": 0, "clean": 10, "unreviewed": 0, "plays": 3}))
    monkeypatch.setattr(m, "BASELINE", str(base))
    res = tmp_path / "r.json"
    res.write_text(json.dumps([{"id": f"f{i}", "expect": "flag", "plays": [True] * 3} for i in range(10)]
                              + [{"id": f"c{i}", "expect": "clean", "plays": [True] * 3} for i in range(10)]))
    for cmd in ("score", "baseline"):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = m.main([cmd, str(res)])
        assert code == 1, (cmd, out.getvalue())
        assert "found-floor" in err.getvalue(), (cmd, err.getvalue())


def test_criteria_that_cannot_be_read_fail(monkeypatch):
    m = mod()
    monkeypatch.setenv("GH_TOKEN", "")
    with pytest.raises(RuntimeError, match="o/r#7"):
        m.pr_text("o/r", 7)
    monkeypatch.setenv("GH_TOKEN", "t")

    def broken(*a):
        raise subprocess.CalledProcessError(1, ["gh", *a])
    monkeypatch.setattr(m, "gh", broken)
    with pytest.raises(RuntimeError, match="o/r#7"):
        m.pr_text("o/r", 7)


def test_an_issue_without_criteria_fails(monkeypatch):
    m = mod()
    monkeypatch.setenv("GH_TOKEN", "t")
    answers = {"pr": json.dumps({"body": "b", "closingIssuesReferences": [{"number": 5}]}), "issue": "no sections at all"}
    monkeypatch.setattr(m, "gh", lambda *a: answers[a[0]])
    real = subprocess.run

    def schema(cmd, *a, **k):
        if any(str(c).endswith("issue-schema.py") for c in cmd):
            return subprocess.CompletedProcess(cmd, 1, "", "no criteria")
        return real(cmd, *a, **k)
    monkeypatch.setattr(m.subprocess, "run", schema)
    with pytest.raises(RuntimeError, match="o/r#7"):
        m.pr_text("o/r", 7)


def test_a_pull_request_closing_no_single_issue_has_no_criteria(monkeypatch):
    m = mod()
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.setattr(m, "gh", lambda *a: json.dumps({"body": "b", "closingIssuesReferences": []}))
    assert m.pr_text("o/r", 7) == ("b", "")
