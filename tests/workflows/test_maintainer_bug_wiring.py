"""A maintainer's own Bug (C2, #564): the triage never classifies it (so no
reproduction, and nothing of one on its board's state, #801);
complete, it is accepted with its writing, sealed in its author's name, and
the autopilot starts on it; the G1 check leaves it to the triage. Both the
triage and the autopilot accept it only for an author `who-decides` lets
add `accepted` (#624)."""
import importlib.util
import subprocess
from pathlib import Path
from unittest import mock

import yaml

try:
    import steps  # tests/workflows/steps.py: it runs a workflow's step with stubs
except ModuleNotFoundError:  # Test first's base has no steps.py (#845): there each call to it fails an assertion
    steps = mock.Mock(**{f"{n}.side_effect": AssertionError("tests/workflows/steps.py is missing") for n in ("evaluate", "run", "step", "workflow")})
run, step = steps.run, steps.step

ROOT = Path(__file__).resolve().parents[2]


def load_autopilot():
    spec = importlib.util.spec_from_file_location("autopilot_own", ROOT / "scripts" / "autopilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
    # An opened or accepted issue starts; only `autopilot:continue` continues (an edit's mode is edit-start's, #1002).
    expr = steps.EXPR.fullmatch(auto["with"]["mode"]).group(1)
    for action, label, want in (("opened", "", "start"), ("labeled", "accepted", "start"), ("labeled", "autopilot:continue", "continue")):
        ctx = {"github.event.action": action, "github.event.label.name": label, "needs.edit-start.outputs.mode": ""}
        assert steps.evaluate(expr, ctx) == want, (action, label)


PRD = ("### Problem\n\nIt breaks.\n\n### Scope\n\n- Fix it.\n\n### Out of scope\n\n- Nothing.\n\n"
       "### Acceptance criteria\n\n- C1: Given a page, when it loads, then it does not break.\n\n### Criticality\n\nNormal\n")


def gh_for(role, comments="echo '[]'"):
    """A stand-in for gh: issue #7 is a Bug its author holds ROLE on, and
    COMMENTS answers for its comments."""
    return f"""case "$*" in
  "api graphql"*) echo 2026-11-08T10:00:00Z ;;
  "api repos/o/r/issues/7/comments"*) {comments} ;;
  "api repos/o/r/issues/7 --jq"*) echo Bug ;;
  "api repos/o/r/collaborators/"*) echo {role} ;;
esac"""


def g1_on_opening(tmp_path, role):
    check = step("issue-accepted.yml", "check", job="ready")
    env = {"ACTION": "opened", "AUTHOR": "boss", "BODY": PRD, "GH_TOKEN": "t", "LABEL": "accepted", "NUMBER": "7",
           "SENDER": "boss", "DX_BOT_APP": "dilux-bot", "DECIDERS_FIXTURE": str(tmp_path / "deciders.json")}
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "deciders.json").write_text('{"roles": {}, "codeowners": "", "files": []}')
    return run(check, tmp_path, env=env, stubs={"gh": gh_for(role)})


def test_the_g1_check_on_opening_leaves_it_to_the_triage(tmp_path):
    ran = g1_on_opening(tmp_path, "admin")
    assert ran.code == 0, ran.stderr
    assert ran.output["ready"] == "true"
    assert not [c for c in ran.of("gh") if c[:2] in (["issue", "edit"], ["issue", "comment"])], ran.calls
    assert "the triage accepts it with its writing" in ran.stdout


def test_the_g1_check_on_opening_labels_anyone_elses_complete_issue(tmp_path):
    ran = g1_on_opening(tmp_path, "write")
    assert ran.code == 0, ran.stderr
    assert ["issue", "edit", "7", "--repo", "o/r", "--add-label", "awaiting-acceptance"] in ran.of("gh")


def test_the_gate_and_the_autopilot_read_the_seal_as_its_authors_acceptance():
    gate = (ROOT / "scripts/issue-gate.sh").read_text(encoding="utf-8")
    assert 'receipts.py" own-bug' in gate and 'own_bug "$answer" "$n"' in gate
    autopilot = (ROOT / "scripts/autopilot.py").read_text(encoding="utf-8")
    assert "own, own_why = own_bug_status(repo, number, issue)" in autopilot
    assert "which_lane(pol, issue, autonomy.read_run(issue, repo), repo, var, own, own_why)" in autopilot


