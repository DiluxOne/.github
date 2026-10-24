"""#421: run-ref's cleanup fails the step after a passing verdict when its
tree holds a file the runner's user cannot remove. Written from the report as
the reproduction's writer would (#376).
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PASS = '<testsuites><testsuite><testcase name="x" classname="issue-1.spec.ts"/></testsuite></testsuites>'
TEST = "tests/repro/issue-1.spec.ts"


@pytest.mark.skipif(os.geteuid() == 0, reason="root can remove anything: the bug cannot show")
def test_run_ref_ends_passed_with_exit_0_when_its_tree_holds_a_file_it_cannot_remove(tmp_path):
    repo, temp = tmp_path / "repo", tmp_path / "temp"
    (repo / "tests" / "repro").mkdir(parents=True)
    temp.mkdir()
    (repo / TEST).write_text("x\n")
    git = ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", "."], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(git + ["commit", "-qm", "test: base"], cwd=repo, check=True)
    # What the confined run's containers leave behind: a file in a folder the
    # runner's user may not write to.
    run = f"mkdir -p build/locked && touch build/locked/f && chmod 555 build/locked && printf %s '{PASS}' > build/j.xml"
    spec = json.dumps({"run": run, "junit": "build/j.xml", "minutes": 1, "test": TEST})
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "RUNNER_TEMP": str(temp),
           "DX_REPRO_UNCONFINED": "1", "SPEC": spec, "GITHUB_OUTPUT": ""}
    try:
        out = subprocess.run(["bash", str(ROOT / "scripts" / "repro-run.sh"), "run-ref", "HEAD", TEST],
                             cwd=repo, env=env, capture_output=True, text=True)
    finally:
        subprocess.run(["chmod", "-R", "u+rwX", str(temp)], check=False)
    outcome = [line for line in out.stdout.splitlines() if line.startswith("outcome=")][-1:]
    assert (outcome, out.returncode) == (["outcome=passed"], 0), out.stderr
