#!/usr/bin/env python3
"""The autonomy policy (policy/autonomy.yml): what may proceed without a person.

  autonomy.py policy        print the policy in force as JSON: the
                            organisation's, made stricter by a repository's own
                            file, never looser
  autonomy.py lane-accept   say whether an issue is accepted by a lane; exit 0
                            when it is, 1 when not (the issue gate calls it)
  autonomy.py --test        self-test

Environment:
  ORG_AUTONOMY     the organisation's policy (default: policy/autonomy.yml
                   next to this script)
  REPO_AUTONOMY    a repository's .github/autonomy.yml from its base branch
                   (missing or empty: none)
  DX_AUTOPILOT     the organisation variable; "off" stops every lane
  For lane-accept:
  LANE_ISSUE       a file holding the issue as the issue gate reads it
                   (GraphQL: number, author, body, labels, label events)
  GITHUB_REPOSITORY  owner/name of the repository the issue is in
  LANE_RUN         a file holding the workflow run named in the issue; read
                   from the API with gh when unset
"""
import copy
import fnmatch
import json
import os
import re
import subprocess
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
LEVELS = ["none", "low", "medium", "high"]
MARKER = re.compile(r"<!--\s*dx-lane:\s*([a-z0-9-]+)\s+run:\s*(https://github\.com/([^/\s]+)/([^/\s]+)/actions/runs/(\d+))\s*-->")


def warn(msg):
    print(f"::warning::{msg}", file=sys.stderr)


