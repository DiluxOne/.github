"""The tools a kind's `make pre-pr` needs (#682): the `work` and `verify`
jobs install what the runner lacks of its pack's `pre-pr-tools` before
`make pre-pr` runs, so a plugin's translations step finds msgcat."""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/autopilot.yml"


def steps(job):
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"][job]["steps"]


def index(job, pred):
    return next(i for i, s in enumerate(steps(job)) if pred(s))


def tools_step(job):
    return steps(job)[index(job, lambda s: s.get("id") == "tools")]


def test_work_and_verify_install_the_tools_before_make_pre_pr():
    for job, before in (("work", lambda s: s.get("id") == "work"), ("verify", lambda s: s.get("name") == "make pre-pr")):
        tools = index(job, lambda s: s.get("id") == "tools")
        central = index(job, lambda s: s.get("id") == "central")
        assert central < tools < index(job, before), job
        run = tools_step(job)["run"]
        assert "pre-pr.py tools ." in run and "apt-get install" in run
        # No secret, and the job keeps what it had.
        assert "secrets." not in yaml.safe_dump(tools_step(job))
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert wf["jobs"]["work"]["permissions"] == wf["jobs"]["verify"]["permissions"] == {"contents": "read"}
    # An install that fails gives no verdict, which apply reads as `lost`.
    result = steps("verify")[index("verify", lambda s: s.get("id") == "result")]
    assert result["if"] == "always() && steps.tools.outcome != 'failure'"


def test_the_wordpress_plugin_pack_lists_gettext():
    pack = yaml.safe_load((ROOT / "kinds/wordpress-plugin/pack.yml").read_text(encoding="utf-8"))
    assert {"command": "msgcat", "package": "gettext"} in pack["pre-pr-tools"]
    assert {"command": "msgfmt", "package": "gettext"} in pack["pre-pr-tools"]
    for kind in ("ai-agent-plugin", "engine-test"):
        assert yaml.safe_load((ROOT / f"kinds/{kind}/pack.yml").read_text(encoding="utf-8"))["pre-pr-tools"] == []


def a_plugin(tmp_path, kind="wordpress-plugin"):
    repo = tmp_path / "plugin"
    (repo / ".github").mkdir(parents=True)
    (repo / ".github/review-policy.yml").write_text(f"kind: {kind}\n")
    (repo / ".dx-central").symlink_to(ROOT)
    return repo


def fake_bin(tmp_path, names):
    """sudo and apt-get that record what they were asked, and an empty PATH
    beside them, so msgcat is not found."""
    bin_dir, log = tmp_path / "bin", tmp_path / "apt.log"
    bin_dir.mkdir()
    for name in names:
        script = bin_dir / name
        if name == "sudo":
            script.write_text(f"#!/bin/sh\necho sudo >> {log}\nexec \"$@\"\n")
        else:
            script.write_text(f"#!/bin/sh\necho \"{name} $*\" >> {log}\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
    for tool in ("python3", "bash", "env", "dirname", "basename"):
        if shutil.which(tool) and not (bin_dir / tool).exists():
            (bin_dir / tool).symlink_to(shutil.which(tool))
    return bin_dir, log


@pytest.mark.parametrize("with_sudo", [True, False])
def test_the_step_installs_the_missing_package_with_sudo_when_it_is_there(tmp_path, with_sudo):
    repo = a_plugin(tmp_path)
    bin_dir, log = fake_bin(tmp_path, ["apt-get"] + (["sudo"] if with_sudo else []))
    env = {"PATH": str(bin_dir), "HOME": str(tmp_path)}
    run = subprocess.run(["bash", "-c", tools_step("verify")["run"]], cwd=repo, env=env, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    lines = log.read_text().splitlines()
    installs = [l for l in lines if l.startswith("apt-get install")]
    assert len(installs) == 1 and installs[0].split()[-1] == "gettext"
    assert ("sudo" in lines) == with_sudo
    assert tools_step("work")["run"] == tools_step("verify")["run"]


def test_the_step_installs_nothing_when_the_tools_are_there_or_the_kind_needs_none(tmp_path):
    repo = a_plugin(tmp_path, kind="ai-agent-plugin")
    bin_dir, log = fake_bin(tmp_path, ["apt-get", "sudo"])
    run = subprocess.run(["bash", "-c", tools_step("work")["run"]], cwd=repo, env={"PATH": str(bin_dir)}, capture_output=True, text=True)
    assert run.returncode == 0 and not log.exists()


def test_an_install_that_fails_fails_the_step(tmp_path):
    repo = a_plugin(tmp_path)
    bin_dir, _ = fake_bin(tmp_path, ["sudo"])
    (bin_dir / "apt-get").write_text("#!/bin/sh\nexit 100\n")
    (bin_dir / "apt-get").chmod(0o755)
    run = subprocess.run(["bash", "-c", tools_step("verify")["run"]], cwd=repo, env={"PATH": str(bin_dir)}, capture_output=True, text=True)
    assert run.returncode != 0


@pytest.mark.skipif(not shutil.which("msgcat"), reason="gettext is not installed: the step installs it on the runner")
def test_with_the_tools_installed_the_translations_step_passes_on_catalogues_in_the_merging_form(tmp_path):
    repo = a_plugin(tmp_path)
    assert subprocess.run(["python3", str(ROOT / "scripts/pre-pr.py"), "tools", str(repo)], capture_output=True, text=True).stdout == ""
    (repo / "languages").mkdir()
    po = ('msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n"PO-Revision-Date: 2026-03-04 05:06+0000\\n"\n'
          '"X-Generator: Poedit 3.4\\n"\n\n#: plugin.php:12\nmsgid "Save"\nmsgstr "Guardar"\n\n#: plugin.php:3\nmsgid "Add"\nmsgstr "Añadir"\n')
    raw = repo / "languages/plugin-es_ES.po"
    raw.write_text(po, encoding="utf-8")
    script = str(ROOT / "scripts/plugin-i18n.sh")
    # In the form that merges, as the autopilot writes them.
    formed = subprocess.run(["bash", script, "form"], input=po, capture_output=True, text=True, check=True).stdout
    raw.write_text(formed, encoding="utf-8")
    check = subprocess.run(["bash", script, "check", str(repo)], capture_output=True, text=True)
    assert check.returncode == 0, check.stdout + check.stderr
    assert "in the form that merges (1 file(s))" in check.stdout
    assert "command not found" not in check.stderr
