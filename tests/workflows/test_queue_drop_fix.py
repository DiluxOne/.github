"""A pull request the merge queue dropped on a failing check (#479 C6): on
`dequeued`, the organisation's pipeline starts one autopilot fix round for
an autopilot pull request, and nothing else of the pipeline runs; the round
runs only when a check failed in its last merge group, within the rounds
cap, and its agent reads the failed jobs' log. The "may" step's gate runs
with python3 and gh stood in."""
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DEQUEUED = "${{ github.event_name == 'pull_request' && github.event.action == 'dequeued' }}"


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def triggers(wf):
    return wf.get("on", wf.get(True))


def test_the_pipeline_starts_one_fix_round_when_the_queue_drops_an_autopilot_pull_request():
    wf = workflow("org-pull-request.yml")
    assert "dequeued" in triggers(wf)["pull_request"]["types"]
    job = wf["jobs"]["autopilot-queue"]
    cond = " ".join(job["if"].split())
    for part in ("github.event.action == 'dequeued'", "contains(github.event.pull_request.labels.*.name, 'autopilot')",
                 "github.event.pull_request.user.login == vars.DX_BOT_LOGIN", "github.repository != 'DiluxOne/.github'"):
        assert part in cond
    assert job["uses"].startswith("DiluxOne/.github/.github/workflows/autopilot.yml@")
    # No input the released major may lack: autopilot.yml reads the event.
    assert job["with"] == {"mode": "fix", "pr": "${{ format('{0}', github.event.pull_request.number) }}"}
    assert job["permissions"] == {"contents": "read", "pull-requests": "read"}


def test_nothing_else_of_the_pipeline_runs_on_dequeued():
    jobs = workflow("org-pull-request.yml")["jobs"]
    for name in ("conventions", "assignee", "wake-vm", "review"):
        assert "github.event.action != 'dequeued'" in jobs[name]["if"], name
    # Those wait for the review, which is skipped then.
    for name in ("auto-merge", "autopilot-fix"):
        assert jobs[name]["needs"] in ("review", ["review"]), name


def prep_step(step_id):
    return next(s for s in workflow("autopilot.yml")["jobs"]["prep"]["steps"] if s.get("id") == step_id)


def test_the_round_knows_it_from_the_event_and_reads_the_failed_jobs_log():
    assert prep_step("may")["env"]["QUEUE"] == DEQUEUED
    task = next(s for s in workflow("autopilot.yml")["jobs"]["prep"]["steps"] if s.get("name") == "The agent's task")
    assert task["env"]["QUEUE"] == DEQUEUED
    assert 'autopilot.py inputs "$MODE"' in task["run"] and "autopilot.py prompt fix" in task["run"]


def gate(tmp_path, round_, queue, failed):
    run = prep_step("may")["run"]
    script = "set -euo pipefail\n" + run[run.index('if [ "$MODE" = fix ]; then'):]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    log.write_text("")
    policy = json.dumps({"autopilot-rounds": 5})
    (bin_dir / "python3").write_text(
        "#!/bin/bash\n"
        f'echo "python3 $*" >> "{log}"\n'
        f"case \"$2\" in policy) echo '{policy}' ;; queue-failed) echo 'Plugin tests (u)'; exit {0 if failed else 1} ;; esac\n")
    (bin_dir / "gh").write_text(f'#!/bin/bash\necho "gh $*" >> "{log}"\nexit 0\n')
    for f in ("python3", "gh"):
        (bin_dir / f).chmod(0o755)
    out = tmp_path / "out"
    out.write_text("")
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", GITHUB_OUTPUT=str(out), GITHUB_REPOSITORY="o/r",
               MODE="fix", ISSUE="7", PR="9", ROUND=str(round_), QUEUE="true" if queue else "false")
    done = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return log.read_text(), out.read_text()


def test_one_round_when_a_check_failed_in_the_group(tmp_path):
    calls, out = gate(tmp_path, 2, True, True)
    assert out == "go=true\n" and "queue-failed" in calls


def test_no_round_when_no_check_failed(tmp_path):
    calls, out = gate(tmp_path, 2, True, False)
    assert out == "go=false\n" and "needs-human" not in calls


@pytest.mark.parametrize("failed", [True, False])
def test_refused_past_the_rounds_cap(tmp_path, failed):
    calls, out = gate(tmp_path, 6, True, failed)
    assert out == "go=false\n"
    assert "queue-failed" not in calls
    assert "--add-label needs-human" in calls


def test_a_blocked_review_round_does_not_ask_the_queue(tmp_path):
    calls, out = gate(tmp_path, 2, False, False)
    assert out == "go=true\n" and "queue-failed" not in calls


def test_the_agent_gets_the_failed_jobs_log(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("autopilot", ROOT / "scripts/autopilot.py")
    ap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ap)
    runs = [{"id": 5, "name": "Plugin tests", "html_url": "https://github.com/o/r/actions/runs/5", "conclusion": "failure",
             "head_branch": "gh-readonly-queue/main/pr-9-abc", "created_at": "2026-10-30T10:00:00Z"},
            {"id": 6, "name": "Plugin checks", "conclusion": "success", "head_branch": "gh-readonly-queue/main/pr-9-abc", "created_at": "2026-10-30T10:00:00Z"}]
    calls = []

    def fake_gh(*args, **kw):
        calls.append(args)
        return json.dumps({"workflow_runs": runs}) if args[0] == "api" else json.dumps({"body": "", "comments": [], "author": {"login": "a"}, "url": "u"})

    class Done:
        stdout = "E2E (single)\tRun the suite\tError: expect(received).toBe(expected) at tests/e2e/login.spec.ts:14\n"

    monkeypatch.setattr(ap, "gh", fake_gh)
    monkeypatch.setattr(ap, "pr_json", lambda *a, **k: {"body": ""})
    monkeypatch.setattr(ap.subprocess, "run", lambda argv, **kw: (calls.append(tuple(argv)), Done())[1])
    monkeypatch.setenv(ap.IO_ENV, str(tmp_path))
    monkeypatch.setenv("QUEUE", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("PR", "9")
    monkeypatch.delenv("NUMBER", raising=False)
    monkeypatch.delenv("BODY", raising=False)
    assert ap.main(["inputs", "fix"]) == 0
    log = (tmp_path / ap.QUEUE_LOG).read_text()
    assert "## Plugin tests (https://github.com/o/r/actions/runs/5)" in log and "login.spec.ts:14" in log
    assert ("gh", "run", "view", "5", "--repo", "o/r", "--log-failed") in calls
    assert not any(c[:4] == ("gh", "run", "view", "6") for c in calls)
    assert not (tmp_path / "review.md").exists()
