"""How a test of a script's logic is written here (#376): the house style the
reproduction's writer reads (.github/review-policy.yml, `repro.ways.python`).

The scripts' names have hyphens, so a test loads one with importlib from the
repository's root and calls its functions, as the script's own `--test` does;
or it runs the script as a command, as a workflow does. No network, no `gh`,
no token: what the script reads comes from the test (`tmp_path`, `env=`).
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    """scripts/<name>.py as a module."""
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_double_star_spans_folders_and_a_single_one_does_not():
    ways = load("repro-ways")
    assert ways.glob_match("assets/css/a.css", "assets/**/*.css")
    assert not ways.glob_match("assets/css/a.css", "assets/*.css")


def test_a_junit_report_with_a_failed_assertion_is_a_reproduction(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text('<testsuites><testsuite><testcase name="x" classname="issue-1.spec.ts">'
                      '<failure message="Error: expect(received).toBe(expected)"/></testcase></testsuite></testsuites>')
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "repro-ways.py"), "verdict", str(report), "issue-1.spec.ts"],
                         capture_output=True, text=True, cwd=ROOT)
    assert (out.returncode, out.stdout.strip()) == (0, "reproduced")
