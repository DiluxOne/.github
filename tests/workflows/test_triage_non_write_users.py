"""The triage answers anyone's issue (#658): claude-code-action refuses an
actor without write permission unless told otherwise, so every use that runs
on a stranger's text passes `allowed_non_write_users: '*'`, from a job whose
token cannot write contents and a model with no tool to act with."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ACTION = "anthropics/claude-code-action@"


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def step(job, step_id):
    return next(s for s in job["steps"] if s.get("id") == step_id)


def test_the_triage_allows_a_reader():
    wf = workflow("issue-triage.yml")
    triage = wf["jobs"]["triage"]
    # Anyone's issue reaches the job: its condition asks nothing of the author's role.
    assert "author_association" not in triage["if"] and "permission" not in triage["if"]
    classify = step(triage, "claude")
    assert classify["name"] == "Classify" and classify["uses"].startswith(ACTION)
    assert classify["with"]["allowed_non_write_users"] == "*", "a reader's issue would never reach the model"
    assert classify["with"]["github_token"] == "${{ github.token }}", "the action honours the list only with a token given"
    # Its verdict reaches the reply and the labels.
    act = next(s for s in triage["steps"] if s.get("name") == "Act (label, reply, lock)")
    assert "steps.claude.outputs.structured_output" in act["env"]["OUT"]
    assert "triage-act.sh" in act["run"]
