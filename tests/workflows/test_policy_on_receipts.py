"""#804, C1: what the policy decided in a person's place is on the receipts,
never a label. auto-merge.yml writes a merge decision (scripts/receipts.py
merge-decision) where it once added `merged-by:policy`, before it enables
auto-merge, and withdraws one in force before it decides again."""
import re
from pathlib import Path

import yaml

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


def test_each_policy_merge_is_decided_on_the_receipts_before_auto_merge():
    job = workflow("auto-merge.yml")["jobs"]["decide"]
    for name, rule in DECIDING.items():
        run = code(step(job, name)["run"])
        withdraw = run.index("DECIDED=withdrawn")
        assert "receipts.py\" merge-decision" in run[withdraw:].splitlines()[0], name
        # A withdrawal that fails stops the step: never a decision left in force.
        assert "exit 1" in run[withdraw:].splitlines()[1], name
        decide = run.index("DECIDED=policy")
        line = run[decide:].splitlines()[0]
        assert f'RULE="{rule}"' in line and "merge-decision" in line, (name, line)
        assert "|| true" not in line, name
        enable = run.index("--auto ")
        off = run.index("--disable-auto")
        assert off < withdraw < decide < enable, name
        # Every early "a person merges" exit comes after the withdrawal.
        for m in re.finditer(r'person "|A human merges this one', run):
            assert m.start() > withdraw, (name, m.group())


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
    run = code(s["run"])
    planned = run.index('if [ "$PLANNED" = true ]')
    block = run[planned:run.index("\nfi", planned)]
    assert "release-issue.py planned-mode" in block and "receipts.py lane get" in block and "policy/autonomy.yml#planned-release" in block
    # It waits for milestones.py's decision, a bounded while, and a read that fails stops it.
    assert "for _ in $(seq 1 18)" in block and "sleep 10" in block and 'if [ "$rc" = 2 ]' in block
    # Before anything is said or opened.
    assert planned < run.index("DX_AUTOPILOT") and planned < run.index("next-version.py")


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
                assert 'EVIDENCE_JSON="$(' not in line or "NUMBER=" not in line.split("EVIDENCE_JSON")[0] and "LANE=" not in line.split("EVIDENCE_JSON")[0], (wf, line)
