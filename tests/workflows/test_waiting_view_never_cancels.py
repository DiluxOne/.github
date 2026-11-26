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
    assert view["env"]["HAS_KEY"] == "${{ secrets.DILUX_BOT_PRIVATE_KEY != '' }}"
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
