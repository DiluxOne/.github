"""The review's baseline after it was asked to account for every changed
file (#953 C2): a whole run of the review set (3 plays, nothing unreviewed)
finds more than the 3 of 10 known bugs the review found before, and blocks
none of its 10 clean cases. The baseline comes from review-eval.yml's run,
never written by hand."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "evals" / "review" / "baseline.json"

FOUND_BEFORE = 3  # evals/review/baseline.json before #953


def baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_c2_the_baseline_is_a_whole_run_of_the_review_set():
    base = baseline()
    assert base["plays"] == 3, base
    assert base["unreviewed"] == 0, base
    assert base["flag"] == 10 and base["clean"] == 10, base


def test_c2_the_review_finds_more_known_bugs_than_before():
    base = baseline()
    assert base["found"] > FOUND_BEFORE, f"the review finds {base['found']} of {base['flag']}, not more than {FOUND_BEFORE}"
    assert base["found"] <= base["flag"], base


def test_c2_the_review_blocks_no_clean_case():
    assert baseline()["blocked"] == 0, baseline()
