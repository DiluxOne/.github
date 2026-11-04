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


def uses_of_the_action(name):
    wf = workflow(name)
    for job_name, job in wf["jobs"].items():
        permissions = job.get("permissions", wf.get("permissions"))
        for s in job.get("steps") or []:
            if str(s.get("uses", "")).startswith(ACTION):
                yield job_name, permissions, s


def test_every_strangers_use_allows_non_write_users_with_no_write_token():
    # Every use in these two workflows reads a stranger's text: the issue, a
    # test written from it, or that test's output.
    seen = 0
    for name in ("issue-triage.yml", "issue-repro.yml"):
        for job_name, permissions, s in uses_of_the_action(name):
            seen += 1
            where = f"{name} {job_name} {s.get('name')}"
            assert s["with"].get("allowed_non_write_users") == "*", f"{where}: a stranger's issue never reaches the model"
            assert s["with"].get("github_token") == "${{ github.token }}", where
            assert isinstance(permissions, dict), f"{where}: the job's token must name its permissions"
            assert permissions.get("contents") in ("read", None), f"{where}: its token can write contents"
            assert "write" not in {permissions.get(k) for k in ("pull-requests", "actions", "workflows")}, where
            tools = s["with"]["claude_args"].split('--allowedTools "', 1)[1].split('"', 1)[0].split(",")
            assert all(t in ("Read", "Glob", "Grep") or t.startswith(("Write(", "Edit(")) for t in tools), f"{where}: {tools}"
        # Each says why it is safe, in a comment just above it.
        lines = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if line.strip().startswith("allowed_non_write_users:"):
                assert lines[i - 1].strip().startswith("#"), f"{name}:{i + 1}: no comment says why it is safe"
    assert seen == 6, "a new use of the action here: check its token and its tools, then count it"
