"""A test that cuts a workflow's text between two literals fails the
scripts job, naming the test (#845, scripts/literal-slices.py).

Each case runs the script as the scripts job does, on a test file written
in `tmp_path`, and reads its exit code and output."""
import re
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


def slices_by_file(*args):
    """{file: number of literal slices} under ARGS, listed in KNOWN or not."""
    got = run("--all", *args)
    assert got.returncode in (0, 1), got.stdout + got.stderr
    counts = {}
    for path in re.findall(r"^::error::([^:]+):\d+ \(", got.stdout, re.M):
        counts[path] = counts.get(path, 0) + 1
    return counts


def test_c3_the_worst_wording_tests_of_tests_workflows_slice_no_more():
    counts = slices_by_file("tests/workflows")
    assert counts, "--all reports no slice: it does not read tests/workflows"
    worst = {f: n for f, n in counts.items() if n > 1}
    assert worst == {}, f"these still cut the workflow's text more than once: {worst}"
    for name in ("maintainer_bug_wiring", "policy_on_receipts", "autopilot_main_merge", "settled_finding_rerun",
                 "conventions_fix_round", "confirmed_bug_no_acceptance"):
        assert f"tests/workflows/test_{name}.py" not in counts


def test_c3_the_files_left_are_on_the_list_that_only_shrinks():
    left = set(slices_by_file("tests/workflows"))
    got = run("tests/workflows")
    assert got.returncode == 0, got.stdout
    assert f"{len(left) + len(slices_by_file('tests/repro'))} files still listed" in got.stdout
