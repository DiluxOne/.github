"""Issue #607: the docs check must not fail a repository with no Markdown under .github/."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GLOB = ".github/**/*.md"
TOLERANT_FLAGS = ("--skip-missing", "--allow-empty", "--no-fail-on-empty")


def test_relative_links_step_passes_when_no_markdown_is_under_github():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "conventions.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["docs"]["steps"]
    step = next(s for s in steps if s.get("name") == "Relative links resolve")
    args = step["with"]["args"]
    # A glob that can match no file is only safe when it is guarded or lychee tolerates it.
    guarded = bool(step.get("if")) or any(flag in args for flag in TOLERANT_FLAGS)
    assert GLOB not in args or guarded, (
        "lychee gets './.github/**/*.md' unconditionally: a repository without Markdown "
        "under .github/ fails with 'No files found for this input source'"
    )
