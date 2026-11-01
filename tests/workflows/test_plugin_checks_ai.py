"""The checks of a plugin for coding agents (#552, C2): the caller runs the
shared workflow on a pull request and in a merge queue's group, and the
shared workflow runs the manifest check and the kind's review rules from the
organisation's checkout, never from the pull request."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def triggers(wf):
    return wf.get("on", wf.get(True))


def runs(job):
    return [str(s.get("run", "")) for s in job.get("steps") or []]


def test_the_caller_runs_on_a_pull_request_and_in_the_merge_queue():
    caller = load("workflow-templates/plugin-checks-ai.yml")
    on = triggers(caller)
    assert "pull_request" in on
    assert on["merge_group"] == {"types": ["checks_requested"]}
    uses = [j.get("uses", "") for j in caller["jobs"].values()]
    assert "DiluxOne/.github/.github/workflows/plugin-checks-ai.yml@v7" in uses


def test_the_shared_workflow_checks_the_manifests_of_every_tool():
    wf = load(".github/workflows/plugin-checks-ai.yml")
    assert "workflow_call" in triggers(wf)
    job = wf["jobs"]["manifests"]
    assert "python3 .dx-central/scripts/agent-manifests.py check ." in runs(job)
    central = [s for s in job["steps"] if (s.get("with") or {}).get("repository") == "DiluxOne/.github"]
    assert central and central[0]["with"]["path"] == ".dx-central"
    assert central[0]["with"]["ref"] == "${{ inputs.central-ref || job.workflow_sha }}"


def test_the_shared_workflow_runs_the_kind_s_rules_from_its_base_policy():
    wf = load(".github/workflows/plugin-checks-ai.yml")
    assert triggers(wf)["workflow_call"]["inputs"]["kind"]["default"] == "ai-agent-plugin"
    job = wf["jobs"]["review-rules"]
    assert any("scripts/kind.sh" in r for r in runs(job))
    assert any('review-rules.php --kind "$KIND" --repo .' in r for r in runs(job))


def test_nothing_writes_and_no_secret_is_read():
    wf = load(".github/workflows/plugin-checks-ai.yml")
    assert wf["permissions"] == {"contents": "read"}
    text = (ROOT / ".github/workflows/plugin-checks-ai.yml").read_text(encoding="utf-8")
    assert "secrets." not in text
    for job in wf["jobs"].values():
        for s in job["steps"]:
            if str(s.get("uses", "")).startswith("actions/checkout@"):
                assert s["with"]["persist-credentials"] is False


def test_the_pack_lists_the_workflow_as_its_battery():
    pack = load("kinds/ai-agent-plugin/pack.yml")
    assert "plugin-checks-ai.yml" in pack["workflows"]
    assert pack["own-checks"]["callers-of"] == ["plugin-checks-ai.yml"]
