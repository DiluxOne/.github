"""#929: the release lane replays only what did not pass on the same
candidate (C1), a re-run of its failed jobs can release (C2), and the test
repository's callers go back to the ref the lane found them at (C3).

Each test runs a step of release-lane.yml (steps.run) in a copy of this
checkout, with `gh` stubbed by a small fake (FAKE_GH, its answers in a JSON
file) and, where the step's decision is what is asserted, `release-lane.py
act` read as `decide`."""
import json
import sys
from pathlib import Path

import yaml

from steps import evaluate, run, step

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import org  # noqa: E402

LANE = "release-lane.yml"
RUN_URL = "https://github.com/o/r/actions/runs/100"
EARLIER = "https://github.com/o/r/actions/runs/7"
IDS = [s["id"] for s in yaml.safe_load((ROOT / "tests/release/scenarios.yml").read_text(encoding="utf-8"))["scenarios"]]


def jobs():
    return yaml.safe_load((ROOT / ".github/workflows" / LANE).read_text(encoding="utf-8"))["jobs"]


# `release-lane.py act` read as `decide`, which writes nothing to GitHub.
DECIDE = """import json, os, runpy, sys
real = {real!r}
with open(os.environ["DX_CALLS"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(["release-lane.py", *sys.argv[1:]]) + "\\n")
sys.argv = [real] + ["decide" if a == "act" else a for a in sys.argv[1:]]
runpy.run_path(real, run_name="__main__")
"""

# A script that records its call and does what FAKE_SCRIPT_DO says: write
# the rows it holds to --out and exit with its code.
RECORD = """import json, os, sys
with open(os.environ["DX_CALLS"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps([{name!r}, *sys.argv[1:]]) + "\\n")
do = json.loads(os.environ.get("FAKE_SCRIPT_DO") or "{{}}").get(sys.argv[1] if len(sys.argv) > 1 else "", {{}})
if "--out" in sys.argv and "rows" in do:
    out = sys.argv[sys.argv.index("--out") + 1]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w").write("<!-- dx-scenarios " + json.dumps(do["rows"]) + " -->\\n")
sys.exit(do.get("code", 0))
"""

# A `gh` that answers from FAKE_GH_STATE: `runs` (the lane's earlier runs),
# `artifacts` ({run id: {file: text}}, what `gh run download` writes),
# `files` ({ref: {name: text}}, the test repository's callers at a ref, ""
# its default branch), `commits` (a caller's history), and records the
# commits it is asked to make, the pull requests opened and their branches.
FAKE_GH = r'''import base64, json, os, re, sys
path = os.environ["FAKE_GH_STATE"]
st = json.load(open(path))
a = sys.argv[1:]
stdin = sys.stdin.read() if "--input" in a or "--body-file" in a else ""
def out(v):
    print(v if isinstance(v, str) else json.dumps(v))
def save():
    json.dump(st, open(path, "w"))
last = a[-1] if a else ""
if a[:1] == ["run"] and a[1:2] == ["download"]:
    got = st["artifacts"].get(a[2])
    if got is None:
        sys.stderr.write("no valid artifacts found to download\n"); sys.exit(1)
    d = a[a.index("--dir") + 1]
    os.makedirs(d, exist_ok=True)
    for name, text in got.items():
        open(os.path.join(d, name), "w").write(text)
    sys.exit(0)
if a[:1] == ["api"] and "/actions/workflows/release-lane.yml/runs" in " ".join(a):
    out({"workflow_runs": st["runs"]}); sys.exit(0)
if a[:1] == ["api"] and a[-2:] == ["--jq", ".default_branch"]:
    out("main"); sys.exit(0)
if a[:1] == ["api"] and a[-2:] == ["--jq", ".object.sha"]:
    out("h1"); sys.exit(0)
if a[:1] == ["api"] and "/rules/branches/" in last:
    out([[]]); sys.exit(0)
if a[:1] == ["api"] and re.search(r"/commits\?", last):
    out(st.get("commits", [])); sys.exit(0)
m = re.search(r"/contents/\.github/workflows(?:/([^?]+))?(?:\?ref=(.*))?$", last)
if a[:1] == ["api"] and m:
    files = st["files"].get(m.group(2) or "", {})
    if not m.group(1):
        out([{"name": n} for n in files]); sys.exit(0)
    if m.group(1) not in files:
        sys.stderr.write("HTTP 404\n"); sys.exit(1)
    out({"content": base64.b64encode(files[m.group(1)].encode()).decode()}); sys.exit(0)
if a[:2] == ["api", "graphql"]:
    q = json.loads(stdin)["variables"]["input"]
    branch = q["branch"]["branchName"]
    for f in q["fileChanges"]["additions"]:
        st["files"].setdefault(branch, {})[f["path"].rsplit("/", 1)[1]] = base64.b64decode(f["contents"]).decode()
    st.setdefault("commits_made", []).append(branch); save(); out("{}"); sys.exit(0)
if a[:3] == ["api", "-X", "DELETE"]:
    sys.exit(0)
if a[:2] == ["api", "repos/" + os.environ.get("FAKE_REPO", "") + "/git/refs"]:
    branch = a[a.index("-f") + 1].split("refs/heads/", 1)[1]
    st["files"][branch] = dict(st["files"][""]); save(); out("{}"); sys.exit(0)
if a[:2] == ["pr", "list"]:
    out([]); sys.exit(0)
if a[:2] == ["pr", "create"]:
    st.setdefault("pulls", []).append(a[a.index("--head") + 1]); save()
    out("https://github.com/o/t/pull/20"); sys.exit(0)
m = re.fullmatch(r"repos/[^/]+/[^/]+/pulls/(\d+)(/files)?", last)
if a[:1] == ["api"] and m:
    branch = st["pulls"][-1]
    if not m.group(2):
        out({"head": {"sha": branch}, "base": {"sha": ""}}); sys.exit(0)
    base, head = st["files"][""], st["files"][branch]
    out([[{"filename": ".github/workflows/" + k, "status": "modified"} for k in sorted(head) if base.get(k) != head.get(k)]]); sys.exit(0)
if a[:2] == ["pr", "view"]:
    # The merge queue merged it: the branch's callers reach main.
    st["files"][""] = dict(st["files"][st["pulls"][-1]]); st["merged"] = st.get("merged", 0) + 1; save()
    out({"mergedAt": "2026-11-22T10:00:00Z", "state": "MERGED"}); sys.exit(0)
out("[]")
'''


