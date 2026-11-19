"""#549: the autopilot brings main into its branch (workflow wiring)."""
import hashlib
import os
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
JOBS = yaml.safe_load((ROOT / ".github" / "workflows" / "autopilot.yml").read_text(encoding="utf-8"))["jobs"]

MERGE = re.compile(r"\bgit\b[^\n]*\bmerge\b(?!-)")

# A stub logs its name and arguments: a call ends with \x1e, its fields with \x1f.
LOG = 'printf \'%s\\x1f\' "$(basename "$0")" "$@" >> "$CALLS"; printf \'\\x1e\' >> "$CALLS"\n'


def stub(bin_dir, name, body):
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + LOG + body + "\n", encoding="utf-8")
    path.chmod(0o755)


def test_the_work_merges_main_into_the_working_tree_before_the_agent_runs():
    steps = JOBS["work"]["steps"]
    agent = next(i for i, s in enumerate(steps) if s.get("id") == "work")
    before = "\n".join(s.get("run", "") for s in steps[:agent])
    assert MERGE.search(before), "no step merges main before Claude works"


def test_a_reproduced_bugs_draft_starts_from_current_main_with_the_test_on_top(tmp_path):
    step = next(s for s in JOBS["draft"]["steps"] if s.get("id") == "draft")
    script = step["run"]
    test_text = "def test_repro():\n    assert False\n"
    bin_dir, work, temp = tmp_path / "bin", tmp_path / "work", tmp_path / "temp"
    for d in (bin_dir, work, temp):
        d.mkdir()
    (work / ".dx-central").symlink_to(ROOT)
    stub(bin_dir, "gh", """case "$*" in
  *"--json comments"*) echo 0 ;;
  *"--json body"*) echo "the PRD" ;;
  *"--json title"*) echo "fix: the bug" ;;
  "api repos/o/r/issues/9 "*) echo Bug ;;
  "repo view"*) echo main ;;
  "pr create"*) echo https://github.com/o/r/pull/12 ;;
esac""")
    stub(bin_dir, "python3", """case "$*" in
  *"issue-schema.py check"*) echo '{"errors": []}' ;;
  *"autopilot.py draft"*) echo '{"branch": "fix/9-the-bug", "title": "fix: the bug", "body": "b"}' ;;
  *"receipts.py state get"*) echo null ;;
esac""")
    stub(bin_dir, "git", """case "$1" in
  ls-remote) exit 2 ;;
  merge-base) echo base0 ;;
  cat-file) printf %s "$TEST_TEXT" ;;
  rev-parse) echo head0 ;;
esac""")
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "CALLS": str(tmp_path / "calls"), "TEST_TEXT": test_text,
           "GITHUB_REPOSITORY": "o/r", "GITHUB_OUTPUT": str(tmp_path / "out"), "GITHUB_RUN_ID": "77",
           "RUNNER_TEMP": str(temp), "DX_BOT_APP": "dilux-bot", "NUMBER": "9", "STARTED": "2026-11-19T00:00:00Z",
           "LANE": "bugfix-reproduced", "REPRO_TEST": "tests/repro/test_issue_9.py",
           "REPRO_SHA": hashlib.sha256(test_text.encode()).hexdigest(), "REPRO_BRANCH": "repro/9", "DEFAULT": "main",
           "RUN_URL": "https://github.com/o/r/actions/runs/77"}
    done = subprocess.run(["bash", "-c", script], env=env, cwd=work, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    calls = [c.split("\x1f")[:-1] for c in (tmp_path / "calls").read_text(encoding="utf-8").split("\x1e")[:-1]]
    git = [c[1:] for c in calls if c[0] == "git"]
    assert ["checkout", "-q", "-b", "fix/9-the-bug", "origin/main"] in git, "the branch does not start at current main"
    start = git.index(["checkout", "-q", "-b", "fix/9-the-bug", "origin/main"])
    onto_main = [c for c in git[start + 1:] if c[0] in ("cherry-pick", "rebase", "merge")]
    assert onto_main and onto_main[0] == ["cherry-pick", "base0..FETCH_HEAD"], \
        "the reproduction's commits are not brought onto current main: the branch starts at the reproduction's old base"
    pushes = [c for c in calls if c[0] == "python3" and "push" in c]
    assert pushes and pushes[0][-2:] == ["--onto", "origin/main"], "the draft is not pushed onto current main"
    assert "pr=12" in (tmp_path / "out").read_text(encoding="utf-8").splitlines()
