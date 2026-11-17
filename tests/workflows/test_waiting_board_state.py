"""What waits and the week's numbers read the board (#802 C3): the same
fixture items, once with the flow's old labels and once migrated (the labels
off, their state on dilux-bot's board comment, as scripts/receipts.py
migrate leaves them), give the same waits in scripts/waiting.py and the same
runs in scripts/flow-numbers.py."""
import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rc = load("receipts_c3", "receipts.py")
waiting = load("waiting_c3", "waiting.py")
flow = load("flow_numbers_c3", "flow-numbers.py")


def migrated(node):
    """The node as the migration leaves it: its old labels off, their state
    on the bot's board, on it and on each issue it closes."""
    node = copy.deepcopy(node)
    for item in [node] + list(((node.get("closingIssuesReferences") or {}).get("nodes") or [])):
        labels = [l["name"] for l in (item.get("labels") or {}).get("nodes") or []]
        old = rc.old_labels(labels)
        item["labels"] = {"nodes": [{"name": l} for l in labels if l not in old]}
        if old:
            board = f"{rc.BOARD}\nthe board\n" + rc.state_block(rc.state_from_labels(old, {}))
            item["comments"] = {"nodes": [{"author": {"login": "someone"}, "body": "hi"}, {"author": {"login": "dilux-bot"}, "body": board}]}
    return node


def fixture():
    return json.loads((ROOT / "scripts/fixtures/waiting.json").read_text(encoding="utf-8"))


def test_c3_what_waits_is_the_same_from_the_board_as_from_the_labels():
    fx = fixture()
    items = fx["prs"] + fx["issues"]
    moved = [migrated(i) for i in items]
    changed = [i["title"] for i, m in zip(items, moved) if i != m]
    assert len(changed) >= 4, changed
    assert [waiting.item_blocker(m) for m in moved] == [waiting.item_blocker(i) for i in items]
    assert [waiting.waits_of(m, ["boss"]) for m in moved] == [waiting.waits_of(i, ["boss"]) for i in items]


def test_c3_a_board_only_a_person_wrote_or_edited_by_hand_is_not_the_bots():
    fx = fixture()
    asked = next(i for i in fx["issues"] if "autopilot:waiting" in [l["name"] for l in i["labels"]["nodes"]])
    moved = migrated(asked)
    spoof = copy.deepcopy(moved)
    spoof["comments"]["nodes"][-1]["author"]["login"] = "mallory"
    assert waiting.issue_blocker(spoof) != waiting.issue_blocker(moved)
    edited = copy.deepcopy(moved)
    edited["comments"]["nodes"][-1]["body"] = edited["comments"]["nodes"][-1]["body"].replace('"asked":true', '"asked":false')
    assert waiting.issue_blocker(edited)[1] == waiting.MAINTAINER


def test_c3_the_weeks_runs_are_the_same_from_the_board_as_from_the_labels():
    def node(n, runs):
        labels = ["autopilot"] + [f"autopilot:{'free' if k % 2 else 'run'}-{k}" for k in range(1, runs + 1)] + ["autopilot:round-1"]
        return {"number": n, "mergedAt": "2026-11-10T00:00:00Z", "author": {"login": "dilux-bot"}, "repository": {"name": "r", "isPrivate": False},
                "labels": {"nodes": [{"name": l} for l in labels]}, "closingIssuesReferences": {"nodes": [{"createdAt": "2026-11-09T00:00:00Z"}]}}
    nodes = [node(1, 3), node(2, 6), node(3, 1)]
    rows, moved = [flow.pr_row(p) for p in nodes], [flow.pr_row(migrated(p)) for p in nodes]
    assert [r["runs"] for r in rows] == [3, 6, 1]
    assert moved == rows
    assert flow.numbers({"prs": moved}) == flow.numbers({"prs": rows})
    assert rc.COMMENTS_GQL in flow.QUERY
    assert waiting.FIELDS.count(rc.COMMENTS_GQL) == 3
    # #811: each item asks for its comments once; an alias asked twice
    # with other arguments is a query GitHub refuses whole.
    for query in (waiting.FIELDS, flow.QUERY):
        assert query.count("comments(first: 20)") == query.count(rc.COMMENTS_GQL)
        assert query.count("lastComments:") == query.count(rc.COMMENTS_GQL)


def busy(item, board):
    """The item as GraphQL reads it with 60 comments, its board the 21st:
    in neither the first 20 nor the last 20."""
    item = copy.deepcopy(item)
    chatter = [{"author": {"login": "ana"}, "body": f"comment {k}"} for k in range(60)]
    item["comments"] = {"totalCount": 60, "nodes": chatter[:20]}
    item["lastComments"] = {"nodes": chatter[40:]}
    return item, [f"{rc.BOARD}\nthe board\n" + rc.state_block(board)]


def test_a_board_past_the_comments_read_is_read_from_all_of_the_bots():
    fx = fixture()
    asked = next(i for i in fx["issues"] if "autopilot:waiting" in [l["name"] for l in i["labels"]["nodes"]])
    moved = migrated(asked)
    item, bodies = busy(moved, {"asked": True})
    calls = []
    read = lambda: calls.append(1) or bodies
    assert waiting.board_of(item, read) == ({"asked": True}, True)
    assert waiting.board_of(item, read) == ({"asked": True}, True)
    assert len(calls) == 1, "all of the bot's comments are read once"
    assert waiting.issue_blocker(item) == waiting.issue_blocker(moved)
    # found among those read: nothing more is read
    assert waiting.board_of(moved, lambda: 1 / 0)[0].get("asked")
    # an item with no more comments than read has no board: nothing is read
    few, _ = busy(moved, {"asked": True})
    few["comments"]["totalCount"] = 20
    assert waiting.board_of(few, lambda: 1 / 0) == ({}, True)


def test_the_weeks_runs_from_a_board_past_the_comments_read():
    p = {"number": 4, "mergedAt": "2026-11-10T00:00:00Z", "author": {"login": "dilux-bot"}, "repository": {"name": "r", "isPrivate": False},
         "labels": {"nodes": [{"name": "autopilot"}]}, "closingIssuesReferences": {"nodes": []}}
    item, bodies = busy(p, {"runs": [{"n": 1, "free": False}, {"n": 2, "free": True}]})
    assert flow.runs_of(item, ["autopilot"], lambda: bodies) == 2
