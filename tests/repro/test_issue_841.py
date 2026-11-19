"""#841: a workflow-layer reproduction that only reads the workflow's file and
asserts on its text confirmed a bug that may not exist. The reproduction
lane's verdict (scripts/repro-ways.py verdict, with the way's SPEC that
scripts/repro-run.sh exports) must say such a test is broken, "the test runs
no step", whatever its JUnit report shows; a test that runs the step with
stubs and fails an assertion still reproduces the bug.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "repro-ways.py"

GREP_ONLY = '''from pathlib import Path

import yaml


def test_the_step_passes_the_flag():
    wf = yaml.safe_load(Path(".github/workflows/x.yml").read_text())
    assert "--flag" in wf["jobs"]["a"]["steps"][0]["run"]
'''

STUBBED = '''import subprocess

import yaml


def test_the_step_calls_gh_with_the_flag(tmp_path):
    script = yaml.safe_load(open(".github/workflows/x.yml"))["jobs"]["a"]["steps"][0]["run"]
    (tmp_path / "gh").write_text("#!/bin/sh\\necho \\"$@\\" >> \\"$LOG\\"\\n")
    (tmp_path / "gh").chmod(0o755)
    subprocess.run(["bash", "-c", script], env={"PATH": f"{tmp_path}:/usr/bin:/bin", "LOG": str(tmp_path / "log")})
    assert "--flag" in (tmp_path / "log").read_text()
'''

FAILED_ASSERTION = ('<testsuites><testsuite name="pytest"><testcase classname="tests.repro.test_issue_9" name="test_it" '
                    'file="tests/repro/test_issue_9.py" line="3"><failure message="AssertionError: assert \'--flag\' in \'gh pr list\'">'
                    'def test_it():\n&gt;       assert "--flag" in run\nE       AssertionError</failure></testcase></testsuite></testsuites>')


def the_workflow_way():
    """The spec the lane runs this repository's `workflow` way with."""
    env = dict(os.environ, DIR=str(ROOT), LAYER="workflow", NUMBER="9", REPO="DiluxOne/.github")
    out = subprocess.run([sys.executable, str(SCRIPT), "resolve"], env=env, capture_output=True, text=True, cwd=ROOT).stdout
    lines = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    assert lines.get("way") == "workflow", out
    return json.loads(lines["spec"])


def lane_verdict(tmp_path, test_text):
    """The verdict the lane reaches on a failed assertion's report, for a test
    whose text is TEST_TEXT."""
    test = tmp_path / "tests" / "repro" / "test_issue_9.py"
    test.parent.mkdir(parents=True)
    test.write_text(test_text, encoding="utf-8")
    junit = tmp_path / "junit.xml"
    junit.write_text(FAILED_ASSERTION, encoding="utf-8")
    spec = dict(the_workflow_way(), test="tests/repro/test_issue_9.py")
    env = dict(os.environ, SPEC=json.dumps(spec))
    done = subprocess.run([sys.executable, str(SCRIPT), "verdict", str(junit), "test_issue_9.py", ""],
                          env=env, capture_output=True, text=True, cwd=tmp_path)
    return done.stdout.strip(), done.stderr


def test_a_workflow_test_that_only_reads_the_file_is_broken_not_a_reproduction(tmp_path):
    verdict, why = lane_verdict(tmp_path, GREP_ONLY)
    assert verdict == "broken", f"a test that runs no step confirmed the bug ({verdict})"
    assert "the test runs no step" in why


ECHO = '''import subprocess


def test_something_runs():
    assert subprocess.run(["echo", "hi"]).returncode == 1
'''

RUNS_THE_SCRIPT = '''import subprocess as sp
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_step_script_says_why():
    done = sp.run([sys.executable, str(ROOT / "scripts" / "fix-it.py")], capture_output=True, text=True)
    assert done.returncode == 1
'''


