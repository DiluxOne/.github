"""The daily drift check brings the workflow callers in step (#672): the
wiring no script's --test can see, read from the workflow's file."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FLOWS = ROOT / ".github" / "workflows"
STEPS = yaml.safe_load((FLOWS / "org-drift.yml").read_text(encoding="utf-8"))["jobs"]["drift"]["steps"]
MAIN = "github.ref == 'refs/heads/main'"


def named(name):
    return next(s for s in STEPS if s.get("name") == name)


def token_of(step):
    """The id of the App token step whose token the step's GH_TOKEN is."""
    env = (step.get("env") or {}).get("GH_TOKEN", "")
    return next((s["id"] for s in STEPS if s.get("id") and f"steps.{s['id']}.outputs.token" in env), None)


def test_the_callers_run_on_main_only_with_a_token_that_writes_workflows_before_compare():
    sync = next(s for s in STEPS if "sync-repos.py callers" in (s.get("run") or ""))
    assert sync["run"].strip() == "python3 scripts/sync-repos.py callers"
    assert sync["if"].startswith(MAIN)
    assert sync.get("continue-on-error") is True
    token = next(s for s in STEPS if s.get("id") == token_of(sync))
    assert token["if"] == MAIN
    assert token.get("continue-on-error") is True
    assert token["with"]["permission-workflows"] == "write"
    for perm in ("contents", "issues", "pull-requests"):
        assert token["with"][f"permission-{perm}"] == "write"
    assert token["with"]["permission-metadata"] == "read"
    # After the labels (lane:org-sync must exist), before the check.
    order = [s.get("name") for s in STEPS]
    labels = named("Sync (labels, shared files, decisions, Adopt issues, releases)")
    assert order.index(labels["name"]) < order.index(sync["name"]) < order.index("Compare")


def test_no_other_step_holds_workflows():
    sync = next(s for s in STEPS if "sync-repos.py callers" in (s.get("run") or ""))
    holders = [s["id"] for s in STEPS if "permission-workflows" in (s.get("with") or {})]
    assert holders == [token_of(sync)]
    users = [s.get("name") for s in STEPS if token_of(s) == token_of(sync)]
    assert users == [sync["name"]]
