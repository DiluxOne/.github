"""The security gate (#956, scripts/security-gate.py): one deterministic
check of leaked secrets, insecure code, vulnerable dependencies and unsafe
workflows, the same in `make pre-pr` (the rendered dx.mk) as in the pull
request's check, for a repository of any kind or of none.

The tools are stubs that print the outputs the pinned tools recorded
(tests/workflows/fixtures/security-gate/), for the files they are given,
and log their calls: no network is needed."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from steps import run as run_step, step  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts" / "security-gate.py"
FIXTURES = ROOT / "tests" / "workflows" / "fixtures" / "security-gate"
KINDS = [None] + sorted(p.parent.name for p in (ROOT / "kinds").glob("*/pack.yml"))

# The change: the same files the recorded outputs were taken from. The
# secrets are put together here, so this file holds none.
APP = ("import os\nimport subprocess\n\ndef handler(request):\n    cmd = request.args.get(\"cmd\")\n"
       "    subprocess.call(cmd, shell=True)\n    return eval(request.args.get(\"x\"))\n")
CONFIG = ("AWS_ACCESS_KEY_ID = \"" + "AKIA" + "Z4QW7RTXN2KD5H3P\"\n"
          "GITHUB_TOKEN = \"" + "ghp_" + "8kJf2Lq9ZxWm4TnR7vBc1YpHs3Gd6Ae0UoIl\"\n")
WORKFLOW = ("name: ci\non: pull_request_target\njobs:\n  t:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: echo \"${{ github.event.pull_request.title }}\"\n")
CHANGE = {"app.py": APP, "config.py": CONFIG, ".github/workflows/ci.yml": WORKFLOW,
          "package-lock.json": (FIXTURES / "package-lock.json").read_text() if (FIXTURES / "package-lock.json").exists() else ""}

# Each stub logs its argv to $DX_GATE_CALLS, then prints what its tool
# recorded for the files it was given (none for a file it was not).
STUB = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["DX_GATE_CALLS"], "a") as fh:
    fh.write(json.dumps([{name!r}] + args) + "\\n")
fixtures = {fixtures!r}
def load(name):
    return json.load(open(os.path.join(fixtures, name)))
name = {name!r}
if name == "gitleaks":
    root = args[-1]
    out = [dict(f, File=os.path.join(root, f["File"])) for f in load("gitleaks.json") if os.path.isfile(os.path.join(root, f["File"]))]
    json.dump(out, open(args[args.index("--report-path") + 1], "w"))
elif name == "semgrep":
    data = load("semgrep.json")
    data["results"] = [r for r in data["results"] if os.path.isfile(r["path"])]
    print(json.dumps(data))
elif name == "zizmor":
    files = set(a for a in args if not a.startswith("-") and a != "json")
    out = [f for f in load("zizmor.json") if any(l["symbolic"]["key"]["Local"]["verbatim_path"] in files for l in f["locations"])]
    print(json.dumps(out))
    sys.exit(14 if out else 0)
elif name == "osv-scanner":
    results = []
    for i, a in enumerate(args):
        if a == "-L" and "1.2.5" in open(args[i + 1]).read():
            for r in load("osv-scanner.json")["results"]:
                results.append(dict(r, source=dict(r["source"], path=args[i + 1])))
    print(json.dumps({{"results": results}}))
    sys.exit(1 if results else 0)
"""


def central(tmp_path, mode):
    """A checkout of the organisation's repository whose org.yml says
    `security-gate: MODE`: this one, linked, but for org.yml."""
    c = tmp_path / "central"
    c.mkdir()
    for entry in ROOT.iterdir():
        if entry.name not in ("org.yml", ".git"):
            (c / entry.name).symlink_to(entry)
    org = (ROOT / "org.yml").read_text(encoding="utf-8")
    lines = [line for line in org.splitlines() if not line.startswith("security-gate:")]
    (c / "org.yml").write_text("\n".join(lines) + f"\nsecurity-gate: {mode}\n", encoding="utf-8")
    return c


