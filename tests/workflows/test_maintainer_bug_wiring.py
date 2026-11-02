"""A maintainer's own Bug (C2, #564): the triage never classifies it (so no
`bug:unconfirmed`, no `layer:`, no reproduction and so no `repro:no-way`);
complete, it is accepted with its writing, sealed in its author's name, and
the autopilot starts on it; the G1 check leaves it to the triage."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def jobs(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))["jobs"]


def test_the_own_job_runs_first_and_accepts_with_a_token_that_seals():
    triage = jobs("issue-triage.yml")
    own = triage["own"]
    assert "github.event.action == 'opened'" in own["if"] and "github.event.issue.user.type != 'Bot'" in own["if"]
    token = next(s for s in own["steps"] if s.get("id") == "bot")["with"]
    assert token["permission-contents"] == "write", "the seal goes on the receipts branch"
    step = next(s for s in own["steps"] if s.get("id") == "own")
    assert "triage-act.sh own-bug" in step["run"]
    # The issue's text reaches the script through env:, never ${{ }} in run.
    assert step["env"]["BODY_TEXT"] == "${{ github.event.issue.body }}" and "${{" not in step["run"]
    assert step["env"]["AUTHOR"] == "${{ github.event.issue.user.login }}"
    assert own["outputs"] == {"own": "${{ steps.own.outputs.own }}", "accepted": "${{ steps.own.outputs.accepted }}"}


def test_the_triage_skips_a_maintainers_own_bug_and_runs_when_the_check_failed():
    triage = jobs("issue-triage.yml")["triage"]
    assert triage["needs"] == "own"
    assert triage["if"].startswith("always() && needs.own.outputs.own != 'true' && ")


def test_the_autopilot_starts_on_the_acceptance_it_sealed():
    auto = jobs("issue-triage.yml")["autopilot"]
    assert "own" in auto["needs"] and "steer" in auto["needs"]
    assert "(github.event.action == 'opened' && needs.own.outputs.accepted == 'true')" in auto["if"]
    assert auto["with"]["mode"] == "${{ github.event.label.name == 'autopilot:continue' && 'continue' || 'start' }}"


def test_the_g1_check_on_opening_leaves_it_to_the_triage():
    check = next(s for s in jobs("issue-accepted.yml")["ready"]["steps"] if s.get("id") == "check")
    run = check["run"]
    leave = run.index("triage-act.sh own-bug-check")
    assert run.index('[ -n "$GH_TOKEN" ] || {') < leave < run.index("issue-schema.py g1-labels")
    assert '[ "$ACTION" = opened ] && [ "$ready" = true ]' in run[run.rindex("\n", 0, leave):leave]
    assert check["env"]["AUTHOR"] == "${{ github.event.issue.user.login }}"


def test_the_gate_and_the_autopilot_read_the_seal_as_its_authors_acceptance():
    gate = (ROOT / "scripts/issue-gate.sh").read_text(encoding="utf-8")
    assert 'receipts.py" own-bug' in gate and 'own_bug "$answer" "$n"' in gate
    autopilot = (ROOT / "scripts/autopilot.py").read_text(encoding="utf-8")
    assert "own_bug_of(repo, number, issue)" in autopilot
