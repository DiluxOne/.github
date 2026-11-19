"""The review set is big enough, and each case is played three times (#844 C3).

`run` and `score` refuse a set of fewer than 10 flag or 10 clean cases;
`run` reviews each case 3 times; `score` takes each case's median (found or
blocked when 2 of 3 plays say so) and shows the three plays. The review is
stood in: run_case is replaced, and the set's check with it.
"""
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/review-eval.py"


def load():
    spec = importlib.util.spec_from_file_location("review_eval", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def a_set(flag=10, clean=10):
    return [{"id": f"o/r#{i}:flag", "repo": "o/r", "pr": i, "expect": "flag", "path": "a.php", "line": 1, "fix": "f", "base": "b", "head": "h", "title": "t"} for i in range(flag)] + \
           [{"id": f"o/r#{100 + i}:clean", "repo": "o/r", "pr": 100 + i, "expect": "clean", "base": "b", "head": "h", "title": "t"} for i in range(clean)]


def results(flag_plays, clean_plays, flag=10, clean=10):
    return [{"id": f"o/r#{i}:flag", "expect": "flag", "plays": list(flag_plays)} for i in range(flag)] + \
           [{"id": f"o/r#{100 + i}:clean", "expect": "clean", "plays": list(clean_plays)} for i in range(clean)]


def run_main(mod, argv):
    out = io.StringIO()
    try:
        with redirect_stdout(out):
            code = mod.main(argv)
    except (KeyError, TypeError) as e:
        raise AssertionError(f"review-eval.py {argv[0]} cannot read a set of three plays: {e!r}") from e
    return code, out.getvalue()


def score(mod, rs):
    try:
        return mod.score(rs)
    except (KeyError, TypeError) as e:
        raise AssertionError(f"score cannot read each case's plays: {e!r}") from e


def needs(mod, *names):
    for name in names:
        assert hasattr(mod, name), f"no {name} in review-eval.py"


def test_the_set_holds_ten_of_each_kind_and_three_plays():
    mod = load()
    assert getattr(mod, "MIN_CASES", None) == 10
    assert getattr(mod, "PLAYS", None) == 3


def test_run_plays_each_case_three_times_on_a_fresh_checkout(tmp_path, monkeypatch):
    mod = load()
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(a_set()))
    needs(mod, "check")
    monkeypatch.setattr(mod, "CASES", str(cases))
    monkeypatch.setattr(mod, "check", lambda cases: 0)
    calls = []
    monkeypatch.setattr(mod, "run_case", lambda case, central, work: calls.append((case["id"], work)) or True)
    code, out = run_main(mod, ["run"])
    assert code == 0
    got = json.loads(out)
    assert len(got) == 20 and all(r["plays"] == [True, True, True] for r in got)
    assert len(calls) == 60
    assert len({w for _, w in calls}) == 3, "each play reviews in its own, fresh work directory"


def test_run_refuses_a_set_of_fewer_than_ten_of_a_kind(tmp_path, monkeypatch):
    mod = load()
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(a_set(flag=9)))
    needs(mod, "check")
    monkeypatch.setattr(mod, "CASES", str(cases))
    monkeypatch.setattr(mod, "check", lambda cases: 0)
    monkeypatch.setattr(mod, "run_case", lambda *a: (_ for _ in ()).throw(AssertionError("a paid review ran")))
    code, _ = run_main(mod, ["run"])
    assert code == 1


def test_score_refuses_a_set_of_fewer_than_ten_of_a_kind(tmp_path):
    mod = load()
    path = tmp_path / "results.json"
    path.write_text(json.dumps(results([True] * 3, [True] * 3, clean=9)))
    code, _ = run_main(mod, ["score", str(path)])
    assert code == 1


def test_score_takes_each_cases_median():
    mod = load()
    # Found on 2 of 3 plays is found; on 1 of 3 is missed.
    assert score(mod, results([True, False, True], [True, True, True]))["found"] == 10
    assert score(mod, results([True, False, False], [True, True, True]))["found"] == 0
    # Blocked on 2 of 3 plays is blocked; on 1 of 3 is not.
    assert score(mod, results([True] * 3, [False, True, False]))["blocked"] == 10
    assert score(mod, results([True] * 3, [False, True, True]))["blocked"] == 0
    # A play that could not be reviewed is dropped; fewer than 2 reviewed is unreviewed.
    now = score(mod, results([True, None, True], [None, None, True]))
    assert (now["found"], now["flag"], now["clean"], now["unreviewed"]) == (10, 10, 0, 10)


def test_the_three_plays_of_a_run_are_merged_and_shown(tmp_path):
    mod = load()
    needs(mod, "merge")
    files = []
    for n, ok in enumerate((True, False, True), 1):
        p = tmp_path / f"play-{n}.json"
        p.write_text(json.dumps(results([ok], [True])))
        files.append(str(p))
    merged = mod.merge([json.loads(Path(f).read_text()) for f in files])
    assert merged[0]["plays"] == [True, False, True]
    now = score(mod, merged)
    assert now["found"] == 10
    assert "found, missed, found" in mod.table(merged, now, {})
