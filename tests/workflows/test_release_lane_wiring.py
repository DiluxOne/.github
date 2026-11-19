"""The release lane's wiring (#644): the callers tokens read the test
repository's checks and the workflow runs behind them, and a failed scenario
reaches the job that opens its bug instead of stopping the lane."""
import json
from pathlib import Path

import yaml

from steps import run, step

ROOT = Path(__file__).resolve().parents[2]


def jobs():
    wf = yaml.safe_load((ROOT / ".github/workflows/release-lane.yml").read_text(encoding="utf-8"))
    return wf["jobs"]


def test_the_callers_tokens_may_read_the_checks_workflow_runs():
    tokens = [s for job in ("move", "play", "back") for s in jobs()[job]["steps"] if "create-github-app-token" in s.get("uses", "")]
    assert [t["id"] for t in tokens] == ["app", "back"]
    for t in tokens:
        w = t["with"]
        assert w["permission-checks"] == "read"
        assert w["permission-statuses"] == "read"
        assert w["permission-actions"] == "read"


def test_the_scenarios_have_time_and_the_play_step_stops_first():
    play = jobs()["play"]
    # Half an hour for each play job, and its play step stops before it, so
    # the results are still uploaded (#690); the step outlasts every
    # scenario's limit (#694: 15 minutes or less, release-scenarios.py plan).
    assert play["timeout-minutes"] == 30
    step = next(s for s in play["steps"] if s.get("id") == "play")
    assert step["name"] == "Play the group's scenarios at v7-next"
    assert 15 < step["timeout-minutes"] == 20 < play["timeout-minutes"]
    # The bug names the numbers the workflow uses, never others.
    env = next(s for s in jobs()["act"]["steps"] if s.get("id") == "act")["env"]
    assert int(env["SCENARIOS_TIMEOUT"]) == play["timeout-minutes"]
    assert int(env["PLAY_TIMEOUT"]) == step["timeout-minutes"]


GROUPS = [{"id": "serial", "scenarios": ["s1", "s2"]}, {"id": "s3", "scenarios": ["s3"]}]


# `release-lane.py act` as the act step calls it, with `act` read as `decide`
# (which writes nothing to GitHub); it records its call as a stub does.
DECIDE = """import json, os, runpy, sys
real = {real!r}
with open(os.environ["DX_CALLS"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(["release-lane.py", *sys.argv[1:]]) + "\\n")
sys.argv = [real] + ["decide" if a == "act" else a for a in sys.argv[1:]]
runpy.run_path(real, run_name="__main__")
"""


def run_act_step(tmp_path, results, written):
    """Run the act step (steps.run) in a copy of this checkout, with
    `release-lane.py act` read as `decide` and git stubbed; its decision, as it printed it. `written`: the
    rows each artifact (`move`, `back`, a group's id) holds, None for one
    its job left none of."""
    s = step("release-lane.yml", "act", job="act")
    # The step runs in this repository's checkout: every top entry but scripts/.
    work = tmp_path / "work"
    scripts = work / "scripts"
    scripts.mkdir(parents=True)
    for top in ROOT.iterdir():
        if top.name not in ("scripts", ".git", ".dx-central"):
            (work / top.name).symlink_to(top)
    for real in (ROOT / "scripts").iterdir():
        (scripts / real.name).symlink_to(real)
    (scripts / "release-lane.py").unlink()
    (scripts / "release-lane.py").write_text(DECIDE.format(real=str(ROOT / "scripts" / "release-lane.py")), encoding="utf-8")
    for name, rows in written.items():
        if rows is not None:
            d = tmp_path / "temp" / "scenarios" / f"scenarios-{name}"
            d.mkdir(parents=True)
            (d / "results.md").write_text(f"| table |\n\n<!-- dx-scenarios {json.dumps(rows)} -->\n", encoding="utf-8")
    plan = {"release": True, "version": "7.14.0", "major": "v7"}
    env = dict(PLAN=json.dumps(plan), SCENARIO_GROUPS=json.dumps(GROUPS),
               RUN_URL="https://github.com/DiluxOne/.github/actions/runs/1", **results)
    ran = run(s, tmp_path, env=env, stubs={"git": ""})
    assert ran.code == 0, ran.stderr
    # The decision reads the plan the step wrote and the table it merged.
    act = ran.of("release-lane.py")
    assert len(act) == 1 and act[0][0] == "act"
    assert act[0][act[0].index("--plan") + 1] == f"{tmp_path}/temp/plan.json"
    assert act[0][act[0].index("--results") + 1] == f"{tmp_path}/temp/results.md"
    d = json.loads(ran.stdout)
    assert ran.output["do"] == d["do"]
    return d


