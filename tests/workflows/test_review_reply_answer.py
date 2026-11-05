"""An answer after a stop (#647): review-reply.yml's answer step finds the
stop or silent end in dilux-bot's last comment that is not the board's
mention (its `dx-mention` marker), so the mention, which always comes after
it, never hides it. The step runs as written, with gh stood in; the
comments go through gh's own --jq, with jq."""
import json
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BOT = "dilux-bot[bot]"
MENTION = "<!-- dx-mention 0123456789abcdef -->\n@maintainer: answer https://github.com/o/r/issues/7"


def job(name):
    return yaml.safe_load((ROOT / ".github/workflows/review-reply.yml").read_text(encoding="utf-8"))["jobs"][name]


def step():
    return next(s for s in job("answer")["steps"] if s.get("id") == "back")["run"]


def token(name):
    """The `with:` of job NAME's dilux-bot token."""
    return next(s for s in job(name)["steps"] if s.get("id") == "bot")["with"]


def answer(tmp_path, comments, pr=False):
    """The gh calls the step makes when a maintainer comments on issue #7,
    labelled `needs-human`, with no pull request, whose comments are
    COMMENTS ((login, body), oldest first); with PR, on its pull request
    #9 instead, labelled `autopilot` and `needs-human`, which closes #7."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    log.write_text("")
    (tmp_path / "comments.json").write_text(json.dumps([{"user": {"login": u}, "body": b} for u, b in comments]))
    (bin_dir / "gh").write_text(
        "#!/bin/bash\n"
        f'echo "gh $*" >> "{log}"\n'
        'case "$*" in\n'
        "  *closingIssuesReferences*) echo 7 ;;\n"
        "  *'--json labels --jq [.labels[].name] | index'*) echo false ;;\n"
        "  *closedByPullRequestsReferences*) ;;\n"
        "  'pr view 9 '*'--json labels'*) echo autopilot,needs-human ;;\n"
        "  *'--json labels'*) echo needs-human,bug ;;\n"
        "  *'/comments'*)\n"
        '    while [ $# -gt 0 ]; do [ "$1" = --jq ] && { shift; q=$1; }; shift; done\n'
        f'    jq -r "$q" "{tmp_path / "comments.json"}" ;;\n'
        "esac\n")
    (bin_dir / "gh").chmod(0o755)
    # Who decides: the maintainer does.
    (tmp_path / ".dx-central/scripts").mkdir(parents=True)
    (tmp_path / ".dx-central/scripts/deciders.py").write_text("print('decides')\n")
    out = tmp_path / "out"
    out.write_text("")
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", GITHUB_OUTPUT=str(out),
               GITHUB_REPOSITORY="o/r", DX_BOT_LOGIN=BOT, NUMBER="9" if pr else "7", IS_PR=str(pr).lower(), LOGIN="maintainer")
    done = subprocess.run(["bash", "-c", step()], env=env, capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    return log.read_text()


def test_a_mention_does_not_hide_the_stop(tmp_path):
    for end in ("<!-- dx-autopilot-silent -->", "<!-- dx-autopilot-stop -->"):
        run = tmp_path / end[5:-4]
        run.mkdir()
        calls = answer(run, [(BOT, "the board"), (BOT, f"{end}\nThe autopilot ended."), ("maintainer", "why?"),
                             (BOT, MENTION), (BOT, MENTION)])
        assert "gh api -X DELETE repos/o/r/issues/7/labels/needs-human" in calls, end
        assert "gh issue edit 7 --repo o/r --add-label autopilot:continue" in calls, end


def test_no_stop_no_continue(tmp_path):
    # The last of dilux-bot's comments but the mentions is no stop: nothing
    # changes, with a mention after it or without one, and a stop before it
    # is over.
    for i, comments in enumerate((
            [(BOT, "<!-- dx-autopilot-stop -->\nStopped."), (BOT, "<!-- dx-board -->\nThe board"), (BOT, MENTION)],
            [(BOT, "<!-- dx-autopilot-silent -->\nSilent."), (BOT, "A question")],
            [(BOT, MENTION)],
            [("someone", "<!-- dx-autopilot-stop -->\nA quote"), (BOT, MENTION)])):
        run = tmp_path / str(i)
        run.mkdir()
        calls = answer(run, comments)
        assert "labels/needs-human" not in calls and "autopilot:continue" not in calls, comments


def test_an_answer_after_a_stop_on_the_pr_clears_needs_human(tmp_path):
    # #660: the stop is on the pull request, so is `needs-human`: the
    # answer takes it off the pull request, with a token that may write
    # its labels, and brings the issue back.
    calls = answer(tmp_path, [(BOT, "<!-- dx-autopilot-stop -->\nStopped."), (BOT, MENTION)], pr=True)
    assert "gh api repos/o/r/issues/9/comments" in calls
    assert "gh api -X DELETE repos/o/r/issues/9/labels/needs-human" in calls
    assert "gh issue edit 7 --repo o/r --add-label autopilot:continue" in calls
    assert token("answer")["permission-pull-requests"] == "write"
