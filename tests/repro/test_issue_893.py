"""#893: the release scenario `prd-edited-after-acceptance` lost the person's
PRD edit. The `spec` intent read the issue's body, and a person's edit that
landed before its write was overwritten by `body + Spec` built from the stale
copy, so the "Edited after its acceptance" job found the sealed PRD again and
kept `accepted`. Whatever appends the Spec must append it to the body as it
is when it writes, never to an older copy, and put back an edit its own write
overwrote.

The step runs as the workflow runs it (`autopilot.py apply <outbox> spec`),
with a `gh` stub that keeps the issue's body and its edit history.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOT = "dilux-bot[bot]"

PRD = "## Problem\n\nThe test repository has no greeting.\n"
EDITED = "## Problem\n\nThe test repository has no greeting, nor a farewell.\n"
SPEC = "### Spec: approach\n\nAdd a greeting.\n\n### Spec: files\n\n- hello.txt\n"

# The stub `gh`: STATE holds the issue's body, its edits and when the
# person's edit lands ("after-read": right after the bot's first read;
# "during-write": between the bot's last read and its write).
GH = r'''
import datetime, json, os, sys
path = os.environ["STATE"]
st = json.load(open(path))
args = sys.argv[1:]
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def save():
    json.dump(st, open(path, "w"))
def edit(who, body):
    st["body"] = body
    st["edits"].append({"editedAt": now, "editor": {"login": who}, "diff": body})
if args[:2] == ["issue", "view"]:
    st["views"] += 1
    print(json.dumps({"body": st["body"]}))
    if st["when"] == "after-read" and st["views"] == 1:
        edit(st["person"], st["edited"])
    save()
elif args[:2] == ["issue", "edit"]:
    body = sys.stdin.read()
    if st["when"] == "during-write" and not st.get("landed"):
        st["landed"] = True
        edit(st["person"], st["edited"])
    edit(st["bot"], body)
    st["writes"] += 1
    save()
elif args[:2] == ["api", "graphql"]:
    nodes = list(reversed(st["edits"]))  # GitHub lists the newest first
    print(json.dumps({"data": {"repository": {"issue": {"userContentEdits": {"nodes": nodes}}}}}))
else:
    sys.stderr.write("unexpected gh call: %r\n" % (args,))
    sys.exit(1)
'''


def apply_spec(tmp_path, when):
    """The issue's body (and the run's log) after the `spec` intent is
    applied, with a person's edit of the PRD landing WHEN."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(f"#!{sys.executable}\n{GH}", encoding="utf-8")
    gh.chmod(0o755)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"body": PRD, "edits": [{"editedAt": "2026-11-20T05:00:00Z", "editor": {"login": "someone"}, "diff": PRD}],
                                 "when": when, "edited": EDITED, "person": "someone", "bot": BOT, "views": 0, "writes": 0}), encoding="utf-8")
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(json.dumps({"kind": "spec", "text": SPEC}) + "\n", encoding="utf-8")
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", STATE=str(state), GITHUB_REPOSITORY="DiluxOne/diluxone-test",
               NUMBER="3109", PR="", DX_BOT_LOGIN=BOT, DX_BOT_APP="dilux-bot", RUNNER_TEMP=str(tmp_path))
    env.pop("GITHUB_OUTPUT", None)
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "autopilot.py"), "apply", str(outbox), "spec"],
                          env=env, capture_output=True, text=True, cwd=tmp_path, timeout=60)
    return json.loads(state.read_text(encoding="utf-8"))["body"], done.stdout + done.stderr


def test_an_edit_between_the_read_and_the_write_keeps_the_persons_prd(tmp_path):
    body, log = apply_spec(tmp_path, "after-read")
    assert "nor a farewell" in body, f"the person's PRD edit was overwritten by the stale copy:\n{body}\n{log}"
    assert body.count("### Spec: approach") == 1, body
    assert body.rstrip().endswith("- hello.txt"), body


def test_an_edit_overwritten_by_the_write_is_put_back_with_the_spec(tmp_path):
    body, log = apply_spec(tmp_path, "during-write")
    assert "nor a farewell" in body, f"the person's PRD edit was overwritten by the bot's write:\n{body}\n{log}"
    assert body.count("### Spec: approach") == 1, body
    assert "put back" in log, log


def test_no_edit_appends_the_spec_once(tmp_path):
    body, log = apply_spec(tmp_path, "never")
    assert body == PRD.rstrip() + "\n\n" + SPEC.strip() + "\n", log
