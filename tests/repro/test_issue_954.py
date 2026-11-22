"""#954: `scripts/gh-wait.sh --test` gives the same answer however fast or
slow the runner is. A `date` on PATH that moves one second on every
`date +%s` makes each case meet the second boundary that failed it in CI:
its first case's reset, one second ahead, has already passed when the
wrapper reads it. With every case deterministic, it passes run after run
(C2)."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts" / "gh-wait.sh"

TICKING_DATE = r"""#!/usr/bin/env bash
# `date +%s` moves one second on every call; any other form is the real date.
if [ "$*" = "+%s" ]; then
  n=$(cat "$TICK" 2>/dev/null || echo 1800000000); n=$((n + 1)); echo "$n" > "$TICK"; echo "$n"; exit 0
fi
exec "$REAL_DATE" "$@"
"""


def test_c1_the_self_test_passes_when_the_clock_ticks_past_the_reset(tmp_path):
    real = subprocess.run(["bash", "-c", "command -v date"], capture_output=True, text=True).stdout.strip()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "date"
    fake.write_text(TICKING_DATE)
    fake.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", REAL_DATE=real, TICK=str(tmp_path / "tick"))
    out = subprocess.run(["bash", str(WRAPPER), "--test"], capture_output=True, text=True, env=env, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr

