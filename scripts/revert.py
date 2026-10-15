#!/usr/bin/env python3
"""Gate G8 (#142, the plan in #78): a merge that turns the default branch red
is reverted, unless the red is a flaky job.

  revert.py scan          every repository the token reaches: for each
                          workflow whose runs on the default branch went red,
                          the run where the red began, the pull request whose
                          merge it ran on, and what to do. Writes the plan (a
                          JSON list, `plan=` to GITHUB_OUTPUT) and a report
                          (GITHUB_STEP_SUMMARY, and stdout)
  revert.py act           one item of the plan (ITEM, JSON): re-run the failed
                          jobs once, or open the Bug issue and the revert pull
                          request and label the original `reverted`
  revert.py decide        whether a revert pull request merges on its own
                          (within the `platform` lane); prints why; exit 0
                          when it may
  revert.py wait-comment  the comment that tells a person what to do when it
                          does not (WHY, PR_URL)
  revert.py --test        self-test, without the network

What is red, and when it is reverted (assess):
  - the red began on a run of a push to the default branch (every finished
    run before it, back to a green one, is that workflow's streak);
  - that run's commit is the merge of a pull request into the default branch;
  - a job that failed there passed on the pull request's head, and none of
    them failed there: the merge turned it red, not the change alone;
  - the first attempt failed: its failed jobs are re-run once. A re-run that
    passes is flaky, said in the report, and nothing is reverted; one that
    fails again holds, and the merge is reverted;
  - never a revert's own merge, never twice (the `reverted` label, or the
    Bug issue that names the commit), never with DX_AUTOPILOT=off or the
    autopilot off in the policy (the repository's .github/autonomy.yml can
    turn it off for that repository).

Environment: GH_TOKEN; DX_AUTOPILOT; ORG_AUTONOMY / REPO_AUTONOMY as
autonomy.py reads them. For decide: GITHUB_REPOSITORY, AUTHOR, RISK,
COMPLEXITY, BLOCKING, DESCRIPTION_OK (the review's outputs), FILES (a file,
one changed path per line, renames by their old path too).
"""
import base64
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


autonomy = _load("autonomy", "autonomy.py")
autopilot = _load("autopilot", "autopilot.py")

LANE = "platform"
BOT = "dilux-bot[bot]"
BOT_EMAIL = "333187390+dilux-bot[bot]@users.noreply.github.com"
AI_LINE = autopilot.AI_LINE
RED = ("failure", "timed_out")
WAIT = "<!-- dx-revert-wait -->"
RUNS_READ = 100


# --- the decision, pure -----------------------------------------------------

def stopped(autopilot_var, policy):
    """Why nothing may be re-run or reverted, or None."""
    if (autopilot_var or "").strip().lower() == "off":
        return "the organisation's DX_AUTOPILOT is off"
    if not policy.get("autopilot", False):
        return "the autopilot is off in the policy"
    return None


def pick(runs):
    """A workflow's runs on the default branch, newest first ->
    (state, run, why). state: healthy, flaky? (green on a re-run: whether its
    first attempt failed decides), red (run: where the red began), none."""
    done = [r for r in runs if r.get("status") == "completed" and r.get("conclusion") in RED + ("success",)]
    if not done:
        return "none", None, "no finished run"
    if done[0]["conclusion"] == "success":
        if int(done[0].get("run_attempt") or 1) > 1:
            return "flaky?", done[0], "green on a re-run"
        return "healthy", done[0], "green"
    start = None
    for r in done:
        if r["conclusion"] == "success":
            return "red", start, "red since this run"
        start = r
    return "none", None, f"red on every run read ({len(done)}): it was red before any merge seen here; a person looks"


def is_revert(pr):
    labels = set(pr.get("labels") or [])
    return "revert" in labels or (pr.get("head_ref") or "").startswith("revert/") or bool(re.match(r"^revert(\(|!|:)", pr.get("title") or ""))


