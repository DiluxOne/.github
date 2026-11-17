"""#496: a Bug a maintainer typed, which the classifier calls `enhancement`, stays a Bug
(#341) but the triage labels it `enhancement`; the reporter expected it to wait for its
reproduction as a bug (then `bug:unconfirmed`; on the issue's board since #801).

scripts/triage-act.sh runs here as a command, with a stand-in for `gh` first on PATH that
records every call and answers as for an issue whose Type is Bug, set by a writer, and a
fixture directory standing in for the issue's board (RECEIPTS_FIXTURE).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FAKE_GH = r"""#!/usr/bin/env bash
printf '%s\n' "$*" | tr '\n' ' ' >> "$GH_LOG"; echo >> "$GH_LOG"
case "$*" in
  "api graphql -f query=query"*) echo boss ;;
  "api repos/o/r/collaborators/"*) echo write ;;
  "api repos/o/r/issues/7 --jq"*) echo Bug ;;
esac
exit 0
"""


def test_a_bug_a_maintainer_typed_that_the_classifier_calls_enhancement_waits_for_its_reproduction(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    log.write_text("")
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "GH_LOG": str(log),
        "VERDICT": '{"category":"enhancement"}',
        "REPLY": "x",
        "SUMMARY": "s",
        "NUMBER": "7",
        "GITHUB_REPOSITORY": "o/r",
        "MAINTAINER": "boss",
        "MODEL": "m",
        "RECEIPTS_FIXTURE": str(tmp_path / "board"),
        "AUTOPILOT_JSON": "null",
        "LABELS_JSON": "[]",
        "HELD": "",
    }
    subprocess.run(["bash", str(ROOT / "scripts" / "triage-act.sh")], env=env, cwd=tmp_path,
                   capture_output=True, text=True)

    calls = log.read_text().splitlines()
    edits = [c for c in calls if c.startswith("issue edit 7 ") and "--add-label" in c]
    got = subprocess.run([sys.executable, str(ROOT / "scripts" / "receipts.py"), "state", "get", "repro"], env=env,
                         capture_output=True, text=True)
    assert (json.loads(got.stdout) or {}).get("step") == "waiting", f"its board does not show it waiting: {got.stdout}"
    assert not any("bug:unconfirmed" in c for c in edits), f"a retired label (#801) in {edits}"
    assert not any("enhancement" in c for c in edits), f"a Bug it keeps is labeled enhancement: {edits}"
    assert not any("type=Feature" in c for c in calls), "the maintainer's Bug was retyped"
