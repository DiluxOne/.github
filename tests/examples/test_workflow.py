"""How a test of a workflow's step is written here (#376, #841): the house
style the reproduction's writer reads (.github/review-policy.yml,
`repro.ways.workflow`).

It reads the workflow's file as YAML, finds the step by its name, and RUNS
its `run:` script with `bash -c`, with stubs on PATH for what it calls (a
fake `gh` that logs its arguments and prints what the case needs), and
asserts on what the step did: its exit code, its output, the stub's log. A
test that only asserts on the file's text runs no step and reproduces
nothing (scripts/repro-ways.py, `runs-step`).
"""
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def step(workflow, job, name):
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8"))
    return next(s for s in wf["jobs"][job]["steps"] if s.get("name") == name or s.get("id") == name)


def run_step(tmp_path, script, private):
    """The step's script, run with a fake `gh` that logs its arguments and
    says whether the repository is private."""
    stub = tmp_path / "gh"
    stub.write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path}/gh.log"\necho {private}\n', encoding="utf-8")
    stub.chmod(0o755)
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin", "GITHUB_REPOSITORY": "Acme/widget", "GITHUB_OUTPUT": str(tmp_path / "out")}
    return subprocess.run(["bash", "-c", script], env=env, cwd=ROOT, capture_output=True, text=True)


def test_the_security_fix_refuses_to_run_from_a_public_repository(tmp_path):
    script = step("security-fix.yml", "plan", "Only from a private repository")["run"]
    done = run_step(tmp_path, script, "false")
    assert done.returncode == 1
    assert "runs only from a private repository" in done.stdout
    assert "api repos/Acme/widget --jq .private" in (tmp_path / "gh.log").read_text(encoding="utf-8")


def test_the_security_fix_goes_on_from_a_private_one(tmp_path):
    script = step("security-fix.yml", "plan", "Only from a private repository")["run"]
    assert run_step(tmp_path, script, "true").returncode == 0
