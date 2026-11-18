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
from pathlib import Path

import yaml

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
    schema = json.loads(claude["with"]["claude_args"].split("--json-schema '", 1)[1].split("'", 1)[0])
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


def test_the_review_does_not_reuse_a_verdict_older_than_a_settlement():
    text = (ROOT / ".github/workflows/claude-review.yml").read_text(encoding="utf-8")
    scope = text[text.index("- name: Scope (previous verdict, range, model)"):]
    scope = scope[:scope.index("- name: The bot's threads from earlier reviews")]
    assert "autopilot.py settlements" in scope and "settled_since" in scope
    reuse = scope[scope.index("mode=full; range=\"\""):]
    assert '[ "$settled_since" = 0 ]' in reuse.split("mode=reuse", 1)[0]
    threads = text[text.index("- name: The bot's threads from earlier reviews"):]
    threads = threads[:threads.index("- name: Brief")]
    assert "settled-threads.json" in threads and "settlements" in threads
