"""`make pre-pr`, the one check before a pull request (#479): the conventions
check reads whether the repository must have one from the organisation's
configuration, never the pull request's, and the switch stays off until
every repository has one."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def steps(job):
    wf = yaml.safe_load((ROOT / ".github/workflows/conventions.yml").read_text(encoding="utf-8"))
    return wf["jobs"][job]["steps"]


def test_the_conventions_check_gets_the_mode_from_the_organisation():
    all_steps = steps("conventions")
    names = [s.get("name") for s in all_steps]
    mode = next(s for s in all_steps if s.get("id") == "pre-pr")
    assert "pre-pr.py required" in mode["run"] and mode["env"] == {"REPO": "${{ github.event.repository.name }}"}
    # A configuration that cannot be read fails the step, never checks nothing.
    assert 'mode=$(python3 .dx-central/scripts/pre-pr.py required "$REPO")' in mode["run"]
    check = next(s for s in all_steps if s.get("name") == "Check branch, title and commits")
    assert check["env"]["PRE_PR"] == "${{ steps.pre-pr.outputs.mode }}"
    assert names.index(mode["name"]) < names.index(check["name"])
    assert names.index("Checkout the conventions script") < names.index(mode["name"])


def test_the_switch_stays_off_until_every_repository_has_one():
    assert yaml.safe_load((ROOT / "org.yml").read_text(encoding="utf-8"))["pre-pr"] == "optional"
