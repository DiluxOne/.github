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
    # #682: always, but after a failed install of the tools, when no
    # verdict is the `lost` apply reads.
    assert step("verify", step_id="result")["if"] == "always() && steps.tools.outcome != 'failure'"


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


CHECKLIST = "<!-- dx-checklist -->\n- [x] **C1** a\n- [x] **C2** b\n<!-- /dx-checklist -->\n"


def test_a_failing_verify_keeps_the_draft_and_brings_a_free_fix_round_with_its_output(tmp_path, monkeypatch):
    ap = autopilot()
    # apply: verify failed, so the ready is kept back and the end rule told.
    outbox, gh_out = tmp_path / "outbox.jsonl", tmp_path / "gh-output"
    outbox.write_text(json.dumps({"kind": "ready", "text": "Ran it.", "deferred": True}) + "\n")
    finished = []
    real_main = ap.main
    monkeypatch.setattr(ap, "main", lambda argv: finished.append(argv) or 0)
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    monkeypatch.setenv("PREPR", "fail")
    with quiet():
        assert ap.apply_outbox(str(outbox), "o/r", "7", "8") == 0
    assert finished == [] and "prepr=fail" in gh_out.read_text()
    monkeypatch.setattr(ap, "main", real_main)
    # end: the marked comment with the output's tail, the run's label free,
    # and the continue, on a pull request that is still a draft.
    tail = tmp_path / "tail.txt"
    tail.write_text("FAILED tests/test_x.py::test_it - AssertionError\n")
    labels = ["autopilot", "autopilot:run-1", "autopilot:run-2"]
    calls = []

    def fake_gh(*args, input_text=None):
        calls.append(list(args))
        return json.dumps({"comments": []}) if args[1] == "view" else ""

    monkeypatch.setattr(ap, "gh", fake_gh)
    monkeypatch.setattr(ap, "pr_json", lambda repo, pr, fields: {"body": CHECKLIST, "isDraft": True, "headRefOid": "abc",
                                                                 "labels": [{"name": l} for l in labels]})
    monkeypatch.setattr(ap, "refresh_board", lambda repo, number: None)
    monkeypatch.setattr(ap.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(ap.autonomy, "policy_in_force", lambda: {"autopilot-runs": 5})
    for k, v in {"MODE": "continue", "NUMBER": "7", "PR": "8", "RUNS": "2", "PREPR": "fail", "PREPR_TAIL": str(tail),
                 "GITHUB_REPOSITORY": "o/r", "STARTED": "2026-01-01T00:00:00Z", "WORK_RESULT": "success", "AGENT_OUTCOME": "success",
                 "WORK_OUTCOME": "success", "WORK_LOG": str(tmp_path / "none.json")}.items():
        monkeypatch.setenv(k, v)
    for k in ("HEAD_BEFORE", "WHY", "FAILED", "HELD", "CORE"):
        monkeypatch.delenv(k, raising=False)
    gh_out.write_text("")
    with quiet():
        assert ap.main(["end"]) == 0
    assert "verdict=continue" in gh_out.read_text()
    comments = [c for c in calls if c[:2] == ["pr", "comment"]]
    assert len(comments) == 1
    body = comments[0][comments[0].index("--body") + 1]
    assert body.startswith(ap.PREPR_MARK) and "FAILED tests/test_x.py::test_it" in body
    assert ["pr", "edit", "8", "--repo", "o/r", "--remove-label", "autopilot:run-2", "--add-label", "autopilot:free-2"] in calls
    assert ["issue", "edit", "7", "--repo", "o/r", "--add-label", "autopilot:continue"] in calls
    # Not ready, and no needs-human.
    assert not any("ready" in c[:2] for c in calls) and not any("needs-human" in c for c in calls)
    # The free label is not counted by the runs cap.
    assert ap.run_numbers(["autopilot:run-1", "autopilot:free-2"]) == (3, 1)
    # The next run's prep writes that comment's tail for the agent, and its
    # prompt asks to fix it first.
    io_dir = tmp_path / "io"
    io_dir.mkdir()
    monkeypatch.setenv("DX_IO", str(io_dir))
    monkeypatch.setattr(ap, "pr_json", lambda repo, pr, fields: {"comments": [{"author": {"login": ap.BOT}, "body": body,
                                                                               "createdAt": "2026-01-01T01:00:00Z"}]})
    with quiet():
        assert ap.main(["prepr-note"]) == 0
    assert (io_dir / ap.PREPR_NOTE).read_text() == "FAILED tests/test_x.py::test_it - AssertionError\n"
    prompt = ap.prompt_work("o/r", "7", "8", "fix/7-x", "x", [], True, prepr_failed=True)
    assert f".dx-io/{ap.PREPR_NOTE}" in prompt and "Fix what it reported first" in prompt


def test_the_workflow_wires_the_verdict_to_the_end_and_the_note_to_the_prompt():
    end = step("apply", step_id="end")
    assert end["env"]["PREPR"] == "${{ steps.applied.outputs.prepr }}"
    assert end["env"]["PREPR_TAIL"] == ".dx-verify/tail.txt"
    task = step("prep", step_id="task")["run"]
    assert task.index("autopilot.py prepr-note") < task.index("autopilot.py prompt work")


def test_a_quick_check_that_passed_at_the_head_skips_verify_and_the_work_keeps_its_limits(tmp_path, monkeypatch):
    ap = autopilot()
    repo, io_dir = a_repo(tmp_path, "@true")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("DX_DEADLINE", str(int(time.time()) + 3600))
    with quiet():
        assert ap.run_pre_pr(str(io_dir)) == 0
    assert ap.read_mark(str(io_dir))["rc"] == 0
    (io_dir / ap.OUTBOX).write_text(json.dumps({"kind": "ready", "text": "Ran it."}) + "\n")
    monkeypatch.setenv("DX_IO", str(io_dir))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        ap.main(["verify", "need"])
    assert out.getvalue().strip() == "false"
    # verify runs only on that answer, which the work's last step writes at
    # the head it bundles; skipped, the ready goes through as before.
    wf = workflow()
    assert "needs.work.outputs.verify == 'true'" in wf["jobs"]["verify"]["if"]
    left = step("work", step_id="left")
    assert left["if"] == "always()" and "autopilot.py verify need" in left["run"]
    assert wf["jobs"]["work"]["outputs"]["verify"] == "${{ steps.left.outputs.verify }}"
    assert ap.ready_goes({"kind": "ready", "text": "Ran it."}, "")
    # The work's limits are what they were before #673.
    work = step("work", step_id="work")
    assert (wf["jobs"]["work"]["timeout-minutes"], work["timeout-minutes"], work["env"]["BASH_MAX_TIMEOUT_MS"]) == (90, 75, "4500000")


def test_the_verdict_and_the_output_reach_apply_through_the_artifact():
    # .dx-verify is hidden: upload-artifact drops it unless told not to, and
    # the fix round would get no output (review of #675).
    wf = workflow()
    up = next(s for s in wf["jobs"]["verify"]["steps"] if "upload-artifact" in s.get("uses", ""))
    assert up["with"]["name"] == "autopilot-verify"
    paths = up["with"]["path"].split()
    assert sorted(paths) == [".dx-verify/tail.txt", ".dx-verify/verify.json"]
    assert up["with"].get("include-hidden-files") is True
    down = next(s for s in wf["jobs"]["apply"]["steps"] if s.get("with", {}).get("name") == "autopilot-verify")
    assert down["with"]["path"] == ".dx-verify"
    assert step("apply", step_id="end")["env"]["PREPR_TAIL"].startswith(down["with"]["path"] + "/")


def test_a_check_stopped_in_a_fix_round_says_reply_and_end_not_finish_ready(tmp_path, monkeypatch):
    ap = autopilot()
    repo, io_dir = a_repo(tmp_path, "@sleep 30")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("DX_DEADLINE", str(int(time.time()) - 1))
    for mode, says, never in (("fix", "Reply in each thread", "finish ready"), ("start", "finish ready", "Reply in each thread")):
        monkeypatch.setenv("MODE", mode)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert ap.run_pre_pr(str(io_dir)) == 0
        assert says in out.getvalue() and never not in out.getvalue()
    assert step("work", step_id="work")["env"]["MODE"] == "${{ needs.prep.outputs.mode }}"


def test_verify_result_reads_only_the_end_of_a_long_log(tmp_path, monkeypatch):
    ap = autopilot()
    log = tmp_path / "pre-pr.log"
    log.write_text("x" * (ap.VERIFY_CHARS * 10) + "\nthe last line\n")
    end = ap.read_end(str(log))
    assert len(end) <= ap.VERIFY_CHARS * 4 and end.endswith("the last line\n")
    assert ap.tail_text(end).endswith("the last line")


def test_a_target_that_failed_early_is_in_the_excerpt_however_long_another_writes(tmp_path, monkeypatch):
    # #679 C1: make -j, where target a fails at once and b writes for long
    # after: a's error and its make line are what verify result keeps.
    ap = autopilot()
    script = tmp_path / "b.sh"
    script.write_text("for i in $(seq 1 3000); do echo \"b writes line $i\"; done\n")
    repo, _ = a_repo(tmp_path, "true")
    (repo / "Makefile").write_text(f"MAKEFLAGS += -j2\npre-pr: a b\na:\n\t@echo 'FAIL test_a - AssertionError: 1 != 2'; exit 1\nb:\n\t@sleep 1; sh {script}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "fix: parallel")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("DX_DEADLINE", str(int(time.time()) + 600))
    out_dir, gh_out = tmp_path / "verify", tmp_path / "gh-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    with quiet():
        ap.main(["verify", "run", str(out_dir)])
        ap.main(["verify", "result", str(out_dir)])
    assert "verdict=fail" in gh_out.read_text()
    log = (out_dir / ap.VERIFY_LOG).read_text()
    assert "b writes line 3000" in log
    # Today's tail would have lost it.
    assert "FAIL test_a" not in ap.tail_text(ap.read_end(str(out_dir / ap.VERIFY_LOG)))
    kept = (out_dir / ap.VERIFY_TAIL).read_text()
    assert re.search(r"^make(\[\d+\])?: \*\*\* \[.*Makefile:\d+: a\] Error 1$", kept, re.M), kept[:2000]
    assert kept.index("FAIL test_a") < kept.index("Makefile:4: a] Error 1") < kept.index("b writes line 3000")
    assert len(kept) <= ap.VERIFY_CHARS + 1


def test_an_early_error_in_a_log_past_the_limit_is_still_in_the_excerpt(tmp_path, monkeypatch):
    # #679 C2: past read_end's window, the error in the first lines is read
    # all the same, and the excerpt stays within VERIFY_CHARS.
    ap = autopilot()
    repo, _ = a_repo(tmp_path, "true")
    monkeypatch.chdir(repo)
    out_dir = tmp_path / "verify"
    out_dir.mkdir()
    head = ap.git_out("rev-parse", "HEAD")
    (out_dir / ap.VERIFY_RESULT).write_text(json.dumps({"head": head, "rc": 2}))
    filler = "".join(f"line {i} " + "y" * 200 + "\n" for i in range(ap.VERIFY_CHARS * 4 // 200 + 100))
    log = out_dir / ap.VERIFY_LOG
    log.write_text("lint: checking\nscripts/x.py:3: E999 SyntaxError\nmake: *** [Makefile:7: lint] Error 1\n" + filler)
    assert log.stat().st_size > ap.VERIFY_CHARS * 4
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "gh-output"))
    with quiet():
        assert ap.main(["verify", "result", str(out_dir)]) == 0
    kept = (out_dir / ap.VERIFY_TAIL).read_text()
    assert "verdict=fail" in (tmp_path / "gh-output").read_text()
    assert kept.startswith("lint: checking\nscripts/x.py:3: E999 SyntaxError\nmake: *** [Makefile:7: lint] Error 1\n… (")
    assert len(kept.rstrip("\n")) <= ap.VERIFY_CHARS
    assert kept.rstrip("\n").endswith(filler.splitlines()[-1])
    # And the comment keeps it whole.
    assert "E999 SyntaxError" in ap.prepr_comment("fail", kept, "u", True)


def test_a_passing_run_keeps_the_tail_as_today(tmp_path, monkeypatch):
    # #679 C3: on a pass, even a log with a make failure line in it (a
    # target that is allowed to fail) gives today's tail, and nothing more.
    ap = autopilot()
    script = tmp_path / "out.sh"
    script.write_text("echo 'make: *** [Makefile:9: optional] Error 1 (ignored)'\nfor i in $(seq 1 1000); do echo \"line $i\"; done\n")
    repo, _ = a_repo(tmp_path, f"@sh {script}")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("DX_DEADLINE", str(int(time.time()) + 600))
    out_dir, gh_out = tmp_path / "verify", tmp_path / "gh-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    printed = io.StringIO()
    with quiet():
        ap.main(["verify", "run", str(out_dir)])
    with contextlib.redirect_stdout(printed):
        ap.main(["verify", "result", str(out_dir)])
    assert "verdict=pass" in gh_out.read_text()
    today = ap.tail_text(ap.read_end(str(out_dir / ap.VERIFY_LOG)))
    assert (out_dir / ap.VERIFY_TAIL).read_text() == today + "\n"
    assert printed.getvalue().startswith(today + "\n") and "Error 1 (ignored)" not in today


def test_a_command_the_runner_lacks_is_an_engine_failure_from_verify_to_the_end(tmp_path, monkeypatch):
    # #682 C2: verify reads `not found` in the output and says `engine`;
    # apply keeps the ready back with it, and the end stops, with no fix round.
    ap = autopilot()
    repo, _ = a_repo(tmp_path, "@echo checking; dx-no-such-tool-682 --check")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("DX_DEADLINE", str(int(time.time()) + 600))
    out_dir, gh_out = tmp_path / "verify", tmp_path / "gh-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    with quiet():
        ap.main(["verify", "run", str(out_dir)])
        ap.main(["verify", "result", str(out_dir)])
    assert "verdict=engine" in gh_out.read_text()
    tail = out_dir / ap.VERIFY_TAIL
    assert ap.missing_command(tail.read_text()) == "dx-no-such-tool-682"
    # The verdict reaches apply as verify's output, and the end as apply's.
    apply_env = step("apply", step_id="applied")["env"]["PREPR"]
    assert "needs.verify.outputs.verdict" in apply_env
    assert step("apply", step_id="end")["env"]["PREPR"] == "${{ steps.applied.outputs.prepr }}"
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(json.dumps({"kind": "ready", "text": "Ran it.", "deferred": True}) + "\n")
    finished = []
    real_main = ap.main
    monkeypatch.setattr(ap, "main", lambda argv: finished.append(argv) or 0)
    monkeypatch.setenv("PREPR", "engine")
    gh_out.write_text("")
    with quiet():
        assert ap.apply_outbox(str(outbox), "o/r", "7", "8") == 0
    assert finished == [] and "prepr=engine" in gh_out.read_text()
    monkeypatch.setattr(ap, "main", real_main)
    labels = ["autopilot", "autopilot:run-1", "autopilot:run-2"]
    calls = []

    def fake_gh(*args, input_text=None):
        calls.append(list(args))
        return json.dumps({"comments": []}) if args[1] == "view" else ""

    monkeypatch.setattr(ap, "gh", fake_gh)
    monkeypatch.setattr(ap, "pr_json", lambda repo, pr, fields: {"body": CHECKLIST, "isDraft": True, "headRefOid": "abc",
                                                                 "labels": [{"name": l} for l in labels]})
    monkeypatch.setattr(ap, "refresh_board", lambda repo, number: None)
    monkeypatch.setattr(ap.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(ap.autonomy, "policy_in_force", lambda: {"autopilot-runs": 5})
    for k, v in {"MODE": "continue", "NUMBER": "7", "PR": "8", "RUNS": "2", "PREPR": "engine", "PREPR_TAIL": str(tail),
                 "GITHUB_REPOSITORY": "o/r", "STARTED": "2026-01-01T00:00:00Z", "WORK_RESULT": "success", "AGENT_OUTCOME": "success",
                 "WORK_OUTCOME": "success", "WORK_LOG": str(tmp_path / "none.json")}.items():
        monkeypatch.setenv(k, v)
    for k in ("HEAD_BEFORE", "WHY", "FAILED", "HELD", "CORE"):
        monkeypatch.delenv(k, raising=False)
    gh_out.write_text("")
    with quiet():
        assert ap.main(["end"]) == 0
    assert "verdict=stopped" in gh_out.read_text()
    comments = [c for c in calls if c[:2] == ["pr", "comment"]]
    assert len(comments) == 1
    body = comments[0][comments[0].index("--body") + 1]
    assert body.startswith(ap.PREPR_MARK) and "the runner lacks `dx-no-such-tool-682`" in body
    assert "engine failure" in body and "starts no fix round" in body
    # No fix round, a person has it, and the run is free.
    assert not any("autopilot:continue" in c for c in calls)
    assert ["pr", "edit", "8", "--repo", "o/r", "--add-label", "needs-human"] in calls
    assert ["pr", "edit", "8", "--repo", "o/r", "--remove-label", "autopilot:run-2", "--add-label", "autopilot:free-2"] in calls


def end_after(ap, tmp_path, monkeypatch, before_tail, tail_text_now):
    """`end` of a fix round whose `make pre-pr` failed with tail_text_now,
    after a run whose comment showed before_tail: the verdict and the calls."""
    tail = tmp_path / "tail.txt"
    tail.write_text(tail_text_now)
    earlier = {"author": {"login": ap.BOT}, "body": ap.prepr_comment("fail", before_tail, "u", True), "createdAt": "2026-01-01T00:00:00Z"}
    calls = []

    def fake_gh(*args, input_text=None):
        calls.append(list(args))
        return json.dumps({"comments": [earlier]}) if args[1] == "view" else ""

    monkeypatch.setattr(ap, "gh", fake_gh)
    monkeypatch.setattr(ap, "pr_json", lambda repo, pr, fields: {"body": CHECKLIST, "isDraft": True, "headRefOid": "abc",
                                                                 "labels": [{"name": l} for l in ("autopilot", "autopilot:run-1", "autopilot:free-2", "autopilot:run-3")]})
    monkeypatch.setattr(ap, "refresh_board", lambda repo, number: None)
    monkeypatch.setattr(ap.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(ap.autonomy, "policy_in_force", lambda: {"autopilot-runs": 5})
    gh_out = tmp_path / "gh-output"
    gh_out.write_text("")
    for k, v in {"MODE": "continue", "NUMBER": "7", "PR": "8", "RUNS": "3", "PREPR": "fail", "PREPR_TAIL": str(tail),
                 "GITHUB_REPOSITORY": "o/r", "STARTED": "2026-01-01T02:00:00Z", "WORK_RESULT": "success", "AGENT_OUTCOME": "success",
                 "WORK_OUTCOME": "success", "WORK_LOG": str(tmp_path / "none.json"), "GITHUB_OUTPUT": str(gh_out)}.items():
        monkeypatch.setenv(k, v)
    for k in ("HEAD_BEFORE", "WHY", "FAILED", "HELD", "CORE"):
        monkeypatch.delenv(k, raising=False)
    with quiet():
        assert ap.main(["end"]) == 0
    return gh_out.read_text(), calls


def test_a_fix_round_that_fails_as_the_round_before_stops_and_says_so(tmp_path, monkeypatch):
    # #682 C3, through `end`: the same failing lines, other timings and paths.
    ap = autopilot()
    before = "FAILED tests/test_x.py::test_it in 1.2s - /tmp/pytest-1/x != y\nmake: *** [Makefile:4: test] Error 1\n"
    now = "FAILED tests/test_x.py::test_it in 7.9s - /tmp/pytest-88/x != y\nmake: *** [Makefile:4: test] Error 1\n"
    out, calls = end_after(ap, tmp_path, monkeypatch, before, now)
    assert "verdict=stopped" in out
    body = next(c for c in calls if c[:2] == ["pr", "comment"])[-1]
    assert body.startswith(ap.PREPR_MARK) and "same failure as the round before" in body and "stops rather than start another" in body
    assert not any("autopilot:continue" in c for c in calls)
    assert ["pr", "edit", "8", "--repo", "o/r", "--add-label", "needs-human"] in calls


def test_a_fix_round_that_fails_another_way_continues(tmp_path, monkeypatch):
    ap = autopilot()
    before = "FAILED tests/test_x.py::test_it - AssertionError\nmake: *** [Makefile:4: test] Error 1\n"
    now = "FAILED tests/test_y.py::test_other - KeyError\nmake: *** [Makefile:4: test] Error 1\n"
    out, calls = end_after(ap, tmp_path, monkeypatch, before, now)
    assert "verdict=continue" in out
    assert ["issue", "edit", "7", "--repo", "o/r", "--add-label", "autopilot:continue"] in calls
    assert not any("needs-human" in c for c in calls)