def test_the_autopilot_asks_who_decides_for_the_seals_author(monkeypatch):
    autopilot = load_autopilot()
    asked = []

    def fake_run(cmd, **kw):
        asked.append((cmd[1:], kw["env"]["NUMBER"], kw["env"]["GITHUB_REPOSITORY"]))
        return subprocess.CompletedProcess(cmd, 0 if cmd[-1] == "boss" else 1, "ok\n" if cmd[-1] == "boss" else "", "no\n")

    monkeypatch.setattr(autopilot.subprocess, "run", fake_run)
    assert autopilot._may_accept("o/r", 7, "boss") == (True, "ok")
    assert autopilot._may_accept("o/r", 7, "alice") == (False, "no")
    assert asked[0] == ([str(ROOT / "scripts" / "deciders.py"), "may", "accepted", "boss"], "7", "o/r")


DECIDER = """#!/usr/bin/env python3
import os, sys
open(os.environ["DECIDER_LOG"], "a").write(" ".join(sys.argv[1:]) + "\\n")
if sys.argv[1] == "who":
    print("@carol")
sys.exit(int(os.environ.get("MAY_RC", "0")) if sys.argv[1] == "may" else 0)
"""


def own_bug(tmp_path, may_rc):
    """triage-act.sh own-bug for an admin's complete Bug, with who-decides
    answering MAY_RC; (gh calls, outputs, the receipts' files, deciders' log)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    decider, log, seals = tmp_path / "deciders.py", tmp_path / "deciders.log", tmp_path / "seals"
    decider.write_text(DECIDER)
    log.write_text("")
    seals.mkdir()
    (tmp_path / "prd.md").write_text(PRD)
    script = {"run": f'bash "{ROOT}/scripts/triage-act.sh" own-bug'}
    env = {"DECIDERS_PY": str(decider), "DECIDER_LOG": str(log), "MAY_RC": str(may_rc), "RECEIPTS_FIXTURE": str(seals),
           "AUTOPILOT_JSON": "null", "LABELS_JSON": "[]", "HELD": "", "NUMBER": "7", "AUTHOR": "boss",
           "BODY": str(tmp_path / "prd.md"), "GH_TOKEN": "t"}
    ran = run(script, tmp_path, env=env, stubs={"gh": gh_for("admin", comments=":")}, central=False)
    files = sorted(str(p.relative_to(seals)) for p in seals.rglob("*") if p.is_file())
    return ran, files, log.read_text().splitlines()


def test_own_accept_asks_who_decides_before_it_seals(tmp_path):
    ran, files, asked = own_bug(tmp_path, 0)
    assert ran.code == 0, ran.stderr
    assert asked == ["may accepted boss"]
    assert ran.output == {"own": "true", "accepted": "true"}
    assert any(f.startswith("issues/7/prd-") for f in files), files
    assert ["issue", "edit", "7", "--repo", "o/r", "--add-label", "accepted"] in ran.of("gh")


def test_own_accept_refused_by_who_decides_neither_seals_nor_accepts(tmp_path):
    for rc in (1, 2):
        ran, files, asked = own_bug(tmp_path / str(rc), rc)
        assert ran.code == 0, ran.stderr
        assert ran.output == {"own": "true", "accepted": "false"}
        assert not any(f.startswith("issues/7/prd-") for f in files), files
        assert ["issue", "edit", "7", "--repo", "o/r", "--add-label", "accepted"] not in ran.of("gh")
        assert ["issue", "edit", "7", "--repo", "o/r", "--add-label", "awaiting-acceptance"] in ran.of("gh")


def test_its_board_carries_no_reproduction(tmp_path):
    ran, _, _ = own_bug(tmp_path, 0)
    assert ran.code == 0, ran.stderr
    boards = [c[-1] for c in ran.of("gh") if c[:2] == ["issue", "comment"] and c[-1].startswith("<!-- dx-board -->")]
    assert len(boards) == 1, ran.calls
    assert "| G2 Accepted | ✓ by boss" in boards[0]
    assert "repro" not in boards[0].lower()
    assert not [c for c in ran.of("gh") if "--add-label" in c and any(l.startswith(("bug:", "repro:", "layer:")) for l in c)]
