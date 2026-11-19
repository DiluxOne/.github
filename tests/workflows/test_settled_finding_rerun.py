"""A settled finding re-runs the review even while the review's run is still
going (#882): review-reply.yml's "Re-run the review on a settled finding"
step finds the head's review check whatever its status, waits (bounded) for
its workflow run to complete, and only then asks GitHub to re-run its failed
jobs. A run that never completes within the bound fails the step with
`::error::`; a review that did not block at the head stays a quiet exit.
Runs the step as the runner does (tests/workflows/steps.py), with `gh`,
`deciders.py` and `sleep` stood in."""
import json

from steps import run, step

HEAD = "a" * 40
BOT = "dilux-bot[bot]"
RUN = 55

# deciders.py stood in: the commenter decides.
DECIDERS = "import sys\nsys.exit(0)\n"

# `gh` stood in: answers from files in DATA, applying `--jq` as gh does, and
# answers the review run's status from the next line of statuses.txt (the
# last line once they run out).
GH = r"""data="{data}"
q=""; prev=""
for a in "$@"; do [ "$prev" = --jq ] && q=$a; prev=$a; done
emit() {{ if [ -n "$q" ]; then jq -r "$q" "$1"; else cat "$1"; fi; }}
case "$*" in
  "pr view"*closingIssuesReferences*) echo "" ;;
  "pr view"*headRefOid*) echo "{head}" ;;
  "api repos/o/r/issues/9/comments"*) emit "$data/comments.json" ;;
  "api repos/o/r/commits/{head}/check-runs"*) emit "$data/checks.json" ;;
  "api -X POST repos/o/r/actions/runs/{run}/rerun-failed-jobs"*) echo "{{}}" ;;
  "api repos/o/r/actions/runs/{run}"*)
    n=$(cat "$data/polls" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$data/polls"
    s=$(sed -n "${{n}}p" "$data/statuses.txt"); [ -n "$s" ] || s=$(tail -1 "$data/statuses.txt")
    printf '{{"id": {run}, "status": "%s"}}\n' "$s" > "$data/run.json"
    emit "$data/run.json" ;;
  *) echo "unexpected gh $*" >&2; exit 1 ;;
esac
"""


def rerun_step():
    return step("review-reply.yml", "Re-run the review on a settled finding")


def play(tmp_path, *, statuses, blocking=True, check_status="in_progress"):
    data = tmp_path / "data"
    data.mkdir()
    record = json.dumps({"sha": HEAD, "blocking": blocking})
    (data / "comments.json").write_text(json.dumps([
        {"user": {"login": BOT}, "body": f"<!-- dx-review -->\nSummary\n<!-- dx-review-record {record} -->"}]))
    (data / "checks.json").write_text(json.dumps({"check_runs": [
        {"name": "test / Claude review", "status": check_status,
         "details_url": f"https://github.com/o/r/actions/runs/{RUN}/job/1"}]}))
    (data / "statuses.txt").write_text("\n".join(statuses) + "\n")
    gh = GH.format(data=data, head=HEAD, run=RUN)
    return run(rerun_step(), tmp_path, central=False,
               files={".dx-central/scripts/deciders.py": DECIDERS},
               stubs={"gh": gh, "sleep": "exit 0"},
               env={"GH_TOKEN": "t", "PR": "9", "LOGIN": "maintainer", "BOT": BOT})


def gh_calls(ran):
    return [" ".join(c) for c in ran.of("gh")]


def rerun_posted(ran):
    return [i for i, c in enumerate(gh_calls(ran)) if c.startswith(f"api -X POST repos/o/r/actions/runs/{RUN}/rerun-failed-jobs")]


def polls(ran):
    return [i for i, c in enumerate(gh_calls(ran)) if c.startswith(f"api repos/o/r/actions/runs/{RUN}")]


def test_rerun_waits_for_an_in_progress_review_run_then_posts(tmp_path):
    ran = play(tmp_path, statuses=["in_progress", "completed"])
    assert ran.code == 0, ran.stdout + ran.stderr
    posted = rerun_posted(ran)
    assert len(posted) == 1, gh_calls(ran)
    seen = polls(ran)
    assert len(seen) == 2, gh_calls(ran)
    # Posted only after the run reported `completed` (the second poll).
    assert posted[0] > seen[1], gh_calls(ran)
    assert ran.of("sleep"), "the step waits between polls"


def test_a_run_that_never_completes_fails_the_step_without_a_rerun(tmp_path):
    ran = play(tmp_path, statuses=["in_progress"])
    assert ran.code != 0
    assert "::error::" in ran.stdout + ran.stderr
    assert not rerun_posted(ran), gh_calls(ran)


def test_a_review_that_did_not_block_still_exits_quietly(tmp_path):
    ran = play(tmp_path, statuses=["completed"], blocking=False)
    assert ran.code == 0, ran.stdout + ran.stderr
    assert not rerun_posted(ran)
    assert "::error::" not in ran.stdout + ran.stderr
