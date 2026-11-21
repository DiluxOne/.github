"""A settled finding re-runs the review only once the review's run has
finished (#912): GitHub refuses `rerun-failed-jobs` on a run still in
progress, and the review's run goes on after its check (auto-merge, waiting,
pipeline). Runs the "Re-run the review on a settled finding" step of
review-reply.yml as the runner does (tests/workflows/steps.py), with `gh`,
deciders.py and `sleep` stood in; `gh --jq` is applied by the real jq."""
import json

from steps import run, step

HEAD = "a" * 40
BOT = "dilux-bot[bot]"

# The gh stand-in: each key of answers.json is a part of the call's text,
# and its value the list of answers, given in turn (the last one again once
# they run out), as {"out": text, "code": n}. `--jq` runs the real jq.
GH = r'''import json, os, re, subprocess, sys
args = sys.argv[1:]
text = " ".join(args)
d = os.environ["DX_GH"]
answers = json.load(open(os.path.join(d, "answers.json")))
for key, seq in answers.items():
    if key in text:
        count = os.path.join(d, "n-" + re.sub(r"[^A-Za-z0-9]", "_", key))
        n = int(open(count).read()) if os.path.exists(count) else 0
        open(count, "w").write(str(n + 1))
        a = seq[min(n, len(seq) - 1)]
        out = a.get("out", "")
        if "--jq" in args and a.get("code", 0) == 0:
            out = subprocess.run(["jq", "-r", args[args.index("--jq") + 1]], input=out,
                                 capture_output=True, text=True, check=True).stdout
        sys.stdout.write(out)
        sys.exit(a.get("code", 0))
sys.exit(1)
'''


def record(blocking):
    rec = json.dumps({"sha": HEAD, "blocking": blocking})
    return json.dumps([{"user": {"login": BOT}, "body": f"<!-- dx-review -->\nSummary\n<!-- dx-review-record {rec} -->"}])


def check(status, run_id=55):
    return json.dumps({"check_runs": [{"name": "review / Claude review", "status": status,
                                       "details_url": f"https://github.com/o/r/actions/runs/{run_id}/job/1"}]})


def play(tmp_path, *, blocking=True, checks, runs):
    data = tmp_path / "gh"
    data.mkdir()
    answers = {
        "closingIssuesReferences": [{"out": json.dumps({"closingIssuesReferences": [{"number": 7}]})}],
        "headRefOid": [{"out": json.dumps({"headRefOid": HEAD})}],
        "issues/9/comments": [{"out": record(blocking)}],
        "rerun-failed-jobs": [{"out": "{}"}],
        f"commits/{HEAD}/check-runs": [{"out": c} for c in checks],
        "actions/runs/55": [{"out": json.dumps({"status": s})} for s in runs],
    }
    (data / "answers.json").write_text(json.dumps(answers))
    (data / "gh.py").write_text(GH)
    s = step("review-reply.yml", "Re-run the review on a settled finding")
    ran = run(s, tmp_path, central=False,
              files={".dx-central/scripts/deciders.py": "import sys\nsys.exit(0)\n"},
              stubs={"gh": f'exec python3 "{data}/gh.py" "$@"', "sleep": "exit 0"},
              env={"PR": "9", "LOGIN": "someone", "BOT": BOT, "DX_GH": str(data)})
    assert ran.code == 0, ran.stdout + ran.stderr
    return ran


def order(ran):
    """The calls of interest, in order: status reads, sleeps and the POST."""
    out = []
    for c in ran.calls:
        text = " ".join(c)
        if c[0] == "sleep":
            out.append("sleep")
        elif "rerun-failed-jobs" in text:
            out.append("rerun")
        elif "actions/runs/55" in text:
            out.append("run-status")
        elif "check-runs" in text:
            out.append("check")
    return out


def test_waits_for_the_run_to_complete_before_the_rerun(tmp_path):
    ran = play(tmp_path, checks=[check("completed")], runs=["in_progress", "completed"])
    seen = order(ran)
    # Read in progress, waited, read completed, and only then the POST.
    assert seen == ["check", "run-status", "sleep", "check", "run-status", "rerun"], seen
    assert "runs again (run 55)" in ran.stdout


def test_waits_for_a_check_in_progress(tmp_path):
    ran = play(tmp_path, checks=[check("in_progress"), check("completed")], runs=["completed"])
    assert "No finished review" not in ran.stdout
    seen = order(ran)
    assert seen.count("rerun") == 1, seen
    assert seen.index("sleep") < seen.index("rerun"), seen


def test_a_run_that_never_completes_stops_with_a_warning(tmp_path):
    ran = play(tmp_path, checks=[check("completed")], runs=["in_progress"])
    seen = order(ran)
    assert "rerun" not in seen, seen
    assert "::warning::" in ran.stdout and "55" in ran.stdout
    # Bounded: 6 minutes of 15-second polls.
    assert 0 < seen.count("sleep") <= 24, seen


def test_a_record_that_does_not_block_reruns_nothing(tmp_path):
    ran = play(tmp_path, blocking=False, checks=[check("completed")], runs=["completed"])
    seen = order(ran)
    assert seen == [], seen
    assert "did not block" in ran.stdout
