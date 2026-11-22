"""#953 C1: the review accounts for every changed file it was shown, and an
answer that leaves one out is a review that did not finish, never a clean
one.

claude-review.yml's review schema requires `examined` (one entry per changed
file, with what was checked) and its prompt asks for every file of the
diff; scripts/review-examined.py compares an answer with the brief's
`shown-files.txt`; the verdict step blocks on a missing file with the "did
not finish" comment; the fixed review (#943) writes an entry for every
shown file; and the review's evaluation plays an answer that misses a file
as not reviewed, not as clean."""
import importlib.util
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from steps import ROOT, run, step  # noqa: E402

SCRIPT = ROOT / "scripts" / "review-examined.py"
WORKFLOW = ROOT / ".github" / "workflows" / "claude-review.yml"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def review_step():
    return step("claude-review.yml", "claude")


def schema():
    args = shlex.split(review_step()["with"]["claude_args"])
    return json.loads(args[args.index("--json-schema") + 1])


def test_c1_the_review_schema_requires_examined_and_the_prompt_asks_for_every_file():
    s = schema()
    assert "examined" in s["required"], s["required"]
    item = s["properties"]["examined"]["items"]
    assert set(item["required"]) == {"file", "checked"}
    assert item["properties"]["checked"]["maxLength"] == 300
    prompt = " ".join(review_step()["with"]["prompt"].split())
    assert "every changed file" in prompt
    assert "hunk by hunk" in prompt
    assert "`examined`" in prompt
    # No new expression the evaluation would have to fill in.
    assert set(re.findall(r"\$\{\{\s*(.*?)\s*\}\}", review_step()["with"]["prompt"])) == {"github.repository", "github.event.pull_request.number"}


def run_script(tmp_path, answer, shown):
    review, files = tmp_path / "review.json", tmp_path / "shown-files.txt"
    review.write_text(json.dumps(answer), encoding="utf-8")
    files.write_text("".join(f"{f}\n" for f in shown), encoding="utf-8")
    return subprocess.run(["python3", str(SCRIPT), "missing", str(review), str(files)], capture_output=True, text=True)


def test_c1_the_script_names_a_shown_file_with_no_entry(tmp_path):
    assert SCRIPT.exists(), "no scripts/review-examined.py"
    answer = {"examined": [{"file": "a.py", "checked": "its callers"}]}
    out = run_script(tmp_path, answer, ["a.py", "lib/b.py"])
    assert out.returncode == 1, out
    assert out.stdout.split() == ["lib/b.py"]


def test_c1_the_script_passes_an_answer_that_covers_every_file(tmp_path):
    answer = {"examined": [{"file": "./a.py", "checked": "x"}, {"file": "lib/b.py", "checked": "y"}]}
    out = run_script(tmp_path, answer, ["a.py", "lib/b.py"])
    assert out.returncode == 0, out
    assert out.stdout == ""
    # An answer with no `examined` at all misses every file.
    out = run_script(tmp_path, {"findings": []}, ["a.py"])
    assert (out.returncode, out.stdout.split()) == (1, ["a.py"])


GH = """
case "$*" in
  *"--json files"*) echo '[]' ;;
  *"--json title"*) echo 'fix: x' ;;
  *"--json labels"*) echo '' ;;
  api*) echo '[]' ;;
esac
"""
CLEAN = {"risk": "low", "complexity": "low", "blocking": False, "type": "fix", "description_matches": True, "summary": "Clean.",
         "findings": [], "lessons": [], "resolved_threads": []}


def verdict(tmp_path, out, shown):
    temp = tmp_path / "temp"
    temp.mkdir(parents=True, exist_ok=True)
    (temp / "open-threads.json").write_text("[]", encoding="utf-8")
    (temp / "previous.json").write_text("{}", encoding="utf-8")
    (temp / "shown-files.txt").write_text("".join(f"{f}\n" for f in shown), encoding="utf-8")
    env = {"OUT": json.dumps(out), "MODE": "full", "PR": "8", "BOT": "dilux-bot[bot]", "SHA": "a" * 40,
           "FLOOR": "low", "REASONS": "none", "TRUSTED": "true", "COUNT": "0", "LAST": "", "MODEL": "claude-opus-5-5",
           "MAX_AUTO": "5", "KIND": "", "BASE": "c" * 40, "BODY": "the description", "EXECUTION_FILE": "", "VERIFY_EXECUTION_FILE": "",
           "GITHUB_SERVER_URL": "https://github.com"}
    return run(step("claude-review.yml", "verdict"), tmp_path, env=env, stubs={"gh": GH})


def posted(ran):
    bodies = [c[c.index("--body") + 1] for c in ran.of("gh") if c[:2] == ["pr", "comment"]]
    bodies += [c[-1][len("body="):] for c in ran.of("gh") if c[:3] == ["api", "-X", "PATCH"]]
    assert bodies, ran.stderr[-2000:]
    return bodies[-1]


