"""A test that cuts a workflow's text between two literals fails the
scripts job, naming the test (#845, scripts/literal-slices.py).

Each case runs the script as the scripts job does, on a test file written
in `tmp_path`, and reads its exit code and output."""
import os
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


def load():
    import importlib.util
    spec = importlib.util.spec_from_file_location("literal_slices", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_c2_a_slicing_test_appended_to_a_listed_file_fails_naming_it(tmp_path):
    """KNOWN holds each file's number of slices, not the file as a whole:
    a new slicing test in a listed file fails, and one fixed asks for the
    count to come down."""
    module = load()
    listed = tmp_path / "test_listed.py"
    listed.write_text(SLICING)
    rel = os.path.relpath(listed, ROOT)
    assert module.check([tmp_path], {rel: 1}) == (0, [])
    listed.write_text(SLICING + "\n\n" + SPLITTING.replace("def test_the_jobs", "def test_the_new_one"))
    code, lines = module.check([tmp_path], {rel: 1})
    assert code == 1
    assert any(f"{rel}:" in line and "(test_the_new_one)" in line for line in lines), lines
    code, lines = module.check([tmp_path], {rel: 3})
    assert code == 1
    assert any("lower the count" in line for line in lines), lines


def test_c2_every_listed_file_carries_its_count_today():
    module = load()
    assert isinstance(module.KNOWN, dict)
    counts = slices_by_file("tests/workflows", "tests/repro")
    assert module.KNOWN == counts


def test_c2_a_path_that_does_not_exist_fails_instead_of_scanning_nothing(tmp_path):
    got = run(tmp_path / "gone")
    assert got.returncode != 0
    assert "gone" in got.stdout + got.stderr


def test_the_repro_guide_sends_no_agent_to_a_helper_the_runs_step_gate_rejects():
    """A way with `runs-step` accepts a test only by the process call in
    its own file (scripts/repro-ways.py `runs_step`): a guide that offers
    tests/workflows/steps.py makes every reproduction that follows it
    "the test runs no step". The guide still forbids slicing the text."""
    ways = yaml.safe_load((ROOT / ".github" / "review-policy.yml").read_text())["repro"]["ways"]
    for name, way in ways.items():
        if not way.get("runs-step"):
            continue
        guide = way["guide"]
        assert "steps.py" not in guide, name
        assert "literal-slices.py" in guide, name
        assert "subprocess" in guide, name


# The 23 files #846 left in KNOWN (#873).
CONVERTED = [f"tests/repro/test_issue_{n}.py" for n in (549, 556, 575, 577, 696, 774)] + [
    f"tests/workflows/test_{name}.py" for name in (
        "autopilot_cancelled_review", "autopilot_commit_cadence", "autopilot_pre_pr", "autopilot_rounds",
        "autopilot_sweep_draft", "claimed_bug_wiring", "configuration_doc", "credits_wiring", "flow_label_words",
        "hint_without_needs_human", "pr_screenshots_wiring", "queue_drop_fix", "release_bug_reproduced",
        "release_lane_wiring", "required_checks", "triage_non_write_users", "who_decides_wiring")]


def test_c1_known_is_empty_and_the_tests_pass_it():
    assert load().KNOWN == {}
    got = run("tests/workflows", "tests/repro")
    assert got.returncode == 0, got.stdout + got.stderr
    assert "(0 files still listed in KNOWN)" in got.stdout

