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
    # The pull request's verdict as one check (#754): it runs on the pull
    # request and in the merge queue alike, and decides on the gates alone.
    assert pipeline["if"] == "always()"
    assert pipeline["permissions"] == {}
    step = pipeline["steps"][-1]
    assert step["env"]["NEEDS"] == "${{ toJSON(needs) }}"


GATES = ("conventions", "review", "auto-merge")


def pipeline_step(needs):
    """The `pipeline` job's step, run with `needs` as GitHub gives it."""
    import json
    import subprocess
    run = load(TEMPLATE)["jobs"]["pipeline"]["steps"][-1]["run"]
    env = {"NEEDS": json.dumps({job: {"result": result, "outputs": {}} for job, result in needs.items()}), "PATH": "/usr/bin:/bin"}
    return subprocess.run(["bash", "-c", run], env=env, capture_output=True, text=True)


def test_c1_the_pipeline_passes_when_its_gates_pass_whatever_waiting_did():
    # `waiting`, whose view its own concurrency group cancels, is no gate:
    # not in `needs`, so its result never reaches the step.
    assert "waiting" not in load(TEMPLATE)["jobs"]["pipeline"]["needs"]
    for results in (("success", "success", "success"), ("success", "success", "skipped"), ("skipped", "skipped", "skipped")):
        got = pipeline_step(dict(zip(GATES, results)))
        assert got.returncode == 0, (results, got.stdout, got.stderr)
        assert "::error::" not in got.stdout, got.stdout


def test_c2_a_failed_or_cancelled_gate_fails_the_pipeline_naming_it():
    for gate in GATES:
        for result, said in (("failure", "failed"), ("cancelled", "was cancelled")):
            got = pipeline_step({g: (result if g == gate else "success") for g in GATES})
            assert got.returncode == 1, (gate, result, got.stdout)
            errors = [line for line in got.stdout.splitlines() if line.startswith("::error::")]
            assert errors == [f"::error::the job {gate} {said}"], (gate, result, got.stdout)
    # Two that fail are both named.
    got = pipeline_step({"conventions": "failure", "review": "skipped", "auto-merge": "cancelled"})
    assert got.returncode == 1
    assert "::error::the job conventions failed" in got.stdout and "::error::the job auto-merge was cancelled" in got.stdout


def org_module():
    spec = importlib.util.spec_from_file_location("org", ROOT / "scripts" / "org.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_c3_the_pipeline_needs_the_gates_of_org_yml_each_a_job_of_the_required_workflow():
    mod = org_module()
    gates = mod.pipeline_gates(mod.load(str(ROOT / "org.yml")))
    # One place: org.yml `pipeline-gates`; a workflow cannot read it before
    # its jobs are planned, so this test holds `needs` to it.
    assert load(TEMPLATE)["jobs"]["pipeline"]["needs"] == gates
    assert gates == list(GATES)
    # The required workflow's checks: each gate is one of its jobs.
    required = load(REQUIRED)["jobs"]
    assert all(gate in required for gate in gates), (gates, sorted(required))


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


def test_c4_the_docs_say_which_jobs_the_pipeline_decides_on_and_why():
    text = (ROOT / "docs" / "workflows.md").read_text(encoding="utf-8")
    said = " ".join(p for p in text.split("\n") if "test-pull-request.yml" in p and "`pipeline`" in p)
    # Which: the three gates, from org.yml.
    assert all(f"`{gate}`" in said for gate in GATES) and "`pipeline-gates`" in said, said
    # Why the others do not count: side work, `waiting`'s view cancelled.
    assert "do not count" in said and "side work" in said and "`waiting`" in said and "cancelled by its own concurrency group" in said, said
