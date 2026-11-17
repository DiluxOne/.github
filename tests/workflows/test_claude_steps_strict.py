"""Every Claude step keeps its --allowedTools strict (#793, scripts/agent-keys.py).

From claude-code-action v1.0.273 a step that states no permission mode may
run tools its --allowedTools does not list, and `restrict_untrusted_prs`
guards a pull request from someone without write access. The scripts job
runs agent-keys.py over .github/workflows/*.yml; each case writes a workflow
into `tmp_path` and runs the script on it as that job does."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "agent-keys.py"
SHA = "cc98b3ae241b0fcfb6a42a2690751afffecb4452"


def bot_only():
    spec = importlib.util.spec_from_file_location("agent_keys", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, "BOT_ONLY", None)


def workflow(args, step_id="work", extra=""):
    return f"""name: x
on: workflow_dispatch
permissions: {{}}
jobs:
  j:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - id: {step_id}
        uses: anthropics/claude-code-action@{SHA} # v1.0.278
        with:
          claude_args: |
            --model m
            --allowedTools "Read,Glob,Grep"{args}
{extra}"""


def run(tmp_path, text, name="x.yml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True, cwd=ROOT)


def restrict(value):
    return f"          restrict_untrusted_prs: {value}\n"


@pytest.mark.parametrize("args", ["\n            --permission-mode dontAsk", "\n            --permission-mode default", '\n            --disallowedTools "Bash,Write"'])
def test_a_step_that_states_a_strict_mode_passes(tmp_path, args):
    got = run(tmp_path, workflow(args))
    assert got.returncode == 0, got.stdout + got.stderr


def test_a_step_without_a_permission_mode_is_refused(tmp_path):
    got = run(tmp_path, workflow(""))
    assert got.returncode != 0
    assert "states no permission mode" in got.stdout


@pytest.mark.parametrize("mode", ["bypassPermissions", "acceptEdits"])
def test_a_wide_permission_mode_is_refused(tmp_path, mode):
    got = run(tmp_path, workflow(f"\n            --permission-mode {mode}"))
    assert got.returncode != 0
    assert mode in got.stdout


@pytest.mark.parametrize("name,step_id", [("x.yml", "work"), ("autopilot.yml", "work"), ("autopilot.yml", "spec")])
def test_restrict_untrusted_prs_false_is_refused_everywhere(tmp_path, name, step_id):
    got = run(tmp_path, workflow("\n            --permission-mode dontAsk", step_id, restrict('"false"')), name)
    assert got.returncode != 0
    assert "restrict_untrusted_prs" in got.stdout


def test_the_bot_only_guard_is_refused_outside_the_autopilot(tmp_path):
    guard = bot_only()
    assert guard, "agent-keys.py names the autopilot's guard (BOT_ONLY)"
    value = '"' + guard.replace('"', '\\"') + '"'
    mode = "\n            --permission-mode dontAsk"
    assert run(tmp_path, workflow(mode, "work", restrict(value)), "autopilot.yml").returncode == 0
    for name, step_id in [("claude-review.yml", "work"), ("autopilot.yml", "fix")]:
        got = run(tmp_path, workflow(mode, step_id, restrict(value)), name)
        assert got.returncode != 0, (name, step_id)
        assert "restrict_untrusted_prs" in got.stdout


def test_the_repositorys_workflows_pass():
    got = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=ROOT)
    assert got.returncode == 0, got.stdout + got.stderr
    assert "strict permission mode" in got.stdout
