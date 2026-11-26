"""An edit that makes an accepted issue pass starts the autopilot, with no
label (#699 C2). The autopilot that refuses an accepted issue for its shape
(G1) says so on the issue, once, with the refusal mark, and notes it on the
issue's board (`shape_refused`); an `edited` event of an issue that carries
`accepted` or `accepted-by:policy` and that note runs next-step from the
issue's state, and a `spec` step (G1 passes now, the seal still matches, no
Spec, no pull request, nobody holds it) starts the autopilot as an
acceptance does. A change of the sealed PRD still needs `accepted` again
(G2, option A of the Spec)."""
import importlib.util
from pathlib import Path
from unittest import mock

import yaml

try:
    import steps  # tests/workflows/steps.py: it runs a workflow's step with stubs
except ModuleNotFoundError:  # Test first's base has no steps.py (#845): there each call to it fails an assertion
    steps = mock.Mock(**{f"{n}.side_effect": AssertionError("tests/workflows/steps.py is missing") for n in ("evaluate", "run", "step", "workflow")})
run, step = steps.run, steps.step

ROOT = Path(__file__).resolve().parents[2]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


autopilot = load("autopilot_c2", "autopilot.py")


def jobs():
    return yaml.safe_load((ROOT / ".github/workflows/issue-triage.yml").read_text(encoding="utf-8"))["jobs"]


def test_next_step_on_an_edited_accepted_issue_starts_it():
    state = {"issue": {"state": "OPEN", "labels": ["accepted"]}, "lane": "human-issue", "may_start": [True, "ready"], "seal": "match"}
    step = autopilot.next_step(state)
    assert (step["action"], step["as"]) == ("spec", "start")
    assert autopilot.edit_starts(step, {"shape_refused": "2026-11-08T10:00:00Z"}) is True
    # Not refused for its shape: an edit starts nothing (its run is on its way).
    assert autopilot.edit_starts(step, {}) is False
    # Still not ready, or a changed PRD (G2): no start.
    assert autopilot.edit_starts(autopilot.next_step(dict(state, may_start=[False, "the issue is not ready (G1): x"])), {"shape_refused": "t"}) is False
    assert autopilot.edit_starts(autopilot.next_step(dict(state, seal="changed")), {"shape_refused": "t"}) is False
    # Its pull request already there: no second start.
    assert autopilot.edit_starts(autopilot.next_step(dict(state, prs=[{"number": 3, "state": "OPEN", "author_type": "Bot", "labels": ["autopilot"]}])), {"shape_refused": "t"}) is False


def test_an_edit_of_a_refused_issue_with_its_spec_starts_its_draft():
    # #1002 C1: the Spec is on the issue, next-step answers draft/start.
    state = {"issue": {"state": "OPEN", "labels": ["accepted"]}, "lane": "human-issue", "may_start": [True, "ready"], "seal": "match", "spec": True}
    step = autopilot.next_step(state)
    assert (step["action"], step["as"]) == ("draft", "start")
    assert autopilot.edit_starts(step, {"shape_refused": "t"}) is True
    assert autopilot.edit_starts(step, {}) is False


def test_the_edit_job_runs_next_step_on_an_accepted_issues_edit():
    job = jobs()["edit-start"]
    cond = " ".join(str(job["if"]).split())
    assert "github.event.action == 'edited'" in cond
    assert "contains(github.event.issue.labels.*.name, 'accepted')" in cond
    assert "contains(github.event.issue.labels.*.name, 'accepted-by:policy')" in cond
    run = "\n".join(s.get("run", "") for s in job["steps"])
    for piece in ("state get shape_refused", "autopilot.py lane", "autopilot.py holder", "receipts.py verify-prd",
                  "autopilot.py may-start", "autopilot.py taken", "autopilot.py next-step", "autopilot.py edit-starts",
                  "state set shape_refused="):
        assert piece in run, piece
    assert job["outputs"]["start"]


