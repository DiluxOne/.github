"""Every reproduced bug goes to the bugfix-reproduced lane, whatever its
test's way (#397): the wiring no script's --test can see, read from the
workflows' files."""
import json
import os
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def step(steps, key):
    return next(s for s in steps if s.get("id") == key or s.get("name") == key)


def test_c1_the_lane_takes_every_way_not_only_the_unit_one():
    report = load("issue-repro.yml")["jobs"]["report"]["steps"]
    may = step(report, "open")
    assert may["if"] == "needs.run.outputs.outcome == 'reproduced'"
    assert "lane-open bugfix-reproduced" in may["run"]


def test_c1_the_way_travels_in_the_prd_only_for_a_way_that_is_not_the_unit_one():
    lane = step(load("issue-repro.yml")["jobs"]["report"]["steps"], "lane")
    for key, out in (("WAY", "way"), ("SPEC", "spec"), ("NOUN", "noun"), ("THEME", "theme")):
        assert lane["env"][key] == f"${{{{ needs.write.outputs.sandbox != 'php-unit' && needs.write.outputs.{out} || '' }}}}"
    assert "repro-lane.py prd" in lane["run"]


def test_c1_the_prd_the_lane_step_writes_carries_the_way_and_reads_back(tmp_path):
    spec = {"setup": ["pip install pytest"], "run": "pytest {test}", "junit": "build/j.xml", "minutes": 10, "test": "tests/repro/test_issue_12.py"}
    env = dict(os.environ, REPORT="12", RUN_URL="https://github.com/DiluxOne/x/actions/runs/42", SHA256="a" * 64, BASE="b" * 40,
               WAY="python", SPEC=json.dumps(spec), NOUN="Python test", THEME="")
    out = subprocess.run(["python3", str(ROOT / "scripts/repro-lane.py"), "prd"], env=env, capture_output=True, text=True, check=True)
    body = tmp_path / "body.md"
    body.write_text(json.loads(out.stdout)["body"], encoding="utf-8")
    ev = subprocess.run(["python3", str(ROOT / "scripts/repro-lane.py"), "evidence"], env=dict(os.environ, BODY=str(body)), capture_output=True, text=True, check=True)
    got = json.loads(ev.stdout)
    assert (got["test"], got["way"], got["spec"], got["branch"]) == ("tests/repro/test_issue_12.py", "python", spec, "test/repro-issue-12")


def test_the_autopilot_hands_the_way_to_the_agent_and_its_finish():
    wf = load("autopilot.yml")
    prep = wf["jobs"]["prep"]
    assert prep["outputs"]["repro-spec"] == "${{ steps.may.outputs.repro-spec }}"
    may = step(prep["steps"], "may")["run"]
    assert "repro-spec=$(jq -c '.spec // empty'" in may and "repro-theme=$(jq -r '.theme // empty'" in may
    for job, key in (("work", "work"), ("spec", "spec")):
        env = step(wf["jobs"][job]["steps"], key)["env"]
        assert env["REPRO_SPEC"] == "${{ needs.prep.outputs.repro-spec }}"
        assert env["REPRO_THEME"] == "${{ needs.prep.outputs.repro-theme }}"


