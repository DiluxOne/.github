"""#934 C2, C3: the apply step when the branch moved on GitHub while the agent
worked (the sweep merged main into it, a person pushed). Its `applied` step
replays the agent's own commits on the branch as GitHub has it when they
apply cleanly (C2: pushed on top, nothing refused); when they do not, it
refuses as before, and still posts the agent's question or stop comment on
the pull request (C3: `apply .dx-out/outbox.jsonl +ask,stop`), so nothing the
agent said is lost.

Real git, in a temporary repository: a bare origin, the agent's commits in a
bundle, the branch moved by a merge of main. The engine's helper is a stand-in
that records what the step asks of it."""
import json
import subprocess
from pathlib import Path

import steps

BRANCH = "fix/7-moved"
FAKE = r'''import json, os, subprocess, sys
with open(os.environ["DX_CALLS"], "a") as fh:
    fh.write(json.dumps(["autopilot.py"] + sys.argv[1:]) + "\n")
cmd = sys.argv[1:2]
if cmd == ["ready-goes"]:
    sys.exit(1)
if cmd == ["push"]:
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    with open(os.environ["DX_PUSHED"], "w") as fh:
        fh.write(head)
'''


def git(cwd, *args):
    out = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main",
                          "-c", "commit.gpgsign=false"] + list(args), cwd=cwd, capture_output=True, text=True)
    assert out.returncode == 0, f"git {' '.join(args)}: {out.stderr}"
    return out.stdout.strip()


def commit(cwd, path, text, msg):
    (Path(cwd) / path).write_text(text)
    git(cwd, "add", path)
    git(cwd, "commit", "-q", "-m", msg)


def round_on_moved_branch(tmp_path, conflict, rewrite=False):
    """The agent commits on BRANCH; meanwhile main moves and is merged into
    BRANCH on GitHub (the sweep's update-branch). With CONFLICT, main's change
    and the agent's touch the same line; with REWRITE, the agent also
    rewrote the head it started from."""
    origin, seed, agent, work = (tmp_path / d for d in ("origin.git", "seed", "agent", "work"))
    git(tmp_path, "init", "-q", "--bare", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(seed))
    commit(seed, "a.txt", "one\n", "chore: the start")
    git(seed, "push", "-q", "origin", "HEAD:main")
    git(seed, "checkout", "-q", "-b", BRANCH)
    git(seed, "commit", "-q", "--allow-empty", "-m", "chore(autopilot): start on #7")
    git(seed, "push", "-q", "origin", BRANCH)
    # The agent's round, from the branch as it was.
    git(tmp_path, "clone", "-q", "-b", BRANCH, str(origin), str(agent))
    start = git(agent, "rev-parse", "HEAD")
    if rewrite:
        git(agent, "commit", "-q", "--amend", "--allow-empty", "-m", "chore(autopilot): start on #7, reworded")
    if conflict:
        commit(agent, "a.txt", "agent\n", "fix: the agent's line (C1)")
    else:
        commit(agent, "b.txt", "agent\n", "fix: the agent's file (C1)")
    agent_head = git(agent, "rev-parse", "HEAD")
    (work / ".dx-out").mkdir(parents=True)
    git(agent, "bundle", "create", "-q", str(work / ".dx-out" / "work.bundle"), "HEAD")
    # Meanwhile main moves and the sweep merges it into the branch.
    git(seed, "checkout", "-q", "main")
    if conflict:
        commit(seed, "a.txt", "main\n", "feat: main's line")
    else:
        commit(seed, "c.txt", "main\n", "feat: main's file")
    git(seed, "push", "-q", "origin", "main")
    git(seed, "checkout", "-q", BRANCH)
    git(seed, "merge", "-q", "--no-ff", "-m", "Merge branch 'main' into " + BRANCH, "main")
    git(seed, "push", "-q", "origin", BRANCH)
    moved = git(seed, "rev-parse", "HEAD")
    # The apply job's checkout: GitHub's branch as it is now.
    git(tmp_path, "clone", "-q", str(origin), str(work / "repo"))
    for p in (work / "repo").iterdir():
        p.rename(work / p.name)
    (work / "repo").rmdir()
    (work / ".dx-out" / "outbox.jsonl").write_text(
        json.dumps({"kind": "tick", "id": "C1"}) + "\n" + json.dumps({"kind": "ask", "text": "1 or 2? I recommend 1."}) + "\n")
    s = steps.step("autopilot.yml", "applied", job="apply")
    pushed = tmp_path / "pushed"
    gh = 'case "$*" in\n  *"/commits"*) cat "$DX_PUSHED" 2>/dev/null; echo ;;\nesac\n'
    ran = steps.run(s, tmp_path, central=False, stubs={"gh": gh, "sleep": ""},
                    files={".dx-central/scripts/autopilot.py": FAKE, ".dx-central/scripts/api-commit.py": FAKE},
                    env={"BRANCH": BRANCH, "DEFAULT": "main", "ENGINE": "false", "NUMBER": "7", "PR": "8",
                         "REWORD_OK": "false", "PREPR": "", "GH_TOKEN": "x", "DX_BOT_LOGIN": "dilux-bot[bot]",
                         "DX_BOT_ID": "1", "DX_PUSHED": str(pushed), "START": start, "GIT_CONFIG_GLOBAL": "/dev/null"})
    return ran, work, moved, agent_head, pushed


