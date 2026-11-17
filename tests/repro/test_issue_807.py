"""#807: accepting a bug the reproduction already confirmed started a second
autopilot on the same fix. Before it starts on an accepted issue, prep must
ask whether the `bugfix-reproduced` lane already took it (dilux-bot's open
"The bug reproduced from #N" issue) or an open pull request closes it, and
then not start.
"""
import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def may_it_start_run():
    wf = yaml.safe_load((ROOT / ".github/workflows/autopilot.yml").read_text(encoding="utf-8"))
    return next(s for s in wf["jobs"]["prep"]["steps"] if s.get("id") == "may")["run"]


def autopilot():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("autopilot_807", ROOT / "scripts" / "autopilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_prep_asks_whether_the_fix_is_already_on_its_way_before_it_starts():
    run = may_it_start_run()
    assert "autopilot.py taken" in run, "prep starts without asking whether the reproduction lane or a pull request already took the issue"
    assert run.index("autopilot.py holder") < run.index("autopilot.py taken") < run.index("autopilot.py lane")


def test_the_lane_issue_of_the_report_and_its_pull_request_take_it():
    ap = autopilot()
    taken_by = getattr(ap, "taken_by", None)
    assert taken_by is not None, "nothing tells that the reproduction lane already took the report"
    lane = {"number": 20, "url": "https://github.com/o/r/issues/20", "title": "The bug reproduced from #7", "state": "OPEN",
            "author": ap.BOT_LOGINS[0], "prs": [{"number": 21, "url": "https://github.com/o/r/pull/21", "state": "OPEN"}]}
    assert taken_by(7, [lane], []) == {"lane": {"number": 20, "url": "https://github.com/o/r/issues/20"},
                                       "prs": [{"number": 21, "url": "https://github.com/o/r/pull/21"}]}
    assert taken_by(7, [{**lane, "author": "mallory"}], []) == {}
    assert taken_by(7, [], []) == {}
