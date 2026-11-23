"""#980 C1: a review that does not finish labels the pull request high.

The release scenario `high-risk-waits` keeps the model's review and waits
for the `risk:high` label the path floor gives it. When the reviewer ended
without a structured verdict, or answered without examining every changed
file (#953), claude-review.yml's verdict step wrote `risk=high` to its
outputs and said the pull request was "treated as high risk and blocked",
but put no label on it: the scenario waited out its limit and the release
lane released nothing. Both "did not finish" branches now set `risk:high`
and `complexity:high` as the finished path sets its labels, leave a
person's `type:*` label alone, and still fail the job."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from steps import run, step  # noqa: E402

# The labels the pull request carries before the verdict (DX_HAVE, as
# `{"labels": [{"name": ...}]}`), read through the step's own `--jq`.
GH = """
case "$*" in
  *"--json labels"*) while [ "$1" != --jq ]; do shift; done; jq -r "$2" "$DX_HAVE" ;;
  *"--json files"*) echo '[]' ;;
  *"--json title"*) echo 'fix: x' ;;
  api*) echo '[]' ;;
esac
"""
CLEAN = {"risk": "low", "complexity": "low", "blocking": False, "type": "fix", "description_matches": True, "summary": "Clean.",
         "findings": [], "lessons": [], "resolved_threads": []}


def verdict(tmp_path, out, shown=None, have=""):
    temp = tmp_path / "temp"
    temp.mkdir(parents=True, exist_ok=True)
    (temp / "open-threads.json").write_text("[]", encoding="utf-8")
    (temp / "previous.json").write_text("{}", encoding="utf-8")
    if shown is not None:
        (temp / "shown-files.txt").write_text("".join(f"{f}\n" for f in shown), encoding="utf-8")
    names = [n for n in have.split(",") if n]
    (tmp_path / "have").write_text(json.dumps({"labels": [{"name": n} for n in names]}), encoding="utf-8")
    env = {"OUT": out, "MODE": "full", "PR": "8", "BOT": "dilux-bot[bot]", "SHA": "a" * 40,
           "FLOOR": "high", "REASONS": "a workflow", "TRUSTED": "true", "COUNT": "0", "LAST": "", "MODEL": "claude-opus-5-5",
           "MAX_AUTO": "5", "KIND": "", "BASE": "c" * 40, "BODY": "the description", "EXECUTION_FILE": "", "VERIFY_EXECUTION_FILE": "",
           "GITHUB_SERVER_URL": "https://github.com", "DX_HAVE": str(tmp_path / "have")}
    return run(step("claude-review.yml", "verdict"), tmp_path, env=env, stubs={"gh": GH})


def edits(ran, flag):
    """The labels each `gh pr edit FLAG` call named, flattened."""
    return [l for c in ran.of("gh") if c[:2] == ["pr", "edit"] and flag in c for l in c[c.index(flag) + 1].split(",")]


def assert_labelled_high(ran):
    assert ran.code == 1, ran.stderr[-2000:]
    assert ran.output.get("risk") == "high" and ran.output.get("blocking") == "true", ran.output
    added = edits(ran, "--add-label")
    assert "risk:high" in added and "complexity:high" in added, (added, ran.stderr[-2000:])
    # The labels exist before they are put on.
    created = [c[2] for c in ran.of("gh") if c[:2] == ["label", "create"]]
    assert "risk:high" in created and "complexity:high" in created, created


def test_c1_no_structured_verdict_labels_the_pull_request_high(tmp_path):
    ran = verdict(tmp_path, "")
    assert_labelled_high(ran)


def test_c1_an_answer_that_misses_a_file_labels_the_pull_request_high(tmp_path):
    out = dict(CLEAN, examined=[{"file": "a.py", "checked": "its callers"}])
    ran = verdict(tmp_path, json.dumps(out), shown=["a.py", "lib/b.py"])
    assert_labelled_high(ran)


def test_c1_an_unfinished_review_replaces_stale_risk_but_keeps_the_type(tmp_path):
    ran = verdict(tmp_path, "", have="risk:low,complexity:low,type:docs,review:full")
    assert_labelled_high(ran)
    removed = edits(ran, "--remove-label")
    assert set(removed) == {"risk:low", "complexity:low"}, removed
    # A person's type:* label, and a review:full still asked for, stay.
    assert not any(l.startswith("type:") for l in edits(ran, "--add-label") + removed)


def test_c1_the_finished_path_keeps_its_labels(tmp_path):
    out = dict(CLEAN, examined=[{"file": "a.py", "checked": "x"}])
    ran = verdict(tmp_path, json.dumps(out), shown=["a.py"], have="risk:low,complexity:low,review:full")
    assert ran.code == 0, ran.stderr[-2000:]
    assert set(edits(ran, "--add-label")) == {"risk:high", "type:fix"}
    assert set(edits(ran, "--remove-label")) == {"risk:low", "review:full"}
