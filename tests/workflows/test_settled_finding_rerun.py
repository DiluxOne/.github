"""A review finding that someone who decides settles in a comment re-runs
the review on the same head (#699 C5). review-reply.yml's reply, when its
verdict settles one of the review's findings (it resolves the bot's thread,
or names a finding with no thread), records a hidden `dx-settled` mark with
the answer's link; when the commenter decides (scripts/deciders.py) and the
review blocked at the current head, it re-runs that head's review job. On
that re-run claude-review.yml does not reuse the previous verdict, since a
settlement is newer than it, and the settled findings reach the brief with
SETTLED_THREADS so the review does not raise them again."""
import importlib.util
import json
import shlex
from pathlib import Path
from unittest import mock

import yaml

try:
    import steps  # tests/workflows/steps.py: it runs a workflow's step with stubs
except ModuleNotFoundError:  # Test first's base has no steps.py (#845): there each call to it fails an assertion
    steps = mock.Mock(**{f"{n}.side_effect": AssertionError("tests/workflows/steps.py is missing") for n in ("evaluate", "run", "step", "workflow")})
run, step = steps.run, steps.step

ROOT = Path(__file__).resolve().parents[2]
BOT = "dilux-bot[bot]"


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


autopilot = load("autopilot_c5", "autopilot.py")


def reply_steps():
    return yaml.safe_load((ROOT / ".github/workflows/review-reply.yml").read_text(encoding="utf-8"))["jobs"]["reply"]["steps"]


def test_the_mark_names_the_finding_and_the_answer_and_reads_back():
    mark = autopilot.settled_mark("The cap is not checked --> <b>", "https://github.com/o/r/pull/8#issuecomment-5")
    assert mark.startswith("<!-- dx-settled ") and mark.endswith(" -->") and mark.count("-->") == 1
    comments = [
        {"user": {"login": BOT}, "body": "Old reply\n" + autopilot.settled_mark("old", "u0"), "created_at": "2026-11-08T09:00:00Z"},
        {"user": {"login": BOT}, "body": "Reply\n" + mark, "created_at": "2026-11-08T11:00:00Z"},
        {"user": {"login": "mallory"}, "body": autopilot.settled_mark("forged", "u1"), "created_at": "2026-11-08T12:00:00Z"},
    ]
    got = autopilot.settlements(comments, "2026-11-08T10:00:00Z", BOT)
    assert [g["answer"] for g in got] == ["https://github.com/o/r/pull/8#issuecomment-5"]
    assert "-->" not in got[0]["finding"]
    assert len(autopilot.settlements(comments, "", BOT)) == 2


def test_the_reply_records_the_settlement_and_reruns_the_blocking_review():
    steps = reply_steps()
    claude = next(s for s in steps if s.get("id") == "claude")
    args = shlex.split(claude["with"]["claude_args"])
    schema = json.loads(args[args.index("--json-schema") + 1])
    assert "settles" in schema["properties"]
    post = next(s for s in steps if s.get("id") == "post")["run"]
    assert "autopilot.py settled-mark" in post and "settled=true" in post
    rerun = next(s for s in steps if s.get("name") == "Re-run the review on a settled finding")
    assert "steps.post.outputs.settled == 'true'" in str(rerun["if"])
    run = rerun["run"]
    assert "deciders.py may answer" in run
    assert "dx-review-record" in run and ".blocking" in run and '"$HEAD"' in run
    assert "rerun-failed-jobs" in run
    token = next(s for s in steps if s.get("id") == "rerunner")
    assert token["with"]["permission-actions"] == "write"


REVIEWED = "<!-- dx-review -->\nBlocked.\n<!-- dx-review-record " + json.dumps(
    {"sha": "h" * 40, "count": 1, "risk": "high", "complexity": "low", "blocking": True}) + " -->"


def scope(tmp_path, comments):
    """claude-review.yml's scope step at the head the last verdict was of,
    with gh answering COMMENTS for the pull request's comments."""
    (tmp_path / "comments.json").write_text(json.dumps(comments))
    gh = f"""case "$1 $2" in
  "api repos/o/r/issues/8/comments") cat {tmp_path}/comments.json ;;
  "api repos/o/r/pulls/8/comments") echo '[]' ;;
  "pr view") echo false ;;
  *) echo "unexpected gh $*" >&2; exit 1 ;;
esac"""
    env = {"BOT": BOT, "PR": "8", "HEAD": "h" * 40, "ACTION": "synchronize", "MAX_AUTO": "5", "MODEL": "m", "EFFORT": "low"}
    return run(step("claude-review.yml", "scope"), tmp_path, env=env, stubs={"gh": gh})


