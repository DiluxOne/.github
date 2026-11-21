"""A plugin for coding agents' release reaches the catalog (#552, C5): the
release workflow makes the GitHub release with the release App's token, and
the publish workflow brings the catalog's entry up to it through a pull
request on diluxone-plugins-ai, with a token scoped to that repository."""
from pathlib import Path
from unittest import mock

import yaml

try:
    import steps as steps_lib  # tests/workflows/steps.py: it runs a workflow's step with stubs
except ModuleNotFoundError:  # Test first's base has no steps.py (#845): there each call to it fails an assertion
    steps_lib = mock.Mock(**{f"{n}.side_effect": AssertionError("tests/workflows/steps.py is missing") for n in ("evaluate", "run", "step", "workflow")})

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def triggers(wf):
    return wf.get("on", wf.get(True))


def steps(wf, job):
    return wf["jobs"][job]["steps"]


def test_the_caller_releases_on_main_and_publishes_on_the_release():
    caller = load("workflow-templates/release-ai.yml")
    on = triggers(caller)
    assert on["release"] == {"types": ["published"]} and "push" in on
    assert caller["jobs"]["release"]["uses"] == "DiluxOne/.github/.github/workflows/plugin-release-ai.yml@v7"
    assert caller["jobs"]["publish"]["uses"] == "DiluxOne/.github/.github/workflows/plugin-publish-ai.yml@v7"
    assert "release" in caller["jobs"]["publish"]["if"]


def test_the_release_checks_the_manifests_and_uses_the_release_app():
    wf = load(".github/workflows/plugin-release-ai.yml")
    runs = " ".join(str(s.get("run", "")) for s in steps(wf, "release"))
    assert "agent-manifests.py check ." in runs and 'agent-manifests.py says . "$VERSION"' in runs
    app = [s for s in steps(wf, "release") if str(s.get("uses", "")).startswith("actions/create-github-app-token@")]
    assert app and app[0]["with"]["private-key"] == "${{ secrets.DILUX_RELEASE_PRIVATE_KEY }}"
    assert wf["jobs"]["release"]["permissions"] == {"contents": "read"}
    gate = " ".join(str(s.get("run", "")) for s in steps(wf, "version"))
    assert "release-issue.py verify" in gate and "release-gate.py" in gate


def test_the_publish_token_is_scoped_to_the_catalog_and_never_pushes_main():
    wf = load(".github/workflows/plugin-publish-ai.yml")
    assert wf["permissions"] == {}
    job = wf["jobs"]["bump"]
    # #568: any organisation's, never a fork's, and only with a catalog.
    assert "DiluxOne" not in job["if"] and "!github.event.repository.fork" in job["if"]
    app = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/create-github-app-token@")][0]
    assert app["with"]["repositories"] == "${{ steps.catalog.outputs.name }}"
    assert app["if"] == "steps.catalog.outputs.name != ''"
    assert triggers(wf)["workflow_call"]["inputs"]["catalog"]["default"] == ""
    catalog = [s for s in job["steps"] if s.get("id") == "catalog"][0]
    assert "org.py publishes-to ai-agent-plugin" in catalog["run"] and catalog["env"]["CATALOG"] == "${{ inputs.catalog }}"
    after = job["steps"][job["steps"].index(catalog) + 1:]
    assert all(s.get("if") == "steps.catalog.outputs.name != ''" for s in after)
    run = " ".join(str(s.get("run", "")) for s in after)
    assert 'agent-manifests.py bump "$VERSION" "$PLUGIN" . --ref "$TAG"' in run
    assert "gh pr create" in run and "gh issue create" in run and "api-commit.py push" in run
    assert "git push" not in run
    # Untrusted text (the tag) reaches the script through env only.
    assert "${{" not in run


def test_the_pack_releases_to_the_catalog():
    release = load("kinds/ai-agent-plugin/pack.yml")["release"]
    # #568: the organisation's catalog, from org.yml, never named in the pack.
    assert release["publishes-to"] == "{catalog}"
    assert load("org.yml")["catalogs"]["ai-agent-plugin"] == "diluxone-plugins-ai"
    assert release["workflow"] == "plugin-release-ai.yml" and release["publish"] == "plugin-publish-ai.yml"
    assert "stable" not in release and "{version}" in release["prepare"]


