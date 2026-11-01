"""#598: the delegated lane counts the bot's own edits as a person's.

A decision's sub-issue that dilux-bot edited after it was linked to its parent
(its board, its seal) is refused as "edited after it was linked", so it never
starts. The lane should read who edited it (the issue's edit history) and
refuse only an edit by someone other than DX_BOT_LOGIN. Written from the report
as the reproduction's writer would (#376).
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINKED = "2026-11-01T10:00:00Z"
EDITED = "2026-11-01T20:26:17Z"


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sub_issue(editor):
    """A sub-issue of a parent a person accepted, opened by the lane's App and
    edited once after it was linked, by `editor`."""
    return {
        "authorAssociation": "NONE",
        "author": {"login": "dilux-bot"},
        "lastEditedAt": EDITED,
        "userContentEdits": {"nodes": [{"createdAt": EDITED, "editor": {"login": editor}}]},
        "timelineItems": {"nodes": [{"__typename": "ParentIssueAddedEvent", "createdAt": LINKED}]},
        "parent": {
            "number": 552,
            "state": "OPEN",
            "stateReason": None,
            "repository": {"nameWithOwner": "DiluxOne/.github"},
            "labels": {"nodes": [{"name": "accepted"}]},
            "timelineItems": {"nodes": [{"__typename": "LabeledEvent", "label": {"name": "accepted"},
                                         "actor": {"__typename": "User", "login": "maintainer"}}]},
        },
    }


def accepts(issue, monkeypatch):
    monkeypatch.setenv("DX_BOT_LOGIN", "dilux-bot")
    autonomy = load("autonomy")
    lane = {"origin": {"parent": True, "app": "dilux-bot"}}
    return autonomy.delegated_accepts("delegated", lane, issue, "DiluxOne/dilux-agentic-workflow")


def test_the_delegated_lane_accepts_a_sub_issue_edited_after_its_link_only_by_the_bot(monkeypatch):
    ok, why = accepts(sub_issue("dilux-bot"), monkeypatch)
    assert ok, why


def test_the_delegated_lane_still_refuses_a_sub_issue_a_person_edited_after_its_link(monkeypatch):
    ok, _ = accepts(sub_issue("some-person"), monkeypatch)
    assert not ok
