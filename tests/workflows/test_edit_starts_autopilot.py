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

import yaml

try:
    import steps
except ModuleNotFoundError:  # #845: with no helper, each test fails on its assertion, not on this import
    import types

    def _missing(*_args, **_kwargs):
        helper = Path(__file__).with_name("steps.py")
        assert helper.is_file(), f"{helper.name}, which runs a workflow's step with stubs, is missing"

    steps = types.SimpleNamespace(evaluate=_missing, receipt=_missing, run=_missing, step=_missing, where=_missing, workflow=_missing)
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
    # Its Spec or its pull request already there: no second start.
    assert autopilot.edit_starts(autopilot.next_step(dict(state, spec=True)), {"shape_refused": "t"}) is False


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
    assert job["with"]["mode"] == "${{ github.event.label.name == 'autopilot:continue' && 'continue' || 'start' }}"


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
