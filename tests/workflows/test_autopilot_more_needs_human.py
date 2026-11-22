"""#928 C2: after a cap end, a decider's `/autopilot more` takes
`needs-human` off for good, from the pull request and from the issue when it
carries it too, with the REST call `reaccepted` uses (a 404 means it is
already off), and reads the labels back before it adds `autopilot:continue`:
the continue run then finds nothing in its way. When the label could not
come off, the extension is undone and the reply says so, never "it continues
now". Runs `autopilot.py more` with gh stood in and the fixture boards
(RECEIPTS_FIXTURE)."""
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOT = "app/dilux-bot"
ISSUE_URL = "https://github.com/o/r/issues/7"
COMMENT_URL = ISSUE_URL + "#issuecomment-1"


def autopilot():
    spec = importlib.util.spec_from_file_location("autopilot_more_nh", ROOT / "scripts/autopilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def board(fx, number):
    path = fx / "comments" / str(number) / "board.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    m = re.search(r"<!-- dx-state v1 (.*?) -->", text, re.S)
    data = json.loads(m.group(1)) if m else {}
    data.pop("sha256", None)
    return data


class World:
    """Issue #7 of o/r and its autopilot draft #8, ended on its cap of 5
    runs with `needs-human` on both. `gh pr edit --remove-label` does
    nothing, as it did on GitHub; the REST DELETE takes the label off,
    unless `stuck`."""

    def __init__(self, tmp_path, monkeypatch, stuck=False, issue_label=True):
        self.fx = tmp_path / "fx"
        self.fx.mkdir()
        self.calls = []
        self.labels = {"7": {"accepted", "needs-human"} if issue_label else {"accepted"}, "8": {"autopilot", "needs-human"}}
        for k, v in (("RECEIPTS_FIXTURE", str(self.fx)), ("GITHUB_REPOSITORY", "o/r"), ("DX_BOT_APP", "dilux-bot"),
                     ("DX_BOT_LOGIN", "dilux-bot[bot]"), ("NUMBER", "7")):
            monkeypatch.setenv(k, v)
        for k in ("PR", "DX_IO", "REPO_AUTONOMY"):
            monkeypatch.delenv(k, raising=False)
        self.ap = ap = autopilot()
        ap.set_board("o/r", 8, "pr", runs=[{"n": n, "free": False} for n in range(1, 6)])

        def fake_gh(*args, input_text=None):
            a = [str(x) for x in args]
            self.calls.append(" ".join(a))
            names = lambda n: [{"name": l} for l in sorted(self.labels[n])]
            if a[:2] == ["issue", "view"]:
                return json.dumps({"url": ISSUE_URL, "comments": [], "labels": names("7"),
                                   "closedByPullRequestsReferences": [{"number": 8}]})
            if a[:2] == ["pr", "view"]:
                return json.dumps({"state": "OPEN", "labels": names("8"), "author": {"login": BOT}})
            if a[:3] == ["api", "-X", "DELETE"]:
                n = re.search(r"/issues/(\d+)/", a[3]).group(1)
                if "needs-human" not in self.labels[n]:
                    raise RuntimeError("gh: Label does not exist (HTTP 404)")
                if stuck:
                    raise RuntimeError("gh: Server Error (HTTP 502)")
                self.labels[n].discard("needs-human")
            if a[:2] == ["issue", "edit"] and "--add-label" in a:
                self.labels["7"].add(a[a.index("--add-label") + 1])
            if a[:2] == ["pr", "edit"] and "--add-label" in a:
                self.labels["8"].add(a[a.index("--add-label") + 1])
            return ""

        monkeypatch.setattr(ap, "gh", fake_gh)
        monkeypatch.setattr(ap, "refresh_board", lambda repo, number: None)
        self.tmp, self.monkeypatch = tmp_path, monkeypatch

    def more(self, body="/autopilot more"):
        (self.tmp / "comment.md").write_text(body, encoding="utf-8")
        for k, v in (("LOGIN", "boss"), ("ALLOWED", "0"), ("COMMENT", str(self.tmp / "comment.md")), ("COMMENT_URL", COMMENT_URL)):
            self.monkeypatch.setenv(k, v)
        try:
            return self.ap.main(["more"])
        except RuntimeError:
            return 1

    def replies(self):
        return [c for c in self.calls if c.startswith("issue comment 7")]


def test_c2_more_takes_needs_human_off_and_the_autopilot_runs_again(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    assert w.more() == 0
    assert "needs-human" not in w.labels["8"], w.calls
    assert "needs-human" not in w.labels["7"], w.calls
    # The continue goes on only once the label is off, read back.
    assert "autopilot:continue" in w.labels["7"]
    delete = max(i for i, c in enumerate(w.calls) if c.startswith("api -X DELETE repos/o/r/issues/8/labels/needs-human"))
    cont = next(i for i, c in enumerate(w.calls) if c.startswith("issue edit 7") and "autopilot:continue" in c)
    assert delete < cont
    # The continue run's own guard finds nothing in its way.
    ok, why = w.ap.may_continue(sorted(w.labels["8"]), "<!-- dx-checklist -->\n- [ ] **C1** x\n<!-- /dx-checklist -->", 5, 10)
    assert ok, why
    assert "It continues now" in w.replies()[-1]
    assert len(board(w.fx, 8)["extensions"]) == 1


def test_c2_a_label_already_off_is_no_failure(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, issue_label=False)
    assert w.more() == 0
    assert "needs-human" not in w.labels["8"] and "autopilot:continue" in w.labels["7"]


def test_c2_a_label_that_does_not_come_off_undoes_the_extension_and_says_so(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, stuck=True)
    w.more()
    assert "autopilot:continue" not in w.labels["7"], w.calls
    assert not board(w.fx, 8).get("extensions")
    said = w.replies()
    assert said and "It continues now" not in said[-1]
    assert "needs-human" in said[-1] and "could not come off" in said[-1]
