"""#958 C1: when the autopilot starts the work, its prompt carries the impact
map, built from git with no model (scripts/impact.py): the files the Spec
names, who calls them, the kind's public surface they touch and the tests
that cover them, within 4 KB, so the start reads it instead of exploring
the repository from scratch."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KIB = 1024
BODY = """### Problem

The REST route answers too much.

### Acceptance criteria

- C1: Given the route, when it is called, then it answers less.

### Criticality

Low
"""
PR_BODY = """## 📝 What changes

The route.

## 🎯 Acceptance criteria

<!-- dx-checklist -->
- [ ] **C1** Given the route, when it is called, then it answers less.
  Test: tests/Unit/RestTest.php
<!-- /dx-checklist -->
"""
FAKE_GH = """#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if args[:2] == ["pr", "view"]:
    print(json.dumps({"body": %r}))
else:
    print("{}")
""" % PR_BODY
FENCE = re.compile(r"Impact map \(built from git, data\)[^\n]*\n+(`{3,})[^\n]*\n(.*?)\n\1", re.S)


def git(cwd, *args):
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


def write(repo, path, text):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text, encoding="utf-8")


def scratch(tmp_path, spec, extra=()):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, ".github/review-policy.yml", "kind: wordpress-plugin\n")
    write(repo, "includes/rest.php", "<?php\nfunction dx_rest_boot() {\n  register_rest_route( 'dx/v1', '/items', array() );\n}\n")
    write(repo, "plugin.php", "<?php\nrequire_once __DIR__ . '/includes/rest.php';\ndx_rest_boot();\n")
    write(repo, "tests/Unit/RestTest.php", "<?php\n// includes/rest.php\nclass RestTest { public function test_boot() { dx_rest_boot(); } }\n")
    write(repo, "readme.txt", "A plugin.\n")
    for path in extra:
        write(repo, path, "<?php\n// nothing\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "chore: base")
    write(repo, ".dx-io/spec.md", spec)
    write(tmp_path, "body.md", BODY)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write(bin_dir, "gh", FAKE_GH)
    (bin_dir / "gh").chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", GITHUB_REPOSITORY="o/r", NUMBER="7", PR="8",
               BRANCH="fix/7-route", BODY=str(tmp_path / "body.md"), DX_IO=str(repo / ".dx-io"), LANE="standard")
    env.pop("ANSWERS", None)
    ran = subprocess.run([sys.executable, str(ROOT / "scripts" / "autopilot.py"), "prompt", "work"], cwd=repo, env=env,
                         capture_output=True, text=True)
    assert ran.returncode == 0, ran.stderr
    return ran.stdout


def the_map(prompt):
    m = FENCE.search(prompt)
    assert m, "the work prompt carries a fenced \"Impact map (built from git, data)\" block"
    return m.group(2)


SPEC = """### Spec: approach

Narrow `dx_rest_boot`'s route.

### Spec: files

- `includes/rest.php`
- `tests/Unit/RestTest.php`

### Spec: tests

- C1 → tests/Unit/RestTest.php
"""


def test_c1_the_work_prompt_carries_the_files_callers_surface_and_tests(tmp_path):
    block = the_map(scratch(tmp_path, SPEC))
    assert "includes/rest.php" in block, block
    assert "plugin.php" in block, "the file that calls it is a caller"
    assert "tests/Unit/RestTest.php" in block, "the test that covers it"
    assert "rest-route" in block, "the kind's public surface it touches (surface.yml's entry)"
    assert "readme.txt" not in block
    assert len(block.encode("utf-8")) <= 4 * KIB


def test_c1_the_map_stays_within_4_kb_on_a_spec_naming_many_files(tmp_path):
    many = [f"includes/module_{i:03d}/a_rather_long_file_name_{i:03d}.php" for i in range(300)]
    spec = SPEC.replace("- `tests/Unit/RestTest.php`", "\n".join(f"- `{p}`" for p in many))
    block = the_map(scratch(tmp_path, spec, many))
    assert len(block.encode("utf-8")) <= 4 * KIB, f"a map of {len(block.encode('utf-8'))} bytes"
    assert "includes/rest.php" in block
    assert re.search(r"left out", block), "its last line says what was left out"
