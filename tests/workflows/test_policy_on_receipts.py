"""#804, C1: what the policy decided in a person's place is on the receipts,
never a label. auto-merge.yml writes a merge decision (scripts/receipts.py
merge-decision) where it once added `merged-by:policy`, before it enables
auto-merge, and withdraws one in force before it decides again."""
import json
import re
from pathlib import Path

import pytest
import yaml

import steps as steps_lib

ROOT = Path(__file__).resolve().parents[2]
POLICY_LABELS = ("accepted-by:policy", "merged-by:policy")


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def step(job, name):
    return next(s for s in job["steps"] if s.get("name") == name)


def code(script):
    """The script without its comments."""
    return "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))


DECIDING = {
    "An autopilot pull request": "policy/autonomy.yml#lanes.$LANE.merge",
    "A revert pull request (G8)": "policy/autonomy.yml#lanes.platform.merge",
    "A release pull request": "policy/autonomy.yml#lanes.release.merge",
    "A sync run's pull request": "policy/autonomy.yml#lanes.$lane.merge",
}


def test_auto_merge_sets_no_policy_label():
    text = code((ROOT / ".github/workflows/auto-merge.yml").read_text(encoding="utf-8"))
    for label in POLICY_LABELS:
        assert label not in text, label


BOT = "dilux-bot[bot]"
HEAD = "h" * 40

# The central checkout's scripts, as stand-ins that record their call (the
# script, its arguments, the DECIDED and RULE they get) and answer what the
# test says: FAKE maps "script verb" (and "receipts.py merge-decision
# <DECIDED>") to [exit code, output].
FAKE_SCRIPT = """import json, os, sys
name = os.path.basename(sys.argv[0])
call = [name] + sys.argv[1:] + [f"{k}={os.environ[k]}" for k in ("DECIDED", "RULE") if k in os.environ]
with open(os.environ["DX_CALLS"], "a") as f:
    f.write(json.dumps(call) + "\\n")
fake = json.loads(os.environ.get("FAKE", "{}"))
key = " ".join([name] + sys.argv[1:2] + ([os.environ["DECIDED"]] if "DECIDED" in os.environ else []))
code, out = fake.get(key, fake.get(" ".join([name] + sys.argv[1:2]), [0, ""]))
print(out)
sys.exit(code)
"""
SCRIPTS = ("receipts.py", "credits.py", "autopilot.py", "revert.py", "autonomy.py", "release-issue.py", "repro-lane.py",
           "surface.py", "no-widening.py", "repro-ways.py")

# git: the central checkout is already there; the release's proof makes
# the head's tree.
GIT = """case " $* " in
  *" init "*) mkdir -p "${@: -1}" ;;
  *" rev-parse "*) echo central-sha ;;
  *" write-tree "*) echo tree-sha ;;
esac"""

# gh: one issue closed, a bot's lane label on it, a release issue's title,
# one file changed, no repository autonomy.yml, the bot's single commit.
GH = """case "$*" in
  "pr view "*closingIssuesReferences*) echo 5 ;;
  "issue view 5 "*"--json labels "*) echo platform ;;
  "issue view 5 "*title,labels*) echo "Release 1.2.3" ;;
  "issue view 5 "*) echo "body" ;;
  "api repos/o/r/contents/.github/autonomy.yml"*) echo "HTTP 404: Not Found" >&2; exit 1 ;;
  "api repos/o/r/pulls/8/files"*) echo a.txt ;;
  "api repos/o/r/pulls/8/commits"*) printf '%s\\t%s\\t1\\tbase-sha\\n' "$HEAD_SHA" "$DX_BOT_LOGIN" ;;
  "api repos/o/r/git/commits/"*) echo tree-sha ;;
  "api repos/o/r/issues/8/comments"*) echo '[]' ;;
  "api repos/o/r/issues/5/comments"*) ;;
  "api repos/o/r/actions/runs"*) echo '{"workflow_runs": []}' ;;
  "api repos/o/r/commits/"*) echo '{"check_runs": []}' ;;
  "api repos/o/r/rules/"*) echo '[]' ;;
  *) ;;
esac"""

ENV = {"PR": "8", "HEAD": HEAD, "HEAD_SHA": HEAD, "BASE": "b" * 40, "BASE_SHA": "b" * 40, "BASE_REF": "main",
       "AUTHOR": BOT, "PR_AUTHOR": BOT, "DX_BOT_LOGIN": BOT, "LABELS": "autopilot", "BLOCKING": "false",
       "DESCRIPTION_OK": "true", "DX_AUTOPILOT": "on", "CENTRAL_REF": "main"}

