"""A call of a shared workflow at the moving tag names one the tag already
has (#564): `uses: DiluxOne/.github/.github/workflows/x.yml@v7` of a workflow
no v7 release ships keeps the whole calling pipeline from starting (a
startup failure, no jobs), here at once and in every repository the day it
merges. A workflow this branch adds is called locally here, and from the
other repositories only after the release that ships it."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CALL = re.compile(r"^\s*uses:\s*DiluxOne/\.github/\.github/workflows/([\w.-]+)@(v\d+)\s*(?:#.*)?$", re.M)
# Added by #564 and in no v7 release yet: the follow-up after the release
# that ships them wires them into org-pull-request.yml, autopilot.yml and
# the template's issues.yml, and takes them off this list.
UNRELEASED = {"waiting-update.yml", "pr-screenshots.yml"}


def calls():
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")) + sorted((ROOT / "workflow-templates").glob("*.yml")):
        for name, ref in CALL.findall(path.read_text(encoding="utf-8")):
            yield path.relative_to(ROOT), name, ref


def test_no_call_at_the_tag_names_a_workflow_not_released_yet():
    bad = [(str(p), n) for p, n, _ in calls() if n in UNRELEASED]
    assert bad == [], bad
    assert (ROOT / ".github/workflows/waiting-update.yml").is_file() and (ROOT / ".github/workflows/pr-screenshots.yml").is_file()


def test_every_call_at_the_tag_names_a_workflow_the_latest_release_has():
    # Where the tags were fetched (a clone, `make pre-pr`): the latest
    # release of each major called must have every workflow called at it.
    for major in sorted({r for _, _, r in calls()}):
        tags = subprocess.run(["git", "tag", "-l", f"{major}.*", "--sort=-v:refname"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        if not tags:
            continue
        missing = sorted({(str(p), n) for p, n, r in calls() if r == major and subprocess.run(
            ["git", "cat-file", "-e", f"{tags[0]}:.github/workflows/{n}"], cwd=ROOT, capture_output=True).returncode != 0})
        assert missing == [], (tags[0], missing)


def test_the_pipelines_here_call_the_new_workflows_locally():
    text = lambda p: (ROOT / ".github/workflows" / p).read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/waiting-update.yml" in text("issues.yml")
    assert "uses: ./.github/workflows/waiting-update.yml" in text("pull-request.yml")
    assert "uses: ./.github/workflows/pr-screenshots.yml" in text("pull-request.yml")
