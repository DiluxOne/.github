"""#603: `sync-repos.py security` attaches the configuration for the repository's
visibility: the public one to a public repository (default for new repositories
set for public ones only), and nothing, billed or not, to a private one."""
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PUBLIC_CONFIG = {"id": 289758, "name": "DiluxOne public"}
CONFIGS = [PUBLIC_CONFIG, {"id": 1, "name": "GitHub recommended"}]
# repos.yml with no private configuration: only the public one is named.
CONF = {"security": {"configuration": {"public": "DiluxOne public"}, "public": "DiluxOne public"}}


class Out:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def load():
    spec = importlib.util.spec_from_file_location("sync_repos", ROOT / "scripts" / "sync-repos.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_security(monkeypatch, visibility):
    mod = load()
    calls = []

    def fake_gh(*args, check=True, input_text=None):
        joined = " ".join(args)
        calls.append(joined)
        if joined == "api orgs/o/code-security/configurations?per_page=100":
            return Out(json.dumps(CONFIGS))
        if joined == "api repos/o/r/code-security-configuration":
            return Out("", 1, "HTTP 404 Not Found")
        if joined == "api repos/o/r":
            return Out(json.dumps({"id": 99}))
        return Out("{}")

    monkeypatch.setattr(mod, "gh", fake_gh)
    monkeypatch.setattr(mod, "ORG", "o")
    monkeypatch.setattr(mod, "SECURITY_CONFIGS", {})
    out = io.StringIO()
    error = None
    with redirect_stdout(out):
        try:
            mod.sync_security({"name": "r", "visibility": visibility}, CONF, False)
        except Exception as exc:  # the adoption failing is the bug
            error = repr(exc)
    return calls, out.getvalue(), error


def test_a_private_repository_without_a_private_configuration_gets_nothing_attached(monkeypatch):
    calls, said, error = run_security(monkeypatch, "PRIVATE")
    writes = [c for c in calls if " -X " in c]
    assert error is None and writes == [] and said.strip(), (error, writes, said)


def test_a_public_repository_gets_the_public_configuration_and_it_is_the_default_for_public_ones_only(monkeypatch):
    calls, said, error = run_security(monkeypatch, "PUBLIC")
    attach = f"api -X POST orgs/o/code-security/configurations/{PUBLIC_CONFIG['id']}/attach --input -"
    default = f"api -X PUT orgs/o/code-security/configurations/{PUBLIC_CONFIG['id']}/defaults -f default_for_new_repos=public"
    assert error is None and attach in calls and default in calls, (error, calls)
