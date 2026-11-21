"""A claimed bug the reproduction confirmed (#488): no lane issue, the
person is given the failing test's branch, and the gate keeps the test."""
import hashlib
import importlib.util
from pathlib import Path

import yaml

import steps

ROOT = Path(__file__).resolve().parents[2]


def report_steps():
    return yaml.safe_load((ROOT / ".github/workflows/issue-repro.yml").read_text(encoding="utf-8"))["jobs"]["report"]["steps"]


def claim():
    spec = importlib.util.spec_from_file_location("claim", ROOT / "scripts/claim.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The engine's helpers the step calls, stood in: each records its call.
HELPER = """import json, os, sys
with open(os.environ["DX_CALLS"], "a") as f:
    f.write(json.dumps([os.path.basename(__file__), *sys.argv[1:]]) + "\\n")
"""
TEST = "tests/Unit/Repro/Issue12Test.php"


def reproduced(tmp_path, *, claimed, lane_open):
    """Runs the report step on a bug the test reproduced (#12), with gh and
    git stood in; CLAIMED is what the issue's `claimed` label reads."""
    written = tmp_path / "temp/written/test"
    written.parent.mkdir(parents=True)
    written.write_text("<?php // fails on main\n")
    gh = ('case "$*" in\n'
          f'  "issue view 12"*"--json labels"*) echo {str(claimed).lower()} ;;\n'
          '  "pr create"*) echo https://github.com/o/r/pull/30 ;;\n'
          "esac\n")
    s = next(s for s in report_steps() if s.get("id") == "report")
    files = {f".dx-central/scripts/{name}": HELPER for name in ("api-commit.py", "receipts.py")}
    ran = steps.run(s, tmp_path, central=False, files=files, stubs={"gh": gh, "git": ""},
                    env={"NUMBER": "12", "WROTE": "true", "AGENT": "success", "RUN_RESULT": "success", "OUTCOME": "reproduced",
                         "REJECTED": "", "TEST": TEST, "SHA256": hashlib.sha256(written.read_bytes()).hexdigest(),
                         "MODEL": "m", "BOT": "dilux-bot[bot]", "DX_BOT_APP": "dilux-bot", "GH_TOKEN": "t",
                         "LANE_OPEN": "yes" if lane_open else "", "LABEL": "", "SENDER_LOGIN": ""})
    assert ran.code == 0, ran.stdout + ran.stderr
    return ran


def test_a_claimed_reproduced_bug_opens_no_lane_issue(tmp_path):
    ran = reproduced(tmp_path, claimed=True, lane_open=True)
    # Read after the test is pushed and the bug confirmed: it ends the step
    # with no hand-off and no draft, and names the branch.
    assert ran.output == {"claimed": "true", "branch": "test/repro-issue-12", "test": TEST}
    push = next(i for i, c in enumerate(ran.calls) if c[:2] == ["api-commit.py", "push"])
    confirmed = next(i for i, c in enumerate(ran.calls) if c[:3] == ["gh", "issue", "edit"] and "bug:confirmed" in c)
    read = next(i for i, c in enumerate(ran.calls) if c[:3] == ["gh", "issue", "view"] and "labels" in c)
    assert push < confirmed < read == len(ran.calls) - 1
    assert not [c for c in ran.of("gh") if c[:2] == ["pr", "create"] or "awaiting-acceptance" in c]


def test_an_unclaimed_reproduced_bug_goes_to_the_lane_or_a_draft(tmp_path):
    lane = reproduced(tmp_path / "lane", claimed=False, lane_open=True)
    assert lane.output == {"handoff": "true", "branch": "test/repro-issue-12"}
    draft = reproduced(tmp_path / "draft", claimed=False, lane_open=False)
    assert "claimed" not in draft.output and "handoff" not in draft.output
    assert [c for c in draft.of("gh") if c[:2] == ["pr", "create"]]


def test_the_claimed_bug_s_steps_are_wired_to_the_report():
    steps_ = report_steps()
    lane = next(s for s in steps_ if s.get("id") == "lane")
    assert lane["if"] == "steps.report.outputs.handoff == 'true'", "the lane opens its issue only on a hand-off"
    given = next(s for s in steps_ if s.get("name") == "A claimed bug's test, to the person")
    assert given["if"] == "steps.report.outputs.claimed == 'true'" and given["run"] == "python3 .dx-central/scripts/claim.py repro"
    assert given["env"]["BRANCH"] == "${{ steps.report.outputs.branch }}" and given["env"]["SHA256"] == "${{ needs.write.outputs.sha256 }}"
    assert steps_.index(given) < steps_.index(lane)
    # On a claimed report the lane's step does not run, the person's does.
    claimed = {"steps.report.outputs.handoff": "", "steps.report.outputs.claimed": "true"}
    assert not steps.evaluate(lane["if"], claimed) and steps.evaluate(given["if"], claimed)


def test_the_person_is_named_the_branch_and_the_test_is_sealed_for_the_gate():
    c = claim()
    cfg = c.config({})
    state = c.start_clock(c.new_claim("ana", c.ts("2026-11-01T00:00:00Z")), c.ts("2026-11-02T00:00:00Z"), reset=True)
    test = {"test": "tests/Unit/Repro/Issue12Test.php", "sha256": "a" * 64, "branch": "test/repro-issue-12", "run": "https://github.com/o/r/actions/runs/4"}
    text = c.repro_text("ana", test, cfg, state)
    assert "@ana" in text and "`test/repro-issue-12`" in text and "unchanged" in text and "released on 2026-11-12" in text
    # The marker the gate reads (scripts/issue-gate.sh claim_test), in dilux-bot's comment.
    assert c.read_marker([{"id": 1, "user": {"login": c.org.BOT}, "body": text}], c.TEST_MARK) == (1, test)
    gate = (ROOT / "scripts/issue-gate.sh").read_text(encoding="utf-8")
    assert "<!-- dx-claim-test " in gate and c.TEST_MARK == "dx-claim-test"
