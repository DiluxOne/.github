"""The autopilot's counts and waits live on the boards (#802 C1), never in
labels: an issue walked through a counted run, a question, an answered (free)
run, the sweep's catch-up, a fix round and a wait for the core, against the
workflows' own steps (extracted, with gh stood in) and scripts/receipts.py's
fixture board (RECEIPTS_FIXTURE). No step adds any of the seven labels the
flow used to carry, and each board's state holds what they said."""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SEVEN = re.compile(r"autopilot:(?:run-|free-|round-|waiting\b|answered\b|catchup\b|core-wait\b)")


def wf(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def step(workflow, job, key):
    return next(s for s in wf(workflow)["jobs"][job]["steps"] if s.get("id") == key or s.get("name") == key)


def autopilot():
    spec = importlib.util.spec_from_file_location("autopilot_board_state", ROOT / "scripts/autopilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def board(fx, number):
    """The state on item `number`'s fixture board, and whether it is intact."""
    path = fx / "comments" / str(number) / "board.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    m = re.search(r"<!-- dx-state v1 (.*?) -->", text, re.S)
    data = json.loads(m.group(1)) if m else {}
    data.pop("sha256", None)
    return data


class World:
    """A repository o/r with issue #7 and its autopilot pull request #8: a gh
    that logs every call, and the fixture boards."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.fx = tmp_path / "fx"
        self.fx.mkdir()
        (tmp_path / ".dx-central").symlink_to(ROOT)
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.log = tmp_path / "calls.log"
        self.log.write_text("")
        pr = {"number": 8, "isDraft": False, "mergeStateStatus": "DIRTY", "labels": [{"name": "autopilot"}], "headRefOid": "abc",
              "author": {"login": "app/dilux-bot"}, "closingIssuesReferences": [{"number": 7}]}
        (tmp_path / "pr.json").write_text(json.dumps(pr))
        (self.bin / "gh").write_text(
            "#!/bin/bash\n"
            f'echo "gh $*" >> "{self.log}"\n'
            'case "$*" in\n'
            "  'search prs'*) echo 'o/r 8' ;;\n"
            "  'search issues'*) ;;\n"
            f"  *'pr view 8'*number,isDraft*) cat \"{tmp_path / 'pr.json'}\" ;;\n"
            "  *'--json labels'*) echo '[]' ;;\n"
            "  *'--json body'*) echo body ;;\n"
            "  *closedByPullRequestsReferences*) echo 8 ;;\n"
            "esac\n")
        # deciders.py stands in for who-decides: boss decides.
        (self.bin / "python3").write_text(
            "#!/bin/bash\n"
            f'echo "python3 $*" >> "{self.log}"\n'
            'case "$1" in *deciders.py) echo "boss decides"; exit 0 ;; esac\n'
            f'exec "{sys.executable}" "$@"\n')
        for f in ("gh", "python3"):
            (self.bin / f).chmod(0o755)
        (tmp_path / "body.md").write_text("### Problem\n\nx\n")
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", RUNNER_TEMP=str(tmp_path), GITHUB_REPOSITORY="o/r",
                        RECEIPTS_FIXTURE=str(self.fx), AUTOPILOT_JSON="null", LABELS_JSON="[]", HELD="", BODY=str(tmp_path / "body.md"),
                        DX_BOT_APP="dilux-bot", DX_BOT_LOGIN="dilux-bot[bot]", GITHUB_OUTPUT=str(tmp_path / "out"))
        # Applied with the key, as the apply job does: not the agent's outbox.
        self.env.pop("DX_IO", None)

    def run(self, run, **env):
        done = subprocess.run(["bash", "-c", run], env=dict(self.env, **env), capture_output=True, text=True, timeout=120, cwd=self.tmp)
        assert done.returncode == 0, done.stdout + done.stderr
        return done.stdout

    def count(self, **env):
        s = step("autopilot.yml", "prep", "Count the round or the run")
        return self.run(s["run"], ISSUE="7", PR="8", **env)


def test_c1_the_flow_walked_through_keeps_its_counts_and_waits_on_the_boards(tmp_path, monkeypatch):
    w = World(tmp_path)
    for k, v in w.env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("DX_IO", raising=False)
    ap = autopilot()
    calls = []

    def fake_gh(*args, input_text=None):
        calls.append(" ".join(str(a) for a in args))
        return json.dumps({"comments": []}) if "view" in args else ""

    monkeypatch.setattr(ap, "gh", fake_gh)
    monkeypatch.setattr(ap, "refresh_board", lambda repo, number: None)
    monkeypatch.setenv("NUMBER", "7")
    monkeypatch.setenv("PR", "8")

    # A counted run.
    w.count(MODE="continue", RUNS="1")
    assert board(w.fx, 8)["runs"] == [{"n": 1, "free": False}]

    # A question: the issue's board says it waits for the answer.
    assert ap.main(["finish", "ask", "1. this, 2. that; I recommend 1."]) == 0
    assert board(w.fx, 7).get("asked")
    assert ap.next_step({"issue": {"state": "OPEN", "labels": ["accepted"], "asked": board(w.fx, 7)["asked"]}, "lane": "x"})["for"] == "answer"

    # The maintainer answers: the board says answered, before the continue.
    reply = step("review-reply.yml", "answer", "back")["run"]
    w.run(reply, NUMBER="7", IS_PR="false", LOGIN="boss")
    st = board(w.fx, 7)
    assert st.get("answered") is True and not st.get("asked")
    assert reply.index("answered=true") < reply.rindex('--add-label "autopilot:continue"')
    assert "gh issue edit 7 --repo o/r --add-label autopilot:continue" in w.log.read_text()

    # The run the answer started is free, and the answer is read once.
    w.count(MODE="continue", RUNS="2")
    assert board(w.fx, 8)["runs"] == [{"n": 1, "free": False}, {"n": 2, "free": True}]
    assert "answered" not in board(w.fx, 7)

    # The sweep's continue on a conflict: a catch-up, free too.
    w.run(step("autopilot-sweep.yml", "sweep", "Bring each one in step")["run"], OWNER="o", REPO="")
    assert board(w.fx, 7).get("catchup") is True
    w.count(MODE="continue", RUNS="3")
    assert board(w.fx, 8)["runs"][-1] == {"n": 3, "free": True}
    assert "catchup" not in board(w.fx, 7)
    ok, why = ap.may_continue([], "<!-- dx-checklist -->\n- [ ] **C1** x\n<!-- /dx-checklist -->\n", ap.run_numbers(board(w.fx, 8))[1], 2)
    assert ok, why
    assert ap.run_numbers(board(w.fx, 8)) == (4, 1)

    # A fix round.
    w.count(MODE="fix", ROUND="1")
    assert board(w.fx, 8)["rounds"] == 1

    # A wait for the core.
    gh_out = tmp_path / "end-out"
    gh_out.write_text("")
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    monkeypatch.setenv("CORE", "#5")
    monkeypatch.setenv("MODE", "start")
    monkeypatch.delenv("PR")
    assert ap.main(["end"]) == 0
    assert "verdict=core" in gh_out.read_text()
    assert board(w.fx, 7)["core_wait"] == 5
    assert set(board(w.fx, 8)) >= {"runs", "rounds"}

    # No step added, or created, any of the seven labels.
    said = w.log.read_text().splitlines() + calls
    assert [c for c in said if SEVEN.search(c)] == []


def test_c1_no_workflow_or_script_adds_the_seven_labels():
    for path in [*(ROOT / ".github/workflows").glob("*.yml"), ROOT / "scripts/autopilot.py", ROOT / "scripts/receipts.py"]:
        text = path.read_text(encoding="utf-8")
        adds = re.findall(r"(?:--add-label|label create)[ \"']+(autopilot:[a-z-]+)", text)
        assert [a for a in adds if SEVEN.search(a)] == [], path.name
    labels = yaml.safe_load((ROOT / "labels.yml").read_text(encoding="utf-8"))
    names = [l["name"] for l in (labels if isinstance(labels, list) else labels.get("labels", []))]
    assert [n for n in names if SEVEN.search(n)] == []


def test_c1_a_board_edited_by_hand_reads_as_the_cap_reached():
    ap = autopilot()
    ok, why = ap.may_continue([], "<!-- dx-checklist -->\n- [ ] **C1** x\n<!-- /dx-checklist -->\n", ap.run_numbers({}, intact=False)[1], 5)
    assert not ok and "cap is 5" in why
