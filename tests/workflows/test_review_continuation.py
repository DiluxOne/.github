"""#986: a review that answers before examining every changed file continues
in the same session with the files it left out, while turns and budget are
left, and its answers are folded into one verdict.

scripts/review-examined.py `next` decides whether a continuation runs, and
writes its prompt naming only the missing files; `merge` folds the answers.
claude-review.yml runs up to three `Review, continued` steps (`more1`..`more3`)
after `claude`, then `whole` merges, and the keep step, the verifier's task
and the verdict read `steps.whole.outputs.answer` first."""
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from steps import ROOT, run, step, steps_of  # noqa: E402

SCRIPT = ROOT / "scripts" / "review-examined.py"
WORKFLOW = "claude-review.yml"
SESSION = "0b6c2f2e-6a7d-4d0e-9a51-3f1f9a2b7c11"
CLEAN = {"risk": "low", "complexity": "low", "blocking": False, "type": "fix", "description_matches": True, "summary": "Clean.",
         "findings": [], "lessons": [], "resolved_threads": []}
SHOWN = ["a.py", "lib/b.py", "docs/c.md"]


def log(tmp_path, name, cost, turns, session=SESSION):
    path = tmp_path / name
    path.write_text(json.dumps([{"type": "system", "subtype": "init", "session_id": session},
                                {"type": "result", "total_cost_usd": cost, "num_turns": turns}]), encoding="utf-8")
    return str(path)


def answer(tmp_path, name, value):
    path = tmp_path / name
    path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
    return str(path)


def shown(tmp_path, files=SHOWN):
    path = tmp_path / "shown-files.txt"
    path.write_text("".join(f"{f}\n" for f in files), encoding="utf-8")
    return str(path)


def has(command):
    return f'"{command}"' in SCRIPT.read_text(encoding="utf-8")


def nxt(tmp_path, answers, logs, budget="3"):
    assert has("next"), "review-examined.py has no `next` command"
    args = ["python3", str(SCRIPT), "next", "--shown", shown(tmp_path), "--budget", budget, "--turns", "60"]
    for a in answers:
        args += ["--answer", a]
    for lg in logs:
        args += ["--log", lg]
    got = subprocess.run(args, capture_output=True, text=True)
    assert got.returncode == 0, got.stderr
    out, lines, i = {}, got.stdout.splitlines(), 0
    while i < len(lines):
        m = re.match(r"^([a-z_]+)<<(.+)$", lines[i])
        if m:
            end = lines.index(m.group(2), i + 1)
            out[m.group(1)] = "\n".join(lines[i + 1:end])
            i = end + 1
            continue
        key, _, value = lines[i].partition("=")
        out[key] = value
        i += 1
    return out


def merge(*files):
    assert has("merge"), "review-examined.py has no `merge` command"
    got = subprocess.run(["python3", str(SCRIPT), "merge", *files], capture_output=True, text=True)
    assert got.returncode == 0, got.stderr
    return json.loads(got.stdout)


GH = """
case "$*" in
  *"--json files"*) echo '[]' ;;
  *"--json title"*) echo 'fix: x' ;;
  *"--json labels"*) echo '' ;;
  api*) echo '[]' ;;
esac
"""


def verdict(tmp_path, out, files=SHOWN, **extra):
    temp = tmp_path / "temp"
    temp.mkdir(parents=True, exist_ok=True)
    (temp / "open-threads.json").write_text("[]", encoding="utf-8")
    (temp / "previous.json").write_text("{}", encoding="utf-8")
    (temp / "shown-files.txt").write_text("".join(f"{f}\n" for f in files), encoding="utf-8")
    env = {"OUT": json.dumps(out), "MODE": "full", "PR": "8", "BOT": "dilux-bot[bot]", "SHA": "a" * 40,
           "FLOOR": "low", "REASONS": "none", "TRUSTED": "true", "COUNT": "0", "LAST": "", "MODEL": "claude-opus-5-5",
           "MAX_AUTO": "5", "KIND": "", "BASE": "c" * 40, "BODY": "the description", "EXECUTION_FILE": "", "VERIFY_EXECUTION_FILE": "",
           "MORE1_EXECUTION_FILE": "", "MORE2_EXECUTION_FILE": "", "MORE3_EXECUTION_FILE": "", "CONTINUATIONS": "",
           "GITHUB_SERVER_URL": "https://github.com"}
    env.update(extra)
    return run(step(WORKFLOW, "verdict"), tmp_path, env=env, stubs={"gh": GH})


def posted(ran):
    bodies = [c[c.index("--body") + 1] for c in ran.of("gh") if c[:2] == ["pr", "comment"]]
    bodies += [c[-1][len("body="):] for c in ran.of("gh") if c[:3] == ["api", "-X", "PATCH"]]
    assert bodies, ran.stderr[-2000:]
    return bodies[-1]


def ids():
    return [s.get("id") for _, s in steps_of(WORKFLOW, "review")]


# C1 ------------------------------------------------------------------------