def test_the_start_takes_the_edit_as_an_acceptance():
    job = jobs()["autopilot"]
    assert "edit-start" in job["needs"]
    cond = " ".join(str(job["if"]).split())
    assert "(github.event.action == 'edited' && needs.edit-start.outputs.start == 'true')" in cond
    mode = steps.EXPR.fullmatch(job["with"]["mode"]).group(1)
    ctx = {"github.event.action": "labeled", "github.event.label.name": "autopilot:continue", "needs.edit-start.outputs.mode": ""}
    assert steps.evaluate(mode, ctx) == "continue"
    assert steps.evaluate(mode, dict(ctx, **{"github.event.label.name": "accepted"})) == "start"
    # #1002: an edit's start takes the mode edit-start says.
    edited = dict(ctx, **{"github.event.action": "edited", "github.event.label.name": ""})
    assert steps.evaluate(mode, dict(edited, **{"needs.edit-start.outputs.mode": "continue"})) == "continue"
    assert steps.evaluate(mode, dict(edited, **{"needs.edit-start.outputs.mode": "start"})) == "start"
    assert jobs()["edit-start"]["outputs"]["mode"] == "${{ steps.step.outputs.mode }}"


# #1002: the edit-start step with the central scripts stood in, but for
# next-step and edit-starts, which are the real ones.
REAL = str(ROOT / "scripts" / "autopilot.py")
EDIT_CENTRAL = """import json, os, runpy, sys
cmd = sys.argv[1:]
open(os.path.join(os.environ["RUNNER_TEMP"], "central.log"), "a").write(os.path.basename(sys.argv[0]) + " " + " ".join(cmd) + "\\n")
board = json.loads(os.environ.get("FAKE_BOARD") or "{}")
if cmd[:1] in (["next-step"], ["edit-starts"]):
    sys.argv = [REAL] + cmd
    runpy.run_path(REAL, run_name="__main__")
elif cmd[:2] == ["state", "get"]:
    print(json.dumps(board if len(cmd) == 2 else board.get(cmd[2])))
elif cmd[:1] == ["lane"]:
    print("human-issue")
elif cmd[:1] == ["holder"]:
    held = os.environ.get("FAKE_HOLDER", "")
    print(held or "nobody holds it")
    sys.exit(1 if held else 0)
elif cmd[:1] == ["verify-prd"]:
    seal = os.environ.get("FAKE_SEAL", "match")
    print(seal)
    sys.exit(0 if seal == "match" else 1)
elif cmd[:1] == ["may-start"]:
    print("ready")
elif cmd[:1] == ["taken"]:
    sys.exit(1 if os.environ.get("FAKE_TAKEN") else 0)
"""


def edited(tmp_path, body, **env):
    """The edit-start step on #9, refused for its shape, whose body is BODY."""
    files = {".dx-central/scripts/autopilot.py": f"REAL = {REAL!r}\n" + EDIT_CENTRAL,
             ".dx-central/scripts/receipts.py": f"REAL = {REAL!r}\n" + EDIT_CENTRAL}
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "body.md").write_text(body)
    gh = f'case "$*" in\n  "issue view 9"*) cat {tmp_path / "body.md"} ;;\nesac\n'
    ran = run(step("issue-triage.yml", "step", job="edit-start"), tmp_path, central=False, files=files, stubs={"gh": gh},
              env=dict({"NUMBER": "9", "GH_TOKEN": "t", "FAKE_BOARD": '{"shape_refused": "2026-11-23T10:00:00Z"}'}, **env))
    assert ran.code == 0, ran.stdout + ran.stderr
    return ran, (ran.temp / "central.log").read_text().splitlines()


PRD = "### Problem\n\nx\n\n### Scope\n\n- y\n"


def test_the_edit_of_an_issue_with_its_spec_starts_it_as_a_continue(tmp_path):
    ran, called = edited(tmp_path, PRD + "\n### Spec: approach\n\nz\n")
    assert ran.output.get("start") == "true", ran.stdout
    assert ran.output.get("mode") == "continue"
    assert "receipts.py state set shape_refused=" in called


