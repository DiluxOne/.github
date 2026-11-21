"""#856 C1: a run that apply-and-end's "do not build on" refusal ends is free.
The refusal is the engine's own (the sweep moved the branch while the run was
on it), never the agent's fault: `applied` says so in its `refused` output,
the end rule passes it as REFUSED, and `autopilot.py end` rewrites the run's
entry on the pull request's board as a free one, so it does not count
towards the cap. The verdict still stops the run: free, but no continue."""
import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def autopilot():
    spec = importlib.util.spec_from_file_location("autopilot_refused_free", ROOT / "scripts/autopilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def apply_steps():
    jobs = yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))["jobs"]
    return {s.get("id"): s for s in jobs["apply"]["steps"] if s.get("id")}


def test_the_refusal_says_so_in_its_output():
    run = apply_steps()["applied"]["run"]
    refusal = next(line for line in run.splitlines() if "do not build on" in line)
    # Written before the exit, on the same line, so the end rule reads it.
    assert 'echo "refused=diverged" >> "$GITHUB_OUTPUT"' in refusal
    assert refusal.index("refused=diverged") < refusal.index("exit 1")


def test_the_end_rule_reads_it():
    env = apply_steps()["end"]["env"]
    assert env.get("REFUSED") == "${{ steps.applied.outputs.refused }}"


def test_a_refused_run_is_free():
    ap = autopilot()
    free_end = getattr(ap, "free_end", None)
    assert callable(free_end), "autopilot.py has no free_end"
    assert free_end("continue", False, False, False, False, True) is True
    assert free_end("start", False, False, False, False, True) is True
    # As a lost runner or a held-back `make pre-pr` already were.
    assert free_end("continue", False, False, True, False, False) is True
    assert free_end("continue", False, False, False, True, False) is True
    # Not refused, not lost, not held back: it counts.
    assert free_end("continue", False, False, False, False, False) is False
    # A fix round has no run on the board; a stop or a question is the agent's own end.
    assert free_end("fix", False, False, False, False, True) is False
    assert free_end("continue", True, False, False, False, True) is False
    assert free_end("continue", False, True, False, False, True) is False


def test_its_entry_on_the_board_no_longer_counts():
    ap = autopilot()
    freed_runs = getattr(ap, "freed_runs", None)
    assert callable(freed_runs), "autopilot.py has no freed_runs"
    st = {"runs": [{"n": 1, "free": False}, {"n": 2, "free": False}, {"n": 3, "free": False}]}
    assert ap.run_numbers(st)[1] == 3
    runs = freed_runs(st, 3, ap.free_end("continue", False, False, False, False, True))
    assert runs == [{"n": 1, "free": False}, {"n": 2, "free": False}, {"n": 3, "free": True}]
    assert ap.run_numbers(dict(st, runs=runs))[1] == 2
    # Nothing to rewrite: not free, already free, or no entry of that number.
    assert freed_runs(st, 3, False) is None
    assert freed_runs({"runs": runs}, 3, True) is None
    assert freed_runs(st, 4, True) is None


def test_the_end_uses_it():
    src = (ROOT / "scripts/autopilot.py").read_text(encoding="utf-8")
    assert 'os.environ.get("REFUSED")' in src
    assert "free_end(mode, stopped, asked, lost, held_back, refused)" in src


def test_a_refused_run_still_stops():
    ap = autopilot()
    # A draft with criteria left, refused: not lost, so no free continue.
    assert ap.end_verdict("continue", "8", True, False, 1, 3, False, 2, 5) == "silent"
