"""#843 C1: a scenario that fails once and passes on its retry does not fail
the candidate, and the lane's summary names it flaky. release-scenarios.py's
play_group plays a failing scenario once more while the play step has time
left (its row: `attempts`, `flaky`, the first failure), its table says
`pass (flaky: …)`, merge keeps those keys, and release-lane.py's decide
releases it while act names it in a Flaky line of the lane's summary. The
scenario itself is a stand-in for `play`."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scen = load("release_scenarios_c1", "scripts/release-scenarios.py")
lane = load("release_lane_c1", "scripts/release-lane.py")

CONF = {"scenarios": [{"id": "spec-to-draft", "opens": {"issue": {}}, "expect": {"labels": ["autopilot"]}}]}


def player(outcomes):
    """A stand-in for `play`: each call's row, in order."""
    calls = []

    def play(s, repo, ref, bodies, run=None, sleep=None, minutes=20, **kw):
        calls.append(minutes)
        ok, why = outcomes[len(calls) - 1]
        return {"id": s["id"], "ok": ok, "why": why, "run": f"https://github.com/o/t/actions/runs/{len(calls)}"}
    return play, calls


def test_a_scenario_that_fails_once_and_passes_on_retry_is_ok_and_flaky(monkeypatch):
    play, calls = player([(False, ["no label autopilot"]), (True, [])])
    monkeypatch.setattr(scen, "play", play)
    rows = scen.play_group(CONF, "spec-to-draft", "o/t", "v7-next", run=lambda *a, **k: "", sleep=lambda s: None, minutes=20)
    assert len(calls) == 2
    assert len(rows) == 1
    row = rows[0]
    assert row["ok"] is True
    assert (row.get("attempts"), row.get("flaky")) == (2, True)
    assert "pass (flaky: no label autopilot)" in scen.table(rows)
    merged = scen.merge([{"id": "spec-to-draft", "scenarios": ["spec-to-draft"]}],
                        {"move": [], "back": [], "spec-to-draft": rows}, {"move": "success", "play": "success", "back": "success"})
    kept = next(r for r in merged if r["id"] == "spec-to-draft")
    assert (kept["ok"], kept.get("attempts"), kept.get("flaky")) == (True, 2, True)


def test_a_scenario_that_passes_first_is_played_once():
    rows = []
    play, calls = player([(True, [])])
    original = scen.play
    scen.play = play
    try:
        rows = scen.play_group(CONF, "spec-to-draft", "o/t", "v7-next", run=lambda *a, **k: "", sleep=lambda s: None, minutes=20)
    finally:
        scen.play = original
    assert len(calls) == 1
    assert rows[0]["ok"] is True and not rows[0].get("flaky")


def test_a_failure_with_no_time_left_is_not_retried_and_says_so(monkeypatch):
    play, calls = player([(False, ["no label autopilot"]), (True, [])])
    monkeypatch.setattr(scen, "play", play)
    rows = scen.play_group(CONF, "spec-to-draft", "o/t", "v7-next", run=lambda *a, **k: "", sleep=lambda s: None, minutes=0)
    assert len(calls) == 1
    assert rows[0]["ok"] is False
    assert any("not retried: no time left in the play step" in w for w in rows[0]["why"])


def test_the_candidate_is_not_failed_and_the_summary_names_it_flaky(tmp_path, monkeypatch, capsys):
    row = {"id": "spec-to-draft", "ok": True, "why": [], "run": "https://github.com/o/t/actions/runs/2",
           "attempts": 2, "flaky": True, "first_why": ["no label autopilot"]}
    nxt = {"last": "7.10.0", "next": "7.10.1", "bump": "patch", "pending": True}
    p = dict(lane.plan(nxt, ["fix(autopilot): a stuck draft goes on (#600)"]), sha="p1")
    assert lane.decide(p, [row])["do"] == "release"
    # What act prints and writes to the lane's summary, on a plan with
    # nothing to release, so no gh nor git runs.
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"release": False, "why": "nothing releasable"}))
    results = tmp_path / "results.md"
    results.write_text(f"<!-- dx-scenarios {json.dumps([row])} -->\n")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert lane.main(["act", "--plan", str(plan), "--results", str(results), "--repo", "O/.github"]) == 0
    out = capsys.readouterr()
    json.loads(out.out)  # stdout stays one JSON object: the workflow reads it with jq
    text = summary.read_text() if summary.exists() else ""
    assert "Flaky" in text and "`spec-to-draft`" in text and "no label autopilot" in text
    assert "Flaky" in out.err and "spec-to-draft" in out.err
