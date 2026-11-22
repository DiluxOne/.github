"""#928 C5: a blocking review started by a description edit (or the
`review:full` label) on an autopilot pull request starts a fix round, as one
from a push does: pull-request-edited.yml has the `autopilot-fix` job, with
pull-request.yml's guards, and only on a review that read the pull request
in this run (claude-review.yml's `fresh` output), so an edit that only
reused the push's verdict never spends a second round on it. The job's
condition is evaluated on the events (tests/workflows/steps.py), and the
verdict step is run with gh stood in for `fresh`."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from steps import evaluate, run, step, workflow  # noqa: E402

BOT = "dilux-bot[bot]"


def edited_fix():
    jobs = workflow("pull-request-edited.yml")["jobs"]
    assert "autopilot-fix" in jobs, "pull-request-edited.yml has no autopilot-fix job"
    return jobs["autopilot-fix"]


def starts(job, blocking="true", fresh="true", result="failure", draft=False, labels=("autopilot",), author=BOT, current="true",
           repo="DiluxOne/.github", mismatch="false"):
    ctx = {"github.event_name": "pull_request", "github.repository": repo, "github.event.action": "edited",
           "github.event.pull_request.draft": draft, "github.event.pull_request.labels.*.name": list(labels),
           "github.event.pull_request.user.login": author, "vars.DX_BOT_LOGIN": BOT,
           "needs.review.outputs.blocking": blocking, "needs.review.outputs.fresh": fresh, "needs.review.result": result,
           "needs.review.outputs.current": current, "needs.review.outputs.description-mismatch": mismatch,
           "needs.conventions.result": "success", "needs.security-gate.result": "success"}
    return bool(evaluate(str(job["if"]), ctx))


def test_c5_a_blocking_review_of_a_description_edit_starts_a_fix_round():
    job = edited_fix()
    assert starts(job) is True
    assert job["uses"] == "./.github/workflows/autopilot.yml"
    assert job["with"]["mode"] == "fix"
    assert job["with"]["pr"] == "${{ format('{0}', github.event.pull_request.number) }}"
    assert sorted(job["needs"]) == ["conventions", "review"]
    assert job["permissions"] == {"contents": "read"} and job["secrets"] == "inherit"


def test_c5_no_round_for_a_reused_verdict_or_what_a_push_would_not_round_either():
    job = edited_fix()
    # The push's verdict reused by the edit: the push's round has it.
    assert starts(job, fresh="false") is False
    assert starts(job, fresh="") is False
    # A review that does not block, a draft, another author, no label, an
    # older head, another repository (org-pull-request.yml's).
    assert starts(job, blocking="false", result="success") is False
    assert starts(job, draft=True) is False
    assert starts(job, author="someone") is False
    assert starts(job, labels=()) is False
    assert starts(job, current="false") is False
    assert starts(job, repo="DiluxOne/other") is False


def test_c5_the_review_says_whether_it_read_the_pull_request_in_this_run(tmp_path):
    wf = workflow("claude-review.yml")
    outputs = (wf.get("on") or wf.get(True))["workflow_call"]["outputs"]
    assert (outputs.get("fresh") or {}).get("value") == "${{ jobs.review.outputs.fresh }}"
    assert wf["jobs"]["review"]["outputs"].get("fresh") == "${{ steps.verdict.outputs.fresh }}"
    review = {"risk": "low", "complexity": "low", "blocking": True, "type": "fix", "description_matches": True, "summary": "s",
              "findings": [{"severity": "blocker", "file": "a.py", "title": "t"}], "lessons": [], "resolved_threads": []}
    gh = 'case "$*" in *"--json files"*) echo "[]";; *"--json title"*) echo "fix: x";; api*) echo "[]";; esac'
    for mode, want in (("full", "true"), ("incremental", "true"), ("reuse", "false"), ("capped", "false")):
        d = tmp_path / mode
        (d / "temp").mkdir(parents=True)
        (d / "temp" / "open-threads.json").write_text("[]", encoding="utf-8")
        (d / "temp" / "previous.json").write_text(json.dumps(dict(review, text="", sha="a" * 40)), encoding="utf-8")
        env = {"OUT": json.dumps(review), "MODE": mode, "PR": "8", "BOT": BOT, "SHA": "a" * 40, "FLOOR": "low", "REASONS": "none",
               "TRUSTED": "true", "COUNT": "1", "LAST": "b" * 40, "MODEL": "m", "MAX_AUTO": "5", "KIND": "", "BASE": "c" * 40,
               "BODY": "b", "EXECUTION_FILE": "", "VERIFY_EXECUTION_FILE": ""}
        ran = run(step("claude-review.yml", "verdict"), d, env=env, stubs={"gh": gh})
        assert ran.output.get("fresh") == want, (mode, ran.output, ran.stderr[-1500:])


def org_fix(path):
    """The `autopilot-fix` job of org-pull-request.yml or of the test
    repository's caller, which keeps its jobs in step."""
    if path.startswith("workflow-templates/"):
        import yaml
        root = Path(__file__).resolve().parents[2]
        return yaml.safe_load((root / path).read_text(encoding="utf-8"))["jobs"]["autopilot-fix"]
    return workflow(path)["jobs"]["autopilot-fix"]


def org_starts(job, action="edited", fresh="true", conventions="success", **kw):
    ctx = {"github.event_name": "pull_request", "github.repository": "DiluxOne/other", "github.event.action": action,
           "github.event.pull_request.draft": False, "github.event.pull_request.labels.*.name": ["autopilot"],
           "github.event.pull_request.user.login": BOT, "vars.DX_BOT_LOGIN": BOT,
           "needs.review.outputs.blocking": "true", "needs.review.outputs.fresh": fresh, "needs.review.result": "success",
           "needs.review.outputs.current": "true", "needs.review.outputs.description-mismatch": "false",
           "needs.conventions.result": conventions, "needs.security-gate.result": "success"}
    ctx.update(kw)
    return bool(evaluate(str(job["if"]), ctx))


def test_c5_every_other_repository_rounds_an_edits_fresh_blocker_too():
    # The maintainer's answer on #928: the same rule in org-pull-request.yml,
    # with the `fresh` guard, and in the test repository's caller with it.
    for path in ("org-pull-request.yml", "workflow-templates/test-pull-request.yml"):
        job = org_fix(path)
        assert org_starts(job) is True, path
        # A verdict the edit only reused: the push's round has it.
        assert org_starts(job, fresh="false") is False, path
        assert org_starts(job, fresh="") is False, path
        # A push's run is as before, `fresh` or not.
        assert org_starts(job, action="synchronize", fresh="") is True, path
        assert org_starts(job, action="synchronize", fresh="", conventions="failure",
                          **{"needs.review.outputs.blocking": "", "needs.review.result": "skipped"}) is True, path
        # An edit whose conventions fail skips the review: no round.
        assert org_starts(job, fresh="", conventions="failure",
                          **{"needs.review.outputs.blocking": "", "needs.review.result": "skipped"}) is False, path
        assert org_starts(job, **{"needs.review.outputs.blocking": "false"}) is False, path
