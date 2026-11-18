"""#832 C2: the autopilot stopped with `needs-human` and a decider answers on
its pull request: `needs-human` comes off and dilux-bot adds
`autopilot:continue`, with no label added by a person. The answer may be a
review comment in a thread (pull_request_review_comment), and a later
comment of dilux-bot's (the review's summary, a reply) no longer hides the
stop; a `needs-human` a maintainer added themselves stays. review-reply.yml's
answer step runs as written, with gh stood in."""
import json
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BOT = "dilux-bot[bot]"
STOP = "<!-- dx-autopilot-stop -->\nThe autopilot stopped: the Spec needs a person."
SILENT = "<!-- dx-autopilot-silent -->\nThe autopilot ended with nothing to say."
SUMMARY = "<!-- dx-review-summary -->\nThe review found nothing blocking."


def wf():
    return yaml.safe_load((ROOT / ".github/workflows/review-reply.yml").read_text(encoding="utf-8"))


def job():
    return wf()["jobs"]["answer"]


def step():
    return next(s for s in job()["steps"] if s.get("id") == "back")


def answer(tmp_path, comments, labelled_by=BOT, event="pull_request_review_comment"):
    """The gh calls the step makes when a maintainer answers on pull request
    #9 (labelled `autopilot` and `needs-human`, closing #7), whose comments
    are COMMENTS ((login, body), oldest first) and whose `needs-human` was
    last added by LABELLED_BY. EVENT: how the answer came, as the step's
    env reads it from the event."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    log.write_text("")
    (tmp_path / "comments.json").write_text(json.dumps([{"user": {"login": u}, "body": b} for u, b in comments]))
    (tmp_path / "events.json").write_text(json.dumps([
        {"event": "labeled", "label": {"name": "autopilot"}, "actor": {"login": BOT}},
        {"event": "labeled", "label": {"name": "needs-human"}, "actor": {"login": BOT}},
        {"event": "unlabeled", "label": {"name": "needs-human"}, "actor": {"login": BOT}},
        {"event": "labeled", "label": {"name": "needs-human"}, "actor": {"login": labelled_by}},
        {"event": "labeled", "label": {"name": "bug"}, "actor": {"login": "someone"}}]))
    (bin_dir / "gh").write_text(
        "#!/bin/bash\n"
        f'echo "gh $*" >> "{log}"\n'
        'case "$*" in\n'
        "  *closingIssuesReferences*) echo 7 ;;\n"
        "  *'--json labels --jq [.labels[].name] | index'*) echo false ;;\n"
        "  'pr view 9 '*'--json labels'*) echo autopilot,needs-human ;;\n"
        "  *'--json labels'*) echo bug ;;\n"
        "  *'/events'*)\n"
        '    while [ $# -gt 0 ]; do [ "$1" = --jq ] && { shift; q=$1; }; shift; done\n'
        f'    jq -r "$q" "{tmp_path / "events.json"}" ;;\n'
        "  *'/comments'*)\n"
        '    while [ $# -gt 0 ]; do [ "$1" = --jq ] && { shift; q=$1; }; shift; done\n'
        f'    jq -r "$q" "{tmp_path / "comments.json"}" ;;\n'
        "esac\n")
    (bin_dir / "gh").chmod(0o755)
    (tmp_path / ".dx-central/scripts").mkdir(parents=True)
    (tmp_path / ".dx-central/scripts/deciders.py").write_text("print('decides')\n")
    (tmp_path / ".dx-central/scripts/receipts.py").write_text("import sys\nprint('null' if sys.argv[1:3] == ['state', 'get'] else '')\n")
    # How the run ended (#696): the real script's run-end.
    (tmp_path / ".dx-central/scripts/autopilot.py").write_text(
        f"import runpy, sys\nsys.path.insert(0, {str(ROOT / 'scripts')!r})\nrunpy.run_path({str(ROOT / 'scripts/autopilot.py')!r}, run_name='__main__')\n")
    out = tmp_path / "out"
    out.write_text("")
    # The step's env, as the event gives it: a review comment has no
    # `issue`, only its `pull_request`.
    ctx = {"issue_comment": {"github.event.issue.number": "9", "github.event.issue.pull_request": {"url": "x"}, "github.event.pull_request": None,
                             "github.event.pull_request.number": ""},
           "pull_request_review_comment": {"github.event.issue.number": "", "github.event.issue.pull_request": None, "github.event.pull_request": {"number": 9},
                                           "github.event.pull_request.number": "9"}}[event]
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", GITHUB_OUTPUT=str(out), GITHUB_REPOSITORY="o/r", RUNNER_TEMP=str(tmp_path),
               DX_BOT_LOGIN=BOT, LOGIN="maintainer")
    for key, expr in step()["env"].items():
        if key in ("NUMBER", "IS_PR"):
            env[key] = evaluate(expr, ctx)
    done = subprocess.run(["bash", "-c", step()["run"]], env=env, capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    return log.read_text()


def evaluate(expr, ctx):
    """The few GitHub expressions the step's NUMBER and IS_PR are written
    in: `a || b` and `x != null`, joined by `||`."""
    inner = expr.strip()
    assert inner.startswith("${{") and inner.endswith("}}"), expr
    inner = inner[3:-2].strip()
    parts = [p.strip() for p in inner.split("||")]
    if all(p.endswith("!= null") for p in parts):
        return str(any(ctx.get(p[:-len("!= null")].strip()) is not None for p in parts)).lower()
    for p in parts:
        if ctx.get(p):
            return ctx[p]
    return ""


def resumed(calls):
    return ("gh api -X DELETE repos/o/r/issues/9/labels/needs-human" in calls
            and "gh issue edit 7 --repo o/r --add-label autopilot:continue" in calls)


def test_the_answer_job_reads_review_comments_too():
    on = job()["if"]
    assert "pull_request_review_comment" in on and "issue_comment" in on


def test_c2_an_answer_in_a_review_thread_resumes_the_stopped_autopilot(tmp_path):
    calls = answer(tmp_path, [(BOT, STOP)], event="pull_request_review_comment")
    assert resumed(calls), calls


def test_c2_a_later_comment_of_the_bot_s_does_not_hide_the_stop(tmp_path):
    for i, (end, event) in enumerate(((STOP, "issue_comment"), (SILENT, "issue_comment"), (STOP, "pull_request_review_comment"))):
        run = tmp_path / str(i)
        run.mkdir()
        calls = answer(run, [(BOT, end), (BOT, SUMMARY), (BOT, "A reply in a thread.")], event=event)
        assert resumed(calls), (end, event, calls)


def test_c2_a_needs_human_a_maintainer_added_stays(tmp_path):
    calls = answer(tmp_path, [(BOT, STOP), (BOT, SUMMARY)], labelled_by="maintainer", event="issue_comment")
    assert "labels/needs-human" not in calls and "autopilot:continue" not in calls, calls


def test_c2_no_stop_no_continue(tmp_path):
    for i, comments in enumerate(([(BOT, SUMMARY)], [("someone", STOP)])):
        run = tmp_path / str(i)
        run.mkdir()
        calls = answer(run, comments)
        assert "labels/needs-human" not in calls and "autopilot:continue" not in calls, comments


def runs(event_name, head="o/r", body="why?"):
    """Whether the answer job's `if:` lets EVENT_NAME through, on o/r, for a
    pull request whose head is HEAD: the expression, read as Python."""
    import re
    expr = " ".join(job()["if"].split())
    ctx = {"github.event_name": event_name, "github.event.action": "created",
           "github.event.sender.type": "User", "github.event.comment.body": body,
           "github.repository": "o/r",
           "github.event.pull_request.head.repo.full_name": head if event_name == "pull_request_review_comment" else None}
    py = re.sub(r"\bgithub(\.[A-Za-z_]+)+", lambda m: repr(ctx[m.group(0)]), expr)
    py = py.replace("&&", " and ").replace("||", " or ").replace("!=", "<>").replace("!", " not ").replace("<>", "!=")
    py = re.sub(r"startsWith\(", "_starts(", py)
    return eval(py, {"_starts": lambda a, b: (a or "").lower().startswith(b.lower())})


def test_the_answer_job_leaves_a_fork_s_review_comment_out():
    # A fork's pull request runs without secrets: the App token would fail.
    assert runs("pull_request_review_comment", head="o/r")
    assert not runs("pull_request_review_comment", head="fork/r")
    assert runs("issue_comment")
    assert not runs("issue_comment", body="/coauthor @x")
