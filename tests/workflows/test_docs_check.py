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


# --- C2: the docs a map ties to a changed path -------------------------------

MAP = "docs-map:\n  - paths: [\"src/**\"]\n    docs: [docs/api.md]\n"


def central_with_kind(tmp_path, mode, kind, pack):
    """The organisation's checkout of gate.central, with one more kind whose
    pack is PACK."""
    cent = gate.central(tmp_path, mode)
    (cent / "kinds").unlink()
    (cent / "kinds").mkdir()
    for entry in (ROOT / "kinds").iterdir():
        (cent / "kinds" / entry.name).symlink_to(entry)
    (cent / "kinds" / kind).mkdir()
    (cent / "kinds" / kind / "pack.yml").write_text(pack, encoding="utf-8")
    return cent


def map_repo(tmp_path, env, own, change, where="repo"):
    files = {"src/a.py": "x = 1\n", "docs/api.md": "# API\n", ".github/review-policy.yml": own}
    return gate.scratch(tmp_path, env, None, files, change, where=where)


def map_findings(repo):
    return [f for f in docs_findings(repo)[1] if f["rule"] == "docs/map"]


def test_c2_a_kinds_map_names_the_docs_to_update_when_none_changed(tmp_path):
    assert CHECK.is_file(), "scripts/docs-check.py is the documentation check"
    cent = central_with_kind(tmp_path, "report", "mapped", "name: mapped\n" + MAP)
    env = gate.environment(tmp_path, cent)
    repo = map_repo(tmp_path, env, "kind: mapped\n", {"src/a.py": "x = 2\n"})
    ran = run_gate(repo, env, "report")
    assert ran.returncode == 0, ran.stdout + ran.stderr
    found = map_findings(repo)
    assert len(found) == 1, found
    f = found[0]
    assert f["file"] == "src/a.py" and "docs/api.md" in f["message"] and f["severity"] == "high" and f["status"] == "new", f
    assert "src/a.py:0 docs/map (docs, new)" in ran.stdout, ran.stdout
    # The same change with the doc edited: nothing.
    again = map_repo(tmp_path, env, "kind: mapped\n", {"src/a.py": "x = 2\n", "docs/api.md": "# API\n\nx is 2.\n"}, where="again")
    run_gate(again, env, "report")
    assert map_findings(again) == []
    # A change to no mapped path: nothing.
    other = map_repo(tmp_path, env, "kind: mapped\n", {"README.md": "y\n"}, where="other")
    run_gate(other, env, "report")
    assert map_findings(other) == []


def test_c2_a_repository_of_no_kind_uses_its_own_map_read_at_the_merge_base(tmp_path):
    assert CHECK.is_file(), "scripts/docs-check.py is the documentation check"
    cent = gate.central(tmp_path, "report")
    env = gate.environment(tmp_path, cent)
    repo = map_repo(tmp_path, env, MAP, {"src/a.py": "x = 2\n"})
    run_gate(repo, env, "report")
    found = map_findings(repo)
    assert [(f["file"], "docs/api.md" in f["message"]) for f in found] == [("src/a.py", True)], found
    # A change that drops its own map entry is still held to it.
    dropped = map_repo(tmp_path, env, MAP, {"src/a.py": "x = 2\n", ".github/review-policy.yml": "docs-map: []\n"}, where="dropped")
    run_gate(dropped, env, "report")
    assert len(map_findings(dropped)) == 1
    edited = map_repo(tmp_path, env, MAP, {"src/a.py": "x = 2\n", "docs/api.md": "# API 2\n"}, where="edited")
    run_gate(edited, env, "report")
    assert map_findings(edited) == []


# --- C3: the description says why no doc needed changing --------------------

def body(what, after=""):
    return f"## 📝 What changes\n\n{what}\n\n## 💡 Why\n\nCloses #1.{after}\n"


