"""#473: the unit job of plugin-checks-wp.yml runs the unit tests with no compiled translations.

A plugin's .mo are built, never committed (#452); the suites and the release
compile them (scripts/plugin-i18n.sh compile) first. The unit job must too,
before `composer test:unit`, or a unit test that reads languages/*.mo fails.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_the_unit_job_compiles_the_translations_before_the_unit_tests():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "plugin-checks-wp.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["unit"]["steps"]
    runs = [step.get("run", "") for step in steps]

    tests = next(i for i, run in enumerate(runs) if "composer test:unit" in run)
    compiled = [i for i, run in enumerate(runs) if "plugin-i18n.sh" in run and "compile" in run]

    assert compiled, "the unit job never compiles languages/*.po into .mo"
    assert min(compiled) < tests, "the unit job compiles the .mo only after the unit tests ran"
