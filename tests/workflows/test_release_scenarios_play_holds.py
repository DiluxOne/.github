"""#878 C1: the release lane's `play` holds on GitHub's side. A group's play
step (release-scenarios.py play, with the `--minutes` release-lane.yml
passes) stops, writes its results and exits before its deadline even when
its scenario fails once and its setup and cleanup take minutes; a rate
limited `gh` in the cleanup is retried and kills nothing; a SIGTERM (GitHub
signals a step past its timeout before it kills it) leaves `results.md`
with a failing `infrastructure` row; and the real plan's calls, setup,
cleanup and the retry included, stay under the test identity's RATE_LIMIT.
`gh` and the clock are stubs: no call reaches GitHub, nothing sleeps."""
import importlib.util
import inspect
import json
import os
import signal
import sys
import time as real_time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("release_scenarios_878", ROOT / "scripts/release-scenarios.py")
scen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scen)

# A scenario of 10 minutes whose label never comes: it fails, and is played
# once more only when the step has time for it.
SCENARIO = {"id": "slow-setup", "opens": {"issue": {"title": "feat: a slow one", "body": "b"}}, "minutes": 10,
            "expect": {"labels": ["never"]}}
CONF = {"scenarios": [SCENARIO], "bodies": {}}
MINUTES = 17
# Seconds a setup or cleanup call takes, and a poll's read.
SLOW, READ = 12, 1


class World:
    """The stubbed `gh` and clock: every call takes time on the clock, a
    sleep moves it on, and `on` hooks one call (by its first two words)."""

    def __init__(self, on=None):
        self.now, self.calls, self.on = 0.0, [], on or {}

    def gh(self, *args, input=None, token=None):
        self.calls.append(args)
        hook = self.on.get(args[:2])
        if hook:
            hook(self, args)
        polling = args[:2] in (("issue", "view"), ("run", "list"))
        self.now += READ if polling else SLOW
        if args[:2] == ("issue", "create"):
            return "https://github.com/o/t/issues/9\n"
        if args[:2] == ("issue", "view"):
            return json.dumps({"labels": [], "comments": [], "state": "OPEN"})
        return "[]"

    def sleep(self, seconds):
        self.now += seconds

    def clock(self):
        return self.now


def stubbed(monkeypatch, world):
    """The module's `gh` and `time` the world's (the clock and the sleep;
    the rest real), and its plan CONF."""
    assert inspect.signature(scen.play_group).parameters["clock"].default is None, \
        "play_group reads its gh, sleep and clock when it plays, so the step's stubs reach it"
    fake = types.SimpleNamespace(**{k: getattr(real_time, k) for k in dir(real_time) if not k.startswith("_")})
    fake.sleep, fake.monotonic = world.sleep, world.clock
    monkeypatch.setattr(scen, "time", fake)
    monkeypatch.setattr(scen, "gh", world.gh)
    monkeypatch.setattr(scen, "load_yaml", lambda path: CONF)


def play(out, minutes=MINUTES):
    return scen.main(["play", "--repo", "o/t", "--ref", "v7-next", "--group", "slow-setup", "--out", str(out), "--minutes", str(minutes)])


def test_a_failing_scenario_with_slow_setup_ends_and_writes_before_the_deadline(monkeypatch, tmp_path):
    world = World()
    stubbed(monkeypatch, world)
    out = tmp_path / "results.md"
    assert play(out) == 1
    rows = scen.read_results(out)
    assert [(r["id"], r["ok"]) for r in rows] == [("slow-setup", False)]
    # Its setup and cleanup took minutes of the step's: the retry, when
    # played, fits what was left of them; otherwise its row says so.
    assert world.now <= MINUTES * 60, f"the player ran {world.now / 60:.1f} minutes, past the step's {MINUTES}"
    assert rows[0]["attempts"] == 2 or scen.NOT_RETRIED in rows[0]["why"]


def test_the_retry_gets_what_is_left_less_the_first_attempts_own_time(monkeypatch, tmp_path):
    world = World()
    stubbed(monkeypatch, world)
    out = tmp_path / "results.md"
    # 25 minutes: time for a retry, which still ends before them.
    play(out, 25)
    rows = scen.read_results(out)
    assert rows[0]["attempts"] == 2
    assert world.now <= 25 * 60


