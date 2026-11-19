"""What a local agent does, and the flow labels nobody adds to move the flow
(#561): the same sentence in the organisation's block, AGENTS.md and
docs/agents.md, and none of them telling an agent to add a flow label."""
import json
import re
from pathlib import Path

from steps import run, step

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


BOT = "dilux-bot[bot]"
STOP = "<!-- dx-autopilot-stop -->\nThe autopilot stopped: the Spec needs a person."
SILENT = "<!-- dx-autopilot-silent -->\nThe autopilot ended with nothing to say."
# A stand-in for a helper under .dx-central/scripts: it records its call
# (with the env the step gives it) as the stubs on PATH do, then answers.
HELPER = """import json, os, sys
with open(os.environ["DX_CALLS"], "a") as f:
    f.write(json.dumps([{name!r}, *sys.argv[1:]]) + "\\n")
{body}
"""


def answer_after_stop(tmp_path, comments, labels="autopilot,needs-human", labelled_by=BOT, decides=True, board_rc=0):
    """review-reply.yml's `back` step, run: a person comments on pull request
    #9 (closing #7, labelled LABELS), whose comments are COMMENTS ((login,
    body), oldest first) and whose `needs-human` was last added by
    LABELLED_BY. DECIDES: whether deciders.py lets them answer; BOARD_RC:
    the exit code of reading #7's board (3: edited by hand)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "comments.json").write_text(json.dumps([{"user": {"login": u}, "body": b, "created_at": f"2026-01-0{i + 1}T00:00:00Z"}
                                                        for i, (u, b) in enumerate(comments)]))
    (tmp_path / "events.json").write_text(json.dumps([
        {"event": "labeled", "label": {"name": "needs-human"}, "actor": {"login": "someone"}},
        {"event": "labeled", "label": {"name": "needs-human"}, "actor": {"login": labelled_by}}]))
    gh = ('case "$*" in\n'
          "  *closingIssuesReferences*) echo 7 ;;\n"
          "  *'--json labels --jq [.labels[].name] | index'*) echo false ;;\n"
          f"  'pr view 9 '*'--json labels'*) echo {labels} ;;\n"
          '  *"/events"*|*"/comments"*)\n'
          '    f=events; case "$*" in *"/comments"*) f=comments ;; esac\n'
          '    while [ $# -gt 0 ]; do [ "$1" = --jq ] && { shift; q=$1; }; shift; done\n'
          f'    jq -r "$q" "{tmp_path}/$f.json" ;;\n'
          "esac\n")
    scripts = ROOT / "scripts"
    files = {
        ".dx-central/scripts/deciders.py": HELPER.format(name="deciders.py", body=f"print('decides' if {decides} else 'does not decide'); sys.exit(0 if {decides} else 1)"),
        ".dx-central/scripts/receipts.py": HELPER.format(name="receipts.py", body=f"print('null' if sys.argv[1:3] == ['state', 'get'] else ''); sys.exit({board_rc} if sys.argv[1:4] == ['state', 'get', 'asked'] else 0)"),
        # How the run ended (#696, #832): the real script's run-end.
        ".dx-central/scripts/autopilot.py": HELPER.format(name="autopilot.py", body=f"import runpy\nsys.path.insert(0, {str(scripts)!r})\nrunpy.run_path({str(scripts / 'autopilot.py')!r}, run_name='__main__')"),
    }
    return run(step("review-reply.yml", "back", "answer"), tmp_path, stubs={"gh": gh}, files=files, central=False,
               env={"DX_BOT_LOGIN": BOT, "LOGIN": "maintainer", "NUMBER": "9", "IS_PR": "true"})


def labelled(ran):
    """The label changes the step made: needs-human off, or a label added."""
    return [c for c in ran.calls if c[0] == "gh" and (c[1:4] == ["api", "-X", "DELETE"] or "--add-label" in c)]


def test_a_maintainers_answer_after_a_stop_brings_the_autopilot_back(tmp_path):
    """The stuck state `needs-human` (a stop, a silent end) waits on a
    person's answer, and the bot moves it from there: review-reply.yml takes
    the label off and adds the continue, only after the bot's own stop."""
    for i, end in enumerate((STOP, SILENT)):
        ran = answer_after_stop(tmp_path / f"end{i}", [(BOT, end)])
        assert ran.code == 0, ran.stdout + ran.stderr
        off = ["gh", "api", "-X", "DELETE", "repos/o/r/issues/9/labels/needs-human"]
        on = ["gh", "issue", "edit", "7", "--repo", "o/r", "--add-label", "autopilot:continue"]
        # needs-human comes off first, then the continue; nothing else.
        assert labelled(ran) == [off, on], ran.calls
        # Only a decider's answer, after scripts/deciders.py (#588).
        assert ran.calls.index(["deciders.py", "may", "answer", "maintainer"]) < ran.calls.index(off)
    # #696, #832 C2: how it ended is run-end's; with no stop of the bot's,
    # or a needs-human a person added, or not the autopilot's pull request,
    # `nothing`: exit 0 and no label moves.
    for name, kw in (("no-stop", {"comments": [(BOT, "The review found nothing blocking.")]}),
                     ("not-the-bots", {"comments": [("someone", STOP)]}),
                     ("a-persons-label", {"comments": [(BOT, STOP)], "labelled_by": "maintainer"}),
                     ("not-autopilot", {"comments": [(BOT, STOP)], "labels": "needs-human"})):
        ran = answer_after_stop(tmp_path / name, **kw)
        assert ran.code == 0 and labelled(ran) == [], (name, ran.calls, ran.stderr)
    # A stop asked no question, so another's comment is neither an answer
    # nor summarised.
    ran = answer_after_stop(tmp_path / "other", [(BOT, STOP)], decides=False)
    assert ran.code == 0 and labelled(ran) == [] and ran.output == {}, ran.calls
    # `nothing` exits 0, but on a board edited by hand with a decider's
    # answer, which it fails with what to restore (#811).
    ran = answer_after_stop(tmp_path / "edited", [(BOT, "The review found nothing blocking.")], board_rc=3)
    assert ran.code == 1 and "edited by hand" in ran.stdout and labelled(ran) == [], ran.stdout + ran.stderr
