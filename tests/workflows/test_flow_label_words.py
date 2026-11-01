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


# #561 C7: every workflow, script (its messages), doc and the organisation's
# block, searched for any sentence that tells a person or an agent to add or
# remove a flow label to move the flow. Taking a pull request over (a
# person's decision, which stops the flow) and a sentence that says never
# are not one.
FLOW = r"\\?`(?:autopilot:[\w*-]+|needs-human)\\?`"
WHO = r"\b(?:a person|a maintainer|the maintainer|maintainers|a human|you|an agent|the agent|a local agent|someone|anyone|they)\b"
DOES = r"\b(?:add|adds|adding|remove|removes|removing|give|gives|giving|put|puts)\b"
TELLS = (
    re.compile(WHO + r"[^.;:|]{0,60}?" + DOES + r"[^.;|]{0,25}?" + FLOW, re.I),
    re.compile(r"(?:^|[.!?:|]\s|[-*]\s)(?:Add|Remove|Put)\s+(?:the\s+)?(?:label\s+)?" + FLOW),
    re.compile(r"\\?`autopilot:continue\\?`\s+(?:resumes|restarts|brings)|\bwith\s+\\?`autopilot:continue\\?`"),
    re.compile(FLOW + r"\s+is\s+(?:added|removed)[^.]{0,30}\bby an? (?:person|maintainer)", re.I),
)
NOT_TOLD = re.compile(r"\b(?:never|not|no|nor|nobody|none)\b|\b(?:takes?|took|taken)\b[^.]{0,40}\bover\b", re.I)
SEARCHED = (".github/workflows/*.yml", "scripts/*.py", "scripts/*.sh", "docs/**/*.md", "kinds/**/*.md", "kinds/**/*.yml",
            "review-profiles/**/*.md", "workflow-templates/*", "profile/*.md", "labels.yml")
SEARCHED_FILES = ("agents-block.md", "AGENTS.md", "README.md", "CONTRIBUTING.md")


def folded(path):
    """The words of a file, its comment markers taken off a script's lines."""
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".py", ".yml", ".yaml", ".sh"):
        text = "\n".join(re.sub(r"^\s*#+\s?", "", line) for line in text.splitlines())
    return " ".join(text.split())


def told(text):
    return [m.group(0) for r in TELLS for m in r.finditer(text) if not NOT_TOLD.search(m.group(0))]


def test_the_search_finds_what_it_must_and_nothing_else():
    for bad in ("So does a hint a maintainer gives with `autopilot:continue` after a stop.",
                "A person who took it back removes `needs-human` first.",
                "Add `autopilot:continue` to the issue.",
                "nothing to start (\\`autopilot:continue\\` resumes the autopilot's).",
                "when `autopilot:continue` is added to the issue (by a person, or by the workflow)."):
        assert told(bad), bad
    for fine in ("dilux-bot adds `autopilot:continue` to its issue.",
                 "A maintainer who takes an autopilot pull request over adds `needs-human`, removes `autopilot` and then pushes.",
                 "never add or remove a flow label (`autopilot:continue`, `needs-human`, `autopilot:*`) to move the flow.",
                 "a maintainer's answer here, a hint in words, brings it back (`needs-human`)."):
        assert not told(fine), fine


def test_no_workflow_script_doc_or_block_tells_anyone_to_add_a_flow_label():
    files = sorted({p for g in SEARCHED for p in ROOT.glob(g) if p.is_file()} | {ROOT / f for f in SEARCHED_FILES})
    assert len(files) > 50
    found = {str(p.relative_to(ROOT)): t for p in files if (t := told(folded(p)))}
    assert not found, found


def test_a_maintainers_answer_after_a_stop_brings_the_autopilot_back():
    """The stuck state `needs-human` (a stop, a silent end) waits on a
    person's answer, and the bot moves it from there: review-reply.yml takes
    the label off and adds the continue, only after the bot's own stop."""
    text = (ROOT / ".github/workflows/review-reply.yml").read_text(encoding="utf-8")
    run = text[text.index("- name: Bring the autopilot back"):text.index("  # The others' opinions")]
    import importlib.util
    spec = importlib.util.spec_from_file_location("autopilot_c7", ROOT / "scripts/autopilot.py")
    ap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ap)
    assert f'"{ap.STOP}"*|"{ap.SILENT}"*) ;; *) exit 0 ;;' in run
    assert "select(.user.login == env.DX_BOT_LOGIN)" in run
    assert '*,needs-human,*) ;; *) exit 0 ;;' in run and '*,autopilot,*) ;; *) exit 0 ;;' in run
    off = run.index('labels/needs-human" >/dev/null')
    assert off < run.index('--add-label "autopilot:continue" >/dev/null', off)
    # Only a decider's answer, after scripts/deciders.py (#588); a stop asked no
    # question, so another's comment is neither an answer nor summarised.
    assert run.index("deciders.py may answer") < off
    assert '[ -z "$stopped" ] || exit 0' in run