def checkout(tmp_path, fakes=()):
    """A copy of this checkout under tmp_path/work: every top entry linked,
    scripts/ linked one by one, but `fakes` ({name: text}) written."""
    work = tmp_path / "work"
    scripts = work / "scripts"
    scripts.mkdir(parents=True)
    for top in ROOT.iterdir():
        if top.name not in ("scripts", ".git", ".dx-central", ".dx-io"):
            (work / top.name).symlink_to(top)
    for real in (ROOT / "scripts").iterdir():
        if real.name not in dict(fakes):
            (scripts / real.name).symlink_to(real)
    for name, text in dict(fakes).items():
        (scripts / name).write_text(text, encoding="utf-8")
    return work


def fake_gh(tmp_path, state):
    """The stub body of `gh`, and the env it reads its state from."""
    (tmp_path / "fake_gh.py").write_text(FAKE_GH, encoding="utf-8")
    (tmp_path / "gh_state.json").write_text(json.dumps(state), encoding="utf-8")
    return f'python3 "{tmp_path}/fake_gh.py" "$@"', {"FAKE_GH_STATE": str(tmp_path / "gh_state.json"), "FAKE_REPO": "o/t"}


def gh_state(tmp_path):
    return json.loads((tmp_path / "gh_state.json").read_text())


def rows_text(rows):
    return f"| table |\n\n<!-- dx-scenarios {json.dumps(rows)} -->\n"


def rows_of(path):
    """The rows a results file records (its `dx-scenarios` mark)."""
    import re
    return json.loads(re.search(r"<!-- dx-scenarios (.*) -->", Path(path).read_text()).group(1))


def lay(tmp_path, written):
    """The artifacts the act job downloads: {artifact name: rows}."""
    for name, rows in written.items():
        d = tmp_path / "temp" / "scenarios" / name
        d.mkdir(parents=True)
        (d / "results.md").write_text(rows_text(rows), encoding="utf-8")


def ok(*ids, run=""):
    return [{"id": i, "ok": True, "why": [], "run": run} for i in ids]


def run_act(tmp_path, groups, written, jobs_=None, passed=()):
    """The act step, its `act` read as `decide`: its decision, and the
    merged table it decided on."""
    checkout(tmp_path, {"release-lane.py": DECIDE.format(real=str(ROOT / "scripts" / "release-lane.py"))})
    lay(tmp_path, written)
    plan = {"release": True, "version": "7.30.0", "major": "v7", "sha": "S"}
    env = dict(PLAN=json.dumps(plan), SCENARIO_GROUPS=json.dumps(groups), PASSED=json.dumps(list(passed)), SHA="S", NEXT="N", RUN_URL=RUN_URL,
               **(jobs_ or {"MOVE": "success", "PLAY": "success", "BACK": "success"}))
    ran = run(step(LANE, "act", job="act"), tmp_path, env=env, stubs={"git": ""})
    assert ran.code == 0, ran.stderr
    text = (tmp_path / "temp" / "results.md").read_text()
    return json.loads(ran.stdout), rows_of(tmp_path / "temp" / "results.md"), text