def assess(run, pr, failed_jobs, pr_checks, already=False):
    """What to do with the run where a workflow's red began -> (action, why).
    action: none, rerun or revert. Pure: everything is read before."""
    if pr is None:
        return "none", "its commit is not the merge of a pull request into the default branch"
    if is_revert(pr):
        return "none", f"the red merge is itself a revert (#{pr['number']}): a person looks"
    if "reverted" in (pr.get("labels") or []) or already:
        return "none", f"#{pr['number']} is already reverted"
    if not failed_jobs:
        return "none", "no failed job to compare with the pull request"
    red_there = [j for j in failed_jobs if pr_checks.get(j) not in (None, "success")]
    if red_there:
        return "none", f"{', '.join(red_there[:3])} did not pass on #{pr['number']} either: it merged red, not turned red by the merge"
    green = [j for j in failed_jobs if pr_checks.get(j) == "success"]
    if not green:
        return "none", f"the failed jobs ({', '.join(failed_jobs[:3])}) did not run on #{pr['number']}: nothing to compare"
    if int(run.get("run_attempt") or 1) < 2:
        return "rerun", f"{', '.join(green[:3])} passed on #{pr['number']} and failed after its merge; re-run once to tell a flaky job"
    return "revert", f"{', '.join(green[:3])} passed on #{pr['number']}, failed after its merge and again on the re-run"


def flaky(first_attempt_conclusion):
    return first_attempt_conclusion in RED


def decide(policy, repository, files, risk, complexity, blocking, description_ok, author, autopilot_var):
    """Gate G8's merge: a revert pull request merges on its own only within
    the `platform` lane's limits. Pure."""
    if author != BOT:
        return False, f"a revert pull request is opened by {BOT}, not {author or 'unknown'}"
    why = stopped(autopilot_var, policy)
    if why:
        return False, why
    lane = (policy.get("lanes") or {}).get(LANE)
    if not lane or not lane.get("enabled", True):
        return False, f"the {LANE} lane is off"
    name = repository.split("/", 1)[-1]
    covered = lane.get("repositories") or []
    if "*" not in covered and name not in covered:
        return False, f"{name} is outside the {LANE} lane (it covers {', '.join(covered) or 'none'})"
    import fnmatch
    protected = [f for f in files if any(fnmatch.fnmatch(f, p) for p in policy.get("constitution") or [])]
    if protected:
        return False, "it touches rules that govern autonomy (" + ", ".join(protected[:3]) + "): a person merges it"
    if blocking != "false":
        return False, "the review is blocking"
    if description_ok != "true":
        return False, "the description does not match the code"
    caps = lane.get("merge") or {}
    if not autopilot.within(risk, caps.get("max-risk", "none")):
        return False, f"risk {risk or 'unknown'} is above the {LANE} lane's {caps.get('max-risk', 'none')}"
    if not autopilot.within(complexity, caps.get("max-complexity", "none")):
        return False, f"complexity {complexity or 'unknown'} is above the {LANE} lane's {caps.get('max-complexity', 'none')}"
    return True, f"merges by policy: G8, lane {LANE}, risk {risk}, complexity {complexity}"


# --- the texts --------------------------------------------------------------

def short(text, limit):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def revert_title(title):
    """`revert: <original title>`, 72 characters at most."""
    return short(f"revert: {title}", 72)


def branch(number, title):
    return f"revert/{number}-{autopilot.kebab(title)}"


def issue_title(item):
    return short(f"Default branch red after #{item['pr']}: {item['pr_title']}", 100)


def issue_body(item):
    repo = item["repo"]
    jobs = ", ".join(f"`{j}`" for j in item["failed"][:5])
    return f"""The default branch went red after #{item['pr']} merged, and stayed red when its failed jobs ran again, so it is not a flaky job (gate G8 of #78).

- **Merge:** https://github.com/{repo}/commit/{item['sha']} (`{item['sha']}`)
- **Failing run:** {item['run_url']} ({item['workflow']}: {jobs})
- **Original pull request:** {item['pr_url']}, whose head passed the same checks.

dilux-bot opens a pull request that reverts the merge and closes this issue. It goes through the gates like any change and merges on its own only within the `{LANE}` lane of policy/autonomy.yml; otherwise this issue says who does what. Fixing the cause is the original issue's, reopened.

{AI_LINE}"""


def pr_body(item, issue):
    return f"""## 📝 What changes

Reverts #{item['pr']} ({item['pr_title']}), merge commit {item['sha']}, on the default branch.

## 💡 Why

Closes #{issue}. After that merge, {item['workflow']} failed on the default branch ({item['run_url']}) and again on a re-run, while the same jobs had passed on the pull request's head: the merge turned the default branch red, and every pull request opened since inherits it.

## 🧪 How I tested it

The revert is `git revert` of the merge commit, applied cleanly on the default branch. The checks of this pull request show the default branch green again.

{AI_LINE}"""


