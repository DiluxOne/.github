"""#459: an empty answer reaches an autopilot continue run as a maintainer's answer.

A guided continue run whose answers file holds only whitespace (what
`autopilot.py answers` prints when nobody answered) is read the way the
workflow reads it (ANSWERS), and the work prompt is built from it.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_whitespace_only_answer_is_no_answer_and_the_prompt_holds_no_answer_block(tmp_path):
    autopilot = load("autopilot")
    answers = tmp_path / "answers.md"
    answers.write_text("\n", encoding="utf-8")
    answered = answers.read_text(encoding="utf-8")

    prompt = autopilot.prompt_work("o/r", "7", "8", "b", "x", [("C1", "a", None)], True, None, "guided", answered)

    assert "A maintainer answered your question" not in prompt
    assert "<answer>" not in prompt