# agent-manifests.py, with its `bump` standing in (it adds the version to
# the catalog's one file) and its publish-plan the real one.
MANIFESTS = """import runpy, sys
if sys.argv[1] == "bump":
    with open("entry.txt", "a") as f:
        f.write(sys.argv[2] + "\\n")
    sys.exit(0)
sys.argv[0] = {real!r}
runpy.run_path({real!r}, run_name="__main__")
"""

# api-commit.py, recording what it pushes.
PUSH = """import json, os, sys
with open(os.environ["DX_CALLS"], "a") as f:
    f.write(json.dumps(["api-commit.py"] + sys.argv[1:]) + "\\n")
"""

GH = """case "$1 $2" in
  "issue list") [ -z "${FAIL_LIST:-}" ] || exit 1; cat "$OPEN_ISSUES" ;;
  "pr list") cat "$OPEN_PRS" ;;
  "issue create") echo https://github.com/DiluxOne/catalog/issues/31 ;;
esac"""


def publish(tmp_path, issues=(), prs=(), fail_list=False):
    """The bump job's step, on a catalog checkout whose bump changes a file,
    with gh listing ISSUES and PRS (number, title) as open."""
    import json
    import subprocess
    run, step = steps_lib.run, steps_lib.step

    real = str(ROOT / "scripts" / "agent-manifests.py")
    catalog = tmp_path / "work" / "catalog"
    catalog.mkdir(parents=True)
    git = lambda *a: subprocess.run(["git", "-C", str(catalog), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    (catalog / "entry.txt").write_text("1.0.0\n")
    git("add", "entry.txt")
    git("commit", "-q", "-m", "catalog")
    for name, items in (("issues", issues), ("prs", prs)):
        (tmp_path / f"{name}.json").write_text(json.dumps([{"number": n, "title": t} for n, t in items]))
    files = {".dx-central/scripts/agent-manifests.py": MANIFESTS.format(real=real), ".dx-central/scripts/api-commit.py": PUSH}
    env = {"PLUGIN": "DiluxOne/daw", "VERSION": "1.3.0", "TAG": "v1.3.0", "CATALOG": "DiluxOne/catalog", "DX_BOT_LOGIN": "dilux-bot[bot]",
           "RELEASE_URL": "https://github.com/DiluxOne/daw/releases/tag/v1.3.0", "OPEN_ISSUES": str(tmp_path / "issues.json"),
           "OPEN_PRS": str(tmp_path / "prs.json"), "FAIL_LIST": "1" if fail_list else ""}
    s = step("plugin-publish-ai.yml", "An issue and a pull request in the catalog", job="bump")
    return run(s, tmp_path, env=env, files=files, central=False, stubs={"gh": GH})


def creates(ran):
    return [c[:2] + [c[c.index("--title") + 1]] for c in ran.of("gh") if c[1] == "create"]


def test_the_publish_opens_the_issue_and_its_pull_request(tmp_path):
    ran = publish(tmp_path)
    assert ran.code == 0, ran.stdout + ran.stderr
    assert creates(ran) == [["issue", "create", "Bring daw to 1.3.0 in the catalog"], ["pr", "create", "chore(catalog): daw 1.3.0"]]
    pr = next(c for c in ran.of("gh") if c[:2] == ["pr", "create"])
    assert "Closes #31." in pr[pr.index("--body") + 1] and pr[pr.index("--head") + 1] == "chore/31-daw-1-3-0"
    # The branch is the run's own, made again from the catalog's main.
    assert ran.of("api-commit.py") == [["push", "chore/31-daw-1-3-0", "--onto", "origin/main", "--force"]]


def test_a_re_run_reuses_the_issue_the_first_run_opened(tmp_path):
    ran = publish(tmp_path, issues=[(30, "Bring daw to 1.3.0 in the catalog")])
    assert ran.code == 0, ran.stdout + ran.stderr
    assert creates(ran) == [["pr", "create", "chore(catalog): daw 1.3.0"]]
    assert "already open, #30" in ran.stdout


def test_a_re_run_with_the_pull_request_open_opens_nothing(tmp_path):
    ran = publish(tmp_path, issues=[(30, "Bring daw to 1.3.0 in the catalog")], prs=[(32, "chore(catalog): daw 1.3.0")])
    assert ran.code == 0, ran.stdout + ran.stderr
    assert creates(ran) == [] and "already open: #32" in ran.stdout


def test_a_failed_read_of_the_open_ones_stops_it(tmp_path):
    ran = publish(tmp_path, fail_list=True)
    assert ran.code != 0
    assert creates(ran) == []
