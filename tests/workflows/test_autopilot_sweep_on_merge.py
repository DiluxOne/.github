"""#669: a merge into main elsewhere brings the autopilot pull requests it
leaves behind or in conflict back in step within minutes, not the hour:
issues.yml's `autopilot-sweep` job (the template's, which every repository
runs, and its mirror here) calls the sweep for that one repository on a
merged pull request's `closed`, and the sweep runs the engine's scripts,
never the caller's code."""
from pathlib import Path

import yaml

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


def test_a_conflict_continues_its_issue_free():
    run = step("Bring each one in step")["run"]
    cont = run[run.index("continue)"):run.index("esac")]
    assert 'gh issue edit "$issue" --repo "$repo" --add-label "autopilot:catchup" --add-label "autopilot:continue"' in cont
