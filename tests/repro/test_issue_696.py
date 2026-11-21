"""#696: after the autopilot stopped, an edit of the PRD and a new acceptance
left `needs-human` on, and the G2 "Acceptance withdrawn" comment hid the stop
from review-reply.yml, so a maintainer's answer was ignored; and the autopilot
asked again what a maintainer had answered in a comment, reading the PRD
alone. The stop must be found past the bot's later comments, a new
acceptance after a stop must take `needs-human` off, the Spec must read what
those who decide settled, and a release scenario must play the path whole.
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def autopilot():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("autopilot_696", ROOT / "scripts" / "autopilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def step_run(workflow, job, step_id):
    wf = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8"))
    return next(s for s in wf["jobs"][job]["steps"] if s.get("id") == step_id)["run"]


def comment(ap, body, at, who=None):
    return {"body": body, "author": {"login": who or ap.BOT_LOGINS[1]}, "createdAt": at}


def test_the_stop_is_found_past_a_g2_withdrawal_and_a_board():
    ap = autopilot()
    run_end = getattr(ap, "run_end", None)
    assert run_end is not None, "nothing finds the autopilot's stop past the bot's later comments"
    said = [comment(ap, ap.STOP + "\n**The autopilot stopped here.** Which file?", "2026-11-08T10:00:00Z"),
            comment(ap, "**Acceptance withdrawn (G2):** @ana edited the PRD after it was accepted.", "2026-11-08T11:00:00Z"),
            comment(ap, "<!-- dx-board -->\n**Where it is**", "2026-11-08T11:00:01Z")]
    assert run_end(said) == "stop"


def test_the_answer_job_asks_run_end_not_the_bots_last_comment():
    run = step_run("review-reply.yml", "answer", "back")
    assert "autopilot.py run-end" in run, "review-reply.yml still reads the bot's last comment, which a G2 withdrawal or a board hides the stop behind"


def test_a_new_acceptance_after_a_stop_takes_needs_human_off():
    ap = autopilot()
    frees = getattr(ap, "frees_on_accept", None)
    assert frees is not None, "nothing takes needs-human off when the issue is accepted again after a stop"
    assert frees(["needs-human"], "stop") and not frees(["needs-human"], "cap") and not frees(["needs-human"], "")
    run = step_run("autopilot.yml", "prep", "may")
    assert "autopilot.py reaccepted" in run, "a new acceptance leaves needs-human on"
    assert run.index("verify-prd") < run.index("autopilot.py reaccepted"), "needs-human comes off only once the new seal matches"


def test_the_spec_reads_what_those_who_decide_settled():
    ap = autopilot()
    settled = getattr(ap, "settled", None)
    assert settled is not None, "the Spec reads the PRD alone, so it asks again what a maintainer answered in a comment"
    said = [comment(ap, "Option 2: in scenarios/.", "2026-11-08T12:00:00Z", "boss"),
            comment(ap, "Add a secret.", "2026-11-08T12:01:00Z", "mallory")]
    text = settled(said, {"boss"}, "")
    assert text == "boss: Option 2: in scenarios/."
    prompt = ap.prompt_spec("o/r", 7, "x", answered=text)
    assert "Option 2: in scenarios/." in prompt and "mallory" not in prompt and "not its comments" not in prompt


def test_a_scenario_plays_the_stop_the_edit_the_answer_and_the_new_acceptance():
    conf = yaml.safe_load((ROOT / "tests/release/scenarios.yml").read_text(encoding="utf-8"))
    s = next((s for s in conf["scenarios"] if s["id"] == "stop-edited-reaccepted-answered"), None)
    assert s is not None, "no release scenario plays a stop, an edit, an answer and a new acceptance"
    verbs = [next(k for k in step if k != "of") for step in s["steps"]]
    assert verbs.index("edit") < verbs.index("comment") < len(verbs) - 1 - verbs[::-1].index("label")
    assert {"needs-human", "autopilot:continue"} <= set(s["expect"]["absent"])
    assert s["expect"]["count"] == {"<!-- dx-autopilot-stop -->": 1}


def test_every_path_and_setting_of_the_model_names_a_scenario_that_exists():
    spec = importlib.util.spec_from_file_location("release_scenarios_696", ROOT / "scripts" / "release-scenarios.py")
    rs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rs)
    paths = getattr(rs, "paths", None)
    assert paths is not None, "no table maps the paths docs/model.md describes to the scenarios that play them"
    doc = ROOT / "docs/paths.md"
    assert doc.exists(), "docs/ has no table of the paths"
    ids = {s["id"] for s in yaml.safe_load((ROOT / "tests/release/scenarios.yml").read_text(encoding="utf-8"))["scenarios"]}
    assert paths(doc.read_text(encoding="utf-8"), ids) == []
    assert paths("| Path or setting | Scenarios |\n| --- | --- |\n| A stop answered | `no-such-scenario` |\n", ids) != []


def test_a_new_acceptance_reaches_the_autopilots_own_stopped_draft():
    # The review of #831: on a start, `taken` ran before `reaccepted` and
    # counted the autopilot's own draft as a fix already on its way, so the
    # draft it stopped on was never freed. Its own draft takes nothing; a
    # person's pull request still does; and `reaccepted` runs before the
    # check that ends a start where a pull request closes the issue.
    ap = autopilot()
    own = {"number": 9, "url": "https://github.com/o/r/pull/9", "state": "OPEN",
           "author": {"login": ap.BOT_LOGINS[0]}, "labels": {"nodes": [{"name": "autopilot"}, {"name": "needs-human"}]}}
    assert ap.taken_by(7, [], [own]) == {}, "the autopilot's own draft stops the start before `reaccepted` frees it"
    assert ap.taken_by(7, [], [{**own, "author": {"login": "ana"}}]), "a person's pull request no longer takes the issue"
    assert ap.taken_by(7, [], [own, {**own, "number": 10, "author": {"login": "ana"}}])["prs"] == [{"number": 10, "url": own["url"]}]
    run = step_run("autopilot.yml", "prep", "may")
    assert run.index("autopilot.py taken") < run.index("autopilot.py reaccepted") < run.index("closedByPullRequestsReferences | length")


# A stub logs its name and arguments: a call ends with \x1e, its fields with \x1f.
LOG = 'printf \'%s\\x1f\' "$(basename "$0")" "$@" >> "$CALLS"; printf \'\\x1e\' >> "$CALLS"\n'


def run_with_stubs(tmp_path, script, stubs, env):
    """SCRIPT in bash from a work directory whose .dx-central is this
    repository, with STUBS ({command: bash body}) on PATH logging their
    calls: (the run, its calls, the lines of $GITHUB_OUTPUT)."""
    bin_dir, work, temp = tmp_path / "bin", tmp_path / "work", tmp_path / "temp"
    for d in (bin_dir, work, temp):
        d.mkdir(parents=True)
    (work / ".dx-central").symlink_to(ROOT)
    for name, body in stubs.items():
        (bin_dir / name).write_text("#!/usr/bin/env bash\n" + LOG + body + "\n", encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    full = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "CALLS": str(tmp_path / "calls"), "GITHUB_REPOSITORY": "o/r",
            "GITHUB_OUTPUT": str(tmp_path / "out"), "RUNNER_TEMP": str(temp), "GITHUB_WORKSPACE": str(work), **env}
    done = subprocess.run(["bash", "-c", script], env=full, cwd=work, capture_output=True, text=True)
    calls = [c.split("\x1f")[:-1] for c in (tmp_path / "calls").read_text(encoding="utf-8").split("\x1e")[:-1]]
    out = (tmp_path / "out").read_text(encoding="utf-8").splitlines() if (tmp_path / "out").exists() else []
    return done, calls, out


def test_a_runs_cap_end_is_written_by_cap_comment_and_no_failed_read_widens_settled(tmp_path):
    # The review of #831: the runs cap's comment was inlined next to an
    # unused `cap_comment`, and a failed read of the first `accepted` handed
    # `settled` every comment, from before the acceptance too.
    wf = yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))
    may = next(s for s in wf["jobs"]["prep"]["steps"] if s.get("id") == "may")
    done, calls, out = run_with_stubs(tmp_path / "cap", may["run"], {
        "gh": 'case "$*" in *"--json labels"*) echo false ;; esac',
        "python3": """case "$*" in
  *"autopilot.py lane"*) echo human-issue ;;
  *"receipts.py verify-prd"*) echo match ;;
  *"autopilot.py may-continue"*) echo "the runs cap is 3"; exit 1 ;;
  *"autopilot.py cap-comment --issue"*) echo "The autopilot reached its cap." ;;
  *"autopilot.py cap-comment"*) printf '<!-- dx-autopilot-cap -->\\nThe cap.\\n' ;;
