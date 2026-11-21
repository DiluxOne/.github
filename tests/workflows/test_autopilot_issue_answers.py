"""#924 C1: an answer on an issue whose pull request does not exist yet.

A decider's comment after the autopilot's stop on the issue reaches the
Spec's prompt in its `<answer>` block, the same way `answers()` reads one
on the pull request, and nothing edits the issue: its body (the seal) and
its labels (`accepted`) stay as they are."""
import json
import re

from steps import run, step

STOP = "<!-- dx-autopilot-stop -->"
BODY = """### Problem

The greeting is missing.

### Acceptance criteria

- C1: Given the page, when it loads, then it greets.

### Criticality

Low
"""
COMMENTS = [
    {"body": "An early note from the maintainer.", "createdAt": "2026-11-20T09:00:00Z", "author": {"login": "boss"}},
    {"body": f"{STOP}\nThe autopilot stopped: which file does the greeting go in?", "createdAt": "2026-11-20T10:00:00Z",
     "author": {"login": "dilux-bot"}},
    {"body": "Put it in greeting.txt, at the root.", "createdAt": "2026-11-20T11:00:00Z", "author": {"login": "boss"}},
    {"body": "Put it anywhere you like.", "createdAt": "2026-11-20T11:30:00Z", "author": {"login": "stranger"}},
]
GH = f"""case "$*" in
  *issues/7/events*) echo "2026-11-19T08:00:00Z" ;;
  "issue view 7 --repo o/r --json comments"*) echo '{json.dumps(COMMENTS)}' ;;
  "api repos/o/r/issues/7 --jq"*) echo "Bug" ;;
  *) echo "unexpected gh $*" >&2; exit 1 ;;
esac
"""


def start(tmp_path):
    (tmp_path / "temp").mkdir(parents=True, exist_ok=True)
    (tmp_path / "temp" / "body.md").write_text(BODY, encoding="utf-8")
    fixture, org_yml = tmp_path / "deciders.json", tmp_path / "org.yml"
    fixture.write_text(json.dumps({"roles": {"boss": "admin", "stranger": "read"}}), encoding="utf-8")
    org_yml.write_text("who-decides: writers\n", encoding="utf-8")
    ran = run(step("autopilot.yml", "task", "prep"), tmp_path, stubs={"gh": GH},
              env={"MODE": "start", "NUMBER": "7", "PR": "", "BRANCH": "", "LANE": "standard",
                   "DECIDERS_FIXTURE": str(fixture), "DX_ORG_YML": str(org_yml)})
    assert ran.code == 0, ran.stderr
    return ran, (tmp_path / "work" / ".dx-io" / "prompt.md").read_text(encoding="utf-8")


def test_the_spec_prompt_holds_the_deciders_answer_in_its_answer_block(tmp_path):
    _, prompt = start(tmp_path)
    blocks = re.findall(r"<answer>\n(.*?)\n</answer>", prompt, re.S)
    assert len(blocks) == 1, prompt
    block = blocks[0]
    assert "Put it in greeting.txt, at the root." in block and "boss" in block
    # Only what came after the stop, and never someone who does not decide.
    assert "An early note" not in block and "stranger" not in block and "anywhere you like" not in block


def test_nothing_edits_the_issue_so_accepted_and_the_seal_stay(tmp_path):
    ran, _ = start(tmp_path)
    for call in ran.of("gh"):
        assert "edit" not in call and "comment" not in call, call
        assert not any(a in ("-X", "--method", "--add-label", "--remove-label", "-f", "-F", "--input") for a in call), call
