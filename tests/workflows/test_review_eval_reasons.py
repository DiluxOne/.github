"""Why the review found each flag case or not (#930 C3): every play keeps
its reason (found; a finding in the file outside the fixed lines, with its
distance; one rejected by verification; no finding in the file; not
reviewed), and the score table gives each flag case its reasons."""
import importlib.util
import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CASE = {"id": "o/r#1:flag", "expect": "flag", "path": "a.py", "line": 10, "fixed": [[10, 12]]}


def mod():
    spec = importlib.util.spec_from_file_location("review_eval", ROOT / "scripts" / "review-eval.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def finding(line, sev="major", file="a.py", **k):
    return {"severity": sev, "file": file, "line": line, "title": "t", **k}


@pytest.mark.parametrize("review,want", [
    ({"findings": [finding(11)]}, "found"),
    ({"findings": [finding(4), finding(15)]}, "outside the fixed lines, 3 lines away"),
    ({"findings": [finding(11, "minor", rejected="the caller checks it")]}, "rejected by verification"),
    ({"findings": [finding(11, file="b.py"), finding(11, "minor")]}, "no finding in the file"),
    ({"findings": []}, "no finding in the file"),
    (None, "not reviewed"),
])
def test_each_reason(review, want):
    m = mod()
    assert hasattr(m, "reason"), "review-eval.py has no reason()"
    assert m.reason(CASE, review) == want


def test_the_reason_agrees_with_the_verdict():
    m = mod()
    assert hasattr(m, "reason"), "review-eval.py has no reason()"
    for review in ({"findings": [finding(11)]}, {"findings": [finding(4)]}, None):
        assert (m.reason(CASE, review) == "found") == bool(m.verdict(CASE, review))


def run_main(m, argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = m.main(argv)
    return code, out.getvalue()


def test_the_score_table_gives_each_flag_case_its_reasons(tmp_path, monkeypatch):
    m = mod()
    base = tmp_path / "baseline.json"
    base.write_text(json.dumps({"found": 0, "flag": 10, "blocked": 0, "clean": 10, "unreviewed": 0, "plays": 3}))
    monkeypatch.setattr(m, "BASELINE", str(base))
    reasons = ["found", "outside the fixed lines, 3 lines away", "rejected by verification", "no finding in the file", "not reviewed"]
    runs = []
    for p in range(3):
        run = [{"id": f"f{i}", "expect": "flag", "plays": [True if reasons[i % 5] == "found" else None if reasons[i % 5] == "not reviewed" and p == 0 else False],
                "why": [reasons[i % 5] if not (reasons[i % 5] == "not reviewed" and p) else "no finding in the file"]} for i in range(10)]
        run += [{"id": f"c{i}", "expect": "clean", "plays": [True], "why": [""]} for i in range(10)]
        f = tmp_path / f"results-{p}.json"
        f.write_text(json.dumps(run))
        runs.append(str(f))
    _, out = run_main(m, ["score", *runs])
    assert "| Why |" in out.splitlines()[0] or "Why" in out.splitlines()[0], out.splitlines()[0]
    rows = {line.split("|")[1].strip(): line for line in out.splitlines() if line.startswith("| f")}
    assert len(rows) == 10
    assert "found" in rows["f0"].split("|")[-2]
    assert "outside the fixed lines, 3 lines away" in rows["f1"]
    assert "rejected by verification" in rows["f2"]
    assert "no finding in the file" in rows["f3"]
    assert "not reviewed" in rows["f4"]


def test_merge_keeps_each_play_reason():
    m = mod()
    got = m.merge([[{"id": "1", "expect": "flag", "plays": [True], "why": ["found"]}],
                   [{"id": "1", "expect": "flag", "plays": [False], "why": ["no finding in the file"]}]])
    assert got[0].get("why") == ["found", "no finding in the file"]


def test_run_records_each_play_reason(tmp_path, monkeypatch):
    m = mod()
    assert hasattr(m, "WHY"), "review-eval.py keeps no play's reason (WHY)"
    cases = [{"id": f"f{i}", "expect": "flag"} for i in range(10)] + [{"id": f"c{i}", "expect": "clean"} for i in range(10)]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases))
    monkeypatch.setattr(m, "CASES", str(path))
    monkeypatch.setattr(m, "check", lambda cases: 0)

    def fake(case, central, work):
        m.WHY[case["id"]] = "rejected by verification" if case["expect"] == "flag" else ""
        return False if case["expect"] == "flag" else True
    monkeypatch.setattr(m, "run_case", fake)
    code, out = run_main(m, ["run", "--play", "1"])
    assert code == 0
    got = json.loads(out)
    assert all(r["why"] == ["rejected by verification"] for r in got if r["expect"] == "flag")
