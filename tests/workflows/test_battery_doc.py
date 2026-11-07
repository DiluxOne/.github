"""What a battery is (#688): kinds/README.md defines it in one paragraph
under `## The battery`, and the first "battery" of each page that uses the
word links to that definition."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
KINDS = ROOT / "kinds" / "README.md"


def section(text, heading):
    start = text.index(f"\n{heading}\n") + len(heading) + 2
    end = text.find("\n## ", start)
    return text[start:] if end < 0 else text[start:end]


def definition():
    paragraphs = [p for p in section(KINDS.read_text(encoding="utf-8"), "## The battery").split("\n\n") if p.strip()]
    assert len(paragraphs) == 1, paragraphs
    return paragraphs[0]


def test_one_paragraph_says_what_a_battery_is():
    assert "**battery**" in definition()


def test_it_names_the_pack_key_it_comes_from():
    assert "`workflows` key" in definition()


def test_it_gives_the_wordpress_plugin_battery():
    pack = yaml.safe_load((ROOT / "kinds" / "wordpress-plugin" / "pack.yml").read_text(encoding="utf-8"))
    for workflow in pack["workflows"]:
        assert f"`{workflow}`" in definition(), workflow


def test_it_says_how_it_differs_from_what_every_repository_gets():
    text = definition()
    assert "every-repository" in text
    repos = yaml.safe_load((ROOT / "repos.yml").read_text(encoding="utf-8"))
    for caller in repos["callers"]["every-repository"]:
        assert f"`{caller}`" in text, caller
    assert "`org-pull-request.yml`" in text
    assert "only a repository of that kind" in text


def test_it_says_a_repository_runs_it_through_its_callers():
    text = definition()
    assert "through its callers" in text
    assert "workflow-templates/" in text
    assert "sync-repos.py callers" in text
