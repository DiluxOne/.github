"""Issue #615: the docs check must not fail a repository whose Markdown has no link."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_relative_links_steps_do_not_fail_when_lychee_finds_no_link():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "conventions.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["docs"]["steps"]
    lychee = [s for s in steps if str(s.get("uses", "")).startswith("lycheeverse/lychee-action@")]
    assert lychee, "the docs job has no lychee step"
    for step in lychee:
        fail_if_empty = step.get("with", {}).get("failIfEmpty", True)
        assert str(fail_if_empty).lower() == "false", (
            f"'{step.get('name')}' leaves failIfEmpty at its default (true): a repository "
            "whose Markdown has no link fails with 'No links were found'"
        )
        # A broken link must still fail the step.
        assert str(step["with"].get("fail", "")).lower() == "true"
