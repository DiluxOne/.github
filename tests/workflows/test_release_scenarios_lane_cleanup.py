"""Issue #985: a scenario's cleanup reaches the issue the engine opened from its own.

The `bug-reproduced` scenario opens a bug report; the reproduction opens a
second issue, "The bug reproduced from #<report>", labelled
`lane:bugfix-reproduced`, and the autopilot's pull request closes that one.
`cleanup` closed only the scenario's own issues and the pull requests that
close them, so every release run left one open pull request behind in the
test repository. Nothing runs: `gh` and `sleep` are fakes.
"""
import importlib.util
import inspect
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = "o/t"
LABEL = "lane:bugfix-reproduced"


def scenarios():
    spec = importlib.util.spec_from_file_location("release_scenarios", ROOT / "scripts" / "release-scenarios.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ref(number):
    return {"number": number, "url": f"https://github.com/{REPO}/pull/{number}"}


class Fake:
    """A fake `gh` over a test repository: `lanes`, the open lane issues
    (number, title); `closes`, which pull requests close which issue;
    `states`, the merge-queue reads of each pull request, one per read, the
    last one repeated: (state, isInMergeQueue); `bodies`, the issues'
    bodies; `pulls`, the open pull requests (number, headRefName)."""

    def __init__(self, lanes=(), closes=None, states=None, bodies=None, pulls=()):
        self.lanes, self.closing, self.states = list(lanes), dict(closes or {}), dict(states or {})
        self.bodies, self.pulls = dict(bodies or {}), list(pulls)
        self.calls, self.reads, self.slept, self.closed_while_queued = [], {}, 0, []

    def sleep(self, seconds):
        self.slept += seconds

    def state(self, number, advance):
        seq = self.states.get(str(number), [("OPEN", False)])
        n = self.reads.get(str(number), 0)
        if advance:
            self.reads[str(number)] = n + 1
            return seq[min(n, len(seq) - 1)]
        return seq[min(max(n - 1, 0), len(seq) - 1)]

    def __call__(self, *argv, input=None, **kw):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        if argv[:2] == ["api", "graphql"]:
            number = [m.group(1) for m in map(re.compile(r"^number=(\d+)$").match, argv) if m][0]
            state, queued = self.state(number, True)
            return json.dumps({"data": {"repository": {"pullRequest": {"state": state, "isInMergeQueue": queued}}}})
        if argv[:2] == ["pr", "close"]:
            if self.state(argv[2], False)[1]:
                self.closed_while_queued.append(argv[2])
            return ""
        if argv[:2] == ["issue", "list"]:
            if LABEL in argv:
                return json.dumps([{"number": n, "title": t} for n, t in self.lanes])
            return "[]"
        if argv[:2] == ["pr", "list"]:
            if "--search" in argv:
                return "[]"
            return json.dumps([{"number": n, "headRefName": b} for n, b in self.pulls])
        if argv[:2] == ["issue", "view"]:
            number = argv[2]
            return json.dumps({"closedByPullRequestsReferences": [ref(p) for p in self.closing.get(number, [])],
                               "body": self.bodies.get(number, "")})
        return ""

    def pr_closes(self, number):
        return [c for c in self.calls if c[:3] == ["pr", "close", str(number)]]

    def did(self, verb, number):
        return [c for c in self.calls if c[:3] == ["issue", verb, str(number)]]


def napping(fn, sleep):
    """`sleep` for `fn` when it takes one."""
    return {"sleep": sleep} if "sleep" in inspect.signature(fn).parameters else {}


def run_cleanup(mod, fake):
    mod.cleanup(REPO, [("issue", "5")], fake, **napping(mod.cleanup, fake.sleep))


def lane_fake(states=None):
    return Fake(lanes=[(20, "The bug reproduced from #5"), (30, "The bug reproduced from #50")],
                closes={"20": [21], "30": [31]}, states=states)


# C1

def test_cleanup_closes_the_lane_issue_and_its_pull_request_with_its_branch():
    mod = scenarios()
    fake = lane_fake()
    run_cleanup(mod, fake)
    assert fake.pr_closes(21) == [["pr", "close", "21", "--repo", REPO, "--delete-branch"]], \
        "the autopilot's pull request that closes the lane issue #20 is left open"
    assert fake.did("close", 20) and fake.did("lock", 20), "the lane issue #20 is not closed and locked"
    assert fake.did("close", 5) and fake.did("lock", 5), "the scenario's own issue #5 is no longer closed and locked"


def test_cleanup_leaves_another_reports_lane_issue_alone():
    mod = scenarios()
    fake = lane_fake()
    run_cleanup(mod, fake)
    assert fake.pr_closes(31) == [] and fake.did("close", 30) == [] and fake.did("lock", 30) == [], \
        "\"The bug reproduced from #50\" is not #5's: cleanup closed it"


def test_cleanup_lists_lane_issues_by_label_never_by_search():
    mod = scenarios()
    fake = lane_fake()
    run_cleanup(mod, fake)
    lists = [c for c in fake.calls if c[:2] == ["issue", "list"]]
    assert lists and all(LABEL in c and "--search" not in c for c in lists)


def test_cleanup_closes_the_lane_issues_pull_request_before_the_report():
    mod = scenarios()
    fake = lane_fake()
    run_cleanup(mod, fake)
    order = [tuple(c[:3]) for c in fake.calls if c[:2] in (["pr", "close"], ["issue", "close"])]
    assert {("pr", "close", "21"), ("issue", "close", "20"), ("issue", "close", "5")} <= set(order), order
    assert order.index(("pr", "close", "21")) < order.index(("issue", "close", "20")) < order.index(("issue", "close", "5"))


def test_a_failed_lane_list_never_keeps_the_report_open():
    mod = scenarios()

    def broken(*argv, input=None, **kw):
        broken.calls.append([str(a) for a in argv])
        if argv[:2] == ("issue", "list"):
            raise RuntimeError("gh: HTTP 502")
        return ""
    broken.calls = []
    mod.cleanup(REPO, [("issue", "5")], broken, **napping(mod.cleanup, lambda _: None))
    assert ["issue", "close", "5", "--repo", REPO] in broken.calls


# C2

def test_cleanup_waits_for_the_lane_pull_request_to_leave_the_queue_then_closes_it():
    mod = scenarios()
    fake = lane_fake(states={"21": [("OPEN", True), ("OPEN", True), ("OPEN", False)]})
    run_cleanup(mod, fake)
    assert fake.closed_while_queued == [], "cleanup closed #21 while the read said it was in the merge queue"
    assert len(fake.pr_closes(21)) == 1, "cleanup did not close #21 once it left the queue unmerged"
    assert fake.slept > 0


def test_cleanup_never_closes_a_merged_lane_pull_request():
    mod = scenarios()
    fake = lane_fake(states={"21": [("OPEN", True), ("MERGED", False)]})
    run_cleanup(mod, fake)
    assert fake.pr_closes(21) == [], "cleanup closed #21, which had merged"
    assert fake.did("close", 20) and fake.did("lock", 20)
    assert any(c[:2] == ["api", "graphql"] and "number=21" in c for c in fake.calls), "the lane's pull request was never read"


# C3

SID = "bug-reproduced"


def run_clear(mod, fake):
    mod.clear(REPO, SID, fake, **napping(mod.clear, fake.sleep))


def sweep_fake(mod):
    """Lane issue #30 already closed (no open lane issue), its pull request
    #40 still open; #41 another scenario's; Dependabot's and the callers'
    sync, no scenario's."""
    return Fake(pulls=[(40, "fix/30-the-bug-reproduced-from-4"), (41, "fix/31-the-bug-reproduced-from-6"),
                       (42, "dependabot/x"), (43, "chore/sync-callers")],
                bodies={"4": mod.marked("the report", SID), "6": mod.marked("another report", "another-scenario")})


def test_clear_closes_an_earlier_runs_orphaned_lane_pull_request_with_its_branch():
    mod = scenarios()
    fake = sweep_fake(mod)
    run_clear(mod, fake)
    closed = [c for c in fake.calls if c[:2] == ["pr", "close"]]
    assert closed == [["pr", "close", "40", "--repo", REPO, "--delete-branch"]], \
        f"clear should close the orphaned lane pull request #40 alone, with its branch: {closed}"


def test_clear_reads_each_report_once():
    mod = scenarios()
    fake = sweep_fake(mod)
    fake.pulls.append((44, "fix/32-the-bug-reproduced-from-4"))
    run_clear(mod, fake)
    assert len(fake.did("view", 4)) == 1, "the report #4 was read more than once"
    assert len(fake.pr_closes(44)) == 1 and fake.did("view", 6)


def test_clear_closes_and_locks_an_open_lane_issue_and_closes_its_pull_request():
    mod = scenarios()
    fake = Fake(lanes=[(20, "The bug reproduced from #5")], closes={"20": [21]}, pulls=[(21, "fix/20-the-bug-reproduced-from-5")],
                bodies={"5": mod.marked("the report", SID)})
    run_clear(mod, fake)
    assert fake.did("close", 20) and fake.did("lock", 20), "the lane issue #20 is not closed and locked"
    assert len(fake.pr_closes(21)) == 1, "the lane issue's pull request #21 was not closed, or closed twice"


def test_a_failed_pull_request_list_never_stops_clear():
    mod = scenarios()

    def broken(*argv, input=None, **kw):
        broken.calls.append([str(a) for a in argv])
        if argv[:2] == ("pr", "list") and "--search" not in argv:
            raise RuntimeError("gh: HTTP 502")
        return "[]" if argv[1:2] == ("list",) else ""
    broken.calls = []
    mod.clear(REPO, SID, broken, **napping(mod.clear, lambda _: None))
    assert [c for c in broken.calls if c[:2] == ["pr", "close"]] == []
