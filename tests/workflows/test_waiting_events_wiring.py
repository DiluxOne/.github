"""What waits on whom (#564 C3): issues.yml and pull-request.yml run the
update of the item that changed on their events; the update writes its
board and mentions once; the view is rewritten, by person, as events come."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github/workflows"


def load(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # PyYAML reads `on:` as True.
    return data.get("on", data.get(True)), data["jobs"]


def test_issues_yml_and_its_template_run_the_update_on_every_item_event():
    for path in (WF / "issues.yml", ROOT / "workflow-templates/issues.yml"):
        on, jobs = load(path)
        assert {"issues", "issue_comment", "pull_request_target"} <= set(on), path
        job = jobs["waiting"]
        assert job["uses"] == "DiluxOne/.github/.github/workflows/waiting-update.yml@v7", path
        assert job["if"] == "github.event_name != 'schedule'" and job["permissions"] == {}
        assert job["with"]["number"] == "${{ format('{0}', github.event.issue.number || github.event.pull_request.number) }}"
        assert set(job["secrets"]) == {"DILUX_BOT_PRIVATE_KEY"}, "only the bot's key, never every secret"


def test_the_pull_request_pipelines_run_it_when_one_is_marked_ready():
    for name, uses in (("pull-request.yml", "./.github/workflows/waiting-update.yml"),
                       ("org-pull-request.yml", "DiluxOne/.github/.github/workflows/waiting-update.yml@v7")):
        on, jobs = load(WF / name)
        assert "ready_for_review" in on["pull_request"]["types"], name
        job = jobs["waiting"]
        assert job["uses"] == uses and job["permissions"] == {}
        assert "github.event.action == 'ready_for_review'" in job["if"]
        assert "github.event.pull_request.head.repo.full_name == github.repository" in job["if"], "never a fork's, with the key"


def test_the_update_writes_the_board_and_starts_the_view():
    on, jobs = load(WF / "waiting-update.yml")
    assert set(on) == {"workflow_call"}
    job = jobs["update"]
    assert job["concurrency"]["cancel-in-progress"] is True and "inputs.number" in job["concurrency"]["group"]
    steps = {s.get("id") or s.get("name"): s for s in job["steps"]}
    item = steps["item"]
    assert "python3 .dx-central/scripts/waiting.py update" in item["run"]
    assert item["env"]["SENDER"] == "${{ github.event.sender.login }}" and item["env"]["NUMBER"] == "${{ inputs.number }}"
    assert "${{" not in item["run"]
    assert steps["bot"]["with"]["permission-issues"] == "write" and "permission-contents" not in steps["bot"]["with"]
    view = steps["view"]
    assert view["with"]["repositories"] == ".github" and view["with"]["permission-actions"] == "write" and len([k for k in view["with"] if k.startswith("permission-")]) == 1
    rewrite = next(s for s in job["steps"] if s.get("name") == "Rewrite the view")
    assert "gh workflow run waiting-digest.yml" in rewrite["run"] and rewrite.get("continue-on-error") is True
    # Its own comments start nothing again.
    assert "github.event.comment.user.type == 'Bot'" in job["if"]


def test_the_view_runs_on_demand_and_the_newest_wins():
    on, jobs = load(WF / "waiting-digest.yml")
    assert "workflow_dispatch" in on and "schedule" in on
    data = yaml.safe_load((WF / "waiting-digest.yml").read_text(encoding="utf-8"))
    assert data["concurrency"]["cancel-in-progress"] is True
    run = jobs["digest"]["steps"][-1]
    assert "python3 scripts/waiting.py" in run["run"] and run["env"].get("MAINTAINER")
