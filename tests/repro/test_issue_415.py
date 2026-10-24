"""#415: the autopilot never starts on a sub-issue dilux-bot opens for an
accepted decision. Written from the report as the reproduction's writer would
(#376).
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ("issue-triage.yml", "issue-accepted.yml")


def workflow(name):
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def test_the_autopilot_starts_on_an_issue_dilux_bot_opens_as_a_decisions_sub_issue():
    starts = []
    for name in WORKFLOWS:
        for job_id, job in workflow(name)["jobs"].items():
            uses = str(job.get("uses", ""))
            if "/autopilot.yml@" in uses and (job.get("with") or {}).get("issue"):
                starts.append((name, job_id, str(job.get("if", ""))))
    assert starts, "no job calls autopilot.yml with an issue"
    # The only start today is `labeled` with `accepted` by a person: a sub-issue
    # is opened, never labelled by a person, so a start on `opened` is needed.
    assert any("'opened'" in cond for _, _, cond in starts), starts
