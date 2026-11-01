"""A Bug a maintainer wrote (#564 C2): accepted with its writing by the
maintainer-bug lane, never classified, never reproduced; the autopilot
starts on it, and the gate asks the lane again."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def triage():
    return yaml.safe_load((ROOT / ".github/workflows/issue-triage.yml").read_text(encoding="utf-8"))["jobs"]


def steps_of(job):
    return {s.get("id") or s.get("name"): s for s in job["steps"]}


def test_the_maintainer_s_bug_is_read_before_anything_is_classified():
    job = triage()["triage"]
    steps = job["steps"]
    by = steps_of(job)
    own, seal = by["own"], by["seal"]
    assert own["run"].strip().endswith('bash .dx-central/scripts/triage-act.sh own-bug >> "$GITHUB_OUTPUT"')
    assert own["if"] == "steps.seal.outputs.token != ''"
    # Its author, its body and the receipts' token, all through env.
    assert own["env"]["AUTHOR"] == "${{ github.event.issue.user.login }}" and own["env"]["BODY_TEXT"] == "${{ github.event.issue.body }}"
    assert own["env"]["SEAL_TOKEN"] == "${{ steps.seal.outputs.token }}" and own["env"]["REPO_AUTONOMY"] == ".github/autonomy.yml"
    assert "${{" not in own["run"], "untrusted text goes through env, never into the script"
    # The receipts token writes contents for the seal, and is minted only
    # for an author who can be a maintainer.
    assert seal["with"]["permission-contents"] == "write" and "OWNER" in seal["if"] and "MEMBER" in seal["if"] and "NONE" not in seal["if"]
    assert steps.index(seal) < steps.index(own) < steps.index(by["cap"]) < steps.index(by["claude"])


def test_a_maintainer_s_bug_is_never_classified_nor_labelled_by_the_verdict():
    by = steps_of(triage()["triage"])
    for sid in ("cap", "brief", "claude", "verdict", "sec", "sectoken"):
        assert by[sid]["if"].startswith("steps.own.outputs.own != 'yes'"), sid
    act = next(s for s in triage()["triage"]["steps"] if s.get("name") == "Act (label, reply, lock)")
    assert act["if"].startswith("steps.own.outputs.own != 'yes'")


def test_the_autopilot_starts_when_the_lane_accepted_it():
    jobs = triage()
    assert jobs["triage"]["outputs"]["own-accepted"] == "${{ steps.own.outputs.accepted }}"
    auto = jobs["autopilot"]
    assert "triage" in auto["needs"] and auto["if"].strip().startswith("!cancelled()")
    assert "github.event.action == 'opened' && needs.triage.outputs.own-accepted == 'true'" in auto["if"]
    assert auto["with"]["mode"] == "start"


def test_the_lane_is_in_the_policy_and_its_label_in_labels_yml():
    policy = yaml.safe_load((ROOT / "policy/autonomy.yml").read_text(encoding="utf-8"))
    lane = policy["lanes"]["maintainer-bug"]
    assert lane["accept"] == "policy" and lane["type"] == "Bug" and lane["origin"] == {"app": "dilux-bot", "author": "maintain-or-admin"}
    assert lane["merge"] == policy["lanes"]["human-issue"]["merge"] and "constitution-merge" not in lane
    labels = yaml.safe_load((ROOT / "labels.yml").read_text(encoding="utf-8"))
    names = {l["name"] for l in (labels if isinstance(labels, list) else labels.get("labels", []))}
    assert "lane:maintainer-bug" in names


def test_the_gate_reads_when_the_lane_s_label_was_added():
    gate = (ROOT / "scripts/issue-gate.sh").read_text(encoding="utf-8")
    assert "LabeledEvent { createdAt label" in gate
