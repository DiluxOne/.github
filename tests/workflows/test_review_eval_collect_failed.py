"""A failed collect fails the Review evaluation check (#844, review of #847).

When `mode: collect` fails, the plays are skipped; the score job (the check
named "Review evaluation") must still run and fail, never stay skipped, which
can read as passing.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = yaml.safe_load((ROOT / ".github/workflows/review-eval.yml").read_text(encoding="utf-8"))


def test_the_score_job_runs_when_collect_failed():
    cond = WF["jobs"]["score"]["if"]
    assert "always()" in cond
    assert "needs.collect.result == 'failure'" in cond


def test_its_first_step_fails_on_a_failed_collect():
    first = WF["jobs"]["score"]["steps"][0]
    assert first["if"] == "needs.collect.result == 'failure'"
    assert "exit 1" in first["run"]
