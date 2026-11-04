"""The ai-agent-plugin kind reproduces a bug with pytest (#653): its pack's
way, read through scripts/repro-ways.py for a repository of the kind."""
import json
import os
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PINS = re.compile(r"\b(pytest|PyYAML)==(\S+)")


def resolve(tmp_path, layer, policy=None):
    (tmp_path / "tests").mkdir(exist_ok=True)
    env = dict(os.environ, REPO="DiluxOne/dilux-agentic-workflow", DIR=str(tmp_path), CENTRAL=str(ROOT),
               LAYER=layer, NUMBER="653", REPO_POLICY=str(tmp_path / "review-policy.yml"))
    env.pop("GITHUB_OUTPUT", None)
    (tmp_path / "review-policy.yml").write_text(yaml.safe_dump(policy or {}), encoding="utf-8")
    out = subprocess.run(["python3", str(ROOT / "scripts/repro-ways.py"), "resolve"], env=env,
                         capture_output=True, text=True, check=True)
    return dict(line.split("=", 1) for line in out.stdout.splitlines() if "=" in line)


def test_the_kind_reproduces_a_bug_with_pytest(tmp_path):
    for layer in ("logic", "cli"):
        got = resolve(tmp_path, layer)
        assert (got["way"], got["test"], got["noun"], got["ready"], got["why"]) == (
            "unit", "tests/repro/test_issue_653.py", "Python test", "yes", "")
    # A repository of the kind with no Python tests switches it off.
    off = resolve(tmp_path, "logic", {"repro": {"ways": {"unit": False}}})
    assert off["way"] == "" and off["ready"] == "no"


def test_repro_ways_lists_the_pytest_way(tmp_path):
    got = resolve(tmp_path, "logic")
    assert got["problems"] == "" and got["minutes"] == "10"
    spec = json.loads(got["spec"])
    assert spec["test"] == "tests/repro/test_issue_653.py"
    assert spec["junit"] == "build/repro.xml"
    setup = " ".join(spec["setup"])
    assert all("pip install" in line and "--target build/dx-py" in line for line in spec["setup"])
    # A repository's own dependencies, only where it has them.
    assert any(line.startswith("if [ -f requirements.txt ]") for line in spec["setup"])
    # The pins this repository's own ways and CI install.
    own = yaml.safe_load((ROOT / ".github/review-policy.yml").read_text(encoding="utf-8"))["repro"]["ways"]["python"]
    assert sorted(PINS.findall(setup)) == sorted(PINS.findall(" ".join(own["setup"]))) != []
    assert "python3 -m pytest" in spec["run"] and "--junitxml=build/repro.xml" in spec["run"]
    assert spec["run"].endswith("tests/repro/test_issue_653.py")
    # No token reaches it, nor the network: scripts/repro-run.sh runs it.
    assert not re.search(r"\$\{?(GH_|GITHUB_|[A-Z_]*TOKEN)", json.dumps(spec))
