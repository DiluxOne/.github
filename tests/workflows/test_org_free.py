"""No organisation's own values in the engine (#568 C3): its packs,
workflows, workflow templates, scripts, review profiles and policies name
neither DiluxOne's App, nor its maintainers, catalog, security repository
or repositories; those live in org.yml and repos.yml, which another
organisation replaces with its own. `settings.py org-free` searches for
them, leaving out comments, self-tests, tests/ and scripts/fixtures/."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PARTS = ("org.yml", "repos.yml", "kinds", ".github/workflows", "workflow-templates", "scripts", "review-profiles", "policy")


def org_free(root):
    return subprocess.run(["python3", str(ROOT / "scripts" / "settings.py"), "org-free", str(root)], capture_output=True, text=True)


@pytest.fixture()
def tree(tmp_path):
    for part in PARTS:
        src = ROOT / part
        (shutil.copytree if src.is_dir() else shutil.copy)(src, tmp_path / part)
    return tmp_path


def test_the_engine_names_no_organisation():
    out = org_free(ROOT)
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout == ""


def test_a_value_planted_in_a_pack_is_found(tree):
    pack = tree / "kinds" / "ai-agent-plugin" / "pack.yml"
    pack.write_text(pack.read_text(encoding="utf-8") + "\nbot: dilux-bot\n", encoding="utf-8")
    out = org_free(tree)
    assert out.returncode == 1
    assert out.stdout.startswith("kinds/ai-agent-plugin/pack.yml:") and ": dilux-bot:" in out.stdout


def test_a_value_planted_in_a_workflow_is_found(tree):
    wf = tree / ".github" / "workflows" / "auto-merge.yml"
    text = wf.read_text(encoding="utf-8").replace("DX_BOT_LOGIN: ${{ vars.DX_BOT_LOGIN }}", "DX_BOT_LOGIN: ${{ vars.DX_BOT_LOGIN || 'dilux-bot[bot]' }}", 1)
    assert text != wf.read_text(encoding="utf-8")
    wf.write_text(text, encoding="utf-8")
    out = org_free(tree)
    assert out.returncode == 1
    assert ".github/workflows/auto-merge.yml:" in out.stdout and "dilux-bot[bot]" in out.stdout


def test_a_maintainer_or_a_repository_is_found_too(tree):
    script = tree / "scripts" / "planted.py"
    script.write_text('WHO = "soydiloreto"\nWHERE = "DiluxOne/diluxone-mermaid"\n', encoding="utf-8")
    out = org_free(tree)
    assert "scripts/planted.py:1: soydiloreto" in out.stdout and "scripts/planted.py:2: diluxone-mermaid" in out.stdout


def test_a_comment_or_a_self_test_is_not(tree):
    pack = tree / "kinds" / "ai-agent-plugin" / "pack.yml"
    pack.write_text(pack.read_text(encoding="utf-8") + "\n# dilux-bot opens it\n", encoding="utf-8")
    (tree / "scripts" / "planted.py").write_text(
        '"""Opened by dilux-bot."""\n# dilux-bot\n\n\ndef self_test():\n    assert login("dilux-bot[bot]")\n\n\ndef merge_test():\n    return "soydiloreto"\n',
        encoding="utf-8")
    (tree / "scripts" / "planted.sh").write_text(
        '#!/usr/bin/env bash\n# dilux-bot\nself_test() {\n  PR_AUTHOR=dilux-bot[bot] check\n}\nif [ "${1:-}" = --test ]; then\n  echo soydiloreto\nfi\n',
        encoding="utf-8")
    out = org_free(tree)
    assert out.returncode == 0, out.stdout


def test_the_organisations_own_files_and_tests_are_not_searched(tree):
    (tree / "tests").mkdir()
    (tree / "tests" / "test_x.py").write_text('BOT = "dilux-bot"\n', encoding="utf-8")
    (tree / "scripts" / "fixtures").mkdir(exist_ok=True)
    (tree / "scripts" / "fixtures" / "x.json").write_text('{"author": "dilux-bot"}\n', encoding="utf-8")
    out = org_free(tree)
    assert out.returncode == 0, out.stdout
