"""A plugin's changelog and translations never conflict between pull requests
(#452): the readme job holds the fragments, the translations job holds the
form that merges, and every tree that runs or ships the plugin compiles its
.mo, which nobody commits."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github/workflows"


def steps(workflow, job):
    return yaml.safe_load((WF / workflow).read_text(encoding="utf-8"))["jobs"][job]["steps"]


def test_the_readme_job_holds_the_fragments_against_the_base():
    readme = steps("plugin-checks-wp.yml", "readme")
    checkout = readme[0]
    assert checkout["with"]["fetch-depth"] == 2
    step = next(s for s in readme if s.get("name") == "Changelog fragments")
    run = step["run"]
    assert "changelog-fragments.sh check ." in run
    assert "changelog-fragments.sh hand-edit" in run
    # Only the pull request that removes fragments (the release) writes them in.
    assert "grep -q '^D'" in run and run.index("grep -q '^D'") < run.index("hand-edit")


def test_the_translations_job_holds_the_form_that_merges():
    job = steps("plugin-checks-wp.yml", "translations")
    names = [s.get("name") for s in job]
    assert names.index("In the form that merges") < names.index("Every shipped locale complete")
    central = next(s for s in job if s.get("with", {}).get("repository") == "DiluxOne/.github")
    assert "scripts/plugin-i18n.sh" in central["with"]["sparse-checkout"]


def test_every_tree_that_ships_or_runs_the_plugin_compiles_its_mo():
    release = (WF / "plugin-release-wp.yml").read_text(encoding="utf-8")
    # The development build and the release zip.
    assert release.count("plugin-i18n.sh compile .") == 2
    zip_job = yaml.safe_load(release)["jobs"]
    release_steps = [s.get("name") for job in zip_job.values() for s in job.get("steps", [])]
    assert release_steps.index("The compiled translations") < release_steps.index("Only the plugin ships")
    tests = (WF / "plugin-tests-wp.yml").read_text(encoding="utf-8")
    # Both suites (integration and end to end), before the site starts.
    assert tests.count("- name: The compiled translations") == 2
    assert tests.count('msgfmt --check -o "${po%.po}.mo" "$po"') == 2
