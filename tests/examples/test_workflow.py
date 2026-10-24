"""How a test of a workflow's wiring is written here (#376): the house style
the reproduction's writer reads (.github/review-policy.yml,
`repro.ways.workflow`).

It reads the workflow's file as YAML and asserts its triggers, the order of
its steps and their conditions; it never runs the workflow. PyYAML reads the
key `on` as the boolean True.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def step_names(job):
    return [step.get("name") or step.get("id") or step.get("uses", "") for step in job["steps"]]


def test_the_reproduction_is_a_reusable_workflow():
    triggers = workflow("issue-repro.yml").get("on", workflow("issue-repro.yml").get(True))
    assert "workflow_call" in triggers


def test_the_way_is_resolved_only_after_the_start_is_decided():
    write = workflow("issue-repro.yml")["jobs"]["write"]
    names = step_names(write)
    assert names.index("Start a reproduction?") < names.index("The way to reproduce")
    way = next(step for step in write["steps"] if step.get("id") == "way")
    assert way["if"] == "steps.start.outputs.go == 'yes'"
