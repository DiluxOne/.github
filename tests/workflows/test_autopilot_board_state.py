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
            "  *'search/issues'*) [ \"${TOTAL-0}\" = fail ] && exit 1; echo \"${TOTAL-0}\" ;;\n"
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

    # No step added, or created, any of the seven labels (a step may still
    # look for one an older run left, to keep its answer).
    said = w.log.read_text().splitlines() + calls
    assert [c for c in said if SEVEN.search(c) and re.search(r"--add-label|label create|labels -f|labels/", c)] == []


def test_the_sweep_fails_when_the_search_for_the_core_waits_gave_less_than_it_found(tmp_path):
    """#811: search gives 1000 at most; an accepted issue past them that
    waits on the core is never started, so the step says so and fails
    (after starting those it read), as it does when the count is unread."""
    w = World(tmp_path)
    run = step("autopilot-sweep.yml", "sweep", "Bring each one in step")["run"]
    for total, why in (("1500", "found 1500"), ("fail", "could not be counted")):
        done = subprocess.run(["bash", "-c", run], env=dict(w.env, OWNER="o", REPO="", TOTAL=total), capture_output=True, text=True,
                              timeout=120, cwd=w.tmp)
        assert done.returncode != 0 and why in done.stdout, done.stdout + done.stderr
        # the pull requests were still brought in step first
        assert "o/r#8: continue" in done.stdout
    assert 'search/issues -f q=is:issue is:open label:"accepted" user:o -f per_page=1' in w.log.read_text()
    w.run(run, OWNER="o", REPO="o/r", TOTAL="0")
    assert "label:\"accepted\" repo:o/r" in w.log.read_text()


OLD_SCRIPTS = "if grep -q '^FLOW_KEYS' .dx-central/scripts/receipts.py"


def test_c1_no_workflow_or_script_adds_the_seven_labels():
    """The scripts add none; a workflow adds one only in the branch it takes
    with scripts older than #802 (central-ref before it, or main's scripts
    while this change is not merged), which keep the flow in labels."""
    adds = lambda text: [a for a in re.findall(r"(?:--add-label|label create)[ \"']+(autopilot:[a-z-]+)", text) if SEVEN.search(a)]
    for path in (ROOT / "scripts/autopilot.py", ROOT / "scripts/receipts.py"):
        assert adds(path.read_text(encoding="utf-8")) == [], path.name
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        wf = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in (wf.get("jobs") or {}).values():
            for s in job.get("steps") or []:
                run = s.get("run") or ""
                if adds(run):
                    flow = "grep -q '^FLOW_KEYS' .dx-central/scripts/receipts.py"
                    assert flow in run, (path.name, s.get("name"))
                    assert run.index(flow) < min(run.index(a) for a in adds(run)), (path.name, s.get("name"))
    labels = yaml.safe_load((ROOT / "labels.yml").read_text(encoding="utf-8"))
    names = [l["name"] for l in (labels if isinstance(labels, list) else labels.get("labels", []))]
    assert [n for n in names if SEVEN.search(n)] == []


def test_c1_a_board_edited_by_hand_reads_as_the_cap_reached():
    ap = autopilot()
    ok, why = ap.may_continue([], "<!-- dx-checklist -->\n- [ ] **C1** x\n<!-- /dx-checklist -->\n", ap.run_numbers({}, intact=False)[1], 5)
    assert not ok and "cap is 5" in why


def test_c1_an_answer_on_a_board_that_cannot_be_read_fails_and_is_never_read_as_no_question(tmp_path):
    root = tmp_path / "r"
    (root / ".dx-central/scripts").mkdir(parents=True)
    # receipts.py stood in: its read fails (exit 1, not 3: not edited by hand).
    (root / ".dx-central/scripts/receipts.py").write_text("FLOW_KEYS = ()\nimport sys\nprint('gh: HTTP 502', file=sys.stderr)\nsys.exit(1 if sys.argv[1:2] == ['state'] else 0)\n")
    bin_dir = root / "bin"
    bin_dir.mkdir()
    log = root / "calls.log"
    (bin_dir / "gh").write_text(f'#!/bin/bash\necho "gh $*" >> "{log}"\n')
    (bin_dir / "gh").chmod(0o755)
    reply = step("review-reply.yml", "answer", "back")["run"]
    done = subprocess.run(["bash", "-c", reply], env=dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", RUNNER_TEMP=str(root), GITHUB_REPOSITORY="o/r",
                                                          NUMBER="7", IS_PR="false", LOGIN="boss", GITHUB_OUTPUT=str(root / "out")),
                          capture_output=True, text=True, timeout=120, cwd=root)
    assert done.returncode == 1 and "board could not be read: gh: HTTP 502" in done.stdout + done.stderr
    assert "autopilot:continue" not in (log.read_text() if log.exists() else "")


def reply_with(tmp_path, receipts, labels_say):
    """review-reply's answer step, with receipts.py and gh stood in: gh says
    `labels_say` when asked whether the issue still carries autopilot:waiting."""
    root = tmp_path / "r"
    (root / ".dx-central/scripts").mkdir(parents=True)
    (root / ".dx-central/scripts/receipts.py").write_text(receipts)
    bin_dir = root / "bin"
    bin_dir.mkdir()
    log = root / "calls.log"
    (bin_dir / "gh").write_text(f'#!/bin/bash\necho "gh $*" >> "{log}"\ncase "$*" in *index*autopilot:waiting*) echo {labels_say} ;; esac\n')
    (bin_dir / "gh").chmod(0o755)
    (bin_dir / "python3").write_text(
        "#!/bin/bash\n"
        f'echo "python3 $*" >> "{log}"\n'
        'case "$1" in *deciders.py) echo "boss decides"; exit 0 ;; esac\n'
        f'exec "{sys.executable}" "$@"\n')
    (bin_dir / "python3").chmod(0o755)
    reply = step("review-reply.yml", "answer", "back")["run"]
    done = subprocess.run(["bash", "-c", reply], env=dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", RUNNER_TEMP=str(root), GITHUB_REPOSITORY="o/r",
                                                          NUMBER="7", IS_PR="false", LOGIN="boss", GITHUB_OUTPUT=str(root / "out")),
                          capture_output=True, text=True, timeout=120, cwd=root)
    return done, log.read_text()


def test_an_answer_is_kept_when_the_migration_could_not_move_the_question(tmp_path):
    """migrate fails (a board edited by hand, or GitHub down): the label it
    could not move still waits, and the answer still brings the autopilot
    back, in the labels when the board cannot be written."""
    receipts = ("FLOW_KEYS = ()\nimport sys\n"
                "if sys.argv[1:2] == ['migrate']: sys.exit(3)\n"
                "if sys.argv[1:3] == ['state', 'get']: print('null'); sys.exit(3)\n"
                "if sys.argv[1:3] == ['state', 'set']: sys.exit(3)\n")
    done, calls = reply_with(tmp_path, receipts, "true")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "--add-label autopilot:answered --add-label autopilot:continue --remove-label autopilot:waiting" in calls


def test_with_scripts_older_than_802_an_answer_goes_in_the_labels(tmp_path):
    done, calls = reply_with(tmp_path, "# before #802\nimport sys\nsys.exit(64)\n", "true")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "migrate" not in calls and "state " not in calls
    assert "--add-label autopilot:answered --add-label autopilot:continue --remove-label autopilot:waiting" in calls
