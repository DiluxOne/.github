"""Before and after screenshots (C4, #564): only when an autopilot pull
request from this same repository is marked ready; its code runs with no
secret, and only the job that never checks it out holds the key."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github/workflows"

ONLY = ("github.event.action == 'ready_for_review'", "contains(github.event.pull_request.labels.*.name, 'autopilot')",
        "github.event.pull_request.user.login == vars.DX_BOT_LOGIN", "github.event.pull_request.head.repo.full_name == github.repository")


def load(name):
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def test_the_pipelines_call_it_on_ready_for_review_of_an_autopilot_pull_request_from_the_same_repository():
    for name, uses in (("pull-request.yml", "./.github/workflows/pr-screenshots.yml"),
                       ("org-pull-request.yml", "DiluxOne/.github/.github/workflows/pr-screenshots.yml@v7")):
        job = load(name)["jobs"]["screenshots"]
        assert job["uses"] == uses, name
        for part in ONLY + ("github.event_name == 'pull_request'",):
            assert part in job["if"], (name, part)
        assert job["permissions"] == {"contents": "read"}
    on = load("pull-request.yml").get("on") or load("pull-request.yml").get(True)
    assert "ready_for_review" in on["pull_request"]["types"]


def test_the_code_runs_with_no_secret_and_the_key_never_meets_it():
    doc = load("pr-screenshots.yml")
    assert set(doc.get("on") or doc.get(True)) == {"workflow_call"}
    take, publish = doc["jobs"]["take"], doc["jobs"]["publish"]
    cond = " ".join(take["if"].split())
    for part in ONLY:
        assert part in cond
    assert "pull_request_target" not in (WF / "pr-screenshots.yml").read_text(encoding="utf-8")
    assert take["permissions"] == {"contents": "read"} and take["runs-on"] == "ubuntu-latest"
    text = yaml.safe_dump(take)
    assert "secrets." not in text and "create-github-app-token" not in text
    checkouts = [s for s in take["steps"] if "actions/checkout" in s.get("uses", "")]
    assert all(s["with"]["persist-credentials"] is False for s in checkouts)
    assert {s["with"].get("path") for s in checkouts} == {".dx-central", "before", "after"}
    runs = " ".join(s.get("run", "") for s in take["steps"])
    assert "screenshots.py plan" in runs and "screenshots.py take before" in runs and "screenshots.py take after" in runs
    # The key: only where nothing of the pull request is checked out.
    assert publish["needs"] == "take"
    assert not any(s.get("with", {}).get("ref") == "${{ github.event.pull_request.head.sha }}" for s in publish["steps"])
    token = next(s for s in publish["steps"] if s.get("id") == "bot")["with"]
    assert token["permission-contents"] == "write" and token["permission-pull-requests"] == "write"
    assert token["repositories"] == "${{ github.event.repository.name }}"
    assert any("screenshots.py publish" in s.get("run", "") for s in publish["steps"])
    # A failed run says so in the section.
    assert "needs.take.result != 'success'" in publish["if"]


def test_the_browser_way_of_the_pack_says_how_to_take_them():
    pack = yaml.safe_load((ROOT / "kinds/wordpress-plugin/pack.yml").read_text(encoding="utf-8"))
    assert "playwright.dx-shots.config.ts" in pack["repro"]["ways"]["browser"]["shots"]
    assert "{tests}" in pack["repro"]["ways"]["browser"]["shots"]


def test_the_template_has_the_sections_markers():
    tpl = (ROOT / "pull_request_template.md").read_text(encoding="utf-8")
    shots = tpl[tpl.index("## 📸 Screenshots"):tpl.index("## ✅ Checklist")]
    assert "<!-- dx-screenshots -->" in shots and "<!-- /dx-screenshots -->" in shots
