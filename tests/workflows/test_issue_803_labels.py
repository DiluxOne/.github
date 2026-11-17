"""The triage keeps its verdicts as labels, and only those (#803).

C1: no step of the triage sets `needs-triage` any more; the issue's board
says whether the triage ran (a `triage` key in its state, #564, and a
Triage row)."""
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ACT = ROOT / "scripts" / "triage-act.sh"


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def receipts():
    spec = importlib.util.spec_from_file_location("receipts", ROOT / "scripts" / "receipts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def runs(wf):
    for job_name, job in wf["jobs"].items():
        for s in job.get("steps") or []:
            if s.get("run"):
                yield job_name, s


def test_c1_no_triage_step_sets_needs_triage():
    for job_name, s in runs(workflow("issue-triage.yml")):
        assert "needs-triage" not in s["run"], f"{job_name} / {s.get('name')} still uses needs-triage"
    # Nor does the script the triage acts with, outside its self-test.
    code = ACT.read_text(encoding="utf-8").split('if [ "${1:-}" = "--test" ]', 1)[0]
    assert "needs-triage" not in code


def act(tmp_path, verdict):
    """triage-act.sh act with a stand-in gh, the board in a fixture: (the
    board's state, every gh call)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    log = tmp_path / "gh.log"
    gh = bin_dir / "gh"
    gh.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> ' + str(log) + "\n", encoding="utf-8")
    gh.chmod(0o755)
    body = tmp_path / "body.md"
    body.write_text("### Problem\n\nIt breaks.\n", encoding="utf-8")
    fixture = tmp_path / "receipts"
    fixture.mkdir()
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", NUMBER="7", GITHUB_REPOSITORY="o/r", MODEL="m",
               MAINTAINER="boss", VERDICT=verdict, REPLY="x", SUMMARY="s", BODY=str(body), RECEIPTS_FIXTURE=str(fixture),
               AUTOPILOT_JSON="null", LABELS_JSON="[]", HELD="", GITHUB_SERVER_URL="https://github.com", GITHUB_RUN_ID="42")
    subprocess.run(["bash", str(ACT)], env=env, check=True, capture_output=True, text=True)
    board = (fixture / "comments" / "7" / "board.md").read_text(encoding="utf-8")
    state, intact = receipts().parse_state(board)
    assert intact
    return state, board, log.read_text(encoding="utf-8") if log.exists() else ""


def test_c1_a_verdict_is_on_the_board(tmp_path):
    state, board, calls = act(tmp_path, '{"category":"needs_info"}')
    assert state["triage"]["ran"] is True and state["triage"]["verdict"] == "needs_info" and state["triage"]["at"]
    assert "| Triage | ✓ ran at " in board and "needs-info" in board
    assert "--add-label needs-info" in calls
    assert "needs-triage" not in calls


def test_c1_no_verdict_says_it_could_not_run(tmp_path):
    state, board, calls = act(tmp_path, "")
    assert state["triage"] == {"ran": False, "why": "no-verdict"}
    assert "| Triage | ✗ could not run (no-verdict)" in board
    # It waits on a maintainer, named on the board.
    assert "| Waits on | " in board
    assert "needs-triage" not in calls


def test_c1_an_unknown_category_says_it_could_not_run(tmp_path):
    state, board, calls = act(tmp_path, '{"category":"nonsense"}')
    assert state["triage"] == {"ran": False, "why": "unknown"}
    assert "needs-triage" not in calls


def test_c1_the_board_shows_the_triage_row():
    r = receipts()
    ran = r.board_text(7, True, None, None, state={"triage": {"ran": True, "verdict": "by_design", "at": "2026-11-17T00:00:00Z"}})
    assert "| Triage | ✓ ran at 2026-11-17T00:00:00Z: by-design |" in ran
    failed = r.board_text(7, True, None, None, state={"triage": {"ran": False, "why": "cap"}})
    assert "| Triage | ✗ could not run (cap): a maintainer re-runs the job or triages it by hand |" in failed
    assert "| Triage |" not in r.board_text(7, True, None, None, state={})


def test_c2_an_answered_spike_needs_human():
    """C2: what waits on a person says `needs-human`, never `needs:maintainer`."""
    spike = workflow("issue-triage.yml")["jobs"]["spike"]
    answer = next(s for s in spike["steps"] if s.get("name") == "The answer, on the issue")
    assert "--add-label needs-human --remove-label spike" in answer["run"]
    for name in ("issue-triage.yml", "runner-image.yml", "autonomy-digest.yml"):
        for job_name, s in runs(workflow(name)):
            assert "needs:maintainer" not in s["run"], f"{name} {job_name} / {s.get('name')}"
    assert "needs:maintainer" not in (ROOT / "scripts" / "run-issue.sh").read_text(encoding="utf-8").split("self_test() {", 1)[0]


def test_c3_the_forms_set_no_bug_or_enhancement_label():
    """C3: the forms set the issue's Type, which says what the labels did."""
    for name, kind in (("bug_report.yml", "Bug"), ("feature_request.yml", "Feature")):
        form = yaml.safe_load((ROOT / ".github/ISSUE_TEMPLATE" / name).read_text(encoding="utf-8"))
        assert form.get("type") == kind, name
        assert not {"bug", "enhancement"} & set(form.get("labels") or []), name
