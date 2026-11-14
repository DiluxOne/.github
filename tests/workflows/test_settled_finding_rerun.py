"""A review finding settled by someone who decides re-runs the review on the
same head (#699 C5): review-reply.yml's reply carries dilux-bot's hidden
`dx-settled` mark when the answer settles a finding (its thread resolved,
or one settled outside the code with no thread), runs that head's failed
review again, and claude-review.yml does not reuse its verdict while a
settlement newer than it exists. Played with the jobs' own scripts, GitHub
and the engine's scripts stood in for where they would be called."""
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
HEAD = "a" * 40


def load():
    spec = importlib.util.spec_from_file_location("review_settled", ROOT / "scripts" / "review-settled.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


settled = load()


def reply_steps():
    return yaml.safe_load((ROOT / ".github/workflows/review-reply.yml").read_text(encoding="utf-8"))["jobs"]["reply"]["steps"]


def by_name(steps, name):
    return next(s for s in steps if s.get("name") == name)


GH = r"""#!/usr/bin/env bash
echo "$*" >> "$LOG"
case "$*" in
  *"--json closingIssuesReferences"*) echo 4 ;;
  *"--json headRefOid"*) echo "$HEADSHA" ;;
  "api repos/o/r/issues/9/comments --paginate") printf '%s' "$COMMENTS" ;;
  "api repos/o/r/actions/runs?"*) printf '%s\n' 71 70 ;;
  "api repos/o/r/actions/runs/71/jobs"*) : ;;
  "api repos/o/r/actions/runs/70/jobs"*) echo 5 ;;
  *) : ;;
esac
"""


def play(run, env_extra, decides="yes"):
    with tempfile.TemporaryDirectory() as d:
        bin_ = Path(d, "bin")
        bin_.mkdir()
        gh = bin_ / "gh"
        gh.write_text(GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        scripts = Path(d, ".dx-central", "scripts")
        scripts.mkdir(parents=True)
        shutil.copy(ROOT / "scripts" / "review-settled.py", scripts)
        (scripts / "deciders.py").write_text(f"import sys\nsys.exit({0 if decides == 'yes' else 1})\n")
        tmp = Path(d, "tmp")
        tmp.mkdir()
        (tmp / "thread.json").write_text(json.dumps({"path": "a.py", "line": 3}))
        log, out = Path(d, "log"), Path(d, "out")
        log.write_text("")
        out.write_text("")
        env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "LOG": str(log), "GITHUB_OUTPUT": str(out), "GITHUB_REPOSITORY": "o/r",
               "RUNNER_TEMP": str(tmp), "GITHUB_SERVER_URL": "https://github.com", "GITHUB_RUN_ID": "1", "HEADSHA": HEAD,
               "DX_BOT_LOGIN": "dilux-bot[bot]", "PR": "9", "COMMENT_ID": "11", "COMMENT_URL": "https://github.com/o/r/pull/9#issuecomment-11",
               "LOGIN": "boss", "MODEL": "m", "THREAD": "", "BOT_THREAD": "false", "EVENT": "issue_comment", **env_extra}
        r = subprocess.run(["bash", "-c", run], cwd=d, env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return log.read_text(), out.read_text()


def post(out, **k):
    return play(by_name(reply_steps(), "Post the reply")["run"], {"OUT": json.dumps(out), **k.get("env", {})}, k.get("decides", "yes"))


def test_a_deciders_answer_that_settles_a_finding_outside_the_code_carries_the_mark():
    calls, outputs = post({"reply": "Agreed: it is #695's.", "resolve": False, "settles": "The credits miss a co-author"})
    assert "settled=true" in outputs and f"head={HEAD}" in outputs
    posted = calls[calls.index("pr comment 9"):]
    assert "<!-- dx-settled " in posted and "The credits miss a co-author" in posted


def test_a_resolved_thread_settles_its_finding_too():
    _, outputs = post({"reply": "Right.", "resolve": True}, env={"THREAD": "T1", "BOT_THREAD": "true", "EVENT": "pull_request_review_comment"})
    assert "settled=true" in outputs


def test_nothing_is_settled_by_someone_who_does_not_decide_nor_by_a_plain_reply():
    assert "settled=true" not in post({"reply": "x", "resolve": False, "settles": "F"}, decides="no")[1]
    calls, outputs = post({"reply": "x", "resolve": False})
    assert "settled=true" not in outputs and "dx-settled" not in calls


def test_the_review_runs_again_on_the_same_head_when_it_blocked_there():
    rerun = by_name(reply_steps(), "Run the review again on the same head")["run"]
    record = lambda sha, blocking: json.dumps([{"user": {"login": "dilux-bot[bot]"}, "body": "<!-- dx-review -->\n<!-- dx-review-record " + json.dumps({"sha": sha, "blocking": blocking}) + " -->"}])
    calls, _ = play(rerun, {"HEAD": HEAD, "COMMENTS": record(HEAD, True)})
    assert "run rerun 70 --failed --repo o/r" in calls
    for sha, blocking in ((HEAD, False), ("b" * 40, True)):
        calls, _ = play(rerun, {"HEAD": HEAD, "COMMENTS": record(sha, blocking)})
        assert "run rerun" not in calls
    token = by_name(reply_steps(), "A token to run the review again")
    assert token["with"]["permission-actions"] == "write" and token["if"] == "steps.post.outputs.settled == 'true'"


def test_the_review_does_not_reuse_its_verdict_past_a_newer_settlement():
    job = yaml.safe_load((ROOT / ".github/workflows/claude-review.yml").read_text(encoding="utf-8"))["jobs"]["review"]
    scope = next(s for s in job["steps"] if s.get("id") == "scope")["run"]
    assert "review-settled.py read" in scope and "mode=full" in scope[scope.index("review-settled.py read"):]
    assert '[ "$ACTION" != edited ]' in scope
    threads = by_name(job["steps"], "The bot's threads from earlier reviews")["run"]
    assert '"$RUNNER_TEMP/settled.json"' in threads and "settled-threads.json" in threads
    verdict = next(s for s in job["steps"] if s.get("id") == "verdict")
    assert "settled:$settled" in verdict["run"] and verdict["env"]["SETTLED"] == "${{ steps.scope.outputs.settled || '[]' }}"
    m = settled.mark("F", "u", HEAD)
    comments = [{"id": 5, "user": {"login": "dilux-bot[bot]"}, "body": m}]
    assert settled.read(comments, "dilux-bot[bot]", HEAD, {"sha": HEAD, "settled": []})["newer"] is True
    assert settled.read(comments, "dilux-bot[bot]", HEAD, {"sha": HEAD, "settled": [5]})["newer"] is False
