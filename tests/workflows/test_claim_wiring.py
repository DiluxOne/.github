"""A person claims an issue (#488): issue-claim.yml, its callers, and the
autopilot's gate, wired as the decisions in scripts/claim.py and
scripts/autopilot.py need them."""
import subprocess
from pathlib import Path

import pytest
import yaml
from steps import run, step

ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def steps(wf, job):
    return wf["jobs"][job]["steps"]


def run_of(wf, job, sid):
    return next(s for s in steps(wf, job) if s.get("id") == sid)["run"]


def test_a_release_starts_the_autopilot_on_the_issue():
    jobs = workflow("issue-claim.yml")["jobs"]
    ap = jobs["autopilot"]
    assert ap["uses"].startswith("DiluxOne/.github/.github/workflows/autopilot.yml@")
    assert ap["with"]["mode"] == "start" and ap["with"]["issue"] == "${{ matrix.issue }}"
    assert set(ap["needs"]) == {"claim", "daily"} and ap["secrets"] == "inherit"
    # Both the event (`/unclaim`, `/adopt`) and the daily run (a release, a
    # stalled pull request closed) hand their issues to it.
    for job in ("claim", "daily"):
        assert f"needs.{job}.outputs.start" in ap["strategy"]["matrix"]["issue"] and f"needs.{job}.outputs.start" in ap["if"]
        assert jobs[job]["outputs"]["start"].startswith(f"${{{{ steps.{job}.outputs.start")
    assert "claim.py daily" in run_of(workflow("issue-claim.yml"), "daily", "daily")
    assert jobs["daily"]["if"] == "github.event_name == 'schedule'"
    # The daily run says which issues to start in its output.
    src = (ROOT / "scripts/claim.py").read_text(encoding="utf-8")
    assert 'fh.write(f"start={json.dumps(start)}\\n")' in src


def test_every_issues_caller_runs_the_claims_daily_and_on_comments():
    for path in (".github/workflows/issues.yml", "workflow-templates/issues.yml"):
        wf = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))
        on = wf[True] if True in wf else wf["on"]
        assert "schedule" in on and on["issue_comment"]["types"] == ["created"] and "pull_request_target" in on, path
        claim = wf["jobs"]["claim"]
        # This repository calls its own engine at `./` (#563 C10).
        assert claim["uses"] in ("./.github/workflows/issue-claim.yml",) or claim["uses"].startswith("DiluxOne/.github/.github/workflows/issue-claim.yml@"), path
        assert claim["secrets"] == "inherit", path
        # The other jobs keep to their own events: a comment or a pull
        # request never runs the triage, the reproduction or the acceptance.
        for name in ("triage", "repro", "repro-triaged", "accepted"):
            assert "github.event_name == 'issues'" in wf["jobs"][name]["if"], (path, name)


def test_the_jobs_with_the_key_never_check_out_a_pull_request():
    wf = workflow("issue-claim.yml")
    for job in ("claim", "daily"):
        for st in steps(wf, job):
            assert "actions/checkout" not in str(st.get("uses", "")), job
            assert "github.event.comment.body" not in str(st.get("run", "")) and "github.event.pull_request.head" not in str(st.get("run", "")), job


def test_yield_is_a_maintainers_and_may_cancel_the_autopilots_run():
    wf = workflow("issue-claim.yml")
    token = next(s for s in steps(wf, "claim") if s.get("id") == "bot")["with"]
    assert token["permission-actions"] == "write", "/yield cancels the autopilot's run"
    assert "github.event.comment.user.type != 'Bot'" in wf["jobs"]["claim"]["if"]
    src = (ROOT / "scripts/claim.py").read_text(encoding="utf-8")
    # The maintainer is read from GitHub, never from author_association.
    assert 'f"repos/{repo}/collaborators/{login}/permission"' in src and ".author_association" not in src
    assert 'perm = permission(repo, login) if name in ("yield", "adopt", "unclaim")' in src and "ok, why = may_act(name, login, perm, who)" in src
    # The autopilot's run is found by its prep job, named for the issue.
    prep = workflow("autopilot.yml")["jobs"]["prep"]["name"]
    assert prep.endswith("· may it run · #${{ inputs.issue || inputs.pr }}")
    assert r'may it run · #" + str(number)' in src


