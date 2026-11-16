"""#720: the review's type:docs and the conventions check's docs-only rule
contradict each other on a diff that has a doc and a test.

scripts/conventions.sh rejects a docs title when any file is outside
`scripts/surface.py --docs-paths <kind>`. The review must bound the type it
labels (and the bot puts in the title) by the same paths, so a diff with a
file outside them is never type:docs.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_the_review_does_not_label_docs_a_diff_with_a_file_outside_the_docs_paths():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "claude-review.yml").read_text(encoding="utf-8"))
    steps = {step.get("name"): step for step in wf["jobs"]["review"]["steps"]}
    verdict = steps["Verdict (labels, summary, result)"]["run"]
    retitle = steps["Correct the title's type"]["run"]
    type_reading = (ROOT / "scripts" / "review-type.sh").read_text(encoding="utf-8")
    # Wherever the type is decided (the verdict, the title step or the script
    # both call), the same docs paths the conventions check uses must bound it.
    decided_with_docs_paths = [text for text in (verdict, retitle, type_reading) if "--docs-paths" in text]
    assert decided_with_docs_paths, "nothing that sets the review's type reads `surface.py --docs-paths`"
