"""#856: `/autopilot more` on an issue gives its autopilot pull request, at its
cap, more runs, on the word of someone `who-decides` allows, at most twice.
issue-claim.yml's `more` job reads it (the workflow that reads `/claim`),
asks scripts/deciders.py, and runs `autopilot.py more`, whose decisions are
`more_plan` and `runs_cap`; the hint reaches the next run through
`answers()`. Run here with gh stood in and the fixture boards
(RECEIPTS_FIXTURE)."""
import importlib.util
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BOT = "app/dilux-bot"
ISSUE_URL = "https://github.com/o/r/issues/7"
COMMENT_URL = ISSUE_URL + "#issuecomment-1"


def autopilot():
    spec = importlib.util.spec_from_file_location("autopilot_more", ROOT / "scripts/autopilot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def wf(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def board(fx, number):
    path = fx / "comments" / str(number) / "board.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    m = re.search(r"<!-- dx-state v1 (.*?) -->", text, re.S)
    data = json.loads(m.group(1)) if m else {}
    data.pop("sha256", None)
    return data


class World:
    """Issue #7 of o/r and its autopilot draft #8, at its cap of 5 runs, with
    `needs-human` on it: gh stood in, logging what is written."""

    def __init__(self, tmp_path, monkeypatch, runs=5, extensions=(), comments=()):
        self.fx = tmp_path / "fx"
        self.fx.mkdir()
        self.calls = []
        self.comments = list(comments)
        monkeypatch.setenv("RECEIPTS_FIXTURE", str(self.fx))
        monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
        monkeypatch.setenv("DX_BOT_APP", "dilux-bot")
        monkeypatch.setenv("DX_BOT_LOGIN", "dilux-bot[bot]")
        monkeypatch.setenv("NUMBER", "7")
        monkeypatch.delenv("PR", raising=False)
        monkeypatch.delenv("DX_IO", raising=False)
        monkeypatch.delenv("REPO_AUTONOMY", raising=False)
        self.ap = ap = autopilot()
        state = {"runs": [{"n": n, "free": False} for n in range(1, runs + 1)]}
        if extensions:
            state["extensions"] = list(extensions)
        ap.set_board("o/r", 8, "pr", **state)

        def fake_gh(*args, input_text=None):
            line = " ".join(str(a) for a in args)
            self.calls.append(line)
            if args[:2] == ("issue", "view"):
                return json.dumps({"url": ISSUE_URL, "comments": self.comments, "closedByPullRequestsReferences": [{"number": 8}]})
            if args[:2] == ("pr", "view"):
                return json.dumps({"state": "OPEN", "labels": [{"name": "autopilot"}, {"name": "needs-human"}], "author": {"login": BOT}})
            return ""

        monkeypatch.setattr(ap, "gh", fake_gh)
        monkeypatch.setattr(ap, "refresh_board", lambda repo, number: None)
        self.tmp = tmp_path
        self.monkeypatch = monkeypatch

    def more(self, login, allowed, body="/autopilot more"):
        (self.tmp / "comment.md").write_text(body, encoding="utf-8")
        self.monkeypatch.setenv("LOGIN", login)
        self.monkeypatch.setenv("ALLOWED", allowed)
        self.monkeypatch.setenv("COMMENT", str(self.tmp / "comment.md"))
        self.monkeypatch.setenv("COMMENT_URL", COMMENT_URL)
        return self.ap.main(["more"])

    def replies(self):
        return [c for c in self.calls if c.startswith("issue comment 7")]


# --- C2: a decider's `/autopilot more` --------------------------------------

def test_c2_the_cap_reads_the_pull_requests_extensions():
    ap = autopilot()
    runs_cap = getattr(ap, "runs_cap", None)
    assert callable(runs_cap), "autopilot.py has no runs_cap"
    one = {"by": "boss", "at": "2026-11-19T10:00:00Z", "comment": COMMENT_URL}
    assert runs_cap(5, {}) == 5
    assert runs_cap(5, {"extensions": [one]}) == 10
    assert runs_cap(5, {"extensions": [one, one]}) == 15
    # Each extension adds the policy's own number (the Spec's choice a).
    assert runs_cap(3, {"extensions": [one]}) == 6
    # Never past two, whatever a board says.
    assert runs_cap(5, {"extensions": [one, one, one]}) == 15


def test_c2_the_planner_extends_a_pull_request_at_its_cap():
    ap = autopilot()
    more_plan = getattr(ap, "more_plan", None)
    assert callable(more_plan), "autopilot.py has no more_plan"
    plan = more_plan(True, {"runs": [{"n": n, "free": False} for n in range(1, 6)]}, True, 5, True, False)
    assert plan["go"] is True and plan["cap"] == 10


def test_c2_a_decider_extends_it_and_the_next_run_starts(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    assert w.more("boss", "0", "/autopilot more\nTry the other fixture first.") == 0
    st = board(w.fx, 8)
    assert st["extensions"] == [{"by": "boss", "at": st["extensions"][0]["at"], "comment": COMMENT_URL}]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", st["extensions"][0]["at"])
    # The runs on its board are as they were; its cap is now 10.
    assert w.ap.run_numbers(st)[1] == 5 and w.ap.runs_cap(5, st) == 10
    body = "<!-- dx-checklist -->\n- [ ] **C1** x\n<!-- /dx-checklist -->\n"
    assert w.ap.may_continue(["autopilot"], body, w.ap.run_numbers(st)[1], w.ap.runs_cap(5, st))[0] is True
    # needs-human off the pull request, the bot's continue on the issue, and
    # no `answered`: the run counts against the new cap.
    assert any(c.startswith("pr edit 8") and "--remove-label needs-human" in c for c in w.calls)
    assert any(c.startswith("issue edit 7") and "--add-label autopilot:continue" in c for c in w.calls)
    assert "answered" not in board(w.fx, 7)
    assert len(w.replies()) == 1 and "10" in w.replies()[0]


def test_c2_the_rest_of_the_comment_is_the_next_runs_hint():
    ap = autopilot()
    cap = {"body": ap.cap_comment("the autopilot already ran 5 times on it (the cap is 5)"), "createdAt": "2026-11-19T09:00:00Z", "author": {"login": BOT}}
    before = {"body": "an old hint, before the cap", "createdAt": "2026-11-19T08:00:00Z", "author": {"login": "boss"}}
    more = {"body": "/autopilot more\nTry the other fixture first.", "createdAt": "2026-11-19T10:00:00Z", "author": {"login": "boss"}}
    said = ap.answers([before, cap, more], {"boss"})
    assert said == "boss: Try the other fixture first."
    # On the same line too; with no rest, nothing.
    assert ap.answers([cap, dict(more, body="/autopilot more use the fixture")], {"boss"}) == "boss: use the fixture"
    assert ap.answers([cap, dict(more, body="/autopilot more")], {"boss"}) == ""
    # Someone who does not decide gives no hint.
    assert ap.answers([cap, dict(more, author={"login": "fork-dev"})], {"boss"}) == ""


def test_c2_the_more_job_reads_it_on_an_issue():
    jobs = wf("issue-claim.yml")["jobs"]
    assert "more" in jobs, "issue-claim.yml has no `more` job"
    more = jobs["more"]
    cond = more["if"]
    assert "github.event_name == 'issue_comment'" in cond and "!github.event.issue.pull_request" in cond
    assert "startsWith(github.event.comment.body, '/autopilot more')" in cond
    assert "github.event.comment.user.type != 'Bot'" in cond
    # "still on it" inside a hint never extends a claim.
    assert "!startsWith(github.event.comment.body, '/autopilot more')" in jobs["claim"]["if"]
    assert more["permissions"] == {} and more["runs-on"].startswith("ubuntu-latest")
    token = next(s for s in more["steps"] if s.get("id") == "bot")["with"]
    assert token["permission-issues"] == "write" and token["permission-pull-requests"] == "write" and token["permission-contents"] == "read"
    assert not any(k.startswith("permission-") and k not in ("permission-issues", "permission-pull-requests", "permission-contents") for k in token)
    run = next(s for s in more["steps"] if s.get("id") == "more")["run"]
    assert 'deciders.py may continue "$LOGIN"' in run and "autopilot.py more" in run
    # Untrusted text from the event's file, never an expression in the script.
    assert "${{" not in run


# --- C3: someone `who-decides` does not allow -------------------------------

def test_c3_the_planner_gives_no_run_and_answers_once():
    ap = autopilot()
    st = {"runs": [{"n": n, "free": False} for n in range(1, 6)]}
    assert ap.more_plan(False, st, True, 5, True, False) == {"go": False, "reply": "refused", "cap": None}
    assert ap.more_plan(False, st, True, 5, True, True) == {"go": False, "reply": "", "cap": None}


def test_c3_a_contributor_gets_one_reply_and_the_board_is_unchanged(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    before = board(w.fx, 8)
    assert w.more("fork-dev", "1", "/autopilot more\nplease, just one more") == 0
    assert board(w.fx, 8) == before and "extensions" not in board(w.fx, 8)
    # No run: no label moved, nothing on the pull request.
    assert not any("--add-label" in c or "--remove-label" in c for c in w.calls)
    assert not any(c.startswith(("pr edit", "pr comment")) for c in w.calls)
    [reply] = w.replies()
    assert "<!-- dx-autopilot-more-refused -->" in reply
    assert "A maintainer decides" in reply and ISSUE_URL in reply
    assert reply.rstrip().endswith("🤖 AI-generated · Claude Opus 5.5 (Anthropic)")


def test_c3_a_repeat_gets_no_second_reply(tmp_path, monkeypatch):
    ap = autopilot()
    said = {"body": ap.more_reply("refused", ISSUE_URL), "createdAt": "2026-11-19T10:00:00Z", "author": {"login": BOT}}
    w = World(tmp_path, monkeypatch, comments=[said])
    before = board(w.fx, 8)
    assert w.more("fork-dev", "1") == 0
    assert w.replies() == [] and board(w.fx, 8) == before
    assert not any("--add-label" in c or "--remove-label" in c for c in w.calls)


def test_c3_who_decides_unread_is_never_a_yes(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    before = board(w.fx, 8)
    assert w.more("boss", "2") == 0
    assert board(w.fx, 8) == before
    assert not any("--add-label" in c or "--remove-label" in c for c in w.calls)
    [reply] = w.replies()
    assert "dx-autopilot-more-refused" not in reply


# --- C4: two extensions already ---------------------------------------------

TWO = [{"by": "boss", "at": "2026-11-19T10:00:00Z", "comment": COMMENT_URL}, {"by": "boss", "at": "2026-11-20T10:00:00Z", "comment": COMMENT_URL}]


def test_c4_the_planner_refuses_a_third():
    ap = autopilot()
    st = {"runs": [{"n": n, "free": False} for n in range(1, 16)], "extensions": TWO}
    plan = ap.more_plan(True, st, True, 5, True, False)
    assert plan["go"] is False and plan["reply"] == "spent" and plan["cap"] == 15


def test_c4_a_third_is_refused_naming_claim_and_closing(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, runs=15, extensions=TWO)
    before = board(w.fx, 8)
    assert w.more("boss", "0", "/autopilot more\none more, please") == 0
    assert board(w.fx, 8) == before and len(board(w.fx, 8)["extensions"]) == 2
    assert not any("--add-label" in c or "--remove-label" in c for c in w.calls)
    [reply] = w.replies()
    assert "`/claim`" in reply and "closes the pull request" in reply


def test_c4_a_pull_request_below_its_cap_or_with_a_board_edited_by_hand_gets_none(tmp_path, monkeypatch):
    ap = autopilot()
    assert ap.more_plan(True, {"runs": [{"n": 1, "free": False}]}, True, 5, False, False)["reply"] == "below"
    assert ap.more_plan(True, {}, False, 5, True, False)["reply"] == "hand"
    w = World(tmp_path, monkeypatch, runs=3)
    assert w.more("boss", "0") == 0
    assert "extensions" not in board(w.fx, 8)
    assert not any("--add-label" in c or "--remove-label" in c for c in w.calls)
    [reply] = w.replies()
    assert "not at its cap" in reply
