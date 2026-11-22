"""A flag case is found when a blocker or major of the review lands in the
case's file, inside the hunk the fix changed or within NEAR (10) lines of
the fixed lines (#930: #811 was missed by being 9 lines away). A finding in
another file, with no line, or farther away is still a miss."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CASE = {"id": "o/r#1:flag", "expect": "flag", "path": "a.py", "line": 40, "hunk": [35, 45], "fixed": [[50, 52]]}


def mod():
    spec = importlib.util.spec_from_file_location("review_eval", ROOT / "scripts" / "review-eval.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def review(line, sev="major", file="a.py", **k):
    return {"findings": [{"severity": sev, "file": file, "line": line, "title": "t", **k}]}


@pytest.mark.parametrize("line,want", [
    (51, True),   # inside the fixed lines
    (41, True),   # 9 lines before them, as #811 was
    (40, True),   # 10 lines before them
    (62, True),   # 10 lines after them
    (36, True),   # inside the hunk, 14 lines away
    (63, False),  # 11 lines after them
    (30, False),  # outside the hunk, 20 lines away
    (None, False),
])
def test_near_the_fixed_lines_is_found(line, want):
    m = mod()
    assert bool(m.verdict(CASE, review(line))) is want
    assert (m.reason(CASE, review(line)) == "found") is want


def test_another_file_or_a_minor_is_still_a_miss():
    m = mod()
    assert not m.verdict(CASE, review(51, file="b.py"))
    assert not m.verdict(CASE, review(51, sev="minor"))
    assert m.reason(CASE, review(51, file="b.py")) == "no finding in the file"


def test_a_far_miss_gives_its_distance():
    m = mod()
    assert m.reason(CASE, review(70)) == "outside the fixed lines, 18 lines away"