def test_c3_docs_none_with_a_why_in_what_changes_passes_the_map_and_the_why_is_in_the_json(tmp_path):
    assert CHECK.is_file(), "scripts/docs-check.py is the documentation check"
    cent = gate.central(tmp_path, "block")
    env = gate.environment(tmp_path, cent)
    repo = map_repo(tmp_path, env, MAP, {"src/a.py": "x = 2\n"})
    good = tmp_path / "good.md"
    good.write_text(body("A refactor of src/a.py.\n\n- Docs: none, the refactor keeps the API"))
    ran = run_gate(repo, env, "block", "--body-file", str(good))
    assert ran.returncode == 0, ran.stdout + ran.stderr
    result, _ = docs_findings(repo)
    assert map_findings(repo) == []
    assert result["docs"]["exempt"] == "the refactor keeps the API"
    assert "(Docs: none): the refactor keeps the API" in ran.stdout, ran.stdout
    # The same through DX_PR_BODY, as `make pre-pr` reads it.
    via_env = subprocess.run([sys.executable, str(cent / "scripts" / "security-gate.py"), "run", "--mode", "block", "--base", "main",
                              "--json", str(repo / ".git" / "gate.json")], cwd=repo, env=dict(env, DX_PR_BODY=str(good)),
                             capture_output=True, text=True, timeout=600)
    assert via_env.returncode == 0 and map_findings(repo) == [], via_env.stdout
    # No why, or the line outside What changes: the map still asks.
    for name, text in (("nowhy.md", body("A refactor.\n\nDocs: none,")),
                       ("outside.md", body("A refactor.", "\n\nDocs: none, the refactor keeps the API")),
                       ("comment.md", body("<!-- Docs: none, the refactor keeps the API -->"))):
        path = tmp_path / name
        path.write_text(text)
        ran = run_gate(repo, env, "block", "--body-file", str(path))
        assert ran.returncode == 1 and len(map_findings(repo)) == 1, (name, ran.stdout)
        assert docs_findings(repo)[0]["docs"]["exempt"] == "", name


def test_c3_docs_none_never_exempts_a_stale_name(tmp_path):
    assert CHECK.is_file(), "scripts/docs-check.py is the documentation check"
    cent = gate.central(tmp_path, "report")
    env = gate.environment(tmp_path, cent)
    repo = gate.scratch(tmp_path, env, None, base_files(), renamed())
    good = tmp_path / "good.md"
    good.write_text(body("Docs: none, nothing to say"))
    run_gate(repo, env, "report", "--body-file", str(good))
    assert any(f["rule"] == "docs/stale-name" for f in docs_findings(repo)[1])


def test_c3_the_pull_requests_check_reads_the_description_through_env_and_a_file(tmp_path):
    assert CHECK.is_file(), "scripts/docs-check.py is the documentation check"
    from steps import run as run_step, step
    cent = gate.central(tmp_path, "block")
    env = gate.environment(tmp_path, cent)
    repo = map_repo(tmp_path, env, MAP, {"src/a.py": "x = 2\n"}, where="wf/work")
    (repo / ".dx-central").symlink_to(cent)
    runner = {k: v for k, v in env.items() if not k.startswith(("GITHUB_", "RUNNER_"))}
    s = step("security-gate.yml", "gate")
    assert "github.event.pull_request.body" in str(s.get("env")) and "pull_request.body" not in s["run"], "the body through env: only"
    told = body('Docs: none, the API stays; "$(touch pwned)"')
    ran = run_step(s, tmp_path / "wf", env=runner, central=False, exprs={"github.event.pull_request.body": told})
    assert ran.code == 0, ran.stdout + ran.stderr
    assert not (repo / "pwned").exists()
    result = json.loads((ran.temp / "security-gate.json").read_text())
    assert result["docs"]["exempt"].startswith("the API stays") and not [f for f in result["findings"] if f["rule"] == "docs/map"]
    silent = run_step(s, tmp_path / "wf", env=runner, central=False, exprs={"github.event.pull_request.body": body("A refactor.")})
    assert silent.code == 1 and "docs/map (docs, new)" in silent.stdout, silent.stdout


def test_c3_autopilot_check_gives_make_pre_pr_the_description_it_writes(tmp_path):
    assert CHECK.is_file(), "scripts/docs-check.py is the documentation check"
    import test_security_gate_attempts as attempts
    cent = gate.central(tmp_path, "block")
    env = gate.environment(tmp_path, cent)
    repo = map_repo(tmp_path, env, MAP, {"src/a.py": "x = 2\n"})
    io = tmp_path / "io"
    io.mkdir()
    (io / "pr.md").write_text(body("A refactor."))
    asked = attempts.helper(repo, env, io, "check")
    assert asked.returncode != 0 and "docs/map (docs, new)" in asked.stdout, asked.stdout + asked.stderr
    (io / "pr.md").write_text(body("A refactor.\n\nDocs: none, the refactor keeps the API"))
    told = attempts.helper(repo, env, io, "check")
    assert told.returncode == 0, told.stdout + told.stderr
    assert "(Docs: none): the refactor keeps the API" in told.stdout


# --- C4: the gate's setting decides, as for a security finding ---------------

