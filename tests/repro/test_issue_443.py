"""#443: the php-unit sandbox gives a test a writable, empty build/ (a tmpfs over
/app/build, its mount point made outside the container) in both of its runs.
Written from the report as the reproduction's writer would (#376): a stand-in
`docker` on the PATH records its arguments, so no Docker is needed.
"""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FAKE_DOCKER = """#!/usr/bin/env bash
{ printf '%s\\n' "$@"; echo '--END--'; } >> "$FAKE_DOCKER_LOG"
"""


def test_the_sandbox_gives_both_runs_a_writable_build_folder_over_the_read_only_checkout(tmp_path):
    checkout = tmp_path / "checkout"
    (checkout / "vendor" / "bin").mkdir(parents=True)
    (checkout / "vendor" / "bin" / "phpunit").write_text("")
    (checkout / "tests" / "Unit").mkdir(parents=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "docker").write_text(FAKE_DOCKER)
    (bindir / "docker").chmod(0o755)
    temp = tmp_path / "temp"
    temp.mkdir()
    test_file = tmp_path / "Issue443Test.php"
    test_file.write_text("<?php\n")
    log = tmp_path / "docker.log"

    env = {
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "RUNNER_TEMP": str(temp),
        "FAKE_DOCKER_LOG": str(log),
    }
    subprocess.run(["bash", str(ROOT / "scripts" / "repro-sandbox.sh"), "run", str(test_file), "Issue443Test.php"],
                   cwd=checkout, env=env, capture_output=True, text=True)

    calls = [c.split("\n")[:-1] for c in log.read_text().split("--END--\n") if c.strip()]
    runs = [c for c in calls if c and c[0] == "run"]
    assert len(runs) == 2
    for args in runs:
        tmpfs = [args[i + 1] for i, a in enumerate(args[:-1]) if a == "--tmpfs"]
        assert any(t == "/app/build" or t.startswith("/app/build:") for t in tmpfs), tmpfs
    assert (checkout / "build").is_dir()
