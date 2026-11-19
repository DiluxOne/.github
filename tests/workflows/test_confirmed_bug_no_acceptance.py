"""A bug the reproduction confirmed waits for no acceptance (#427): the
reproduction that hands a report to its lane takes `awaiting-acceptance` and
`incomplete` off it, and G1 leaves alone a `bug:confirmed` report that carries
neither; with the lane closed, the report keeps waiting for a maintainer.

G1's job condition is evaluated on events; the reproduction's report step
is run with gh and the central scripts stubbed."""
import hashlib
import json
import re
import subprocess

from pathlib import Path
from unittest import mock

try:
    import steps  # tests/workflows/steps.py: it runs a workflow's step with stubs
except ModuleNotFoundError:  # Test first's base has no steps.py (#845): there each call to it fails an assertion
    steps = mock.Mock(**{f"{n}.side_effect": AssertionError("tests/workflows/steps.py is missing") for n in ("evaluate", "run", "step", "workflow")})
evaluate, run, step, workflow = steps.evaluate, steps.run, steps.step, steps.workflow

def ready_runs(action, labels):
    ctx = {"github.event_name": "issues", "github.event.sender.type": "User", "github.event.action": action,
           "github.event.label.name": "accepted" if action == "labeled" else "", "inputs.label": "accepted",
           "github.event.issue.user.type": "User", "github.event.issue.labels.*.name": labels}
    return evaluate(workflow("issue-accepted.yml")["jobs"]["ready"]["if"], ctx)


def test_g1_leaves_a_confirmed_report_alone_on_open_and_edit():
    for action in ("opened", "edited"):
        assert not ready_runs(action, ["bug:confirmed"])
        # Still waiting on an acceptance, or incomplete: checked.
        assert ready_runs(action, ["bug:confirmed", "awaiting-acceptance"])
        assert ready_runs(action, ["bug:confirmed", "incomplete"])
        assert ready_runs(action, [])


def test_g1_still_checks_an_acceptance_of_a_confirmed_report():
    assert ready_runs("labeled", ["bug:confirmed", "accepted"])


STUB_PY = "import sys\nif sys.argv[1:3] == ['state', 'get']:\n    print('null')\n"


def report(tmp_path, lane_open):
    """issue-repro.yml's report step for a test that reproduced the bug."""
    work, temp = tmp_path / "work", tmp_path / "temp"
    (temp / "written").mkdir(parents=True)
    (temp / "output").mkdir()
    (temp / "written" / "test").write_text("def test_it():\n    assert False\n")
    (temp / "output" / "output-tail.txt").write_text("1 failed\n")
    work.mkdir()
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.hooksPath=/dev/null"]
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=work, check=True)
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "base"], cwd=work, check=True)
    gh = """case "$1 $2" in
  "issue list") ;;
  "issue view") echo false ;;
  "pr create") echo https://github.com/o/r/pull/9 ;;
esac"""
    env = {"NUMBER": "7", "BOT": "dilux-bot[bot]", "DX_BOT_APP": "dilux-bot", "GH_TOKEN": "t", "MODEL": "m", "BT": "`",
           "WROTE": "true", "AGENT": "success", "RUN_RESULT": "success", "OUTCOME": "reproduced",
           "TEST": "tests/repro/test_issue_7.py", "SHA256": hashlib.sha256((temp / "written" / "test").read_bytes()).hexdigest(),
           "LANE_OPEN": "yes" if lane_open else "no", "LABEL": "", "SENDER_LOGIN": "boss", "GITHUB_SERVER_URL": "https://github.com"}
    files = {".dx-central/scripts/receipts.py": STUB_PY, ".dx-central/scripts/api-commit.py": STUB_PY}
    return run(step("issue-repro.yml", "report", job="report"), tmp_path, env=env, stubs={"gh": gh}, files=files, central=False)


def edits(ran):
    return [c[3:] for c in ran.of("gh") if c[:3] == ["issue", "edit", "7"]]


def test_the_reproduction_takes_the_waiting_labels_off_when_it_hands_it_to_the_lane(tmp_path):
    ran = report(tmp_path, lane_open=True)
    assert ran.code == 0, ran.stdout + ran.stderr
    assert ran.output["handoff"] == "true"
    done = edits(ran)
    confirmed = done.index(["--repo", "o/r", "--add-label", "bug:confirmed"])
    for label in ("awaiting-acceptance", "incomplete"):
        assert done.index(["--repo", "o/r", "--remove-label", label]) > confirmed


def test_with_the_lane_closed_the_report_still_waits_for_a_maintainer(tmp_path):
    ran = report(tmp_path, lane_open=False)
    assert ran.code == 0, ran.stdout + ran.stderr
    assert "handoff" not in ran.output
    done = edits(ran)
    assert ["--repo", "o/r", "--add-label", "bug:confirmed"] in done
    assert not [e for e in done if e[-1] in ("awaiting-acceptance", "incomplete")]
    assert [c for c in ran.of("gh") if c[:2] == ["pr", "create"]]