# The central scripts' stand-in: each records its call; `lane` names one,
# `may-start` refuses with REFUSAL, `shape-refusal` writes the real words.
CENTRAL = """import os, sys
open(os.path.join(os.environ["RUNNER_TEMP"], "central.log"), "a").write(os.path.basename(sys.argv[0]) + " " + " ".join(sys.argv[1:]) + "\\n")
if sys.argv[1] == "lane":
    print("human-issue")
elif sys.argv[1] == "may-start":
    print(os.environ["REFUSAL"])
    sys.exit(1)
elif sys.argv[1] == "shape-refusal":
    print("refused: an edit that makes it pass starts it")
"""


def refused(tmp_path, as_, refusal):
    env = {"AS": as_, "MODE": as_, "ISSUE": "9", "PR": "", "GH_TOKEN": "t", "REFUSAL": refusal}
    files = {".dx-central/scripts/autopilot.py": CENTRAL, ".dx-central/scripts/receipts.py": CENTRAL}
    ran = run(step("autopilot.yml", "may", job="prep"), tmp_path, env=env, central=False,
              stubs={"sleep": ":", "gh": ":"}, files=files)
    return ran, (ran.temp / "central.log").read_text().splitlines()


def test_the_refusal_says_an_edit_starts_it(tmp_path):
    ran, called = refused(tmp_path, "start", "the issue is not ready (G1): x")
    assert ran.code == 0, ran.stderr
    assert ran.output["go"] == "false"
    assert "autopilot.py shape-refusal" in called
    noted = [c for c in called if c.startswith("receipts.py state set shape_refused=")]
    assert len(noted) == 1 and noted[0] != "receipts.py state set shape_refused="
    comments = [c for c in ran.of("gh") if c[:3] == ["issue", "comment", "9"] and "--body-file" in c]
    assert len(comments) == 1
    assert "an edit that makes it pass starts it" in autopilot.shape_refusal("the issue is not ready (G1): x")
    assert autopilot.shape_refusal("x").startswith(autopilot.SHAPE_MARK)


def test_a_refusal_for_anything_but_its_shape_notes_nothing(tmp_path):
    ran, called = refused(tmp_path, "start", "the lane is closed")
    assert ran.code == 0, ran.stderr
    assert not [c for c in called if "shape" in c]
    assert not [c for c in ran.of("gh") if "--body-file" in c]


def test_the_edit_of_an_issue_with_no_spec_starts_it_as_today(tmp_path):
    # #1002 C2: no Spec, next-step answers spec/start: a start, the agent writes it.
    ran, called = edited(tmp_path, PRD)
    assert (ran.output.get("start"), ran.output.get("mode")) == ("true", "start"), ran.stdout
    assert "receipts.py state set shape_refused=" in called


def test_a_changed_seal_a_hold_or_a_pull_request_start_nothing(tmp_path):
    for i, env in enumerate(({"FAKE_SEAL": "changed"}, {"FAKE_HOLDER": "held by @alice (`/claim`)"}, {"FAKE_TAKEN": "1"})):
        for j, body in enumerate((PRD, PRD + "\n### Spec: approach\n\nz\n")):
            ran, called = edited(tmp_path / f"{i}-{j}", body, **env)
            assert "start" not in ran.output and "mode" not in ran.output, (env, ran.stdout)
            assert "receipts.py state set shape_refused=" not in called, env


def test_the_edit_start_step_passes_shellcheck():
    # An unquoted `mode=continue` is shellcheck's SC2209 (`continue` is a
    # builtin), which fails actionlint (#1003, round 1): the modes are quoted.
    import shutil, subprocess
    import pytest
    if not shutil.which("shellcheck"):
        pytest.skip("no shellcheck")
    script = steps.expand(step("issue-triage.yml", "step", job="edit-start")["run"], {})
    # The ones actionlint leaves out of its shellcheck run.
    checked = subprocess.run(["shellcheck", "-s", "bash", "-e", "SC1091,SC2194,SC2050,SC2154,SC2157", "-"],
                             input=script, capture_output=True, text=True)
    assert checked.returncode == 0, checked.stdout
