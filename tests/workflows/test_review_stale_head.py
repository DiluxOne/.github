"""#888 C1: a review run of a commit that is no longer the pull request's
head neither reviews it nor cancels the head's review. A pull request pushed
to right after it opens gets two runs: `opened` at the first commit and
`synchronize` at the new head; the older one could reach the review's
concurrency group (`cancel-in-progress`) last, cancel the head's review and
review a commit nobody merges. claude-review.yml's `head` job, outside the
group, reads the pull request's head first; the review needs it and runs
only when it is current, and the callers act on no verdict of a stale run.
The head job's step runs as written, with gh and sleep stood in."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from steps import evaluate, run, step, workflow  # noqa: E402

OLD, NEW = "c500e8b" + "0" * 33, "0fb9c65" + "0" * 33


def jobs():
    return workflow("claude-review.yml")["jobs"]


def test_c1_the_review_needs_a_head_job_outside_its_group():
    all_jobs = jobs()
    assert "head" in all_jobs, "claude-review.yml has no `head` job reading the pull request's current head"
    head, review = all_jobs["head"], all_jobs["review"]
    # Outside the group: a stale run's head job cancels nothing.
    assert "concurrency" not in head
    # The same fork and draft guard as the review.
    gate = "needs.head.outputs.current != 'false'"
    assert " ".join(review["if"].split()) == "!cancelled() && " + " ".join(head["if"].split()) + " && " + gate
    needs = review.get("needs") or []
    assert "head" in (needs if isinstance(needs, list) else [needs])
    assert head["outputs"]["current"] == "${{ steps.current.outputs.current }}"
    out = workflow("claude-review.yml")[True]["workflow_call"]["outputs"]
    assert out["current"]["value"] == "${{ jobs.head.outputs.current }}"
    # The review keeps its group: a newer push still cancels the review before it.
    assert "cancel-in-progress" in review["concurrency"]


def review_if(current, event_head_repo="o/r", draft=False):
    ctx = {"needs.head.result": "success" if current else "failure", "github.event_name": "pull_request", "github.event.pull_request.head.repo.full_name": event_head_repo,
           "github.repository": "o/r", "github.event.pull_request.draft": draft, "needs.head.outputs.current": current}
    return evaluate(" ".join(jobs()["review"]["if"].split()), ctx)


def test_c1_a_stale_run_skips_the_review_and_the_heads_runs():
    assert review_if("true") is True
    assert review_if("false") is False
    assert review_if("true", draft=True) is False
    assert review_if("true", event_head_repo="fork/r") is False


def test_c1_a_failed_head_job_never_skips_the_review():
    # A skipped required check passes the ruleset: were the head job to fail
    # (its App token, a runner), skipping the review would let the head merge
    # unreviewed. With no answer, the review runs as it did before #888.
    assert review_if("") is True
    # Asserted, never looked up: at the base, which has no head job, the
    # test fails on an assertion, not on a KeyError ("Test first", #845).
    assert "head" in jobs(), "claude-review.yml has no `head` job"
    head = jobs()["head"]
    token = step("claude-review.yml", "bot", job="head")
    assert token.get("continue-on-error") is True
    read = step("claude-review.yml", "current", job="head")
    assert (read.get("env") or {}).get("GH_TOKEN") == "${{ steps.bot.outputs.token || github.token }}"
    assert head.get("permissions") == {"contents": "read", "pull-requests": "read"}


def run_head(tmp_path, answer, action="synchronize", sha=OLD):
    s = step("claude-review.yml", "current", job="head")
    stubs = {"gh": answer, "sleep": "true"}
    env = {"GH_TOKEN": "t", "REPO": "o/r", "PR": "3459", "SHA": sha, "ACTION": action}
    return run(s, tmp_path, env=env, stubs=stubs, central=False)


def test_c1_a_newer_head_answers_not_current(tmp_path):
    ran = run_head(tmp_path, f'echo "{NEW}"')
    assert ran.code == 0, ran.stderr
    assert ran.output["current"] == "false"
    assert ["api", "repos/o/r/pulls/3459", "--jq", ".head.sha"] in ran.of("gh")


def test_c1_the_same_head_answers_current(tmp_path):
    ran = run_head(tmp_path, f'echo "{NEW}"', sha=NEW)
    assert ran.code == 0, ran.stderr
    assert ran.output["current"] == "true"


def test_c1_an_edit_is_always_current(tmp_path):
    ran = run_head(tmp_path, f'echo "{NEW}"', action="edited")
    assert ran.code == 0, ran.stderr
    assert ran.output["current"] == "true"


def test_c1_a_failed_read_never_skips_the_review(tmp_path):
    ran = run_head(tmp_path, 'echo "HTTP 502" >&2; exit 1')
    assert ran.code == 0, ran.stderr
    assert ran.output["current"] == "true"
    # It retried before it gave up.
    assert len(ran.of("gh")) > 1


def caller_if(name, job, current, **more):
    wf = workflow(name)
    ctx = {"github.event_name": "pull_request", "github.repository": "DiluxOne/.github" if name == "pull-request.yml" else "DiluxOne/x",
           "github.event.action": "synchronize", "github.event.pull_request.draft": False,
           "github.event.pull_request.labels.*.name": ["autopilot"], "github.event.pull_request.user.login": "dilux-bot[bot]",
           "vars.DX_BOT_LOGIN": "dilux-bot[bot]", "needs.review.result": "success", "needs.review.outputs.blocking": "true",
           "needs.review.outputs.current": current, "needs.review.outputs.description-ok": "true", "needs.review.outputs.description-mismatch": "false"}
    for need in ("conventions", "actionlint", "scripts", "test-first"):
        ctx[f"needs.{need}.result"] = "success"
    ctx.update(more)
    return evaluate(" ".join(str(wf["jobs"][job]["if"]).split()), ctx)


def test_c1_the_callers_act_on_no_verdict_of_a_stale_run():
    for name in ("org-pull-request.yml", "pull-request.yml", "workflow-templates/test-pull-request.yml"):
        for job in ("auto-merge", "autopilot-fix"):
            assert caller_if(name, job, "true") is True, (name, job)
            assert caller_if(name, job, "false") is False, (name, job)
            # A failed conventions on a stale commit starts no round either.
            if job == "autopilot-fix":
                assert caller_if(name, job, "false", **{"needs.conventions.result": "failure"}) is False, name
            # A review that never ran its head job (no output) still acts.
            assert caller_if(name, job, "") is True, (name, job)