def wait_comment(why, pr_url):
    return f"""{WAIT}
**The revert waits for a person (G8):** {why}.

Approve and merge {pr_url}

{AI_LINE}"""


def conflict_comment(item):
    return f"""**The merge could not be reverted cleanly** on today's default branch: later changes touch the same lines. Nothing was opened; a person reverts it by hand.

Revert #{item['pr']} by hand: {item['pr_url']}

{AI_LINE}"""


def report_line(item_label, workflow, verdict, why, run_url=None):
    where = f" ([run]({run_url}))" if run_url else ""
    return f"- **{item_label}**, {workflow}: {verdict}: {why}{where}."


# --- the network ------------------------------------------------------------

def gh(*args, input_text=None):
    out = subprocess.run(["gh"] + list(args), input=input_text, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:300])
    return out.stdout


def api(path, *args):
    return json.loads(gh("api", path, *args) or "null")


def repo_policy(repo, default):
    org = autonomy.load(os.environ.get("ORG_AUTONOMY") or os.path.join(HERE, "..", "policy", "autonomy.yml"))
    mine = {}
    try:
        content = api(f"repos/{repo}/contents/.github/autonomy.yml?ref={default}").get("content", "")
        path = os.path.join(tempfile.mkdtemp(), "autonomy.yml")
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(content))
        mine = autonomy.load(path)
    except RuntimeError:
        pass
    return autonomy.merge(org, mine)


def find_pr(repo, sha, default):
    for p in api(f"repos/{repo}/commits/{sha}/pulls") or []:
        if p.get("merged_at") and p.get("merge_commit_sha") == sha and (p.get("base") or {}).get("ref") == default:
            return {"number": p["number"], "title": p.get("title", ""), "url": p.get("html_url", ""),
                    "head_sha": p["head"]["sha"], "head_ref": p["head"].get("ref", ""),
                    "labels": [l["name"] for l in p.get("labels") or []]}
    return None


def checks_at(repo, sha):
    """{check name: success, or the first conclusion that is not}."""
    out = {}
    for c in (api(f"repos/{repo}/commits/{sha}/check-runs?filter=latest&per_page=100") or {}).get("check_runs") or []:
        name, concl = c.get("name"), c.get("conclusion") or c.get("status")
        if out.get(name, "success") == "success":
            out[name] = concl
    return out


def failed_jobs(repo, run_id):
    jobs = (api(f"repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100") or {}).get("jobs") or []
    return [j["name"] for j in jobs if j.get("conclusion") in RED]


def issue_for(repo, sha):
    q = f"repo:{repo} is:issue author:app/dilux-bot {sha} in:body"
    items = (api("search/issues", "-X", "GET", "-f", f"q={q}") or {}).get("items") or []
    return items[0]["number"] if items else None