# C1: a lane on a candidate already tried plays only what did not pass there.

def earlier_run(tmp_path, key, failed):
    """A `gh` whose one earlier lane run left `scenarios-results` with KEY,
    where every scenario passed but FAILED."""
    rows = ok("callers-check") + [{"id": i, "ok": i != failed, "why": [] if i != failed else ["no label"], "run": f"https://github.com/o/t/actions/runs/{n}"}
                                  for n, i in enumerate(IDS)]
    lane = {"event": "workflow_run", "head_branch": "main", "head_repository": {"full_name": "o/r"}}
    return fake_gh(tmp_path, {"runs": [dict(lane, id=100, html_url=RUN_URL), dict(lane, id=7, html_url=EARLIER)],
                              "artifacts": {"7": {"key.json": json.dumps(key), "results.md": rows_text(rows)}}, "files": {}})


def run_groups(tmp_path, key):
    checkout(tmp_path)
    body, env = earlier_run(tmp_path, key, IDS[-1])
    ran = run(step(LANE, "groups", job="move"), tmp_path, env=dict(env, SHA="S", NEXT="N", GH_TOKEN="t"), stubs={"gh": body})
    assert ran.code == 0, ran.stderr
    assert "groups" in ran.output and "passed" in ran.output, ran.output
    return ran


def test_c1_the_same_candidate_plays_only_the_scenario_that_did_not_pass(tmp_path):
    ran = run_groups(tmp_path, {"sha": "S", "next": "N"})
    assert json.loads(ran.output["groups"]) == [{"id": IDS[-1], "scenarios": [IDS[-1]]}]
    passed = json.loads(ran.output["passed"])
    assert sorted(p["id"] for p in passed) == sorted(IDS[:-1])
    assert {p["in"] for p in passed} == {EARLIER}
    # It reads the lane's runs and the earlier run's results, never this run's.
    downloads = [c for c in ran.of("gh") if c[:2] == ["run", "download"]]
    assert downloads and all(c[2] == "7" and "scenarios-results" in c for c in downloads)


FAILING_GROUPS = """import sys
if sys.argv[1] == "passed":
    open(sys.argv[sys.argv.index("--out") + 1], "w").write("[]")
    sys.exit(0)
sys.exit(1)
"""


def test_c1_a_groups_command_that_fails_fails_the_step(tmp_path):
    checkout(tmp_path, {"release-scenarios.py": FAILING_GROUPS})
    ran = run(step(LANE, "groups", job="move"), tmp_path, env=dict(SHA="S", NEXT="N", GH_TOKEN="t"))
    assert ran.code != 0
    assert "groups" not in ran.output


def test_c1_a_new_candidate_plays_every_scenario(tmp_path):
    for n, key in enumerate(({"sha": "S", "next": "OTHER"}, {"sha": "OLD", "next": "N"})):
        ran = run_groups(tmp_path / str(n), key)
        assert [g["id"] for g in json.loads(ran.output["groups"])] == IDS
        assert json.loads(ran.output["passed"]) == []


def test_c1_the_scenario_that_passes_now_releases_the_candidate(tmp_path):
    b = IDS[-1]
    passed = [{"id": i, "in": EARLIER} for i in IDS[:-1]]
    d, rows, text = run_act(tmp_path, [{"id": b, "scenarios": [b]}],
                            {"scenarios-move": [], f"scenarios-{b}": ok(b), "scenarios-back": []}, passed=passed)
    assert d["do"] == "release"
    assert sorted(r["id"] for r in rows) == sorted(IDS) and all(r["ok"] for r in rows)
    assert f"pass (in {EARLIER})" in text
    # Its table, with the key, is what the next lane on this candidate reads.
    key = tmp_path / "temp" / "lane" / "key.json"
    assert json.loads(key.read_text()) == {"sha": "S", "next": "N"}
    assert (tmp_path / "temp" / "lane" / "results.md").read_text() == text


def test_c1_nothing_left_to_play_moves_no_caller_and_still_releases(tmp_path):
    passed = [{"id": i, "in": EARLIER} for i in IDS]
    d, rows, _ = run_act(tmp_path, [], {"scenarios-move": [], "scenarios-back": []},
                         {"MOVE": "success", "PLAY": "skipped", "BACK": "success"}, passed=passed)
    assert d["do"] == "release" and all(r["ok"] for r in rows)
    play = jobs()["play"]
    assert "needs.move.outputs.groups != '[]'" in play["if"]


