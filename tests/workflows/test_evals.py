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
