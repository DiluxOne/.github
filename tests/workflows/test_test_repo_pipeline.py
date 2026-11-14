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


def test_the_template_is_the_required_workflow_job_for_job_plus_pipeline():
    template, required = load(TEMPLATE), load(REQUIRED)
    assert template[True] == required[True]
    assert template["permissions"] == required["permissions"]
    jobs = dict(template["jobs"])
    pipeline = jobs.pop("pipeline")
    # The same ids, `uses:`, `if:`, `needs`, permissions, inputs and secrets,
    # so the same check names.
    assert jobs == required["jobs"]
    # The whole run as one check: it waits for every other job, runs on the
    # pull request and in the merge queue alike, and fails when one failed
    # or was cancelled.
    assert sorted(pipeline["needs"]) == sorted(required["jobs"])
    assert pipeline["if"] == "always()"
    assert pipeline["permissions"] == {}
    step = pipeline["steps"][-1]
    assert step["env"]["RESULTS"] == "${{ join(needs.*.result, ' ') }}"
    assert '*" failure "*|*" cancelled "*' in step["run"] and "exit 1" in step["run"]


def test_the_pipeline_job_fails_on_a_failed_or_cancelled_job_only():
    import subprocess
    run = load(TEMPLATE)["jobs"]["pipeline"]["steps"][-1]["run"]
    for results, code in (("success skipped success", 0), ("skipped skipped", 0), ("success failure", 1), ("cancelled success", 1)):
        got = subprocess.run(["bash", "-c", run], env={"RESULTS": results, "PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
        assert got.returncode == code, (results, got.stdout)


def test_the_docs_say_the_test_repository_runs_the_candidates_pipeline_and_why():
    for doc in ("docs/versioning.md", "docs/workflows.md"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        paragraphs = [p for p in text.split("\n") if "test-pull-request.yml" in p]
        assert paragraphs, doc
        said = " ".join(paragraphs)
        # What: the test repository runs its own caller at the candidate.
        assert "@v7-next" in said, doc
        # Why: the required workflow runs at `v7`, its calls hard-wired.
        assert "required workflow" in said and "at `v7`" in said and "hard-wired" in said, doc