def test_c1_the_verdict_on_an_answer_that_misses_a_file_did_not_finish(tmp_path):
    out = dict(CLEAN, examined=[{"file": "a.py", "checked": "its callers"}])
    ran = verdict(tmp_path, out, ["a.py", "lib/b.py"])
    body = posted(ran)
    assert "did not finish" in body, body
    assert "lib/b.py" in body
    assert ran.output.get("blocking") == "true" and ran.output.get("risk") == "high", ran.output
    assert ran.code == 1


def test_c1_the_verdict_on_an_answer_that_covers_every_file_is_clean(tmp_path):
    out = dict(CLEAN, examined=[{"file": "a.py", "checked": "x"}, {"file": "lib/b.py", "checked": "y"}])
    ran = verdict(tmp_path, out, ["a.py", "lib/b.py"])
    body = posted(ran)
    assert "did not finish" not in body
    assert "Examined 2 of 2 changed files" in body
    record = json.loads(re.search(r"<!-- dx-review-record (.*?) -->", body).group(1))
    assert record["examined"] == 2
    assert ran.output.get("blocking") == "false" and ran.code == 0, ran.stderr[-1500:]


def test_c1_the_fixed_review_covers_every_shown_file(tmp_path):
    fixed = load("fixed_review", ROOT / "scripts" / "fixed-review.py")
    issue = ("<!-- dx-scenario: claim-and-release -->\n### Problem\n\nx\n\n### Acceptance criteria\n\n"
             "- C1: Given a, when b, then c.\n\n### Criticality\n\nNormal\n")

    def read(*args):
        return {"body": "Closes #5"} if args[1].endswith("pulls/7") else {"body": issue}

    shown = tmp_path / "shown-files.txt"
    shown.write_text("a.py\nlib/b.py\n", encoding="utf-8")
    env = {"FIXED": "scenarios/{scenario}/{n}.test.md", "REPO": "o/t", "PR": "7", "TITLE": "feat: a greeting",
           "FLOOR": "low", "SCENARIOS": str(ROOT / "tests" / "release" / "scenarios.yml"), "SHOWN": str(shown)}
    hit, ans = fixed.decide(env, read)
    assert hit is True
    assert [e["file"] for e in ans["examined"]] == ["a.py", "lib/b.py"]
    examined = load("review_examined", SCRIPT)
    assert examined.missing(ans, ["a.py", "lib/b.py"]) == []
    # An unreadable list: the model reviews.
    assert fixed.decide(dict(env, SHOWN=str(tmp_path / "none.txt")), read) == (False, None)
    # The fixedrev step hands the script the brief's list.
    assert "shown-files.txt" in step("claude-review.yml", "fixedrev")["run"]


def test_c1_the_evaluation_plays_an_answer_that_misses_a_file_as_not_reviewed(tmp_path, monkeypatch):
    ev = load("review_eval", ROOT / "scripts" / "review-eval.py")
    work = tmp_path / "work"
    work.mkdir()
    (work / "shown-files.txt").write_text("a.py\nlib/b.py\n", encoding="utf-8")
    flag = {"severity": "major", "file": "a.py", "line": 3, "title": "t", "detail": "d"}
    answer = dict(CLEAN, findings=[flag], examined=[{"file": "a.py", "checked": "x"}])
    case = {"id": "o/r#7:flag", "repo": "o/r", "pr": 7, "base": "b" * 40, "head": "h" * 40, "expect": "flag", "path": "a.py", "line": 3, "hunk": [1, 4], "fixed": [[3, 3]]}
    assert ev.unfinished(answer, str(work)) == ["lib/b.py"]
    assert ev.unfinished(dict(answer, examined=[{"file": "a.py", "checked": "x"}, {"file": "lib/b.py", "checked": "y"}]), str(work)) == []
    # run_case scores what play_review returns: an unfinished one is None,
    # with its reason, never a clean or a missed play.
    monkeypatch.setattr(ev, "play_review", lambda c, repo_dir, w, steps: ev.finished(c, answer, str(work)))
    monkeypatch.setattr(ev.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    (tmp_path / "w" / "o_r").mkdir(parents=True)
    assert ev.run_case(case, str(ROOT), str(tmp_path / "w"), steps={"review": {}, "verify": {}}) is None
    assert ev.WHY[case["id"]] == "did not examine every changed file"
    covered = dict(answer, examined=[{"file": "a.py", "checked": "x"}, {"file": "lib/b.py", "checked": "y"}])
    monkeypatch.setattr(ev, "play_review", lambda c, repo_dir, w, steps: ev.finished(c, covered, str(work)))
    assert ev.run_case(case, str(ROOT), str(tmp_path / "w"), steps={"review": {}, "verify": {}}) is True
    assert ev.WHY[case["id"]] == "found"


def test_c1_the_verification_keeps_examined_as_the_review_wrote_it():
    verify = load("review_verify", ROOT / "scripts" / "review-verify.py")
    examined = [{"file": "a.py", "checked": "x"}]
    review = dict(CLEAN, findings=[{"severity": "major", "file": "a.py", "line": 3, "title": "t", "detail": "d"}], examined=examined)
    out = verify.apply(review, {"verdicts": [{"i": 0, "real": False, "why": "no"}]})
    assert out["examined"] == examined
