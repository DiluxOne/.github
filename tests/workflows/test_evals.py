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
# GitHub, and repro's with its replay's fix, in their own issue (the
# maintainer's answers on #735).
WITH_SETS = ("spec", "autopilot", "review")


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
    # passes with a warning and proposes its results, until `evals.py baseline` writes it).
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
    assert mod.steps_of(["policy/autonomy.yml"], with_set=True) == list(WITH_SETS)
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
    assert all("head.repo.full_name == github.repository" in str(j.get("if")) for j in jobs.values())
    assert all("fromJSON" in str(j["strategy"]["matrix"]) for j in jobs.values() if "strategy" in j)
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
    if base is not None:
        # A string is the file's raw text (a corrupt one); anything else, its JSON.
        text = base if isinstance(base, str) else json.dumps(base)
        (root / "evals" / step / "baseline.json").write_text(text, encoding="utf-8")
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


def test_c2_a_case_not_replayed_fails_the_runner_with_its_name(tmp_path):
    base = {"passed": 5, "cases": 6, "unrun": 0}
    got = run_score(tmp_path, "repro", results(5, 0, 1), base)
    assert got.returncode == 1 and "The runner did not replay" in got.stdout and "c0" in got.stdout
    assert "Worse than the baseline" not in got.stdout, "a runner's failure is not the step's score"


def baseline_block(step, text):
    start, end = f"--- baseline {step} ---\n", "\n--- end ---"
    assert start in text and end in text.split(start, 1)[1], text
    return json.loads(text.split(start, 1)[1].split(end, 1)[0])


@pytest.mark.parametrize("base", [None, {"pending": "first run"}])
def test_c2_no_baseline_passes_with_a_warning_and_proposes_one(tmp_path, base):
    # Only for a step that never had a baseline (not in BASELINED).
    res = results(5, 1)
    got = run_score(tmp_path, "repro", res, base)
    assert got.returncode == 0, got.stdout + got.stderr
    assert "::warning::" in got.stderr and "No baseline" in got.stdout
    # The block is the whole run's results, what `evals.py baseline` reads.
    assert baseline_block("repro", got.stdout) == res


@pytest.mark.parametrize("step,base", [
    ("review", None), ("spec", None), ("autopilot", {"pending": "again"}),
    ("repro", "{not json"), ("repro", {"found": 1, "flag": 2}), ("review", {"passed": 1, "cases": 6, "unrun": 0}),
])
def test_c2_a_baseline_that_cannot_be_read_fails_closed(tmp_path, step, base):
    # A baselined step's missing or pending file, a corrupt one, or one of
    # the wrong shape: the check could not tell, so it fails, never passes quietly.
    res = ([{"id": f"f{i}", "expect": "flag", "ok": True} for i in range(3)] if step == "review" else results(5, 1))
    got = run_score(tmp_path, step, res, base)
    assert got.returncode == 1, got.stdout + got.stderr
    assert "could not be read" in got.stdout and "--- baseline" not in got.stdout


def test_c2_autopilot_baseline_of_one_still_gates(tmp_path):
    # 1 of 6 with a slack of one could never fail: below the slack there is none.
    base = json.loads((ROOT / "evals" / "autopilot" / "baseline.json").read_text(encoding="utf-8"))
    assert evals().worse("autopilot", {"passed": 0, "cases": 6, "unrun": 0}, {"passed": 1, "cases": 6, "unrun": 0})
    if base.get("passed", 0) >= 1:
        got = run_score(tmp_path, "autopilot", results(0, base["cases"]), base)
        assert got.returncode == 1 and "Worse than the baseline" in got.stdout


def test_c2_baselined_is_every_step_with_a_score_baseline():
    ev = evals()
    for step in ev.STEPS:
        f = ROOT / "evals" / step / "baseline.json"
        scored = f.exists() and "pending" not in json.loads(f.read_text(encoding="utf-8"))
        assert scored == (step in ev.BASELINED), step


def test_c2_no_baseline_and_a_case_not_replayed_still_fails(tmp_path):
    got = run_score(tmp_path, "repro", results(5, 0, 1), None)
    assert got.returncode == 1 and "The runner did not replay" in got.stdout and "--- baseline" not in got.stdout