def ok(*ids):
    return [{"id": i, "ok": True, "run": ""} for i in ids]


def test_a_failed_scenario_reaches_the_decision(tmp_path):
    act = jobs()["act"]
    # The decision runs when the move ended, failed or not, never when the
    # plan releases nothing or the run was cancelled.
    cond = act["if"]
    assert "!cancelled()" in cond and "needs.plan.outputs.release == 'true'" in cond
    assert "needs.move.result == 'failure'" in cond and "always()" not in cond
    for job in ("play", "back"):
        upload = next(s for s in jobs()[job]["steps"] if "upload-artifact" in s.get("uses", ""))
        assert upload["if"] == "${{ !cancelled() }}"
    download = next(s for s in act["steps"] if "download-artifact" in s.get("uses", ""))
    assert download["continue-on-error"] is True and download["with"]["pattern"] == "scenarios-*"
    step = next(s for s in act["steps"] if s.get("id") == "act")
    assert {step["env"][k] for k in ("MOVE", "PLAY", "BACK")} == {f"${{{{ needs.{j}.result }}}}" for j in ("move", "play", "back")}

    done = {"MOVE": "success", "PLAY": "success", "BACK": "success"}
    every = {"move": [], "serial": ok("s1", "s2"), "s3": ok("s3"), "back": []}
    failed = {"id": "callers", "ok": False, "why": ["checks unreadable"], "run": "https://github.com/x/t/actions/runs/9"}
    # A failed row is the bug, with its run.
    d = run_act_step(tmp_path / "a", done, dict(every, back=[failed]))
    assert d["do"] == "bug" and d["scenario"] == "callers" and d["run"] == failed["run"]
    assert "`callers`" in d["body"] and failed["run"] in d["body"]
    # Every row passed but a play job failed: still a bug, never a release.
    d = run_act_step(tmp_path / "b", dict(done, PLAY="failure"), every)
    assert d["do"] == "bug" and d["scenario"] == "play"
    assert d["run"] == "https://github.com/DiluxOne/.github/actions/runs/1"
    # A group that timed out left no results: a bug naming it and this run.
    d = run_act_step(tmp_path / "c", dict(done, PLAY="failure"), dict(every, s3=None))
    assert d["do"] == "bug" and d["scenario"] == "s3" and "actions/runs/1" in d["body"]
    # Every job succeeded and every scenario passed: released.
    d = run_act_step(tmp_path / "d", done, every)
    assert d["do"] == "release"


def test_every_out_directory_is_made_in_its_job_before_it_is_written():
    """#693: back wrote into $RUNNER_TEMP/back/, which no step made."""
    import re
    for name, job in jobs().items():
        made = set()
        for step in job.get("steps", []):
            run = step.get("run", "")
            for line in run.splitlines():
                made.update(re.findall(r'mkdir -p "\$RUNNER_TEMP/([^"/]+)"', line))
                for d in re.findall(r'--out "\$RUNNER_TEMP/([^"/]+)/[^"]+"', line):
                    assert d in made, f"{name}: --out into $RUNNER_TEMP/{d}/ before any mkdir of it"


def test_a_timed_out_play_job_reaches_the_decision(tmp_path):
    # GitHub cancels a job past its timeout-minutes without cancelling the
    # run: the decision still runs, and a person's cancel still stops it (#690).
    cond = jobs()["act"]["if"]
    assert "!cancelled()" in cond and "always()" not in cond
    assert "needs.move.result == 'cancelled'" in cond
    done = {"MOVE": "success", "PLAY": "success", "BACK": "success"}
    every = {"move": [], "serial": ok("s1", "s2"), "s3": ok("s3"), "back": []}
    # A play job cancelled at its timeout, with no results: a bug.
    d = run_act_step(tmp_path / "a", dict(done, PLAY="cancelled"), dict(every, serial=None))
    assert d["do"] == "bug" and "actions/runs/1" in d["body"]
    assert d["scenario"] == "serial" and "its play step at 20 minutes, its job at 30" in d["body"]
    # Cancelled after every row it wrote passed: still a bug, never a release.
    d = run_act_step(tmp_path / "b", dict(done, PLAY="cancelled"), every)
    assert d["do"] == "bug" and d["scenario"] == "play" and "timeout of 30 minutes and was cancelled" in d["body"]
    # A play step stopped at its own timeout: the job failed, the bug says so.
    d = run_act_step(tmp_path / "c", dict(done, PLAY="failure"), every)
    assert d["do"] == "bug" and "its play step past its timeout of 20 minutes" in d["body"]
