"""The flow's old labels move onto the boards (#802 C2): scripts/receipts.py
migrate, for one open item, writes on its board the state its labels meant,
reads the board back, and only then takes the labels off; the runs cap
counts the same runs from the board as it did from the labels, and a second
run changes nothing. Runs receipts.py itself against its fixture
(RECEIPTS_FIXTURE: the boards, the items' labels and the call log)."""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RECEIPTS = ROOT / "scripts/receipts.py"
CHECKLIST = "<!-- dx-checklist -->\n- [ ] **C1** x\n<!-- /dx-checklist -->\n"


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def world(tmp_path):
    fx = tmp_path / "fx"
    (fx / "labels").mkdir(parents=True)
    (fx / "labels" / "8.json").write_text(json.dumps(["autopilot", "autopilot:run-1", "autopilot:free-2", "autopilot:run-3", "autopilot:round-2"]))
    (fx / "labels" / "7.json").write_text(json.dumps(["accepted", "autopilot:waiting", "autopilot:core-wait"]))
    # The autopilot's comment on the core, which names the pull request it waits for.
    (fx / "comments" / "7").mkdir(parents=True)
    (fx / "comments" / "7" / "mentions.md").write_text("<!-- dx-autopilot-core -->\nThe autopilot waits for #5: it changes the core.\n---\n")
    body = tmp_path / "body.md"
    body.write_text("### Problem\n\nx\n")
    env = dict(os.environ, RECEIPTS_FIXTURE=str(fx), GITHUB_REPOSITORY="o/r", AUTOPILOT_JSON="null", HELD="", BODY=str(body))
    env.pop("LABELS_JSON", None)
    return fx, env


def migrate(env, number, item):
    return subprocess.run([sys.executable, str(RECEIPTS), "migrate"], env=dict(env, NUMBER=str(number), ITEM=item),
                          capture_output=True, text=True, timeout=60)


def state(fx, number):
    rc = load("receipts_c2_state", "receipts.py")
    path = fx / "comments" / str(number) / "board.md"
    return rc.parse_state(path.read_text(encoding="utf-8") if path.exists() else "")


def test_c2_the_labels_move_to_the_board_before_they_come_off(tmp_path):
    fx, env = world(tmp_path)
    for number, item in ((8, "pr"), (7, "issue")):
        done = migrate(env, number, item)
        assert done.returncode == 0, done.stdout + done.stderr
    pr, ok = state(fx, 8)
    assert ok and pr["runs"] == [{"n": 1, "free": False}, {"n": 2, "free": True}, {"n": 3, "free": False}] and pr["rounds"] == 2
    issue, ok = state(fx, 7)
    assert ok and issue["asked"] is True and issue["core_wait"] == 5
    assert json.loads((fx / "labels" / "8.json").read_text()) == ["autopilot"]
    assert json.loads((fx / "labels" / "7.json").read_text()) == ["accepted"]
    # Written, read back, and only then a label taken off: on each item.
    log = (fx / "calls.log").read_text().splitlines()
    for n in ("8", "7"):
        mine = [l for l in log if l.split()[1] == n]
        writes = [i for i, l in enumerate(mine) if l.startswith("write ")]
        removes = [i for i, l in enumerate(mine) if l.startswith("unlabel ")]
        assert writes and len(removes) == (4 if n == "8" else 2)
        assert any(l.startswith("read ") for l in mine[writes[-1] + 1:removes[0]]), mine
        assert max(writes) < min(removes)


def test_c2_the_cap_counts_the_same_runs_and_a_second_run_changes_nothing(tmp_path):
    fx, env = world(tmp_path)
    migrate(env, 8, "pr")
    ap = load("autopilot_c2", "autopilot.py")
    pr, ok = state(fx, 8)
    # From the labels, the autopilot gave run 4 next, with 2 runs counted.
    assert ap.run_numbers(pr, ok) == (4, 2)
    assert ap.may_continue(["autopilot"], CHECKLIST, ap.run_numbers(pr, ok)[1], 3)[0] is True
    assert ap.may_continue(["autopilot"], CHECKLIST, ap.run_numbers(pr, ok)[1], 2)[0] is False
    before = ((fx / "comments" / "8" / "board.md").read_text(), (fx / "calls.log").read_text())
    again = migrate(env, 8, "pr")
    assert again.returncode == 0, again.stderr
    log = (fx / "calls.log").read_text()[len(before[1]):]
    assert (fx / "comments" / "8" / "board.md").read_text() == before[0]
    assert "write " not in log and "unlabel " not in log


