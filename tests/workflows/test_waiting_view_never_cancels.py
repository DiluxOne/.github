"""A superseded "What waits" view never cancels the pull request's required
run (#1004): the view leaves the caller's run, which keeps no concurrency
group shared between items, and asks waiting-digest.yml for the rewrite."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github/workflows"


def load(name):
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def jobs():
    return load("waiting-update.yml")["jobs"]


def test_c1_no_job_shares_a_group_between_items_nor_cancels_in_progress():
    item = "${{ github.event.issue.number || github.event.pull_request.number }}"
    for name, job in jobs().items():
        conc = job.get("concurrency")
        if conc is None:
            continue
        group = conc["group"] if isinstance(conc, dict) else conc
        assert item in group, f"{name}: its group {group!r} is shared between items, and GitHub cancels the runs a burst queues there"
        assert not (isinstance(conc, dict) and conc.get("cancel-in-progress") is True), f"{name}: cancels the run in progress"


def test_c1_the_step_that_asks_for_the_view_continues_on_error():
    view = jobs()["view"]
    assert "concurrency" not in view
    ask = [s for s in view["steps"] if "waiting-digest.yml" in s.get("run", "")]
    assert ask, "a step asks waiting-digest.yml for the view"
    for step in ask:
        assert step.get("continue-on-error") is True, "a failed request leaves a warning, never a red required run"


def test_c1_without_the_key_the_request_does_nothing_and_the_run_passes(tmp_path):
    # A run with no secrets (a fork's, or a repository without the App's
    # key) mints no token, and the request warns and ends with success.
    view = jobs()["view"]
    assert (view.get("env") or {}).get("HAS_KEY") == "${{ secrets.DILUX_BOT_PRIVATE_KEY != '' }}"
    token = next(s for s in view["steps"] if s.get("id") == "bot")
    assert token["if"] == "env.HAS_KEY == 'true'" and token.get("continue-on-error") is True
    ask = next(s for s in view["steps"] if "waiting-digest.yml" in s.get("run", ""))
    assert ask["env"]["GH_TOKEN"] == "${{ steps.bot.outputs.token }}"
    gh = tmp_path / "gh"
    gh.write_text("#!/bin/sh\necho called > \"$0.log\"\nexit 1\n")
    gh.chmod(0o755)
    import os
    import subprocess
    env = dict(os.environ, GH_TOKEN="", CENTRAL="DiluxOne/.github", PATH=f"{tmp_path}:{os.environ['PATH']}")
    out = subprocess.run(["bash", "-e", "-c", ask["run"]], env=env, capture_output=True, text=True)
    assert out.returncode == 0 and "::warning::" in out.stdout
    assert not (tmp_path / "gh.log").exists(), "no request without a token"
    # And a request GitHub refuses is a warning, never a failure.
    out = subprocess.run(["bash", "-e", "-c", ask["run"]], env=dict(env, GH_TOKEN="ghs_test"), capture_output=True, text=True)
    assert out.returncode == 0 and "::warning::" in out.stdout and (tmp_path / "gh.log").exists()


def test_c2_the_view_dispatches_the_digest_on_main_with_a_token_for_github_alone():
    view = jobs()["view"]
    assert view["needs"] == "update", "after the board's update, which the view lists"
    token = next(s for s in view["steps"] if s.get("id") == "bot")
    got = token["with"]
    assert "owner" not in got and got["repositories"] == ".github"
    asked = {k[len("permission-"):]: v for k, v in got.items() if k.startswith("permission-")}
    assert asked == {"actions": "write", "metadata": "read"}
    ask = next(s for s in view["steps"] if "waiting-digest.yml" in s.get("run", ""))
    assert "repos/$CENTRAL/actions/workflows/waiting-digest.yml/dispatches" in ask["run"] and "-f ref=main" in ask["run"]
    assert ask["env"]["CENTRAL"] == "${{ github.repository_owner }}/.github"


def test_c2_the_digest_runs_after_the_last_request():
    doc = load("waiting-digest.yml")
    on = doc.get("on") or doc.get(True)
    assert "workflow_dispatch" in on
    # One running and one pending: the newest request replaces the older
    # ones, so a run starts after the last event of a burst.
    assert doc["concurrency"] == {"group": "waiting-digest", "cancel-in-progress": True}
    steps = doc["jobs"]["digest"]["steps"]
    assert any(s.get("run") == "python3 scripts/waiting.py publish" for s in steps)


def test_c2_the_contract_pins_the_views_token():
    import importlib.util
    spec = importlib.util.spec_from_file_location("caller_contract", ROOT / "scripts/caller-contract.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.TOKENS["waiting-update.yml"].get("view") == {"repositories": ".github", "permissions": {"actions": "write", "metadata": "read"}}
    assert mod.tokens({"waiting-update.yml": load("waiting-update.yml")}) == []


def test_c3_a_failing_check_of_its_own_still_fails_the_required_run():
    for name in ("org-pull-request.yml", "pull-request.yml"):
        job = load(name)["jobs"]["waiting"]
        assert job["needs"] == "review", name
        assert job["uses"].split("@")[0].endswith(".github/workflows/waiting-update.yml"), name
    update = jobs()["update"]
    assert "continue-on-error" not in update
    assert not any("continue-on-error" in s for s in update["steps"]), "the board's update still fails the run"
    assert update["concurrency"] == {
        "group": "waiting-${{ github.repository }}-${{ github.event.issue.number || github.event.pull_request.number }}",
        "cancel-in-progress": False}
    # Only the view's steps, which ask for the rewrite, may continue on error.
    for jname, job in jobs().items():
        assert "continue-on-error" not in job, jname
        for step in job["steps"]:
            if step.get("continue-on-error"):
                assert jname == "view", f"{jname}: {step.get('name')}"
    ask = [s for s in jobs()["view"]["steps"] if s.get("name") == "Ask for the view"]
    assert ask and ask[0].get("continue-on-error") is True, "the view's request is the one step that may fail without failing the run"
