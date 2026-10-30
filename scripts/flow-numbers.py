#!/usr/bin/env python3
"""The numbers, every week (#479): how the flow spent its time, from the
same data as #479, in one issue the maintainer reads (flow-numbers.yml keeps
its body up to date in DiluxOne/.github).

  lead time       from the issue a merged pull request closes to its merge,
                  median and average, the autopilot's (`autopilot`, by
                  dilux-bot) and the others' (people's and their agents')
                  apart
  merge queue     its groups' runs that week (merge_group): how many failed,
                  the share, and the median minutes a run took
  autopilot runs  per merged autopilot pull request, its runs (the
                  autopilot:run-N and autopilot:free-N labels, #479 C5),
                  median and average
  flaky tests     the tests the queue's E2E jobs reported flaky (a warning
                  titled "Flaky test", scripts/flaky.py), each once

The issue is public: a private repository's pull requests and runs are in
the numbers, its flaky tests are counted, never named.

  flow-numbers.py              the body, from the last seven days (GH_TOKEN,
                               OWNER; NOW, an ISO time, defaults to now)
  flow-numbers.py render FILE  the body from FILE, the week's data as
                               fetch() returns it (NOW as above)
  flow-numbers.py --test       self-test, from fixtures/flow-numbers.json
"""
import datetime
import json
import os
import re
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MARKER = "<!-- dx-flow-numbers -->"
BOT_LOGINS = ("dilux-bot", "dilux-bot[bot]", "app/dilux-bot")
WEEK = datetime.timedelta(days=7)
RUN_RE = re.compile(r"^autopilot:(?:run|free)-[0-9]+$")

QUERY = """query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 50, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      number mergedAt
      author { login }
      repository { name isPrivate }
      labels(first: 50) { nodes { name } }
      closingIssuesReferences(first: 5) { nodes { createdAt } }
    } }
  }
}"""


def parse(ts):
    return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def spread(values):
    """{n, median, average} of a list of numbers, rounded to one place."""
    if not values:
        return {"n": 0, "median": None, "average": None}
    return {"n": len(values), "median": round(statistics.median(values), 1), "average": round(sum(values) / len(values), 1)}


def numbers(data):
    """The week's numbers from its data ({"prs", "queue", "flaky"}). Pure.

    prs: [{repo, private, number, mergedAt, issueCreatedAt (None when it
    closes none), autopilot, runs}]; queue: [{repo, conclusion, started,
    updated}]; flaky: [{repo, private, spec, line}]."""
    lead = {"autopilot": [], "agents": []}
    for p in data.get("prs") or []:
        if p.get("issueCreatedAt"):
            hours = (parse(p["mergedAt"]) - parse(p["issueCreatedAt"])).total_seconds() / 3600
            lead["autopilot" if p.get("autopilot") else "agents"].append(max(hours, 0))
    done = [r for r in data.get("queue") or [] if r.get("conclusion") not in (None, "", "cancelled", "skipped")]
    failed = [r for r in done if r["conclusion"] in ("failure", "timed_out")]
    minutes = [(parse(r["updated"]) - parse(r["started"])).total_seconds() / 60 for r in done if r.get("started") and r.get("updated")]
    flaky, seen = [], set()
    for f in data.get("flaky") or []:
        key = (f.get("repo"), f.get("spec"), f.get("line"))
        if key not in seen:
            seen.add(key)
            flaky.append(f)
    return {
        "merged": len(data.get("prs") or []),
        "lead": {k: spread(v) for k, v in lead.items()},
        "queue": {"runs": len(done), "failed": len(failed), "rate": round(100 * len(failed) / len(done)) if done else None,
                  "median_minutes": spread(minutes)["median"]},
        "runs": spread([p.get("runs") or 0 for p in data.get("prs") or [] if p.get("autopilot")]),
        "flaky": flaky,
    }


def render(n, now):
    """The issue's body. Pure."""
    def h(v):
        return "–" if v is None else f"{v} h"
    lines = [MARKER, f"# The week's numbers ({(now - WEEK).strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')})", "",
             f"How the flow spent its time over the last seven days (#479, `scripts/flow-numbers.py`), from {n['merged']} merged pull requests. "
             "This body is rewritten every week.", "",
             "## Lead time, from the issue to the merge", "",
             "| | Pull requests | Median | Average |", "| --- | --- | --- | --- |"]
    for k, label in (("autopilot", "The autopilot's"), ("agents", "The others' (people and their agents)")):
        s = n["lead"][k]
        lines.append(f"| {label} | {s['n']} | {h(s['median'])} | {h(s['average'])} |")
    q = n["queue"]
    lines += ["", "## The merge queue", ""]
    if q["runs"]:
        lines.append(f"{q['failed']} of {q['runs']} runs of its groups failed ({q['rate']}%); a run took {q['median_minutes']} minutes (median). "
                     "Each failure drops a pull request and costs another run.")
    else:
        lines.append("No group ran this week.")
    r = n["runs"]
    lines += ["", "## The autopilot's runs per pull request", ""]
    lines.append(f"{r['median']} (median), {r['average']} (average), over {r['n']} merged autopilot pull requests." if r["n"]
                 else "No autopilot pull request merged this week.")
    lines += ["", "## Flaky tests found", ""]
    public = [f for f in n["flaky"] if not f.get("private")]
    hidden = len(n["flaky"]) - len(public)
    if not n["flaky"]:
        lines.append("None: no test failed and then passed on its retry in the queue.")
    else:
        lines.append(f"{len(n['flaky'])} test(s) failed and then passed on their retry (scripts/flaky.py); each repository's agent fixes its own:")
        lines += [""] + [f"- {f['repo']}: `{f['spec']}:{f['line']}`" for f in public]
        if hidden:
            lines.append(f"- {hidden} in private repositories")
    return "\n".join(lines) + "\n"


