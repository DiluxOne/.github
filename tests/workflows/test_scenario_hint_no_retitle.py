"""#919 C1: the hint with no needs-human (#699 C4) is held statically, never
played by luck. The release scenario `hint-no-needs-human` retitled the
ready pull request with no type to make it wait on the autopilot; the
conventions check failed on it at once and the board waited on a person, so
its `until` never held (#906, #919). In the test repository no ready
autopilot pull request lasts waiting on the autopilot (Test first is red on
every scenario's feat pull request), so tests/release/scenarios.yml holds
`flow:hint-no-needs-human` in `statically:`, with the tests that hold it,
and no scenario plays it."""
import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FLOW = "flow:hint-no-needs-human"


def conf():
    return yaml.safe_load((ROOT / "tests/release/scenarios.yml").read_text(encoding="utf-8"))


def load_release_scenarios():
    spec = importlib.util.spec_from_file_location("release_scenarios_919", ROOT / "scripts/release-scenarios.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_scenario_plays_the_hint_with_no_needs_human():
    scenarios = conf()["scenarios"]
    assert [s["id"] for s in scenarios if s["id"] == "hint-no-needs-human"] == []
    assert [s["id"] for s in scenarios if FLOW in (s.get("covers") or [])] == []


def test_the_flow_is_held_statically_by_its_tests():
    c = conf()
    assert "hint-no-needs-human" in (c.get("flows") or {})
    why = (c.get("statically") or {}).get(FLOW, "")
    assert "scripts/autopilot.py --test" in why, why
    assert "#699 C4" in why, why
    assert "tests/workflows/test_hint_without_needs_human.py" in why, why
    for path in ("scripts/autopilot.py", "tests/workflows/test_hint_without_needs_human.py"):
        assert (ROOT / path).is_file(), path
    src = (ROOT / "scripts/autopilot.py").read_text(encoding="utf-8")
    assert "#699 C4: a decider's comment on an autopilot pull request that waits on the autopilot is a hint, stopped or not" in src


def test_no_scenario_retitles_before_a_hint():
    """What failed twice (#906, #919): a retitle with no type, which the
    engine corrects, before a hint that needs the board on the autopilot."""
    for s in conf()["scenarios"]:
        steps = s.get("steps") or []
        hint = [i for i, st in enumerate(steps) if str(st.get("comment", "")).startswith("Hint:")]
        if hint:
            assert not [st for st in steps[:hint[0]] if "retitle" in st], s["id"]


def test_the_coverage_counts_it_covered_statically():
    rs = load_release_scenarios()
    c = conf()
    wanted = rs.played(ROOT, rs.test_pack(ROOT)) | rs.transitions(ROOT) | rs.flows(c)
    assert rs.coverage(c["scenarios"], wanted, c.get("statically") or {}) == []
