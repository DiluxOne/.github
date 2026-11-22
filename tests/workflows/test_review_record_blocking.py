"""#928 C4: the review's record (`dx-review-record`) and its text agree on
`blocking`. The heading and the step's output take what `review-count.py
blocking` decided from the findings (#506); the record took the model's own
boolean, so a review that said "**blocking** · 1 to fix (1 major)" could
record `"blocking":false` and no fix round ran (#926's review 3). Runs
claude-review.yml's verdict step with gh stood in (tests/workflows/steps.py)."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from steps import run, step  # noqa: E402

MAJOR = {"severity": "major", "file": "scripts/x.py", "line": 3, "title": "the guard is inverted", "detail": "d"}
OUT = {"risk": "medium", "complexity": "low", "blocking": False, "type": "fix", "description_matches": True, "summary": "One major.",
       "findings": [MAJOR], "lessons": [], "resolved_threads": []}

GH = """
case "$*" in
  *"--json files"*) echo '[]' ;;
  *"--json title"*) echo 'fix: x' ;;
  *"--json labels"*) echo '' ;;
  api*) echo '[]' ;;
esac
"""


def verdict(tmp_path, mode="full", out=None, previous=None):
    temp = tmp_path / "temp"
    temp.mkdir(parents=True, exist_ok=True)
    (temp / "open-threads.json").write_text("[]", encoding="utf-8")
    if previous is not None:
        (temp / "previous.json").write_text(json.dumps(previous), encoding="utf-8")
    env = {"OUT": json.dumps(out if out is not None else OUT), "MODE": mode, "PR": "8", "BOT": "dilux-bot[bot]", "SHA": "a" * 40,
           "FLOOR": "low", "REASONS": "none", "TRUSTED": "true", "COUNT": "2", "LAST": "b" * 40, "MODEL": "claude-opus-5-5",
           "MAX_AUTO": "5", "KIND": "", "BASE": "c" * 40, "BODY": "the description", "EXECUTION_FILE": "", "VERIFY_EXECUTION_FILE": ""}
    return run(step("claude-review.yml", "verdict"), tmp_path, env=env, stubs={"gh": GH})


def posted(ran):
    bodies = [c[c.index("--body") + 1] for c in ran.of("gh") if c[:2] == ["pr", "comment"]]
    bodies += [c[-1][len("body="):] for c in ran.of("gh") if c[:3] == ["api", "-X", "PATCH"]]
    assert bodies, ran.stderr[-2000:]
    return bodies[-1]


def record(body):
    m = re.search(r"<!-- dx-review-record (.*?) -->", body)
    assert m, body
    return json.loads(m.group(1))


def test_c4_a_review_that_lists_a_major_finding_records_blocking_true(tmp_path):
    ran = verdict(tmp_path)
    body = posted(ran)
    assert "**blocking**" in body and "1 to fix" in body
    assert ran.output.get("blocking") == "true"
    assert record(body)["blocking"] is True, record(body)
    assert ran.code == 1


def test_c4_a_review_with_only_minors_records_blocking_false(tmp_path):
    minor = dict(OUT, blocking=True, findings=[dict(MAJOR, severity="minor")])
    ran = verdict(tmp_path, out=minor)
    body = posted(ran)
    assert "**blocking**" not in body
    assert record(body)["blocking"] is False
    assert ran.output.get("blocking") == "false" and ran.code == 0


def test_c4_a_reused_record_written_wrong_before_reads_right(tmp_path):
    # A record written before this fix: false, with a major to fix.
    old = {"risk": "medium", "complexity": "low", "blocking": False, "type": "fix", "description_matches": True,
           "text": "", "findings": [{k: v for k, v in MAJOR.items() if k != "detail"}], "sha": "a" * 40}
    ran = verdict(tmp_path, mode="reuse", previous=old)
    assert ran.output.get("blocking") == "true", (ran.output, ran.stderr[-1500:])
    assert ran.code == 1