def test_the_review_reuses_the_verdict_of_its_head_with_nothing_settled(tmp_path):
    ran = scope(tmp_path, [{"user": {"login": BOT}, "body": REVIEWED, "updated_at": "2026-11-08T10:00:00Z"}])
    assert ran.code == 0, ran.stderr
    assert ran.output["mode"] == "reuse"


def test_the_review_does_not_reuse_a_verdict_older_than_a_settlement(tmp_path):
    settled = "Settled.\n" + autopilot.settled_mark("The cap is not checked", "https://github.com/o/r/pull/8#issuecomment-5")
    comments = [{"user": {"login": BOT}, "body": REVIEWED, "updated_at": "2026-11-08T10:00:00Z"},
                {"user": {"login": BOT}, "body": settled, "created_at": "2026-11-08T11:00:00Z", "updated_at": "2026-11-08T11:00:00Z"}]
    ran = scope(tmp_path, comments)
    assert ran.code == 0, ran.stderr
    assert ran.output["mode"] == "full"
    assert "1 finding(s) settled since the last verdict" in ran.stdout


def test_a_mark_typed_by_someone_else_does_not_stop_the_reuse(tmp_path):
    forged = autopilot.settled_mark("forged", "u1")
    comments = [{"user": {"login": BOT}, "body": REVIEWED, "updated_at": "2026-11-08T10:00:00Z"},
                {"user": {"login": "mallory"}, "body": forged, "created_at": "2026-11-08T11:00:00Z"}]
    assert scope(tmp_path, comments).output["mode"] == "reuse"


def test_the_settled_findings_reach_the_brief_as_settled_threads(tmp_path):
    (tmp_path / "temp").mkdir()
    (tmp_path / "temp" / "settlement-comments.json").write_text(json.dumps(
        [{"user": {"login": BOT}, "body": autopilot.settled_mark("The cap is not checked", "https://x/5"), "created_at": "2026-11-08T11:00:00Z"}]))
    threads = {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}
    (tmp_path / "threads.json").write_text(json.dumps(threads))
    ran = run(step("claude-review.yml", "The bot's threads from earlier reviews"), tmp_path,
              env={"PR": "8", "SLUG": BOT.removesuffix("[bot]")}, stubs={"gh": f"cat {tmp_path}/threads.json"})
    assert ran.code == 0, ran.stderr
    settled = json.loads((tmp_path / "temp" / "settled-threads.json").read_text())
    assert [t["finding"] for t in settled] == ["The cap is not checked"]
    assert settled[0]["replies"][0]["body"] == "https://x/5"


# #871: `settled-rerun` settles, in the pull request's conversation, a finding
# the review posted inline as a thread of its own. The reply must see the
# bot's open threads, record the settlement and resolve the finding's thread.
THREAD_ID = "PRRT_kwDOtoken"
NODES = [
    {"id": THREAD_ID, "isResolved": False, "path": "app/token.py", "line": 12,
     "comments": {"nodes": [{"databaseId": 1, "author": {"login": BOT.removesuffix("[bot]")},
                             "body": "**blocker**: The token is written to the log\n\nIt leaks."}]}},
    {"id": "PRRT_done", "isResolved": True, "path": "a.py", "line": 1,
     "comments": {"nodes": [{"databaseId": 2, "author": {"login": BOT.removesuffix("[bot]")}, "body": "**major**: Old\n\nx"}]}},
    {"id": "PRRT_human", "isResolved": False, "path": "b.py", "line": 2,
     "comments": {"nodes": [{"databaseId": 3, "author": {"login": "alice"}, "body": "**blocker**: Not the bot"}]}},
]