def test_c1_the_candidate_keeps_a_v7_next_already_built_on_the_same_commit():
    import importlib.util
    spec = importlib.util.spec_from_file_location("release_lane_929", ROOT / "scripts" / "release-lane.py")
    lane = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lane)
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        (Path(root) / ".github" / "workflows").mkdir(parents=True)
        caller = Path(root) / ".github" / "workflows" / "a.yml"
        main = "on:\n  workflow_call:\njobs:\n  x:\n    uses: O/.github/.github/workflows/b.yml@v7\n"
        caller.write_text(main)
        answers = {"write-tree": "T\n", "refs/tags/v7-next^{commit}": "K\n", "K^{tree}": "T\n", "K^": "M\n", "rev-parse HEAD": "M\n"}
        calls = []

        def fake(*argv, input=None):
            calls.append(argv)
            line = " ".join(argv)
            return next((v for k, v in answers.items() if line.endswith(k)), "")
        assert lane.candidate("O/.github", "v7", root=root, run=fake) == "K"
        assert not [c for c in calls if "push" in c or any(str(x).endswith("api-commit.py") for x in c)]
        # Another tree: a new commit, and v7-next moved to it.
        answers["K^{tree}"] = "OTHER\n"
        caller.write_text(main)
        calls.clear()
        lane.candidate("O/.github", "v7", root=root, run=fake)
        assert ("git", "-C", root, "push", "-f", "origin", "refs/tags/v7-next") in calls


# C2: a re-run of the lane's failed jobs replays the failed group and releases.

def run_play_step(tmp_path, rows, code):
    checkout(tmp_path, {"release-scenarios.py": RECORD.format(name="release-scenarios.py")})
    do = {"play": {"rows": rows, "code": code}}
    return run(step(LANE, "play", job="play"), tmp_path, env={"FAKE_SCRIPT_DO": json.dumps(do), "GROUP": "b", "OWNER": "o", "TEST_REPO": "t"})


def test_c2_a_play_step_whose_scenario_fails_exits_1(tmp_path):
    ran = run_play_step(tmp_path / "fail", [{"id": "b", "ok": False, "why": ["no label"], "run": ""}], 1)
    assert ran.code == 1
    assert [c[0] for c in ran.of("release-scenarios.py")] == ["play"]
    ran = run_play_step(tmp_path / "pass", ok("b"), 0)
    assert ran.code == 0
    # Its results are uploaded all the same, before the job ends red.
    upload = next(s for s in jobs()["play"]["steps"] if "upload-artifact" in s.get("uses", ""))
    assert upload["if"] == "${{ !cancelled() }}"


def test_c2_the_latest_attempt_of_a_group_is_what_the_decision_reads(tmp_path):
    gs = [{"id": "a", "scenarios": ["a"]}, {"id": "b", "scenarios": ["b"]}]
    failed = [{"id": "b", "ok": False, "why": ["no label"], "run": "", "class": "engine"}]
    written = {"scenarios-move-a1": [], "scenarios-a-a1": ok("a"), "scenarios-b-a1": failed, "scenarios-b-a2": ok("b"),
               "scenarios-back-a1": [], "scenarios-back-a2": []}
    d, rows, _ = run_act(tmp_path / "rerun", gs, written)
    assert d["do"] == "release"
    assert sorted(r["id"] for r in rows) == ["a", "b"] and all(r["ok"] for r in rows)
    # The first attempt alone: its failure is the decision.
    d, _, _ = run_act(tmp_path / "first", gs, {k: v for k, v in written.items() if not k.endswith("-a2")}, {"MOVE": "success", "PLAY": "failure", "BACK": "success"})
    assert d["do"] == "bug" and d["scenario"] == "b" and [f["scenario"] for f in d["filings"]] == ["b"]


def test_c2_the_artifacts_carry_the_attempt():
    names = {job: [s["with"]["name"] for s in jobs()[job]["steps"] if "upload-artifact" in s.get("uses", "")] for job in ("move", "play", "back")}
    assert names == {"move": ["scenarios-move-a${{ github.run_attempt }}"], "play": ["scenarios-${{ matrix.group.id }}-a${{ github.run_attempt }}"],
                     "back": ["scenarios-back-a${{ github.run_attempt }}"]}


