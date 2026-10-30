"""The merge queue (#451): the organisation's pipeline runs in a queue's
group with only its `queue` job, the slow suites move to the group where the
repository has a queue, and the bot queues instead of naming a merge method."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def triggers(wf):
    return wf.get("on", wf.get(True))


def test_the_pipeline_runs_in_a_merge_group_with_only_its_queue_job():
    wf = workflow("org-pull-request.yml")
    assert triggers(wf)["merge_group"] == {"types": ["checks_requested"]}
    for name, job in wf["jobs"].items():
        cond = " ".join(str(job.get("if", "")).split())
        if name == "queue":
            assert "github.event_name == 'merge_group'" in cond and job["permissions"] == {}
        elif name != "wake-vm":
            assert "github.event_name == 'pull_request'" in cond, name


def test_the_slow_suites_run_in_the_group_where_the_repository_has_a_queue():
    wf = workflow("plugin-tests-wp.yml")
    go = wf["jobs"]["integration"]["env"]["GO"]
    assert "!(github.event_name == 'pull_request' && vars.DX_MERGE_QUEUE == 'on')" in go
    # #479: the E2E suites run at the pull request's level there, when it
    # has mapped specs, reproduction tests or a smoke set to run.
    go = wf["jobs"]["e2e"]["env"]["GO"]
    assert "!(github.event_name == 'pull_request' && vars.DX_MERGE_QUEUE == 'on' && needs.changes.outputs.quick != 'true')" in go


def step(job, name):
    return next(s for s in workflow("plugin-tests-wp.yml")["jobs"][job]["steps"] if s.get("name") == name or s.get("id") == name)


def test_a_queues_pull_request_runs_the_mapped_specs_and_the_smoke_set():
    """#479 C3: the plan is the pull request's alone; at the pull request's
    level (a queue) e2e-run.sh runs its mapped specs and the smoke set."""
    wf = workflow("plugin-tests-wp.yml")
    e2e = wf["jobs"]["e2e"]
    assert e2e["env"]["LEVEL"] == "${{ github.event_name == 'pull_request' && vars.DX_MERGE_QUEUE == 'on' && 'pr' || '' }}"
    plan = step("changes", "targeted")
    assert plan["if"] == "github.event_name == 'pull_request'"
    assert wf["jobs"]["changes"]["outputs"]["quick"] == "${{ steps.targeted.outputs.quick }}"
    run = step("e2e", "Run the suite")["run"]
    assert '[ "$LEVEL" = pr ]' in run and "e2e-run.sh run" in run
    central = [s for s in e2e["steps"] if (s.get("with") or {}).get("repository") == "DiluxOne/.github"]
    assert central and "env.LEVEL == 'pr'" in central[0]["if"]


def quick(plan):
    import subprocess
    script = step("changes", "targeted")["run"]
    line = next(l for l in script.splitlines() if l.strip().startswith("quick="))
    out = subprocess.run(["bash", "-c", f"plan='{plan}'; {line.strip()}; echo $quick"], capture_output=True, text=True)
    return out.stdout.strip()


def test_quick_says_whether_the_pull_request_level_has_anything_to_run():
    assert quick('{"targeted":false,"tests":[],"repro":[],"smoke":["s.spec.ts"]}') == "true"
    assert quick('{"targeted":false,"tests":["a.spec.ts"],"repro":[]}') == "true"
    assert quick('{"targeted":false,"tests":[],"repro":[],"smoke":[]}') == "false"
    assert quick('not json') == "false"


def test_the_queue_runs_every_suite_whole():
    """#479 C3: in the merge group there is no plan and no level, so each
    suite's command runs whole, integration included."""
    wf = workflow("plugin-tests-wp.yml")
    for name in ("integration", "e2e"):
        go = wf["jobs"][name]["env"]["GO"]
        # Every condition that skips is the pull request's.
        assert go.count("github.event_name == 'pull_request'") == 1, name
    run = step("e2e", "Run the suite")["run"]
    assert 'bash -c "$RUN"' in run


def test_the_bot_queues_where_there_is_a_queue_and_squashes_elsewhere():
    text = (ROOT / ".github/workflows/auto-merge.yml").read_text(encoding="utf-8")
    assert workflow("auto-merge.yml")["env"]["METHOD"] == "${{ vars.DX_MERGE_QUEUE != 'on' && '--squash' || '' }}"
    assert "--auto --squash" not in text
    assert text.count('--auto ${METHOD:+"$METHOD"}') == 5


def test_the_plugin_template_runs_in_a_merge_group():
    wf = yaml.safe_load((ROOT / "workflow-templates/plugin-checks-wp.yml").read_text(encoding="utf-8"))
    assert triggers(wf)["merge_group"] == {"types": ["checks_requested"]}
