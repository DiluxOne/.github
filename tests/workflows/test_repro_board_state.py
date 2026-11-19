"""The reproduction's steps on the issue's board (#801), not in labels.

`bug:unconfirmed` and `layer:*` are no longer set: the triage writes the
board's state, `repro` `{"step": "waiting", "layer": ...}`
(scripts/receipts.py state set), and the reproduction reads the layer from
it. Its outcomes are the board's too; `could-not-reproduce` became
`needs-info` and `repro:no-way` `needs-human`, which a person acts on. What
no script's --test can see, read from the workflows' files.
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RETIRED = ("bug:unconfirmed", "layer:", "could-not-reproduce", "repro:no-way")
# A label added (`--add-label X`, `--add-label "X"`) or created (`gh label
# create X`) whose name is, or starts with, a retired one.
ADDS = re.compile(r"""(?:--add-label|label create)\s+["']?([^\s"']+)""")


def load(path):
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def steps(workflow, job):
    return load(f".github/workflows/{workflow}")["jobs"][job]["steps"]


def step(all_steps, name):
    return next(s for s in all_steps if s.get("name") == name)


def runs(workflow):
    """(job, step name, run) of every step of the workflow."""
    for job, body in load(f".github/workflows/{workflow}")["jobs"].items():
        for s in body.get("steps") or []:
            if s.get("run"):
                yield job, s.get("name") or s.get("id"), s["run"]


def retired_in(text):
    return sorted({m for m in ADDS.findall(text) if any(m.startswith(r) for r in RETIRED)})


def test_c1_no_step_adds_a_retired_label():
    found = {f"{wf} {job}/{name}": retired_in(run) for wf in ("issue-triage.yml", "issue-repro.yml") for job, name, run in runs(wf)}
    # scripts/triage-act.sh's own --test runs `act` with a stand-in gh and
    # fails on any retired label it adds or creates (the scripts job).
    assert {k: v for k, v in found.items() if v} == {}


def test_c1_the_pattern_sees_a_retired_label():
    assert retired_in('gh issue edit "$N" --add-label "layer:$layer"; gh label create repro:no-way --force') == ["layer:$layer", "repro:no-way"]
    assert retired_in("gh issue edit 1 --add-label needs-info --add-label bug:confirmed") == []


def test_c1_the_triage_sets_the_reproduction_waiting_with_its_layer():
    act = (ROOT / "scripts/triage-act.sh").read_text(encoding="utf-8")
    assert '[ "$effective" != bug_unconfirmed ] || step=waiting' in act
    assert 'receipts.py" state set "repro=$repro"' in act
    assert "{step: $step}" in act and "{layer: $layer}" in act
    # The bot's own Bug (#247): no classifier, the same state, on a token
    # that reads the receipts branch for the board's seal row.
    nightly = load(".github/workflows/issue-triage.yml")["jobs"]["nightly"]
    mark = step(nightly["steps"], "Its reproduction waits, on its board")
    assert "receipts.py state set" in mark["run"] and '{step: "waiting"' in mark["run"]
    token = next(s for s in nightly["steps"] if s.get("id") == "bot")["with"]
    assert token["permission-contents"] == "read" and token["permission-issues"] == "write"
    assert any(s.get("with", {}).get("repository") == "DiluxOne/.github" and s["with"].get("path") == ".dx-central" for s in nightly["steps"])


def test_c1_the_way_step_reads_the_layer_from_the_board():
    write = steps("issue-repro.yml", "write")
    way = step(write, "The way to reproduce")
    assert "receipts.py state get repro" in way["run"]
    assert '"logic"' in way["run"], "no layer on the board is logic, as before"
    assert "labels" not in way["run"]
    assert way["env"]["GH_TOKEN"] == "${{ steps.bot.outputs.token }}"
    token = next(s for s in write if s.get("id") == "bot")["with"]
    assert token["permission-issues"] == "read", "the board is one of the issue's comments"


def test_c1_the_tokens_that_write_the_board_read_its_seal():
    write = steps("issue-repro.yml", "write")
    say = next(s for s in write if s.get("id") == "say")["with"]
    assert say["permission-contents"] == "read" and say["permission-issues"] == "write"
    broke = next(s for s in write if s.get("id") == "broke")["with"]
    assert broke["permission-contents"] == "read" and broke["permission-issues"] == "write"
    report = steps("issue-repro.yml", "report")
    assert next(s for s in report if s.get("id") == "bot")["with"]["permission-contents"] == "write"


def test_c1_the_report_knows_the_layer_it_ran_for():
    report = step(steps("issue-repro.yml", "report"), "Labels, branch, pull request, comment")
    assert report["env"]["LAYER"] == "${{ needs.write.outputs.layer }}"
    assert "repro_state() {" in report["run"] and "receipts.py state set" in report["run"]


# C2: the report step's script, run with stand-ins for gh and for the
# scripts it calls (receipts.py, api-commit.py) in a .dx-central of its own,
# every call logged in order.
import json  # noqa: E402
import hashlib  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

SET = "receipts state set repro="
FAKE_GH = r"""#!/usr/bin/env bash
printf 'gh %s\n' "$*" | tr '\n' ' ' >> "$CALLS"; echo >> "$CALLS"
case "$*" in
  "issue view "*'index("claimed")'*) echo false ;;
  "pr create "*) echo https://github.com/o/r/pull/9 ;;
esac
exit 0
"""
FAKE_RECEIPTS = r"""import json, os, sys
open(os.environ["CALLS"], "a").write("receipts " + " ".join(sys.argv[1:]) + "\n")
if sys.argv[1:3] == ["state", "get"]:
    print(os.environ.get("BEFORE") or "null")
sys.exit(int(os.environ.get("STATE_RC", "0")) if sys.argv[1:3] == ["state", "set"] else 0)
"""


def report(tmp_path, where=("report", "Labels, branch, pull request, comment"), **env):
    """The calls a step (the report's, by default) makes for an outcome:
    [(kind, text)], and each board state it set, parsed."""
    the_step = step(steps("issue-repro.yml", where[0]), where[1])
    run = the_step["run"]
    work, temp, bindir = tmp_path / "work", tmp_path / "temp", tmp_path / "bin"
    for d in (work / ".dx-central/scripts", temp / "written", temp / "output", bindir):
        d.mkdir(parents=True)
    (bindir / "gh").write_text(FAKE_GH)
    (bindir / "gh").chmod(0o755)
    (work / ".dx-central/scripts/receipts.py").write_text(FAKE_RECEIPTS)
    (work / ".dx-central/scripts/api-commit.py").write_text("")
    (temp / "written/test").write_text("def test_x():\n    assert False\n")
    calls = tmp_path / "calls"
    calls.write_text("")
    git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=work, check=True, capture_output=True)
    git("init", "-q")
    (work / ".gitignore").write_text(".dx-central/\n")
    git("add", ".gitignore")
    git("commit", "-q", "-m", "init")
    # Every key of the step's env is set, empty when the event leaves it so.
    base = {key: "" for key in the_step["env"]}
    base |= {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path), "CALLS": str(calls),
            "GITHUB_REPOSITORY": "o/r", "GITHUB_SERVER_URL": "https://github.com", "GITHUB_RUN_ID": "1",
            "RUNNER_TEMP": str(temp), "GITHUB_OUTPUT": str(tmp_path / "out"), "NUMBER": "7", "MODEL": "m",
            "SUMMARY": "the save | button @x\nfails", "WROTE": "true", "AGENT": "success", "RUN_RESULT": "success",
            "OUTCOME": "passed", "TEST": "tests/repro/test_issue_7.py", "NOUN": "unit test", "LAYER": "cli",
            "SHA256": hashlib.sha256((temp / "written/test").read_bytes()).hexdigest(), "BOT": "dilux-bot[bot]",
            "BT": "`", "DX_BOT_APP": "dilux-bot"}
    out = subprocess.run(["bash", "-c", run], cwd=work, env={**base, **env}, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    lines = calls.read_text().splitlines()
    states = [json.loads(l.removeprefix(SET)) for l in lines if l.startswith(SET)]
    return lines, states, out.stdout


def added(lines, label):
    return [i for i, l in enumerate(lines) if l.startswith("gh issue edit 7 ") and f"--add-label {label} " in l + " "]


def removed(lines, label):
    return [i for i, l in enumerate(lines) if l.startswith("gh issue edit 7 ") and f"--remove-label {label} " in l + " "]


def set_at(lines, step_):
    return [i for i, l in enumerate(lines) if l.startswith(SET) and json.loads(l.removeprefix(SET)).get("step") == step_]


FOUND_NOTHING = {
    "a passing test": {},
    "no test written": {"WROTE": "false"},
    "a browser test that read a stylesheet twice": {"REJECTED": "css", "BROWSER": "browser", "LABEL": "repro:retry", "SENDER_LOGIN": "dilux-bot[bot]"},
}


def test_c2_each_found_nothing_branch_adds_needs_info_with_its_step_and_reason_on_the_board(tmp_path):
    for i, (name, env) in enumerate(FOUND_NOTHING.items()):
        lines, states, _ = report(tmp_path / str(i), **env)
        assert added(lines, "needs-info"), (name, lines)
        assert set_at(lines, "not-reproduced") and set_at(lines, "not-reproduced")[0] < added(lines, "needs-info")[0], (name, lines)
        last = states[-1]
        assert last["step"] == "not-reproduced" and last["reason"].strip() and last["at"], (name, last)
        assert last["layer"] == ("browser" if env.get("REJECTED") else "cli"), (name, last)
        assert not added(lines, "needs-human"), name


def test_c2_no_way_in_the_report_adds_needs_human_with_its_step_and_reason(tmp_path):
    lines, states, _ = report(tmp_path, REJECTED="css", BROWSER="")
    assert added(lines, "needs-human") and set_at(lines, "no-way")[0] < added(lines, "needs-human")[0], lines
    assert states[-1]["step"] == "no-way" and "browser test" in states[-1]["reason"] and states[-1]["layer"] == "browser"
    assert not added(lines, "needs-info")


def test_c2_no_way_before_any_model_adds_needs_human_with_its_step_and_reason():
    no_way = step(steps("issue-repro.yml", "write"), "No way reproduces it")["run"]
    assert no_way.index("receipts.py state set") < no_way.index("--add-label needs-human")
    assert "{step: \"no-way\", layer: $layer, reason: ($reason | .[0:300]), at: $at}" in no_way
    assert '--arg reason "$WHY"' in no_way, "the reason is repro-ways.py's why, through env and jq"


def test_c2_a_confirmed_run_takes_off_only_the_labels_the_reproduction_put_there(tmp_path):
    for i, (before, off) in enumerate([("not-reproduced", "needs-info"), ("no-way", "needs-human"), ("waiting", None), ("", None)]):
        lines, states, _ = report(tmp_path / str(i), OUTCOME="reproduced", BEFORE=json.dumps({"step": before, "layer": "cli"}) if before else "")
        assert states[-1]["step"] == "confirmed" and added(lines, "bug:confirmed"), lines
        took = {l for l in ("needs-info", "needs-human") if removed(lines, l)}
        assert took == ({off} if off else set()), (before, took)


def test_c2_any_later_outcome_takes_off_the_label_the_earlier_step_owned(tmp_path):
    # The review on #813: an earlier step's label left behind goes stale,
    # and the stale sweep closes a `needs-info` issue.
    board = lambda step_: json.dumps({"step": step_, "layer": "cli"})
    cases = [
        ("no-way -> not-reproduced", "no-way", {}, "needs-human", "needs-info"),
        ("no-way -> no-verdict", "no-way", {"OUTCOME": "limit"}, "needs-human", None),
        ("not-reproduced -> no-verdict", "not-reproduced", {"OUTCOME": "limit"}, "needs-info", None),
        ("not-reproduced -> broken", "not-reproduced", {"OUTCOME": "broken", "LABEL": "repro:retry", "SENDER_LOGIN": "dilux-bot[bot]"}, "needs-info", None),
        ("not-reproduced -> no-way", "not-reproduced", {"REJECTED": "css", "BROWSER": ""}, "needs-info", "needs-human"),
    ]
    for i, (name, before, env, off, on) in enumerate(cases):
        lines, _, _ = report(tmp_path / str(i), BEFORE=board(before), **env)
        assert removed(lines, off), (name, lines)
        if on:
            assert added(lines, on) and not removed(lines, on), (name, lines)


def test_c2_the_same_step_again_keeps_its_label(tmp_path):
    lines, _, _ = report(tmp_path, BEFORE=json.dumps({"step": "not-reproduced", "layer": "cli"}))
    assert added(lines, "needs-info") and not removed(lines, "needs-info"), lines


def test_c2_not_reproduced_then_no_verdict_then_confirmed_leaves_no_needs_info(tmp_path):
    # The board's step after each run is the next run's `before`.
    first, states, _ = report(tmp_path / "a", BEFORE=json.dumps({"step": "not-reproduced", "layer": "cli"}), OUTCOME="limit")
    assert removed(first, "needs-info"), first
    second, _, _ = report(tmp_path / "b", BEFORE=json.dumps(states[-1]), OUTCOME="reproduced")
    assert added(second, "bug:confirmed") and not added(second, "needs-info"), second


def test_c2_a_refused_board_takes_no_label_off(tmp_path):
    lines, _, _ = report(tmp_path, BEFORE=json.dumps({"step": "no-way", "layer": "cli"}), STATE_RC="3")
    assert not removed(lines, "needs-human"), lines


def test_c2_no_way_before_any_model_takes_off_an_earlier_needs_info():
    no_way = step(steps("issue-repro.yml", "write"), "No way reproduces it")["run"]
    assert "state get repro" in no_way
    assert no_way.index("receipts.py state set") < no_way.index("--remove-label needs-info")
    assert '[ "$before" != not-reproduced ] || gh issue edit' in no_way


BROKE = ("write", "The reproduction broke")


def test_c2_a_broken_run_says_its_step_on_the_board_before_needs_human(tmp_path):
    # The review on #813: the broke step added needs-human with no board
    # step, so an earlier not-reproduced run's needs-info stayed, stale.
    lines, states, _ = report(tmp_path, where=BROKE, BEFORE=json.dumps({"step": "not-reproduced", "layer": "cli"}))
    assert states and states[-1]["step"] == "broken" and states[-1]["reason"] and states[-1]["layer"] == "cli", states
    assert set_at(lines, "broken")[0] < added(lines, "needs-human")[0], lines
    assert removed(lines, "needs-info"), lines


def test_c2_a_broken_run_keeps_a_needs_info_it_did_not_own_and_a_refused_board_takes_nothing_off(tmp_path):
    lines, _, _ = report(tmp_path / "a", where=BROKE, BEFORE=json.dumps({"step": "waiting", "layer": "cli"}))
    assert not removed(lines, "needs-info") and added(lines, "needs-human"), lines
    lines, _, out = report(tmp_path / "b", where=BROKE, BEFORE=json.dumps({"step": "not-reproduced"}), STATE_RC="3")
    assert not removed(lines, "needs-info") and added(lines, "needs-human"), lines
    assert "did not take the reproduction's step (broken)" in out


def test_c2_the_triggers_still_come_off_and_repro_no_way_is_no_longer_read(tmp_path):
    lines, _, _ = report(tmp_path)
    for trigger in ("repro:run", "repro:again", "repro:retry"):
        assert removed(lines, trigger), trigger
    assert not any("repro:no-way" in l or "could-not-reproduce" in l or "bug:unconfirmed" in l for l in lines)


def test_c2_a_board_that_refuses_the_state_is_said_and_the_run_goes_on(tmp_path):
    lines, _, out = report(tmp_path, STATE_RC="3")
    assert "did not take the reproduction's step (not-reproduced)" in out
    assert added(lines, "needs-info") and any(l.startswith("gh issue comment 7 ") for l in lines)


def test_c2_the_other_outcomes_say_their_step(tmp_path):
    cases = {"no-verdict": {"OUTCOME": "limit"}, "broken": {"OUTCOME": "broken", "LABEL": "repro:retry", "SENDER_LOGIN": "dilux-bot[bot]"}}
    for i, (want, env) in enumerate(cases.items()):
        lines, states, _ = report(tmp_path / str(i), **env)
        assert states[-1]["step"] == want and states[-1]["reason"], (want, states)
        assert not added(lines, "needs-info") and not added(lines, "needs-human"), want


# C3: a migrated `could-not-reproduce` issue is `needs-info` now, and its
# reproduction's comment may be old. The stale sweep counts the wait from
# when `needs-info` was last added (the maintainer's answer on #813), read
# from the issue's events, so a migrated issue is not closed the next day.
FAKE_STALE_GH = r"""#!/usr/bin/env bash
printf 'gh %s\n' "$*" | tr '\n' ' ' >> "$CALLS"; echo >> "$CALLS"
case "$*" in
  "issue list "*) echo 7 ;;
  "api repos/o/r/issues/7/comments"*) printf '%s' "$COMMENTS" ;;
  "api repos/o/r/issues/7/events"*) printf '%s' "$EVENTS" ;;
esac
exit 0
"""


def stale(tmp_path, comments, events):
    the_step = steps("issue-triage.yml", "stale")[-1]
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True)
    (bindir / "gh").write_text(FAKE_STALE_GH)
    (bindir / "gh").chmod(0o755)
    calls = tmp_path / "calls"
    calls.write_text("")
    env = {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path), "CALLS": str(calls),
           "GITHUB_REPOSITORY": "o/r", "DAYS": "14", "BOT": "dilux-bot[bot]",
           "COMMENTS": json.dumps(comments), "EVENTS": json.dumps(events)}
    out = subprocess.run(["bash", "-c", the_step["run"]], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    return calls.read_text().splitlines()


def closed(lines):
    return any(l.startswith("gh issue close 7 ") for l in lines)


OLD, RECENT = "2020-01-01T00:00:00Z", "2999-01-01T00:00:00Z"
BOT_ASKED_LONG_AGO = [{"user": {"login": "dilux-bot[bot]"}, "created_at": OLD}]


def labeled(name, at):
    return {"event": "labeled", "label": {"name": name}, "created_at": at}


def test_c3_the_stale_sweep_counts_the_wait_from_when_needs_info_was_last_added(tmp_path):
    # Migrated today, the bot's comment years old: not closed.
    assert not closed(stale(tmp_path / "a", BOT_ASKED_LONG_AGO, [labeled("needs-info", OLD), labeled("bug", OLD), labeled("needs-info", RECENT)]))
    # Added long ago and nobody answered: closed, as before.
    assert closed(stale(tmp_path / "b", BOT_ASKED_LONG_AGO, [labeled("needs-info", OLD), labeled("bug", RECENT)]))
    # When it was added cannot be read: the issue is left open.
    assert not closed(stale(tmp_path / "c", BOT_ASKED_LONG_AGO, []))


def test_c3_an_answer_still_takes_needs_info_off(tmp_path):
    lines = stale(tmp_path, [{"user": {"login": "reporter"}, "created_at": OLD}], [labeled("needs-info", OLD)])
    assert any(l.startswith("gh issue edit 7 ") and "--remove-label needs-info" in l for l in lines) and not closed(lines)
