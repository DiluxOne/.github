"""#727: the test identity's pull requests must be trusted in the test repository only."""
import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_test_identity_is_a_trusted_author_in_the_test_repository_only(monkeypatch):
    monkeypatch.chdir(ROOT)
    policy = load("policy")
    org = load("org")
    login = org.test_pack()["identity"]["login"]
    assert login
    default = str(ROOT / "policy" / "review-policy.default.yml")

    _, in_test_repo = policy.run_case(default, "kind: engine-test\n", ["docs/a.md"], PR_AUTHOR=login)
    _, elsewhere = policy.run_case(default, "kind: wordpress-plugin\n", ["docs/a.md"], PR_AUTHOR=login)

    assert in_test_repo.get("trusted") == "true"
    assert elsewhere.get("trusted") == "false"
