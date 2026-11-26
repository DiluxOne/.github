"""The autopilot brings main into its branch (#549, #550, #561): the wiring
no script's --test can see, read from the workflow's file."""
import hashlib
import os
import subprocess
from pathlib import Path
from unittest import mock

import yaml

try:
    import steps  # tests/workflows/steps.py: it runs a workflow's step with stubs
except ModuleNotFoundError:  # Test first's base has no steps.py (#845): there each call to it fails an assertion
    steps = mock.Mock(**{f"{n}.side_effect": AssertionError("tests/workflows/steps.py is missing") for n in ("evaluate", "run", "step", "workflow")})

ROOT = Path(__file__).resolve().parents[2]
FLOWS = ROOT / ".github" / "workflows"
JOBS = yaml.safe_load((FLOWS / "autopilot.yml").read_text(encoding="utf-8"))["jobs"]


def step(job, sid):
    return next(s for s in JOBS[job]["steps"] if s.get("id") == sid)


def test_the_work_merges_main_before_the_agent_and_leaves_a_conflict_to_it():
    run = step("work", "task")["run"]
    names = [s.get("id") for s in JOBS["work"]["steps"]]
    assert names.index("task") < names.index("work")
    assert 'git merge -q --no-edit "origin/$DEFAULT"' in run
    # #561 C2: a conflict no longer leaves the branch as it is: the agent
    # merges main and resolves it, its prompt says so, before the prompt
    # goes out (a fix round's prompt already asks for it).
    assert "goes on from the branch as it is" not in run
    note = run.index('autopilot.py conflict-note "$DEFAULT" >> .dx-io/prompt.md')
    assert run.index("git merge --abort") < note < run.index('echo "prompt=')
    assert 'grep -q "Main does not merge cleanly" .dx-io/prompt.md' in run


def test_a_merge_into_main_sweeps_the_autopilot_pull_requests_with_no_persons_label():
    # #669: the merge reaches it from issues.yml's `autopilot-sweep` job
    # (tests/workflows/test_autopilot_sweep_on_merge.py), here as anywhere:
    # no second sweep on the push.
    pipeline = yaml.safe_load((FLOWS / "pull-request.yml").read_text(encoding="utf-8"))
    assert "autopilot-sweep" not in pipeline["jobs"]
    sweep = yaml.safe_load((FLOWS / "autopilot-sweep.yml").read_text(encoding="utf-8"))
    on = sweep.get("on", sweep.get(True))
    assert {"schedule", "workflow_call", "workflow_dispatch"} <= set(on)
    run = next(s for s in sweep["jobs"]["sweep"]["steps"] if s.get("name") == "Bring each one in step")["run"]
    # next-step's own answer decides, through autopilot.py sweep; the bot
    # acts on it: update-branch for one behind, its own continue for one
    # in conflict, which the run's fix round merges and resolves.
    assert "python3 .dx-central/scripts/autopilot.py sweep" in run
    assert 'gh api -X PUT "repos/$repo/pulls/$n/update-branch"' in run
    # #563 C12: the run it starts only catches up with another merge: free
    # (#802: `catchup` on the issue's board, set before the continue).
    assert run.index('receipts.py state set catchup=true') < run.index('gh issue edit "$issue" --repo "$repo" --add-label "autopilot:continue"')
    assert "mergeStateStatus" in run and "UNKNOWN" in run


def test_start_is_recorded_before_the_merge_and_base_after():
    run = step("work", "task")["run"]
    merge = run.index("git merge -q")
    assert run.index('echo "start=') < merge < run.index('echo "base=')


# The draft step's helpers, stood in: each records its call, and
# api-commit.py what it would push (the branch's commits onto main).
FAKE_SCRIPT = r"""import json, os, subprocess, sys
name = os.path.basename(sys.argv[0])
with open(os.environ["DX_CALLS"], "a") as fh:
    fh.write(json.dumps([name, *sys.argv[1:]]) + "\n")
args = sys.argv[1:]
if name == "autopilot.py" and args[:1] == ["draft"]:
    print(json.dumps({"branch": "fix/7-save", "title": "fix: save (#7)", "body": "Closes #7"}))
elif name == "receipts.py" and args[:2] == ["state", "get"]:
    print("null")
elif name == "api-commit.py":
    log = subprocess.run(["git", "log", "--format=%s", args[args.index("--onto") + 1] + "..HEAD"], capture_output=True, text=True).stdout
    open(os.environ["RUNNER_TEMP"] + "/pushed.txt", "w").write(log)
"""
GH = r"""case "$*" in
  *"--json comments "*) echo 0 ;;
  *"--json title "*) echo "Save fails" ;;
  "api repos/o/r/issues/7 "*) echo Bug ;;
  "pr create "*) echo https://github.com/o/r/pull/9 ;;
  "repo view "*) echo main ;;
esac"""
TEST = "tests/repro/test_issue_7.py"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **IDENTITY}, check=True, capture_output=True, text=True).stdout.strip()


