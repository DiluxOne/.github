"""A hint on an autopilot pull request that waits on the autopilot brings it
back (#699 C4), stopped or not: review-reply.yml's `answer` job takes the
comment of someone who decides, on such a pull request with no
`needs-human`, for a hint, and dilux-bot adds `autopilot:continue`. Played
here with the job's own script, GitHub and the engine's scripts stood in
for."""
import os
import stat
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def step():
    job = yaml.safe_load((ROOT / ".github/workflows/review-reply.yml").read_text(encoding="utf-8"))["jobs"]["answer"]
    return job, next(s for s in job["steps"] if s.get("id") == "back")


GH = r"""#!/usr/bin/env bash
echo "$*" >> "$LOG"
case "$*" in
  "pr view 9 --repo o/r --json closingIssuesReferences"*) echo 4 ;;
  "issue view 4 --repo o/r --json labels"*) echo false ;;
  "pr view 9 --repo o/r --json labels"*) echo "$PR_LABELS" ;;
  "api repos/o/r/issues/9/comments"*) printf '%s\n' "$LAST" ;;
  *) : ;;
esac
"""
WAITING = 'import json, os\nprint(json.dumps({"what": "a failed check", "who": os.environ["WHO"]}))\n'
DECIDERS = 'import os, sys\nsys.exit(0 if os.environ["DECIDES"] == "yes" else 1)\n'


def play(pr_labels="autopilot", who="the autopilot", decides="yes", last="<!-- dx-board -->"):
    _, back = step()
    with tempfile.TemporaryDirectory() as d:
        bin_ = Path(d, "bin")
        bin_.mkdir()
        gh = bin_ / "gh"
        gh.write_text(GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        scripts = Path(d, ".dx-central", "scripts")
        scripts.mkdir(parents=True)
        (scripts / "waiting.py").write_text(WAITING)
        (scripts / "deciders.py").write_text(DECIDERS)
        log = Path(d, "log")
        log.write_text("")
        out = Path(d, "out")
        env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", LOG=str(log), GITHUB_OUTPUT=str(out), GITHUB_REPOSITORY="o/r",
                   NUMBER="9", IS_PR="true", LOGIN="boss", PR_LABELS=pr_labels, WHO=who, DECIDES=decides, LAST=last,
                   DX_BOT_LOGIN="dilux-bot[bot]")
        r = subprocess.run(["bash", "-c", back["run"]], cwd=d, env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return log.read_text()


def test_a_deciders_hint_where_it_waits_on_the_autopilot_brings_it_back():
    calls = play()
    assert "issue edit 4 --repo o/r --add-label autopilot:continue" in calls
    # No stop: no needs-human to take off.
    assert "labels/needs-human" not in calls


def test_not_where_it_waits_on_someone_else_nor_from_someone_who_does_not_decide():
    assert "autopilot:continue" not in play(who="the maintainer")
    assert "autopilot:continue" not in play(decides="no")
    assert "autopilot:continue" not in play(pr_labels="")


def test_a_stopped_one_comes_back_as_before():
    calls = play(pr_labels="autopilot,needs-human", who="the maintainer", last="<!-- dx-autopilot-stop -->")
    assert "-X DELETE repos/o/r/issues/9/labels/needs-human" in calls
    assert "issue edit 4 --repo o/r --add-label autopilot:continue" in calls
    # A person's pull request with needs-human and no stop of the autopilot's stays a person's.
    assert "autopilot:continue" not in play(pr_labels="autopilot,needs-human", last="<!-- dx-board -->")


def test_the_job_reads_the_checks_it_asks_about():
    job, back = step()
    token = job["steps"][0]["with"]
    assert token["permission-checks"] == "read" and token["permission-statuses"] == "read"
    assert "waiting.py who" in back["run"]
