"""Every AI step is measured (#735): one evaluation set per step under
evals/<step>/, one runner (scripts/evals.py), one workflow (evals.yml)
that runs the set of a step a pull request changes, and the docs that say
how."""
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SIX = ("triage", "repro", "spec", "autopilot", "review", "reply")
# The sets this pull request carries; triage's and reply's come from
# GitHub, in their own issue (the maintainer's answer on #735).
WITH_SETS = ("repro", "spec", "autopilot", "review")


def evals():
    spec = importlib.util.spec_from_file_location("evals", ROOT / "scripts" / "evals.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def public_repos():
    conf = yaml.safe_load((ROOT / "repos.yml").read_text(encoding="utf-8"))
    # A private repository's code would show in this public one's logs.
    private = {"security"}
    return {f"DiluxOne/{name}" for name in (conf.get("repos") or {}) if name not in private}


# C1: each step's set, real cases with their expected outcome.

def test_c1_the_runner_knows_the_six_steps():
    assert tuple(evals().STEPS) == SIX


@pytest.mark.parametrize("step", WITH_SETS)
def test_c1_each_set_holds_six_real_cases(step):
    mod = evals()
    cases = json.loads((ROOT / "evals" / step / "cases.json").read_text(encoding="utf-8"))
    assert len(cases) >= 6, f"{step}: {len(cases)} cases"
    assert len({c["id"] for c in cases}) == len(cases), f"{step}: an id twice"
    repos = public_repos()
    for c in cases:
        assert c["repo"] in repos, f"{c['id']}: {c['repo']} is not a public repository of repos.yml"
        assert c.get("expect"), f"{c['id']}: no expected outcome"
        missing = [f for f in mod.STEPS[step]["fields"] if f not in c]
        assert not missing, f"{c['id']}: no {missing}"
        # A model judges only where no deterministic grade exists: reply.
        assert ("rubric" in c) == (step == "reply"), f"{c['id']}: a rubric only on reply"


def test_c1_the_grades_are_deterministic_but_reply():
    mod = evals()
    judged = [s for s in SIX if mod.STEPS[s]["judge"]]
    assert judged == ["reply"]


@pytest.mark.parametrize("step", WITH_SETS)
def test_c1_each_set_has_its_baseline(step):
    mod = evals()
    base = json.loads((ROOT / "evals" / step / "baseline.json").read_text(encoding="utf-8"))
    # Either a whole run's score, or pending its first paid run (which
    # fails the gate until `evals.py baseline` writes it, never passes it).
    if "pending" in base:
        assert set(base) == {"pending"} and isinstance(base["pending"], str) and base["pending"]
    else:
        assert set(base) == set(mod.score(step, []))


def test_c1_the_review_set_is_unchanged():
    cases = json.loads((ROOT / "evals" / "review" / "cases.json").read_text(encoding="utf-8"))
    assert len(cases) == 12 and {c["expect"] for c in cases} == {"flag", "clean"}


COMMITS = [
    {"sha": "m1", "parent": "p1", "subject": "fix: the bug reproduced from #41 (#42)", "body": "Closes #43.",
     "files": ["scripts/a.py", "tests/repro/test_issue_41.py"]},
    {"sha": "m2", "parent": "p2", "subject": "feat: a new thing (#45)", "body": "Closes #44. More.",
     "files": ["scripts/b.py", "docs/b.md", "tests/workflows/test_b.py", "changelog.d/45.md"]},
    {"sha": "m3", "parent": "p3", "subject": "revert: feat: a new thing (#46)", "body": "Closes #47.",
     "files": ["scripts/b.py", "tests/workflows/test_b.py"]},
    {"sha": "m4", "parent": "p4", "subject": "chore: no issue (#48)", "body": "",
     "files": ["scripts/c.py", "tests/workflows/test_c.py"]},
    {"sha": "m5", "parent": "p5", "subject": "fix: untested (#50)", "body": "Closes #49.", "files": ["scripts/d.py"]},
]


def test_c1_collect_takes_repro_cases_from_the_reproduced_bugs():
    got = evals().cases_from_commits("repro", "DiluxOne/.github", COMMITS, 6)
    assert got == [{"id": "DiluxOne/.github#41:repro", "repo": "DiluxOne/.github", "issue": 41, "pr": 42, "base": "p1",
                    "test": "tests/repro/test_issue_41.py", "expect": "reproduced"}]


def test_c1_collect_takes_spec_and_autopilot_cases_from_accepted_issues_with_tests():
    mod = evals()
    spec = mod.cases_from_commits("spec", "DiluxOne/.github", COMMITS, 6)
    work = mod.cases_from_commits("autopilot", "DiluxOne/.github", COMMITS, 6)
    # Neither a revert, nor a commit that closes no issue, nor one with no test.
    assert [c["issue"] for c in spec] == [44] and [c["issue"] for c in work] == [44]
    assert spec[0]["files"] == ["docs/b.md", "scripts/b.py"] and spec[0]["type"] == "Feature"
    assert work[0]["tests"] == ["tests/workflows/test_b.py"] and work[0]["merge"] == "m2" and work[0]["base"] == "p2"


# C2: a pull request that changes a step runs its set, and fails when worse.

@pytest.mark.parametrize("path, want", [
    (".github/workflows/issue-triage.yml", ["triage"]),
    (".github/workflows/issue-repro.yml", ["repro"]),
    ("scripts/repro-ways.py", ["repro"]),
    (".github/workflows/autopilot.yml", ["spec", "autopilot"]),
    ("scripts/autopilot.py", ["spec", "autopilot"]),
    ("review-profiles/general.md", ["review"]),
    ("kinds/wordpress-plugin/rules.yml", ["review"]),
    (".github/workflows/claude-review.yml", ["review"]),
    (".github/workflows/review-reply.yml", ["reply"]),
    ("evals/spec/cases.json", ["spec"]),
    ("evals/review/baseline.json", ["review"]),
    ("policy/autonomy.yml", list(SIX)),
    ("README.md", []),
    ("scripts/sync-repos.py", []),
    ("evals/README.md", []),
])
def test_c2_a_path_maps_to_its_steps(path, want):
    assert evals().steps_of([path]) == want


def test_c2_the_steps_listed_are_those_with_a_set():
    mod = evals()
    assert mod.steps_of(["policy/autonomy.yml"], with_set=True) == list(WITH_SETS[:3]) + ["review"]
    assert mod.steps_of([".github/workflows/issue-triage.yml"], with_set=True) == []


def test_c2_evals_yml_runs_on_the_union_of_the_paths():
    mod = evals()
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "evals.yml").read_text(encoding="utf-8"))
    on = wf.get("on") or wf.get(True)
    assert sorted(on["pull_request"]["paths"]) == sorted(mod.all_paths())
    assert "step" in on["workflow_dispatch"]["inputs"]
    assert not (ROOT / ".github" / "workflows" / "review-eval.yml").exists(), "evals.yml replaces review-eval.yml"


