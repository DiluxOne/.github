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


def test_an_accepted_issue_edited_after_its_seal_is_unsealed():
    job = workflow("issue-accepted.yml")["jobs"]["unseal"]
    cond = " ".join(job["if"].split())
    assert "github.event.action == 'edited'" in cond and "contains(github.event.issue.labels.*.name, inputs.label)" in cond
    run = job["steps"][-1]["run"]
    order = ["receipts.py verify-prd", "g1-labels unsealed", '--remove-label "$LABEL"', "receipts.py sealed-prd", "issue-schema.py diff", "deciders.py who accepted", "gh issue comment"]
    assert [run.index(s) for s in order] == sorted(run.index(s) for s in order)
    # A seal that cannot be read is never taken for a change.
    assert 'if [ "$rc" -gt 1 ]; then' in run and '[ "$verdict" = changed ] ||' in run
    assert job["concurrency"]["group"] == workflow("issue-accepted.yml")["jobs"]["ready"]["concurrency"]["group"]
