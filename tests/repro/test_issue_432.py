"""#432: the issues sync-repos.py opens outside the sync lane are not PRDs, so G1
takes a maintainer's `accepted` off. Written from the report as the
reproduction's writer would (#376).
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Out:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


@pytest.mark.parametrize("part", ["dependabot", "files"])
def test_every_issue_sync_repos_opens_passes_the_issue_schema_check(part, monkeypatch):
    sync = load("sync-repos")
    schema = load("issue-schema")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(sync, "ORG", "o")
    opened = []

    def fake(*args, check=True, input_text=None):
        joined = " ".join(args)
        if args[:2] in (("pr", "list"), ("issue", "list")):
            return Out("[]")
        if args[:2] == ("issue", "create"):
            opened.append(args[args.index("--body") + 1])
            return Out("https://github.com/o/r/issues/7\n")
        if args[:2] == ("pr", "create"):
            return Out("https://github.com/o/r/pull/8\n")
        if joined.startswith("api repos/o/r/contents/?ref=main"):
            return Out(json.dumps([{"name": "readme.txt"}]))
        if joined.startswith("api repos/o/r/contents/.github/dependabot.yml?ref=main"):
            return Out("version: 2\n")
        if joined.startswith("api repos/o/r/contents/AGENTS.md?ref=main"):
            return Out("# AGENTS.md\n")
        if joined.startswith("api repos/o/r/git/ref/heads/main"):
            return Out(json.dumps({"object": {"sha": "abc"}}))
        if joined.startswith("api -X"):
            return Out("{}")
        return Out("", 1, "HTTP 404")

    monkeypatch.setattr(sync, "gh", fake)
    monkeypatch.setattr(sync, "listed", lambda name: None)
    repo = {"name": "r", "defaultBranchRef": {"name": "main"}}
    sync.sync_files(repo, {"files": {}}, "<!-- dx:org:start -->\nrules\n<!-- dx:org:end -->\n", False, part=part)

    assert len(opened) == 1
    result = schema.check(opened[0])
    assert result["ok"], result["errors"]
