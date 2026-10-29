"""#496: a Bug a maintainer typed, which the classifier calls `enhancement`, stays a Bug
(#341) but the triage labels it `enhancement`; the reporter expected `bug:unconfirmed`.

scripts/triage-act.sh runs here as a command, with a stand-in for `gh` first on PATH that
records every call and answers as for an issue whose Type is Bug, set by a writer.
"""
import os
import subprocess
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


def test_a_bug_a_maintainer_typed_that_the_classifier_calls_enhancement_is_labeled_bug_unconfirmed(tmp_path):
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
    }
    subprocess.run(["bash", str(ROOT / "scripts" / "triage-act.sh")], env=env, cwd=tmp_path,
                   capture_output=True, text=True)

    calls = log.read_text().splitlines()
    edits = [c for c in calls if c.startswith("issue edit 7 ") and "--add-label" in c]
    assert any("--add-label bug:unconfirmed" in c for c in edits), f"no bug:unconfirmed label in {edits}"
    assert not any("enhancement" in c for c in edits), f"a Bug it keeps is labeled enhancement: {edits}"
    assert not any("type=Feature" in c for c in calls), "the maintainer's Bug was retyped"