def test_a_rate_limited_gh_in_the_cleanup_is_retried_and_kills_nothing(monkeypatch, tmp_path):
    limited = []

    def once(world, args):
        if not limited:
            limited.append(args)
            raise scen.GhError("gh issue close: HTTP 403: API rate limit exceeded", 1, "", "API rate limit exceeded; retry-after: 30")

    world = World({("issue", "close"): once})
    stubbed(monkeypatch, world)
    out = tmp_path / "results.md"
    assert play(out) == 1
    assert limited, "the cleanup closed its issue"
    closes = [c for c in world.calls if c[:3] == ("issue", "close", "9")]
    assert len(closes) >= 2, "the rate-limited close was retried"
    assert [r["id"] for r in scen.read_results(out)] == ["slow-setup"]


def test_an_error_that_escapes_the_cleanup_is_a_failing_row_not_a_dead_process(monkeypatch, tmp_path):
    def broken(world, args):
        raise TypeError("a cleanup that broke")

    world = World({("issue", "lock"): broken})
    stubbed(monkeypatch, world)
    out = tmp_path / "results.md"
    assert play(out) == 1
    rows = scen.read_results(out)
    assert [(r["id"], r["ok"]) for r in rows] == [("slow-setup", False)]


def test_a_sigterm_mid_attempt_leaves_a_failing_infrastructure_row(monkeypatch, tmp_path):
    def term(world, args):
        if len([c for c in world.calls if c[:2] == ("issue", "view")]) == 3:
            os.kill(os.getpid(), signal.SIGTERM)

    before = signal.getsignal(signal.SIGTERM)
    world = World({("issue", "view"): term})
    stubbed(monkeypatch, world)
    out = tmp_path / "results.md"
    with pytest.raises(SystemExit):
        play(out)
    assert signal.getsignal(signal.SIGTERM) == before, "the handler is put back"
    rows = scen.read_results(out)
    assert [(r["id"], r["ok"], r.get("class")) for r in rows] == [("slow-setup", False, "infrastructure")]


def test_the_file_is_there_before_the_first_attempt_ends(monkeypatch, tmp_path):
    out = tmp_path / "results.md"
    seen = []

    def look(world, args):
        if not seen:
            seen.append(scen.read_results(out))

    world = World({("issue", "view"): look})
    stubbed(monkeypatch, world)
    play(out)
    assert [(r["id"], r["ok"], r.get("class")) for r in seen[0]] == [("slow-setup", False, "infrastructure")]


def test_the_real_plans_calls_with_setup_cleanup_and_retry_stay_under_the_rate_limit():
    real = scen.load_yaml(ROOT / "tests/release/scenarios.yml")
    budget = getattr(scen, "call_budget", None)
    assert budget is not None, "the plan counts the calls of every scenario's setup and cleanup"
    calls = budget(real["scenarios"], real["bodies"])
    assert calls > scen.poll_budget(real["scenarios"]), "the setup, the cleanup and the retry are counted"
    assert calls < scen.RATE_LIMIT
    # And the plan check refuses a plan that, with them, passes it.
    many = real["scenarios"] * 2
    assert any("past the test identity's" in line for line in scen.timing(many, real["bodies"]))


def test_a_write_cut_in_the_middle_leaves_the_last_whole_file(monkeypatch, tmp_path):
    out = tmp_path / "results.md"
    scen.write_results([scen.ended("slow-setup")], str(out), echo=False)

    def cut(*a, **k):
        raise SystemExit(143)  # a signal in the middle of the next write

    monkeypatch.setattr(scen.json, "dumps", cut)
    with pytest.raises(SystemExit):
        scen.write_results([{"id": "slow-setup", "ok": True, "why": [], "run": ""}], str(out), echo=False)
    monkeypatch.undo()
    assert [(r["id"], r["ok"]) for r in scen.read_results(out)] == [("slow-setup", False)]
    assert [p.name for p in tmp_path.iterdir()] == ["results.md"]
