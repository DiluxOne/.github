"""A person claims an issue (#488): issue-claim.yml, its callers, and the
autopilot's gate, wired as the decisions in scripts/claim.py and
scripts/autopilot.py need them."""
from pathlib import Path

import yaml

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
        assert claim["uses"].startswith("DiluxOne/.github/.github/workflows/issue-claim.yml@") and claim["secrets"] == "inherit", path
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


def test_the_autopilot_asks_who_holds_the_issue_before_it_starts_opens_or_pushes():
    wf = workflow("autopilot.yml")
    may = run_of(wf, "prep", "may")
    draft = run_of(wf, "draft", "draft")
    applied = run_of(wf, "apply", "applied")
    for where, text, before in (("prep", may, "autopilot.py may-start"), ("draft", draft, "api-commit.py push"), ("apply", applied, "autopilot.py push")):
        gate = text.index("autopilot.py holder")
        assert gate < text.index(before), f"{where}: the gate comes before {before}"
        # Any exit but 0 stops it (held, or unread: it fails closed).
        assert '|| rc=$?' in text[gate:gate + 80] and 'if [ "$rc" -ne 0 ]' in text[gate:], where
    assert 'echo "go=false" >> "$GITHUB_OUTPUT"; exit 0' in may[may.index("autopilot.py holder"):may.index("Who accepted it")]
    assert "the outbox" not in applied and applied.index("autopilot.py holder") < applied.index("autopilot.py apply .dx-out/outbox.jsonl")
    # The run that steps aside says so, and is no silent end.
    assert wf["jobs"]["draft"]["outputs"]["held"] == "${{ steps.draft.outputs.held }}"
    end = next(s for s in steps(wf, "apply") if s.get("id") == "end")
    assert end["env"]["HELD"] == "${{ needs.draft.outputs.held || steps.applied.outputs.held }}"


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
    draft = run_of(workflow("autopilot.yml"), "draft", "draft")
    adopted = draft[draft.index("autopilot.py adopted"):draft.index("api-commit.py push")]
    assert '[ "$(git rev-parse FETCH_HEAD)" != "$sha" ]' in adopted and 'git checkout -q -b "$branch" "$sha"' in adopted and "onto=$sha" in adopted
    # Its commits are pushed by autopilot.py push, which adds the trailer.
    assert "python3 .dx-central/scripts/autopilot.py push" in run_of(workflow("autopilot.yml"), "apply", "applied")
