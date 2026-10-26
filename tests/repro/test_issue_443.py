"""#443: the php-unit sandbox gives a test no writable build/ folder.

scripts/repro-sandbox.sh `run` is driven in a temporary checkout with a
stand-in `docker` on PATH that records its arguments and prints PHPUnit's
green summary, so both runs happen (the test alone, then the rest of
tests/Unit).
"""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DOCKER = """#!/usr/bin/env bash
if [ "$1" = run ]; then
  echo CALL >> "$DOCKER_LOG"
  printf '%s\\n' "$@" >> "$DOCKER_LOG"
  echo 'OK (1 test, 1 assertion)'
fi
exit 0
"""


def test_the_sandbox_gives_both_runs_a_writable_empty_build_folder(tmp_path):
    checkout = tmp_path / "checkout"
    (checkout / "vendor" / "bin").mkdir(parents=True)
    (checkout / "vendor" / "bin" / "phpunit").write_text("#!/usr/bin/env php\n")
    (checkout / "tests" / "Unit").mkdir(parents=True)
    test = tmp_path / "Issue443Test.php"
    test.write_text("<?php\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "docker").write_text(DOCKER)
    (bindir / "docker").chmod(0o755)
    temp = tmp_path / "temp"
    temp.mkdir()
    log = tmp_path / "docker.log"
    log.write_text("")

    env = {k: v for k, v in os.environ.items() if k not in ("RUNNER_ENVIRONMENT", "GITHUB_OUTPUT", "REPRO_VENDOR")}
    env.update(PATH=f"{bindir}:{env['PATH']}", RUNNER_TEMP=str(temp), DOCKER_LOG=str(log))
    out = subprocess.run(["bash", str(ROOT / "scripts" / "repro-sandbox.sh"), "run", str(test), "Issue443Test.php"],
                         capture_output=True, text=True, cwd=checkout, env=env)

    runs = [call.split("\n")[1:] for call in log.read_text().split("CALL\n")[1:]]
    assert len(runs) == 2, out.stdout + out.stderr
    for args in runs:
        tmpfs = [args[i + 1] for i, a in enumerate(args[:-1]) if a == "--tmpfs"]
        assert any(t == "/app/build" or t.startswith("/app/build:") for t in tmpfs), args
    build = checkout / "build"
    assert build.is_dir() and list(build.iterdir()) == []
