"""#572: a decision's own pull request closes the parent while its sub-issues in
other repositories are open, and the delegated lane then refuses them because
their parent is not open. Written from the report as the reproduction's writer
would (#376).
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sub_issue(parent_state, state_reason):
    """A sub-issue of a parent a person accepted, opened by the lane's App."""
    return {
        "authorAssociation": "NONE",
        "author": {"login": "dilux-bot"},
        "lastEditedAt": None,
        "timelineItems": {"nodes": [{"__typename": "ParentIssueAddedEvent", "createdAt": "2026-10-30T10:00:00Z"}]},
        "parent": {
            "number": 552,
            "state": parent_state,
            "stateReason": state_reason,
            "repository": {"nameWithOwner": "DiluxOne/.github"},
            "labels": {"nodes": [{"name": "accepted"}]},
            "timelineItems": {"nodes": [{"__typename": "LabeledEvent", "label": {"name": "accepted"},
                                         "actor": {"__typename": "User", "login": "maintainer"}}]},
        },
    }


def test_the_delegated_lane_accepts_a_sub_issue_whose_accepted_parent_closed_as_completed():
    autonomy = load("autonomy")
    lane = {"origin": {"parent": True, "app": "dilux-bot"}}
    ok, why = autonomy.delegated_accepts("delegated", lane, sub_issue("CLOSED", "COMPLETED"), "DiluxOne/dilux-agentic-workflow")
    assert ok, why
