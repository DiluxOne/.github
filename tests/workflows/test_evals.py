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


# C3: the runner's self-test, run by the scripts job, and the review's set
# graded as review-eval.py graded it.

def test_the_runner_tests_itself_offline_in_the_scripts_job():
    got = evals("--test")
    assert got.returncode == 0, got.stdout[-2000:]
    for name in ("steps:", "triage:", "repro:", "spec:", "autopilot:", "reply:", "review verdict:", "review score:", "review worse:"):
        assert f"ok   {name}" in got.stdout, name
    runs = [s.get("run", "") for s in workflow("pull-request.yml")["jobs"]["scripts"]["steps"]]
    assert "python3 scripts/evals.py --test" in runs and "python3 scripts/review-eval.py --test" in runs


def test_the_review_gives_review_eval_pys_results_on_its_old_fixtures():
    ev, wrapper = load("evals"), load("review-eval")
    case_f = {"expect": "flag", "path": "a.php"}
    assert ev.verdict(case_f, {"findings": [{"severity": "major", "file": "a.php"}]}) is True
    assert ev.verdict(case_f, {"findings": [{"severity": "minor", "file": "a.php"}, {"severity": "major", "file": "b.php"},
                                            {"severity": "blocker", "file": "a.php", "pre_existing": True}]}) is False
    assert ev.verdict({"expect": "clean"}, {"findings": [{"severity": "major"}]}) is False
    assert ev.verdict(case_f, None) is None
    res = [{"id": "1", "expect": "flag", "ok": True}, {"id": "2", "expect": "flag", "ok": False},
           {"id": "3", "expect": "clean", "ok": False}, {"id": "4", "expect": "clean", "ok": None}]
    now = ev.score(res)
    assert now == {"found": 1, "flag": 2, "blocked": 1, "clean": 1, "unreviewed": 1}
    assert ev.worse(now, {"found": 2, "flag": 2, "blocked": 0}) == ""
    assert ev.worse({**now, "found": 0}, {"found": 2, "flag": 2, "blocked": 0}).startswith("it found 0 of 2")
    assert ev.SLACK == 1
    for name in ("verdict", "score", "worse", "table", "cases_from", "pick"):
        assert getattr(wrapper, name) is getattr(wrapper.evals, name)
    cases = json.loads((ROOT / "evals" / "review" / "cases.json").read_text(encoding="utf-8"))
    assert len(cases) == 12 and all("rubric" not in c for c in cases)


# C4: the docs say how the AI is measured, which paths run which set, and
# how a case is added.

def test_the_docs_say_how_the_ai_is_measured():
    ev = load("evals")
    for doc in ("docs/model.md", "docs/testing-and-quality.md", "docs/workflows.md"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        assert "scripts/evals.py" in text and "evals.yml" in text, doc
        for step in STEPS:
            for path in ev.STEPS[step]["paths"] + ev.EVERY:
                assert f"`{path}`" in text, (doc, step, path)
        assert "evals/<step>/" in text, doc
        assert "collect" in text and "baseline" in text, doc
    quality = (ROOT / "docs" / "testing-and-quality.md").read_text(encoding="utf-8")
    assert "## How the AI is measured" in quality and "`evals.py collect <step> [N]`" in quality and "`evals.py baseline <step> FILE`" in quality
    assert "review-eval.yml)" not in (ROOT / "docs" / "workflows.md").read_text(encoding="utf-8")


# The sets (C1): real cases of the organisation's public repositories, each
# in its step's shape. The triage's and the reply's come from the API (the
# collect job of evals.yml), the baselines from a whole paid run.

def public_names():
    raw = (ROOT / "repos.yml").read_text(encoding="utf-8")
    repos = yaml.safe_load(raw)["repos"]
    private = {name for name in repos if any(l.strip().startswith(f"{name}:") and "private" in l.split("#", 1)[-1] for l in raw.splitlines() if "#" in l)}
    return set(repos) - private


def test_every_set_there_is_holds_real_cases_in_its_steps_shape():
    ev = load("evals")
    names = public_names()
    assert "security" not in names and ".github" in names
    found = [s for s in STEPS if (ROOT / "evals" / s / "cases.json").exists()]
    assert {"repro", "spec", "autopilot", "review"} <= set(found)
    for step in found:
        cases = json.loads((ROOT / "evals" / step / "cases.json").read_text(encoding="utf-8"))
        assert len(cases) >= 6, step
        assert ev.problems(step, cases) == [], step
        for c in cases:
            assert c["repo"].split("/", 1)[1] in names, c["id"]
            assert ("rubric" in c) == (step == "reply"), c["id"]
