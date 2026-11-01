"""The commands that replaced the autopilot's and the review's labels (#564):
`/continue <hint>` and `/review full`, honoured from a writer only, and the
bot's own continue comment, read from dilux-bot only. Runs review-reply.yml's
"Bring the autopilot back" step with gh and python3 stood in (as
test_autopilot_continue_start.py does), and checks the jobs it wires."""
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def jobs(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))["jobs"]


def step(wf, job, key):
    return next(s for s in jobs(wf)[job]["steps"] if s.get("id") == key or s.get("name") == key)


def back(tmp_path, body, login="boss", sender_type="User", role="write", is_pr=False, state=None, pr=None):
    """The step's outputs and the calls it made for a comment on #7 (an
    issue), or on #9 (a pull request closing #7) when is_pr."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    log.write_text("")
    pr = pr if pr is not None else {"author": {"login": "app/dilux-bot"}, "labels": [{"name": "autopilot"}], "closingIssuesReferences": [{"number": 7}]}
    (tmp_path / "pr.json").write_text(json.dumps(pr))
    (tmp_path / "state.json").write_text(json.dumps(state or {}))
    (bin_dir / "gh").write_text(
        "#!/bin/bash\n"
        f'echo "gh $*" >> "{log}"\n'
        'case "$*" in\n'
        f"  *collaborators/*) echo {role} ;;\n"
        f"  *closingIssuesReferences*) cat \"{tmp_path / 'pr.json'}\" ;;\n"
        "  *'--json labels'*) echo false ;;\n"
        "esac\n")
    (bin_dir / "python3").write_text(
        "#!/bin/bash\n"
        f'echo "NUMBER=$NUMBER BOARD_TITLE=$BOARD_TITLE python3 $*" >> "{log}"\n'
        f'case "$2 $3" in "state get") cat "{tmp_path / "state.json"}" ;; esac\n')
    for f in ("gh", "python3"):
        (bin_dir / f).chmod(0o755)
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"comment": {"body": body}}))
    out = tmp_path / "out"
    out.write_text("")
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", GITHUB_OUTPUT=str(out), GITHUB_EVENT_PATH=str(event),
               GITHUB_REPOSITORY="o/r", DX_BOT_APP="dilux-bot", DX_BOT_LOGIN="dilux-bot[bot]",
               NUMBER="9" if is_pr else "7", IS_PR="true" if is_pr else "false", LOGIN=login, SENDER_TYPE=sender_type)
    done = subprocess.run(["bash", "-c", step("review-reply.yml", "answer", "back")["run"]], env=env, capture_output=True,
                          text=True, timeout=60, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines())
    return outputs, log.read_text()


@pytest.mark.parametrize("is_pr", [False, True])
def test_a_writers_continue_brings_the_autopilot_back(tmp_path, is_pr):
    out, calls = back(tmp_path, "/continue look at t.py first\nand then the rest", is_pr=is_pr)
    assert out == {"continue": "true", "issue": "7"}
    # Not waiting: no answer, so the run counts.
    assert "answered" not in calls


@pytest.mark.parametrize("role", ["read", "triage", "none"])
def test_a_continue_from_someone_without_write_access_is_nothing(tmp_path, role):
    out, calls = back(tmp_path, "/continue", login="stranger", role=role)
    assert out == {}
    assert "state set" not in calls


def test_continue_only_on_the_first_line(tmp_path):
    out, _ = back(tmp_path, "please\n/continue")
    assert out == {}


def test_a_writers_answer_while_waiting_frees_the_run(tmp_path):
    out, calls = back(tmp_path, "Option A.", state={"waiting": True}, is_pr=True)
    assert out == {"continue": "true", "issue": "7"}
    assert "NUMBER=7 BOARD_TITLE= python3 .dx-central/scripts/receipts.py state set answered=true waiting=" in calls


def test_someone_elses_opinion_while_waiting_is_summarised(tmp_path):
    out, calls = back(tmp_path, "do B", login="stranger", role="read", state={"waiting": True})
    assert out == {"others": "true", "issue": "7"}
    assert "state set" not in calls


def test_a_hand_edited_state_waits_on_nobody(tmp_path):
    out, calls = back(tmp_path, "Option A.", state={"waiting": True, "tampered": True})
    assert out == {}
    assert "state set" not in calls


def test_the_bots_continue_comment_starts_the_next_run(tmp_path):
    out, _ = back(tmp_path, "The run ended.\n<!-- dx-autopilot-continue -->", login="dilux-bot[bot]", sender_type="Bot", is_pr=True)
    assert out == {"continue": "true", "issue": "7"}


@pytest.mark.parametrize("login,sender_type,body", [
    ("mallory", "User", "copied\n<!-- dx-autopilot-continue -->"),
    ("other-bot[bot]", "Bot", "copied\n<!-- dx-autopilot-continue -->"),
    ("dilux-bot[bot]", "Bot", "a review summary"),
])
def test_the_continue_marker_from_anyone_else_is_nothing(tmp_path, login, sender_type, body):
    out, _ = back(tmp_path, body, login=login, sender_type=sender_type, is_pr=True)
    assert out == {}


def test_continue_on_a_pull_request_not_the_autopilots_is_nothing(tmp_path):
    out, _ = back(tmp_path, "/continue", is_pr=True, pr={"author": {"login": "ana"}, "labels": [], "closingIssuesReferences": [{"number": 7}]})
    assert out == {}


def test_review_full_from_a_writer_sets_the_pull_requests_state(tmp_path):
    out, calls = back(tmp_path, "/review full", is_pr=True)
    assert out == {}
    assert "NUMBER=9 BOARD_TITLE=The pull request's board python3 .dx-central/scripts/receipts.py state set review_full=true" in calls


def test_review_full_from_someone_else_is_nothing(tmp_path):
    out, calls = back(tmp_path, "/review full", login="stranger", role="read", is_pr=True)
    assert out == {}
    assert "state set" not in calls


def test_the_jobs_are_wired():
    rr = jobs("review-reply.yml")
    cond = rr["answer"]["if"]
    assert "github.event.sender.type == 'User'" in cond
    assert "github.event.sender.login == (vars.DX_BOT_LOGIN || 'dilux-bot[bot]')" in cond and "<!-- dx-autopilot-continue -->" in cond
    ap = rr["autopilot"]
    assert ap["needs"] == "answer" and ap["if"] == "needs.answer.outputs.continue == 'true'"
    assert ap["uses"].startswith("DiluxOne/.github/.github/workflows/autopilot.yml@")
    assert ap["with"]["mode"] == "continue" and ap["with"]["issue"] == "${{ needs.answer.outputs.issue }}"
    assert ap["permissions"] == {"contents": "read", "pull-requests": "read"}
    # The commands wake no reply.
    assert "!startsWith(github.event.comment.body, '/continue')" in rr["reply"]["if"]
    # The comment's text reaches the script from the event's file only.
    assert "github.event.comment.body" not in step("review-reply.yml", "answer", "back")["run"]


def test_the_review_reads_and_clears_review_full_from_the_board():
    scope = step("claude-review.yml", "review", "scope")["run"]
    assert "receipts.py state get" in scope and ".review_full == true" in scope and "review:full" not in scope
    verdict = step("claude-review.yml", "review", "verdict")["run"]
    assert "state set review_full=" in verdict


def tamper_gate():
    run = step("autopilot.yml", "prep", "may")["run"]
    start = run.index("# A board's state edited by hand")
    end = run.index("fi\n", run.index('if [ "${TAMPERED:-}" = true ]', start)) + 3
    return "set -euo pipefail\n" + run[start:end] + 'echo "go=true" >> "$GITHUB_OUTPUT"\n'


@pytest.mark.parametrize("tampered,go", [("true", "false"), ("false", "true"), ("", "true")])
def test_a_hand_edited_board_hands_the_pull_request_to_a_person(tmp_path, tampered, go):
    log = tmp_path / "calls.log"
    log.write_text("")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(f'#!/bin/bash\necho "gh $*" >> "{log}"\n')
    (bin_dir / "gh").chmod(0o755)
    out = tmp_path / "out"
    out.write_text("")
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", GITHUB_OUTPUT=str(out), GITHUB_REPOSITORY="o/r", PR="9", TAMPERED=tampered)
    done = subprocess.run(["bash", "-c", tamper_gate()], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert out.read_text() == f"go={go}\n"
    assert ("gh pr edit 9 --repo o/r --add-label needs-human" in log.read_text()) == (go == "false")
    assert step("autopilot.yml", "prep", "may")["env"]["TAMPERED"] == "${{ steps.what.outputs.tampered }}"


def test_the_first_run_and_each_count_go_to_the_pull_requests_board():
    draft = step("autopilot.yml", "draft", "draft")["run"]
    assert 'NUMBER="$pr" BOARD_TITLE="The pull request\'s board" python3 .dx-central/scripts/receipts.py state add runs 1' in draft
    assert "autopilot.py count" in step("autopilot.yml", "prep", "Count the round or the run")["run"]
    # The question answered or the hint read: waiting goes from the issue.
    assert "receipts.py state set waiting=" in step("autopilot.yml", "prep", "The agent's task")["run"]
