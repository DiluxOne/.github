"""What a battery is (#688): kinds/README.md defines it in one section,
`## The battery`, and every page that says "battery" links its first
mention there."""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
KINDS = ROOT / "kinds" / "README.md"


def section(text, heading):
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, f"no '## {heading}' section"
    return match.group(1).strip()


def paragraphs(body):
    return [p for p in re.split(r"\n\s*\n", body) if p.strip()]


def test_c1_one_paragraph_defines_the_battery():
    body = section(KINDS.read_text(encoding="utf-8"), "The battery")
    paras = paragraphs(body)
    assert len(paras) == 1, "the battery is defined in one paragraph"
    text = " ".join(paras[0].split())
    assert "`workflows`" in text, "it names the pack key the battery comes from"
    pack = yaml.safe_load((ROOT / "kinds" / "wordpress-plugin" / "pack.yml").read_text(encoding="utf-8"))
    assert "wordpress-plugin" in text
    for workflow in pack["workflows"]:
        assert f"`{workflow}`" in text, f"the wordpress-plugin example names {workflow}"
    repos = yaml.safe_load((ROOT / "repos.yml").read_text(encoding="utf-8"))
    every = next(v["every-repository"] for v in repos.values() if isinstance(v, dict) and "every-repository" in v)
    assert "every-repository" in text, "it says how it differs from what every repository gets"
    for workflow in every:
        assert f"`{workflow}`" in text, f"it names {workflow}, which every repository gets"
    assert "caller" in text and "sync-repos.py callers" in text, "it says a repository runs it through its callers"
    assert "workflow-templates/" in text


def test_c1_the_earlier_mentions_link_to_it():
    text = KINDS.read_text(encoding="utf-8")
    heading = re.search(r"^## The battery$", text, re.M)
    assert heading, "no '## The battery' section"
    before = text[: heading.start()]
    first = re.search(r"\[?battery(\]\(#the-battery\))?", before, re.I)
    assert first and first.group(0) == "[battery](#the-battery)", "the intro links it"
    row = next(line for line in before.splitlines() if line.startswith("| `workflows` |"))
    assert "(#the-battery)" in row, "the `workflows` row links it"


@pytest.mark.parametrize("page", ["configuration.md", "adopting.md", "maintaining.md"])
def test_c2_the_first_battery_on_each_page_links_to_it(page):
    text = (ROOT / "docs" / page).read_text(encoding="utf-8")
    match = re.search(r"battery", text, re.I)
    assert match, f"docs/{page} no longer says battery"
    rest = text[match.start():]
    assert text[match.start() - 1] == "[" and re.match(r"battery\]\(\.\./kinds/README\.md#the-battery\)", rest, re.I), (
        f"the first 'battery' of docs/{page} does not link to ../kinds/README.md#the-battery"
    )