def test_a_clean_merge_of_main_while_the_agent_worked_is_replayed_on_top(tmp_path):
    ran, work, moved, agent_head, pushed = round_on_moved_branch(tmp_path, conflict=False)
    assert ran.code == 0, ran.stdout + ran.stderr
    assert "refused" not in ran.output and "do not build on" not in ran.stdout
    assert f"{BRANCH} moved on GitHub while the agent worked: its 1 commit(s) are replayed on top." in ran.stdout
    # Pushed: the agent's commit on top of GitHub's moved branch, its message
    # and its change kept, main's merge under it.
    assert ["autopilot.py", "push"] in ran.calls
    head = pushed.read_text().strip()
    assert head and head != agent_head
    assert git(work, "rev-parse", f"{head}^") == moved
    assert git(work, "log", "-1", "--format=%s", head) == "fix: the agent's file (C1)"
    assert git(work, "show", f"{head}:b.txt") == "agent" and git(work, "show", f"{head}:c.txt") == "main"
    # Then the rest of the agent's intents, as on any round.
    assert ["autopilot.py", "apply", ".dx-out/outbox.jsonl"] in ran.calls


def test_commits_that_do_not_apply_are_refused_and_the_question_still_posted(tmp_path):
    ran, work, moved, agent_head, pushed = round_on_moved_branch(tmp_path, conflict=True)
    assert ran.code == 1, ran.stdout + ran.stderr
    assert ran.output.get("refused") == "diverged"
    assert f"The agent's commits do not build on {BRANCH} as GitHub has it: nothing is pushed." in ran.stdout
    assert ["autopilot.py", "push"] not in ran.calls and not pushed.exists()
    # Only the agent's final words, so its question or stop reaches the pull
    # request; no tick against a commit that is not there.
    applies = [c for c in ran.calls if c[:2] == ["autopilot.py", "apply"]]
    assert applies == [["autopilot.py", "apply", ".dx-out/outbox.jsonl", "+ask,stop"]]
    # The repository is left as it was: no rebase in progress.
    assert not (work / ".git" / "rebase-merge").exists() and not (work / ".git" / "rebase-apply").exists()


def test_a_rewrite_of_the_head_it_started_from_is_still_refused(tmp_path):
    # Replayed, it would apply cleanly; but the agent rewrote the branch's
    # history, which only a conventions fix round may do (#699).
    ran, work, moved, agent_head, pushed = round_on_moved_branch(tmp_path, conflict=False, rewrite=True)
    assert ran.code == 1, ran.stdout + ran.stderr
    assert ran.output.get("refused") == "diverged"
    assert ["autopilot.py", "push"] not in ran.calls and not pushed.exists()
