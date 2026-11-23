"""Issue #997: the release candidate v7.23.1 fails `low-risk-merges`.

#987 gave `clear`'s sweep of earlier runs' orphan lane pull requests
(`lane_leftovers`) the same `closer`, and so the same QUEUE_LEAVE budget,
as the scenario's own marked pull requests: an orphan that sits in the
merge queue spends the whole wait, and the scenario's own queued pull
request is then closed at once, which knocks the other pull requests of
its merge group (`low-risk-merges`' among them) out of the queue unmerged
(#936 again). And once the wait runs out, `closer` closed a pull request
still in the queue anyway. Now a cleanup never closes a pull request that
is in the merge queue: when the wait runs out it is left open, for the
merge or the next run's `clear`; and the lane sweep has a wait of its own.
Nothing runs: `gh` and `sleep` are fakes.
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = "o/t"
SID = "bug-reproduced"
ORPHAN, OWN, REPORT = 41, 42, 40


def scenarios():
    spec = importlib.util.spec_from_file_location("release_scenarios", ROOT / "scripts" / "release-scenarios.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Repo:
    """A fake `gh`: every pull request reads OPEN and in the merge queue on
    every poll; an earlier run's orphan lane pull request (#41, from report
    #40 which carries the mark) and the scenario's own marked one (#42)."""

    def __init__(self, mod):
        self.mod, self.calls, self.slept = mod, [], 0
        self.polls = {}

    def sleep(self, seconds):
        self.slept += seconds

    def __call__(self, *argv, input=None, **kw):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        if argv[:2] == ["api", "graphql"]:
            number = int(next(a for a in argv if a.startswith("number=")).split("=", 1)[1])
            self.polls[number] = self.polls.get(number, 0) + 1
            return json.dumps({"data": {"repository": {"pullRequest": {"state": "OPEN", "isInMergeQueue": True}}}})
        if argv[:2] == ["issue", "view"] and argv[2] == str(REPORT):
            return json.dumps({"body": self.mod.marked("the report", SID)})
        if argv[:2] == ["pr", "list"] and "--search" in argv:
            return json.dumps([{"number": OWN, "body": self.mod.marked("the scenario's pull request", SID)}])
        if argv[:2] == ["pr", "list"]:
            return json.dumps([{"number": ORPHAN, "headRefName": f"fix/39-the-bug-reproduced-from-{REPORT}"}])
        if argv[:2] == ["issue", "list"]:
            return "[]"
        return ""

    def closes(self, number):
        return [c for c in self.calls if c[:3] == ["pr", "close", str(number)]]


def test_clear_never_closes_a_queued_pull_request_and_the_orphans_wait_is_its_own():
    mod = scenarios()
    fake = Repo(mod)
    mod.clear(REPO, SID, fake, sleep=fake.sleep)
    assert fake.closes(ORPHAN) == [], "clear closed the orphan lane pull request while it sat in the merge queue"
    assert fake.closes(OWN) == [], "clear closed the scenario's own pull request while it sat in the merge queue"
    assert fake.polls.get(OWN, 0) > 1, "the orphan's wait used up the scenario's own pull request's: it was never waited on"


def test_cleanup_leaves_a_pull_request_that_never_leaves_the_queue_open():
    mod = scenarios()
    fake = Repo(mod)
    mod.cleanup(REPO, [("pr", "7")], fake, sleep=fake.sleep)
    assert fake.closes(7) == [], "cleanup closed #7 while it was still in the merge queue, after QUEUE_LEAVE"
    assert 0 < fake.slept <= mod.QUEUE_LEAVE
