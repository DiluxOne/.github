"""Another organisation's partial configuration (#568): Acme's `.github`
sets only what it changes, and the engine's defaults hold for every other
setting. scripts/config-overlay.sh lays it over a copy of the engine, as
every workflow does after its checkout, and scripts/autonomy.py decides
from what it laid (C1); a repository of Acme's then raises a lane's
`merge` within Acme's `ceiling`, and past it is held there with a
warning (C2)."""
import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ACME = Path(__file__).resolve().parent / "fixtures" / "acme"
GIT = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def run(*args, cwd=None, env=None, check=True):
    full = {**os.environ, **GIT, **(env or {})}
    for key in ("ORG_AUTONOMY", "REPO_AUTONOMY", "DX_AUTOPILOT", "DX_BOT_APP", "DX_BOT_LOGIN", "DX_BOT_ID"):
        if key not in (env or {}):
            full.pop(key, None)
    out = subprocess.run(list(args), cwd=cwd, env=full, capture_output=True, text=True)
    if check:
        assert out.returncode == 0, out.stdout + out.stderr
    return out


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    """A copy of the engine with Acme's `.github` laid over it."""
    tmp = tmp_path_factory.mktemp("acme")
    eng = tmp / "engine"
    shutil.copytree(ROOT, eng, ignore=shutil.ignore_patterns(".git", ".dx-*", "tests", "evals", "node_modules"))
    config = tmp / "config"
    shutil.copytree(ACME, config)
    run("git", "init", "-q", cwd=config)
    run("git", "add", "-A", cwd=config)
    run("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "Acme's configuration", cwd=config)
    out = run("bash", str(eng / "scripts" / "config-overlay.sh"), str(eng),
              env={"GITHUB_REPOSITORY_OWNER": "Acme", "DX_CONFIG_SOURCE": str(config)})
    assert "Acme's policy" in out.stdout
    return eng


def autonomy(eng, *args, env=None, check=True):
    return run("python3", str(eng / "scripts" / "autonomy.py"), *args,
               env={"GITHUB_REPOSITORY": "Acme/widgets", **(env or {})}, check=check)


def engine_policy():
    out = run("python3", str(ROOT / "scripts" / "autonomy.py"), "policy", env={"ORG_AUTONOMY": str(ROOT / "policy" / "autonomy.yml")})
    return json.loads(out.stdout)


def test_c1_the_reproduced_bug_lane_waits_for_a_person(engine):
    out = autonomy(engine, "lane-open", "bugfix-reproduced", check=False)
    assert out.returncode == 1, out.stdout + out.stderr
    assert "needs a person to accept" in out.stdout


def test_c1_every_other_setting_is_the_engines_default(engine):
    acme = json.loads(autonomy(engine, "policy").stdout)
    want = copy.deepcopy(engine_policy())
    want["lanes"]["bugfix-reproduced"]["accept"] = "human"
    want["lanes"]["human-issue"]["merge"]["max-risk"] = "low"
    want["lanes"]["human-issue"]["ceiling"]["max-risk"] = "medium"
    assert acme == want


def test_c1_the_merged_policy_holds_to_its_schema(engine):
    assert autonomy(engine, "check").stdout == ""


def test_c1_acme_is_its_own_organisation(engine):
    org = (engine / "org.yml").read_text(encoding="utf-8")
    assert "Acme" in org and "DiluxOne" not in org
    out = run("python3", "-c", "import org; print(org.ORG, org.APP, org.BOT, org.BOT_ID)", cwd=engine / "scripts")
    assert out.stdout.split() == ["Acme", "acme-bot", "acme-bot[bot]", "7"]


def repo_file(tmp_path, text):
    path = tmp_path / "autonomy.yml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_c2_a_repository_raises_merge_within_the_ceiling(engine, tmp_path):
    out = autonomy(engine, "policy", env={"REPO_AUTONOMY": repo_file(tmp_path, "lanes:\n  human-issue:\n    merge: {max-risk: medium}\n")})
    assert json.loads(out.stdout)["lanes"]["human-issue"]["merge"] == {"max-risk": "medium", "max-complexity": "high"}
    assert "::warning::" not in out.stderr


def test_c2_past_the_ceiling_the_organisations_limit_applies_with_a_warning(engine, tmp_path):
    out = autonomy(engine, "policy", env={"REPO_AUTONOMY": repo_file(tmp_path, "lanes:\n  human-issue:\n    merge: {max-risk: high}\n")})
    assert json.loads(out.stdout)["lanes"]["human-issue"]["merge"] == {"max-risk": "medium", "max-complexity": "high"}
    assert "::warning::lanes.human-issue.merge.max-risk" in out.stderr and "(medium)" in out.stderr


def test_c2_without_its_own_file_a_repository_has_acmes(engine):
    out = autonomy(engine, "policy")
    assert json.loads(out.stdout)["lanes"]["human-issue"]["merge"] == {"max-risk": "low", "max-complexity": "high"}
