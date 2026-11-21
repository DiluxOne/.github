"""No two release scenarios open the same bug (#916). The release lane plays
its scenarios at once in the test repository, and the triage reads every
open issue: a bug body that cites the same file name, or quotes the same
word, as another scenario's bug body is rightly called a duplicate of it
(v7.20.0's `bug-by-person-merges` was labelled `duplicate` of
`bug-reproduced`'s "helo" in a greeting.md, not `needs-info`, so its
`until` never held). Each body a scenario opens as a Bug (its `type:` or
the file's `types:`) must cite only file names, by base name under
`scenarios/<id>/`, and quote only words, that no other bug body does."""
import itertools
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "tests" / "release" / "scenarios.yml"

FILE = re.compile(r"scenarios/[^/\s`]+/([^/\s`]+)")
QUOTED = re.compile(r'"([^"\n]+)"')


def bug_bodies(data):
    """The names of the bodies some scenario opens as a Bug."""
    types = data.get("types") or {}
    out = []
    for s in data.get("scenarios") or []:
        issue = (s.get("opens") or {}).get("issue") or {}
        body = issue.get("body")
        if body and (issue.get("type") or types.get(body)) == "Bug" and body not in out:
            out.append(body)
    return out


def marks(text):
    """The file base names a body cites under scenarios/<id>/, and the words it quotes."""
    return {f"file {m}" for m in FILE.findall(text)} | {f"word {m.lower()}" for m in QUOTED.findall(text)}


def shared(data):
    """One line per pair of bug bodies that cite the same file name or quote the same word."""
    bodies = data.get("bodies") or {}
    names = bug_bodies(data)
    out = []
    for a, b in itertools.combinations(names, 2):
        common = sorted(marks(bodies.get(a, "")) & marks(bodies.get(b, "")))
        if common:
            out.append(f"{a} and {b} share {', '.join(common)}")
    return out


def test_no_two_real_bug_bodies_describe_the_same_bug():
    data = yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))
    assert len(bug_bodies(data)) >= 3
    assert shared(data) == []


def test_the_check_catches_a_shared_file_or_word_and_passes_distinct_ones():
    def data(one, two):
        return {"types": {"one": "Bug"},
                "bodies": {"one": one, "two": two, "feat": "Read `scenarios/x/greeting.md`."},
                "scenarios": [{"id": "a", "opens": {"issue": {"body": "one"}}},
                              {"id": "b", "opens": {"issue": {"body": "two", "type": "Bug"}}},
                              {"id": "c", "opens": {"issue": {"body": "feat"}}}]}

    assert shared(data('`scenarios/a/greeting.md` says "helo".', 'A reader saw `scenarios/b/greeting.md`.')) == [
        "one and two share file greeting.md"]
    assert shared(data('It says "helo".', 'It said "Helo" once.')) == ["one and two share word helo"]
    assert shared(data('`scenarios/a/greeting.md` says "helo".', '`scenarios/b/footer.md` says "thnaks".')) == []
