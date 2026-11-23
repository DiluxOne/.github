"""#924 C3: the autopilot rewrites its own pull request's description.

A review that says the description does not match (`description-ok`
false) starts a fix round for an autopilot pull request; that round's
prompt asks for `describe`; applying the intent rewrites only What changes,
How I tested it and the checklist's `Test:` lines (Closes, the ticks and
the Credits stay); and a round that pushed no commit adds `review:full`
before the edit, so the edit's review runs `full`, not `reuse`, and its
record carries the new `description_matches`."""
import json
import os
import re
import subprocess
from pathlib import Path

from steps import ROOT, evaluate, run, step, workflow

BOT = "dilux-bot[bot]"
HEAD = "h" * 40


def fix_if(name):
    cond = workflow(name)["jobs"]["autopilot-fix"]["if"]
    return re.sub(r"^\$\{\{\s*|\s*\}\}$", "", cond.strip())


def event(repo, mismatch, blocking="false", description_ok=None):
    return {
        "github.event_name": "pull_request", "github.repository": repo, "github.event.action": "synchronize",
        "needs.review.outputs.blocking": blocking, "needs.review.result": "success", "needs.conventions.result": "success",
        "needs.actionlint.result": "success", "needs.scripts.result": "success", "needs.security-gate.result": "success", "needs.test-first.result": "success", "needs.review.outputs.current": "true", "needs.review.outputs.fresh": "",
        "needs.review.outputs.description-mismatch": mismatch,
        "needs.review.outputs.description-ok": description_ok or ("false" if mismatch == "true" else "true"),
        "github.event.pull_request.draft": False,
        "github.event.pull_request.labels.*.name": ["autopilot"], "github.event.pull_request.user.login": "dilux-bot[bot]",
        "vars.DX_BOT_LOGIN": "dilux-bot[bot]",
    }


def test_the_fix_round_starts_when_the_review_says_the_description_does_not_match():
    for name, repo in (("pull-request.yml", "DiluxOne/.github"), ("org-pull-request.yml", "DiluxOne/site")):
        cond = fix_if(name)
        assert evaluate(cond, event(repo, "true")) is True, name
        assert evaluate(cond, event(repo, "false")) is False, name
        # A description edited since the review (a reused verdict on a new
        # text: description-ok false, nobody found it wrong) starts no round,
        # on any event that reaches the trigger.
        for action in ("synchronize", "ready_for_review", "reopened"):
            edited = {**event(repo, "false", description_ok="false"), "github.event.action": action}
            assert evaluate(cond, edited) is False, (name, action)
        # Never for someone else's pull request.
        other = {**event(repo, "true"), "github.event.pull_request.user.login": "alice"}
        assert evaluate(cond, other) is False, name
        # The round knows why it runs: only a found mismatch asks for a rewrite.
        passed = workflow(name)["jobs"]["autopilot-fix"]["with"]["description-ok"]
        expr = re.sub(r"^\$\{\{\s*|\s*\}\}$", "", passed)
        assert evaluate(expr, {"needs.review.outputs.description-mismatch": "true"}) == "false", name
        assert evaluate(expr, {"needs.review.outputs.description-mismatch": "false"}) == "true", name
        assert evaluate(expr, {"needs.review.outputs.description-mismatch": ""}) == "true", name
    assert "description-mismatch" in workflow("claude-review.yml")[True]["workflow_call"]["outputs"]


def test_the_fix_inputs_reach_the_prompt():
    assert "description-ok" in workflow("autopilot.yml")[True]["workflow_call"]["inputs"]
    assert step("autopilot.yml", "task", "prep")["env"]["DESCRIPTION_OK"] == "${{ inputs.description-ok }}"


