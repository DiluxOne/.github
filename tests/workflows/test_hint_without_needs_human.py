"""A hint of someone who decides, on an autopilot pull request that waits on
the autopilot, brings it back, stopped or not (#699 C4). review-reply.yml's
`answer` job takes a comment on a pull request labelled `autopilot`, opened
by dilux-bot, whose board says it waits on the autopilot, as a hint, even
with no `needs-human`: dilux-bot adds `autopilot:continue` to its issue (the
path of #561), and the run reads the comment as its hint. With no
`needs-human` and not waiting on the autopilot, it stays a reply."""
import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


autopilot = load("autopilot_c4", "autopilot.py")
waiting = load("waiting_c4", "waiting.py")


def back_step():
    job = yaml.safe_load((ROOT / ".github/workflows/review-reply.yml").read_text(encoding="utf-8"))["jobs"]["answer"]
    return next(s for s in job["steps"] if s.get("id") == "back")["run"]


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


def test_the_answer_job_reads_the_pull_requests_board():
    run = back_step()
    assert "ITEM=pr" in run and "state get waits" in run
    assert "autopilot.py hint" in run
    # The hint path adds autopilot:continue, and takes needs-human off only
    # when it is there.
    tail = run[run.index('if [ -n "$stopped" ]; then'):]
    assert "autopilot:continue" in tail and 'hint" = stop' in tail


def test_the_wait_on_the_autopilot_is_the_boards():
    assert waiting.AUTOPILOT == "the autopilot"
    src = (ROOT / "scripts/autopilot.py").read_text(encoding="utf-8")
    assert 'WAITS_ON_AUTOPILOT = "the autopilot"' in src


def run_back(tmp_path, labels, waits):
    """review-reply.yml's step as written, gh stood in: a decider comments on
    pull request #9 (closing #7, opened by dilux-bot) labelled LABELS, whose
    board's `waits` is WAITS. Returns the gh calls."""
    import json
    import os
    import subprocess
    bot = "dilux-bot[bot]"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    log.write_text("")
    (bin_dir / "gh").write_text(
        "#!/bin/bash\n"
        f'echo "gh $*" >> "{log}"\n'
        'case "$*" in\n'
        "  *closingIssuesReferences*) echo 7 ;;\n"
        "  *'--json labels --jq [.labels[].name] | index'*) echo false ;;\n"
        f"  'pr view 9 '*'--json labels'*) echo {labels} ;;\n"
        f"  'pr view 9 '*'--json author'*) echo '{bot}' ;;\n"
        "esac\n")
    (bin_dir / "gh").chmod(0o755)
    scripts = tmp_path / ".dx-central/scripts"
    scripts.mkdir(parents=True)
    (scripts / "deciders.py").write_text("print('decides')\n")
    (scripts / "receipts.py").write_text(
        "import os, sys\n"
        f"print({json.dumps(json.dumps(waits))} if sys.argv[1:4] == ['state', 'get', 'waits'] and os.environ.get('ITEM') == 'pr' else 'null' if sys.argv[1:3] == ['state', 'get'] else '')\n")
    (scripts / "autopilot.py").write_text(
        f"import runpy, sys\nsys.path.insert(0, {str(ROOT / 'scripts')!r})\nrunpy.run_path({str(ROOT / 'scripts/autopilot.py')!r}, run_name='__main__')\n")
    out = tmp_path / "out"
    out.write_text("")
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", GITHUB_OUTPUT=str(out), GITHUB_REPOSITORY="o/r", RUNNER_TEMP=str(tmp_path),
               DX_BOT_LOGIN=bot, LOGIN="maintainer", NUMBER="9", IS_PR="true")
    done = subprocess.run(["bash", "-c", back_step()], env=env, capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    return log.read_text()


def test_the_hint_brings_it_back_with_no_label_of_a_persons(tmp_path):
    calls = run_back(tmp_path, "autopilot,type:fix", {"role": "the autopilot", "what": "fix round"})
    assert "gh issue edit 7 --repo o/r --add-label autopilot:continue" in calls
    assert "labels/needs-human" not in calls


def test_a_comment_on_one_that_waits_on_a_person_is_a_reply(tmp_path):
    calls = run_back(tmp_path, "autopilot,type:fix", {"role": "the maintainer", "what": "merge"})
    assert "autopilot:continue" not in calls
