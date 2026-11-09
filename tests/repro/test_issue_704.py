"""#704: a scenario whose `gh issue create` hits a GitHub rate limit is retried
after its back-off, as an observation is (#698), not failed at once."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_rate_limited_issue_create_is_retried_and_the_scenario_holds():
    scen = load("release-scenarios")
    state = {"creates": 0, "sleeps": []}

    def fake(*a, input=None):
        if a[:2] == ("issue", "create"):
            state["creates"] += 1
            if state["creates"] <= 2:
                raise scen.GhError("gh issue create --repo: GraphQL: API rate limit already exceeded for user ID 1.", 1, "",
                                   "GraphQL: API rate limit already exceeded for user ID 1.")
            return "https://github.com/o/t/issues/9\n"
        if a[:2] == ("issue", "view"):
            return json.dumps({"labels": [{"name": "x"}], "closedByPullRequestsReferences": []})
        return "[]"

    got = scen.play({"id": "r", "opens": {"issue": {"title": "t"}}, "expect": {"labels": ["x"]}},
                    "o/t", "v7-next", {}, fake, state["sleeps"].append, 20)
    assert got["ok"], got["why"]
    assert state["creates"] == 3