def test_c2_a_count_already_on_the_board_is_never_lowered():
    rc = load("receipts_c2_pure", "receipts.py")
    on_board = {"runs": [{"n": 1, "free": False}, {"n": 2, "free": False}, {"n": 4, "free": False}], "rounds": 3, "waits": {"role": "x"}}
    got = rc.state_from_labels(["autopilot:free-2", "autopilot:run-3", "autopilot:round-1", "autopilot:answered", "autopilot:catchup"], on_board)
    assert got["runs"] == [{"n": 1, "free": False}, {"n": 2, "free": False}, {"n": 3, "free": False}, {"n": 4, "free": False}]
    assert got["rounds"] == 3 and got["answered"] is True and got["catchup"] is True and got["waits"] == {"role": "x"}
    assert rc.state_from_labels(["autopilot", "needs-human"], on_board) == on_board
    assert rc.old_labels(["autopilot", "autopilot:continue", "autopilot:run-1", "autopilot:waiting", "autopilot:round-x"]) == ["autopilot:run-1", "autopilot:waiting"]


def test_c2_a_board_edited_by_hand_keeps_its_labels(tmp_path):
    fx, env = world(tmp_path)
    rc = load("receipts_c2_tamper", "receipts.py")
    (fx / "comments" / "8").mkdir(parents=True)
    (fx / "comments" / "8" / "board.md").write_text(rc.pr_board_text({"runs": [{"n": 1, "free": False}]}).replace('"free":false', '"free":true'))
    done = migrate(env, 8, "pr")
    assert done.returncode == 3
    assert "autopilot:run-1" in json.loads((fx / "labels" / "8.json").read_text())
    assert "unlabel " not in ((fx / "calls.log").read_text() if (fx / "calls.log").exists() else "")


def test_c2_the_sweep_migrates_every_open_item_before_it_reads_a_board():
    steps = yaml.safe_load((ROOT / ".github/workflows/autopilot-sweep.yml").read_text(encoding="utf-8"))["jobs"]["sweep"]["steps"]
    names = [s.get("name") for s in steps]
    mig = next(s for s in steps if "receipts.py migrate" in (s.get("run") or ""))
    assert names.index(mig["name"]) < names.index("Bring each one in step")
    run = mig["run"]
    assert "--label autopilot " in run and 'ITEM="$item"' in run
    for label in ("waiting", "answered", "catchup", "core-wait"):
        assert label in run
    assert mig["env"]["GH_TOKEN"] == "${{ steps.bot.outputs.token }}"
    assert re.search(r"\$\{\{[^}]*\}\}", run) is None


def test_c2_a_run_migrates_its_own_items_before_it_counts():
    """A run between the deploy and the next sweep never counts from a board
    that lacks what the labels said: prep migrates its pull request and its
    issue before it reads the next run, and stops when it cannot."""
    prep = yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))["jobs"]["prep"]["steps"]
    run = next(s for s in prep if s.get("id") == "what")["run"]
    mig = run.index('NUMBER="$PR" ITEM=pr python3 .dx-central/scripts/receipts.py migrate\n')
    assert mig < run.index("autopilot.py next-run")
    assert run.index('NUMBER="$ISSUE" python3 .dx-central/scripts/receipts.py migrate\n') < run.index("autopilot.py next-run")
    reply = yaml.safe_load((ROOT / ".github/workflows/review-reply.yml").read_text(encoding="utf-8"))["jobs"]["answer"]["steps"]
    back = next(s for s in reply if s.get("id") == "back")["run"]
    assert back.index("receipts.py migrate") < back.index("state get asked")


def test_c2_a_fixture_without_labels_gets_no_call_log(tmp_path):
    """The call log is the migration's world only: another script's fixture
    (triage-act.sh's seals, which must stay empty when nothing is sealed) is
    left as its test made it."""
    fx = tmp_path / "fx"
    fx.mkdir()
    env = dict(os.environ, RECEIPTS_FIXTURE=str(fx), GITHUB_REPOSITORY="o/r", NUMBER="7")
    done = subprocess.run([sys.executable, str(RECEIPTS), "state", "get", "asked"], env=env,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode in (0, 1), done.stdout + done.stderr
    assert not (fx / "calls.log").exists()
