"""The autopilot's fix rounds (#507): the policy allows five, and the gate in
the "may" step runs rounds 4 and 5 and hands round 6 to a person. Runs the
step's own fix-round gate with python3 and gh stood in, the policy's number
read from policy/autonomy.yml."""
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def rounds():
    return yaml.safe_load((ROOT / "policy/autonomy.yml").read_text(encoding="utf-8"))["autopilot-rounds"]


def fix_gate_script():
    jobs = yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))["jobs"]
    run = next(s["run"] for s in jobs["prep"]["steps"] if s.get("id") == "may")
    start = run.index('if [ "$MODE" = fix ]; then')
    return "set -euo pipefail\n" + run[start:]


def run(tmp_path, round_):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    log.write_text("")
    policy = json.dumps({"autopilot-rounds": rounds()})
    (bin_dir / "python3").write_text(
        "#!/bin/bash\n"
        f'echo "python3 $*" >> "{log}"\n'
        f"case \"$2\" in policy) echo '{policy}' ;; esac\n")
    (bin_dir / "gh").write_text(f'#!/bin/bash\necho "gh $*" >> "{log}"\nexit 0\n')
    for f in ("python3", "gh"):
        (bin_dir / f).chmod(0o755)
    out = tmp_path / "out"
    out.write_text("")
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", GITHUB_OUTPUT=str(out),
               GITHUB_REPOSITORY="o/r", MODE="fix", ISSUE="7", PR="9", ROUND=str(round_))
    done = subprocess.run(["bash", "-c", fix_gate_script()], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return log.read_text(), out.read_text()


def test_the_policy_allows_five_rounds():
    assert rounds() == 5


@pytest.mark.parametrize("round_", [4, 5])
def test_a_fourth_and_a_fifth_round_run(tmp_path, round_):
    calls, out = run(tmp_path, round_)
    assert "autonomy.py policy" in calls
    assert out == "go=true\n"
    assert "needs-human" not in calls


def test_no_sixth_round(tmp_path):
    calls, out = run(tmp_path, 6)
    assert out == "go=false\n"
    assert "gh pr edit 9 --repo o/r --add-label needs-human" in calls
    assert "spent its 5 rounds" in calls
