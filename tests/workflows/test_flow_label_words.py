"""What a local agent does, and the flow labels nobody adds to move the flow
(#561): the same sentence in the organisation's block, AGENTS.md and
docs/agents.md, and none of them telling an agent to add a flow label."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The one sentence, said the same in the three files (#561 C8).
SENTENCE = (
    "Without a claim, never edit code locally: open or improve the issue, answer on GitHub in words "
    "(an answer to the autopilot's question, a hint when it stops), accept or merge only where the person "
    "you work for may, and never add or remove a flow label (`autopilot:continue`, `needs-human`, "
    "`autopilot:*`) to move the flow: the bot moves it from the answer. Never finish the autopilot's pull "
    "request by hand."
)
AGENT_FILES = ("agents-block.md", "AGENTS.md", "docs/agents.md")


def words(path):
    """The file's text with its line breaks and indentation folded, as
    Markdown reads it."""
    return " ".join((ROOT / path).read_text(encoding="utf-8").split())


def test_the_three_files_say_the_same_sentence():
    for path in AGENT_FILES:
        assert SENTENCE in words(path), path


# Adding or removing a label that moves the flow on: what the bot does from
# an answer, a verdict or a merge, never a person's or an agent's step. A
# maintainer who takes a pull request over (`needs-human`) stops the flow,
# a person's decision, and is not one of these.
TOLD = re.compile(r"(?i)\b(add|adds|adding|remove|removes|removing)\s+(the\s+)?(label\s+)?`(autopilot:[\w-]+)`")


def test_none_of_the_three_tells_an_agent_to_add_a_flow_label():
    for path in AGENT_FILES:
        assert not [m.group(0) for m in TOLD.finditer(words(path))], path