def test_c2_each_case_is_replayed_in_a_job_of_its_own(tmp_path):
    import subprocess
    out = subprocess.run(["python3", str(ROOT / "scripts" / "evals.py"), "matrix"], input="spec\nautopilot\n", capture_output=True, text=True, check=True).stdout
    matrix = json.loads(out)
    cases = {s: json.loads((ROOT / "evals" / s / "cases.json").read_text(encoding="utf-8")) for s in ("spec", "autopilot")}
    assert [(m["step"], m["case"]) for m in matrix] == [(s, c["id"]) for s in ("spec", "autopilot") for c in cases[s]]
    assert all(isinstance(m["n"], int) and m["minutes"] > evals().STEPS[m["step"]]["minutes"] for m in matrix)
    # The step's jobs merge their results in the cases' order; a case whose
    # job left none is not replayed, by its name.
    one = tmp_path / "one.json"
    one.write_text(json.dumps([{"id": cases["spec"][1]["id"], "expect": "failed", "ok": True}]), encoding="utf-8")
    merged = json.loads(subprocess.run(["python3", str(ROOT / "scripts" / "evals.py"), "merge", "spec", str(one)], capture_output=True, text=True, check=True).stdout)
    assert [r["id"] for r in merged] == [c["id"] for c in cases["spec"]]
    assert [r["ok"] for r in merged] == [None, True] + [None] * (len(cases["spec"]) - 2)
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "evals.yml").read_text(encoding="utf-8"))
    replay = [j for j in wf["jobs"].values() if "matrix.case" in str(j.get("name"))]
    assert replay and "matrix.minutes" in str(replay[0]["timeout-minutes"])


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
    sections = {}
    heading = ""
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
        sections[heading] = sections.get(heading, "") + line + "\n"
    assert "How the AI is measured" in sections
    section = sections["How the AI is measured"]
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


# The autopilot's replay against real git trees: the agent's tree is one
# commit of its own, the merged pull request comes from the real history.

POLICY = """test-first:
  setup: []
  tests:
    - paths: ["tests/**/test_*.py"]
      way: py
  not-tests: []
repro:
  ways:
    py:
      layer: logic
      test: tests/repro/test_issue_{n}.py
      run: python3 -m pytest {test}
      minutes: 2
"""


def git_in(path, *args):
    import subprocess
    return subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True).stdout.strip()


def commit_in(path, files, message):
    for name, text in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text, encoding="utf-8")
    git_in(path, "add", "-A")
    git_in(path, "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)
    return git_in(path, "rev-parse", "HEAD")


def test_c2_the_autopilot_replay_plans_the_merged_tests_from_the_real_base(tmp_path, monkeypatch):
    monkeypatch.setenv("REPO", "Acme/none-such")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    files = {".github/review-policy.yml": POLICY, "src/calc.py": "A = 1\n"}
    real = tmp_path / "real"
    real.mkdir()
    git_in(real, "init", "-q", ".")
    base = commit_in(real, files, "chore: base")
    merge = commit_in(real, {"src/calc.py": "A = 2\n", "tests/unit/test_calc.py": "def test_a():\n    pass\n"}, "feat: a (#9)")
    tree = tmp_path / "tree"
    tree.mkdir()
    git_in(tree, "init", "-q", ".")
    commit_in(tree, files, "the base, as one commit")
    head = commit_in(tree, {"src/calc.py": "A = 2\n"}, "chore: what the agent left")
    ev = evals()
    tf = ev._load("test_first", "test-first.py")
    ran = []
    monkeypatch.setattr(tf, "run_one", lambda root, central, entry, ref, test_ref, out: ran.append((entry["test"], ref, test_ref)) or "passed")
    case = {"id": "Acme/none-such#9:autopilot", "repo": "Acme/none-such", "issue": 9, "base": base, "merge": merge, "tests": ["tests/unit/test_calc.py"]}
    got = ev.merged_tests(str(tree), case, str(real), head, str(tmp_path / "out"))
    assert got == {"tests/unit/test_calc.py": "passed"}
    assert ran == [("tests/unit/test_calc.py", head, merge)]


def test_c2_an_empty_file_list_fails_steps_not_selects_nothing():
    # pr-files.py prints nothing when it could not list the files; the
    # workflow only starts when `paths:` matched one, so "none" is "could
    # not tell", and the check must fail rather than score nothing.
    import subprocess
    import sys
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "evals.py"), "steps"], input="\n", capture_output=True, text=True)
    assert out.returncode == 1 and out.stdout == "" and "could not" in out.stderr
    ok = subprocess.run([sys.executable, str(ROOT / "scripts" / "evals.py"), "steps"], input="README.md\n", capture_output=True, text=True)
    assert ok.returncode == 0 and ok.stdout.strip() == ""
    text = (ROOT / ".github" / "workflows" / "evals.yml").read_text(encoding="utf-8")
    assert "set -euo pipefail" in text and "pr-files.py | python3 scripts/evals.py steps" in text