def write_output(key, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")


def write_summary(text):
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def scan():
    head = "## Red default branches (G8)\n"
    org = autonomy.merge(autonomy.load(os.environ.get("ORG_AUTONOMY") or os.path.join(HERE, "..", "policy", "autonomy.yml")), {})
    why = stopped(os.environ.get("DX_AUTOPILOT", ""), org)
    if why:
        write_output("plan", "[]")
        write_summary(f"{head}\nNothing is re-run or reverted: {why}.")
        return 0
    lines, plan = [], []
    repos = []
    page = 1
    while True:
        got = api(f"installation/repositories?per_page=100&page={page}") or {}
        repos += got.get("repositories") or []
        if len(got.get("repositories") or []) < 100:
            break
        page += 1
    for r in repos:
        if r.get("archived") or r.get("disabled"):
            continue
        full, default, private = r["full_name"], r.get("default_branch") or "main", bool(r.get("private"))
        if private:
            # This repository is public, and so are its logs.
            print(f"::add-mask::{full}")
            print(f"::add-mask::{r['name']}")
        label = "A private repository" if private else full
        try:
            why = stopped(os.environ.get("DX_AUTOPILOT", ""), repo_policy(full, default))
            if why:
                lines.append(report_line(label, "every workflow", "skipped", why))
                continue
            runs = (api(f"repos/{full}/actions/runs?branch={default}&event=push&per_page={RUNS_READ}") or {}).get("workflow_runs") or []
            groups = {}
            for run in runs:
                if run.get("head_branch") == default:
                    groups.setdefault(run["workflow_id"], []).append(run)
            seen = set()
            for wruns in groups.values():
                workflow = wruns[0].get("name") or "a workflow"
                state, run, why = pick(wruns)
                url = None if private else (run or {}).get("html_url")
                if state == "flaky?":
                    first = (api(f"repos/{full}/actions/runs/{run['id']}/attempts/1") or {}).get("conclusion")
                    if flaky(first):
                        lines.append(report_line(label, workflow, "flaky", "it failed, then passed when re-run; nothing is reverted", url))
                    continue
                if state == "none" and run is None and why.startswith("red"):
                    lines.append(report_line(label, workflow, "left alone", why))
                if state != "red" or run["head_sha"] in seen:
                    continue
                seen.add(run["head_sha"])
                pr = find_pr(full, run["head_sha"], default)
                failed = failed_jobs(full, run["id"])
                action, why = assess(run, pr, failed, checks_at(full, pr["head_sha"]) if pr else {})
                if action == "revert":
                    n = issue_for(full, run["head_sha"])
                    if n:
                        action, why = assess(run, pr, failed, {}, already=True)
                lines.append(report_line(label, workflow, {"none": "left alone", "rerun": "re-run", "revert": "reverted"}[action], why, url))
                if action in ("rerun", "revert"):
                    plan.append({"kind": action, "repo": full, "name": r["name"], "private": private, "default": default,
                                 "run_id": run["id"], "run_url": run["html_url"], "run_attempt": int(run.get("run_attempt") or 1),
                                 "workflow": workflow, "sha": run["head_sha"], "failed": failed,
                                 "pr": pr["number"], "pr_title": pr["title"], "pr_url": pr["url"]})
        except (RuntimeError, KeyError, ValueError) as e:
            lines.append(report_line(label, "every workflow", "not read", str(e)[:200] if not private else "the API failed"))
    write_output("plan", json.dumps(plan, separators=(",", ":")))
    write_summary(head + "\n" + ("\n".join(lines) if lines else "Every default branch read is green, or red before any merge seen here."))
    return 0


def ensure_label(repo, name):
    have = {l["name"] for l in api(f"repos/{repo}/labels?per_page=100")}
    if name in have:
        return
    spec = next((l for l in autonomy.read_yaml(os.path.join(HERE, "..", "labels.yml")) if l.get("name") == name), {})
    gh("label", "create", name, "--repo", repo, "--color", spec.get("color", "B60205"), "--description", spec.get("description", ""))


def act():
    item = json.loads(os.environ["ITEM"])
    repo = item["repo"]
    if (os.environ.get("DX_AUTOPILOT", "") or "").strip().lower() == "off":
        print("Nothing is done: the organisation's DX_AUTOPILOT is off.")
        return 0
    if item["kind"] == "rerun":
        gh("api", "-X", "POST", f"repos/{repo}/actions/runs/{item['run_id']}/rerun-failed-jobs")
        print("The failed jobs run again; the next sweep reads their verdict.")
        return 0
    # Read again: nothing changed since the scan?
    run = api(f"repos/{repo}/actions/runs/{item['run_id']}")
    if run.get("status") != "completed" or run.get("conclusion") not in RED or int(run.get("run_attempt") or 1) < 2:
        print("The run changed since the scan; the next sweep reads it again.")
        return 0
    pr = api(f"repos/{repo}/pulls/{item['pr']}")
    if "reverted" in [l["name"] for l in pr.get("labels") or []] or issue_for(repo, item["sha"]):
        print("Already reverted.")
        return 0
    for name in ("revert", "reverted"):
        ensure_label(repo, name)
    with tempfile.TemporaryDirectory() as tmp:
        body = os.path.join(tmp, "issue.md")
        with open(body, "w", encoding="utf-8") as fh:
            fh.write(issue_body(item))
        url = gh("issue", "create", "--repo", repo, "--title", issue_title(item), "--body-file", body).strip()
        issue = url.rsplit("/", 1)[-1]
        try:
            gh("api", "-X", "PATCH", f"repos/{repo}/issues/{issue}", "-f", "type=Bug")
        except RuntimeError as e:
            print(f"::warning::The issue's Type was not set: {str(e)[:200]}")
        work = os.path.join(tmp, "repo")
        auth = base64.b64encode(f"x-access-token:{os.environ['GH_TOKEN']}".encode()).decode()
        env = dict(os.environ, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                   GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {auth}", GIT_TERMINAL_PROMPT="0")
        git = lambda *a, check=True: subprocess.run(["git", "-C", work] + list(a), env=env, capture_output=True, text=True, check=check)
        subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--branch", item["default"], f"https://github.com/{repo}", work],
                       env=env, capture_output=True, text=True, check=True)
        git("config", "user.name", BOT)
        git("config", "user.email", BOT_EMAIL)
        parents = len(api(f"repos/{repo}/commits/{item['sha']}").get("parents") or [])
        name = branch(issue, item["pr_title"])
        git("switch", "-q", "-c", name)
        mainline = ["-m", "1"] if parents > 1 else []
        if git("revert", "--no-edit", "--no-commit", *mainline, item["sha"], check=False).returncode != 0:
            git("revert", "--abort", check=False)
            gh("issue", "comment", issue, "--repo", repo, "--body", conflict_comment(item))
            print("The merge does not revert cleanly; the issue says so.")
            return 0
        title = revert_title(item["pr_title"])
        git("commit", "-q", "-m", title, "-m", f"This reverts commit {item['sha']} (#{item['pr']}): the default branch went red after it merged.")
        git("push", "-q", "origin", f"HEAD:refs/heads/{name}")
        pbody = os.path.join(tmp, "pr.md")
        with open(pbody, "w", encoding="utf-8") as fh:
            fh.write(pr_body(item, issue))
        gh("pr", "create", "--repo", repo, "--base", item["default"], "--head", name, "--title", title, "--body-file", pbody, "--label", "revert")
    gh("pr", "edit", str(item["pr"]), "--repo", repo, "--add-label", "reverted")
    # The cause is the original issue's: it opens again for the autopilot or a person.
    try:
        closed = json.loads(gh("pr", "view", str(item["pr"]), "--repo", repo, "--json", "closingIssuesReferences"))
        for ref in closed.get("closingIssuesReferences") or []:
            n = str(ref["number"])
            gh("issue", "reopen", n, "--repo", repo, "--comment", f"Reopened: #{item['pr']} is reverted (#{issue}), the default branch went red after it merged.\n\n{AI_LINE}")
    except RuntimeError as e:
        print(f"::warning::The original issue was not reopened: {str(e)[:200]}")
    print(f"The revert is open; it closes #{issue}.")
    return 0


# --- the self-test ----------------------------------------------------------

def self_test():
    failed = 0

    # C5: no test reaches the network; a call to gh fails the run.
    def offline(*args, **kwargs):
        raise AssertionError(f"the self-test called gh {' '.join(args[:2])}")
    globals()["gh"] = offline

    def check(name, got, want):
        nonlocal failed
        if got == want:
            print(f"ok   {name}")
        else:
            print(f"FAIL {name}: got {got!r}, want {want!r}")
            failed = 1

    org = autonomy.load(os.path.join(HERE, "..", "policy", "autonomy.yml"))
    pol = autonomy.merge(org, {})

    def run(i, concl, attempt=1, status="completed"):
        return {"id": i, "status": status, "conclusion": concl, "run_attempt": attempt, "head_sha": f"sha{i}",
                "html_url": f"https://github.com/DiluxOne/x/actions/runs/{i}"}

    pr = {"number": 12, "title": "fix(sync): retry once", "url": "https://github.com/DiluxOne/x/pull/12",
          "head_sha": "head12", "head_ref": "fix/9-retry", "labels": []}
    checks = {"checks / PHP 8.3": "success", "checks / PHPCS": "success"}

    # Where the red began.
    check("pick: green is healthy", pick([run(3, "success"), run(2, "failure")])[0], "healthy")
    state, r, _ = pick([run(5, "failure"), run(4, "failure"), run(3, "success")])
    check("pick: the red began on the oldest failure after a green run", (state, r["id"]), ("red", 4))
    check("pick: a run still going is not read", pick([run(6, None, status="in_progress"), run(5, "failure"), run(4, "success")])[1]["id"], 5)
    check("pick: a cancelled run is skipped", pick([run(6, "cancelled"), run(5, "failure"), run(4, "success")])[1]["id"], 5)
    check("pick: red on every run read is left to a person", pick([run(5, "failure"), run(4, "failure")])[:2], ("none", None))
    check("pick: green on a re-run asks whether it was flaky", pick([run(5, "success", 2), run(4, "success")])[0], "flaky?")

    # C1: a green pull request, red after its merge, red again on the re-run.
    first = run(4, "failure", 1)
    check("C1: the first red is re-run once, not reverted", assess(first, pr, ["checks / PHP 8.3"], checks)[0], "rerun")
    again = run(4, "failure", 2)
    check("C1: red again on the re-run: reverted", assess(again, pr, ["checks / PHP 8.3"], checks)[0], "revert")
    item = {"repo": "DiluxOne/x", "sha": "abc123", "run_url": again["html_url"], "workflow": "Checks", "failed": ["checks / PHP 8.3"],
            "pr": 12, "pr_title": pr["title"], "pr_url": pr["url"], "default": "main"}
    ib = issue_body(item)
    check("C1: the issue links the merge", "https://github.com/DiluxOne/x/commit/abc123" in ib, True)
    check("C1: the issue links the failing run", again["html_url"] in ib, True)
    check("C1: the issue links the original pull request", pr["url"] in ib, True)
    pb = pr_body(item, 40)
    check("C1: the revert closes the new issue", "Closes #40." in pb, True)
    check("C1: the revert links the failing run", again["html_url"] in pb, True)
    check("C1: the revert's description has What changes and Why", ("## 📝 What changes" in pb, "## 💡 Why" in pb), (True, True))
    check("C1: the revert's title", revert_title(pr["title"]), "revert: fix(sync): retry once")
    check("C1: a long title stays within 72", len(revert_title("feat(x): " + "a" * 200)), 72)
    check("C1: the revert's branch", branch(40, pr["title"]), "revert/40-fix-sync-retry-once")
    check("C1: the branch passes the conventions", bool(re.match(r"^revert/[a-z0-9][a-z0-9._-]*$", branch(40, "Ünïcode: déjà vu!"))), True)
    wf = autonomy.read_yaml(os.path.join(HERE, "..", ".github", "workflows", "revert-on-red.yml"))
    cron = ((wf.get("on") or wf.get(True) or {}).get("schedule") or [{}])[0].get("cron", "")
    m = re.match(r"^\*/(\d+) \* \* \* \*$", cron)
    check("C1: the sweep runs often enough to revert within the hour (every 20 minutes or less)", bool(m) and int(m.group(1)) <= 20, True)

    # Nothing to revert.
    check("left alone: not a pull request's merge", assess(again, None, ["a"], {})[0], "none")
    check("left alone: already reverted (label)", assess(again, {**pr, "labels": ["reverted"]}, ["checks / PHP 8.3"], checks)[0], "none")
    check("left alone: already reverted (its issue)", assess(again, pr, ["checks / PHP 8.3"], checks, already=True)[0], "none")
    check("left alone: a revert's own merge, never reverted in turn", assess(again, {**pr, "head_ref": "revert/40-x", "title": "revert: x"}, ["checks / PHP 8.3"], checks)[0], "none")
    check("left alone: it was red on the pull request too", assess(again, pr, ["checks / PHP 8.3"], {"checks / PHP 8.3": "failure"})[0], "none")
    check("left alone: the failed job never ran on the pull request", assess(again, pr, ["deploy / dev build"], checks)[0], "none")
    check("left alone: no failed job named", assess(again, pr, [], checks)[0], "none")

    # C2: failed once, passed on the re-run.
    state, r, _ = pick([run(4, "success", 2), run(3, "success")])
    check("C2: a run green on its re-run is flaky when its first attempt failed", (state, flaky("failure")), ("flaky?", True))
    check("C2: not flaky when the first attempt passed too", flaky("success"), False)
    line = report_line("DiluxOne/x", "Checks", "flaky", "it failed, then passed when re-run; nothing is reverted", r["html_url"])
    check("C2: the run says it was flaky, and nothing is reverted", ("flaky" in line, "nothing is reverted" in line), (True, True))

    # C3: DX_AUTOPILOT=off.
    check("C3: DX_AUTOPILOT=off stops it, and says why", stopped("off", pol), "the organisation's DX_AUTOPILOT is off")
    check("C3: so does the autopilot off in a repository's policy", stopped("", autonomy.merge(org, {"autopilot": False})), "the autopilot is off in the policy")
    check("C3: on otherwise", stopped("", pol), None)
    with tempfile.TemporaryDirectory() as tmp:
        out, summary = os.path.join(tmp, "out"), os.path.join(tmp, "summary")
        saved = {k: os.environ.get(k) for k in ("DX_AUTOPILOT", "GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY")}
        os.environ.update(DX_AUTOPILOT="off", GITHUB_OUTPUT=out, GITHUB_STEP_SUMMARY=summary)
        try:
            scan()
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        check("C3: the sweep plans nothing", open(out, encoding="utf-8").read().strip(), "plan=[]")
        check("C3: and its run says why", "Nothing is re-run or reverted: the organisation's DX_AUTOPILOT is off." in open(summary, encoding="utf-8").read(), True)

    # C4: the merge, within the platform lane only.
    def merge(repository="DiluxOne/.github", files=("README.md",), risk="low", complexity="low", blocking="false", ok="true", author=BOT, var="", p=pol):
        return decide(p, repository, list(files), risk, complexity, blocking, ok, author, var)
    check("C4: within the platform lane, it merges on its own", merge()[0], True)
    check("C4: a repository outside the lane waits for a person", merge(repository="DiluxOne/diluxone-offload-wordpress")[0], False)
    check("C4: a protected path waits for a person", merge(files=("scripts/revert.py",))[0], False)
    check("C4: risk above the lane's waits", merge(risk="high")[0], False)
    check("C4: complexity above the lane's waits", merge(complexity="high")[0], False)
    check("C4: a blocking review waits", merge(blocking="true")[0], False)
    check("C4: an untrue description waits", merge(ok="false")[0], False)
    check("C4: not dilux-bot's: a person merges", merge(author="someone")[0], False)
    check("C4: DX_AUTOPILOT=off: a person merges", merge(var="off")[0], False)
    check("C4: the lane off in the repository: a person merges", merge(p=autonomy.merge(org, {"lanes": {"platform": {"enabled": False}}}))[0], False)
    why = merge(repository="DiluxOne/diluxone-offload-wordpress")[1]
    wc = wait_comment(why, "https://github.com/DiluxOne/diluxone-offload-wordpress/pull/41")
    check("C4: its issue shows the action and its URL", "Approve and merge https://github.com/DiluxOne/diluxone-offload-wordpress/pull/41" in wc, True)
    check("C4: and why it waits", why in wc, True)
    check("C4: a revert that does not apply says who does what", f"Revert #12 by hand: {pr['url']}" in conflict_comment(item), True)

    # The workflows that apply it.
    am = open(os.path.join(HERE, "..", ".github", "workflows", "auto-merge.yml"), encoding="utf-8").read()
    check("auto-merge.yml decides a revert pull request with this script", "scripts/revert.py\" decide" in am, True)
    check("auto-merge.yml posts the wait comment on the revert's issue", "revert.py\" wait-comment" in am, True)
    check("the labels exist in labels.yml", {"revert", "reverted"} <= {l.get("name") for l in autonomy.read_yaml(os.path.join(HERE, "..", "labels.yml"))}, True)

    if not failed:
        print("all tests passed")
    return failed


def main(argv):
    mode = argv[0] if argv else ""
    if mode == "--test":
        return self_test()
    if mode == "scan":
        return scan()
    if mode == "act":
        return act()
    if mode == "decide":
        files = [l.strip() for l in open(os.environ["FILES"], encoding="utf-8") if l.strip()] if os.environ.get("FILES") else []
        ok, why = decide(autonomy.policy_in_force(), os.environ.get("GITHUB_REPOSITORY", ""), files, os.environ.get("RISK", ""),
                         os.environ.get("COMPLEXITY", ""), os.environ.get("BLOCKING", ""), os.environ.get("DESCRIPTION_OK", ""),
                         os.environ.get("AUTHOR", ""), os.environ.get("DX_AUTOPILOT", ""))
        print(why)
        return 0 if ok else 1
    if mode == "wait-comment":
        print(wait_comment(os.environ.get("WHY", "").strip().rstrip("."), os.environ["PR_URL"]))
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
