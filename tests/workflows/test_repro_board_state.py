"""The reproduction's steps on the issue's board (#801), not in labels.

`bug:unconfirmed` and `layer:*` are no longer set: the triage writes the
board's state, `repro` `{"step": "waiting", "layer": ...}`
(scripts/receipts.py state set), and the reproduction reads the layer from
it. Its outcomes are the board's too; `could-not-reproduce` became
`needs-info` and `repro:no-way` `needs-human`, which a person acts on. What
no script's --test can see, read from the workflows' files.
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RETIRED = ("bug:unconfirmed", "layer:", "could-not-reproduce", "repro:no-way")
# A label added (`--add-label X`, `--add-label "X"`) or created (`gh label
# create X`) whose name is, or starts with, a retired one.
ADDS = re.compile(r"""(?:--add-label|label create)\s+["']?([^\s"']+)""")


def load(path):
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def steps(workflow, job):
    return load(f".github/workflows/{workflow}")["jobs"][job]["steps"]


def step(all_steps, name):
    return next(s for s in all_steps if s.get("name") == name)


def runs(workflow):
    """(job, step name, run) of every step of the workflow."""
    for job, body in load(f".github/workflows/{workflow}")["jobs"].items():
        for s in body.get("steps") or []:
            if s.get("run"):
                yield job, s.get("name") or s.get("id"), s["run"]


def retired_in(text):
    return sorted({m for m in ADDS.findall(text) if any(m.startswith(r) for r in RETIRED)})


def test_c1_no_step_adds_a_retired_label():
    found = {f"{wf} {job}/{name}": retired_in(run) for wf in ("issue-triage.yml", "issue-repro.yml") for job, name, run in runs(wf)}
    found["scripts/triage-act.sh"] = retired_in((ROOT / "scripts/triage-act.sh").read_text(encoding="utf-8").split('if [ "${1:-}" = "--test" ]')[0])
    assert {k: v for k, v in found.items() if v} == {}


def test_c1_the_pattern_sees_a_retired_label():
    assert retired_in('gh issue edit "$N" --add-label "layer:$layer"; gh label create repro:no-way --force') == ["layer:$layer", "repro:no-way"]
    assert retired_in("gh issue edit 1 --add-label needs-info --add-label bug:confirmed") == []


def test_c1_the_triage_sets_the_reproduction_waiting_with_its_layer():
    act = (ROOT / "scripts/triage-act.sh").read_text(encoding="utf-8")
    assert '[ "$effective" != bug_unconfirmed ] || step=waiting' in act
    assert 'receipts.py" state set "repro=$repro"' in act
    assert "{step: $step}" in act and "{layer: $layer}" in act
    # The bot's own Bug (#247): no classifier, the same state, on a token
    # that reads the receipts branch for the board's seal row.
    nightly = load(".github/workflows/issue-triage.yml")["jobs"]["nightly"]
    mark = step(nightly["steps"], "Its reproduction waits, on its board")
    assert "receipts.py state set" in mark["run"] and '{step: "waiting"' in mark["run"]
    token = next(s for s in nightly["steps"] if s.get("id") == "bot")["with"]
    assert token["permission-contents"] == "read" and token["permission-issues"] == "write"
    assert any(s.get("with", {}).get("repository") == "DiluxOne/.github" and s["with"].get("path") == ".dx-central" for s in nightly["steps"])


def test_c1_the_way_step_reads_the_layer_from_the_board():
    write = steps("issue-repro.yml", "write")
    way = step(write, "The way to reproduce")
    assert "receipts.py state get repro" in way["run"]
    assert '"logic"' in way["run"], "no layer on the board is logic, as before"
    assert "labels" not in way["run"]
    assert way["env"]["GH_TOKEN"] == "${{ steps.bot.outputs.token }}"
    token = next(s for s in write if s.get("id") == "bot")["with"]
    assert token["permission-issues"] == "read", "the board is one of the issue's comments"


def test_c1_the_tokens_that_write_the_board_read_its_seal():
    write = steps("issue-repro.yml", "write")
    say = next(s for s in write if s.get("id") == "say")["with"]
    assert say["permission-contents"] == "read" and say["permission-issues"] == "write"
    report = steps("issue-repro.yml", "report")
    assert next(s for s in report if s.get("id") == "bot")["with"]["permission-contents"] == "write"


def test_c1_the_report_knows_the_layer_it_ran_for():
    report = step(steps("issue-repro.yml", "report"), "Labels, branch, pull request, comment")
    assert report["env"]["LAYER"] == "${{ needs.write.outputs.layer }}"
    assert "repro_state() {" in report["run"] and "receipts.py state set" in report["run"]
