"""A hint of someone who decides, on an autopilot pull request that waits on
the autopilot, brings it back, stopped or not (#699 C4). review-reply.yml's
`answer` job takes a comment on a pull request labelled `autopilot`, opened
by dilux-bot, whose board says it waits on the autopilot, as a hint, even
with no `needs-human`: dilux-bot adds `autopilot:continue` to its issue (the
path of #561), and the run reads the comment as its hint. With no
`needs-human` and not waiting on the autopilot, it stays a reply."""
import importlib.util
from pathlib import Path

from steps import run, step

ROOT = Path(__file__).resolve().parents[2]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


autopilot = load("autopilot_c4", "autopilot.py")
waiting = load("waiting_c4", "waiting.py")


def test_a_hint_on_a_pull_request_that_waits_on_the_autopilot_is_taken():
    labels = ["autopilot", "type:fix"]
    assert autopilot.hint_of(labels, True, {"role": waiting.AUTOPILOT}, "") == "waits"
    # Stopped (needs-human after a stop): the hint of #561, as before.
    assert autopilot.hint_of(labels + ["needs-human"], True, {"role": waiting.MAINTAINER}, "stop") == "stop"
    # Not waiting on the autopilot, and not stopped: a reply, no hint.
    assert autopilot.hint_of(labels, True, {"role": waiting.MAINTAINER}, "") == ""
    assert autopilot.hint_of(labels, True, None, "") == ""
    # Not the autopilot's pull request: never.
    assert autopilot.hint_of(["type:fix"], True, {"role": waiting.AUTOPILOT}, "") == ""
    assert autopilot.hint_of(labels, False, {"role": waiting.AUTOPILOT}, "") == ""
    # A cap end, or a person's own needs-human, stays with a person.
    assert autopilot.hint_of(labels + ["needs-human"], True, {"role": waiting.AUTOPILOT}, "cap") == ""


def test_the_answer_job_reads_the_pull_requests_board(tmp_path):
    """The step reads `waits` from the pull request's board (ITEM=pr) and
    asks autopilot.py hint; the hint path adds autopilot:continue, and takes
    needs-human off only when it is there (a stop)."""
    waits = {"role": "the autopilot", "what": "fix round"}
    ran = run_back(tmp_path / "waits", "autopilot,type:fix", waits)
    assert ["receipts.py", "pr", "9", "state", "get", "waits"] in ran.calls, ran.calls
    assert ["autopilot.py", "hint"] in ran.calls, ran.calls
    assert ["gh", "issue", "edit", "7", "--repo", "o/r", "--add-label", "autopilot:continue"] in ran.calls
    assert not [c for c in ran.calls if c[:3] == ["gh", "api", "-X"]], ran.calls
    # Stopped (needs-human, the bot's stop): the label comes off too.
    stopped = run_back(tmp_path / "stop", "autopilot,needs-human", waits, stop=True)
    assert ["gh", "api", "-X", "DELETE", "repos/o/r/issues/9/labels/needs-human"] in stopped.calls, stopped.calls
    assert ["gh", "issue", "edit", "7", "--repo", "o/r", "--add-label", "autopilot:continue"] in stopped.calls


def test_the_wait_on_the_autopilot_is_the_boards():
    assert waiting.AUTOPILOT == "the autopilot"
    src = (ROOT / "scripts/autopilot.py").read_text(encoding="utf-8")
    assert 'WAITS_ON_AUTOPILOT = "the autopilot"' in src


# A stand-in for a helper under .dx-central/scripts: it records its call
# (ITEM and NUMBER first, as the step sets them) as the stubs on PATH do.
HELPER = """import json, os, sys
with open(os.environ["DX_CALLS"], "a") as f:
    f.write(json.dumps([{name!r}, *([os.environ.get("ITEM", ""), os.environ.get("NUMBER", "")] if {name!r} == "receipts.py" else []), *sys.argv[1:]]) + "\\n")
{body}
"""


def run_back(tmp_path, labels, waits, stop=False):
    """review-reply.yml's step as written, gh stood in: a decider comments on
    pull request #9 (closing #7, opened by dilux-bot) labelled LABELS, whose
    board's `waits` is WAITS; with STOP, the bot's stop is its last comment
    and the bot added needs-human. Returns what it ran (steps.Ran)."""
    import json
    bot = "dilux-bot[bot]"
    tmp_path.mkdir(parents=True, exist_ok=True)
    comments = [{"user": {"login": bot}, "body": "<!-- dx-autopilot-stop -->\nStopped.", "created_at": "2026-01-01T00:00:00Z"}] if stop else []
    (tmp_path / "comments.json").write_text(json.dumps(comments))
    (tmp_path / "events.json").write_text(json.dumps([{"event": "labeled", "label": {"name": "needs-human"}, "actor": {"login": bot}}]))
    gh = ('case "$*" in\n'
          "  *closingIssuesReferences*) echo 7 ;;\n"
          "  *'--json labels --jq [.labels[].name] | index'*) echo false ;;\n"
          f"  'pr view 9 '*'--json labels'*) echo {labels} ;;\n"
          f"  'pr view 9 '*'--json author'*) echo '{bot}' ;;\n"
          '  *"/events"*|*"/comments"*)\n'
          '    f=events; case "$*" in *"/comments"*) f=comments ;; esac\n'
          '    while [ $# -gt 0 ]; do [ "$1" = --jq ] && { shift; q=$1; }; shift; done\n'
          f'    jq -r "$q" "{tmp_path}/$f.json" ;;\n'
          "esac\n")
    scripts = ROOT / "scripts"
    answer = json.dumps(json.dumps(waits))
    files = {
        ".dx-central/scripts/deciders.py": HELPER.format(name="deciders.py", body="print('decides')"),
        ".dx-central/scripts/receipts.py": HELPER.format(name="receipts.py", body=(
            f"print({answer} if sys.argv[1:4] == ['state', 'get', 'waits'] and os.environ.get('ITEM') == 'pr' "
            "else 'null' if sys.argv[1:3] == ['state', 'get'] else '')")),
        ".dx-central/scripts/autopilot.py": HELPER.format(name="autopilot.py", body=(
            f"import runpy\nsys.path.insert(0, {str(scripts)!r})\nrunpy.run_path({str(scripts / 'autopilot.py')!r}, run_name='__main__')")),
    }
    ran = run(step("review-reply.yml", "back", "answer"), tmp_path, stubs={"gh": gh}, files=files, central=False,
              env={"DX_BOT_LOGIN": bot, "LOGIN": "maintainer", "NUMBER": "9", "IS_PR": "true"})
    assert ran.code == 0, ran.stdout + ran.stderr
    return ran


def test_the_hint_brings_it_back_with_no_label_of_a_persons(tmp_path):
    calls = run_back(tmp_path, "autopilot,type:fix", {"role": "the autopilot", "what": "fix round"}).of("gh")
    assert ["issue", "edit", "7", "--repo", "o/r", "--add-label", "autopilot:continue"] in calls
    assert not [c for c in calls if "repos/o/r/issues/9/labels/needs-human" in c], calls


def test_a_comment_on_one_that_waits_on_a_person_is_a_reply(tmp_path):
    calls = run_back(tmp_path, "autopilot,type:fix", {"role": "the maintainer", "what": "merge"}).of("gh")
    assert not [c for c in calls if "autopilot:continue" in c], calls