def environment(tmp_path, cent):
    """The environment `make pre-pr` runs in: the stubs installed where
    `install` puts the pinned tools (so it downloads nothing), a log of
    their calls, and no-op stand-ins for a kind's own tools."""
    cache = tmp_path / "cache"
    env = dict(os.environ, XDG_CACHE_HOME=str(cache), DX_CENTRAL=str(cent), DX_GATE_CALLS=str(tmp_path / "calls.jsonl"),
               GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")
    where = subprocess.run([sys.executable, str(cent / "scripts" / "security-gate.py"), "where"], env=env,
                           capture_output=True, text=True, check=True).stdout.strip()
    bin_dir = Path(where) / "bin"
    bin_dir.mkdir(parents=True)
    for name in ("gitleaks", "semgrep", "osv-scanner", "zizmor"):
        stub = bin_dir / name
        stub.write_text(STUB.format(name=name, fixtures=str(FIXTURES)), encoding="utf-8")
        stub.chmod(0o755)
    digest = Path(where).name
    (Path(where) / "installed").write_text(digest + "\n")
    others = tmp_path / "others"
    others.mkdir()
    for name in ("composer", "npm", "npx", "php"):
        (others / name).write_text("#!/bin/sh\nexit 0\n")
        (others / name).chmod(0o755)
    env["PATH"] = f"{others}{os.pathsep}{env['PATH']}"
    (tmp_path / "calls.jsonl").write_text("")
    return env


def git(repo, env, *args):
    return subprocess.run(["git", "-C", str(repo), *args], env=env, capture_output=True, text=True, check=True).stdout


def scratch(tmp_path, env, kind, base_files, change, where="repo"):
    """A repository of KIND (None: of no kind) on a branch off main: BASE_FILES
    committed on main, CHANGE committed on the branch, and the dx.mk
    `pre-pr.py render` writes for it, with the Makefile that includes it."""
    repo = tmp_path / where
    repo.mkdir(parents=True)
    git(repo, env, "init", "-q", "-b", "main")
    files = dict(base_files)
    if kind:
        files[".github/review-policy.yml"] = f"kind: {kind}\n"
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    render = subprocess.run([sys.executable, str(Path(env["DX_CENTRAL"]) / "scripts" / "pre-pr.py"), "render"] + ([kind] if kind else []),
                            env=env, capture_output=True, text=True)
    assert render.returncode == 0, render.stderr
    (repo / "dx.mk").write_text(render.stdout, encoding="utf-8")
    (repo / "Makefile").write_text("include dx.mk\n", encoding="utf-8")
    git(repo, env, "add", "-A")
    git(repo, env, "commit", "-qm", "base")
    git(repo, env, "checkout", "-qb", "feat/1-x")
    for rel, text in change.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    git(repo, env, "add", "-A")
    git(repo, env, "commit", "-qm", "change")
    return repo


def pre_pr(repo, env):
    env = dict(env, DX_BASE="main")
    return subprocess.run(["make", "-s", "pre-pr"], cwd=repo, env=env, capture_output=True, text=True, timeout=600)


def calls(tmp_path):
    return [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines() if line.strip()]


def test_the_gate_exists_with_its_policy_and_recorded_outputs():
    assert GATE.is_file(), "scripts/security-gate.py is the gate"
    assert (ROOT / "policy" / "security-gate.yml").is_file()
    for name in ("gitleaks", "semgrep", "osv-scanner", "zizmor"):
        assert (FIXTURES / f"{name}.json").is_file()


@pytest.mark.parametrize("kind", KINDS, ids=[k or "no-kind" for k in KINDS])
def test_c1_make_pre_pr_names_each_finding_with_its_file_line_rule_and_fix(tmp_path, kind):
    assert GATE.is_file(), "scripts/security-gate.py is the gate"
    cent = central(tmp_path, "report")
    env = environment(tmp_path, cent)
    repo = scratch(tmp_path, env, kind, {"README.md": "x\n"}, CHANGE)
    ran = pre_pr(repo, env)
    out = ran.stdout + ran.stderr
    assert "Security gate (report)" in out, out
    # A leaked secret, with no secret in the output.
    assert "config.py:1 gitleaks.aws-access-token (gitleaks, new)" in out
    assert "ghp_" not in out and "AKIA" not in out
    # An OWASP Top 10 pattern of high severity.
    assert "[high] app.py:6 python.lang.security.audit.subprocess-shell-true (semgrep, new)" in out
    # A dependency with a known critical vulnerability, and its fix.
    assert "[critical] package-lock.json:" in out and "GHSA-xvch-5gv4-984h (osv-scanner, new)" in out
    assert "Fix: Upgrade minimist to" in out
    # An untrusted value inside `run:`.
    assert ".github/workflows/ci.yml:7 zizmor.template-injection (zizmor, new)" in out
    assert "Fix: Pass the value through env:" in out
    # Each finding says how to fix it.
    findings = [line for line in out.splitlines() if line.startswith("- [")]
    assert len(findings) >= 4
    assert out.count(" Fix: ") == len(findings)
    if kind is None:
        assert ran.returncode == 0, out


def test_c2_a_finding_on_a_line_the_change_did_not_touch_is_pre_existing_and_never_fails(tmp_path):
    assert GATE.is_file(), "scripts/security-gate.py is the gate"
    cent = central(tmp_path, "block")
    env = environment(tmp_path, cent)
    # app.py's subprocess and eval lines are on main already; the change
    # adds a line at its end, so the file is read, those lines are not new.
    repo = scratch(tmp_path, env, None, {"app.py": APP}, {"app.py": APP + "# the end\n"})
    ran = pre_pr(repo, env)
    out = ran.stdout + ran.stderr
    assert "[high] app.py:6 python.lang.security.audit.subprocess-shell-true (semgrep, pre-existing)" in out, out
    assert "(semgrep, new)" not in out
    assert "Security gate (block): 0 new" in out, out
    assert ran.returncode == 0, out
    result = json.loads((repo / ".git" / "dx-review" / "security-gate.json").read_text())
    assert {f["status"] for f in result["findings"]} == {"pre-existing"} and result["blocking"] == []
    # The same finding on a line the change adds fails it under `block`.
    git(repo, env, "checkout", "-q", "main")
    git(repo, env, "rm", "-q", "app.py")
    git(repo, env, "commit", "-qm", "no app")
    git(repo, env, "checkout", "-qb", "feat/2-y")
    (repo / "app.py").write_text(APP)
    git(repo, env, "add", "-A")
    git(repo, env, "commit", "-qm", "app")
    again = pre_pr(repo, env)
    assert "(semgrep, new)" in again.stdout and again.returncode != 0, again.stdout + again.stderr


@pytest.mark.parametrize("mode", ["report", "block", "off"])
def test_c3_the_setting_decides_in_make_pre_pr_and_in_the_pull_requests_check(tmp_path, mode):
    assert GATE.is_file(), "scripts/security-gate.py is the gate"
    assert (ROOT / ".github" / "workflows" / "security-gate.yml").is_file(), "security-gate.yml is the pull request's check"
    cent = central(tmp_path, mode)
    env = environment(tmp_path, cent)
    repo = scratch(tmp_path, env, None, {"README.md": "x\n"}, CHANGE, where="wf/work")
    made = pre_pr(repo, env)
    (repo / ".dx-central").symlink_to(cent)
    runner = {k: v for k, v in env.items() if not k.startswith(("GITHUB_", "RUNNER_"))}
    checked = run_step(step("security-gate.yml", "gate"), tmp_path / "wf", env=runner, central=False)
    for name, code, out in (("make pre-pr", made.returncode, made.stdout + made.stderr),
                            ("the check", checked.code, checked.stdout + checked.stderr)):
        if mode == "off":
            assert code == 0 and "Security gate: off" in out, (name, out)
            assert "- [" not in out
        elif mode == "report":
            assert code == 0, (name, out)
            assert "[critical] config.py:1 gitleaks.aws-access-token (gitleaks, new)" in out, (name, out)
        else:
            assert code != 0, (name, out)
            assert "(it fails the gate)" in out and "[high] app.py:6" in out, (name, out)
    if mode == "off":
        assert calls(tmp_path) == [], "under off no tool is called"
    else:
        assert {c[0] for c in calls(tmp_path)} == {"gitleaks", "semgrep", "osv-scanner", "zizmor"}
        # The check's report reaches the job summary too.
        assert "Security gate (" + mode + ")" in (tmp_path / "wf" / "summary").read_text()


def recorded_findings():
    """The four tools' recorded findings, read as the gate reads them."""
    spec = __import__("importlib.util").util.spec_from_file_location("security_gate_c5", GATE)
    mod = __import__("importlib.util").util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sev = mod.load_policy()["severities"]
    load = lambda name: json.loads((FIXTURES / f"{name}.json").read_text())  # noqa: E731
    return mod, (mod.from_gitleaks(load("gitleaks"), sev["gitleaks"]) + mod.from_semgrep(load("semgrep"), sev["semgrep"])
                 + mod.from_osv(load("osv-scanner"), sev["osv-scanner"]) + mod.from_zizmor(load("zizmor"), sev["zizmor"]))


def test_c5_more_than_30_findings_give_the_30_most_severe_and_the_count_of_the_rest_within_8_kb(tmp_path):
    assert GATE.is_file(), "scripts/security-gate.py is the gate"
    mod, recorded = recorded_findings()
    assert {f["severity"] for f in recorded} >= {"critical", "high", "medium"}
    # 45 findings: the recorded ones, again and again on further lines.
    many = []
    for i in range(45):
        f = dict(recorded[i % len(recorded)])
        f.update(line=f["line"] + 100 * (i // len(recorded)), status="new", fingerprint=f"{i:012x}")
        many.append(f)
    path = tmp_path / "security-gate.json"
    path.write_text(json.dumps({"mode": "report", "findings": many, "blocking": [], "caps": {"findings": 30, "bytes": 8192}}))
    out = subprocess.run([sys.executable, str(GATE), "report", str(path)], capture_output=True, text=True, check=True).stdout
    assert len(out.encode("utf-8")) <= 8192, len(out.encode("utf-8"))
    shown = [line for line in out.splitlines() if line.startswith("- [")]
    assert len(shown) == 30, out
    assert "15 more not shown" in out
    rank = ["critical", "high", "medium", "low"]
    levels = [rank.index(re.match(r"- \[(\w+)\]", line).group(1)) for line in shown]
    assert levels == sorted(levels), "the most severe first"
    every = sorted(rank.index(f["severity"]) for f in many)
    assert levels == every[:30], "the 30 most severe"
    # Each one shown still names its file, line, rule and fix.
    assert out.count(" Fix: ") == 30
    # Whatever their size, the report stays within 8 KB and says how many more.
    huge = [dict(f, message="m" * 5000, fix="f" * 5000, rule="r" * 400) for f in many]
    path.write_text(json.dumps({"mode": "block", "findings": huge, "blocking": [], "caps": {"findings": 30, "bytes": 8192}}))
    big = subprocess.run([sys.executable, str(GATE), "report", str(path)], capture_output=True, text=True, check=True).stdout
    kept = sum(1 for line in big.splitlines() if line.startswith("- ["))
    assert len(big.encode("utf-8")) <= 8192 and f"{45 - kept} more not shown" in big