def test_c4_report_block_and_off_treat_a_docs_finding_as_the_gate_treats_its_own(tmp_path):
    assert CHECK.is_file(), "scripts/docs-check.py is the documentation check"
    cent = gate.central(tmp_path, "report")
    env = gate.environment(tmp_path, cent)
    repo = gate.scratch(tmp_path, env, None, base_files(), renamed())
    report = run_gate(repo, env, "report")
    assert report.returncode == 0 and "README.md:3 docs/stale-name (docs, new)" in report.stdout, report.stdout
    assert "Documentation check: 6 stale name(s)" in report.stdout, report.stdout
    block = run_gate(repo, env, "block")
    assert block.returncode == 1 and "(it fails the gate)" in block.stdout and "docs/stale-name" in block.stdout, block.stdout
    (repo / ".git" / "gate.json").unlink()
    off = run_gate(repo, env, "off")
    assert off.returncode == 0 and "nothing runs" in off.stdout and "- [" not in off.stdout, off.stdout
    assert not (repo / ".git" / "gate.json").exists()
    # The review's brief says the gate checked the docs, so it does not hunt for them again.
    mod = gate.gate_module()
    text = mod.brief({"mode": "report", "findings": [], "blocking": [], "docs": {"exempt": ""}})
    assert "still name what the change removed or renamed" in text and "docs the map ties to a changed path" in text, text


def test_c4_45_docs_findings_keep_the_30_first_and_15_more_within_8_kb(tmp_path):
    many = [{"tool": "docs", "rule": "docs/stale-name", "file": f"docs/page-{i:02}.md", "line": i + 1, "severity": "high",
             "status": "new", "fingerprint": f"{i:012x}", "message": "Still names the flag --" + "x" * 30 + ", which the change removed.",
             "fix": "Update or remove the mention: " + "y" * 40} for i in range(45)]
    path = tmp_path / "gate.json"
    path.write_text(json.dumps({"mode": "report", "findings": many, "blocking": [], "caps": {"findings": 30, "bytes": 8192},
                                "docs": {"exempt": ""}}))
    out = subprocess.run([sys.executable, str(GATE), "report", str(path)], capture_output=True, text=True, check=True).stdout
    shown = [line for line in out.splitlines() if line.startswith("- [")]
    assert len(out.encode("utf-8")) <= 8192 and len(shown) == 30 and "15 more not shown" in out, out
    assert [re.search(r"page-(\d+)", line).group(1) for line in shown] == [f"{i:02}" for i in range(30)]


def attempts_at_two(tmp_path, env, repo, rule, ap):
    """DX_IO with the marker's count at 2 for the first `new` finding of RULE."""
    run_gate(repo, env, "report")
    result = json.loads((repo / ".git" / "gate.json").read_text())
    f = next(f for f in result["findings"] if f["rule"] == rule and f["status"] == "new")
    io = tmp_path / ("io-" + rule.replace("/", "-"))
    io.mkdir()
    (io / ap.ATTEMPTS).write_text(json.dumps({"counts": {ap.finding_key(f): 2}}))
    return io, f


def test_c4_two_attempts_at_a_docs_finding_then_a_suppression_or_finish_stop_and_push_refuses(tmp_path):
    assert CHECK.is_file(), "scripts/docs-check.py is the documentation check"
    import test_security_gate_attempts as attempts
    ap = attempts.autopilot()
    cent = gate.central(tmp_path, "report")
    env = gate.environment(tmp_path, cent)
    repo = gate.scratch(tmp_path, env, None, base_files(), renamed())
    io, f = attempts_at_two(tmp_path, env, repo, "docs/stale-name", ap)
    third = attempts.helper(repo, env, io, "check")
    out = third.stdout + third.stderr
    assert third.returncode != 0, out
    assert "The gate still finds these after 2 attempts" in out and "The security gate still" not in out, out
    assert ".github/review-suppressions.yml" in out and "finish stop" in out and f"rule: docs/stale-name, file: {f['file']}" in out, out
    pushed = attempts.helper(repo, env, io, "push")
    assert pushed.returncode != 0 and "third attempt" in pushed.stdout, pushed.stdout
    # A docs/map finding's way out also names `Docs: none, <why>` in pr.md.
    mapped = map_repo(tmp_path, env, MAP, {"src/a.py": "x = 2\n"}, where="mapped")
    io2, _ = attempts_at_two(tmp_path, env, mapped, "docs/map", ap)
    again = attempts.helper(mapped, env, io2, "check")
    assert again.returncode != 0 and "finish stop" in again.stdout, again.stdout
    assert "Docs: none, <why>" in again.stdout and "pr.md" in again.stdout, again.stdout
    assert attempts.helper(mapped, env, io2, "push").returncode != 0
