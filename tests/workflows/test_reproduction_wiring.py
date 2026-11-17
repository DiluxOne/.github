"""The reproduction's wiring (#376): what no script's --test can see, read
from the workflows' files."""
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def steps(workflow, job):
    return load(f".github/workflows/{workflow}")["jobs"][job]["steps"]


def step(all_steps, name):
    return next(s for s in all_steps if s.get("name") == name)


def test_no_way_hands_it_to_a_person_before_any_model_runs():
    write = steps("issue-repro.yml", "write")
    names = [s.get("name") for s in write]
    no_way = step(write, "No way reproduces it")
    assert no_way["if"] == "steps.start.outputs.go == 'yes' && steps.way.outputs.ready != 'yes'"
    # #801: `needs-human`, and the board's step `no-way` with its reason.
    assert "--add-label needs-human" in no_way["run"]
    assert "{step: \"no-way\"" in no_way["run"] and "receipts.py state set" in no_way["run"]
    assert no_way["env"]["WHY"] == "${{ steps.way.outputs.why }}"
    assert names.index("The way to reproduce") < names.index("No way reproduces it") < names.index("Daily cap")
    assert "steps.way.outputs.ready == 'yes'" in step(write, "Daily cap")["if"]


def test_the_triage_can_choose_the_workflow_layer():
    triage = (ROOT / ".github/workflows/issue-triage.yml").read_text(encoding="utf-8")
    schemas = re.findall(r"DX_(?:FULL|PAID)_SCHEMA: '(\{.*\})'", triage)
    assert len(schemas) == 2
    for schema in schemas:
        assert "workflow" in json.loads(schema)["properties"]["layer"]["enum"]
    assert 'IN("logic","browser","cli","api","workflow")' in triage


def test_the_labels_exist_everywhere():
    names = {label["name"] for label in load("labels.yml")}
    assert {"needs-info", "needs-human", "bug:confirmed", "repro:run", "repro:again"} <= names


def test_ci_runs_tests_with_the_pytest_the_ways_install():
    ways = load(".github/review-policy.yml")["repro"]["ways"]
    pins = {w: re.findall(r"\b(pytest|PyYAML)==(\S+)", " ".join(way["setup"])) for w, way in ways.items()}
    ci = step(steps("pull-request.yml", "scripts"), "tests/ (pytest)")["run"]
    for found in pins.values():
        assert found and sorted(found) == sorted(re.findall(r"\b(pytest|PyYAML)==(\S+)", ci))
