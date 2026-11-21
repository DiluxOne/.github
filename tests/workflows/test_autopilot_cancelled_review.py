"""A review cancelled by a newer run of the same pull request (#820) is not a
failed review: the fix gate of the "may" step waits for the newer run's
review (go=false, no `needs-human`, no comment), while a review that failed
on its own at the current head, with no newer run, starts its round or
stops at the cap as before (C3). Runs the whole "may" step as the runner
does (tests/workflows/steps.py) on a fix round, with gh stood in, the
engine's other helpers answering "go on", and autopilot.py's real
`superseded` and `rounds-spent` reading what gh gives."""
import json
import sys
from pathlib import Path

from steps import run, step

ROOT = Path(__file__).resolve().parents[2]
BRANCH = "fix/7-thing"

# The engine's helpers the step calls, stood in: each records its call,
# then answers ANSWERS[subcommand] (stdout, exit code), or runs the real
# script for a subcommand in REAL.
HELPER = """import json, os, sys
with open(os.environ["DX_CALLS"], "a") as f:
    f.write(json.dumps([os.path.basename(__file__), *sys.argv[1:]]) + "\\n")
sub = sys.argv[1] if len(sys.argv) > 1 else ""
if sub in {real!r}:
    os.execv(sys.executable, [sys.executable, {path!r}, *sys.argv[1:]])
out, code = {answers!r}.get(sub, ("", 0))
if out:
    print(out)
sys.exit(code)
"""


def helper(name, answers, real=()):
    return HELPER.format(real=set(real), path=str(ROOT / "scripts" / name), answers=answers)


def may_step():
    return step("autopilot.yml", "may", job="prep")


def gate(tmp_path, *, review, run_head, pr_head, runs, round_=2):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "pr.json").write_text(json.dumps({"headRefOid": pr_head, "headRefName": BRANCH}))
    (data / "jobs.json").write_text(json.dumps([{"jobs": [
        {"name": "conventions", "conclusion": "success"}, {"name": "review / Review", "conclusion": review}]}]))
    (data / "run.json").write_text(json.dumps({"id": 5, "workflow_id": 77, "head_branch": BRANCH, "head_sha": run_head, "event": "pull_request"}))
    (data / "runs.json").write_text(json.dumps({"workflow_runs": [{"id": i, "workflow_id": 77, "event": "pull_request"} for i in runs]}))
    gh = ('case "$*" in\n'
          # The step's own read of the pull request's labels: no needs-human.
          '  "pr view"*"--json labels"*) echo false ;;\n'
          f'  "pr view"*) cat "{data}/pr.json" ;;\n'
          f'  "api repos/o/r/actions/runs/5/jobs"*) cat "{data}/jobs.json" ;;\n'
          f'  "api repos/o/r/actions/runs/5") cat "{data}/run.json" ;;\n'
          f'  "api repos/o/r/actions/workflows/77/runs"*) cat "{data}/runs.json" ;;\n'
          '  api*) exit 1 ;;\n'
          "esac\n")
    files = {
        ".dx-central/scripts/autopilot.py": helper("autopilot.py", {"lane": ("human-issue", 0), "checks-failed": ("", 0)},
                                                   real=("superseded", "rounds-spent")),
        ".dx-central/scripts/receipts.py": helper("receipts.py", {"verify-prd": ("match", 0)}),
        ".dx-central/scripts/autonomy.py": helper("autonomy.py", {"policy": (json.dumps({"autopilot-rounds": 5}), 0)}),
    }
    ran = run(may_step(), tmp_path, central=False, files=files, stubs={"gh": gh},
              env={"GITHUB_RUN_ID": "5", "MODE": "fix", "AS": "fix", "ISSUE": "7", "PR": "9", "ROUND": str(round_),
                   "QUEUE": "false", "RUN_HEAD": run_head, "OPEN_TO_CLAIM": "open", "DX_AUTOPILOT": ""})
    assert ran.code == 0, ran.stdout + ran.stderr
    return ran


def gh_calls(ran):
    return [" ".join(c) for c in ran.of("gh")]


def labels_added(ran):
    return [c[c.index("--add-label") + 1] for c in ran.of("gh") if "--add-label" in c]


def comments(ran):
    return [c for c in ran.of("gh") if c[1:2] == ["comment"]]


def test_the_step_knows_the_head_its_run_checked():
    assert may_step()["env"].get("RUN_HEAD") == "${{ github.event.pull_request.head.sha }}"


def test_c1_a_review_cancelled_by_a_newer_run_waits_for_it(tmp_path):
    ran = gate(tmp_path, review="cancelled", run_head="aaa", pr_head="bbb", runs=[6, 5])
    assert ran.output == {"lane": "human-issue", "go": "false"}
    assert ["superseded"] in ran.of("autopilot.py")
    assert "needs-human" not in labels_added(ran)
    assert comments(ran) == [] and not any(c[:2] == ["pr", "edit"] for c in ran.of("gh"))
    # No round is counted: the cap is never read.
    assert ran.of("autonomy.py") == [] and ["rounds-spent"] not in ran.of("autopilot.py")
    assert "waits for the newer run's review" in ran.stdout


def test_c1_even_at_the_cap_a_superseded_run_counts_no_round(tmp_path):
    ran = gate(tmp_path, review="cancelled", run_head="aaa", pr_head="bbb", runs=[6, 5], round_=6)
    assert ran.output["go"] == "false"
    assert "needs-human" not in labels_added(ran) and comments(ran) == []


def test_c1_a_cancelled_review_at_the_same_head_waits_for_the_newer_run(tmp_path):
    ran = gate(tmp_path, review="cancelled", run_head="aaa", pr_head="aaa", runs=[6, 5])
    assert ran.output["go"] == "false"
    assert "needs-human" not in labels_added(ran)
    # It read the run's jobs and the newer runs to tell.
    assert any(c.startswith("api repos/o/r/actions/workflows/77/runs") for c in gh_calls(ran))


def test_c3_a_review_that_failed_on_its_own_starts_its_round(tmp_path):
    ran = gate(tmp_path, review="failure", run_head="aaa", pr_head="aaa", runs=[5])
    assert ran.output["go"] == "true"
    assert "needs-human" not in labels_added(ran)
    assert ["superseded"] in ran.of("autopilot.py") and ["policy"] in ran.of("autonomy.py")


def test_c3_a_review_that_failed_on_its_own_stops_at_the_cap(tmp_path):
    ran = gate(tmp_path, review="failure", run_head="aaa", pr_head="aaa", runs=[5], round_=6)
    assert ran.output["go"] == "false"
    assert "pr edit 9 --repo o/r --add-label needs-human" in gh_calls(ran)
    pr_comment = [c for c in ran.of("gh") if c[:3] == ["pr", "comment", "9"]]
    assert len(pr_comment) == 1 and "spent its 5 rounds" in pr_comment[0][pr_comment[0].index("--body") + 1]
    # The issue is opened to a claim.
    assert ["issue", "comment", "7", "--repo", "o/r", "--body", "open"] in ran.of("gh")


def test_c3_a_cancelled_review_with_no_newer_run_goes_on(tmp_path):
    ran = gate(tmp_path, review="cancelled", run_head="aaa", pr_head="aaa", runs=[5])
    assert ran.output["go"] == "true"
