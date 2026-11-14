"""The test repository runs the candidate's pull-request pipeline (#748):
its own caller, workflow-templates/test-pull-request.yml, which the release
lane moves to `@v7-next` with its other callers, in place of the required
workflow, which the organisation's ruleset reads at `v7`."""
import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "workflow-templates" / "test-pull-request.yml"
REQUIRED = ROOT / ".github" / "workflows" / "org-pull-request.yml"


def scenarios():
    spec = importlib.util.spec_from_file_location("release_scenarios", ROOT / "scripts" / "release-scenarios.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_review_auto_merge_and_fix_rounds_run_the_candidate_once_moved():
    mod = scenarios()
    text = TEMPLATE.read_text(encoding="utf-8")
    jobs = yaml.safe_load(mod.at_ref(text, "DiluxOne/.github", "v7-next"))["jobs"]
    for job in ("review", "auto-merge", "autopilot-fix", "autopilot-queue"):
        assert jobs[job]["uses"].startswith("DiluxOne/.github/.github/workflows/"), job
        assert jobs[job]["uses"].endswith("@v7-next"), job
    # Every engine call there, not those three alone, is one the move rewrites.
    assert "@v7\n" not in mod.at_ref(text, "DiluxOne/.github", "v7-next")


def test_the_pack_gives_the_test_repository_the_caller():
    pack = load(ROOT / "kinds" / "engine-test" / "pack.yml")
    assert "test-pull-request.yml" in pack["callers"]
