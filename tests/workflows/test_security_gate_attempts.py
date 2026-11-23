"""The autopilot's attempts at a security gate finding (#956 C4): at most 2
at the same finding, then a suppression with its reason or `finish stop`,
never a third. The count carries across runs in the hidden marker of the
autopilot's own `make pre-pr` comment, as the #682 signature does."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_security_gate as gate  # noqa: E402  the scratch repository, the stubs

ROOT = Path(__file__).resolve().parents[2]


def autopilot():
    spec = importlib.util.spec_from_file_location("autopilot_c4", ROOT / "scripts" / "autopilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def helper(repo, env, io, *args):
    """An agent helper command, as the agent runs it (DX_IO set)."""
    full = dict(env, DX_IO=str(io), DX_BASE="main", NUMBER="1", PR="2", BRANCH="feat/1-x")
    return subprocess.run([sys.executable, str(Path(env["DX_CENTRAL"]) / "scripts" / "autopilot.py"), *args], cwd=repo, env=full,
                          capture_output=True, text=True, timeout=600)


def test_c4_two_attempts_then_a_suppression_or_finish_stop_never_a_third(tmp_path):
    assert gate.GATE.is_file(), "scripts/security-gate.py is the gate"
    ap = autopilot()
    assert hasattr(ap, "attempts_of"), "autopilot.py reads the attempts from its marker"
    cent = gate.central(tmp_path, "report")
    env = gate.environment(tmp_path, cent)
    # One new critical finding: a key on the line the change adds.
    repo = gate.scratch(tmp_path, env, None, {"README.md": "x\n"}, {"config.py": gate.CONFIG.splitlines()[0] + "\n"})
    io = tmp_path / "io"
    io.mkdir()
    first = helper(repo, env, io, "check")
    second = helper(repo, env, io, "check")
    assert first.returncode == 0 and second.returncode == 0, first.stdout + second.stdout
    assert "attempt 1 of 2" in first.stdout and "attempt 2 of 2" in second.stdout, first.stdout + second.stdout
    saved = json.loads((io / ap.ATTEMPTS).read_text())
    assert list(saved["counts"].values()) == [2]

    # The next run: the marker of the autopilot's `make pre-pr` comment
    # holds the 2 attempts, and the prep writes them for the agent.
    comment = ap.prepr_comment("fail", "make: *** [dx.mk:5: pre-pr] Error 1", "https://run", True, attempts=saved)
    bot = {"author": {"login": ap.BOT_LOGINS[0]}, "body": comment, "createdAt": "2026-01-02T00:00:00Z"}
    held = ap.attempts_of([bot])
    assert held["counts"] == saved["counts"]
    assert ap.attempts_of([dict(bot, author={"login": "mallory"})]) == {"counts": {}}, "only dilux-bot's marker counts"
    io2 = tmp_path / "io2"
    io2.mkdir()
    (io2 / ap.ATTEMPTS).write_text(json.dumps(held))
    third = helper(repo, env, io2, "check")
    out = third.stdout + third.stderr
    assert third.returncode != 0, out
    assert "2 attempts" in out and ".github/review-suppressions.yml" in out and "finish stop" in out, out
    assert "rule: gitleaks.aws-access-token, file: config.py" in out
    pushed = helper(repo, env, io2, "push")
    assert pushed.returncode != 0 and "third attempt" in pushed.stdout, pushed.stdout
    # Its count does not grow past the limit.
    assert list(json.loads((io2 / ap.ATTEMPTS).read_text())["counts"].values()) == [2]

    # A suppression with its reason clears it.
    result = json.loads((repo / ".git" / "dx-review" / "security-gate.json").read_text())
    new = [f for f in result["findings"] if f["status"] == "new"]
    entries = "".join(f"  - rule: {f['rule']}\n    file: {f['file']}\n    fingerprint: {f['fingerprint']}\n"
                      "    reason: A test key of the fixture, never a real one.\n" for f in new)
    (repo / ".github").mkdir(exist_ok=True)
    (repo / ".github" / "review-suppressions.yml").write_text("suppressions:\n" + entries)
    gate.git(repo, env, "add", "-A")
    gate.git(repo, env, "commit", "-qm", "suppress")
    cleared = helper(repo, env, io2, "check")
    assert cleared.returncode == 0, cleared.stdout + cleared.stderr
    assert "(gitleaks, suppressed)" in cleared.stdout
    assert helper(repo, env, io2, "push").returncode == 0


def test_c4_an_entry_without_a_reason_suppresses_nothing(tmp_path):
    assert gate.GATE.is_file(), "scripts/security-gate.py is the gate"
    cent = gate.central(tmp_path, "block")
    env = gate.environment(tmp_path, cent)
    repo = gate.scratch(tmp_path, env, None, {"README.md": "x\n"}, {"config.py": gate.CONFIG.splitlines()[0] + "\n"})
    ran = gate.pre_pr(repo, env)
    result = json.loads((repo / ".git" / "dx-review" / "security-gate.json").read_text())
    f = next(f for f in result["findings"] if f["status"] == "new")
    (repo / ".github").mkdir(exist_ok=True)
    (repo / ".github" / "review-suppressions.yml").write_text(
        f"suppressions:\n  - rule: {f['rule']}\n    file: {f['file']}\n    fingerprint: {f['fingerprint']}\n    reason: ''\n")
    gate.git(repo, env, "add", "-A")
    gate.git(repo, env, "commit", "-qm", "no reason")
    again = gate.pre_pr(repo, env)
    assert ran.returncode != 0 and again.returncode != 0, again.stdout
    assert "(gitleaks, new)" in again.stdout


def test_c4_the_review_rules_read_a_gate_entry_as_none_of_theirs(tmp_path):
    """review-rules.php reads the same file: a `rule:` entry (no `sniff:`)
    is the gate's, neither an error nor a stale entry of its own."""
    import shutil
    if not shutil.which("php"):
        return
    repo = tmp_path / "plugin"
    (repo / ".github").mkdir(parents=True)
    (repo / ".github" / "review-suppressions.yml").write_text(
        "suppressions:\n  - rule: gitleaks.aws-access-token\n    file: config.py\n    fingerprint: 0123456789ab\n    reason: A fixture's key.\n")
    (repo / "plugin.php").write_text("<?php\n/**\n * Plugin Name: P\n */\n")
    ran = subprocess.run(["php", str(ROOT / "scripts" / "review-rules.php"), "--kind", "wordpress-plugin", "--repo", str(repo)],
                         capture_output=True, text=True, timeout=300)
    out = ran.stdout + ran.stderr
    assert "is missing or empty" not in out and "stale" not in out, out