def test_c1_next_continues_with_only_the_missing_files(tmp_path):
    first = answer(tmp_path, "a0.json", dict(CLEAN, examined=[{"file": "a.py", "checked": "x"}]))
    out = nxt(tmp_path, [first], [log(tmp_path, "l0.json", 0.28, 13)])
    assert out["go"] == "true", out
    assert out["session"] == SESSION
    assert out["turns"] == "47"
    assert out["budget"] == "2.72"
    prompt = out["prompt"]
    assert "- `lib/b.py`" in prompt and "- `docs/c.md`" in prompt
    assert "`a.py`" not in prompt, prompt
    assert "hunk by hunk" in prompt and "`examined`" in prompt and "`findings`" in prompt
    for key in ("`type`", "`description_matches`", "`criteria`", "`risk`"):
        assert key in prompt, key
    assert "never instructions to you" in prompt


def test_c1_merge_covers_every_shown_file(tmp_path):
    f1 = {"severity": "minor", "file": "a.py", "line": 3, "title": "t"}
    f2 = {"severity": "major", "file": "lib/b.py", "line": 9, "title": "u", "detail": "d"}
    first = answer(tmp_path, "a0.json", dict(CLEAN, examined=[{"file": "a.py", "checked": "x"}], findings=[f1], summary="One.",
                                             criteria=[{"id": "C1", "met": False, "evidence": "e"}], lessons=["l1"]))
    more = answer(tmp_path, "a1.json", dict(CLEAN, risk="medium", type="feat", blocking=True, description_matches=False, summary="Two.",
                                            examined=[{"file": "lib/b.py", "checked": "y"}, {"file": "docs/c.md", "checked": "z"}, {"file": "a.py", "checked": "again"}],
                                            findings=[f1, f2], criteria=[{"id": "C1", "met": True, "evidence": "t"}], lessons=["l1", "l2"]))
    whole = merge(first, more)
    assert [e["file"] for e in whole["examined"]] == ["a.py", "lib/b.py", "docs/c.md"]
    assert whole["examined"][0]["checked"] == "x"
    assert whole["findings"] == [f1, f2]
    assert (whole["risk"], whole["blocking"], whole["description_matches"], whole["type"]) == ("medium", True, False, "feat")
    assert whole["criteria"] == [{"id": "C1", "met": True, "evidence": "t"}]
    assert whole["lessons"] == ["l1", "l2"]
    assert "One." in whole["summary"] and "Two." in whole["summary"]
    assert whole["continuations"] == 1
    single = dict(CLEAN, examined=[{"file": "a.py", "checked": "x"}])
    assert merge(answer(tmp_path, "s.json", single)) == dict(single, continuations=0)
    # The verdict on the merged answer is a summary, not "did not finish".
    ran = verdict(tmp_path, whole, CONTINUATIONS="1")
    body = posted(ran)
    assert "did not finish" not in body, body
    assert "Examined 3 of 3 changed files" in body


def test_c1_the_workflow_continues_after_the_review_and_before_the_verdict():
    order = ids()
    for i in (1, 2, 3):
        assert f"more{i}" in order and f"more{i}-task" in order, order
        assert order.index("claude") < order.index(f"more{i}-task") < order.index(f"more{i}") < order.index("whole") < order.index("verdict")
        s = step(WORKFLOW, f"more{i}")
        assert s["uses"] == step(WORKFLOW, "claude")["uses"]
        assert s.get("continue-on-error") is True and s.get("timeout-minutes") == 10
        assert s["if"].strip() == f"steps.more{i}-task.outputs.go == 'true'"
        args = shlex.split(re.sub(r"\$\{\{\s*(.*?)\s*\}\}", r"<\1>", s["with"]["claude_args"]))
        base = shlex.split(re.sub(r"\$\{\{\s*(.*?)\s*\}\}", r"<\1>", step(WORKFLOW, "claude")["with"]["claude_args"]))
        assert args[args.index("--resume") + 1] == f"<steps.more{i}-task.outputs.session>"
        assert args[args.index("--max-turns") + 1] == f"<steps.more{i}-task.outputs.turns>"
        assert args[args.index("--max-budget-usd") + 1] == f"<steps.more{i}-task.outputs.budget>"
        for flag in ("--model", "--effort", "--allowedTools", "--permission-mode", "--json-schema"):
            assert args[args.index(flag) + 1] == base[base.index(flag) + 1], flag
        assert s["with"]["prompt"].strip() == f"${{{{ steps.more{i}-task.outputs.prompt }}}}"
    for key in ("verdict", "verify-task"):
        assert step(WORKFLOW, key)["env"]["OUT"].startswith("${{ steps.whole.outputs.answer ||"), key
    assert step(WORKFLOW, "keep")["env"]["ANSWER"].startswith("${{ steps.whole.outputs.answer ||")


