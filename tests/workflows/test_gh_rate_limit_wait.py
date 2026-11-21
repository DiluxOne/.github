"""#925 C1: a run that hits the App's rate limit waits for its reset and
tries again, instead of failing. scripts/gh-wait.sh is the `gh` every job
of the autopilot, the review, its replies and the release lane puts first
on its PATH: on GitHub's rate-limit answer it reads `gh api rate_limit`,
sleeps until the reset and runs the same command again, with the same
stdin; a reset after the job's deadline (`DX_RATE_DEADLINE`) fails at once,
naming the reset. The `gh` behind it is a fake that records its calls."""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts" / "gh-wait.sh"
LIMITED = "gh: API rate limit already exceeded for installation ID 164273842. (HTTP 403)"

# The fake `gh`: `api rate_limit` gives the reset in $RESET; any other call
# is recorded with its stdin (when it reads one) and fails with the
# rate-limit answer the first $FAILS times, then prints "ok".
FAKE = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if args[:2] == ["api", "rate_limit"]:
    reset = int(os.environ["RESET"])
    print(json.dumps({"resources": {"core": {"limit": 5000, "remaining": 0, "reset": reset},
                                    "graphql": {"limit": 5000, "remaining": 12, "reset": reset + 900}}}))
    sys.exit(0)
log = os.environ["DX_CALLS"]
stdin = sys.stdin.read() if ("-" in args or any(a.endswith(("@-", "=-")) for a in args)) else None
calls = [json.loads(l) for l in open(log)] if os.path.exists(log) else []
with open(log, "a") as f:
    f.write(json.dumps({"args": args, "stdin": stdin}) + "\n")
if len(calls) < int(os.environ.get("FAILS", "1")):
    print('{"message": "API rate limit already exceeded for installation ID 164273842."}')
    print(os.environ["LIMITED"], file=sys.stderr)
    sys.exit(1)
