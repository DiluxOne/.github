"""A claimed bug the reproduction confirmed (#488): no lane issue, the
person is given the failing test's branch, and the gate keeps the test."""
import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def report_steps():
    return yaml.safe_load((ROOT / ".github/workflows/issue-repro.yml").read_text(encoding="utf-8"))["jobs"]["report"]["steps"]


def claim():
    spec = importlib.util.spec_from_file_location("claim", ROOT / "scripts/claim.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_claimed_reproduced_bug_opens_no_lane_issue():
    steps = report_steps()
    report = next(s for s in steps if s.get("id") == "report")["run"]
    claimed = report.index('index("claimed") != null')
    # Read after the test is pushed and the bug confirmed, before the lane's
    # hand-off and the draft: it ends the step with no handoff.
    assert report.index("api-commit.py push") < claimed < report.index('if [ "$LANE_OPEN" = yes ]') < report.index("gh pr create")
    branch = report[claimed:report.index('if [ "$LANE_OPEN" = yes ]')]
    assert 'echo "claimed=true"' in branch and 'echo "branch=$branch"' in branch and "exit 0" in branch and "handoff=true" not in branch
    lane = next(s for s in steps if s.get("id") == "lane")
    assert lane["if"] == "steps.report.outputs.handoff == 'true'", "the lane opens its issue only on a hand-off"
    given = next(s for s in steps if s.get("name") == "A claimed bug's test, to the person")
    assert given["if"] == "steps.report.outputs.claimed == 'true'" and given["run"] == "python3 .dx-central/scripts/claim.py repro"
    assert given["env"]["BRANCH"] == "${{ steps.report.outputs.branch }}" and given["env"]["SHA256"] == "${{ needs.write.outputs.sha256 }}"
    assert steps.index(given) < steps.index(lane)


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