# What makes each step reach its policy decision.
DECIDES = {
    "An autopilot pull request": {"autopilot.py lane": [0, "platform"], "autopilot.py decide": [0, "the lane allows it"]},
    "A revert pull request (G8)": {"revert.py decide": [0, "a revert of a merged change"]},
    "A release pull request": {"release-issue.py verify": [0, '{"ok": true, "issue": "5", "why": "accepted"}'],
                               "release-issue.py argv": [0, '["true"]']},
    "A sync run's pull request": {"autonomy.py lane-merge": [0, "the lane merges"]},
}
DECLINES = {
    "An autopilot pull request": {"autopilot.py lane": [0, "platform"], "autopilot.py decide": [1, "the risk is high"]},
    "A revert pull request (G8)": {"revert.py decide": [1, "not a revert"]},
    "A release pull request": {"release-issue.py verify": [0, '{"ok": false, "why": "not accepted"}']},
    "A sync run's pull request": {"autonomy.py lane-merge": [1, "the lane does not merge"]},
}


def decide(tmp_path, name, fake):
    import json
    central = tmp_path / "temp" / "central" / "scripts"
    central.mkdir(parents=True)
    for script in SCRIPTS:
        (central / script).write_text(FAKE_SCRIPT, encoding="utf-8")
    (tmp_path / "temp" / "central" / "repos.yml").write_text("repos: {}\n", encoding="utf-8")
    s = steps_lib.step("auto-merge.yml", name, job="decide")
    return steps_lib.run(s, tmp_path, env=dict(ENV, FAKE=json.dumps(fake)), stubs={"gh": GH, "git": GIT, "yq": "echo '?'"})


def events(ran):
    """What the step did to the merge, in order: auto-merge off or on, and
    each merge decision written to the receipts."""
    out = []
    for call in ran.calls:
        if call[:2] == ["gh", "pr"] and "--disable-auto" in call:
            out.append("off")
        elif call[:2] == ["gh", "pr"] and "--auto" in call:
            assert call[call.index("--match-head-commit") + 1] == HEAD, call
            out.append("on")
        elif call[:2] == ["receipts.py", "merge-decision"]:
            out.append(" ".join(call[2:]))
    return out


@pytest.mark.parametrize("name", sorted(DECIDING))
def test_each_policy_merge_is_decided_on_the_receipts_before_auto_merge(tmp_path, name):
    ran = decide(tmp_path, name, DECIDES[name])
    assert ran.code == 0, ran.stdout + ran.stderr
    rule = DECIDING[name].replace("$LANE", "platform").replace("$lane", "platform")
    assert events(ran) == ["off", "DECIDED=withdrawn", f"DECIDED=policy RULE={rule}", "on"], ran.stdout


@pytest.mark.parametrize("name", sorted(DECIDING))
def test_a_person_merges_with_the_decision_withdrawn_and_auto_merge_off(tmp_path, name):
    ran = decide(tmp_path, name, DECLINES[name])
    assert ran.code == 0, ran.stdout + ran.stderr
    assert events(ran) == ["off", "DECIDED=withdrawn"], ran.stdout
    assert "A human merges this one" in ran.stdout


@pytest.mark.parametrize("name", sorted(DECIDING))
def test_a_withdrawal_that_fails_stops_the_step_with_auto_merge_off(tmp_path, name):
    ran = decide(tmp_path, name, dict(DECIDES[name], **{"receipts.py merge-decision withdrawn": [1, ""]}))
    assert ran.code == 1, ran.stdout + ran.stderr
    assert events(ran) == ["off", "DECIDED=withdrawn"], ran.stdout
    assert "merge decision could not be withdrawn" in ran.stdout


# The writers of `accepted-by:policy` write the lane's decision instead, and
# nothing adds or removes the policy's labels any more but the migration.
MIGRATION = {"scripts/policy-receipts.py", ".github/workflows/policy-receipts.yml"}


def test_no_workflow_or_script_sets_a_policy_label():
    paths = list((ROOT / ".github/workflows").glob("*.yml")) + list((ROOT / "scripts").glob("*.py")) + list((ROOT / "scripts").glob("*.sh"))
    for path in paths:
        rel = path.relative_to(ROOT).as_posix()
        if rel in MIGRATION:
            continue
        text = path.read_text(encoding="utf-8")
        for label in POLICY_LABELS:
            for verb in ("--add-label", "--remove-label", "--label"):
                assert not re.search(rf"{verb}\s+\"?{re.escape(label)}", text), (rel, verb, label)
            assert not re.search(rf"\"{verb}\",\s*\"{re.escape(label)}\"", text), (rel, verb, label)


def test_labels_yml_no_longer_defines_them():
    names = {l["name"] for l in yaml.safe_load((ROOT / "labels.yml").read_text(encoding="utf-8"))["labels"]}
    assert not names & set(POLICY_LABELS)
    assert {"lane:release", "lane:platform", "lane:bugfix-reproduced", "lane:org-sync"} <= names