print("ok")
"""


def fake_gh(tmp_path):
    bin_ = tmp_path / "fake"
    bin_.mkdir(exist_ok=True)
    (bin_ / "gh").write_text(FAKE)
    (bin_ / "gh").chmod(0o755)
    return bin_


def env_for(tmp_path, front, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DX_RATE", "GITHUB_"))}
    env.update({"PATH": f"{front}:{fake_gh(tmp_path)}:{os.environ['PATH']}", "DX_CALLS": str(tmp_path / "calls.jsonl"),
                "LIMITED": LIMITED, "DX_RATE_SLACK": "0"})
    env.update({k: str(v) for k, v in extra.items()})
    return env


def calls(tmp_path):
    log = tmp_path / "calls.jsonl"
    return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []


def test_it_waits_for_the_reset_and_runs_the_same_command_again_with_its_stdin(tmp_path):
    env = env_for(tmp_path, tmp_path, RESET=int(time.time()) + 2, DX_RATE_DEADLINE=int(time.time()) + 600)
    started = time.time()
    ran = subprocess.run(["bash", str(WRAPPER), "api", "repos/o/r/issues/1/comments", "--input", "-"],
                         input="the comment's body\n", capture_output=True, text=True, env=env, timeout=60)
    took = time.time() - started
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "ok\n"
    got = calls(tmp_path)
    assert [c["args"] for c in got] == [["api", "repos/o/r/issues/1/comments", "--input", "-"]] * 2
    assert [c["stdin"] for c in got] == ["the comment's body\n"] * 2
    assert took >= 1, f"it did not wait for the reset ({took:.1f} s)"
    assert "rate limit" in ran.stderr and "waits" in ran.stderr


def test_a_reset_after_the_deadline_fails_at_once_naming_it(tmp_path):
    reset = int(time.time()) + 1800
    env = env_for(tmp_path, tmp_path, RESET=reset, DX_RATE_DEADLINE=int(time.time()) + 60)
    started = time.time()
    ran = subprocess.run(["bash", str(WRAPPER), "pr", "view", "9", "--json", "headRefOid"],
                         capture_output=True, text=True, env=env, timeout=30)
    assert ran.returncode != 0
    assert time.time() - started < 10
    when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(reset))
    assert f"::error::GitHub's API rate limit for the App resets at {when}, after this job's time: left for the next run" in ran.stderr
    assert len(calls(tmp_path)) == 1


def test_any_other_failure_is_gh_s_own_at_once(tmp_path):
    bin_ = tmp_path / "fake404"
    bin_.mkdir()
    (bin_ / "gh").write_text("#!/usr/bin/env bash\necho '{\"message\": \"Not Found\"}'\necho 'gh: Not Found (HTTP 404)' >&2\nexit 4\n")
    (bin_ / "gh").chmod(0o755)
    env = env_for(tmp_path, bin_)
    env["PATH"] = f"{bin_}:{os.environ['PATH']}"
    ran = subprocess.run(["bash", str(WRAPPER), "api", "repos/o/r/nothing"], capture_output=True, text=True, env=env, timeout=30)
    assert (ran.returncode, ran.stdout, ran.stderr) == (4, '{"message": "Not Found"}\n', "gh: Not Found (HTTP 404)\n")


def test_installed_it_is_the_gh_on_path_and_the_deadline_is_the_job_s(tmp_path):
    gh_path, gh_env, temp = tmp_path / "path", tmp_path / "env", tmp_path / "temp"
    temp.mkdir()
    env = env_for(tmp_path, tmp_path, GITHUB_PATH=gh_path, GITHUB_ENV=gh_env, RUNNER_TEMP=temp)
    now = int(time.time())
    ran = subprocess.run(["bash", str(WRAPPER), "--install", "15"], capture_output=True, text=True, env=env, timeout=30)
    assert ran.returncode == 0, ran.stderr
    front = gh_path.read_text().strip()
    assert front.startswith(str(temp)), "outside the workspace, so a later checkout cannot remove it"
    values = dict(l.split("=", 1) for l in gh_env.read_text().splitlines())
    assert abs(int(values["DX_RATE_DEADLINE"]) - (now + 15 * 60 - 180)) <= 5
    # On PATH before the real one, it finds that one and does not call itself.
    env = env_for(tmp_path, front, RESET=int(time.time()) + 1, DX_RATE_DEADLINE=int(time.time()) + 600, FAILS=0)
    ran = subprocess.run(["gh", "issue", "view", "1"], capture_output=True, text=True, env=env, timeout=30)
    assert (ran.returncode, ran.stdout) == (0, "ok\n"), ran.stderr


# The wiring: every job of these workflows installs it before its first
# step that runs `gh` or a script that does, with the job's own timeout.
WORKFLOWS = ("autopilot.yml", "claude-review.yml", "review-reply.yml", "release-lane.yml")
# config-overlay.sh calls no API, and runs where the scripts are cloned.
CALLS_GH = re.compile(r"(^|[\s(|;&`$])gh\s|scripts/(?!config-overlay\.sh|gh-wait\.sh)[\w.-]+\.(py|sh)")


def install_step(s):
    return bool(re.search(r'gh-wait\.sh"? --install', str(s.get("run") or "")))


def test_every_job_puts_the_waiting_gh_on_path_before_its_first_gh():
    missing = []
    for name in WORKFLOWS:
        wf = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())
        for job_id, job in wf["jobs"].items():
            steps = job.get("steps") or []
            first = next((i for i, s in enumerate(steps) if CALLS_GH.search(str(s.get("run") or "")) and not install_step(s)), None)
            if first is None:
                continue
            installs = [i for i, s in enumerate(steps) if install_step(s)]
            if not installs or installs[0] > first:
                missing.append(f"{name} {job_id}: step {first} ({steps[first].get('name')}) runs gh first")
                continue
            s = steps[installs[0]]
            if CALLS_GH.search(str(s.get("run"))):
                missing.append(f"{name} {job_id}: its install step calls gh itself, before its PATH holds the wrapper")
            timeout = str((s.get("env") or {}).get("TIMEOUT", ""))
            if timeout != str(job.get("timeout-minutes")):
                missing.append(f"{name} {job_id}: its TIMEOUT {timeout!r} is not the job's {job.get('timeout-minutes')!r}")
    assert not missing, "\n".join(missing)


def test_the_scripts_job_runs_its_own_test():
    text = (ROOT / ".github" / "workflows" / "pull-request.yml").read_text()
    assert "bash scripts/gh-wait.sh --test" in text
    ran = subprocess.run(["bash", str(WRAPPER), "--test"], capture_output=True, text=True, timeout=120)
    assert ran.returncode == 0, ran.stdout + ran.stderr


def test_the_sweep_continues_an_issue_left_to_the_rate_limit_once_it_reset():
    """The run that could not wait wrote `rate_limited` on its issue's
    board (its `rate-limited` job, after the reset): the hourly sweep asks the continue once the reset passed."""
    def sweep(board, labels=""):
        ran = subprocess.run([sys.executable, str(ROOT / "scripts" / "autopilot.py"), "sweep", "rate-limited"], input=json.dumps(board),
                             capture_output=True, text=True, env={**os.environ, "LABELS": labels}, timeout=30)
        assert ran.returncode == 0, ran.stderr
        return "continue" if ran.stdout.startswith("continue\t") else ran.stdout
    now = int(time.time())
    assert sweep({"rate_limited": now - 60}) == "continue"
    assert sweep({"rate_limited": now + 600}) != "continue"
    assert sweep({"rate_limited": now - 60}, "accepted,autopilot:continue") != "continue"
    assert sweep({}) != "continue"
    text = (ROOT / ".github" / "workflows" / "autopilot-sweep.yml").read_text()
    assert "autopilot.py sweep rate-limited" in text


def test_giving_up_notes_the_reset_with_no_api_call(tmp_path):
    """The limit is spent when it gives up, so a board write then would fail
    with the same answer: it notes the reset in DX_RATE_NOTE, a file, and
    makes no call but the one that failed (no receipts.py, no gh)."""
    reset = int(time.time()) + 1800
    note = tmp_path / "rate-limited"
    env = env_for(tmp_path, tmp_path, RESET=reset, FAILS=99, DX_RATE_DEADLINE=int(time.time()) + 60, DX_RATE_NOTE=note)
    ran = subprocess.run(["bash", str(WRAPPER), "issue", "view", "9"], capture_output=True, text=True, env=env, timeout=30)
    assert ran.returncode == 1
    assert note.read_text().strip() == str(reset)
    assert len(calls(tmp_path)) == 1, "only the call that met the limit: nothing tries to write while it is spent"


def test_until_sleeps_to_the_reset_at_most_its_bound(tmp_path):
    env = {**os.environ, "DX_RATE_SLACK": "0"}
    started = time.time()
    ran = subprocess.run(["bash", str(WRAPPER), "--until", str(int(time.time()) + 2)], capture_output=True, text=True, env=env, timeout=30)
    assert ran.returncode == 0 and time.time() - started >= 1
    ran = subprocess.run(["bash", str(WRAPPER), "--until", str(int(time.time()) + 3600)], capture_output=True, text=True,
                         env={**env, "DX_RATE_UNTIL_MAX": "1"}, timeout=30)
    assert ran.returncode == 0 and "waits 1 s" in ran.stdout


def test_the_board_is_written_after_the_reset_by_its_own_job():
    """#925 C1's recovery: every autopilot job reads the note into its
    `rate-limited` output, even when it failed; the `rate-limited` job needs
    them all, sleeps until the latest reset before any API call (its token
    too), and only then writes `rate_limited` on the issue's board."""
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "autopilot.yml").read_text())
    jobs = wf["jobs"]
    noting = [j for j, job in jobs.items() if j != "rate-limited" and any(install_step(s) for s in job.get("steps") or []) and j != "where"]
    assert set(noting) == {"prep", "spec", "draft", "work", "verify", "apply"}
    for j in noting:
        steps = jobs[j]["steps"]
        rate = [s for s in steps if s.get("id") == "rate"]
        assert rate and rate[0].get("if") == "always()" and steps[-1] is rate[0], f"{j}: its note is read last, always"
        assert "DX_RATE_NOTE" in rate[0]["run"]
        assert jobs[j]["outputs"]["rate-limited"] == "${{ steps.rate.outputs.reset }}", j
    rl = jobs["rate-limited"]
    assert set(rl["needs"]) == set(noting)
    assert rl["if"].startswith("${{ always()")
    steps = rl["steps"]
    names = [s.get("id") or s.get("name") for s in steps]
    until = next(i for i, s in enumerate(steps) if "gh-wait.sh --until" in str(s.get("run")))
    token = next(i for i, s in enumerate(steps) if "create-github-app-token" in str(s.get("uses")))
    write = next(i for i, s in enumerate(steps) if "receipts.py state set" in str(s.get("run")))
    assert until < token < write, names
    assert not any(CALLS_GH.search(str(s.get("run") or "")) for s in steps[:until + 1]), "no API call before the reset"
    for j in noting:
        assert f"needs.{j}.outputs.rate-limited" in steps[until]["env"]["RESETS"], j
        assert f"needs.{j}.outputs.rate-limited" in rl["if"], j
    assert "rate_limited=$AT" in steps[write]["run"]
    perms = steps[token]["with"]
    assert perms.get("permission-contents") == "read", "state set reads the receipts branch"
    assert perms.get("permission-pull-requests") == "read", "the board keeps the autopilot's pull request row"


def test_every_token_that_writes_a_board_can_read_the_receipts_branch():
    """#926's review: `receipts.py state set` reads the receipts branch
    (contents API) before it writes the board, so a token minted for it with
    `permission-*` inputs and no `permission-contents` gets a 403 on a private
    repository and the board is never written."""
    checked = 0
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        wf = yaml.safe_load(path.read_text())
        for name, job in (wf.get("jobs") or {}).items():
            steps = job.get("steps") or []
            tokens = {s["id"]: s for s in steps if s.get("id") and "create-github-app-token" in str(s.get("uses"))}
            for s in steps:
                if "receipts.py state set" not in str(s.get("run") or ""):
                    continue
                m = re.search(r"steps\.([\w-]+)\.outputs\.token", str((s.get("env") or {}).get("GH_TOKEN")))
                if not m or m.group(1) not in tokens:
                    continue
                inputs = tokens[m.group(1)].get("with") or {}
                if not any(k.startswith("permission-") for k in inputs):
                    continue  # the App's whole installation
                checked += 1
                assert inputs.get("permission-contents") in ("read", "write"), f"{path.name}:{name}: {s.get('name')}"
    assert checked
