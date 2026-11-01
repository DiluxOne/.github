"""The triage's and the reproduction's labels became the board's state and a
writer's commands (#564): `/continue`, `/spike` and `/repro` from a writer
start what the labels started, from anyone else nothing; the layer, the
verdict and the reproduction's state are read from and written to the
board. Runs the steps' own scripts with gh and python3 stood in."""
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def jobs(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))["jobs"]


def step(job, name):
    return next(s for s in job["steps"] if s.get("name") == name or s.get("id") == name)


def run(tmp_path, script, env, role="write", states=None):
    """Runs a step's script; gh answers ROLE for a permission and OPEN for an
    issue's state, python3 (receipts.py) answers STATES[NUMBER] for
    `state get`. Returns the calls and the step's outputs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    log.write_text("")
    states = states or {}
    for n, st in states.items():
        (tmp_path / f"state-{n}.json").write_text(st)
    (bin_dir / "gh").write_text(
        "#!/bin/bash\n"
        f'echo "gh $*" >> "{log}"\n'
        'case "$*" in\n'
        f"  *collaborators/*) echo {role} ;;\n"
        "  *dependencies/blocking*) echo 12 ;;\n"
        "  *'--json state'*) echo true ;;\n"
        "  *'issue list'*) echo 12 ;;\n"
        "  *'/comments'*) echo '[{\"user\": {\"login\": \"alice\"}, \"created_at\": \"2026-01-01T00:00:00Z\"}]' ;;\n"
        "esac\n")
    (bin_dir / "python3").write_text(
        "#!/bin/bash\n"
        f'echo "python3 $* NUMBER=$NUMBER" >> "{log}"\n'
        f'if [ "$2 $3" = "state get" ]; then f="{tmp_path}/state-$NUMBER.json"; if [ -n "$4" ]; then [ -f "$f" ] && jq -r --arg k "$4" \'.[$k] // empty\' "$f"; else cat "$f" 2>/dev/null || echo "{{}}"; fi; fi\n')
    for f in ("gh", "python3"):
        (bin_dir / f).chmod(0o755)
    out = tmp_path / "out"
    out.write_text("")
    full = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", GITHUB_OUTPUT=str(out), RUNNER_TEMP=str(tmp_path),
                GITHUB_REPOSITORY="o/r", DX_BOT_APP="dilux-bot", DX_BOT_LOGIN="dilux-bot[bot]", **env)
    done = subprocess.run(["bash", "-c", script], env=full, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
    return log.read_text(), out.read_text()


def command(tmp_path, body, role):
    return run(tmp_path, step(jobs("issue-triage.yml")["command"], "who")["run"],
               {"NUMBER": "7", "LOGIN": "alice", "COMMENT": body}, role=role)


def test_continue_from_a_writer_resumes_the_autopilot(tmp_path):
    calls, out = command(tmp_path, "/continue use the cache\r\nmore of the hint", "write")
    assert "command=continue" in out
    assert "state set" not in calls


def test_continue_from_a_reader_or_a_triager_starts_nothing(tmp_path):
    for role in ("read", "triage", "none", "unknown"):
        _, out = command(tmp_path, "/continue", role)
        assert "command=" not in out, role


def test_spike_from_a_writer_records_it_on_the_board(tmp_path):
    calls, out = command(tmp_path, "/spike", "maintain")
    assert "command=spike" in out
    assert "receipts.py state set spike=true NUMBER=7" in calls


def test_spike_from_a_non_writer_writes_nothing(tmp_path):
    calls, out = command(tmp_path, "/spike", "read")
    assert "command=" not in out and "state set" not in calls


def test_only_the_first_line_and_the_word_alone_count(tmp_path):
    for body in ("/continued", "please\n/continue", "/spikes", " /spike"):
        _, out = command(tmp_path, body, "admin")
        assert "command=" not in out, body


def test_the_command_job_never_runs_for_a_bot_or_on_a_pull_request():
    cond = jobs("issue-triage.yml")["command"]["if"]
    assert "github.event.comment.user.type != 'Bot'" in cond and "github.event.sender.type != 'Bot'" in cond
    assert "!github.event.issue.pull_request" in cond and "github.event_name == 'issue_comment'" in cond


def test_the_spike_and_the_continue_wait_for_the_command():
    j = jobs("issue-triage.yml")
    assert j["spike"]["needs"] == "command" and j["spike"]["if"] == "needs.command.outputs.command == 'spike'"
    assert j["autopilot"]["needs"] == "command" and str(j["autopilot"]["if"]).lstrip().startswith("!cancelled()")


def test_the_spike_clears_its_request_when_it_answers(tmp_path):
    script = step(jobs("issue-triage.yml")["spike"], "The answer, on the issue")["run"]
    calls, _ = run(tmp_path, script, {"NUMBER": "7", "OUT": "", "GITHUB_SERVER_URL": "https://github.com", "GITHUB_RUN_ID": "1"})
    assert "receipts.py state set spike= NUMBER=7" in calls and "--add-label" not in calls


def test_the_nightly_bug_is_marked_on_the_board(tmp_path):
    calls, out = run(tmp_path, step(jobs("issue-triage.yml")["nightly"], "mark")["run"], {"NUMBER": "9"})
    assert "receipts.py state set verdict=bug repro=unconfirmed NUMBER=9" in calls and "--add-label" not in calls
    assert "bug=true" in out


def unblock(tmp_path, state):
    script = step(jobs("issue-triage.yml")["unblock"], "Run their reproductions again")["run"]
    return run(tmp_path, script, {"NUMBER": "5"}, states={"12": state})[0]


def test_a_blocked_reproduction_runs_again_with_the_apps_comment(tmp_path):
    calls = unblock(tmp_path, '{"repro": "blocked"}')
    assert "receipts.py state set repro=unconfirmed NUMBER=12" in calls
    assert "gh issue comment 12 --repo o/r --body <!-- dx-repro-unblocked -->" in calls


def test_one_not_blocked_or_edited_by_hand_does_not(tmp_path):
    for state in ('{"repro": "confirmed"}', '{}', '{"repro": "blocked", "tampered": true}'):
        calls = unblock(tmp_path, state)
        assert "issue comment" not in calls and "state set" not in calls, state


def test_an_answered_needs_info_issue_loses_its_verdict(tmp_path):
    script = jobs("issue-triage.yml")["stale"]["steps"][-1]["run"]
    calls, _ = run(tmp_path, script, {"DAYS": "14", "BOT": "dilux-bot[bot]"}, states={"12": '{"verdict": "needs-info"}'})
    assert "receipts.py state set verdict= NUMBER=12" in calls and "--label needs-info" not in calls
    calls, _ = run(tmp_path, script, {"DAYS": "14", "BOT": "dilux-bot[bot]"}, states={"12": '{"verdict": "needs-info", "tampered": true}'})
    assert "state set" not in calls and "issue close" not in calls


def way(tmp_path, layer):
    script = step(jobs("issue-repro.yml")["write"], "way")["run"]
    calls, _ = run(tmp_path, script, {"NUMBER": "3", "CENTRAL": ".dx-central"},
                   states={"3": '{"layer": "%s"}' % layer} if layer else None)
    return calls


def test_the_reproduction_reads_the_layer_from_the_board(tmp_path):
    calls = way(tmp_path, "browser")
    assert "receipts.py state get layer NUMBER=3" in calls and "--json labels" not in calls
    assert "repro-ways.py resolve" in calls


def test_the_reproduction_starts_on_a_writers_repro_or_the_apps_own_comment():
    write = jobs("issue-repro.yml")["write"]
    cond = " ".join(str(write["if"]).split())
    assert "github.event_name == 'issue_comment'" in cond and "startsWith(github.event.comment.body, '/repro')" in cond
    assert "'<!-- dx-repro-unblocked -->'" in cond and "'<!-- dx-repro-retry -->'" in cond
    assert "label.name" not in cond
    start = step(write, "start")
    assert start["env"]["COMMENT"] == "${{ github.event.comment.body }}" and "LABEL" not in start["env"]
    assert write["outputs"]["kind"] == "${{ steps.start.outputs.kind }}"
    report = step(jobs("issue-repro.yml")["report"], "report")
    assert report["env"]["KIND"] == "${{ needs.write.outputs.kind }}"
    assert '[ "$KIND" != retry ]' in report["run"] and "repro:retry" not in report["run"]
