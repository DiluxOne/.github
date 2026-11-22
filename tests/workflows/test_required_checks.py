"""#842 C1: a pull request to DiluxOne/.github whose `Scripts (self-tests)`
or `Test first` is red cannot merge, and one with nothing for them to check
sees both report success.

Three pieces hold it: test-first.yml's `verdict` job, the one "Test first"
check, which reports on every pull request and is red when the tests are;
pull-request.yml, which runs both jobs on every pull request; and the
ruleset "own checks" that `sync-repos.py own-checks` writes from repos.yml
`required-checks`, requiring exactly those contexts, with the security
gate's (#956)."""
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from steps import evaluate

ROOT = Path(__file__).resolve().parents[2]
FLOWS = ROOT / ".github" / "workflows"
REQUIRED = ["Scripts (self-tests)", "test-first / Test first", "security-gate / Security gate"]


def workflow(name):
    return yaml.safe_load((FLOWS / name).read_text(encoding="utf-8"))


def triggers(wf):
    return wf.get("on", wf.get(True))


def load(name):
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# test-first.yml: one "Test first" check that always reports.

def verdict_job():
    jobs = workflow("test-first.yml")["jobs"]
    assert "verdict" in jobs, "test-first.yml has no `verdict` job"
    return jobs["verdict"]


def test_the_check_named_test_first_is_the_verdict_of_the_plan_and_the_tests():
    jobs = workflow("test-first.yml")["jobs"]
    named = [k for k, j in jobs.items() if j.get("name") == "Test first"]
    assert named == ["verdict"]
    assert jobs["plan"]["name"] == "Test first (plan)"
    job = verdict_job()
    assert job["needs"] == ["plan", "run"]
    assert " ".join(str(job["if"]).split()) == "always() && github.event_name == 'pull_request'"
    assert job["runs-on"] == "ubuntu-latest"


def verdict(plan, result, run):
    """The verdict step's exit code for the plan's job result, the plan's
    `result` output and the tests' job result."""
    step = next(s for s in verdict_job()["steps"] if "run" in s)
    env = {k: v for k, v in step["env"].items()}
    assert env == {"PLAN": "${{ needs.plan.result }}", "RESULT": "${{ needs.plan.outputs.result }}", "RUN": "${{ needs.run.result }}"}
    out = subprocess.run(["bash", "-c", step["run"]], env={"PATH": "/usr/bin:/bin", "PLAN": plan, "RESULT": result, "RUN": run},
                         capture_output=True, text=True)
    return out.returncode


@pytest.mark.parametrize("plan,result,run", [
    ("success", "run", "success"),     # the tests ran and passed
    ("success", "pass", "skipped"),    # nothing to check: a docs pull request
    ("success", "", "skipped"),
])
def test_the_verdict_is_green_when_the_tests_passed_or_there_was_nothing_to_run(plan, result, run):
    assert verdict(plan, result, run) == 0


@pytest.mark.parametrize("plan,result,run", [
    ("success", "run", "failure"),     # the tests are red
    ("success", "run", "cancelled"),
    ("success", "run", "skipped"),     # the plan said run, yet nothing ran
    ("failure", "", "skipped"),        # a fix with no test, or no declaration
    ("cancelled", "", "skipped"),
    ("skipped", "", "skipped"),
])
def test_the_verdict_is_red_otherwise(plan, result, run):
    assert verdict(plan, result, run) != 0


# pull-request.yml: both checks run on every pull request.

def test_both_required_checks_run_on_every_pull_request():
    wf = workflow("pull-request.yml")
    on = triggers(wf)["pull_request"]
    assert "paths" not in on and "paths-ignore" not in on
    assert set(on["types"]) >= {"opened", "synchronize", "reopened", "ready_for_review"}
    jobs = wf["jobs"]
    assert jobs["scripts"]["name"] == "Scripts (self-tests)"
    assert "if" not in jobs["scripts"]
    assert jobs["test-first"]["if"] == "github.event_name == 'pull_request'"
    assert jobs["test-first"]["uses"] == "./.github/workflows/test-first.yml"
    assert evaluate(jobs["test-first"]["if"], {"github.event_name": "pull_request"}) is True
    # The contexts these jobs report are the two the ruleset requires: a
    # called workflow's check is `<caller job's name> / <its job's name>`.
    called = workflow("test-first.yml")["jobs"]
    contexts = [jobs["scripts"]["name"]] + [f"{jobs['test-first'].get('name', 'test-first')} / {j['name']}"
                                            for j in called.values() if j.get("name") == "Test first"]
    # #956: the security gate's check, on every pull request too.
    assert jobs["security-gate"]["if"] == "github.event_name == 'pull_request'"
    assert jobs["security-gate"]["uses"] == "./.github/workflows/security-gate.yml"
    contexts += [f"security-gate / {j['name']}" for j in workflow("security-gate.yml")["jobs"].values()]
    assert contexts == REQUIRED


