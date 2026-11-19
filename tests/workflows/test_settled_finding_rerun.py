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