def test_c2_g7_runs_another_ways_test_again_with_no_secret():
    wf = load("auto-merge.yml")
    job = wf["jobs"]["repro"]
    text = json.dumps(job)
    assert "secrets." not in text and "DILUX_BOT" not in text
    # Only the lane's branch by dilux-bot, for which the route is GitHub's runner.
    assert job["runs-on"] == load("auto-merge.yml")["jobs"]["decide"]["runs-on"] and "-the-bug-reproduced-from-" in job["runs-on"]
    assert job["permissions"] == {"contents": "read", "issues": "read", "pull-requests": "read"}
    assert "-the-bug-reproduced-from-" in job["if"] and "head.repo.full_name == github.repository" in job["if"]
    checkouts = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout@")]
    assert checkouts and all(s["with"]["persist-credentials"] is False for s in checkouts)
    assert checkouts[0]["with"]["ref"] == "${{ github.event.pull_request.head.sha }}"
    run = step(job["steps"], "run")
    assert run["run"].startswith("bash .dx-central/scripts/repro-run.sh run-ref HEAD ")
    assert run["if"] == "steps.way.outputs.spec != ''"
    # Nothing of the repository's own runs in it but the way's setup, inside
    # repro-run.sh: no install step of its own before the verdict.
    assert not any("composer" in (s.get("run") or "") or "setup-php" in str(s.get("uses", "")) for s in job["steps"])
    way = step(job["steps"], "way")["run"]
    # The sealed test only: one that changed is never run.
    assert "outcome=changed" in way and way.index("sha256sum") < way.index("spec=")


def test_c2_the_decision_waits_for_it_and_reads_its_verdict_for_its_issue():
    wf = load("auto-merge.yml")
    decide = wf["jobs"]["decide"]
    assert decide["needs"] == "repro"
    assert decide["if"].startswith("!cancelled() && ")
    ap = step(decide["steps"], "autopilot")
    assert ap["env"]["REPRO_RUN"] == "${{ needs.repro.outputs.outcome }}"
    assert '[ "$REPRO_RUN_ISSUE" = "$issue" ] && [ "$REPRO_RUN" = passed ]' in ap["run"]
    # The verdict is read again from the report, in the job that runs nothing of the repository's.
    assert 'repro-ways.py" verdict "$RUNNER_TEMP/repro-junit/junit.xml"' in ap["run"]
    names = [s.get("uses", "") for s in decide["steps"]]
    assert any(n.startswith("actions/download-artifact@") for n in names)
    assert names.index(next(n for n in names if n.startswith("actions/download-artifact@"))) < [s.get("id") for s in decide["steps"]].index("autopilot")
    up = [s for s in wf["jobs"]["repro"]["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    assert up and up[0]["with"]["path"] == "${{ runner.temp }}/repro/junit.xml"
    assert decide["steps"][[s.get("uses", "") for s in decide["steps"]].index(next(n for n in names if n.startswith("actions/download-artifact@")))]["with"]["name"] == up[0]["with"]["name"]


def test_c4_the_decision_measures_what_a_reproduced_fix_widens():
    ap = step(load("auto-merge.yml")["jobs"]["decide"]["steps"], "autopilot")["run"]
    assert "no-widening.py\" check \"$BASE\" \"$HEAD\"" in ap
    # Not knowing counts as widening: "unknown" first, emptied only on exit 0.
    assert ap.index('echo unknown > "$RUNNER_TEMP/widening"') < ap.index('no-widening.py" check')
    assert '0) : > "$RUNNER_TEMP/widening" ;;' in ap
    assert 'WIDENING="$RUNNER_TEMP/widening"' in ap
    assert ap.index("WIDENING=") < ap.index("autopilot.py\" decide")


def test_every_caller_grants_what_the_repro_job_asks():
    for name in ("org-pull-request.yml", "pull-request.yml", "pull-request-edited.yml"):
        job = load(name)["jobs"]["auto-merge"]
        assert job["permissions"] == {"contents": "read", "issues": "read", "pull-requests": "read"}, name


def test_ci_runs_the_no_widening_self_test():
    runs = [s.get("run", "") for s in load("pull-request.yml")["jobs"]["scripts"]["steps"]]
    assert "python3 scripts/no-widening.py --test" in runs


def test_the_policy_gives_constitution_merge_to_the_reproduced_lane_alone():
    pol = yaml.safe_load((ROOT / "policy/autonomy.yml").read_text(encoding="utf-8"))
    have = [n for n, lane in pol["lanes"].items() if "constitution-merge" in lane]
    assert have == ["bugfix-reproduced"]
    assert re.search(r"no-widening\.py", (ROOT / "policy/autonomy.yml").read_text(encoding="utf-8"))
