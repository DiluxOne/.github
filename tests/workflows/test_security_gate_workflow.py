"""The "Security gate" check on a fork's pull request (#956 C7): it reads a
stranger's code, so it runs on `pull_request` only (never
`pull_request_target`), with `contents: read` and nothing more, no secret
passed or read, a checkout that keeps no token, and every action pinned to
a commit."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / ".github" / "workflows" / "security-gate.yml"
CALLERS = [ROOT / ".github" / "workflows" / "org-pull-request.yml", ROOT / ".github" / "workflows" / "pull-request.yml",
           ROOT / "workflow-templates" / "test-pull-request.yml"]
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def load(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # YAML reads the key `on` as True.
    data["on"] = data.pop(True, data.get("on"))
    return data


def test_c7_the_gate_runs_on_pull_request_with_no_secret_and_no_write_token():
    assert GATE.is_file(), ".github/workflows/security-gate.yml is the pull request's check"
    wf = load(GATE)
    text = GATE.read_text(encoding="utf-8")
    assert list(wf["on"]) == ["workflow_call"], "reusable only"
    assert "secrets" not in (wf["on"]["workflow_call"] or {}), "it takes no secret"
    assert "secrets." not in text and "secrets:" not in text, "it reads no secret"
    assert "pull_request_target" not in text
    assert wf["permissions"] == {"contents": "read"}
    for name, job in wf["jobs"].items():
        assert job["permissions"] == {"contents": "read"}, name
        assert job["if"] == "github.event_name == 'pull_request'", name
        assert job["runs-on"] == "ubuntu-latest", "a fork's code: GitHub's fresh runner"
        for s in job["steps"]:
            uses = s.get("uses")
            if not uses:
                continue
            assert PINNED.match(uses), f"{uses} is pinned to a full commit SHA"
            if uses.startswith("actions/checkout@"):
                assert s["with"]["persist-credentials"] is False, "the checkout keeps no token"
            assert "token" not in (s.get("with") or {}), "no token is handed to an action"
        # Untrusted text never inside a script.
        for s in job["steps"]:
            assert "github.event" not in str(s.get("run", "")), s.get("name")


def test_c7_its_callers_run_it_on_pull_request_and_pass_it_no_secret():
    for path in CALLERS:
        wf = load(path)
        assert "pull_request" in wf["on"] and "pull_request_target" not in wf["on"], path.name
        job = wf["jobs"]["security-gate"]
        assert re.fullmatch(r"(\./|DiluxOne/\.github/)\.github/workflows/security-gate\.yml(@v7)?", job["uses"]), path.name
        assert "secrets" not in job, f"{path.name} passes the gate no secret"
        assert job["permissions"] == {"contents": "read"}, path.name
        assert "github.event_name == 'pull_request'" in job.get("if", ""), path.name


def test_c7_it_is_a_required_check_of_this_repository():
    repos = yaml.safe_load((ROOT / "repos.yml").read_text(encoding="utf-8"))
    assert "security-gate / Security gate" in repos["repos"][".github"]["required-checks"]
