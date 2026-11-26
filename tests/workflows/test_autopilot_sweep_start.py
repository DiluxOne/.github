"""The hourly sweep starts an accepted issue whose start was missed (#1002
C3, C4). An accepted issue the autopilot holds (nobody claimed it), with no
run queued or in progress, no open pull request and no stop waiting on a
person, gets dilux-bot's `autopilot:continue` (a continue with no pull
request is a start, and opens the draft when the Spec is there), once:
`swept_start` goes on its board first and the sweep never clears it. One
whose autopilot pull request a person closed unmerged is left (the
maintainer's answer on #1003: the sweep recovers a missed start, never
undoes a decision). next-step (scripts/autopilot.py) is the one judge of
the issue's next phase; `sweep start` adds what only the sweep knows."""
import json
from pathlib import Path
from unittest import mock

try:
    import steps  # tests/workflows/steps.py: it runs a workflow's step with stubs
except ModuleNotFoundError:  # pragma: no cover
    steps = mock.Mock(**{f"{n}.side_effect": AssertionError("tests/workflows/steps.py is missing") for n in ("run", "step")})

import importlib.util

ROOT = Path(__file__).resolve().parents[2]
REAL = str(ROOT / "scripts" / "autopilot.py")


def load():
    spec = importlib.util.spec_from_file_location("autopilot_1002_sweep", REAL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


autopilot = load()

# The central scripts stood in, but for next-step and `sweep start`, which
# are the real ones: each call is logged; the board, the hold, the seal, the
# runs come from the environment the test sets.
CENTRAL = """import json, os, runpy, sys
cmd = sys.argv[1:]
open(os.path.join(os.environ["RUNNER_TEMP"], "central.log"), "a").write(os.path.basename(sys.argv[0]) + " " + " ".join(cmd) + "\\n")
open(os.environ["DX_CALLS"], "a").write(json.dumps([os.path.basename(sys.argv[0])] + cmd) + "\\n")
board = json.loads(os.environ.get("FAKE_BOARD") or "{}")
if cmd[:1] == ["next-step"] or cmd[:2] == ["sweep", "start"]:
    sys.argv = [REAL] + cmd
    runpy.run_path(REAL, run_name="__main__")
elif cmd[:2] == ["state", "get"]:
    if os.environ.get("FAKE_BOARD_FAILS"):
        sys.exit(1)
    print(json.dumps(board if len(cmd) == 2 else board.get(cmd[2])))
elif cmd[:2] == ["state", "set"]:
    pass
elif cmd[:1] == ["lane"]:
    print("human-issue")
elif cmd[:1] == ["holder"]:
    held = os.environ.get("FAKE_HOLDER", "")
    print(held or "nobody holds it")
    sys.exit(1 if held else 0)
elif cmd[:1] == ["verify-prd"]:
    print("match")
elif cmd[:1] == ["may-start"]:
    print("ready")
elif cmd[:1] == ["taken"]:
    sys.exit(0)
elif cmd[:1] == ["runs-busy"]:
    if os.environ.get("FAKE_RUNS_FAIL"):
        sys.exit(1)
    print(os.environ.get("FAKE_RUNS", ""), end="")
"""

PRD = "### Problem\n\nx\n\n### Scope\n\n- y\n\n### Spec: approach\n\nz\n"


def sweep(tmp_path, labels=("accepted",), closed="[]", **env):
    """The sweep's missed-start step on o/r#9, an accepted issue with its
    Spec; CLOSED is `gh pr list --state all --label autopilot`'s JSON for o/r."""
    files = {".dx-central/scripts/autopilot.py": f"REAL = {REAL!r}\n" + CENTRAL,
             ".dx-central/scripts/receipts.py": f"REAL = {REAL!r}\n" + CENTRAL}
    tmp_path.mkdir(parents=True, exist_ok=True)
    issue = {"body": PRD, "labels": [{"name": l} for l in labels]}
    (tmp_path / "issue.json").write_text(json.dumps(issue))
    (tmp_path / "closed.json").write_text(closed)
    gh = ('case "$*" in\n'
          '  "search issues"*"--label accepted "*) echo "o/r 9" ;;\n'
          '  "search issues"*) ;;\n'
          f'  "issue view 9"*) cat {tmp_path / "issue.json"} ;;\n'
          f'  "pr list"*) cat {tmp_path / "closed.json"} ;;\n'
          "esac\n")
    s = steps.step("autopilot-sweep.yml", "Start a missed one", job="sweep")
    ran = steps.run(s, tmp_path, central=False, files=files, stubs={"gh": gh, "sleep": ""},
                    env=dict({"REPO": "o/r", "OWNER": "o", "GH_TOKEN": "t"}, **env))
    log = (ran.temp / "central.log").read_text().splitlines() if (ran.temp / "central.log").exists() else []
    return ran, log


def continued(ran):
    return [c for c in ran.of("gh") if c[:2] == ["issue", "edit"] and "autopilot:continue" in c]


def marked(log):
    return [c for c in log if c.startswith("receipts.py state set swept_start=") and c != "receipts.py state set swept_start="]


def test_a_missed_start_is_started_once(tmp_path):
    ran, log = sweep(tmp_path)
    assert ran.code == 0, ran.stdout + ran.stderr
    assert continued(ran) == [["issue", "edit", "9", "--repo", "o/r", "--add-label", "autopilot:continue"]], ran.stdout
    assert len(marked(log)) == 1
    # The key goes on before the label.
    order = [c[0] for c in ran.calls if c[:3] == ["receipts.py", "state", "set"] or (c[:3] == ["gh", "issue", "edit"])]
    assert order == ["receipts.py", "gh"], ran.calls
    assert "o/r#9: a missed start: it starts" in ran.stdout


def test_the_key_on_the_board_starts_nothing_again(tmp_path):
    ran, log = sweep(tmp_path, FAKE_BOARD='{"swept_start": "2026-11-26T10:07:00Z"}')
    assert ran.code == 0, ran.stdout + ran.stderr
    assert not continued(ran) and not marked(log), ran.stdout


def test_a_run_queued_or_in_progress_or_unreadable_starts_nothing(tmp_path):
    for i, env in enumerate(({"FAKE_RUNS": "4242\n"}, {"FAKE_RUNS_FAIL": "1"})):
        ran, log = sweep(tmp_path / str(i), **env)
        assert ran.code == 0, ran.stdout + ran.stderr
        assert not continued(ran) and not marked(log), (env, ran.stdout)


def test_a_wait_on_the_core_or_the_rate_limit_is_the_sweeps_other_pass(tmp_path):
    for i, board in enumerate(({"core_wait": ["scripts/x.py"]}, {"core_started": "t"}, {"rate_limited": 1})):
        ran, log = sweep(tmp_path / str(i), FAKE_BOARD=json.dumps(board))
        assert not continued(ran) and not marked(log), (board, ran.stdout)


def test_a_draft_a_person_closed_is_left(tmp_path):
    # The maintainer's answer: a closed autopilot pull request that closes
    # it, unmerged, is a person's decision, not a missed start.
    closed = json.dumps([{"number": 12, "body": "Closes #9.", "state": "CLOSED", "mergedAt": None}])
    ran, log = sweep(tmp_path, closed=closed)
    assert ran.code == 0, ran.stdout + ran.stderr
    assert not continued(ran) and not marked(log), ran.stdout
    # Another issue's, or a merged one's, does not hold it.
    other = json.dumps([{"number": 12, "body": "Closes #90.", "state": "CLOSED", "mergedAt": None},
                        {"number": 13, "body": "Closes #9.", "state": "MERGED", "mergedAt": "2026-11-01T00:00:00Z"}])
    ran, log = sweep(tmp_path / "other", closed=other)
    assert len(continued(ran)) == 1, ran.stdout


def test_an_open_autopilot_draft_is_its_own_flow_s(tmp_path):
    # `taken` leaves the autopilot's own draft out (#696): the sweep reads it.
    ran, log = sweep(tmp_path, closed=json.dumps([{"number": 12, "body": "Closes #9", "state": "OPEN", "mergedAt": None}]))
    assert ran.code == 0, ran.stdout + ran.stderr
    assert not continued(ran) and not marked(log), ran.stdout
    assert "its autopilot pull request is open" in ran.stdout


def test_unreadable_pull_requests_start_nothing(tmp_path):
    ran, log = sweep(tmp_path, closed="boom")
    assert ran.code == 0, ran.stdout + ran.stderr
    assert not continued(ran) and not marked(log), ran.stdout


def test_the_closed_pull_requests_are_read_once_per_repository(tmp_path):
    ran, _ = sweep(tmp_path)
    assert len([c for c in ran.of("gh") if c[:2] == ["pr", "list"]]) == 1


def test_a_continue_that_cannot_be_asked_for_takes_the_key_off(tmp_path):
    files = {".dx-central/scripts/autopilot.py": f"REAL = {REAL!r}\n" + CENTRAL,
             ".dx-central/scripts/receipts.py": f"REAL = {REAL!r}\n" + CENTRAL}
    (tmp_path / "issue.json").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "issue.json").write_text(json.dumps({"body": PRD, "labels": [{"name": "accepted"}]}))
    gh = ('case "$*" in\n'
          '  "search issues"*"--label accepted "*) echo "o/r 9" ;;\n'
          '  "search issues"*) ;;\n'
          f'  "issue view 9"*) cat {tmp_path / "issue.json"} ;;\n'
          '  "pr list"*) echo "[]" ;;\n'
          '  "issue edit"*) exit 1 ;;\n'
          "esac\n")
    s = steps.step("autopilot-sweep.yml", "Start a missed one", job="sweep")
    ran = steps.run(s, tmp_path, central=False, files=files, stubs={"gh": gh}, env={"REPO": "o/r", "OWNER": "o", "GH_TOKEN": "t"})
    log = (ran.temp / "central.log").read_text().splitlines()
    assert ran.code == 1, ran.stdout
    assert "receipts.py state set swept_start=" in log


