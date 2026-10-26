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
    for name in ("integration", "e2e"):
        go = wf["jobs"][name]["env"]["GO"]
        assert "!(github.event_name == 'pull_request' && vars.DX_MERGE_QUEUE == 'on')" in go, name


def test_the_bot_queues_where_there_is_a_queue_and_squashes_elsewhere():
    text = (ROOT / ".github/workflows/auto-merge.yml").read_text(encoding="utf-8")
    assert workflow("auto-merge.yml")["env"]["METHOD"] == "${{ vars.DX_MERGE_QUEUE != 'on' && '--squash' || '' }}"
    assert "--auto --squash" not in text
    assert text.count('--auto ${METHOD:+"$METHOD"}') == 5


def test_the_plugin_template_runs_in_a_merge_group():
    wf = yaml.safe_load((ROOT / "workflow-templates/plugin-checks-wp.yml").read_text(encoding="utf-8"))
    assert triggers(wf)["merge_group"] == {"types": ["checks_requested"]}
