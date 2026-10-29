import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_node_test_junit_without_file_with_a_failed_assert_is_reproduced(tmp_path):
    # What node:test's junit reporter writes: name = the test title,
    # classname="test", no `file`.
    report = tmp_path / "junit.xml"
    report.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites name="test" tests="1" failures="1">'
        '<testsuite name="test" tests="1" failures="1">'
        '<testcase name="the player keeps its volume" time="0.01" classname="test">'
        '<failure type="testCodeFailure" message="Expected values to be strictly equal:\n\n1 !== 2\n">'
        "AssertionError [ERR_ASSERTION]: Expected values to be strictly equal"
        "</failure></testcase></testsuite></testsuites>"
    )
    ways = load("repro-ways")
    assert ways.verdict(str(report), "issue-239.test.mts") == "reproduced"
