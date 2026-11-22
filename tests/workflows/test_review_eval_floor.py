"""The review's evaluation has an absolute floor on the found side (#930
C2): a review that finds fewer flag cases than the policy's
`review-eval.found-floor` fails the check whatever the baseline says, one
that finds none always does, and no baseline is written below it."""
import importlib.util
import io
import json
import math
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "policy" / "review-policy.default.yml"


def mod():
    spec = importlib.util.spec_from_file_location("review_eval", ROOT / "scripts" / "review-eval.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def results(found, flag=10, clean=10):
    return ([{"id": f"f{i}", "expect": "flag", "plays": [i < found] * 3} for i in range(flag)]
            + [{"id": f"c{i}", "expect": "clean", "plays": [True] * 3} for i in range(clean)])


def share():
    pol = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    got = (pol.get("review-eval") or {}).get("found-floor")
    assert isinstance(got, (int, float)) and 0 < got <= 1, f"policy has no review-eval.found-floor share: {got!r}"
    return got


def main(m, argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = m.main(argv)
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch):
    m = mod()
    base = tmp_path / "baseline.json"
    monkeypatch.setattr(m, "BASELINE", str(base))

    def play(found, baseline=None):
        res = tmp_path / f"r{found}.json"
        res.write_text(json.dumps(results(found)))
        if baseline is not None:
            base.write_text(json.dumps({"found": baseline, "flag": 10, "blocked": 0, "clean": 10, "unreviewed": 0, "plays": 3}))
        return str(res)
    return m, play, base


def test_the_policy_sets_the_floor():
    assert share() == 0.2


def test_finding_none_fails_against_a_baseline_of_none(env):
    m, play, _ = env
    code, out, _ = main(m, ["score", play(0, baseline=0)])
    assert code == 1, out
    assert "floor" in out


@pytest.mark.parametrize("baseline", range(0, 11))
def test_below_the_floor_fails_against_any_baseline(env, baseline):
    m, play, _ = env
    need = max(1, math.ceil(share() * 10))
    code, out, _ = main(m, ["score", play(need - 1, baseline=baseline)])
    assert code == 1, (baseline, out)


def test_at_the_floor_and_the_baseline_passes(env):
    m, play, _ = env
    need = max(1, math.ceil(share() * 10))
    code, out, _ = main(m, ["score", play(need, baseline=need)])
    assert code == 0, out


def test_the_floor_is_never_below_one_case():
    m = mod()
    assert hasattr(m, "found_floor"), "review-eval.py has no found_floor()"
    assert m.found_floor(10, 0.3) == 3
    assert m.found_floor(10, 0) == 1
    assert m.found_floor(1, 0.01) == 1
    assert m.found_floor(11, 0.3) == 4


def test_baseline_refuses_to_write_below_the_floor(env):
    m, play, base = env
    need = max(1, math.ceil(share() * 10))
    code, _, err = main(m, ["baseline", play(need - 1)])
    assert code == 1
    assert "floor" in err
    assert not base.exists()
    code, _, _ = main(m, ["baseline", play(need)])
    assert code == 0 and json.loads(base.read_text())["found"] == need
