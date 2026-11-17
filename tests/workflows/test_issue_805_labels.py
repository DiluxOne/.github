"""labels.yml lists only the labels that stay (#805, part 5 of #618).

C1: the sync deletes every retired label from a repository (none of
labels.yml's, none a repository added for itself), and labels.yml's
`retired:` holds what parts 1 to 4 took out of it.
C2: a script or workflow that sets a label labels.yml does not list fails
scripts/sync-repos.py --test, naming the label and the file.
C3: a retired label still on an open issue or pull request is kept, and the
sync says which one carries it."""
import contextlib
import importlib.util
import io
import json
import urllib.parse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def sync_repos():
    spec = importlib.util.spec_from_file_location("sync_repos_805", ROOT / "scripts" / "sync-repos.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def catalog():
    return yaml.safe_load((ROOT / "labels.yml").read_text(encoding="utf-8"))


class Out:
    def __init__(self, stdout="", returncode=0):
        self.stdout, self.returncode, self.stderr = stdout, returncode, ""


def fake_gh(have, carried, calls):
    """A stand-in for gh: the repository's labels HAVE, and CARRIED, a label
    name to the open issues and pull requests that carry it."""
    def run(*args, **_):
        calls.append(args)
        if args[:2] == ("label", "list"):
            return Out(json.dumps([{"name": n} for n in have]))
        if args[:2] == ("label", "delete"):
            have.remove(args[2])
            return Out("")
        if args[0] == "api":
            path = next(a for a in args[1:] if a.startswith("repos/"))
            name = urllib.parse.unquote(path.split("labels=", 1)[1].split("&", 1)[0])
            return Out(json.dumps([[{"number": n} for n in carried.get(name, [])]]))
        raise AssertionError(f"unexpected gh {args}")
    return run


def retired_names(sr):
    """One name for each retired entry: a prefix entry gets a numbered one."""
    return [r["name"].replace("*", "3") for r in sr.read_labels()["retired"]]


def test_c1_labels_yml_keeps_the_labels_that_stay_and_lists_the_retired():
    data = catalog()
    assert isinstance(data, dict) and isinstance(data["labels"], list) and isinstance(data["retired"], list)
    stay = {l["name"] for l in data["labels"]}
    retired = {r["name"] for r in data["retired"]}
    assert all(r.get("now") for r in data["retired"]), "each retired label says where its state is now"
    removed = {"bug:unconfirmed", "layer:logic", "layer:browser", "layer:cli", "layer:api", "layer:workflow",
               "could-not-reproduce", "repro:no-way", "enhancement", "bug", "needs:maintainer", "needs-triage",
               "accepted-by:policy", "merged-by:policy", "autopilot:answered", "autopilot:catchup",
               "autopilot:core-wait", "autopilot:waiting", "autopilot:run-*", "autopilot:free-*",
               "autopilot:round-*", "autopilot:waiting-*"}
    assert removed <= retired, sorted(removed - retired)
    assert not stay & retired
    assert {"lane:platform", "lane:bugfix-reproduced", "accepted", "autopilot:continue", "repro:run", "type:feat"} <= stay


def test_c1_the_sync_deletes_every_retired_label_and_nothing_else():
    sr = sync_repos()
    stay = [l["name"] for l in sr.read_labels()["labels"]]
    gone = retired_names(sr)
    have = stay + gone + ["help wanted", "our-own"]
    calls = []
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        failed = sr.delete_retired_labels({"name": "r"}, False, run=fake_gh(have, {}, calls))
    deleted = [c[2] for c in calls if c[:2] == ("label", "delete")]
    assert failed == 0
    assert sorted(deleted) == sorted(gone)
    assert all("--yes" in c for c in calls if c[:2] == ("label", "delete"))
    assert sorted(have) == sorted(stay + ["help wanted", "our-own"])
    assert not any(c[:2] == ("label", "delete") for c in calls if c[2] in stay)


def test_c1_a_dry_run_deletes_nothing_and_says_what_it_would():
    sr = sync_repos()
    calls = []
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        sr.delete_retired_labels({"name": "r"}, True, run=fake_gh(["bug", "accepted"], {}, calls))
    assert not any(c[:2] == ("label", "delete") for c in calls)
    assert "would delete bug" in out.getvalue()


def test_c1_the_labels_sync_deletes_after_the_migrations(monkeypatch):
    sr = sync_repos()
    ran = []
    monkeypatch.setattr(sr, "repositories", lambda only, exclude: [{"name": "r"}])
    monkeypatch.setattr(sr, "listed", lambda name: {})
    monkeypatch.setattr(sr, "sync_labels", lambda *a, **k: ran.append("create"))
    monkeypatch.setattr(sr, "retire_labels", lambda *a, **k: ran.append("migrate") or 0)
    monkeypatch.setattr(sr, "delete_retired_labels", lambda *a, **k: ran.append("delete") or 0)
    with contextlib.redirect_stdout(io.StringIO()):
        assert sr.main(["labels", "--repo", "r"]) == 0
    assert ran == ["create", "migrate", "delete"]


def test_c1_the_drift_check_lists_a_retired_label_left():
    sr = sync_repos()
    lines = sr.retired_drift(["accepted", "bug", "autopilot:run-2"], sr.read_labels()["retired"])
    assert len(lines) == 2 and "`bug`" in lines[0] and "`autopilot:run-2`" in lines[1]


def tree(tmp_path, files):
    (tmp_path / "labels.yml").write_text(yaml.safe_dump({"labels": [{"name": "accepted", "color": "0E8A16"}], "retired": []}), encoding="utf-8")
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def test_c2_a_workflow_that_sets_an_unlisted_label_is_named_with_its_file(tmp_path):
    sr = sync_repos()
    root = tree(tmp_path, {".github/workflows/x.yml": "jobs:\n  a:\n    steps:\n      - run: |\n          gh issue edit 1 --add-label not-a-label\n          gh issue edit 1 --add-label accepted\n"})
    found = sr.label_misuse(str(root))
    assert len(found) == 1 and found[0].startswith(".github/workflows/x.yml:5:") and "not-a-label" in found[0]


def test_c2_every_way_to_set_a_label_is_seen_and_removing_or_listing_is_not(tmp_path):
    sr = sync_repos()
    root = tree(tmp_path, {
        "scripts/a.sh": 'gh label create "made:up" --force\ngh issue create --title t --label "x:one,accepted"\n'
                        'gh api repos/o/r/issues -f "labels[]=x:two"\ngh issue edit 1 --remove-label gone\n'
                        'gh issue list --label listed\ngh search issues --label searched\n'
                        'gh issue create --title t \\\n  --label x:three\n'
                        'if [ "${1:-}" = "--test" ]; then\n  gh issue edit 1 --add-label in-its-test\nfi\n',
        "scripts/b.py": 'X_LABEL = "x:four"\n\n\ndef main():\n    gh("issue", "edit", "1", "--add-label", X_LABEL)\n'
                        '    gh("issue", "list", "--label", "listed")\n    gh("issue", "edit", "1", "--remove-label", "gone")\n\n\n'
                        'def self_test():\n    gh("issue", "edit", "1", "--add-label", "in-its-test")\n',
        "workflow-templates/t.yml": "jobs:\n  a:\n    steps:\n      - run: gh pr edit 1 --add-label=x:five\n",
        "scripts/fixtures/f.sh": "gh issue edit 1 --add-label in-a-fixture\n",
    })
    found = sr.label_misuse(str(root))
    names = sorted(f.split("sets label ", 1)[1].split(",", 1)[0] for f in found)
    assert names == ["made:up", "x:five", "x:four", "x:one", "x:three", "x:two"], found


def test_c2_a_label_built_from_a_variable_the_check_does_not_know_fails(tmp_path):
    sr = sync_repos()
    root = tree(tmp_path, {"scripts/a.sh": 'gh issue edit 1 --add-label "$what"\n'})
    found = sr.label_misuse(str(root))
    assert len(found) == 1 and found[0].startswith("scripts/a.sh:1:") and "$what" in found[0]


def test_c2_this_repository_sets_only_labels_it_lists():
    assert sync_repos().label_misuse(str(ROOT)) == []


def test_c2_the_check_runs_in_the_scripts_test():
    text = (ROOT / "scripts" / "sync-repos.py").read_text(encoding="utf-8")
    test = text[text.index("def self_test("):]
    assert "label_misuse(CENTRAL)" in test


def test_c3_a_retired_label_on_an_open_issue_is_kept_and_the_issue_named():
    sr = sync_repos()
    have = ["accepted", "bug:unconfirmed", "needs-triage"]
    calls = []
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        failed = sr.delete_retired_labels({"name": "r"}, False, run=fake_gh(have, {"bug:unconfirmed": [7]}, calls))
    assert failed == 0
    assert ("label", "delete", "bug:unconfirmed", "--repo", "DiluxOne/r", "--yes") not in calls
    assert "bug:unconfirmed" in have and "needs-triage" not in have
    assert "label bug:unconfirmed kept: still on #7 (open)" in out.getvalue()
    asked = [c for c in calls if c[0] == "api" and "labels=bug%3Aunconfirmed" in " ".join(c)]
    assert asked and all("state=open" in " ".join(c) for c in asked)


def test_c3_an_open_pull_request_keeps_it_too_and_every_carrier_is_named():
    sr = sync_repos()
    have = ["merged-by:policy"]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        sr.delete_retired_labels({"name": "r"}, False, run=fake_gh(have, {"merged-by:policy": [12, 3]}, []))
    assert have == ["merged-by:policy"]
    assert "label merged-by:policy kept: still on #3, #12 (open)" in out.getvalue()


def test_c3_a_call_that_fails_keeps_the_label_and_is_counted():
    sr = sync_repos()
    have = ["bug", "enhancement"]
    calls = []
    base = fake_gh(have, {}, calls)

    def run(*args, **k):
        if args[:3] == ("label", "delete", "bug"):
            raise RuntimeError("gh label delete bug: HTTP 502")
        return base(*args, **k)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        failed = sr.delete_retired_labels({"name": "r"}, False, run=run)
    assert failed == 1 and have == ["bug"]
    assert "label bug kept: it could not be deleted" in out.getvalue()
