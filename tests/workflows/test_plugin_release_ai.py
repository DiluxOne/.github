"""A plugin for coding agents' release reaches the catalog (#552, C5): the
release workflow makes the GitHub release with the release App's token, and
the publish workflow brings the catalog's entry up to it through a pull
request on diluxone-plugins-ai, with a token scoped to that repository."""
from pathlib import Path

import yaml

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
    assert "github.repository_owner == 'DiluxOne'" in job["if"] and "fork" in job["if"]
    app = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/create-github-app-token@")][0]
    assert app["with"]["repositories"] == "${{ inputs.catalog }}"
    assert triggers(wf)["workflow_call"]["inputs"]["catalog"]["default"] == "diluxone-plugins-ai"
    run = " ".join(str(s.get("run", "")) for s in job["steps"])
    assert 'agent-manifests.py bump "$VERSION" "$PLUGIN" . --ref "$TAG"' in run
    assert "gh pr create" in run and "gh issue create" in run and "api-commit.py push" in run
    assert "git push" not in run
    # Untrusted text (the tag) reaches the script through env only.
    assert "${{" not in run


def test_the_pack_releases_to_the_catalog():
    release = load("kinds/ai-agent-plugin/pack.yml")["release"]
    assert release["publishes-to"] == "diluxone-plugins-ai"
    assert release["workflow"] == "plugin-release-ai.yml" and release["publish"] == "plugin-publish-ai.yml"
    assert "stable" not in release and "{version}" in release["prepare"]


def test_the_publish_is_safe_to_re_run():
    # A re-run after a failed push or pull request reuses the issue the first
    # run opened, and a failed read of the open ones stops it (#552).
    import importlib.util
    spec = importlib.util.spec_from_file_location("agent_manifests", ROOT / "scripts" / "agent-manifests.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    run = " ".join(str(s.get("run", "")) for s in steps(load(".github/workflows/plugin-publish-ai.yml"), "bump"))
    plan, create = run.index("agent-manifests.py publish-plan"), run.index("gh issue create")
    assert run.index("gh issue list") < plan < create and run.index("gh pr list") < plan
    assert '[ "$action" = create ]' in run[:create] and "*)" in run[plan:create]
    assert "| grep" not in run[:create], "a failed read must not read as 'none open'"
    # The titles it opens are the ones the plan looks for.
    issue = mod.PUBLISH_ISSUE.format(name="$name", version="$VERSION")
    pr = mod.PUBLISH_PR.format(name="$name", version="$VERSION")
    assert f'--title "{issue}"' in run and f'--title "{pr}"' in run
    assert 'api-commit.py push "$branch" --onto "origin/$base" --force' in run
