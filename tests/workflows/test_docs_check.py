"""The documentation check (#957, scripts/docs-check.py), part of the
security gate (`security-gate.py run`): docs, workflow header comments,
packs and the README that still name what the change removed or renamed
(`docs/stale-name`), and the docs a map ties to a changed path that did not
change (`docs/map`), unless the description says why (`Docs: none, <why>`).

The gate's tools are the stubs of test_security_gate.py: no network."""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_security_gate as gate  # noqa: E402  the scratch repository, the stubs

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts" / "security-gate.py"
CHECK = ROOT / "scripts" / "docs-check.py"

# A reusable workflow with an input, a script with a flag, and a label.
FLOW = """name: Build

# Reusable. Builds the site. Pass `target-dir` to choose where it goes; the
# script runs with --out-dir.

on:
  workflow_call:
    inputs:
      {inp}:
        type: string
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: python3 scripts/build.py {flag} "${{{{ inputs.{inp} }}}}"
"""
SCRIPT = """import sys

def main(argv):
    if argv[:1] == ["{flag}"]:
        return 0
    return 1
"""
LABELS = "labels:\n  - name: {label}\n    color: ededed\n"


def base_files():
    return {
        ".github/workflows/build.yml": FLOW.format(inp="target-dir", flag="--out-dir"),
        "scripts/build.py": SCRIPT.format(flag="--out-dir"),
        "labels.yml": LABELS.format(label="needs-triage"),
        "README.md": "# Site\n\nRun `build.py --out-dir x`.\nOr `build.py --out-dir-legacy x`.\n",
        "docs/build.md": ("# Build\n\nThe input target-dir says where.\n"
                          "The input target-directory is another one.\n"
                          "Issues get needs-triage first.\n"
                          "Nothing else here.\n"),
        "kinds/site/pack.yml": "# Its issues carry needs-triage.\nname: site\n",
    }


def renamed():
    return {
        ".github/workflows/build.yml": FLOW.format(inp="output-dir", flag="--dest"),
        "scripts/build.py": SCRIPT.format(flag="--dest"),
        "labels.yml": LABELS.format(label="awaiting-triage"),
    }


def run_gate(repo, env, mode, *extra):
    return subprocess.run([sys.executable, str(Path(env["DX_CENTRAL"]) / "scripts" / "security-gate.py"), "run", "--mode", mode,
                           "--base", "main", "--json", str(repo / ".git" / "gate.json"), *extra],
                          cwd=repo, env=env, capture_output=True, text=True, timeout=600)


def docs_findings(repo):
    result = json.loads((repo / ".git" / "gate.json").read_text())
    return result, [f for f in result["findings"] if f.get("tool") == "docs"]


def test_c1_a_renamed_input_flag_or_label_names_every_line_that_still_has_the_old_name(tmp_path):
    assert CHECK.is_file(), "scripts/docs-check.py is the documentation check"
    cent = gate.central(tmp_path, "report")
    env = gate.environment(tmp_path, cent)
    repo = gate.scratch(tmp_path, env, None, base_files(), renamed())
    ran = run_gate(repo, env, "report")
    out = ran.stdout + ran.stderr
    assert ran.returncode == 0, out
    result, found = docs_findings(repo)
    stale = {(f["file"], f["line"]) for f in found if f["rule"] == "docs/stale-name"}
    assert stale == {
        ("README.md", 3),                     # --out-dir (not line 4's --out-dir-legacy)
        ("docs/build.md", 3),                 # target-dir (not line 4's target-directory)
        ("docs/build.md", 5),                 # needs-triage
        ("kinds/site/pack.yml", 1),           # needs-triage, in a pack
        (".github/workflows/build.yml", 3),   # target-dir, in the header comment
        (".github/workflows/build.yml", 4),   # --out-dir, in the header comment
    }, found
    for f in found:
        assert f["severity"] == "high" and f["status"] == "new" and f["fingerprint"] and f["fix"], f
    by_line = {(f["file"], f["line"]): f["message"] for f in found}
    assert "target-dir" in by_line[("docs/build.md", 3)] and "input" in by_line[("docs/build.md", 3)]
    assert "--out-dir" in by_line[("README.md", 3)] and "flag" in by_line[("README.md", 3)]
    assert "needs-triage" in by_line[("docs/build.md", 5)] and "label" in by_line[("docs/build.md", 5)]
    # The report names each with its file and line.
    assert "README.md:3 docs/stale-name (docs, new)" in out, out
    assert ".github/workflows/build.yml:3 docs/stale-name (docs, new)" in out, out
    # Nothing that only has the new name.
    assert not any("output-dir" in f["message"] or "--dest" in f["message"] or "awaiting-triage" in f["message"] for f in found)


def test_c1_an_identifier_another_file_still_defines_is_not_removed(tmp_path):
    assert CHECK.is_file(), "scripts/docs-check.py is the documentation check"
    cent = gate.central(tmp_path, "report")
    env = gate.environment(tmp_path, cent)
    files = base_files()
    files["scripts/other.py"] = SCRIPT.format(flag="--out-dir")
    repo = gate.scratch(tmp_path, env, None, files, renamed())
    run_gate(repo, env, "report")
    _, found = docs_findings(repo)
    assert not any("--out-dir" in f["message"] for f in found), found
    assert any("target-dir" in f["message"] for f in found), found