# The engine's scripts the autopilot's steps call, as stand-ins: each
# records its argv and answers from FAKE_<SCRIPT>_<SUBCOMMAND> (stdout) and
# FAKE_<SCRIPT>_<SUBCOMMAND>_RC (exit code). api-commit.py also records the
# branch and the parent of the commit it is asked to push.
FAKE = """import json, os, subprocess, sys
name, args = os.path.basename(sys.argv[0]), sys.argv[1:]
rec = [name] + args
if name == "api-commit.py":
    rec += [[subprocess.run(["git", "rev-parse", *a], capture_output=True, text=True).stdout.strip()
             for a in (["--abbrev-ref", "HEAD"], ["HEAD~1"])]]
with open(os.environ["DX_CALLS"], "a") as f:
    f.write(json.dumps(rec) + "\\n")
key = "FAKE_" + "".join(c if c.isalnum() else "_" for c in name[:-3] + "_" + (args[0] if args else "")).upper()
sys.stdout.write(os.environ.get(key, ""))
sys.exit(int(os.environ.get(key + "_RC", "0")))
"""
CENTRAL = {f".dx-central/scripts/{n}": FAKE for n in ("autopilot.py", "api-commit.py", "issue-schema.py", "receipts.py")}
GATED = {"may": ["autopilot.py", "may-start"], "draft": ["api-commit.py", "push"], "applied": ["autopilot.py", "push"]}


@pytest.mark.parametrize("rc", [1, 2], ids=["held", "unread"])
@pytest.mark.parametrize("job,sid", [("prep", "may"), ("draft", "draft"), ("apply", "applied")])
def test_the_autopilot_asks_who_holds_the_issue_before_it_starts_opens_or_pushes(tmp_path, job, sid, rc):
    """Held (1) or unread (2, it fails closed): the step ends, and starts,
    opens or pushes nothing."""
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    env = {"ISSUE": "7", "NUMBER": "7", "PR": "8", "BRANCH": "fix/7-a", "DEFAULT": "main", "MODE": "start",
           "DX_BOT_LOGIN": "dilux-bot[bot]", "DX_BOT_ID": "1", "DX_BOT_APP": "dilux-bot",
           "FAKE_AUTOPILOT_HOLDER": "@ana claimed it", "FAKE_AUTOPILOT_HOLDER_RC": str(rc)}
    ran = run(step("autopilot.yml", sid, job=job), tmp_path, env=env, files=CENTRAL, central=False, stubs={"gh": "echo 0"})
    assert ran.code == 0, ran.stdout + ran.stderr
    names = [c[:2] for c in ran.calls]
    assert ["autopilot.py", "holder"] in names
    assert not any(c[:2] == GATED[sid] for c in ran.calls), ran.calls
    assert not ran.of("api-commit.py")
    if sid == "may":
        assert ran.output["go"] == "false"
    else:
        assert ran.output["held"] == "@ana claimed it"


def test_the_run_that_steps_aside_says_so():
    wf = workflow("autopilot.yml")
    assert wf["jobs"]["draft"]["outputs"]["held"] == "${{ steps.draft.outputs.held }}"
    end = next(s for s in steps(wf, "apply") if s.get("id") == "end")
    assert end["env"]["HELD"] == "${{ needs.draft.outputs.held || steps.applied.outputs.held }}"