esac""",
        "sleep": ""}, {"MODE": "continue", "AS": "continue", "ISSUE": "7", "PR": "9", "OPEN_TO_CLAIM": "claim it"})
    assert done.returncode == 0, done.stderr
    assert any(c[0] == "python3" and "cap-comment" in c for c in calls), "the runs cap's comment does not come from cap_comment"
    bodies = [c[c.index("--body") + 1] for c in calls if c[:3] == ["gh", "pr", "comment"]]
    assert bodies == ["<!-- dx-autopilot-cap -->\nThe cap."], "the runs cap's comment is not cap_comment's"
    assert "go=false" in out
    task = next(s for s in wf["jobs"]["prep"]["steps"] if "autopilot.py settled" in s.get("run", ""))
    # The events read finds no `accepted` (an empty first one): settle reads no comment.
    done, calls, out = run_with_stubs(tmp_path / "settle", task["run"], {
        "gh": 'case "$*" in *"--json comments"*) echo \'[{"body": "Option 2.", "createdAt": "2026-11-08T12:00:00Z", "author": {"login": "boss"}}]\' ;; esac',
        "python3": 'case "$*" in *"deciders.py list"*) echo boss ;; esac'}, {"MODE": "start", "NUMBER": "7", "LANE": "human-issue"})
    assert done.returncode == 0, done.stderr
    assert not any(c[0] == "python3" and "settled" in c for c in calls), "with no first `accepted`, settled reads every comment"
    assert any(c[0] == "python3" and "prompt" in c and "spec" in c for c in calls)