def pr_and_thread(tmp_path):
    """review-reply.yml's "Pull request and thread" on an issue_comment, gh
    answering the repository, the conversation and the review threads."""
    (tmp_path / "nodes.jsonl").write_text("\n".join(json.dumps(n) for n in NODES) + "\n")
    gh = f"""case "$*" in
  *headRepository*) echo o/r ;;
  "pr view"*"--json comments"*) echo '{{"comments":[{{"author":"alice","body":"@dilux-bot settled"}}]}}' ;;
  "api graphql"*) cat {tmp_path}/nodes.jsonl ;;
  *) echo "unexpected gh $*" >&2; exit 1 ;;
esac"""
    env = {"SLUG": BOT.removesuffix("[bot]"), "PR": "8", "COMMENT_ID": "5", "EVENT": "issue_comment"}
    return run(step("review-reply.yml", "pr"), tmp_path, env=env, stubs={"gh": gh})


def test_a_conversation_comment_shows_the_reply_the_bots_open_threads(tmp_path):
    ran = pr_and_thread(tmp_path)
    assert ran.code == 0, ran.stderr
    assert ran.output.get("run") == "true"
    thread = json.loads((ran.temp / "thread.json").read_text())
    assert thread.get("comments"), thread
    assert [t["id"] for t in thread.get("review_threads", [])] == [THREAD_ID]
    first = thread["review_threads"][0]
    assert first["path"] == "app/token.py" and first["line"] == 12
    assert first["comment"].startswith("**blocker**: The token is written to the log")
    saved = ran.temp / "bot-threads.json"
    assert saved.exists(), "the bot's open threads are not saved for the post step"
    assert [t["id"] for t in json.loads(saved.read_text())] == [THREAD_ID]


def post(tmp_path, settles, threads):
    """review-reply.yml's "Post the reply" on an issue_comment whose verdict
    SETTLES, with THREADS the bot's open threads the first step saved."""
    (tmp_path / "temp").mkdir(parents=True, exist_ok=True)
    (tmp_path / "temp" / "bot-threads.json").write_text(json.dumps(threads))
    out = json.dumps({"reply": "Fixed: the token is no longer logged.", "resolve": False, "settles": settles})
    env = {"OUT": out, "PR": "8", "THREAD": "", "BOT_THREAD": "false", "COMMENT_ID": "5",
           "EVENT": "issue_comment", "MODEL": "m", "GH_TOKEN": "t", "GITHUB_SERVER_URL": "https://github.com"}
    return run(step("review-reply.yml", "post"), tmp_path, env=env, stubs={"gh": "true"})


BOT_THREADS = [{"id": THREAD_ID, "path": "app/token.py", "line": 12,
                "comment": "**blocker**: The token is written to the log\n\nIt leaks."}]


def test_settling_a_finding_with_a_thread_in_the_conversation_reruns_and_resolves_it(tmp_path):
    ran = post(tmp_path, "The token is written to the log", BOT_THREADS)
    assert ran.code == 0, ran.stderr
    assert ran.output.get("settled") == "true"
    body = ran.of("gh")[0]
    assert body[:2] == ["pr", "comment"]
    assert "<!-- dx-settled " in body[body.index("--body") + 1]
    assert ran.output.get("resolve") == "true"
    assert (ran.temp / "resolve.txt").exists() and (ran.temp / "resolve.txt").read_text().strip() == THREAD_ID


def test_settling_a_finding_with_no_thread_still_settles_and_resolves_nothing(tmp_path):
    ran = post(tmp_path, "The changelog is missing", BOT_THREADS)
    assert ran.code == 0, ran.stderr
    assert ran.output.get("settled") == "true"
    body = ran.of("gh")[0]
    assert "<!-- dx-settled " in body[body.index("--body") + 1]
    assert "resolve" not in ran.output
    assert not (ran.temp / "resolve.txt").exists()


def test_a_title_that_only_begins_another_finding_resolves_nothing(tmp_path):
    ran = post(tmp_path, "The token", BOT_THREADS)
    assert ran.code == 0, ran.stderr
    assert ran.output.get("settled") == "true"
    assert "resolve" not in ran.output


# #882: the settlement can reach the re-run while the review's run is still
# going (the review posts its summary before its job ends, and the run's
# other jobs go on after it). The step finds the head's review check whatever
# its status, waits, bounded, for its run to complete, and only then posts
# the re-run; a run that never completes fails the step with `::error::`; a
# review that did not block at the head stays a quiet exit.
HEAD = "a" * 40
RUN = 55

