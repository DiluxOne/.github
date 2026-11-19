"""A test that cuts a workflow's text between two literals fails the
scripts job, naming the test (#845, scripts/literal-slices.py).

Each case runs the script as the scripts job does, on a test file written
in `tmp_path`, and reads its exit code and output."""
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "literal-slices.py"

SLICING = '''from pathlib import Path


def test_the_push_step_runs_after_the_review():
    text = Path(".github/workflows/autopilot.yml").read_text()
    step = text[text.index("- name: Push"):text.index("- name: Next")]
    assert "review" in step
'''

SPLITTING = '''def test_the_jobs():
    text = open("w.yml").read()
    assert "run:" in text.split("jobs:")[1]
'''

BEHAVING = '''import yaml


def test_the_push_step_is_named():
    steps = yaml.safe_load(open("w.yml"))["jobs"]["a"]["steps"]
    assert [s["name"] for s in steps] == ["Push"]
'''


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=ROOT, capture_output=True, text=True)


def test_c2_a_new_test_that_slices_between_literals_fails_naming_it(tmp_path):
    (tmp_path / "test_slicing.py").write_text(SLICING)
    got = run(tmp_path)
    assert got.returncode == 1, got.stdout + got.stderr
    assert "test_slicing.py:6 (test_the_push_step_runs_after_the_review)" in got.stdout


def test_c2_a_fixed_index_into_a_split_on_a_literal_fails_too(tmp_path):
    (tmp_path / "test_splitting.py").write_text(SPLITTING)
    got = run(tmp_path)
    assert got.returncode == 1, got.stdout + got.stderr
    assert "test_splitting.py:3 (test_the_jobs)" in got.stdout


def test_c2_a_test_that_reads_the_workflow_through_yaml_passes(tmp_path):
    (tmp_path / "test_behaving.py").write_text(BEHAVING)
    got = run(tmp_path)
    assert got.returncode == 0, got.stdout + got.stderr


def test_c2_the_scripts_job_runs_it_over_the_tests_and_its_self_test():
    job = yaml.safe_load((ROOT / ".github" / "workflows" / "pull-request.yml").read_text())["jobs"]["scripts"]
    runs = [step.get("run") for step in job["steps"]]
    assert "python3 scripts/literal-slices.py --test" in runs
    assert "python3 scripts/literal-slices.py tests/workflows tests/repro" in runs
    got = run("--test")
    assert got.returncode == 0, got.stdout + got.stderr


def test_c2_the_repository_passes_it_as_it_is():
    got = run("tests/workflows", "tests/repro")
    assert got.returncode == 0, got.stdout + got.stderr
