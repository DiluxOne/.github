"""#669: a merge into main elsewhere brings the autopilot pull requests it
leaves behind or in conflict back in step within minutes, not the hour:
issues.yml's `autopilot-sweep` job (the template's, which every repository
runs, and its mirror here) calls the sweep for that one repository on a
merged pull request's `closed`, and the sweep runs the engine's scripts,
never the caller's code."""
import json
from pathlib import Path

import yaml

try:
    import steps
except ModuleNotFoundError:  # #845: with no helper, each test fails on its assertion, not on this import
    import types

    def _missing(*_args, **_kwargs):
        helper = Path(__file__).with_name("steps.py")
        assert helper.is_file(), f"{helper.name}, which runs a workflow's step with stubs, is missing"

    steps = types.SimpleNamespace(evaluate=_missing, receipt=_missing, run=_missing, step=_missing, where=_missing, workflow=_missing)
run = steps.run

ROOT = Path(__file__).resolve().parents[2]
FLOWS = ROOT / ".github" / "workflows"
CALLERS = ((ROOT / "workflow-templates" / "issues.yml", "DiluxOne/.github/.github/workflows/autopilot-sweep.yml@v7"),
           (FLOWS / "issues.yml", "./.github/workflows/autopilot-sweep.yml"))
MERGED = ("github.event_name == 'pull_request_target' && github.event.action == 'closed' && github.event.pull_request.merged == true"
          " && github.event.pull_request.base.ref == github.event.repository.default_branch")


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def sweep():
    return load(FLOWS / "autopilot-sweep.yml")["jobs"]["sweep"]


def step(name):
    return next(s for s in sweep()["steps"] if s.get("name") == name)


def test_every_caller_sweeps_its_own_repository_on_a_merge_into_the_default_branch():
    for path, uses in CALLERS:
        doc = load(path)
        on = doc.get("on", doc.get(True))
        assert "closed" in on["pull_request_target"]["types"], path
        job = doc["jobs"]["autopilot-sweep"]
        assert job["if"] == MERGED, path
        assert job["uses"] == uses, path
        assert job["with"] == {"repo": "${{ github.repository }}"}, path
        # The bot's key alone, never every secret the caller holds.
        assert job["secrets"] == {"DILUX_BOT_PRIVATE_KEY": "${{ secrets.DILUX_BOT_PRIVATE_KEY }}"}, path
        assert job["permissions"] == {"contents": "read"}, path


def test_the_sweep_runs_the_engine_at_its_own_commit_and_no_callers_code():
    steps = sweep()["steps"]
    assert not any(str(s.get("uses", "")).startswith("actions/checkout@") for s in steps)
    scripts = step("The organisation's scripts")
    assert scripts["env"]["REF"] == "${{ job.workflow_sha }}"
    assert "https://github.com/DiluxOne/.github \"$REF\"" in scripts["run"] and ".dx-central" in scripts["run"]
    run = step("Bring each one in step")["run"]
    assert "python3 .dx-central/scripts/autopilot.py sweep" in run
    assert "python3 .dx-central/scripts/autopilot.py core-wait" in run
    assert "python3 scripts/" not in run


def test_one_repositorys_sweep_gets_a_token_for_it_alone():
    where = step("Which repository")
    assert where["env"]["REPO"] == "${{ inputs.repo }}"
    assert 'echo "name=${REPO#*/}"' in where["run"]
    token = step("App token")["with"]
    assert token["repositories"] == "${{ steps.where.outputs.name }}"
    assert token["owner"] == "${{ github.repository_owner }}"
    run = step("Bring each one in step")["run"]
    assert 'if [ -n "$REPO" ]; then where=(--repo "$REPO")' in run


GH = r"""case "$*" in
  "search prs "*) echo "o/r 5" ;;
  "pr view 5 "*) cat "$DX_PR" ;;
  "issue view 7 --repo o/r --json labels "*) echo '[]' ;;
  "issue edit "*) cp "$RECEIPTS_FIXTURE/comments/7/board.md" "$RUNNER_TEMP/board-at-edit.md"; exit "${EDIT_RC:-0}" ;;
  "search issues "*) ;;
  "api -X GET search/issues "*) echo 0 ;;
esac"""


def swept(tmp_path, pr, **env):
    """The sweep's step for o/r with one open autopilot pull request, #5
    (PR, as gh pr view gives it), which closes #7: the run, and #7's board."""
    pr = {"number": 5, "labels": [{"name": "autopilot"}], "author": {"login": "app/dilux-bot"}, "headRefOid": "abc123",
          "closingIssuesReferences": [{"number": 7}], **pr}
    (tmp_path / "pr.json").write_text(json.dumps(pr))
    fx = tmp_path / "fx"
    fx.mkdir()
    ran = run(steps.step("autopilot-sweep.yml", "Bring each one in step"), tmp_path, stubs={"gh": GH, "sleep": ""},
              env={"REPO": "o/r", "OWNER": "o", "DX_PR": str(tmp_path / "pr.json"), "RECEIPTS_FIXTURE": str(fx),
                   "DX_BOT_APP": "dilux-bot", "DX_BOT_LOGIN": "dilux-bot[bot]", **env})
    board = fx / "comments" / "7" / "board.md"
    return ran, board.read_text() if board.exists() else ""


def test_a_conflict_continues_its_issue_free(tmp_path):
    ran, board = swept(tmp_path, {"isDraft": False, "mergeStateStatus": "DIRTY"})
    assert ran.code == 0, ran.stdout + ran.stderr
    assert ["issue", "edit", "7", "--repo", "o/r", "--add-label", "autopilot:continue"] in ran.of("gh"), ran.calls
    # The catch-up is on the board before the continue is asked for.
    assert '"catchup":true' in (ran.temp / "board-at-edit.md").read_text()
    assert not any(c[:2] == ["api", "-X"] and c[2] == "PUT" for c in ran.of("gh"))


def test_a_continue_that_cannot_be_asked_for_takes_the_catch_up_off_and_fails(tmp_path):
    ran, board = swept(tmp_path, {"isDraft": False, "mergeStateStatus": "DIRTY"}, EDIT_RC="1")
    assert ran.code == 1 and "the continue could not be asked for on o/r#7" in ran.stdout
    assert '"catchup":true' not in board


def test_one_only_behind_main_gets_main_merged_in_at_its_head(tmp_path):
    """C2: on `update` (autopilot.py sweep --test covers the verdict for a
    pull request only behind main), the same merge-triggered sweep merges
    main into it with GitHub's update-branch, at the head it read."""
    ran, board = swept(tmp_path, {"isDraft": True, "mergeStateStatus": "BEHIND"})
    assert ran.code == 0, ran.stdout + ran.stderr
    assert ["api", "-X", "PUT", "repos/o/r/pulls/5/update-branch", "-f", "expected_head_sha=abc123"] in ran.of("gh"), ran.calls
    assert not any(c[:1] == ["issue"] and "edit" in c for c in ran.of("gh"))
    # A token that may merge main in: contents write, on that repository.
    token = step("App token")["with"]
    assert token["permission-contents"] == "write" and token["repositories"] == "${{ steps.where.outputs.name }}"
