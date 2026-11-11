"""#715: the release scenarios wait `until` the comment SEAL (`<!-- dx-prd-seal -->`)
once an issue is accepted, so an accepted, sealed issue must carry a bot comment
with that mark. The only comment the engine keeps on it is its board
(scripts/receipts.py board_text), which must therefore say so."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_board_of_an_accepted_and_sealed_issue_carries_the_mark_the_scenarios_wait_for():
    scenarios = load("release-scenarios")
    receipts = load("receipts")
    body = "## PRD\n\n### What happened?\n\nIt does not greet.\n"
    last_seal = receipts.seal(415, body, "boss", None, "2026-11-10T00:00:00Z")
    board = receipts.board_text(415, True, last_seal, None, labels=["accepted"])
    assert scenarios.SEAL in board