def load(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def stricter_level(a, b):
    """The lower of two levels; an unknown one counts as none."""
    ia = LEVELS.index(a) if a in LEVELS else 0
    ib = LEVELS.index(b) if b in LEVELS else 0
    return LEVELS[min(ia, ib)]


def merge(org, repo):
    """The organisation's policy, made stricter by a repository's: never looser."""
    out = copy.deepcopy(org)
    out.setdefault("lanes", {})
    out["autopilot"] = bool(org.get("autopilot", False)) and repo.get("autopilot", True) is not False
    if repo.get("autopilot") is True and not org.get("autopilot", False):
        warn("autopilot: the organisation has it off; a repository cannot turn it on. Ignored.")
    extra = [p for p in (repo.get("constitution") or []) if isinstance(p, str)]
    out["constitution"] = list(org.get("constitution") or []) + [p for p in extra if p not in (org.get("constitution") or [])]
    for name, mine in (repo.get("lanes") or {}).items():
        lane = out["lanes"].get(name)
        if lane is None:
            warn(f"lanes.{name}: a repository cannot add a lane; ignored.")
            continue
        mine = mine or {}
        if mine.get("enabled") is False:
            lane["enabled"] = False
        if mine.get("accept") == "human":
            lane["accept"] = "human"
        elif "accept" in mine and mine.get("accept") != lane.get("accept"):
            warn(f"lanes.{name}.accept: a repository can only make a lane human; ignored.")
        if "repositories" in mine:
            theirs = set(mine.get("repositories") or [])
            ours = lane.get("repositories") or []
            lane["repositories"] = sorted(theirs) if "*" in ours else [r for r in ours if r in theirs]
        for key in ("max-risk", "max-complexity"):
            want = (mine.get("merge") or {}).get(key)
            if want is not None:
                have = (lane.get("merge") or {}).get(key, "none")
                lane.setdefault("merge", {})[key] = stricter_level(have, want)
                if stricter_level(have, want) != want:
                    warn(f"lanes.{name}.merge.{key}: a repository can only lower it; kept {have}.")
        for key in mine:
            if key not in ("enabled", "accept", "repositories", "merge"):
                warn(f"lanes.{name}.{key}: a repository cannot set it; ignored.")
    for name, lane in out["lanes"].items():
        lane.setdefault("enabled", True)
    return out


def last_label_event(issue, label):
    events = [e for e in ((issue.get("timelineItems") or {}).get("nodes") or []) if (e.get("label") or {}).get("name") == label]
    return events[-1] if events else None


def lane_accepts(policy, issue, run, repository, autopilot_var):
    """(True, why) when a lane accepts the issue; (False, why) otherwise. Pure."""
    if (autopilot_var or "").strip().lower() == "off":
        return False, "the organisation's DX_AUTOPILOT is off"
    if not policy.get("autopilot", False):
        return False, "the autopilot is off in the policy"
    labels = [n.get("name") for n in ((issue.get("labels") or {}).get("nodes") or [])]
    lanes = [l[len("lane:"):] for l in labels if l and l.startswith("lane:")]
    if len(lanes) != 1:
        return False, "the issue needs exactly one lane:<name> label" if not lanes else "the issue carries more than one lane"
    name = lanes[0]
    lane = (policy.get("lanes") or {}).get(name)
    if lane is None:
        return False, f"no lane named {name} in the policy"
    if not lane.get("enabled", True):
        return False, f"the lane {name} is off"
    if lane.get("accept") != "policy":
        return False, f"the lane {name} needs a person to accept"
    repo_name = repository.split("/", 1)[-1]
    if "*" not in (lane.get("repositories") or []) and repo_name not in (lane.get("repositories") or []):
        return False, f"the lane {name} does not cover {repo_name}"
    origin = lane.get("origin") or {}
    app = origin.get("app", "")
    bot_logins = {app, f"{app}[bot]"}
    event = last_label_event(issue, f"lane:{name}")
    if not event or event.get("__typename") != "LabeledEvent" or (event.get("actor") or {}).get("login") not in bot_logins:
        return False, f"the last to add lane:{name} was not {app}"
    if ((issue.get("author") or {}).get("login")) not in bot_logins:
        return False, f"the issue was not opened by {app}"
    m = MARKER.search(issue.get("body") or "")
    if not m or m.group(1) != name:
        return False, "the issue does not name the run that opened it"
    owner, repo, run_id = m.group(3), m.group(4), m.group(5)
    if f"{owner}/{repo}".lower() != repository.lower():
        return False, "the run named is in another repository"
    if not run or str(run.get("id")) != run_id:
        return False, "the run named could not be read"
    paths = [run.get("path") or ""] + [w.get("path") or "" for w in (run.get("referenced_workflows") or [])]
    names = {os.path.basename(p.split("@", 1)[0]) for p in paths if p}
    allowed = set(origin.get("workflows") or [])
    if not names & allowed:
        return False, f"the run's workflows ({', '.join(sorted(names)) or 'none'}) are not the lane's ({', '.join(sorted(allowed))})"
    return True, f"accepted by policy: lane {name}, opened by run {run_id}"


def touches_constitution(policy, files):
    pats = policy.get("constitution") or []
    return [f for f in files if any(fnmatch.fnmatch(f, p) for p in pats)]


def read_run(issue, repository):
    m = MARKER.search(issue.get("body") or "")
    if not m:
        return None
    if os.environ.get("LANE_RUN"):
        return load_json(os.environ["LANE_RUN"])
    try:
        out = subprocess.run(["gh", "api", f"repos/{repository}/actions/runs/{m.group(5)}"],
                             capture_output=True, text=True, check=True).stdout
        return json.loads(out)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def policy_in_force():
    org = load(os.environ.get("ORG_AUTONOMY") or os.path.join(HERE, "..", "policy", "autonomy.yml"))
    return merge(org, load(os.environ.get("REPO_AUTONOMY")))


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        if got == want:
            print(f"ok   {name}")
        else:
            print(f"FAIL {name}: got {got!r}, want {want!r}")
            failed = 1

    org = load(os.path.join(HERE, "..", "policy", "autonomy.yml"))
    check("the organisation's policy has the four lanes", sorted(org.get("lanes", {})), ["bugfix-reproduced", "human-issue", "platform", "release"])
    check("a release is never accepted by policy", org["lanes"]["release"]["accept"], "human")

    # The golden rule: every protected path is high risk, so it never merges on its own.
    default = load(os.path.join(HERE, "..", "policy", "review-policy.default.yml"))
    here = load(os.path.join(HERE, "..", ".github", "review-policy.yml"))
    high = list(default.get("high-risk") or []) + list(here.get("high-risk") or [])
    for pat in org.get("constitution") or []:
        probe = pat.replace("**", "x/y").replace("*", "x")
        check(f"protected path {pat} is high risk", any(fnmatch.fnmatch(probe, h) for h in high), True)

    m = merge(org, {"lanes": {"platform": {"enabled": False}}})
    check("a repository switches a lane off", m["lanes"]["platform"]["enabled"], False)
    m = merge(org, {"lanes": {"platform": {"merge": {"max-risk": "high"}}}})
    check("a repository cannot raise what a lane merges", m["lanes"]["platform"]["merge"]["max-risk"], "medium")
    m = merge(org, {"lanes": {"platform": {"merge": {"max-risk": "low"}}}})
    check("a repository lowers what a lane merges", m["lanes"]["platform"]["merge"]["max-risk"], "low")
    m = merge(org, {"lanes": {"human-issue": {"accept": "policy"}}})
    check("a repository cannot make a lane accept by policy", m["lanes"]["human-issue"]["accept"], "human")
    m = merge(org, {"lanes": {"platform": {"accept": "human"}}})
    check("a repository makes a lane human", m["lanes"]["platform"]["accept"], "human")
    m = merge(org, {"lanes": {"mine": {"accept": "policy"}}})
    check("a repository cannot add a lane", "mine" in m["lanes"], False)
    m = merge(org, {"lanes": {"bugfix-reproduced": {"repositories": ["a", "b"]}}})
    check("a repository narrows a lane's repositories", m["lanes"]["bugfix-reproduced"]["repositories"], ["a", "b"])
    m = merge(org, {"lanes": {"platform": {"repositories": [".github", "other"]}}})
    check("a repository cannot widen a lane's repositories", m["lanes"]["platform"]["repositories"], [".github"])
    m = merge(org, {"autopilot": False})
    check("a repository turns the autopilot off", m["autopilot"], False)
    m = merge({**org, "autopilot": False}, {"autopilot": True})
    check("a repository cannot turn it on", m["autopilot"], False)
    m = merge(org, {"constitution": ["docs/rules.md"]})
    check("a repository adds a protected path", "docs/rules.md" in m["constitution"], True)
    check("protected paths are found", touches_constitution(merge(org, {}), ["README.md", "policy/autonomy.yml", ".github/workflows/x.yml"]), ["policy/autonomy.yml", ".github/workflows/x.yml"])

    repo = "DiluxOne/.github"
    url = f"https://github.com/{repo}/actions/runs/42"

    def issue(labels=("lane:platform",), actor="dilux-bot", author="dilux-bot", body=None, typ="LabeledEvent"):
        return {
            "number": 7,
            "author": {"login": author},
            "body": body if body is not None else f"A build failed.\n\n<!-- dx-lane: platform run: {url} -->",
            "labels": {"nodes": [{"name": n} for n in labels]},
            "timelineItems": {"nodes": [{"__typename": typ, "label": {"name": "lane:platform"}, "actor": {"__typename": "Bot", "login": actor}}]},
        }

    run = {"id": 42, "path": ".github/workflows/runner-image.yml", "referenced_workflows": []}
    pol = merge(org, {})

    def accepted(i=None, r=run, p=pol, repository=repo, var=""):
        return lane_accepts(p, i or issue(), r, repository, var)[0]

    check("accepts: the lane's App opened it, from the lane's workflow", accepted(), True)
    check("refuses: DX_AUTOPILOT is off", accepted(var="off"), False)
    check("refuses: the autopilot is off in the policy", accepted(p=merge(org, {"autopilot": False})), False)
    check("refuses: the lane is off for the repository", accepted(p=merge(org, {"lanes": {"platform": {"enabled": False}}})), False)
    check("refuses: a person added the lane label", accepted(issue(actor="soydiloreto")), False)
    check("refuses: another bot added it", accepted(issue(actor="dependabot[bot]")), False)
    check("refuses: a person opened the issue", accepted(issue(author="someone")), False)
    check("refuses: no run named", accepted(issue(body="text only")), False)
    check("refuses: the run is in another repository", accepted(issue(body=f"<!-- dx-lane: platform run: https://github.com/x/y/actions/runs/42 -->")), False)
    check("refuses: the run is another workflow", accepted(r={"id": 42, "path": ".github/workflows/other.yml"}), False)
    check("refuses: the run could not be read", accepted(r=None), False)
    check("refuses: the lane does not cover the repository", accepted(repository="DiluxOne/diluxone-offload-wordpress", i=issue(body="<!-- dx-lane: platform run: https://github.com/DiluxOne/diluxone-offload-wordpress/actions/runs/42 -->")), False)
    check("refuses: a lane that needs a person", accepted(issue(labels=("lane:human-issue",))), False)
    check("refuses: two lanes", accepted(issue(labels=("lane:platform", "lane:release"))), False)
    rr = {"id": 42, "path": ".github/workflows/issues.yml", "referenced_workflows": [{"path": "DiluxOne/.github/.github/workflows/issue-repro.yml@refs/tags/v5"}]}
    bug = issue(labels=("lane:bugfix-reproduced",), body="<!-- dx-lane: bugfix-reproduced run: https://github.com/DiluxOne/x/actions/runs/42 -->")
    bug["timelineItems"]["nodes"][0]["label"]["name"] = "lane:bugfix-reproduced"
    check("accepts: a reproduction through a repository's caller", lane_accepts(pol, bug, rr, "DiluxOne/x", "")[0], True)

    if not failed:
        print("all tests passed")
    return failed


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "--test":
        return self_test()
    if mode == "policy":
        print(json.dumps(policy_in_force(), indent=2))
        return 0
    if mode == "lane-accept":
        issue = load_json(os.environ["LANE_ISSUE"])
        repository = os.environ["GITHUB_REPOSITORY"]
        ok, why = lane_accepts(policy_in_force(), issue, read_run(issue, repository), repository, os.environ.get("DX_AUTOPILOT", ""))
        print(why)
        return 0 if ok else 1
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main())
