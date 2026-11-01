"""One reference of every setting (#568 C4): docs/configuration.md is what
`settings.py docs` writes from policy/settings-schema.yml, and
`settings.py check`, which the scripts job runs, fails when a setting the
engine's files hold is missing from the schema, or one the schema lists
is gone from it."""
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PARTS = ("org.yml", "repos.yml", "labels.yml", "kinds", "scripts", "policy", ".github/workflows", "docs/configuration.md")


def settings(*args):
    return subprocess.run(["python3", str(ROOT / "scripts" / "settings.py"), *args], capture_output=True, text=True)


@pytest.fixture()
def tree(tmp_path):
    for part in PARTS:
        src, dst = ROOT / part, tmp_path / part
        dst.parent.mkdir(parents=True, exist_ok=True)
        (shutil.copytree if src.is_dir() else shutil.copy)(src, dst)
    return tmp_path


def test_check_passes_on_the_tree():
    out = settings("check")
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout == ""


def test_the_page_is_what_docs_writes():
    assert (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8") == settings("docs").stdout


def test_every_setting_is_on_the_page_with_its_default_levels_and_limit():
    page = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
    schema = yaml.safe_load((ROOT / "policy" / "settings-schema.yml").read_text(encoding="utf-8"))
    for pattern, entries in schema["files"].items():
        assert f"## `{pattern}`" in page
        section = page.split(f"## `{pattern}`", 1)[1].split("\n## ", 1)[0]
        for s in entries:
            name = "(the whole list)" if s["key"] == "." else f"`{s['key']}`"
            row = next(line for line in section.split("\n") if line.startswith(f"| {name}: "))
            cells = row.split(" | ")
            assert cells[2] == f"`{s['org']}`" and cells[3] == f"`{s['repo']}`", row
            assert cells[1] and cells[4], row


def test_a_setting_deleted_from_the_schema_fails(tree):
    path = tree / "policy" / "settings-schema.yml"
    schema = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema["files"]["policy/autonomy.yml"] = [s for s in schema["files"]["policy/autonomy.yml"] if s["key"] != "autopilot-runs"]
    path.write_text(yaml.safe_dump(schema, sort_keys=False), encoding="utf-8")
    out = settings("check", str(tree))
    assert out.returncode == 1
    assert "policy/autonomy.yml autopilot-runs: a setting the schema (policy/settings-schema.yml) does not list" in out.stdout


def test_a_key_added_to_the_policy_fails(tree):
    path = tree / "policy" / "autonomy.yml"
    path.write_text(path.read_text(encoding="utf-8") + "\nautopilot-naps: 3\n", encoding="utf-8")
    out = settings("check", str(tree))
    assert out.returncode == 1
    assert "policy/autonomy.yml autopilot-naps: a setting the schema" in out.stdout


def test_a_key_added_to_a_lane_or_a_pack_fails(tree):
    path = tree / "kinds" / "wordpress-plugin" / "pack.yml"
    path.write_text(path.read_text(encoding="utf-8") + "\nrelease-train: weekly\n", encoding="utf-8")
    out = settings("check", str(tree))
    assert "kinds/wordpress-plugin/pack.yml release-train: a setting the schema" in out.stdout


def test_a_setting_no_script_reads_fails(tree):
    path = tree / "policy" / "settings-schema.yml"
    schema = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema["files"]["policy/autonomy.yml"].append({"key": "autopilot-naps", "org": "any", "repo": "never", "limit": "x", "read-by": ["scripts/autonomy.py"], "issue": "#568", "says": "x"})
    path.write_text(yaml.safe_dump(schema, sort_keys=False), encoding="utf-8")
    out = settings("check", str(tree))
    assert "scripts/autonomy.py does not read `autopilot-naps`" in out.stdout


def test_a_page_out_of_step_fails(tree):
    page = tree / "docs" / "configuration.md"
    page.write_text(page.read_text(encoding="utf-8").replace("| `autopilot-runs`", "| `autopilot-runz`"), encoding="utf-8")
    out = settings("check", str(tree))
    assert out.returncode == 1 and "docs/configuration.md: not what `settings.py docs` writes" in out.stdout


def test_the_scripts_job_runs_the_check():
    jobs = yaml.safe_load((ROOT / ".github" / "workflows" / "pull-request.yml").read_text(encoding="utf-8"))["jobs"]
    runs = [str(s.get("run", "")) for job in jobs.values() for s in job.get("steps", [])]
    assert {"python3 scripts/settings.py --test", "python3 scripts/settings.py check", "python3 scripts/settings.py org-free"} <= set(runs)
