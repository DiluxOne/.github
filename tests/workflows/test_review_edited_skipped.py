"""#832 C4: an autopilot pull request whose push review was skipped (a
draft at the push, or a cancelled run), then its title is edited: the edit's
run reviews that commit itself, at once, instead of waiting 50 minutes for
a record that never comes and failing; it still waits, and reuses the
verdict, while an older run's review of that commit is queued or in
progress. The conventions check reads the title as GitHub has it now.
claude-review.yml's scope step runs as written, with gh and sleep stood in."""
import json
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FLOWS = ROOT / ".github/workflows"
BOT = "dilux-bot[bot]"
RUN_ID = 5000


def review():
    return yaml.safe_load((FLOWS / "claude-review.yml").read_text(encoding="utf-8"))["jobs"]["review"]


def scope():
    return next(s for s in review()["steps"] if s.get("id") == "scope")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def record(sha):
    rec = {"sha": sha, "count": 1, "risk": "low", "complexity": "low", "blocking": False}
    return {"user": {"login": BOT}, "body": f"<!-- dx-review -->\nSummary\n<!-- dx-review-record {json.dumps(rec)} -->"}


def run_scope(tmp_path, checks, comments_after=None, comments=None):
    """The scope step on an edit of pull request #9. CHECKS: the check runs
    on its head, one list per read (the last one repeats); COMMENTS: the
    bot's comments the step's first read and the wait's first read find,
    COMMENTS_AFTER (or a function of the head) the ones from the wait's
    second read on."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "commit", "-q", "--allow-empty", "-m", "fix: one (C1)")
    reviewed = git(repo, "rev-parse", "HEAD")
    git(repo, "commit", "-q", "--allow-empty", "-m", "chore: ready")
    head = git(repo, "rev-parse", "HEAD")
    comments = comments if comments is not None else [record(reviewed)]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for i, c in enumerate(checks):
        (tmp_path / f"checks{i}.json").write_text(json.dumps({"check_runs": c}))
    (tmp_path / "comments0.json").write_text(json.dumps(comments))
    if callable(comments_after):
        comments_after = comments_after(head)
    (tmp_path / "comments1.json").write_text(json.dumps(comments_after if comments_after is not None else comments))
    log = tmp_path / "calls.log"
    log.write_text("")
    n = len(checks) - 1
    (bin_dir / "gh").write_text(
        "#!/bin/bash\n"
        f'echo "gh $*" >> "{log}"\n'
        f'T="{tmp_path}"\n'
        'case "$*" in\n'
        "  *'pr view'*labels*) echo false ;;\n"
        "  *check-runs*)\n"
        '    c=$(cat "$T/checks.n" 2>/dev/null || echo 0); echo $((c + 1)) > "$T/checks.n"\n'
        f'    [ "$c" -le {n} ] || c={n}\n'
        '    while [ $# -gt 0 ]; do [ "$1" = --jq ] && { shift; q=$1; }; shift; done\n'
        '    jq -r "$q" "$T/checks$c.json" ;;\n'
        "  *'/comments'*)\n"
        '    c=$(cat "$T/comments.n" 2>/dev/null || echo 0); echo $((c + 1)) > "$T/comments.n"\n'
        '    if [ "$c" -le 1 ]; then c=0; else c=1; fi\n'
        '    cat "$T/comments$c.json" ;;\n'
        "esac\n")
    (bin_dir / "gh").chmod(0o755)
    (bin_dir / "sleep").write_text(f'#!/bin/bash\necho "sleep $*" >> "{log}"\n')
    (bin_dir / "sleep").chmod(0o755)
    out = tmp_path / "out"
    out.write_text("")
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", GITHUB_OUTPUT=str(out), GITHUB_REPOSITORY="o/r", RUNNER_TEMP=str(tmp_path),
               GITHUB_RUN_ID=str(RUN_ID), GH_TOKEN="x", BOT=BOT, PR="9", HEAD=head, BASE=base, ACTION="edited", FLOOR="low", MAX_AUTO="5",
               MODEL="m", EFFORT="low")
    r = subprocess.run(["bash", "-c", scope()["run"]], cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
    return r, outputs, log.read_text(), reviewed, head


def check_run(run_id, status="in_progress", name="review / Claude review"):
    return {"name": name, "status": status, "details_url": f"https://github.com/o/r/actions/runs/{run_id}/job/1"}


def test_an_edit_whose_push_review_was_skipped_reviews_the_commit_at_once(tmp_path):
    # No review of the head is running but the edit's own: nothing to wait for.
    r, out, calls, reviewed, head = run_scope(tmp_path, [[check_run(RUN_ID), check_run(4000, "completed")]])
    assert r.returncode == 0, r.stdout + r.stderr
    assert out["mode"] == "incremental" and out["range"] == f"{reviewed}..{head}"
    assert "sleep" not in calls
    assert "within 50 minutes" not in r.stdout + r.stderr and "this edit's run reviews it" in r.stdout


def test_with_no_review_at_all_it_reviews_the_whole_change(tmp_path):
    r, out, calls, _, _ = run_scope(tmp_path, [[]], comments=[])
    assert r.returncode == 0, r.stdout + r.stderr
    assert out["mode"] == "full"
    assert "sleep" not in calls


def test_it_waits_while_an_older_run_reviews_the_head_and_reuses_its_verdict(tmp_path):
    # The push's run (older) is reviewing the head; its record lands while
    # the edit waits, and the edit pays for no second review.
    r, out, calls, _, head = run_scope(tmp_path, [[check_run(4000), check_run(RUN_ID)], [check_run(4000, "completed")]],
                                       comments_after=lambda head: [record(head)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert out["mode"] == "reuse" and out["last"] == head
    assert calls.count("sleep 15") == 1


def test_an_older_run_that_ends_with_no_record_leaves_the_review_to_the_edit(tmp_path):
    # The push's run was cancelled: no record of the head ever comes.
    r, out, calls, reviewed, head = run_scope(tmp_path, [[check_run(4000, "queued")], [check_run(4000)], [check_run(4000, "completed")]])
    assert r.returncode == 0, r.stdout + r.stderr
    assert out["mode"] == "incremental" and out["range"] == f"{reviewed}..{head}"
    assert calls.count("sleep 15") == 2


def test_a_newer_edits_run_is_not_waited_for(tmp_path):
    # Two edits a second apart: the older one does not wait for the newer.
    r, out, calls, _, _ = run_scope(tmp_path, [[check_run(RUN_ID + 1), check_run(RUN_ID)]])
    assert r.returncode == 0, r.stdout + r.stderr
    assert out["mode"] == "incremental" and "sleep" not in calls


def test_the_review_reads_check_runs_with_its_app_token():
    token = next(s for s in review()["steps"] if s.get("id") == "bot")["with"]
    assert token["permission-checks"] == "read"
    run = scope()["run"]
    assert "commits/$HEAD/check-runs" in run
    assert "seq 1 200" not in run and "within 50 minutes" not in run


def test_the_conventions_check_reads_the_title_live():
    job = yaml.safe_load((FLOWS / "conventions.yml").read_text(encoding="utf-8"))["jobs"]["conventions"]
    steps = job["steps"]
    ids = [s.get("id") for s in steps]
    live = steps[ids.index("live")]
    assert 'pulls/$PR" --jq .title' in live["run"]
    assert "::warning::" in live["run"]
    names = [s.get("name") for s in steps]
    gate = names.index("An accepted issue")
    check = names.index("Check branch, title and commits")
    assert ids.index("live") < gate < check
    for i in (gate, check):
        assert steps[i]["env"]["TITLE"] == "${{ steps.live.outputs.title || github.event.pull_request.title }}"
