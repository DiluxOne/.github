"""A play has the time for the whole set (#844, review of #847).

Each play reviews every case of the set (at least 10 flag and 10 clean), one
after the other; 180 minutes left 9 a case. It gets the most a GitHub-hosted
job may run, less a margin: 350 of 360.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = yaml.safe_load((ROOT / ".github/workflows/review-eval.yml").read_text(encoding="utf-8"))


def test_a_play_may_run_350_minutes():
    play = WF["jobs"]["play"]
    assert play["runs-on"] == "ubuntu-latest"
    assert play["timeout-minutes"] == 350