def test_lane_writers_write_the_lane_decision():
    for wf, step_name, lane in (("issue-repro.yml", "Hand it to the bugfix-reproduced lane", "LANE=bugfix-reproduced"),
                                ("runner-image.yml", "Record the build", "LANE=platform")):
        job_steps = [s for j in workflow(wf)["jobs"].values() for s in j.get("steps", [])]
        run = code(next(s for s in job_steps if s.get("name") == step_name)["run"])
        assert lane in run and "receipts.py lane-decision" in run, wf
    lane_job = workflow("issue-accepted.yml")["jobs"]["lane"]
    run = code(step(lane_job, "Ask the policy, and say so on the issue")["run"])
    assert "DECIDED=policy" in run and "DECIDED=withdrawn" in run and "receipts.py lane-decision" in run
    token = step(lane_job, "App token")["with"]
    assert token["permission-contents"] == "write"
    claim = (ROOT / "scripts/claim.py").read_text(encoding="utf-8")
    assert '"lane-decision"' in claim and 'LANE="bugfix-reproduced"' in claim


def test_the_planned_release_starts_on_lane_release_and_reads_the_receipts():
    job = workflow("issue-accepted.yml")["jobs"]["release"]
    cond = " ".join(str(job["if"]).split())
    assert "github.event.label.name == 'lane:release' && github.event.sender.login == vars.DX_BOT_LOGIN" in cond
    s = step(job, "Open it, or say why not")
    assert s["env"]["PLANNED"] == "${{ github.event.label.name == 'lane:release' }}"


def planned(tmp_path, fake):
    """The release job's step for a plan's `lane:release`, with the
    organisation's DX_AUTOPILOT off: it says so once the plan's acceptance
    is found, and before anything else is read or opened."""
    import json
    files = {".git/info/exclude": ""}
    files.update({f".dx-central/scripts/{n}": FAKE_SCRIPT for n in ("release-issue.py", "receipts.py", "next-version.py")})
    s = steps_lib.step("issue-accepted.yml", "Open it, or say why not", job="release")
    env = {"PLANNED": "true", "NUMBER": "5", "DX_AUTOPILOT": "off", "FAKE": json.dumps(fake)}
    return steps_lib.run(s, tmp_path, env=env, files=files, central=False, stubs={"gh": "", "sleep": ""})


ACCEPTED = json.dumps({"lane": "release", "rule": "policy/autonomy.yml#planned-release"})


def test_a_planned_release_goes_on_once_the_plans_acceptance_is_on_the_receipts(tmp_path):
    ran = planned(tmp_path, {"release-issue.py planned-mode": [0, "auto"], "receipts.py lane": [0, ACCEPTED]})
    assert ran.code == 0, ran.stdout + ran.stderr
    assert ran.of("receipts.py") == [["lane", "get"]] and ran.of("sleep") == []
    assert "DX_AUTOPILOT" in ran.stdout and ran.of("gh"), "it went on to what it says on the issue"


def test_a_planned_release_waits_a_bounded_while_then_leaves_it_to_a_person(tmp_path):
    ran = planned(tmp_path, {"release-issue.py planned-mode": [0, "auto"], "receipts.py lane": [0, "null"]})
    assert ran.code == 0, ran.stdout + ran.stderr
    assert len(ran.of("receipts.py")) == 18 and ran.of("sleep") == [["10"]] * 18
    assert "not accepted by the plan; a person accepts it" in ran.stdout
    assert ran.of("gh") == [] and ran.of("next-version.py") == []


def test_a_planned_release_whose_receipts_cannot_be_read_stops(tmp_path):
    ran = planned(tmp_path, {"release-issue.py planned-mode": [0, "auto"], "receipts.py lane": [2, ""]})
    assert ran.code == 1 and "receipts could not be read" in ran.stdout
    assert ran.of("gh") == [] and ran.of("sleep") == []


def test_a_planned_release_not_in_auto_is_a_persons_to_confirm(tmp_path):
    ran = planned(tmp_path, {"release-issue.py planned-mode": [0, "manual"]})
    assert ran.code == 0 and "confirmed by a person" in ran.stdout
    assert ran.of("receipts.py") == [] and ran.of("gh") == []


def test_the_receipt_and_the_report_route_on_the_lane_decision():
    job = workflow("issue-accepted.yml")["jobs"]["receipt"]
    close = step(job, "Close the report it came from")
    assert "steps.receipt.outputs.lane == 'bugfix-reproduced'" in close["if"]
    run = code(step(job, "Write the receipt")["run"])
    assert run.index("receipts.py lane get") < run.index("receipts.py merged")


def test_a_lane_decisions_evidence_is_read_before_its_prefix_assignments():
    # Bash shows a command's earlier prefix assignments to its later ones:
    # `NUMBER=$lane EVIDENCE_JSON="$(... $NUMBER ...)"` would name the lane's
    # issue as the report. The evidence is read first, on its own line.
    for wf in ("issue-repro.yml", "issue-accepted.yml", "runner-image.yml"):
        for line in code((ROOT / ".github/workflows" / wf).read_text(encoding="utf-8")).splitlines():
            if "receipts.py lane-decision" in line or line.rstrip().endswith("\\"):
                assert not re.search(r'\b(NUMBER|LANE)=.*EVIDENCE_JSON="\$\(', line), (wf, line)