def test_a_workflow_test_that_runs_some_other_command_is_broken(tmp_path):
    verdict, why = lane_verdict(tmp_path, ECHO)
    assert (verdict, "the test runs no step" in why) == ("broken", True), f"a test that runs `echo hi` confirmed the bug ({verdict})"


def test_a_workflow_test_that_runs_the_script_the_step_calls_reproduces(tmp_path):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "x.yml").write_text("jobs:\n  a:\n    steps:\n      - run: python3 scripts/fix-it.py\n", encoding="utf-8")
    assert lane_verdict(tmp_path, RUNS_THE_SCRIPT) == ("reproduced", "")


def test_a_lane_issue_sealed_before_runs_step_keeps_the_reports_verdict(tmp_path):
    """Its PRD sealed the way as it was then: no `runs-step`, so its test that
    only greps keeps running as before."""
    test = tmp_path / "tests" / "repro" / "test_issue_9.py"
    test.parent.mkdir(parents=True)
    test.write_text(GREP_ONLY, encoding="utf-8")
    junit = tmp_path / "junit.xml"
    junit.write_text(FAILED_ASSERTION, encoding="utf-8")
    sealed = {k: v for k, v in the_workflow_way().items() if k != "runs-step"}
    sealed["test"] = "tests/repro/test_issue_9.py"
    done = subprocess.run([sys.executable, str(SCRIPT), "verdict", str(junit), "test_issue_9.py", ""],
                          env=dict(os.environ, SPEC=json.dumps(sealed)), capture_output=True, text=True, cwd=tmp_path)
    assert (done.stdout.strip(), done.stderr) == ("reproduced", "")


def test_a_workflow_test_that_runs_the_step_with_stubs_still_reproduces(tmp_path):
    assert the_workflow_way().get("runs-step") is True, "the workflow way does not ask its test to run the step"
    verdict, why = lane_verdict(tmp_path, STUBBED)
    assert (verdict, why) == ("reproduced", ""), f"a test that runs the step and fails an assertion did not confirm the bug ({verdict}: {why})"


MENTIONS_THE_SCRIPT = '''import subprocess


def test_the_script_is_named():
    assert subprocess.run(["bash", "-c", "echo scripts/fix-it.py"]).returncode == 1
'''

SHELL_RUNS_THE_SCRIPT = '''import subprocess


def test_the_script_runs():
    assert subprocess.run(["bash", "-e", "-c", "scripts/fix-it.py --go"]).returncode == 1
'''


def test_a_shell_string_that_only_names_the_script_runs_no_step(tmp_path):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "x.yml").write_text("jobs:\n  a:\n    steps:\n      - run: scripts/fix-it.py\n", encoding="utf-8")
    verdict, why = lane_verdict(tmp_path, MENTIONS_THE_SCRIPT)
    assert (verdict, "the test runs no step" in why) == ("broken", True), f"`echo scripts/fix-it.py` confirmed the bug ({verdict})"


def test_a_shell_string_whose_command_is_the_script_reproduces(tmp_path):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "x.yml").write_text("jobs:\n  a:\n    steps:\n      - run: scripts/fix-it.py\n", encoding="utf-8")
    assert lane_verdict(tmp_path, SHELL_RUNS_THE_SCRIPT) == ("reproduced", "")


def test_the_workflow_way_s_spec_builds_the_lane_issue():
    """The lane seals the resolved spec, `runs-step` with it, in the PRD
    (scripts/repro-lane.py prd), so a confirmed workflow bug opens its issue."""
    env = dict(os.environ, REPORT="9", RUN_URL="https://github.com/DiluxOne/x/actions/runs/1", SHA256="a" * 64,
               BASE="b" * 40, WAY="workflow", SPEC=json.dumps(the_workflow_way()), NOUN="workflow test")
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "repro-lane.py"), "prd"], env=env,
                          capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stderr
    assert '"runs-step":true' in json.loads(done.stdout)["body"]