def gh_json(*args):
    res = subprocess.run(["gh", *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])} failed: {res.stderr.strip()[:300]}")
    return json.loads(res.stdout or "null")


def fetch(owner, now):
    """The week's data, read from GitHub: merged pull requests, the merge
    groups' runs and their E2E jobs' flaky-test warnings."""
    since = (now - WEEK).strftime("%Y-%m-%dT%H:%M:%SZ")
    prs, after = [], None
    while True:
        args = ["api", "graphql", "-f", f"query={QUERY}", "-f", f"q=org:{owner} is:pr is:merged merged:>={since}"] + (["-f", f"after={after}"] if after else [])
        page = gh_json(*args)["data"]["search"]
        for p in page["nodes"]:
            if not p:
                continue
            labels = [l["name"] for l in p["labels"]["nodes"]]
            issues = sorted(i["createdAt"] for i in p["closingIssuesReferences"]["nodes"])
            prs.append({"repo": p["repository"]["name"], "private": p["repository"]["isPrivate"], "number": p["number"], "mergedAt": p["mergedAt"],
                        "issueCreatedAt": issues[0] if issues else None,
                        "autopilot": "autopilot" in labels and (p.get("author") or {}).get("login") in BOT_LOGINS,
                        "runs": sum(1 for l in labels if RUN_RE.match(l))})
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    queue, flaky = [], []
    repos = gh_json("api", "--paginate", "--slurp", f"orgs/{owner}/repos?per_page=100")
    for repo in [r for chunk in repos for r in chunk if not r.get("archived")]:
        full = repo["full_name"]
        runs = gh_json("api", f"repos/{full}/actions/runs?event=merge_group&created=>={since[:10]}&per_page=100")["workflow_runs"]
        for run in runs:
            queue.append({"repo": repo["name"], "conclusion": run.get("conclusion"), "started": run.get("run_started_at"), "updated": run.get("updated_at")})
            for job in gh_json("api", f"repos/{full}/actions/runs/{run['id']}/jobs?per_page=100")["jobs"]:
                if not str(job.get("name", "")).startswith("E2E"):
                    continue
                for a in gh_json("api", f"repos/{full}/check-runs/{job['id']}/annotations?per_page=100"):
                    if a.get("title") == "Flaky test":
                        flaky.append({"repo": repo["name"], "private": repo.get("private", True), "spec": a.get("path"), "line": a.get("start_line")})
    return {"prs": prs, "queue": queue, "flaky": flaky}


def now_():
    return parse(os.environ["NOW"]) if os.environ.get("NOW") else datetime.datetime.now(datetime.timezone.utc)


def self_test():
    fails = []

    def check(name, got, want):
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        if got != want:
            fails.append(name)

    with open(os.path.join(HERE, "fixtures", "flow-numbers.json"), encoding="utf-8") as fh:
        fx = json.load(fh)
    n = numbers(fx)
    check("C8 lead time, the autopilot's: median and average hours", n["lead"]["autopilot"], {"n": 3, "median": 8.0, "average": 12.7})
    check("C8 lead time, the others', apart; a pull request that closes no issue has none", n["lead"]["agents"], {"n": 2, "median": 1.0, "average": 1.0})
    check("C8 the queue's failure rate and time, a cancelled run left out", n["queue"], {"runs": 4, "failed": 2, "rate": 50, "median_minutes": 40.5})
    check("C8 the autopilot's runs per pull request", n["runs"], {"n": 3, "median": 6, "average": 5.0})
    check("C8 the flaky tests found, each once", [(f["repo"], f["spec"], f["line"]) for f in n["flaky"]],
          [("diluxone-users-wordpress", "tests/e2e/login.spec.ts", 14), ("diluxone-users-wordpress", "tests/e2e/media.spec.ts", 3), ("secret", "x.spec.ts", 1)])
    body = render(n, parse(fx["now"]))
    for what in ("| The autopilot's | 3 | 8.0 h | 12.7 h |", "| The others' (people and their agents) | 2 | 1.0 h | 1.0 h |",
                 "2 of 4 runs of its groups failed (50%); a run took 40.5 minutes (median)", "6 (median), 5.0 (average), over 3 merged autopilot pull requests",
                 "- diluxone-users-wordpress: `tests/e2e/login.spec.ts:14`", "- 1 in private repositories"):
        check(f"C8 the body says: {what}", what in body, True)
    check("C8 a private repository's flaky test is counted, never named", "secret" in body, False)
    empty = render(numbers({}), parse(fx["now"]))
    check("C8 an empty week says so", ("No group ran this week." in empty, "No autopilot pull request merged" in empty, "| The autopilot's | 0 | – | – |" in empty), (True, True, True))
    print("all tests passed" if not fails else f"{len(fails)} failed")
    return 1 if fails else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if len(argv) == 2 and argv[0] == "render":
        with open(argv[1], encoding="utf-8") as fh:
            sys.stdout.write(render(numbers(json.load(fh)), now_()))
        return 0
    if not argv:
        now = now_()
        sys.stdout.write(render(numbers(fetch(os.environ.get("OWNER", "DiluxOne"), now)), now))
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
