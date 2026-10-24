"""#409: run-ref leaves out .dx-central, which a way's setup reads, so the
verdict is `limit`. Written from the report as the reproduction's writer would
(#376).
"""
import json
import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PASS = '<testsuites><testsuite><testcase name="x" classname="issue-1.spec.ts"/></testsuite></testsuites>'


def git(repo, *args):
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                    "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True, capture_output=True)


def test_run_ref_gives_a_setup_the_working_trees_dx_central(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tests" / "repro").mkdir(parents=True)
    (repo / "tests" / "repro" / "issue-1.spec.ts").write_text("x\n")
    git(repo, "init", "-q", ".")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "test: base")
    # As in the lane: .dx-central/ is in the working tree, kept out of git.
    (repo / ".dx-central").mkdir()
    (repo / ".dx-central" / "playwright.dx-repro.config.ts").write_text("config\n")
    with open(repo / ".git" / "info" / "exclude", "a") as f:
        f.write(".dx-central/\n")
    spec = {
        "setup": ["cp .dx-central/playwright.dx-repro.config.ts playwright.dx-repro.config.ts"],
        "run": "printf %s " + shlex.quote(PASS) + " > build/j.xml",
        "junit": "build/j.xml",
        "minutes": 1,
        "test": "tests/repro/issue-1.spec.ts",
    }
    env = {k: v for k, v in os.environ.items() if k not in ("RUNNER_ENVIRONMENT", "GITHUB_OUTPUT")}
    env.update(DX_REPRO_UNCONFINED="1", REPRO_SPEC=json.dumps(spec), TMPDIR=str(tmp_path))
    out = subprocess.run(["bash", str(ROOT / "scripts" / "repro-run.sh"), "run-ref", "HEAD", "tests/repro/issue-1.spec.ts"],
                         cwd=repo, env=env, capture_output=True, text=True)
    outcomes = [line for line in out.stdout.splitlines() if line.startswith("outcome=")]
    assert outcomes[-1:] == ["outcome=passed"], out.stdout + out.stderr