def prompt_fix(tmp_path, description_ok):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
    env.update({"GITHUB_REPOSITORY": "o/r", "PR": "8", "ROUND": "1", "DESCRIPTION_OK": description_ok, "DX_IO": str(tmp_path)})
    out = subprocess.run(["python3", str(ROOT / "scripts" / "autopilot.py"), "prompt", "fix"], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_prompt_fix_asks_for_describe_when_the_description_does_not_match(tmp_path):
    asked = prompt_fix(tmp_path, "false")
    assert "PR=8 python3 .dx-central/scripts/autopilot.py describe" in asked
    assert "does not match" in asked
    assert "autopilot.py describe" not in prompt_fix(tmp_path, "true")


PR_BODY = """## 📝 What changes

The old text.

## 💡 Why

Closes #7. The autopilot works it here.

## 🎯 Acceptance criteria

<!-- dx-checklist -->
- [x] **C1** Given a, when b, then c.
  Test: tests/old_one.py
- [ ] **C2** Given d, when e, then f.
  Test: tests/old_two.py
<!-- /dx-checklist -->

## 🙌 Credits

<!-- dx-credits -->
- @alice: reported (https://github.com/o/r/issues/7)
<!-- /dx-credits -->

## 🧪 How I tested it

<!-- dx-tested -->
The old test note.

🤖 AI-generated · Claude Opus 5.5 (Anthropic)
"""
DESCRIBE = """## What changes

The new text, true to the code.

## How I tested it

Ran tests/new_one.py and tests/new_two.py.

## Tests

- C1: tests/new_one.py
- C2: tests/new_two.py (the second)
"""


def apply_describe(tmp_path, no_commit, text=DESCRIBE):
    """`autopilot.py apply` of one `describe` intent, with gh stubbed: it
    serves PR_BODY and records each call and the body it is given."""
    bin_dir, out = tmp_path / "bin", tmp_path / "out"
    bin_dir.mkdir(exist_ok=True)
    out.mkdir(exist_ok=True)
    (tmp_path / "body.md").write_text(PR_BODY, encoding="utf-8")
    gh = bin_dir / "gh"
    gh.write_text(f"""#!/usr/bin/env bash
python3 -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "$@" >> {out}/calls.jsonl
case "$*" in
  "pr view"*"--json body"*) python3 -c 'import json; print(json.dumps({{"body": open("{tmp_path}/body.md").read()}}))' ;;
  "pr edit"*"--body-file -"*) cat > {out}/new-body.md ;;
  *) : ;;
esac
""", encoding="utf-8")
    gh.chmod(0o755)
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(json.dumps({"kind": "describe", "text": text}) + "\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
    env.update({"GITHUB_REPOSITORY": "o/r", "NUMBER": "7", "PR": "8", "NO_COMMIT": no_commit, "RUNNER_TEMP": str(tmp_path),
                "GITHUB_OUTPUT": str(out / "output"), "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}"})
    ran = subprocess.run(["python3", str(ROOT / "scripts" / "autopilot.py"), "apply", str(outbox), "+describe"], capture_output=True, text=True, env=env)
    calls = [json.loads(l) for l in (out / "calls.jsonl").read_text().splitlines()] if (out / "calls.jsonl").exists() else []
    new = (out / "new-body.md").read_text(encoding="utf-8") if (out / "new-body.md").exists() else None
    output = (out / "output").read_text() if (out / "output").exists() else ""
    return ran, calls, new, output


def test_describe_rewrites_only_its_sections_and_keeps_closes_the_ticks_and_credits(tmp_path):
    ran, calls, new, output = apply_describe(tmp_path, "false")
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert new is not None, ran.stdout
    assert "The new text, true to the code." in new and "The old text." not in new
    assert "Ran tests/new_one.py and tests/new_two.py." in new and "The old test note." not in new
    assert "  Test: tests/new_one.py\n" in new and "  Test: tests/new_two.py (the second)\n" in new
    assert "tests/old_one.py" not in new and "tests/old_two.py" not in new
    assert "Closes #7." in new
    assert "- [x] **C1** Given a, when b, then c." in new and "- [ ] **C2** Given d, when e, then f." in new
    assert "- @alice: reported (https://github.com/o/r/issues/7)" in new
    assert "described=true" in output
    # A round that pushes commits sets the body alone: the push's review reads it.
    assert not any("--add-label" in c for c in calls)


def test_describe_refuses_a_criterion_the_checklist_does_not_have(tmp_path):
    ran, _, new, _ = apply_describe(tmp_path, "false", DESCRIBE + "- C9: tests/nine.py\n")
    assert ran.returncode != 0 and new is None


def test_a_round_with_no_commit_asks_for_a_full_review_before_the_edit(tmp_path):
    ran, calls, new, _ = apply_describe(tmp_path, "true")
    assert ran.returncode == 0, ran.stdout + ran.stderr
    label = [i for i, c in enumerate(calls) if c[:2] == ["pr", "edit"] and "--add-label" in c and "review:full" in c]
    edit = [i for i, c in enumerate(calls) if c[:2] == ["pr", "edit"] and "--body-file" in c]
    assert label and edit and label[0] < edit[0], calls


REVIEWED = "<!-- dx-review -->\nNo match.\n<!-- dx-review-record " + json.dumps(
    {"sha": HEAD, "count": 1, "risk": "low", "complexity": "low", "blocking": False, "description_matches": False}) + " -->"


def scope(tmp_path, full_label):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "comments.json").write_text(json.dumps([{"user": {"login": BOT}, "body": REVIEWED, "updated_at": "2026-11-21T10:00:00Z"}]))
    gh = f"""case "$1 $2" in
  "api repos/o/r/issues/8/comments") cat {tmp_path}/comments.json ;;
  "api repos/o/r/pulls/8/comments") echo '[]' ;;
  "pr view") echo {"true" if full_label else "false"} ;;
  *) echo '[]' ;;
esac"""
    env = {"BOT": BOT, "PR": "8", "HEAD": HEAD, "ACTION": "edited", "MAX_AUTO": "5", "MODEL": "m", "EFFORT": "low"}
    return run(step("claude-review.yml", "scope"), tmp_path, env=env, stubs={"gh": gh})


def test_the_edit_with_review_full_runs_a_full_review_not_reuse(tmp_path):
    assert scope(tmp_path / "a", False).output["mode"] == "reuse"
    ran = scope(tmp_path / "b", True)
    assert ran.code == 0, ran.stderr
    assert ran.output["mode"] == "full"


def test_the_full_reviews_record_carries_the_new_description_matches(tmp_path):
    verdict = next(s for _, s in __import__("steps").steps_of("claude-review.yml") if "dx-review-record" in str(s.get("run", ""))
                   and "OUT" in (s.get("env") or {}))
    out = {"risk": "low", "complexity": "low", "blocking": False, "type": "fix", "description_matches": True, "summary": "Fine.",
           "findings": [], "lessons": [], "resolved_threads": [], "criteria": []}
    posted = tmp_path / "posted.md"
    gh = f"""case "$*" in
  "pr comment"*) shift 2; while [ $# -gt 0 ]; do [ "$1" = --body ] && printf '%s' "$2" > {posted}; shift; done ;;
  "api repos/o/r/issues/8/comments"*) echo '[]' ;;
  *) echo '[]' ;;
esac"""
    (tmp_path / "temp").mkdir(parents=True, exist_ok=True)
    (tmp_path / "temp" / "open-threads.json").write_text("[]")
    (tmp_path / "temp" / "previous.json").write_text(json.dumps({"sha": HEAD, "count": 1, "description_matches": False}))
    env = {"BOT": BOT, "PR": "8", "OUT": json.dumps(out), "SHA": HEAD, "MODE": "full", "LAST": HEAD, "COUNT": "1", "MODEL": "m",
           "MAX_AUTO": "5", "FLOOR": "low", "KIND": "", "BODY": "The new body", "TRUSTED": "true", "REASONS": ""}
    ran = run(verdict, tmp_path, env=env, stubs={"gh": gh})
    assert posted.exists(), ran.stdout + ran.stderr
    record = json.loads(re.findall(r"<!-- dx-review-record (.*?) -->", posted.read_text())[-1])
    assert record["description_matches"] is True and record["mode"] == "full"
    assert ran.output.get("description_ok") == "true"
    assert ran.output.get("description_mismatch") == "false"


def verdict_step():
    return next(s for _, s in __import__("steps").steps_of("claude-review.yml") if "dx-review-record" in str(s.get("run", ""))
                and "OUT" in (s.get("env") or {}))


def reuse(tmp_path, recorded_text, matches):
    """The verdict step reusing a record of MATCHES for the text whose hash
    is RECORDED_TEXT, with the body "The body"."""
    import hashlib
    (tmp_path / "temp").mkdir(parents=True, exist_ok=True)
    text = hashlib.sha256(recorded_text.encode()).hexdigest()[:16]
    (tmp_path / "temp" / "previous.json").write_text(json.dumps(
        {"sha": HEAD, "count": 1, "risk": "low", "complexity": "low", "blocking": False, "type": "fix", "description_matches": matches, "text": text}))
    env = {"BOT": BOT, "PR": "8", "OUT": "", "SHA": HEAD, "MODE": "reuse", "LAST": HEAD, "COUNT": "1", "MODEL": "m",
           "MAX_AUTO": "5", "FLOOR": "low", "KIND": "", "BODY": "The body", "TRUSTED": "true", "REASONS": ""}
    ran = run(verdict_step(), tmp_path, env=env, stubs={"gh": "echo '[]'"})
    assert ran.code == 0, ran.stdout + ran.stderr
    return ran.output


def test_a_reused_verdict_on_an_edited_description_is_unchecked_not_a_mismatch(tmp_path):
    out = reuse(tmp_path, "An older body", True)
    assert (out["description_ok"], out["description_mismatch"]) == ("false", "false")
    # Nor when the older text was found wrong: the new one was not read.
    out = reuse(tmp_path / "b", "An older body", False)
    assert (out["description_ok"], out["description_mismatch"]) == ("false", "false")


def test_a_reused_verdict_on_the_same_description_keeps_its_mismatch(tmp_path):
    out = reuse(tmp_path, "The body", False)
    assert (out["description_ok"], out["description_mismatch"]) == ("false", "true")
    out = reuse(tmp_path / "b", "The body", True)
    assert (out["description_ok"], out["description_mismatch"]) == ("true", "false")