def test_sweep_start_is_next_steps_start_and_nothing_else():
    assert hasattr(autopilot, "sweep_start") and hasattr(autopilot, "closed_by_person"), "no sweep_start in scripts/autopilot.py"
    state = {"issue": {"state": "OPEN", "labels": ["accepted"]}, "lane": "human-issue", "may_start": [True, "ready"], "seal": "match", "spec": True}
    step = autopilot.next_step(state)
    assert autopilot.sweep_start(step, {}, ["accepted"], "")[0] == "start"
    assert autopilot.sweep_start(autopilot.next_step(dict(state, spec=False)), {}, ["accepted"], "")[0] == "start"
    assert autopilot.sweep_start(step, {"swept_start": "t"}, ["accepted"], "")[0] == ""
    assert autopilot.sweep_start(step, {}, ["accepted", "autopilot:continue"], "")[0] == ""
    assert autopilot.sweep_start(step, {}, ["accepted"], "4242")[0] == ""
    assert autopilot.sweep_start(step, {}, ["accepted"], "", closed=True)[0] == ""
    pr = [{"number": 3, "state": "OPEN", "author_type": "Bot", "labels": ["autopilot"]}]
    assert autopilot.sweep_start(autopilot.next_step(dict(state, prs=pr)), {}, ["accepted"], "")[0] == ""
    assert autopilot.closed_by_person([{"number": 1, "body": "Fixes #9", "mergedAt": None}], 9) is True
    assert autopilot.closed_by_person([{"number": 1, "body": "Fixes #9", "mergedAt": "2026-11-01T00:00:00Z"}], 9) is False
    assert autopilot.closed_by_person([{"number": 1, "body": "Closes #90", "mergedAt": None}], 9) is False


