"""#701: v7.14.0's release scenarios fail opening their issue with a token that has `public_repo`.

`gh issue create --type` (and `gh issue edit --type`) set the Type through the
GraphQL mutation `updateIssueIssueType`, which GitHub answers with "Your token
has not been granted the required scopes" to a token with only `public_repo`
(the test identity's). The scenarios' issues must be opened without it, and
still get their Type some other way (the REST API).
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_scenario_opens_its_typed_issue_without_the_graphql_type_flag_a_public_repo_token_cannot_use():
    scenarios = load("release-scenarios")
    calls = []

    def fake(*args, input=None):
        calls.append(args)
        return "https://github.com/o/t/issues/5\n"

    try:
        scenarios.open_issue("o/t", {"title": "t", "body": "f"}, {"f": "x"}, "d", fake, "s", {"f": "Feature"})
    except Exception:
        pass  # the verdict is on the calls made, not on how the fake's answers are read

    graphql = [c for c in calls if c[:1] == ("issue",) and "--type" in c]
    typed = [c for c in calls if "Feature" in c]
    assert not graphql, f"the Type is set through GraphQL, which needs the `repo` scope: {graphql}"
    assert typed, f"the issue never gets its Type: {calls}"
