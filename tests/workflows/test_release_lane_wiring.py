"""The release lane's wiring (#644): the callers tokens read the test
repository's checks and the workflow runs behind them, and a failed scenario
reaches the job that opens its bug instead of stopping the lane."""
import json
import os
import subprocess
from pathlib import Path

import yaml

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


def run_act_step(tmp_path, scenarios, written):
    """The act step's shell up to the decision, with `release-lane.py act`
    replaced by `decide` (which writes nothing to GitHub)."""
    step = next(s for s in jobs()["act"]["steps"] if s.get("id") == "act")
    script = step["run"].split("# Exit 1")[0]
    script = "\n".join(l for l in script.splitlines() if not l.startswith("git config"))
    tmp_path.mkdir()
    if written is not None:
        (tmp_path / "scenarios").mkdir()
        (tmp_path / "scenarios" / "results.md").write_text(
            f"| table |\n\n<!-- dx-scenarios {json.dumps(written)} -->\n", encoding="utf-8")
    plan = {"release": True, "version": "7.14.0", "major": "v7"}
    env = dict(os.environ, RUNNER_TEMP=str(tmp_path), PLAN=json.dumps(plan), SCENARIOS=scenarios,
               RUN_URL="https://github.com/DiluxOne/.github/actions/runs/1")
    script += f'\npython3 {ROOT}/scripts/release-lane.py decide --plan "$RUNNER_TEMP/plan.json" --results "$results"\n'
    out = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_a_failed_scenario_reaches_the_decision(tmp_path):
    act = jobs()["act"]
    # The decision runs when the scenarios job failed, never when the plan
    # releases nothing or the run was cancelled.
    cond = act["if"]
    assert "!cancelled()" in cond and "needs.plan.outputs.release == 'true'" in cond
    assert "needs.scenarios.result == 'failure'" in cond and "always()" not in cond
    upload = next(s for s in jobs()["scenarios"]["steps"] if "upload-artifact" in s.get("uses", ""))
    assert upload["if"] == "${{ !cancelled() }}"
    download = next(s for s in act["steps"] if "download-artifact" in s.get("uses", ""))
    assert download["continue-on-error"] is True
    step = next(s for s in act["steps"] if s.get("id") == "act")
    assert step["env"]["SCENARIOS"] == "${{ needs.scenarios.result }}"

    failed = {"id": "callers", "ok": False, "why": ["checks unreadable"], "run": "https://github.com/x/t/actions/runs/9"}
    # A failed scenario is the bug, with its run.
    d = run_act_step(tmp_path / "a", "failure", [{"id": "s1", "ok": True, "run": ""}, failed])
    assert d["do"] == "bug" and d["scenario"] == "callers" and d["run"] == failed["run"]
    assert "`callers`" in d["body"] and failed["run"] in d["body"]
    # Every row passed but the job failed: still a bug, never a release.
    d = run_act_step(tmp_path / "b", "failure", [{"id": "s1", "ok": True, "run": ""}])
    assert d["do"] == "bug" and d["scenario"] == "scenarios"
    assert d["run"] == "https://github.com/DiluxOne/.github/actions/runs/1"
    # No results at all: a bug naming the job and this run.
    d = run_act_step(tmp_path / "c", "failure", None)
    assert d["do"] == "bug" and d["scenario"] == "scenarios" and "actions/runs/1" in d["body"]
    # A job that succeeded is read as it wrote.
    d = run_act_step(tmp_path / "d", "success", [{"id": "s1", "ok": True, "run": ""}])
    assert d["do"] == "release"
