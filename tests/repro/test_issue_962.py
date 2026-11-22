"""#962: `scripts/gh-wait.sh --test` never writes the rate-limit note of the
job it runs in. `gh-wait.sh --install` sets DX_RATE_NOTE and
DX_RATE_DEADLINE in every autopilot job, and `make pre-pr` runs the
self-test there: a case that gives up wrote that note, and the job believed
GitHub's API rate limit spent (#956 stood still until a fake reset in 2027)."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts" / "gh-wait.sh"


def test_c1_the_self_test_leaves_the_jobs_note_alone(tmp_path):
    note = tmp_path / "rate-limited"
    env = dict(os.environ, DX_RATE_NOTE=str(note), DX_RATE_DEADLINE="4102444800")
    out = subprocess.run(["bash", str(WRAPPER), "--test"], capture_output=True, text=True, env=env, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    assert not note.exists(), f"the self-test wrote the job's note: {note.read_text()!r}"


def test_c2_the_954_repro_leaves_the_jobs_note_alone(tmp_path):
    note = tmp_path / "rate-limited"
    env = dict(os.environ, DX_RATE_NOTE=str(note))
    out = subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", str(ROOT / "tests" / "repro" / "test_issue_954.py")],
                         capture_output=True, text=True, env=env, timeout=300, cwd=ROOT)
    assert out.returncode == 0, out.stdout + out.stderr
    assert not note.exists(), f"the #954 repro wrote the job's note: {note.read_text()!r}"