def test_c2_evals_yml_runs_the_listed_steps_with_the_runner():
    text = (ROOT / ".github" / "workflows" / "evals.yml").read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    jobs = wf["jobs"]
    assert "evals.py steps" in text and "evals.py run" in text and "evals.py score" in text
    run = [j for j in jobs.values() if "strategy" in j][0]
    assert "fromJSON" in str(run["strategy"]["matrix"])
    # A fork's code never runs with the keys.
    assert "head.repo.full_name == github.repository" in str(run.get("if"))
    assert wf["permissions"] == {"contents": "read"}


def run_score(tmp_path, step, results, base):
    import shutil
    import subprocess
    import tempfile
    root = Path(tempfile.mkdtemp(dir=tmp_path))
    (root / "scripts").mkdir(parents=True)
    for f in ("evals.py", "org.py", "issue-schema.py"):
        shutil.copy(ROOT / "scripts" / f, root / "scripts" / f)
    shutil.copy(ROOT / "org.yml", root / "org.yml")
    (root / "policy").mkdir()
    shutil.copy(ROOT / "policy" / "issue-schema.yml", root / "policy" / "issue-schema.yml")
    (root / "evals" / step).mkdir(parents=True)
    (root / "evals" / step / "baseline.json").write_text(json.dumps(base), encoding="utf-8")
    res = root / "results.json"
    res.write_text(json.dumps(results), encoding="utf-8")
    return subprocess.run(["python3", str(root / "scripts" / "evals.py"), "score", step, str(res)], capture_output=True, text=True)


def results(n_ok, n_bad, n_none=0):
    return ([{"id": f"a{i}", "expect": "passed", "ok": True} for i in range(n_ok)]
            + [{"id": f"b{i}", "expect": "passed", "ok": False} for i in range(n_bad)]
            + [{"id": f"c{i}", "expect": "passed", "ok": None} for i in range(n_none)])


def test_c2_score_fails_when_worse_than_the_baseline(tmp_path):
    base = {"passed": 5, "cases": 6, "unrun": 0}
    assert run_score(tmp_path, "autopilot", results(4, 2), base).returncode == 0, "one case of slack"
    got = run_score(tmp_path, "autopilot", results(3, 3), base)
    assert got.returncode == 1 and "Worse than the baseline" in got.stdout
    assert run_score(tmp_path, "autopilot", results(4, 0, 2), base).returncode == 1, "two cases not replayed"


def test_c2_a_pending_baseline_fails(tmp_path):
    got = run_score(tmp_path, "spec", results(6, 0), {"pending": "first run"})
    assert got.returncode == 1 and "No baseline" in got.stdout


def test_c2_the_review_scores_as_before(tmp_path):
    base = {"found": 3, "flag": 6, "blocked": 0, "clean": 6, "unreviewed": 0}
    res = ([{"id": f"f{i}", "expect": "flag", "ok": i < 1} for i in range(6)]
           + [{"id": f"c{i}", "expect": "clean", "ok": True} for i in range(6)])
    got = run_score(tmp_path, "review", res, base)
    assert got.returncode == 1 and "it found 1 of 6 known bugs, the baseline 3 of 6" in got.stdout


# C4: the docs say how the AI is measured, which paths run which set, and
# how a case is added.

DOCS = ("docs/model.md", "docs/testing-and-quality.md", "docs/workflows.md")


@pytest.mark.parametrize("doc", DOCS)
def test_c4_each_doc_names_the_runner_and_the_workflow(doc):
    text = (ROOT / doc).read_text(encoding="utf-8")
    assert "evals.py" in text and "evals.yml" in text, doc


def test_c4_testing_and_quality_says_which_paths_run_which_set_and_how_a_case_is_added():
    text = (ROOT / "docs" / "testing-and-quality.md").read_text(encoding="utf-8")
    assert "## How the AI is measured" in text
    section = text.split("## How the AI is measured", 1)[1]
    mod = evals()
    for step in SIX:
        assert f"`{step}`" in section, step
        for path in mod.STEPS[step]["paths"]:
            assert path in section, f"{step}: {path}"
    assert "policy/autonomy.yml" in section and "evals/<step>/" in section
    assert "evals.py collect" in section and "evals.py baseline" in section


def test_c4_no_page_links_the_removed_review_eval_yml():
    for path in [*ROOT.glob("*.md"), *ROOT.glob("docs/**/*.md"), *ROOT.glob("kinds/**/*.md")]:
        assert "workflows/review-eval.yml" not in path.read_text(encoding="utf-8"), path