def test_c2_a_re_run_play_job_moves_the_callers_to_v7_next_before_it_plays(tmp_path):
    play = jobs()["play"]["steps"]
    ids = [s.get("id") for s in play]
    assert {"callers", "rerun", "play"} <= set(ids), ids
    assert ids.index("callers") < ids.index("rerun") < ids.index("play")
    token, rerun = play[ids.index("callers")], play[ids.index("rerun")]
    for s in (token, rerun):
        assert evaluate(s["if"], {"github.run_attempt": "2"}) is True
        assert evaluate(s["if"], {"github.run_attempt": "1"}) is False
    assert token["with"]["repositories"] == "${{ steps.test.outputs.repo }}"
    assert rerun["env"]["DX_CALLERS_TOKEN"] == "${{ steps.callers.outputs.token }}"
    assert "DX_CALLERS_TOKEN" not in (play[ids.index("play")].get("env") or {})
    checkout(tmp_path, {"release-scenarios.py": RECORD.format(name="release-scenarios.py")})
    ran = run(rerun, tmp_path, env={"OWNER": "o", "TEST_REPO": "t", "DX_CALLERS_TOKEN": "app"})
    assert ran.code == 0, ran.stderr
    moves = ran.of("release-scenarios.py")
    assert len(moves) == 1 and moves[0][0] == "move"
    assert moves[0][moves[0].index("--repo") + 1] == "o/t" and moves[0][moves[0].index("--ref") + 1] == "v7-next"
    # A move that fails plays nothing: the step fails, with its row for the group's file.
    checkout(tmp_path / "x", {"release-scenarios.py": RECORD.format(name="release-scenarios.py")})
    ran = run(rerun, tmp_path / "x", env={"OWNER": "o", "TEST_REPO": "t", "DX_CALLERS_TOKEN": "app",
                                          "FAKE_SCRIPT_DO": json.dumps({"move": {"rows": [{"id": "callers", "ok": False, "why": ["x"]}], "code": 1}})})
    assert ran.code == 1
    assert "callers" in (tmp_path / "x" / "temp" / "results.md").read_text()


# C3: the callers go back to the ref the lane found them at.

CENTRAL = org.CENTRAL
AT_V7 = f"on:\n  issues:\njobs:\n  t:\n    uses: {CENTRAL}/.github/workflows/issue-triage.yml@v7\n"
AT_NEXT = AT_V7.replace("@v7\n", "@v7-next\n")
LANE_PULL = [{"sha": "c2", "commit": {"message": "ci: the engine's callers at v7-next (#41)\n\nThe release lane's scenarios."}, "parents": [{"sha": "c1"}]}]


def left_at_next(tmp_path):
    """A test repository whose caller an earlier lane left at @v7-next: its
    history has the lane's pull request, and @v7 before it."""
    checkout(tmp_path)
    return fake_gh(tmp_path, {"runs": [], "artifacts": {}, "commits": LANE_PULL, "files": {"": {"issues.yml": AT_NEXT}, "c1": {"issues.yml": AT_V7}}})


def test_c3_move_records_a_caller_left_at_v7_next_as_it_was_before_the_lane(tmp_path):
    for left in ('[{"id":"b","scenarios":["b"]}]', "[]"):
        where = tmp_path / ("play" if left != "[]" else "none")
        body, env = left_at_next(where)
        ran = run(step(LANE, "move", job="move"), where, env=dict(env, OWNER="o", TEST_REPO="t", DX_CALLERS_TOKEN="app", LEFT=left), stubs={"gh": body})
        assert ran.code == 0, ran.stderr
        moved = json.loads((where / "temp" / "move" / "moved.json").read_text())
        assert moved == [{"name": "issues.yml", "before": AT_V7}]
        # Already at v7-next: no pull request opens to move it there.
        assert "pulls" not in gh_state(where)
        assert ran.output.get("moved") == ("true" if left != "[]" else None)


def test_c3_back_puts_back_the_ref_the_lane_found(tmp_path):
    body, env = left_at_next(tmp_path)
    record = tmp_path / "temp" / "move" / "scenarios-move-a1"
    record.mkdir(parents=True)
    (record / "moved.json").write_text(json.dumps([{"name": "issues.yml", "before": AT_V7}]))
    ran = run(step(LANE, "The callers back from v7-next", job="back"), tmp_path, env=dict(env, OWNER="o", TEST_REPO="t", DX_CALLERS_TOKEN="app"), stubs={"gh": body})
    assert ran.code == 0, ran.stderr
    st = gh_state(tmp_path)
    assert st["pulls"] == ["ci/callers-v7-next-back"] and st["merged"] == 1
    assert st["files"][""]["issues.yml"] == AT_V7
    assert rows_of(tmp_path / "temp" / "back" / "results.md") == []