# deciders.py stood in: the commenter decides.
DECIDERS = "import sys\nsys.exit(0)\n"

# `gh` stood in: answers from files in DATA, applying `--jq` as gh does, and
# answers the review run's status from the next line of statuses.txt (the
# last line once they run out).
GH = r"""data="{data}"
q=""; prev=""
for a in "$@"; do [ "$prev" = --jq ] && q=$a; prev=$a; done
emit() {{ if [ -n "$q" ]; then jq -r "$q" "$1"; else cat "$1"; fi; }}
case "$*" in
  "pr view"*closingIssuesReferences*) echo "" ;;
  "pr view"*headRefOid*) echo "{head}" ;;
  "api repos/o/r/issues/9/comments"*) emit "$data/comments.json" ;;
  "api repos/o/r/commits/{head}/check-runs"*) emit "$data/checks.json" ;;
  "api -X POST repos/o/r/actions/runs/{run}/rerun-failed-jobs"*) echo "{{}}" ;;
  "api repos/o/r/actions/runs/{run}"*)
    n=$(cat "$data/polls" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$data/polls"
    s=$(sed -n "${{n}}p" "$data/statuses.txt"); [ -n "$s" ] || s=$(tail -1 "$data/statuses.txt")
    printf '{{"id": {run}, "status": "%s"}}\n' "$s" > "$data/run.json"
    emit "$data/run.json" ;;
  *) echo "unexpected gh $*" >&2; exit 1 ;;
esac
"""


def rerun_step():
    return step("review-reply.yml", "Re-run the review on a settled finding")


def play(tmp_path, *, statuses, blocking=True, check_status="in_progress"):
    data = tmp_path / "data"
    data.mkdir()
    record = json.dumps({"sha": HEAD, "blocking": blocking})
    (data / "comments.json").write_text(json.dumps([
        {"user": {"login": BOT}, "body": f"<!-- dx-review -->\nSummary\n<!-- dx-review-record {record} -->"}]))
    (data / "checks.json").write_text(json.dumps({"check_runs": [
        {"name": "test / Claude review", "status": check_status,
         "details_url": f"https://github.com/o/r/actions/runs/{RUN}/job/1"}]}))
    (data / "statuses.txt").write_text("\n".join(statuses) + "\n")
    gh = GH.format(data=data, head=HEAD, run=RUN)
    return run(rerun_step(), tmp_path, central=False,
               files={".dx-central/scripts/deciders.py": DECIDERS},
               stubs={"gh": gh, "sleep": "exit 0"},
               env={"GH_TOKEN": "t", "PR": "9", "LOGIN": "maintainer", "BOT": BOT})


def gh_calls(ran):
    return [" ".join(c) for c in ran.of("gh")]


def rerun_posted(ran):
    return [i for i, c in enumerate(gh_calls(ran)) if c.startswith(f"api -X POST repos/o/r/actions/runs/{RUN}/rerun-failed-jobs")]


def polls(ran):
    return [i for i, c in enumerate(gh_calls(ran)) if c.startswith(f"api repos/o/r/actions/runs/{RUN}")]


def test_rerun_waits_for_an_in_progress_review_run_then_posts(tmp_path):
    ran = play(tmp_path, statuses=["in_progress", "completed"])
    assert ran.code == 0, ran.stdout + ran.stderr
    posted = rerun_posted(ran)
    assert len(posted) == 1, gh_calls(ran)
    seen = polls(ran)
    assert len(seen) == 2, gh_calls(ran)
    # Posted only after the run reported `completed` (the second poll).
    assert posted[0] > seen[1], gh_calls(ran)
    assert ran.of("sleep"), "the step waits between polls"


def test_a_run_that_never_completes_fails_the_step_without_a_rerun(tmp_path):
    ran = play(tmp_path, statuses=["in_progress"])
    assert ran.code != 0
    assert "::error::" in ran.stdout + ran.stderr
    assert not rerun_posted(ran), gh_calls(ran)


def test_a_review_that_did_not_block_still_exits_quietly(tmp_path):
    ran = play(tmp_path, statuses=["completed"], blocking=False)
    assert ran.code == 0, ran.stdout + ran.stderr
    assert not rerun_posted(ran)
    assert "::error::" not in ran.stdout + ran.stderr
