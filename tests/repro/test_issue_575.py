"""#575: a delegated lane's sub-issue that has no seal (its repository ran
nothing when dilux-bot opened it) is sealed by the may-it-run step, not sent
back to a maintainer to be accepted again."""
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REFUSAL = "the issue's PRD is not the one sealed when it was accepted"

# A stub logs its name and arguments: a call ends with \x1e, its fields with \x1f.
LOG = 'printf \'%s\\x1f\' "$(basename "$0")" "$@" >> "$CALLS"; printf \'\\x1e\' >> "$CALLS"\n'


def may_it_run_step():
    wf = yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))
    steps = [step for job in wf["jobs"].values() for step in job.get("steps", [])
             if "receipts.py verify-prd" in step.get("run", "")]
    assert len(steps) == 1
    return steps[0]


def stub(bin_dir, name, body):
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + LOG + body + "\n", encoding="utf-8")
    path.chmod(0o755)


def run_may(tmp_path, lane):
    """The may-it-run step on a start of an unsealed issue of LANE: the
    seal reads `unsealed` until receipts.py seal-prd writes it."""
    script = may_it_run_step()["run"]
    bin_dir, work, temp = tmp_path / "bin", tmp_path / "work", tmp_path / "temp"
    for d in (bin_dir, work, temp):
        d.mkdir(parents=True)
    (work / ".dx-central").symlink_to(ROOT)
    stub(bin_dir, "gh", """case "$*" in
  *"--json labels"*) echo false ;;
  *"closedByPullRequestsReferences"*) echo 0 ;;
  "api repos/o/r/issues/"*) echo Task ;;
esac""")
    stub(bin_dir, "python3", """case "$*" in
  *"autopilot.py lane"*) echo "$THE_LANE" ;;
  *"receipts.py state get"*) echo null ;;
  *"receipts.py seal-prd"*) touch "$SEALED" ;;
  *"receipts.py verify-prd"*) if [ -e "$SEALED" ]; then echo match; else echo unsealed; fi ;;
esac""")
    stub(bin_dir, "git", "echo abcdef012345")
    stub(bin_dir, "sleep", "")
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "CALLS": str(tmp_path / "calls"), "SEALED": str(tmp_path / "sealed"),
           "THE_LANE": lane, "GITHUB_REPOSITORY": "o/r", "GITHUB_OUTPUT": str(tmp_path / "out"), "RUNNER_TEMP": str(temp),
           "MODE": "start", "AS": "start", "ISSUE": "7", "PR": "", "OPEN_TO_CLAIM": "claim it"}
    done = subprocess.run(["bash", "-c", script], env=env, cwd=work, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    calls = [c.split("\x1f")[:-1] for c in (tmp_path / "calls").read_text(encoding="utf-8").split("\x1e")[:-1]]
    return done, calls, (tmp_path / "out").read_text(encoding="utf-8").splitlines()


def test_an_unsealed_delegated_sub_issue_is_sealed_instead_of_sent_back_to_a_person(tmp_path):
    done, calls, out = run_may(tmp_path / "delegated", "delegated")
    seals = [c for c in calls if c[0] == "python3" and any(a.endswith("receipts.py") for a in c) and "seal-prd" in c]
    assert seals, "an unsealed delegated sub-issue is not sealed"
    assert REFUSAL not in done.stdout and not any(c[:3] == ["gh", "issue", "comment"] for c in calls), \
        "an unsealed delegated sub-issue is sent back to a person"
    assert "go=true" in out
    # Any other lane is not sealed here: it is refused, and a person accepts it again.
    done, calls, out = run_may(tmp_path / "other", "human-issue")
    assert not any(c[0] == "python3" and "seal-prd" in c for c in calls)
    assert REFUSAL in done.stdout and "go=false" in out
