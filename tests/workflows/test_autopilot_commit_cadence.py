"""#832 C3: a run that ends at its turn limit after finishing one criterion
leaves that criterion's work on the branch. The work prompt asks for a
commit and a push the moment a criterion's test passes, before anything of
the next one, and "What the agent left" (always()) commits whatever is
still in the working tree, so the bundle the apply job pushes carries it.
The step runs as written, in a throwaway repository, with the engine's
helpers stood in."""
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import autopilot  # noqa: E402
from steps import numbered  # noqa: E402

JOBS = yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))["jobs"]
SUBJECT = "chore(autopilot): work left when the run ended"


def left():
    return next(s for s in JOBS["work"]["steps"] if s.get("id") == "left")


def prompt():
    return autopilot.prompt_work("DiluxOne/site", 7, 9, "fix/7-x", "the PRD", [("C1", "one", "t1.py"), ("C2", "two", "t2.py")], False)


def prompt_lists(p):
    """The prompt's numbered lists, in order: each block of numbered steps."""
    return [items for items in (numbered(block) for block in re.split(r"\n\s*\n", p)) if items]


def test_the_prompt_commits_and_pushes_each_criterion_before_the_next():
    lists = prompt_lists(prompt())
    # Two lists: the steps for each criterion, then the steps once every
    # box is ticked (the review, make pre-pr, the credits, finish).
    assert len(lists) == 2
    per_criterion, at_the_end = lists
    at = lambda items, word: [i for i, item in enumerate(items) if word in item]
    commit, push, tick = at(per_criterion, "Commit it alone"), at(per_criterion, "autopilot.py push"), at(per_criterion, "autopilot.py tick")
    # The commit, then its push, then the tick, each one step, in that
    # order, all inside the loop over the criteria.
    assert len(commit) == len(push) == len(tick) == 1
    assert commit[0] < push[0] < tick[0]
    assert not at(at_the_end, "autopilot.py tick")
    step = per_criterion[commit[0]]
    assert "the moment its test passes" in step
    assert "before you read anything for the next one" in step
    assert "never batch two criteria" in step.lower() or "never two criteria in one commit" in step


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def run_left(tmp_path, engine="false", change=None, outbox=""):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "fix/7-x")
    git(repo, "config", "user.name", "dilux-bot[bot]")
    git(repo, "config", "user.email", "1+dilux-bot[bot]@users.noreply.github.com")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / ".git/info/exclude").write_text("/.dx-central/\n/.dx-io/\n/.dx-out/\n")
    (repo / "app.py").write_text("x = 1\n")
    (repo / ".github/workflows").mkdir(parents=True)
    (repo / ".github/workflows/ci.yml").write_text("on: push\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "chore: start")
    start = git(repo, "rev-parse", "HEAD")
    # C1 committed by the agent; C2's test passed and the turn limit came
    # before its commit.
    (repo / "c1.py").write_text("c1 = True\n")
    git(repo, "add", "c1.py")
    git(repo, "commit", "-q", "-m", "fix: one (C1)")
    (change or (lambda r: ((r / "app.py").write_text("x = 2\n"), (r / "test_c2.py").write_text("def test(): pass\n"))))(repo)
    # The engine's helpers the step calls, stood in.
    (repo / ".dx-central/scripts").mkdir(parents=True)
    (repo / ".dx-central/scripts/autopilot.py").write_text("import sys\nprint('false' if sys.argv[1:] == ['verify', 'need'] else '')\nsys.exit(1 if sys.argv[1:] == ['work-log'] else 0)\n")
    (repo / ".dx-io").mkdir()
    (repo / ".dx-io/outbox.jsonl").write_text(outbox)
    out = tmp_path / "out"
    out.write_text("")
    env = dict(os.environ, START=start, WORK_LOG="", WORK_STARTED="", DX_IO=str(repo / ".dx-io"), GITHUB_OUTPUT=str(out), ENGINE=engine)
    r = subprocess.run(["bash", "-eo", "pipefail", "-c", left()["run"]], cwd=repo, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return repo, start


def bundled(repo, start):
    """The commits the bundle carries, as the apply job reads it."""
    b = repo / ".dx-out/work.bundle"
    assert b.exists()
    heads = git(repo, "bundle", "list-heads", str(b))
    tip = heads.split()[0]
    return git(repo, "log", "--format=%s", f"{start}..{tip}").splitlines(), tip


def test_work_left_uncommitted_goes_on_the_branch(tmp_path):
    repo, start = run_left(tmp_path)
    subjects, tip = bundled(repo, start)
    assert subjects == [SUBJECT, "fix: one (C1)"]
    body = git(repo, "log", "-1", "--format=%B", tip)
    assert autopilot.ASSISTED in body
    # It ticks nothing: no criterion's id in its subject.
    assert "(C" not in subjects[0]
    files = git(repo, "show", "--name-only", "--format=", tip).splitlines()
    assert sorted(files) == ["app.py", "test_c2.py"]
    # The engine's and the run's own files stay out.
    assert not any(f.startswith((".dx-central", ".dx-io", ".dx-out")) for f in files)
    assert git(repo, "status", "--porcelain") == ""


def test_a_workflow_change_outside_the_engine_stays_out(tmp_path):
    def change(r):
        (r / "app.py").write_text("x = 3\n")
        (r / ".github/workflows/ci.yml").write_text("on: pull_request\n")
    repo, start = run_left(tmp_path, change=change)
    _, tip = bundled(repo, start)
    assert git(repo, "show", "--name-only", "--format=", tip).splitlines() == ["app.py"]


def test_the_engine_keeps_its_workflow_change(tmp_path):
    def change(r):
        (r / ".github/workflows/ci.yml").write_text("on: pull_request\n")
    repo, start = run_left(tmp_path, engine="true", change=change)
    _, tip = bundled(repo, start)
    assert git(repo, "show", "--name-only", "--format=", tip).splitlines() == [".github/workflows/ci.yml"]


def test_nothing_left_is_no_commit(tmp_path):
    repo, start = run_left(tmp_path, change=lambda r: None)
    subjects, _ = bundled(repo, start)
    assert subjects == ["fix: one (C1)"]


def test_the_step_knows_the_engine():
    assert "github.repository" in str(left()["env"].get("ENGINE", ""))


def test_notes_left_after_the_agent_reached_its_end_stay_out(tmp_path):
    # It wrote the credits and finished: a file left then is its own notes.
    def change(r):
        (r / "tested.md").write_text("How I tested it\n")
    for i, outbox in enumerate(('{"kind": "tick", "id": "C1"}\n{"kind": "credits", "text": ""}\n', '{"kind": "stop", "text": "x"}\n')):
        (tmp_path / str(i)).mkdir()
        repo, start = run_left(tmp_path / str(i), change=change, outbox=outbox)
        subjects, _ = bundled(repo, start)
        assert subjects == ["fix: one (C1)"]


def test_a_tick_alone_is_not_the_end(tmp_path):
    repo, start = run_left(tmp_path, outbox='{"kind": "tick", "id": "C1"}\n')
    subjects, _ = bundled(repo, start)
    assert subjects[0] == SUBJECT