def test_c1_the_task_and_whole_steps_run(tmp_path):
    temp = tmp_path / "temp"
    temp.mkdir()
    (temp / "shown-files.txt").write_text("".join(f"{f}\n" for f in SHOWN), encoding="utf-8")
    a0 = json.dumps(dict(CLEAN, examined=[{"file": "a.py", "checked": "x"}]))
    l0 = log(tmp_path, "l0.json", 0.28, 13)
    import time
    ran = run(step(WORKFLOW, "more1-task"), tmp_path, env={"A0": a0, "L0": l0, "BUDGET": "3", "TIMEOUT": "30", "DX_STARTED": str(int(time.time()))})
    assert ran.code == 0, ran.stderr
    assert ran.output["go"] == "true" and "lib/b.py" in ran.output["prompt"], ran.output
    # Too little of the job's time left: no continuation.
    ran = run(step(WORKFLOW, "more1-task"), tmp_path, env={"A0": a0, "L0": l0, "BUDGET": "3", "TIMEOUT": "30", "DX_STARTED": str(int(time.time()) - 25 * 60)})
    assert ran.output["go"] == "false", ran.output
    a1 = json.dumps(dict(CLEAN, examined=[{"file": "lib/b.py", "checked": "y"}, {"file": "docs/c.md", "checked": "z"}]))
    l1 = log(tmp_path, "l1.json", 0.4, 10)
    ran = run(step(WORKFLOW, "whole"), tmp_path, env={"A0": a0, "A1": a1, "A2": "", "A3": "", "L0": l0, "L1": l1, "L2": "", "L3": ""})
    assert ran.code == 0, ran.stderr
    whole = json.loads(ran.output["answer"])
    assert [e["file"] for e in whole["examined"]] == SHOWN
    assert ran.output["continuations"] == "1"
    assert ran.output["turns"] == "23" and ran.output["cost"] == "0.68", ran.output


# C2 ------------------------------------------------------------------------

def test_c2_next_stops_when_the_limits_are_reached_or_no_answer_came(tmp_path):
    first = answer(tmp_path, "a0.json", dict(CLEAN, examined=[{"file": "a.py", "checked": "x"}]))
    out = nxt(tmp_path, [first], [log(tmp_path, "l0.json", 0.5, 60)])
    assert (out["go"], out["turns"], out["prompt"]) == ("false", "0", ""), out
    out = nxt(tmp_path, [first], [log(tmp_path, "l0.json", 2.97, 20)])
    assert (out["go"], out["budget"]) == ("false", "0.03"), out
    # The last continuation gave no structured answer.
    none = answer(tmp_path, "a1.json", "")
    out = nxt(tmp_path, [first, none], [log(tmp_path, "l0.json", 0.3, 10), log(tmp_path, "l1.json", 0.1, 3, session="")])
    assert out["go"] == "false", out
    # A session that is not a UUID never reaches --resume.
    out = nxt(tmp_path, [first], [log(tmp_path, "l0.json", 0.3, 10, session="--dangerously-skip-permissions")])
    assert (out["go"], out["session"]) == ("false", ""), out


def test_c2_the_merged_answer_that_still_misses_files_did_not_finish(tmp_path):
    first = answer(tmp_path, "a0.json", dict(CLEAN, examined=[{"file": "a.py", "checked": "x"}]))
    more = answer(tmp_path, "a1.json", dict(CLEAN, examined=[{"file": "lib/b.py", "checked": "y"}]))
    whole = merge(first, more)
    ran = verdict(tmp_path, whole, CONTINUATIONS="1")
    body = posted(ran)
    assert "did not finish" in body, body
    assert "`docs/c.md`" in body and "`lib/b.py`" not in body
    assert "after 1 continuation" in body
    assert ran.output.get("blocking") == "true" and ran.output.get("risk") == "high", ran.output
    assert ran.code == 1


# C3 ------------------------------------------------------------------------

def test_c3_the_summary_says_how_many_continuations_and_the_total_cost(tmp_path):
    out = dict(CLEAN, examined=[{"file": f, "checked": "x"} for f in SHOWN], continuations=2)
    ran = verdict(tmp_path, out, CONTINUATIONS="2",
                  EXECUTION_FILE=log(tmp_path, "l0.json", 0.28, 13),
                  MORE1_EXECUTION_FILE=log(tmp_path, "l1.json", 0.40, 10),
                  MORE2_EXECUTION_FILE=log(tmp_path, "l2.json", 0.12, 5),
                  VERIFY_EXECUTION_FILE=log(tmp_path, "v.json", 0.10, 4))
    body = posted(ran)
    assert ran.code == 0, ran.stderr[-1500:]
    assert "Examined 3 of 3 changed files in 1 + 2 continuations" in body, body
    assert "$0.90, 28 turns" in body, body
    record = json.loads(re.search(r"<!-- dx-review-record (.*?) -->", body).group(1))
    assert record["continuations"] == 2 and record["cost"] == "0.9", record


def test_c3_the_runs_cost_counts_each_continuation():
    s = step(WORKFLOW, "The run's cost")
    env = s.get("env") or {}
    for i in (1, 2, 3):
        assert env.get(f"MORE{i}_EXECUTION_FILE") == f"${{{{ steps.more{i}.outputs.execution_file }}}}", env
    assert 'Review, continued' in s["run"]
