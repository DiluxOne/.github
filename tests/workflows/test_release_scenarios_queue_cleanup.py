"""Issue #936: a scenario's cleanup closes a pull request that sits in the merge queue.

The test repository's merge queue merges up to 3 entries in one group. When
scenario `review-replied` ran `cleanup` on its own pull request while it was
queued, GitHub removed the other scenarios' pull requests of the same group
from the queue unmerged, and `low-risk-merges` ran out its limit. `cleanup`
and `clear` now wait for a queued pull request to leave the queue (at most
QUEUE_LEAVE seconds) before they close it, and close nothing once it merged
or is still queued when the wait runs out (#997: closing it then knocks its
group out all the same; the merge or the next run's `clear` settles it).
Nothing runs: `gh` and `sleep` are fakes.
"""
import importlib.util
import inspect
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = "o/t"


def scenarios():
    spec = importlib.util.spec_from_file_location("release_scenarios", ROOT / "scripts" / "release-scenarios.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Queue:
    """A fake `gh` whose GraphQL read answers from `states`, one per read,
    the last one repeated: (state, isInMergeQueue)."""

    def __init__(self, states, marked_pr=None):
        self.states, self.reads, self.calls, self.slept = list(states), 0, [], 0
        self.marked_pr = marked_pr
        self.closed_while_queued = []

    def now(self):
        return self.states[min(self.reads, len(self.states) - 1)]

    def sleep(self, seconds):
        self.slept += seconds

    def __call__(self, *argv, input=None, **kw):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        if argv[:2] == ["api", "graphql"]:
            state, queued = self.now()
            self.reads += 1
            return json.dumps({"data": {"repository": {"pullRequest": {"state": state, "isInMergeQueue": queued}}}})
        if argv[:2] == ["pr", "close"]:
            # What the read says when it closes (the last read).
            last = self.states[min(max(self.reads - 1, 0), len(self.states) - 1)]
            if last[1]:
                self.closed_while_queued.append(argv[2])
            return ""
        if argv[:2] == ["pr", "list"] and self.marked_pr:
            return json.dumps([{"number": int(self.marked_pr), "body": self.marked_pr_body}])
        if argv[:2] in (["issue", "list"], ["pr", "list"]):
            return "[]"
        return ""

    def closes(self, number):
        return [c for c in self.calls if c[:3] == ["pr", "close", str(number)]]


def napping(fn, sleep):
    """`sleep` for `fn` when it takes one (at the base it does not, and the
    test then fails on its assertion, not on the call)."""
    return {"sleep": sleep} if "sleep" in inspect.signature(fn).parameters else {}


def run_cleanup(mod, fake):
    mod.cleanup(REPO, [("pr", "7")], fake, **napping(mod.cleanup, fake.sleep))


def run_clear(mod, fake):
    fake.marked_pr_body = mod.marked("a scenario's pull request", "x")
    mod.clear(REPO, "x", fake, **napping(mod.clear, fake.sleep))


def test_cleanup_waits_for_a_queued_pull_request_to_leave_the_queue_unmerged_then_closes_it():
    mod = scenarios()
    fake = Queue([("OPEN", True), ("OPEN", True), ("OPEN", False)])
    run_cleanup(mod, fake)
    assert fake.closed_while_queued == [], "cleanup closed #7 while the read said it was in the merge queue"
    assert len(fake.closes(7)) == 1, "cleanup did not close #7 once it left the queue unmerged"
    assert fake.slept > 0


def test_cleanup_closes_nothing_once_the_queued_pull_request_merged():
    mod = scenarios()
    fake = Queue([("OPEN", True), ("MERGED", False)])
    run_cleanup(mod, fake)
    assert fake.closed_while_queued == []
    assert fake.closes(7) == [], "cleanup closed #7, which had merged"


def test_cleanup_leaves_a_pull_request_that_never_leaves_the_queue_open_after_queue_leave():
    mod = scenarios()
    fake = Queue([("OPEN", True)])
    run_cleanup(mod, fake)
    assert fake.closes(7) == [], "cleanup closed #7 while it was still in the merge queue (#997)"
    leave, poll = getattr(mod, "QUEUE_LEAVE", 120), getattr(mod, "QUEUE_POLL", 15)
    assert leave - poll < fake.slept <= leave, f"cleanup gave up on #7 after {fake.slept}s, not after QUEUE_LEAVE"


def test_cleanup_closes_a_pull_request_not_queued_at_once():
    mod = scenarios()
    fake = Queue([("OPEN", False)])
    run_cleanup(mod, fake)
    assert len(fake.closes(7)) == 1 and fake.slept == 0


def test_clear_waits_for_a_marked_queued_pull_request_to_leave_the_queue():
    mod = scenarios()
    fake = Queue([("OPEN", True), ("OPEN", False)], marked_pr="8")
    run_clear(mod, fake)
    assert fake.closed_while_queued == [], "clear closed #8 while the read said it was in the merge queue"
    assert len(fake.closes(8)) == 1


def test_clear_closes_nothing_once_the_marked_pull_request_merged():
    mod = scenarios()
    fake = Queue([("OPEN", True), ("MERGED", False)], marked_pr="8")
    run_clear(mod, fake)
    assert fake.closes(8) == []


def test_clear_leaves_a_marked_pull_request_that_never_leaves_the_queue_open_after_queue_leave():
    mod = scenarios()
    fake = Queue([("OPEN", True)], marked_pr="8")
    run_clear(mod, fake)
    assert fake.closes(8) == [], "clear closed #8 while it was still in the merge queue (#997)"
    leave, poll = getattr(mod, "QUEUE_LEAVE", 120), getattr(mod, "QUEUE_POLL", 15)
    assert leave - poll < fake.slept <= leave, f"clear gave up on #8 after {fake.slept}s, not after QUEUE_LEAVE"


def test_a_read_that_fails_closes_it_as_before():
    mod = scenarios()

    def broken(*argv, input=None, **kw):
        broken.calls.append([str(a) for a in argv])
        if argv[:2] == ("api", "graphql"):
            raise RuntimeError("gh: HTTP 502")
        return ""
    broken.calls = []
    mod.cleanup(REPO, [("pr", "7")], broken, **napping(mod.cleanup, lambda _: None))
    assert [c for c in broken.calls if c[:2] == ["pr", "close"]] == [["pr", "close", "7", "--repo", REPO, "--delete-branch"]]
