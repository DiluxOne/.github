"""#726: the release lane's scenarios, all played at once with one test identity's
token, must not poll GitHub faster than that token's 5000 requests an hour."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOURLY_LIMIT = 5000


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_scenarios_polling_together_stay_within_the_hourly_rate_limit():
    ws = load("release-scenarios")
    scenarios = ws.load_yaml(ROOT / "tests" / "release" / "scenarios.yml")["scenarios"]
    calls, marks = [], []

    def fake(*a, input=None):
        calls.append(a)
        if a[:2] == ("issue", "create"):
            return "https://github.com/o/t/issues/9\n"
        if a[:2] == ("issue", "view"):
            return json.dumps({"labels": [], "comments": [], "state": "OPEN"})
        return "[]"

    def sleep(seconds):
        if seconds == ws.POLL:
            marks.append(len(calls))

    s = {"id": "never", "opens": {"issue": {"title": "t"}}, "expect": {"labels": ["never"]}}
    ws.play(s, "o/t", "v7-next", {}, fake, sleep, 2)
    assert len(marks) >= 3
    per_poll = max(b - a for a, b in zip(marks, marks[1:]))
    per_hour = len(scenarios) * per_poll * 3600 / ws.POLL
    assert per_hour <= HOURLY_LIMIT, f"{len(scenarios)} scenarios at {per_poll} calls per poll make {per_hour:.0f} calls an hour"
