"""`make pre-pr` after the agent's step (#673): a check that outlasts the
work step's deadline is stopped and deferred, the `verify` job runs it whole
with no key, and only its pass marks the pull request ready."""
import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/autopilot.yml"


def autopilot():
    spec = importlib.util.spec_from_file_location("autopilot", ROOT / "scripts/autopilot.py")
    ap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ap)
    return ap


def workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def step(job, name=None, step_id=None):
    return next(s for s in workflow()["jobs"][job]["steps"] if (step_id and s.get("id") == step_id) or (name and s.get("name") == name))


def git(d, *args):
    subprocess.run(["git", "-C", str(d), *args], check=True, capture_output=True,
                   env=dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))


def a_repo(tmp_path, recipe):
    repo, io_dir = tmp_path / "repo", tmp_path / "io"
    repo.mkdir()
    io_dir.mkdir()
    git(repo, "init", "-q")
    (repo / "Makefile").write_text(f"pre-pr:\n\t{recipe}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "feat: the change (C1)")
    return repo, io_dir


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


def test_a_check_past_the_deadline_is_stopped_and_finish_ready_takes_it_deferred(tmp_path, monkeypatch):
    ap = autopilot()
    repo, io_dir = a_repo(tmp_path, "@sleep 120")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("DX_DEADLINE", str(int(time.time()) + 2))
    began = time.time()
    with quiet():
        assert ap.run_pre_pr(str(io_dir)) == 0
    # Stopped at the deadline, its whole process group with it.
    assert time.time() - began < 30
    head = ap.git_out("rev-parse", "HEAD")
    assert ap.read_mark(str(io_dir)) == {"head": head, "rc": ap.TIMEOUT}
    # finish ready takes it, and says the ready is deferred.
    (io_dir / "pr.md").write_text("<!-- dx-checklist -->\n- [x] **C1** a\n<!-- /dx-checklist -->\n\n## 🙌 Credits\n\n<!-- dx-credits -->\n<!-- /dx-credits -->\n")
    (tmp_path / "tested.md").write_text("Ran it.\n")
    with quiet():
        assert ap.agent_helper(["finish", "ready", str(tmp_path / "tested.md")], str(io_dir)) == 0
    intents, _ = ap.read_outbox(str(io_dir / ap.OUTBOX))
    assert intents == [{"kind": "ready", "text": "Ran it.\n", "deferred": True}]
    # And verify runs it after the step.
    monkeypatch.setenv("DX_IO", str(io_dir))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        ap.main(["verify", "need"])
    assert out.getvalue().strip() == "true"


def test_verify_runs_make_pre_pr_whole_for_at_least_90_minutes_with_no_key():
    wf = workflow()
    job = wf["jobs"]["verify"]
    assert job["permissions"] == {"contents": "read"}
    text = yaml.safe_dump(job)
    assert "secrets." not in text and "create-github-app-token" not in text and "claude-code-action" not in text
    assert job["runs-on"] == wf["jobs"]["work"]["runs-on"]
    run = step("verify", name="make pre-pr")
    assert run["timeout-minutes"] >= 90 and job["timeout-minutes"] >= run["timeout-minutes"]
    m = re.search(r"\((\d+) - (\d+)\) \* 60", run["run"])
    assert int(m.group(1)) == run["timeout-minutes"] and 90 <= int(m.group(1)) - int(m.group(2))
    assert "verify run" in run["run"] and run["env"]["DX_PULLS"].endswith("/.dx-io/pulls.json")
    assert set(job["needs"]) >= {"work"} and "verify" in wf["jobs"]["apply"]["needs"]
    assert step("verify", step_id="result")["if"] == "always()"


def test_verify_runs_it_whole_and_says_pass_or_fail(tmp_path, monkeypatch):
    ap = autopilot()
    repo, _ = a_repo(tmp_path, "@echo checked; sleep 2")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("DX_DEADLINE", str(int(time.time()) + 600))
    out_dir, gh_out = tmp_path / "verify", tmp_path / "gh-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    with quiet():
        assert ap.main(["verify", "run", str(out_dir)]) == 0
        assert ap.main(["verify", "result", str(out_dir)]) == 0
    assert "verdict=pass" in gh_out.read_text()
    assert "checked" in (out_dir / ap.VERIFY_TAIL).read_text()
    (repo / "Makefile").write_text("pre-pr:\n\t@echo the test broke; exit 3\n")
    git(repo, "commit", "-qam", "fix: break it")
    gh_out.write_text("")
    with quiet():
        ap.main(["verify", "run", str(out_dir)])
        ap.main(["verify", "result", str(out_dir)])
    assert "verdict=fail" in gh_out.read_text()
    assert "the test broke" in (out_dir / ap.VERIFY_TAIL).read_text()


def test_a_pass_lets_ready_through_and_the_run_ends_ready(tmp_path, monkeypatch):
    ap = autopilot()
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(json.dumps({"kind": "ready", "text": "Ran it.", "deferred": True}) + "\n")
    calls = []
    monkeypatch.setattr(ap, "main", lambda argv: calls.append(argv) or 0)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("PREPR", "pass")
    with quiet():
        assert ap.apply_outbox(str(outbox), "o/r", "7", "8") == 0
    assert [c[:2] for c in calls] == [["finish", "ready"]]
    # Ready, so the end rule says ready: no needs-human from a time-out.
    assert ap.end_verdict("continue", "8", False, False, 3, 3, False, 2, 5) == "ready"
    # Deferred with no verdict, or verify's failure: the pull request stays a draft.
    for prepr in ("", "fail", "timeout", "lost"):
        calls.clear()
        monkeypatch.setenv("PREPR", prepr)
        with quiet():
            ap.apply_outbox(str(outbox), "o/r", "7", "8")
        assert calls == [], prepr