def adopted_draft(tmp_path, at_head=True):
    """The draft step on an issue whose pull request a maintainer adopted:
    (ran, the adopted commit)."""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    ident = ["-c", "user.name=a", "-c", "user.email=a@b", "-c", "commit.gpgsign=false"]
    git = lambda cwd, *a: subprocess.run(["git", *ident, *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(work))
    git(work, "commit", "-q", "--allow-empty", "-m", "chore: base")
    main = git(work, "rev-parse", "HEAD")
    git(work, "push", "-q", "origin", "main")
    git(work, "checkout", "-q", "-b", "adopted/41")
    git(work, "commit", "-q", "--allow-empty", "-m", "feat: ana's work")
    head = git(work, "rev-parse", "HEAD")
    git(work, "push", "-q", "origin", "adopted/41")
    git(work, "checkout", "-q", "main")
    for key in ("user.name", "user.email"):
        git(work, "config", key, "a")
    sha = head if at_head else main
    gh = """case "$*" in
  *"--json comments"*) echo 0 ;;
  *"--json title"*) echo "A thing" ;;
  "api repos/o/r/issues/7 "*) echo Feature ;;
  *) echo "### Spec" ;;
esac"""
    env = {"NUMBER": "7", "DEFAULT": "main", "LANE": "", "STARTED": "2026-11-01T00:00:00Z", "DX_BOT_APP": "dilux-bot",
           "FAKE_AUTOPILOT_DRAFT": '{"branch": "feat/7-a-thing", "body": "b", "title": "feat: a thing"}',
           "FAKE_AUTOPILOT_ADOPTED": f'{{"sha": "{sha}", "branch": "adopted/41", "pr": 41, "trailer": "Co-authored-by: ana <77+ana@users.noreply.github.com>"}}',
           "FAKE_API_COMMIT_PUSH_RC": "1"}
    ran = run(step("autopilot.yml", "draft", job="draft"), tmp_path, env=env, files=CENTRAL, central=False, stubs={"gh": gh})
    return ran, sha


def test_the_draft_of_an_adopted_pull_request_starts_at_the_head_the_maintainer_read(tmp_path):
    ran, sha = adopted_draft(tmp_path)
    pushes = ran.of("api-commit.py")
    assert pushes == [["push", "feat/7-a-thing", "--onto", sha, ["feat/7-a-thing", sha]]], ran.stdout + ran.stderr


def test_an_adopted_branch_that_moved_opens_no_draft(tmp_path):
    ran, _ = adopted_draft(tmp_path, at_head=False)
    assert ran.code == 0, ran.stdout + ran.stderr
    assert "is not at the commit the maintainer read" in ran.output["why"]
    assert not ran.of("api-commit.py")


def test_adopt_records_the_head_the_maintainer_read_and_the_draft_starts_there():
    import importlib.util
    spec = importlib.util.spec_from_file_location("claim", ROOT / "scripts/claim.py")
    c = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(c)
    head = "d" * 40
    acts, rec = c.plan_adopt({"number": 41, "author": "ana", "author_id": 77, "head": head}, "soydiloreto", 7, c.ts("2026-11-01T00:00:00Z"))
    assert rec["sha"] == head and rec["pr"] == 41 and rec["author"] == "ana"
    assert ("branch", rec["branch"], head) in acts, "only the commit read is copied"
    note = next(a[1] for a in acts if a[0] == "comment")
    spec = importlib.util.spec_from_file_location("autopilot", ROOT / "scripts/autopilot.py")
    ap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ap)
    assert ap.adopted_record([{"user": {"login": ap.BOT_LOGINS[1]}, "body": note}]) == rec, "what claim.py records is what the autopilot reads"
    assert acts[-1] == ("start", 7)
    # Its commits are pushed by autopilot.py push, which adds the trailer.
    assert "python3 .dx-central/scripts/autopilot.py push" in run_of(workflow("autopilot.yml"), "apply", "applied")


def test_at_its_cap_the_autopilot_says_anyone_may_claim_the_issue():
    may = next(s for s in steps(workflow("autopilot.yml"), "prep") if s.get("id") == "may")
    assert "anyone may `/claim` this issue" in may["env"]["OPEN_TO_CLAIM"]
    # Both caps: the runs (a continue) and the review rounds (a fix).
    assert may["run"].count('--body "${OPEN_TO_CLAIM:-}"') == 2
