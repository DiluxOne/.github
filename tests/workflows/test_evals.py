"""Every AI step is measured (#735): one set per step, one runner
(scripts/evals.py), one gate (.github/workflows/evals.yml)."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
STEPS = ["triage", "repro", "spec", "autopilot", "review", "reply"]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def workflow(name):
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def evals(*args, stdin=""):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "evals.py"), *args], input=stdin, capture_output=True, text=True, cwd=ROOT)


# C2: the path-to-step mapping, and the gate.

def test_each_steps_paths_run_that_step():
    ev = load("evals")
    assert list(ev.STEPS) == STEPS
    cases = {
        ".github/workflows/issue-triage.yml": ["triage"],
        "scripts/triage-brief.sh": ["triage"],
        ".github/workflows/issue-repro.yml": ["repro"],
        "scripts/repro-ways.py": ["repro"],
        ".github/workflows/autopilot.yml": ["spec", "autopilot"],
        "scripts/autopilot.py": ["spec", "autopilot", "reply"],
        "review-profiles/general.md": ["review"],
        "kinds/wordpress-plugin/review-profile.md": ["review"],
        "kinds/ai-agent-plugin/rules.yml": ["review"],
        "policy/review-policy.default.yml": ["review"],
        "scripts/local-review.sh": ["review"],
        ".github/workflows/claude-review.yml": ["review"],
        ".github/workflows/review-reply.yml": ["reply"],
        "policy/autonomy.yml": STEPS,
    }
    for path, want in cases.items():
        assert ev.steps_for([path]) == want, path
    for step in STEPS:
        assert ev.steps_for([f"evals/{step}/cases.json"]) == [step]


def test_an_unrelated_path_runs_no_set():
    ev = load("evals")
    for path in ("README.md", "docs/model.md", "scripts/evals.py", "kinds/wordpress-plugin/pack.yml", "kinds/a/b/rules.yml",
                 "tests/workflows/test_evals.py", ".github/workflows/pull-request.yml"):
        assert ev.steps_for([path]) == [], path
    got = evals("steps", stdin="README.md\ndocs/workflows.md\n")
    assert got.returncode == 0 and got.stdout.strip() == ""
    got = evals("steps", stdin="README.md\nscripts/repro-ways.py\n")
    assert got.stdout.split() == ["repro"]


def test_the_workflows_paths_are_the_union_of_the_mapping():
    ev = load("evals")
    wf = workflow("evals.yml")
    on = wf.get("on", wf.get(True))
    assert on["pull_request"]["paths"] == ev.all_paths()
    assert sorted(set(ev.all_paths())) == sorted({p for s in STEPS for p in ev.paths_of(s)})
    assert evals("paths").stdout.split() == ev.all_paths()
    assert "workflow_dispatch" in on


def test_the_workflow_runs_the_steps_the_files_name_one_check_each():
    wf = workflow("evals.yml")
    first = wf["jobs"]["steps"]
    assert "secrets." not in json.dumps(first)
    assert "head.repo.full_name == github.repository" in first["if"]
    run = first["steps"][-1]["run"]
    assert "scripts/pr-files.py | python3 scripts/evals.py steps" in run
    job = wf["jobs"]["eval"]
    assert job["name"] == "AI evaluation (${{ matrix.step }})"
    assert job["strategy"]["matrix"]["step"] == "${{ fromJSON(needs.steps.outputs.steps) }}"
    assert "needs.steps.outputs.steps != '[]'" in job["if"]
    runs = [s.get("run", "") for s in job["steps"]]
    assert any('evals.py run "$STEP"' in r for r in runs)
    assert any('evals.py score "$STEP"' in r and 'exit "${PIPESTATUS[0]}"' in r for r in runs)
    for s in job["steps"]:
        assert "${{" not in s.get("run", ""), s.get("name")
    assert not (ROOT / ".github" / "workflows" / "review-eval.yml").exists()
    collect = wf["jobs"]["collect"]
    assert "secrets." not in json.dumps(collect) and set(collect["permissions"].values()) == {"read"}


def test_score_exits_1_when_worse_than_the_baseline(tmp_path):
    ev = load("evals")
    base = {"passed": 6, "cases": 6, "unreplayed": 0}
    worse = [{"id": str(i), "expect": "pass", "ok": i < 4} for i in range(6)]
    within = [{"id": str(i), "expect": "pass", "ok": i < 5} for i in range(6)]
    assert ev.gate("spec", worse, base)[0] == 1
    assert ev.gate("spec", within, base)[0] == 0
    assert ev.gate("spec", within, None)[0] == 1
    results = tmp_path / "results.json"
    results.write_text(json.dumps([{"id": str(i), "expect": "flag" if i < 6 else "clean", "ok": i >= 6} for i in range(12)]))
    got = evals("score", "review", str(results))
    assert got.returncode == 1 and "Worse than the baseline" in got.stdout
    assert evals("score", "nope", str(results)).returncode == 64


# Option A (#735): what is measured is what ships, the prompts read from
# the scripts both the workflows and the runner call.

def step(wf, name):
    return next(s for j in wf["jobs"].values() for s in j.get("steps") or [] if s.get("name") == name)


def test_the_workflows_read_their_prompts_from_the_scripts():
    tri, rep, rr = workflow("issue-triage.yml"), workflow("issue-repro.yml"), workflow("review-reply.yml")
    assert step(tri, "Classify")["with"]["prompt"] == "${{ steps.prompt.outputs.text }}"
    assert "triage-brief.sh prompt classify" in step(tri, "The classifying prompt")["run"]
    for name in ("Write the test", "Write the test (the repository's way)"):
        assert step(rep, name)["with"]["prompt"] == "${{ steps.prompt.outputs.text }}"
    assert "repro-ways.py prompt" in step(rep, "The prompt that writes the test")["run"]
    assert step(rr, "Reply")["with"]["prompt"] == "${{ steps.prompt.outputs.text }}"
    assert "autopilot.py prompt reply" in step(rr, "The reply's prompt")["run"]


def test_the_scripts_give_the_prompts_filled():
    env = dict(os.environ, GITHUB_REPOSITORY="o/r", BRIEF=".dx-central/brief.md", NUMBER="7", SANDBOX="", LAYER="logic",
               NOUN="Python test", TEST="tests/repro/test_issue_7.py", PR="12", PROFILE="review-profiles/general.md")
    tri = subprocess.run(["bash", str(ROOT / "scripts" / "triage-brief.sh"), "prompt", "classify"], env=env, capture_output=True, text=True).stdout
    assert tri.startswith("You triage issues for o/r. Read .dx-central/brief.md, whole:") and "@" not in tri.split("(#352)")[0]
    rep = subprocess.run([sys.executable, str(ROOT / "scripts" / "repro-ways.py"), "prompt"], env=env, capture_output=True, text=True).stdout
    assert rep.startswith("You try to reproduce a reported bug in o/r, issue #7.\nIt is a logic bug") and "Write ONE Python test at tests/repro/test_issue_7.py." in rep
    rr = subprocess.run([sys.executable, str(ROOT / "scripts" / "autopilot.py"), "prompt", "reply"], env=env, capture_output=True, text=True).stdout
    assert rr.startswith("You are the code reviewer for o/r, pull request #12.") and ".dx-central/review-profiles/general.md," in rr