# repos.yml and the ruleset "own checks".

def test_repos_yml_requires_the_two_checks_here_and_its_schema_knows_the_key():
    conf = yaml.safe_load((ROOT / "repos.yml").read_text(encoding="utf-8"))
    assert conf["repos"][".github"].get("required-checks") == REQUIRED
    rc = load("repos-config")
    assert "required-checks" in rc.ATTRIBUTES
    assert "required-checks" in load("repos_conf").ATTRIBUTES


@pytest.fixture
def sync(monkeypatch):
    mod = load("sync-repos")
    state = {"calls": [], "bodies": [], "mine": []}

    class Out:
        returncode, stdout, stderr = 0, "{}", ""

    def gh(*args, check=True, input_text=None):
        state["calls"].append(" ".join(args))
        if input_text is not None:
            state["bodies"].append((" ".join(args), json.loads(input_text)))
        return Out()

    monkeypatch.setattr(mod, "gh", gh)
    monkeypatch.setattr(mod, "rulesets", lambda full: copy.deepcopy(state["mine"]))
    monkeypatch.setattr(mod, "org_rulesets", lambda: [])
    state["mod"] = mod
    return state


def writes(state):
    return [c for c in state["calls"] if " -X " in c]


def own_rule(contexts, strict=False):
    return {"type": "required_status_checks", "parameters": {
        "strict_required_status_checks_policy": strict, "do_not_enforce_on_create": False,
        "required_status_checks": [{"context": c} for c in contexts]}}


def test_own_checks_creates_the_ruleset_requiring_exactly_the_two_checks(sync):
    sync["mod"].sync_own_checks({"name": ".github", "defaultBranchRef": {"name": "main"}}, False)
    assert writes(sync) == ["api -X POST repos/DiluxOne/.github/rulesets --input -"]
    body = sync["bodies"][0][1]
    assert body == {"name": "own checks", "target": "branch", "enforcement": "active", "bypass_actors": [],
                    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
                    "rules": [own_rule(REQUIRED)]}


def test_own_checks_replaces_only_the_required_checks_and_sends_the_whole_ruleset(sync):
    signed = {"type": "required_signatures"}
    sync["mine"] = [{"id": 5, "name": "own checks", "target": "branch", "enforcement": "active", "source_type": "Repository",
                     "source": "DiluxOne/.github", "node_id": "X", "_links": {}, "created_at": "t", "updated_at": "t",
                     "current_user_can_bypass": "never", "bypass_actors": [{"actor_id": 1, "actor_type": "OrganizationAdmin", "bypass_mode": "always"}],
                     "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": ["refs/heads/x"]}},
                     "rules": [signed, own_rule(["lint"], strict=True)]}]
    sync["mod"].sync_own_checks({"name": ".github", "defaultBranchRef": {"name": "main"}}, False)
    assert writes(sync) == ["api -X PUT repos/DiluxOne/.github/rulesets/5 --input -"]
    body = sync["bodies"][0][1]
    assert body == {"name": "own checks", "target": "branch", "enforcement": "active",
                    "bypass_actors": [{"actor_id": 1, "actor_type": "OrganizationAdmin", "bypass_mode": "always"}],
                    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": ["refs/heads/x"]}},
                    "rules": [signed, own_rule(REQUIRED)]}


def test_own_checks_in_step_writes_nothing(sync):
    sync["mine"] = [{"id": 5, "name": "own checks", "target": "branch", "enforcement": "active",
                     "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}, "rules": [own_rule(REQUIRED)]}]
    sync["mod"].sync_own_checks({"name": ".github", "defaultBranchRef": {"name": "main"}}, False)
    assert writes(sync) == []


def test_own_checks_never_writes_a_ruleset_with_part_of_its_conditions(sync):
    sync["mine"] = [{"id": 5, "name": "own checks", "target": "branch", "enforcement": "active",
                     "conditions": {}, "rules": [own_rule(["lint"])]}]
    with pytest.raises(RuntimeError, match="`ref_name`"):
        sync["mod"].sync_own_checks({"name": ".github", "defaultBranchRef": {"name": "main"}}, False)
    assert writes(sync) == []
