"""Who decides (#588): every place that asked "has write access?" asks
scripts/deciders.py instead, before anything else it does."""
from pathlib import Path

import yaml

import steps

ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def run_guard(tmp_path, rc):
    """The guard step, run with deciders.py answering exit RC and gh stubbed."""
    s = steps.step("issue-accepted.yml", "guard", job="ready")
    decider = f"import sys\nprint('not a decider: ' + ' '.join(sys.argv[1:]))\nsys.exit({rc})\n"
    return steps.run(s, tmp_path, central=False, stubs={"gh": ""},
                     files={".dx-central/scripts/deciders.py": decider},
                     exprs={"inputs.label": "accepted", "github.event.issue.number": "7", "github.event.sender.login": "eve"})


def test_accepted_is_guarded_before_the_check_the_assignee_and_the_seal(tmp_path, monkeypatch):
    ready = steps.workflow("issue-accepted.yml")["jobs"]["ready"]["steps"]
    names = [s.get("id") or s.get("name", "") for s in ready]
    guard = names.index("guard")
    # Nothing but the scripts and the token comes before it.
    assert [n for i, n in enumerate(names) if i < guard] == ["central", "bot"]
    assert guard < names.index("check") and guard < names.index("Assign it to whoever accepted it")
    # A decider passes: nothing is written, and the steps after it run.
    ok = run_guard(tmp_path / "ok", 0)
    assert ok.code == 0 and ok.output == {} and ok.calls == []
    # It asks deciders.py whether the sender may accept.
    assert "not a decider: may accepted eve" in ok.stdout
    # Anyone else (1), or a decider that could not be told (2): refused, the
    # label comes off and the issue says why.
    for rc in (1, 2):
        no = run_guard(tmp_path / f"no{rc}", rc)
        assert no.code == 0 and no.output == {"refused": "true"}
        edit, comment = no.of("gh")
        assert edit == ["issue", "edit", "7", "--repo", "o/r", "--remove-label", "accepted"]
        assert comment[:4] == ["issue", "comment", "7", "--repo"] and "`accepted` was taken off" in comment[-1]
        # Anyone else hears deciders.py's reason; "could not tell" never passes as it.
        assert ("not a decider: may accepted eve" in comment[-1]) == (rc == 1)
    # The check and the assignee run only when the guard did not refuse.
    monkeypatch.setitem(steps.FUNCS, "hashFiles", lambda *paths: "abc")
    event = {"github.event.action": "labeled", "steps.bot.outputs.token": "t"}
    for s in ready:
        if s.get("id") == "check" or s.get("name", "").startswith("Assign it"):
            assert steps.evaluate(s["if"], dict(event, **{"steps.guard.outputs.refused": ""})) is True, s.get("name")
            assert steps.evaluate(s["if"], dict(event, **{"steps.guard.outputs.refused": "true"})) is False, s.get("name")
    seal = next(s for s in ready if s.get("name", "").startswith("Seal the PRD"))
    assert names.index(seal["name"]) > names.index("check")
    assert steps.evaluate(seal["if"], dict(event, **{"steps.check.outputs.ready": "true"})) is True
    assert steps.evaluate(seal["if"], dict(event, **{"steps.check.outputs.ready": ""})) is False


def test_continue_is_guarded_before_the_autopilot_starts():
    jobs = workflow("issue-triage.yml")["jobs"]
    steer, ap = jobs["steer"], jobs["autopilot"]
    run = next(s for s in steer["steps"] if s.get("id") == "may")["run"]
    assert 'deciders.py may "$action" "$SENDER"' in run
    assert '--remove-label "$LABEL"' in run and "gh issue comment" in run
    cond = " ".join(steer["if"].split())
    assert "github.event.label.name == 'autopilot:continue'" in cond and "github.event.label.name == 'accepted'" in cond
    assert "github.event.sender.type != 'Bot'" in cond
    assert "steer" in ap["needs"]  # and `own`, a maintainer's own Bug (#564)
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


def test_an_incomplete_issue_is_shaped_by_its_answers_only():
    wf = workflow("issue-accepted.yml")
    job = wf["jobs"]["shape"]
    cond = " ".join(job["if"].split())
    for part in ("github.event_name == 'issue_comment'", "!github.event.issue.pull_request", "github.event.comment.user.type != 'Bot'",
                 "contains(github.event.issue.labels.*.name, 'incomplete')", "!contains(github.event.issue.labels.*.name, inputs.label)"):
        assert part in cond, part
    steps = {s.get("id") or s.get("name"): s for s in job["steps"]}
    who = steps["who"]["run"]
    # Only the author's and the deciders' words reach the rewrite.
    assert "deciders.py list answer" in who and "issue-schema.py shape-prompt" in who and 'ANSWERS="$RUNNER_TEMP/answers.json"' in who
    assert "shape-others" in who and "steps.who.outputs.others" in steps["summary"]["if"]
    for model in ("rewrite", "summary"):
        args = steps[model]["with"]["claude_args"]
        assert '--allowedTools ""' in args and "Bash" in args and "--max-budget-usd" in args
    apply = next(s for s in job["steps"] if s.get("name") == "The rewrite, checked, on the issue")["run"]
    assert apply.index("issue-schema.py shape-check") < apply.index("gh issue edit \"$NUMBER\" --repo \"$GITHUB_REPOSITORY\" --body-file")
    assert job["runs-on"].startswith("ubuntu-latest") and job["permissions"] == {"issues": "read"}
    assert job["concurrency"]["group"] == wf["jobs"]["ready"]["concurrency"]["group"]
    # The G1 comment asks the questions.
    check = next(s for s in wf["jobs"]["ready"]["steps"] if s.get("id") == "check")["run"]
    assert "issue-schema.py questions" in check


def test_every_issues_caller_forwards_the_comments_and_the_model_to_the_acceptance():
    for path in (".github/workflows/issues.yml", "workflow-templates/issues.yml"):
        wf = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))
        acc = wf["jobs"]["accepted"]
        assert "github.event_name == 'issue_comment'" in acc["if"], path
        assert {"DILUX_BOT_PRIVATE_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"} <= set(acc["secrets"]), path
        assert acc["permissions"] == {"actions": "write", "issues": "read", "pull-requests": "read"}, path


def test_every_job_that_asks_who_decides_can_read_what_decides():
    """deciders.py reads CODEOWNERS and the seal (contents), the change's
    files (pull requests) and the issue: a token without one refuses
    everyone, every acceptance included."""
    import json
    for name in ("autopilot.yml", "issue-accepted.yml", "issue-triage.yml", "review-reply.yml"):
        for job_name, job in workflow(name).get("jobs", {}).items():
            if "deciders.py" not in json.dumps(job):
                continue
            token = next(s for s in job["steps"] if "create-github-app-token" in str(s.get("uses", "")) and s.get("id") == "bot")["with"]
            assert token.get("permission-contents") in ("read", "write"), (name, job_name)
            assert token.get("permission-pull-requests") in ("read", "write"), (name, job_name)
            assert token.get("permission-issues") in ("read", "write"), (name, job_name)
