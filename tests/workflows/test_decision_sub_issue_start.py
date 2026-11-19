"""An accepted decision's sub-issue starts the autopilot (#415): the start on
`opened` is only for an issue dilux-bot opens with no label, never a
reproduced bug's lane issue, and a start that finds no lane asks once more.

The triage's autopilot job condition is evaluated on events; autopilot.yml's
`may` step is run with its central scripts stubbed."""
from steps import evaluate, run, step, workflow

BOT = "dilux-bot[bot]"


def starts_on_opened(sender, labels, title="A decision's part"):
    ctx = {"needs.steer.result": "skipped", "needs.steer.outputs.ok": "", "github.event_name": "issues",
           "github.event.issue.labels.*.name": [l["name"] for l in labels], "github.event.issue.labels": labels,
           "github.event.action": "opened", "needs.own.outputs.accepted": "false", "github.event.label.name": "",
           "github.event.sender.type": "Bot" if sender == BOT else "User", "github.event.sender.login": sender,
           "vars.DX_BOT_LOGIN": BOT, "needs.edit-start.outputs.start": "", "github.event.issue.title": title}
    return evaluate(workflow("issue-triage.yml")["jobs"]["autopilot"]["if"], ctx)


def test_the_start_on_opened_is_dilux_bots_unlabelled_issue():
    assert starts_on_opened(BOT, [])
    assert not starts_on_opened("mallory", [])
    assert not starts_on_opened(BOT, [{"name": "spike"}])
    assert not starts_on_opened(BOT, [], title="The bug reproduced from #7")


def test_an_opened_issue_starts_and_only_autopilot_continue_continues():
    mode = workflow("issue-triage.yml")["jobs"]["autopilot"]["with"]["mode"]
    assert mode == "${{ github.event.label.name == 'autopilot:continue' && 'continue' || 'start' }}"


# autopilot.py stand-in: `lane` fails until its LANE_AFTER-th call, then
# names the lane; `may-start` refuses, which ends the step after the lane.
AUTOPILOT = """import os, sys
cmd = sys.argv[1]
log = os.path.join(os.environ["RUNNER_TEMP"], "autopilot.log")
open(log, "a").write(cmd + "\\n")
if cmd == "lane":
    n = sum(1 for l in open(log) if l == "lane\\n")
    if n < int(os.environ["LANE_AFTER"]):
        print("no lane yet")
        sys.exit(1)
    print("delegated")
elif cmd == "may-start":
    print("stopped here")
    sys.exit(1)
"""


def may(tmp_path, as_, lane_after):
    env = {"AS": as_, "MODE": as_, "ISSUE": "9", "PR": "", "LANE_AFTER": str(lane_after), "GH_TOKEN": "t"}
    ran = run(step("autopilot.yml", "may", job="prep"), tmp_path, env=env, central=False,
              stubs={"sleep": ":", "gh": "echo"}, files={".dx-central/scripts/autopilot.py": AUTOPILOT})
    asked = (ran.temp / "autopilot.log").read_text().split()
    return ran, asked


def test_a_start_that_finds_no_lane_asks_once_more(tmp_path):
    ran, asked = may(tmp_path, "start", 2)
    assert ran.code == 0, ran.stderr
    assert asked.count("lane") == 2 and ran.output["lane"] == "delegated"
    assert ran.of("sleep") == [["15"]]


def test_a_start_asks_for_half_a_minute_and_no_more(tmp_path):
    ran, asked = may(tmp_path, "start", 9)
    assert ran.code == 0, ran.stderr
    assert asked.count("lane") == 3 and ran.output == {"go": "false"}
    assert ran.of("sleep") == [["15"], ["15"]]


def test_a_continue_that_finds_no_lane_does_not_wait(tmp_path):
    ran, asked = may(tmp_path, "continue", 2)
    assert ran.code == 0, ran.stderr
    assert asked.count("lane") == 1 and ran.output == {"go": "false"}
    assert ran.of("sleep") == []
