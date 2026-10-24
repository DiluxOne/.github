"""#361: the size limit for outside authors stops the organisation's own bot.
Written from the report as the reproduction's writer would (#376); it failed
on the commit before the fix (7396d1f) and passes since.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def issue_gate(tmp_path, **env):
    """scripts/policy.py as conventions.yml runs it: its outputs as a dict."""
    out = tmp_path / "out"
    out.write_text("")
    repo = tmp_path / "review-policy.yml"
    repo.write_text("{}\n")
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("PR_", "HEAD_", "DX_", "POLICY_"))}
    clean.update({"POLICY_MODE": "issue-gate", "DEFAULT_POLICY": str(ROOT / "policy" / "review-policy.default.yml"),
                  "REPO_POLICY": str(repo), "GITHUB_OUTPUT": str(out), "CHANGED_FILES": "scripts/a.py"}, **env)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "policy.py")], env=clean, cwd=ROOT, check=True, capture_output=True, text=True)
    return dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)


def test_the_organisations_bot_from_a_branch_of_the_repository_has_no_size_cap(tmp_path):
    gate = issue_gate(tmp_path, PR_AUTHOR="dilux-bot[bot]", PR_AUTHOR_TYPE="Bot", HEAD_IN_REPO="true")
    assert gate["max_lines"] == ""


def test_an_untrusted_person_keeps_the_size_cap(tmp_path):
    gate = issue_gate(tmp_path, PR_AUTHOR="someone", PR_AUTHOR_TYPE="User", HEAD_IN_REPO="false")
    assert gate["max_lines"] != ""