# #1002 C4: a stop waiting on a person, or a person's hold, is never started.
def test_needs_human_a_claim_or_an_assignee_start_nothing(tmp_path):
    cases = ({"labels": ("accepted", "needs-human")}, {"labels": ("accepted", "claimed")},
             {"FAKE_HOLDER": "a person claimed it (`claimed`)"}, {"FAKE_HOLDER": "it is assigned to @alice"},
             {"labels": ("accepted", "autopilot:waiting")}, {"FAKE_BOARD": '{"asked": "2026-11-26T10:00:00Z"}'})
    for i, case in enumerate(cases):
        ran, log = sweep(tmp_path / str(i), **case)
        assert ran.code == 0, ran.stdout + ran.stderr
        assert not continued(ran) and not marked(log), (case, ran.stdout)
        assert "o/r#9: not started" in ran.stdout, (case, ran.stdout)


def test_sweep_start_says_no_to_a_person_s_stop_or_hold():
    state = {"issue": {"state": "OPEN", "labels": ["accepted"]}, "lane": "human-issue", "may_start": [True, "ready"], "seal": "match", "spec": True}
    for labels in (["accepted", "needs-human"], ["accepted", "claimed"]):
        step = autopilot.next_step(dict(state, issue={"state": "OPEN", "labels": labels}))
        assert autopilot.sweep_start(step, {}, labels, "")[0] == "", labels
    step = autopilot.next_step(dict(state, issue={"state": "OPEN", "labels": ["accepted"], "assignees": ["alice"]}))
    assert autopilot.sweep_start(step, {}, ["accepted"], "")[0] == ""


def test_the_missed_start_step_passes_shellcheck():
    # `a && b || c` is shellcheck's SC2015, which fails actionlint (#1003,
    # round 1): the read of the pull requests is an if, not a chain.
    import shutil, subprocess
    import pytest
    if not shutil.which("shellcheck"):
        pytest.skip("no shellcheck")
    script = steps.expand(steps.step("autopilot-sweep.yml", "Start a missed one", job="sweep")["run"], {})
    # The ones actionlint leaves out of its shellcheck run.
    checked = subprocess.run(["shellcheck", "-s", "bash", "-e", "SC1091,SC2194,SC2050,SC2154,SC2157", "-"],
                             input=script, capture_output=True, text=True)
    assert checked.returncode == 0, checked.stdout
