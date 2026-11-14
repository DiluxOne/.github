"""An edit that makes an accepted issue pass starts the autopilot (#699 C2):
the start refused it for its shape and said so in a comment kept up to
date; a person's edit that makes it pass starts it, as the acceptance did,
with no label. An edit of the sealed PRD still needs a new acceptance (G2)."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "autopilot.py"


def load():
    spec = importlib.util.spec_from_file_location("autopilot", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ap = load()


def triage():
    return yaml.safe_load((ROOT / ".github/workflows/issue-triage.yml").read_text(encoding="utf-8"))["jobs"]


def state(**k):
    refused = [{"user": {"login": ap.BOT_LOGINS[1]}, "body": ap.shape_comment("the issue is not ready (G1): text outside any section")}]
    base = {"issue": {"state": "OPEN", "labels": ["accepted"], "assignees": []}, "prs": [], "lane": "accepted",
            "may_start": [True, ""], "seal": "match", "spec": False, "pr": None, "sender_is_bot": False, "comments": refused}
    return {**base, **k}


def edit_start(st):
    r = subprocess.run([sys.executable, str(SCRIPT), "edit-start"], input=json.dumps(st), capture_output=True, text=True)
    return r.returncode, json.loads(r.stdout)["start"]


def test_an_edit_that_makes_a_refused_issue_pass_starts_it():
    assert edit_start(state()) == (0, True)


def test_nothing_else_starts_on_an_edit():
    for st in (state(may_start=[False, "the issue is not ready (G1): x"]), state(seal="changed"), state(seal="unread"),
               state(comments=[]), state(sender_is_bot=True), state(spec=True),
               state(prs=[{"number": 9, "state": "OPEN", "author": ap.BOT_LOGINS[1], "author_type": "Bot", "labels": ["autopilot"]}]),
               state(issue={"state": "OPEN", "labels": ["accepted", "claimed"]})):
        assert edit_start(st) == (1, False), st


def test_the_refusal_says_so_and_keeps_text_the_issue_controls_in_code():
    body = ap.shape_comment("the issue is not ready (G1): text outside any section, before the first heading: '@mallory [x](http://e)'")
    assert body.startswith("<!-- dx-autopilot-shape: refused -->")
    assert "an edit that makes it pass starts the autopilot" in body
    assert all(line.startswith("- `") for line in body.splitlines() if "@mallory" in line)
    assert "`accepted`" not in body and "autopilot:continue" not in body


def test_the_triage_job_runs_on_a_persons_edit_of_an_accepted_issue_and_starts_the_autopilot():
    jobs = triage()
    job = jobs["edited"]
    cond = " ".join(job["if"].split())
    assert "github.event.action == 'edited'" in cond and "github.event.sender.type != 'Bot'" in cond
    assert "'accepted')" in cond and "'accepted-by:policy')" in cond
    assert job["concurrency"]["cancel-in-progress"] is True
    run = next(s for s in job["steps"] if s.get("id") == "step")["run"]
    for piece in ("receipts.py verify-prd", "issue-schema.py g1", "autopilot.py edit-start", "closedByPullRequestsReferences"):
        assert piece in run, piece
    auto = jobs["autopilot"]
    assert "edited" in auto["needs"]
    assert "(github.event.action == 'edited' && needs.edited.outputs.start == 'true')" in " ".join(auto["if"].split())
    # The edit starts, as an acceptance does: never a continue.
    assert auto["with"]["mode"] == "${{ github.event.label.name == 'autopilot:continue' && 'continue' || 'start' }}"


def test_the_start_writes_the_refusal_and_marks_it_started():
    text = (ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8")
    step = text[text.index("The shape refusal's comment (#699 C2)"):]
    step = step[:step.index("A reproduced bug: the test that failed")]
    assert "autopilot.py shape-comment" in step and "dx-autopilot-shape: started" in step
    assert 'shape refused "$why"' in step and '[ "$AS" != start ] || shape started' in step
    assert "env.DX_BOT_LOGIN" in step