def reproduced_draft(tmp_path, test_text="def test_save():\n    assert False\n", main_touches_test=False, sealed=None):
    """The draft step of a reproduced bug: origin has main, moved on since
    the reproduction branch left it, and that branch with its failing test."""
    origin, seed = tmp_path / "origin.git", tmp_path / "seed"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(seed))
    (seed / "app.txt").write_text("v1\n")
    git(seed, "add", ".")
    git(seed, "commit", "-q", "-m", "app")
    git(seed, "push", "-q", "origin", "HEAD:main")
    git(seed, "checkout", "-q", "-b", "repro/7")
    (seed / TEST).parent.mkdir(parents=True)
    (seed / TEST).write_text(test_text)
    git(seed, "add", ".")
    git(seed, "commit", "-q", "-m", "test: reproduce #7")
    git(seed, "push", "-q", "origin", "repro/7")
    git(seed, "checkout", "-q", "main")
    if main_touches_test:
        (seed / TEST).parent.mkdir(parents=True, exist_ok=True)
        (seed / TEST).write_text("other\n")
    (seed / "app.txt").write_text("v2\n")
    git(seed, "add", ".")
    git(seed, "commit", "-q", "-m", "main moved on")
    git(seed, "push", "-q", "origin", "HEAD:main")
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(origin), str(work))
    files = {f".dx-central/scripts/{n}": FAKE_SCRIPT for n in ("autopilot.py", "receipts.py", "api-commit.py", "issue-schema.py")}
    sha = hashlib.sha256(test_text.encode()).hexdigest() if sealed is None else sealed
    ran = steps.run(steps.step("autopilot.yml", "draft", job="draft"), tmp_path, central=False, files=files, stubs={"gh": GH},
                    env={"NUMBER": "7", "LANE": "bugfix-reproduced", "DEFAULT": "main", "REPRO_BRANCH": "repro/7",
                         "REPRO_TEST": TEST, "REPRO_SHA": sha, "STARTED": "", "DX_BOT_APP": "dilux-bot", **IDENTITY})
    return ran, work


def test_a_reproduced_bugs_draft_starts_at_main_and_checks_the_test_on_top(tmp_path):
    ran, work = reproduced_draft(tmp_path)
    assert ran.code == 0, ran.stdout + ran.stderr
    assert ran.output.get("branch") == "fix/7-save" and ran.output.get("pr") == "9", ran.output
    # Current main, with the reproduction's commit alone on top of it.
    assert git(work, "rev-parse", "HEAD~1") == git(work, "rev-parse", "origin/main")
    assert git(work, "show", "HEAD:app.txt") == "v2"
    assert ["api-commit.py", "push", "fix/7-save", "--onto", "origin/main"] in ran.calls
    assert (ran.temp / "pushed.txt").read_text().splitlines() == ["test: reproduce #7"]


def test_a_reproduction_test_that_is_not_the_sealed_one_opens_no_draft(tmp_path):
    ran, _ = reproduced_draft(tmp_path, sealed="0" * 64)
    assert ran.code == 0, ran.stdout + ran.stderr
    assert "is not the one the PRD sealed" in ran.output.get("why", ""), ran.output
    assert not any(c[0] == "api-commit.py" for c in ran.calls) and not any(c[:2] == ["pr", "create"] for c in ran.of("gh"))


def test_reproduction_commits_that_do_not_apply_on_main_open_no_draft(tmp_path):
    ran, work = reproduced_draft(tmp_path, main_touches_test=True)
    assert ran.code == 0, ran.stdout + ran.stderr
    assert "do not apply on main" in ran.output.get("why", ""), ran.output
    assert not (work / ".git" / "CHERRY_PICK_HEAD").exists(), "the cherry-pick is aborted"
    assert not any(c[0] == "api-commit.py" for c in ran.calls)


def test_the_workflows_guard_reads_only_the_agents_own_commits():
    run = next(s for s in JOBS["apply"]["steps"] if s.get("id") == "applied")["run"]
    assert 'git log --first-parent --no-merges --no-renames --format= --name-only "origin/$BRANCH..$new"' in run
    assert 'git diff --name-only "origin/$BRANCH" "$new"' not in run


def test_a_catch_up_run_is_counted_free():
    """#563 C12: the run the sweep's continue starts is free on the pull
    request's board, from `catchup` on the issue's, which it clears (#802,
    scripts/autopilot.py count; tests/workflows/test_autopilot_board_state.py
    walks it)."""
    wf = yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))
    count = next(s for job in wf["jobs"].values() for s in job.get("steps", []) if s.get("name") == "Count the round or the run")
    run = count["run"]
    assert 'python3 .dx-central/scripts/autopilot.py count' in run
    # Never in a label (#805): the branch scripts older than #802 took is gone.
    assert "autopilot:" not in run and "--add-label" not in run


def test_the_hourly_sweep_still_covers_every_repository():
    """#669 C3: a merge whose sweep never ran (a caller not in step yet, or
    one that closes no issue) is still brought in step within the hour: the
    schedule passes no `repo`, so the sweep searches the whole organisation
    with the organisation's token, and it can still be run by hand."""
    sweep = yaml.safe_load((FLOWS / "autopilot-sweep.yml").read_text(encoding="utf-8"))
    on = sweep.get("on", sweep.get(True))
    assert on["schedule"] == [{"cron": "7 * * * *"}]
    assert on["workflow_dispatch"]["inputs"]["repo"]["default"] == ""
    assert on["workflow_call"]["inputs"]["repo"]["default"] == ""
    steps = sweep["jobs"]["sweep"]["steps"]
    in_step = next(s for s in steps if s.get("name") == "Bring each one in step")
    run = in_step["run"]
    assert 'else where=(--owner "$OWNER"); fi' in run
    assert in_step["env"]["OWNER"] == "${{ github.repository_owner }}"
    # No repo, no name: the App token stays the organisation's.
    where = next(s for s in steps if s.get("id") == "where")
    assert 'echo "name=${REPO#*/}"' in where["run"]
    assert next(s for s in steps if s.get("id") == "bot")["with"]["owner"] == "${{ github.repository_owner }}"
    assert sweep["concurrency"]["group"] == "autopilot-sweep-${{ inputs.repo || 'all' }}"
