"""#487: the "what others said" summary can land on a pull request that never asked.

The pull request that asked is the one whose comments hold the autopilot's
question marker (`autopilot.py`, ASK); the last pull request that closes the
issue is only a guess when two of them link it.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def step(name):
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "review-reply.yml").read_text(encoding="utf-8"))
    return next(s for s in wf["jobs"]["others"]["steps"] if s.get("name") == name)


def test_the_summary_goes_to_the_pull_request_that_asked_not_the_last_one_closing_the_issue():
    run = step("What others said since the question")["run"]

    assert "dx-autopilot-ask" in run, "the pull request is not chosen by the question's marker"
