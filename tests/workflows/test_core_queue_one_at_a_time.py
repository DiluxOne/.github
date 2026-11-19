"""#832 C1: two issues waiting on the core (`core_wait` on their boards) when
the core is freed: only the oldest starts, and the other starts when that one
ends. autopilot-sweep.yml's step, run with gh stood in and scripts/
receipts.py's fixture boards, and scripts/autopilot.py's pure core_next."""
import datetime
import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def autopilot():
    spec = importlib.util.spec_from_file_location("autopilot_core_queue", ROOT / "scripts/autopilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def core_next(*args):
    ap = autopilot()
    assert hasattr(ap, "core_next"), "scripts/autopilot.py has no core_next"
    return {(r, n): what for r, n, what in ap.core_next(*args)}


def wf(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def step(workflow, job, name):
    return next(s for s in wf(workflow)["jobs"][job]["steps"] if s.get("id") == name or s.get("name") == name)


def board(fx, number):
    path = fx / "comments" / str(number) / "board.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    m = re.search(r"<!-- dx-state v1 (.*?) -->", text, re.S)
    data = json.loads(m.group(1)) if m else {}
    data.pop("sha256", None)
    return data


NOW = datetime.datetime(2026, 11, 18, 12, 0, tzinfo=datetime.timezone.utc)


def test_core_next_starts_only_the_oldest_waiter_of_each_repository():
    waiters = [{"repo": "o/r", "number": 9}, {"repo": "o/r", "number": 7}, {"repo": "o/s", "number": 3}]
    got = core_next(waiters, [], NOW)
    assert got == {("o/r", 7): "start", ("o/r", 9): "first 7", ("o/s", 3): "start"}


def test_core_next_starts_none_while_one_started_is_still_in_its_spec():
    at = (NOW - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    got = core_next([{"repo": "o/r", "number": 9}], [{"repo": "o/r", "number": 7, "at": at}], NOW)
    assert got == {("o/r", 9): "first 7"}


def test_core_next_lets_a_start_older_than_six_hours_go():
    old = (NOW - datetime.timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    got = core_next([{"repo": "o/r", "number": 9}], [{"repo": "o/r", "number": 7, "at": old}], NOW)
    assert got == {("o/r", 7): "expired", ("o/r", 9): "start"}
    # A time that cannot be read holds nothing either.
    got = core_next([{"repo": "o/r", "number": 9}], [{"repo": "o/r", "number": 7, "at": "x"}], NOW)
    assert got == {("o/r", 7): "expired", ("o/r", 9): "start"}


class World:
    """o/r with two accepted issues, #7 and #9, both waiting on the core, and
    no open autopilot pull request: a gh that logs every call."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.fx = tmp_path / "fx"
        self.fx.mkdir()
        (tmp_path / ".dx-central").symlink_to(ROOT)
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.log = tmp_path / "calls.log"
        self.log.write_text("")
        (self.bin / "gh").write_text(
            "#!/bin/bash\n"
            f'echo "gh $*" >> "{self.log}"\n'
            'case "$*" in\n'
            "  'search prs'*) ;;\n"
            "  'search issues'*) printf 'o/r 9\\no/r 7\\n' ;;\n"
            "  *'search/issues'*) echo 2 ;;\n"
            "  *'--json body'*) echo body ;;\n"
            "esac\n")
        (self.bin / "gh").chmod(0o755)
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", RUNNER_TEMP=str(tmp_path), GITHUB_REPOSITORY="o/r",
                        RECEIPTS_FIXTURE=str(self.fx), OWNER="o", REPO="", DX_BOT_APP="dilux-bot", DX_BOT_LOGIN="dilux-bot[bot]")
        self.env.pop("DX_IO", None)

    def run(self, run, **env):
        done = subprocess.run(["bash", "-c", run], env=dict(self.env, **env), capture_output=True, text=True, timeout=120, cwd=self.tmp)
        assert done.returncode == 0, done.stdout + done.stderr
        return done.stdout

    def started(self):
        return re.findall(r"gh issue edit (\d+) --repo o/r --add-label autopilot:continue", self.log.read_text())


def test_c1_only_the_oldest_starts_and_the_other_when_that_one_ends(tmp_path):
    w = World(tmp_path)
    for n in ("7", "9"):
        w.run("python3 .dx-central/scripts/receipts.py state set core_wait=5", NUMBER=n)
    sweep = step("autopilot-sweep.yml", "sweep", "Bring each one in step")["run"]

    out = w.run(sweep)
    assert w.started() == ["7"], out
    assert "o/r#9: still waits, #7 goes first" in out
    assert "core_wait" not in board(w.fx, 7) and board(w.fx, 7).get("core_started")
    assert board(w.fx, 9).get("core_wait") == 5

    # The next sweep, #7 still in its Spec: #9 still waits.
    out = w.run(sweep)
    assert w.started() == ["7"], out
    assert "o/r#9: still waits, #7 goes first" in out

    # #7's draft opens: core_started comes off there (autopilot.yml), and its
    # pull request then holds the core until it merges or closes.
    draft = step("autopilot.yml", "draft", "draft")["run"]
    assert "receipts.py state set core_started=" in draft
    w.run("python3 .dx-central/scripts/receipts.py state set core_started=", NUMBER="7")
    # It merged: the core is free, and #9 starts.
    out = w.run(sweep)
    assert w.started() == ["7", "9"], out
    assert "core_wait" not in board(w.fx, 9) and board(w.fx, 9).get("core_started")


def test_c1_a_start_that_never_opened_its_draft_holds_the_queue_six_hours_at_most(tmp_path):
    w = World(tmp_path)
    w.run("python3 .dx-central/scripts/receipts.py state set core_wait=5", NUMBER="9")
    w.run("python3 .dx-central/scripts/receipts.py state set 'core_started=\"2026-01-01T00:00:00Z\"'", NUMBER="7")
    out = w.run(step("autopilot-sweep.yml", "sweep", "Bring each one in step")["run"])
    assert w.started() == ["9"], out
    assert "core_started" not in board(w.fx, 7)


def ended(tmp_path, **env):
    """autopilot.py end for #7, which holds the core (core_started on its
    board), with no pull request: its board afterwards, and the step's exit."""
    w = World(tmp_path)
    (w.bin / "gh").write_text(f"#!/bin/bash\necho \"gh $*\" >> \"{w.log}\"\n"
                              "case \"$*\" in *'--json comments'*) echo '{\"comments\": []}' ;; esac\n")
    w.run("python3 .dx-central/scripts/receipts.py state set 'core_started=\"2026-11-18T10:00:00Z\"'", NUMBER="7")
    done = subprocess.run(["python3", ".dx-central/scripts/autopilot.py", "end"], env=dict(w.env, NUMBER="7", PR="", **env),
                          capture_output=True, text=True, timeout=120, cwd=tmp_path)
    return board(w.fx, 7), done


def test_c1_a_run_that_waits_on_the_core_again_lets_the_queue_go(tmp_path):
    state, done = ended(tmp_path, CORE="#5")
    assert done.returncode == 0, done.stdout + done.stderr
    assert state.get("core_wait") == 5 and not state.get("core_started"), state


def test_c1_a_run_that_stops_lets_the_queue_go(tmp_path):
    state, done = ended(tmp_path, WHY="It broke.")
    assert "silent" in done.stdout and done.returncode == 1, done.stdout + done.stderr
    assert not state.get("core_started"), state
