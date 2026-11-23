"""#958 C2: when the review builds its brief, the brief carries the same
impact map the work's prompt does (scripts/impact.py, from git, no model):
claude-review.yml builds it at BASE..HEAD from the closing issue's Spec and
hands it to review-brief.sh as `IMPACT=`, which adds its section."""
import os
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from steps import sections  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
ENV = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
SPEC = """### Spec: approach

Narrow the route.

### Spec: files

- `includes/rest.php`
"""


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], env=ENV, capture_output=True, text=True, check=True).stdout.strip()


def write(repo, path, text):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text, encoding="utf-8")


def scratch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, ".github/review-policy.yml", "kind: wordpress-plugin\n")
    write(repo, "includes/rest.php", "<?php\nfunction dx_rest_boot() {\n  register_rest_route( 'dx/v1', '/items', array() );\n}\n")
    write(repo, "plugin.php", "<?php\nrequire_once __DIR__ . '/includes/rest.php';\ndx_rest_boot();\n")
    write(repo, "tests/Unit/RestTest.php", "<?php\n// includes/rest.php\nclass RestTest {}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "chore: base")
    write(repo, "includes/rest.php", "<?php\nfunction dx_rest_boot() {\n  register_rest_route( 'dx/v1', '/items', array( 'methods' => 'GET' ) );\n}\n")
    git(repo, "commit", "-qam", "fix: narrow")
    return repo, git(repo, "rev-parse", "HEAD^"), git(repo, "rev-parse", "HEAD")


def impact_map(tmp_path, repo, base, head):
    (tmp_path / "issue.md").write_text(SPEC, encoding="utf-8")
    ran = subprocess.run([sys.executable, str(ROOT / "scripts" / "impact.py"), "map", "--spec", str(tmp_path / "issue.md"),
                          "--base", base, "--head", head, "--kind", "wordpress-plugin"], cwd=repo, env=ENV, capture_output=True, text=True)
    assert ran.returncode == 0, ran.stderr
    (tmp_path / "impact.md").write_text(ran.stdout, encoding="utf-8")
    return ran.stdout


def brief(tmp_path, repo, base, head, **extra):
    out = tmp_path / "brief.md"
    env = dict(ENV, REPO="o/r", TITLE="fix(rest): narrow", BODY="the body", BASE=base, HEAD=head, FLOOR="high", REASONS="why",
               PROFILE="general", CENTRAL=str(ROOT), WORK=str(tmp_path / "work"), OUT=str(out), **extra)
    subprocess.run(["bash", str(ROOT / "scripts" / "review-brief.sh")], cwd=repo, env=env, capture_output=True, text=True, check=True)
    return out.read_text(encoding="utf-8")


def test_c2_the_brief_carries_the_same_map(tmp_path):
    repo, base, head = scratch(tmp_path)
    the_map = impact_map(tmp_path, repo, base, head)
    for what in ("includes/rest.php", "plugin.php", "tests/Unit/RestTest.php", "rest-route"):
        assert what in the_map, f"the map names {what}"
    text = brief(tmp_path, repo, base, head, IMPACT=str(tmp_path / "impact.md"))
    section = sections(text).get("Impact map (deterministic)")
    assert section is not None, "the brief has its \"## Impact map (deterministic)\" section"
    assert the_map.strip() in section, "the same map, as impact.py printed it"


def test_c2_no_map_no_section(tmp_path):
    repo, base, head = scratch(tmp_path)
    assert "## Impact map" not in brief(tmp_path, repo, base, head)
    assert "## Impact map" not in brief(tmp_path, repo, base, head, IMPACT=str(tmp_path / "missing.md"))


def test_c2_the_review_builds_the_map_and_exports_it():
    review = yaml.safe_load((WORKFLOWS / "claude-review.yml").read_text(encoding="utf-8"))
    steps = review["jobs"]["review"]["steps"]
    briefs = [s for s in steps if "review-brief.sh" in str(s.get("run", ""))]
    assert len(briefs) == 1
    run = briefs[0]["run"]
    assert ".dx-central/scripts/impact.py map" in run, "the brief step runs impact.py map"
    assert '--base "$BASE" --head "$HEAD"' in run, "at BASE..HEAD"
    assert "export IMPACT" in run, "and hands it to review-brief.sh"
    assert "${{" not in run, "untrusted text goes through env:, never ${{ }} in run:"
    local = (ROOT / "scripts" / "local-review.sh").read_text(encoding="utf-8")
    assert "impact.py\" map" in local and "IMPACT=" in local, "local-review.sh passes the same, from the diff alone"
