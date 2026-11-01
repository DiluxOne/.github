"""Screenshots of an autopilot pull request (#564 C4): taken when it is
marked ready, only for the autopilot's own pull request from a branch of the
same repository, never a fork's; its code runs without a secret. Here
through pull-request.yml's local call: autopilot.yml and org-pull-request.yml
call it once a release ships it (test_shared_calls_released.py)."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github/workflows"


def load(name):
    data = yaml.safe_load((WF / name).read_text(encoding="utf-8"))
    return data.get("on", data.get(True)), data["jobs"]


def test_the_pipeline_calls_it_on_ready_for_review_of_an_autopilot_pull_request_from_this_repository():
    for name, uses in (("pull-request.yml", "./.github/workflows/pr-screenshots.yml"),):
        on, jobs = load(name)
        assert "ready_for_review" in on["pull_request"]["types"] and "pull_request_target" not in on, name
        job = jobs["screenshots"]
        assert job["uses"] == uses
        cond = job["if"]
        for part in ("github.event.action == 'ready_for_review'", "contains(github.event.pull_request.labels.*.name, 'autopilot')",
                     "github.event.pull_request.user.login == (vars.DX_BOT_LOGIN || 'dilux-bot[bot]')",
                     "github.event.pull_request.head.repo.full_name == github.repository"):
            assert part in cond, (name, part)
        assert set(job["secrets"]) == {"DILUX_BOT_PRIVATE_KEY"}


def test_the_caller_grants_what_its_jobs_ask_for():
    # A nested job may not ask for more than its caller grants, or the
    # whole pipeline fails to start.
    _, jobs = load("pull-request.yml")
    _, called = load("pr-screenshots.yml")
    granted = jobs["screenshots"]["permissions"]
    for job in called.values():
        for scope, level in (job.get("permissions") or {}).items():
            assert granted.get(scope) in (level, "write"), (scope, level)
    _, waiting = load("waiting-update.yml")
    assert all(not job.get("permissions") for job in waiting.values()) and jobs["waiting"]["permissions"] == {}


def test_it_checks_the_pull_request_itself_and_runs_its_code_without_a_secret():
    on, jobs = load("pr-screenshots.yml")
    assert set(on) == {"workflow_call"}
    shots = jobs["shots"]
    assert shots["permissions"] == {"contents": "read", "pull-requests": "read"}
    steps = {s.get("id") or s.get("name") or s.get("uses"): s for s in shots["steps"]}
    pr = steps["pr"]["run"]
    for part in ('.head.repo.full_name == $repo', '.user.login == $bot', 'index("autopilot") != null', "(.draft | not)"):
        assert part in pr, part
    text = (WF / "pr-screenshots.yml").read_text(encoding="utf-8")
    shots_text = text[text.index("\n  shots:"):text.index("\n  publish:")]
    assert "secrets." not in shots_text and "create-github-app-token" not in shots_text, "the job that runs its code holds no key"
    for s in shots["steps"]:
        if s.get("uses", "").startswith("actions/checkout"):
            assert s["with"]["persist-credentials"] is False
    run = steps["run"]["run"]
    assert "screenshots.py config" in run and "playwright.dx-shots.config.ts" in run and "npx playwright test -c playwright.dx-shots.config.ts" in run
    assert "screenshots.py plan" in steps["plan"]["run"]
    publish = jobs["publish"]
    assert publish["needs"] == "shots" and "needs.shots.outputs.ok == 'true'" in publish["if"]
    token = next(s for s in publish["steps"] if s.get("id") == "bot")["with"]
    assert token["permission-contents"] == "write" and token["permission-pull-requests"] == "write"
    last = publish["steps"][-1]["run"]
    assert "screenshots.py publish" in last and "screenshots.py section" in last and "screenshots.py apply" in last and "gh pr edit" in last
    assert "${{" not in last


def test_the_template_has_the_section_it_fills():
    assert "## 📸 Screenshots" in (ROOT / "pull_request_template.md").read_text(encoding="utf-8")
