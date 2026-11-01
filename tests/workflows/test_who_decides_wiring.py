"""Who decides (#588): every place that asked "has write access?" asks
scripts/deciders.py instead, before anything else it does."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def test_accepted_is_guarded_before_the_check_the_assignee_and_the_seal():
    steps = workflow("issue-accepted.yml")["jobs"]["ready"]["steps"]
    names = [s.get("id") or s.get("name", "") for s in steps]
    guard = names.index("guard")
    assert "deciders.py may accepted" in steps[guard]["run"]
    assert '--remove-label "$LABEL"' in steps[guard]["run"] and "gh issue comment" in steps[guard]["run"]
    # Nothing but the scripts and the token comes before it.
    assert guard < names.index("check") and guard < names.index("Assign it to whoever accepted it")
    for s in steps[guard + 1:]:
        if s.get("id") == "check" or s.get("name", "").startswith("Assign it"):
            assert "steps.guard.outputs.refused != 'true'" in s["if"], s.get("name")
    seal = next(s for s in steps if s.get("name", "").startswith("Seal the PRD"))
    assert "steps.check.outputs.ready == 'true'" in seal["if"]


def test_continue_is_guarded_before_the_autopilot_starts():
    jobs = workflow("issue-triage.yml")["jobs"]
    steer, ap = jobs["steer"], jobs["autopilot"]
    run = next(s for s in steer["steps"] if s.get("id") == "may")["run"]
    assert 'deciders.py may "$action" "$SENDER"' in run
    assert '--remove-label "$LABEL"' in run and "gh issue comment" in run
    cond = " ".join(steer["if"].split())
    assert "github.event.label.name == 'autopilot:continue'" in cond and "github.event.label.name == 'accepted'" in cond
    assert "github.event.sender.type != 'Bot'" in cond
    assert ap["needs"] == "steer"
    acond = " ".join(ap["if"].split())
    assert acond.startswith("!cancelled() && (needs.steer.result == 'skipped' || needs.steer.outputs.ok == 'true')")


def test_answers_and_others_ask_who_decides():
    ap = (ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8")
    assert "deciders.py list answer" in ap and "DECIDERS=" in ap and "WRITERS=" not in ap
    rr = workflow("review-reply.yml")["jobs"]
    back = next(s for s in rr["answer"]["steps"] if s.get("id") == "back")["run"]
    assert "deciders.py may answer" in back and "admin|maintain|write" not in back
    others = next(s for s in rr["others"]["steps"] if s.get("id") == "others")["run"]
    assert "deciders.py list answer" in others
    who = next(s for s in rr["credits"]["steps"] if s.get("id") == "who")["run"]
    assert "deciders.py may credits" in who
