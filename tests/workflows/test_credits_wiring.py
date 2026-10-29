"""Who signs what (#491): every way a pull request merges writes the body
scripts/credits.py composes (the description, then the Credits block's
people and the commits' human co-authors), never one of its own."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CREDITS = 'body=$(python3 "$RUNNER_TEMP/central/scripts/credits.py" body "$GITHUB_REPOSITORY" "$PR")'


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def steps(name, job):
    return workflow(name)["jobs"][job]["steps"]


def merges(run):
    return [l.strip() for l in run.split("\n") if re.search(r"gh pr merge .*--body", l)]


def test_every_auto_merge_path_passes_the_credits_body():
    """C4: the merge queue squashes with the body given to --auto; every
    step that enables it (the autopilot's, a revert's, a release's, a sync
    run's and the usual decision) composes that body through credits.py,
    and nothing else writes co-authors."""
    seen = 0
    for step in steps("auto-merge.yml", "decide"):
        run = step.get("run", "")
        for line in merges(run):
            seen += 1
            assert '--body "$body"' in line, (step.get("name"), line)
            before = run[: run.index(line)]
            assert before.rfind(CREDITS) > before.rfind("body=$(gh "), step.get("name")
            assert CREDITS in before, step.get("name")
    assert seen == 5
    text = (ROOT / ".github/workflows/auto-merge.yml").read_text(encoding="utf-8")
    assert "grep -iE '^co-authored-by:'" not in text


def test_the_usual_decision_has_the_central_scripts_and_disables_first():
    step = next(s for s in steps("auto-merge.yml", "decide") if s.get("name") == "Enable or disable")
    run = step["run"]
    assert step["env"]["CENTRAL_REF"] == "${{ inputs.central-ref || job.workflow_sha }}"
    # Off before the body is read: a read that fails leaves nothing set to
    # merge with an old body.
    assert run.index("--disable-auto") < run.index(CREDITS) < run.index("--auto ${METHOD")
    assert run.index('fetch -q --depth 1 https://github.com/DiluxOne/.github "$CENTRAL_REF"') < run.index(CREDITS)


def test_the_hand_squash_passes_the_credits_body():
    """C4: scripts/squash-merge.sh, the maintainer's direct squash, is the
    same call, with the maintainer who merges as the one never credited."""
    text = (ROOT / "scripts/squash-merge.sh").read_text(encoding="utf-8")
    assert 'body=$(python3 "$here/credits.py" body "$repo" "$pr" "$merger")' in text
    assert "merger=$(gh api user --jq .login)" in text
    assert 'gh pr merge "$pr" --repo "$repo" --squash --delete-branch --body "$body"' in text
    assert "co-authored-by" not in text.lower().replace("co-authors", "")
