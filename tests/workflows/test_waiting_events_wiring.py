"""What waits on whom (C3, #564): issues.yml (here and in the template every
repository copies) and the pull request pipelines run the update on their
events, so the view and the item's board are current within minutes; the
daily run stays as a sweep."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github/workflows"


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def events(doc):
    # PyYAML reads the key `on` as True.
    return doc.get("on") or doc.get(True)


def test_issues_yml_runs_the_update_on_every_issue_and_pull_request_event():
    for path, uses in ((WF / "issues.yml", "./.github/workflows/waiting-update.yml"),
                       (ROOT / "workflow-templates/issues.yml", "DiluxOne/.github/.github/workflows/waiting-update.yml@v7")):
        doc = load(path)
        on = events(doc)
        assert {"issues", "issue_comment", "pull_request_target"} <= set(on), path
        job = doc["jobs"]["waiting"]
        assert job["uses"] == uses and job["if"] == "github.event_name != 'schedule'"
        assert job["permissions"] == {"contents": "read"}
        assert job["secrets"] == {"DILUX_BOT_PRIVATE_KEY": "${{ secrets.DILUX_BOT_PRIVATE_KEY }}"}


def test_the_pull_request_pipelines_run_it_after_the_review_for_their_own_branches():
    for name, uses in (("pull-request.yml", "./.github/workflows/waiting-update.yml"),
                       ("org-pull-request.yml", "DiluxOne/.github/.github/workflows/waiting-update.yml@v7")):
        job = load(WF / name)["jobs"]["waiting"]
        assert job["uses"] == uses and job["needs"] == "review", name
        assert job["if"].startswith("always() && github.event_name == 'pull_request'")
        assert "github.event.pull_request.head.repo.full_name == github.repository" in job["if"], "a fork's has no secrets: issues.yml covers it"


def test_the_update_reads_the_item_then_rewrites_the_view_and_never_runs_a_pull_requests_code():
    doc = load(WF / "waiting-update.yml")
    assert set(events(doc)) == {"workflow_call"}
    update, view = doc["jobs"]["update"], doc["jobs"]["view"]
    cond = " ".join(update["if"].split())
    for event in ("issues", "issue_comment", "pull_request_target"):
        assert f"github.event_name == '{event}'" in cond
    assert "github.event.pull_request.head.repo.full_name == github.repository" in cond
    assert "github.event.comment.user.type == 'Bot'" in cond, "the bot's own comments (the board, the mention) start nothing"
    assert "'run:'" in cond, "nor do the bot's run: issues, the view among them"
    assert update["concurrency"]["cancel-in-progress"] is False, "queued, so a mention is never posted twice"
    assert view["needs"] == "update" and view["concurrency"]["cancel-in-progress"] is True
    runs = [s.get("run", "") for s in update["steps"]]
    assert any("waiting.py update" in r for r in runs)
    assert any("waiting.py publish" in s.get("run", "") for s in view["steps"])
    text = (WF / "waiting-update.yml").read_text(encoding="utf-8")
    assert "actions/checkout" not in text, "only DiluxOne/.github's scripts, fetched by git"
    # The event's text never reaches a script but through env:.
    for job in (update, view):
        for step in job["steps"]:
            assert "github.event" not in step.get("run", "")


def test_the_daily_digest_is_the_sweep_of_the_same_view():
    steps = load(WF / "waiting-digest.yml")["jobs"]["digest"]["steps"]
    assert any(s.get("run") == "python3 scripts/waiting.py publish" for s in steps)


def test_the_board_is_written_with_a_token_for_the_items_repository_that_may_write_issues():
    # #619: an owner-wide token, minted for the whole installation, had its
    # board comment answered with HTTP 403.
    update = load(WF / "waiting-update.yml")["jobs"]["update"]
    assert update["permissions"] == {}, "the callers grant contents: read, no more"
    token = next(s for s in update["steps"] if s.get("id") == "bot")
    assert token["uses"].startswith("actions/create-github-app-token@")
    got = token["with"]
    assert "owner" not in got, "never a token for every repository of the installation"
    assert got["repositories"] == "${{ github.event.repository.name }}"
    asked = {k[len("permission-"):]: v for k, v in got.items() if k.startswith("permission-")}
    assert asked == {"issues": "write", "pull-requests": "read", "checks": "read", "contents": "read", "metadata": "read"}
    board = next(s for s in update["steps"] if "waiting.py update" in s.get("run", ""))
    assert board["env"]["GH_TOKEN"] == "${{ steps.bot.outputs.token }}"