# C3: the review's gate is review-eval.yml's, exactly: a slack of one case
# on each count, whatever the baseline (a baseline of found <= 1 keeps it).

def old_review_worse(now, base):
    """review-eval.py's worse() as review-eval.yml ran it before #735."""
    why = []
    if base.get("flag") and now["found"] < base["found"] - 1:
        why.append("found")
    if now["blocked"] > base.get("blocked", 0) + 1:
        why.append("blocked")
    if now["unreviewed"] > 1:
        why.append("unreviewed")
    return why


def review_results(found, flag, blocked, clean, unreviewed=0):
    return ([{"id": f"f{i}", "expect": "flag", "ok": i < found} for i in range(flag)]
            + [{"id": f"c{i}", "expect": "clean", "ok": i >= blocked} for i in range(clean)]
            + [{"id": f"u{i}", "expect": "flag", "ok": None} for i in range(unreviewed)])


REVIEW_BASES = [json.loads((ROOT / "evals" / "review" / "baseline.json").read_text(encoding="utf-8")),
                {"found": 1, "flag": 6, "blocked": 0, "clean": 6, "unreviewed": 0},
                {"found": 0, "flag": 6, "blocked": 1, "clean": 6, "unreviewed": 0}]


@pytest.mark.parametrize("base", REVIEW_BASES)
def test_c3_the_review_gate_is_review_eval_ymls(base):
    ev = evals()
    for found in range(base["flag"] + 1):
        for blocked in range(base["clean"] + 1):
            for unreviewed in range(3):
                res = review_results(found, base["flag"], blocked, base["clean"], unreviewed)
                now = ev.score("review", res)
                assert bool(ev.worse("review", now, base)) == bool(old_review_worse(now, base)), (now, base)


def test_c3_the_review_verdict_on_its_baseline_is_the_same_through_both_scripts(tmp_path):
    import subprocess
    base = REVIEW_BASES[0]
    for found in range(base["flag"] + 1):
        for blocked in (0, 1, 2):
            res = tmp_path / f"r{found}{blocked}.json"
            res.write_text(json.dumps(review_results(found, base["flag"], blocked, base["clean"])), encoding="utf-8")
            new = subprocess.run(["python3", str(ROOT / "scripts" / "evals.py"), "score", "review", str(res)], capture_output=True, text=True)
            old = subprocess.run(["python3", str(ROOT / "scripts" / "review-eval.py"), "score", str(res)], capture_output=True, text=True)
            assert (new.returncode, new.stdout) == (old.returncode, old.stdout)
            now = evals().score("review", json.loads(res.read_text(encoding="utf-8")))
            assert new.returncode == (1 if old_review_worse(now, base) else 0), (now, new.stdout)


# C2: a step's score is compared by rate (passed / cases), so a change that
# adds or removes cases is compared fairly.

@pytest.mark.parametrize("now,base,is_worse", [
    ({"passed": 10, "cases": 12, "unrun": 0}, {"passed": 5, "cases": 6, "unrun": 0}, False),  # the same rate, twice the cases
    ({"passed": 8, "cases": 12, "unrun": 0}, {"passed": 5, "cases": 6, "unrun": 0}, False),   # one case of slack, at the baseline's size
    ({"passed": 6, "cases": 12, "unrun": 0}, {"passed": 5, "cases": 6, "unrun": 0}, True),    # 6 more passed, a lower rate
    ({"passed": 4, "cases": 4, "unrun": 0}, {"passed": 5, "cases": 6, "unrun": 0}, False),    # fewer passed, a higher rate
    ({"passed": 2, "cases": 4, "unrun": 0}, {"passed": 5, "cases": 6, "unrun": 0}, True),
    ({"passed": 0, "cases": 12, "unrun": 0}, {"passed": 1, "cases": 6, "unrun": 0}, True),    # the slack never lets 0 pass
])
def test_c2_worse_compares_by_rate_across_set_sizes(now, base, is_worse):
    assert bool(evals().worse("spec", now, base)) == is_worse
