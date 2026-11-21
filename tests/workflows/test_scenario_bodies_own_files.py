"""#881: release scenario `bug-by-person-merges` fails at its first `until`.
It opened its issue from the body `bug-not-reproduced`, which names
`scenarios/bug-not-reproduced/greeting.md`, the file of another scenario that
plays at the same time; the triage read the two issues as one report, marked
this one `duplicate`, never reproduced it and never added `needs-info`. No
scenario may open an issue or a pull request whose body names another
scenario's `scenarios/<id>/` path, and `preconditions` refuses one that does.
The triage also read "the same title": no two scenarios that open a Bug may
have titles where one starts with the other."""
import importlib.util
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load():
    spec = importlib.util.spec_from_file_location("release_scenarios_881", ROOT / "scripts" / "release-scenarios.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rs = load()
REAL = yaml.safe_load((ROOT / "tests/release/scenarios.yml").read_text(encoding="utf-8"))
PATH = re.compile(r"scenarios/([A-Za-z0-9_-]+)/")


def opened_bodies(s, bodies):
    opens = s.get("opens") or {}
    for kind in ("issue", "pull"):
        if kind in opens:
            yield kind, rs.body_of((opens[kind] or {}).get("body"), bodies)


def test_no_scenario_opens_a_body_that_names_another_scenarios_file():
    others = []
    for s in REAL["scenarios"]:
        for kind, body in opened_bodies(s, REAL["bodies"]):
            for other in sorted(set(PATH.findall(body)) - {s["id"]}):
                others.append(f"{s['id']}: its {kind}'s body names scenarios/{other}/")
    assert others == [], others


def test_preconditions_refuses_a_body_that_names_another_scenarios_file():
    synthetic = {"id": "copycat", "opens": {"issue": {"body": "borrowed"}}, "expect": {"labels": ["needs-info"]}}
    bodies = {"borrowed": "Read `scenarios/someone-else/greeting.md` on `main`.\n"}
    got = rs.preconditions([synthetic], bodies, {}, repro=True)
    assert any("scenarios/someone-else/" in p for p in got), got
    own = rs.preconditions([dict(synthetic, id="someone-else")], bodies, {}, repro=True)
    assert own == [], own


def test_preconditions_has_no_such_refusal_for_the_real_scenarios():
    got = rs.preconditions(REAL["scenarios"], REAL["bodies"], {}, types=REAL.get("types") or {}, repro=True)
    assert [p for p in got if "another scenario's file" in p] == []


def bug_titles(scenarios, types):
    """Each scenario's Bug issue title: the issue it opens (or the one its
    pull request closes), its own `type:` over the Type its body's form
    gives it."""
    for s in scenarios:
        opens = s.get("opens") or {}
        for issue in (opens.get("issue"), (opens.get("pull") or {}).get("issue")):
            if issue and (issue.get("type") or types.get(issue.get("body"))) == "Bug":
                yield s["id"], issue.get("title") or ""


def prefixed(titles):
    """The pairs of different scenarios whose Bug title starts with the other's."""
    norm = lambda t: " ".join(t.lower().split())
    return [f"{a}: {ta!r} starts with {b}'s {tb!r}" for a, ta in titles for b, tb in titles
            if a != b and norm(ta).startswith(norm(tb))]


def test_no_two_bug_scenarios_have_titles_where_one_starts_with_the_other():
    """On DiluxOne/diluxone-test#2913 the triage read "the same title":
    `fix: something failed once, accepted` is bug-not-reproduced's title
    plus one word."""
    got = prefixed(list(bug_titles(REAL["scenarios"], REAL.get("types") or {})))
    assert got == [], got


def test_the_title_check_catches_a_prefix_and_spares_a_feature():
    types = {"b": "Bug", "f": "Feature"}
    scenarios = [{"id": "one", "opens": {"issue": {"title": "fix: something failed once", "body": "b"}}},
                 {"id": "two", "opens": {"issue": {"title": "fix: something failed once, accepted", "body": "b"}}},
                 {"id": "three", "opens": {"issue": {"title": "fix: something failed once, again", "body": "f"}}}]
    assert prefixed(list(bug_titles(scenarios, types))) == [
        "two: 'fix: something failed once, accepted' starts with one's 'fix: something failed once'"]
