#!/usr/bin/env python3
"""The autonomy policy (policy/autonomy.yml): what may proceed without a person.

  autonomy.py policy        print the policy in force as JSON: the
                            organisation's, made stricter by a repository's own
                            file, never looser
  autonomy.py lane-accept   say whether an issue is accepted by a lane; exit 0
                            when it is, 1 when not (the issue gate, the
                            autopilot and the reproduction call it)
  autonomy.py lane-open NAME
                            say whether the lane NAME may accept an issue of
                            this repository now, before one is opened; exit
                            0 when it may (the reproduction asks it)
  autonomy.py --test        self-test

Environment:
  ORG_AUTONOMY     the organisation's policy (default: policy/autonomy.yml
                   next to this script)
  REPO_AUTONOMY    a repository's .github/autonomy.yml from its base branch
                   (missing or empty: none)
  DX_AUTOPILOT     the organisation variable; "off" stops every lane
  For lane-accept:
  LANE_ISSUE       a file holding the issue as the issue gate reads it
                   (GraphQL: number, author, body, labels, label events);
                   when unset, issue NUMBER is read from GitHub with gh
  GITHUB_REPOSITORY  owner/name of the repository the issue is in
  LANE_RUN         a file holding the workflow run named in the issue; read
                   from the API with gh when unset
"""
import copy
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LEVELS = ["none", "low", "medium", "high"]
CENTRAL = "DiluxOne/.github"
MARKER = re.compile(r"<!--\s*dx-lane:\s*([a-z0-9-]+)\s+run:\s*(https://github\.com/([^/\s]+)/([^/\s]+)/actions/runs/(\d+))\s*-->")


def warn(msg):
    print(f"::warning::{msg}", file=sys.stderr)


def read_yaml(path):
    """yq where it is (the runners), PyYAML otherwise (a contributor's machine),
    as scripts/policy.py does: a stock macOS has neither PyYAML nor GNU tools."""
    if not path or not os.path.exists(path):
        return {}
    if shutil.which("yq"):
        out = subprocess.run(["yq", "-o=json", ".", path], check=True, capture_output=True, text=True).stdout
        return json.loads(out or "{}") or {}
    try:
        import yaml
    except ImportError:
        sys.exit(f"{os.path.basename(sys.argv[0])} needs yq or PyYAML to read {path}")
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load(path):
    return read_yaml(path)


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


def lane_open(policy, name, repository, autopilot_var):
    """(True, why) when the lane `name` may accept an issue of `repository`
    now, before any issue exists: the autopilot is on (the policy, the
    repository's file, DX_AUTOPILOT), and the lane is on, accepts by policy
    and covers the repository. Pure. A workflow asks it before it opens a
    lane's issue; lane_accepts asks it again of the issue."""
    if (autopilot_var or "").strip().lower() == "off":
        return False, "the organisation's DX_AUTOPILOT is off"
    if not policy.get("autopilot", False):
        return False, "the autopilot is off in the policy"
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
    return True, f"the lane {name} is open in {repo_name}"


def lane_of(issue):
    """The lane an issue names with its labels: (name, None), or (None, why)
    when it names none or more than one."""
    labels = [n.get("name") for n in ((issue.get("labels") or {}).get("nodes") or [])]
    lanes = [l[len("lane:"):] for l in labels if l and l.startswith("lane:")]
    if len(lanes) != 1:
        return None, ("the issue needs exactly one lane:<name> label" if not lanes else "the issue carries more than one lane")
    return lanes[0], None


def lane_accepts(policy, issue, run, repository, autopilot_var):
    """(True, why) when a lane accepts the issue; (False, why) otherwise. Pure."""
    if (autopilot_var or "").strip().lower() == "off":
        return False, "the organisation's DX_AUTOPILOT is off"
    if not policy.get("autopilot", False):
        return False, "the autopilot is off in the policy"
    name, why = lane_of(issue)
    if name is None:
        return False, why
    ok, why = lane_open(policy, name, repository, autopilot_var)
    if not ok:
        return False, why
    lane = policy["lanes"][name]
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
    # The run's own workflow is in the issue's repository (checked above);
    # a workflow it calls counts only when it is the organisation's own,
    # from DiluxOne/.github.
    names = {os.path.basename(run.get("path") or "")}
    names |= {os.path.basename(p.split("@", 1)[0]) for p in (w.get("path") or "" for w in (run.get("referenced_workflows") or []))
              if p.startswith(f"{CENTRAL}/.github/workflows/")}
    names.discard("")
    allowed = set(origin.get("workflows") or [])
    if not names & allowed:
        return False, f"the run's workflows ({', '.join(sorted(names)) or 'none'}) are not the lane's ({', '.join(sorted(allowed))})"
    return True, f"accepted by policy: lane {name}, opened by run {run_id}"


# The issue as the issue gate reads it (scripts/issue-gate.sh): who opened
# it, its body, its labels and who added each, from GitHub's history.
ISSUE_QUERY = """query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      number
      body
      author { login }
      labels(first: 50) { nodes { name } }
      timelineItems(itemTypes: [LABELED_EVENT, UNLABELED_EVENT], last: 100) {
        nodes {
          __typename
          ... on LabeledEvent { label { name } actor { __typename login } }
          ... on UnlabeledEvent { label { name } actor { __typename login } }
        }
      }
    }
  }
}"""


def read_issue(repository, number):
    """The issue, read from GitHub with gh (GH_TOKEN), or None when it cannot be."""
    owner, name = repository.split("/", 1)
    try:
        out = subprocess.run(["gh", "api", "graphql", "-f", f"query={ISSUE_QUERY}", "-F", f"owner={owner}", "-F", f"name={name}",
                              "-F", f"number={number}"], capture_output=True, text=True, check=True).stdout
        return (((json.loads(out).get("data") or {}).get("repository") or {}).get("issue")) or None
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


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
    fake = {"id": 42, "path": ".github/workflows/issues.yml", "referenced_workflows": [{"path": "someone/else/.github/workflows/issue-repro.yml@main"}]}
    check("refuses: a called workflow of the same name from elsewhere", lane_accepts(pol, bug, fake, "DiluxOne/x", "")[0], False)

    # #84: the lane a reproduction hands a bug to, asked before its issue exists.
    check("lane-open: bugfix-reproduced is open everywhere by default", lane_open(pol, "bugfix-reproduced", "DiluxOne/x", "")[0], True)
    check("lane-open: not with DX_AUTOPILOT off", lane_open(pol, "bugfix-reproduced", "DiluxOne/x", "off")[0], False)
    check("lane-open: not when the repository switches the lane off", lane_open(merge(org, {"lanes": {"bugfix-reproduced": {"enabled": False}}}), "bugfix-reproduced", "DiluxOne/x", "")[0], False)
    check("lane-open: not when the repository makes it human", lane_open(merge(org, {"lanes": {"bugfix-reproduced": {"accept": "human"}}}), "bugfix-reproduced", "DiluxOne/x", "")[0], False)
    check("lane-open: not when the repository turns the autopilot off", lane_open(merge(org, {"autopilot": False}), "bugfix-reproduced", "DiluxOne/x", "")[0], False)
    check("lane-open: not outside the repositories it narrows to", lane_open(merge(org, {"lanes": {"bugfix-reproduced": {"repositories": ["y"]}}}), "bugfix-reproduced", "DiluxOne/x", "")[0], False)
    check("lane-open: never a lane a person accepts", lane_open(pol, "human-issue", "DiluxOne/x", "")[0], False)
    check("lane-open: never a lane that does not exist", lane_open(pol, "mine", "DiluxOne/x", "")[0], False)
    person = issue(labels=("lane:bugfix-reproduced",), author="reporter", body="<!-- dx-lane: bugfix-reproduced run: https://github.com/DiluxOne/x/actions/runs/42 -->")
    person["timelineItems"]["nodes"][0]["label"]["name"] = "lane:bugfix-reproduced"
    check("refuses: a reporter's own issue, even with the lane's label and marker", lane_accepts(pol, person, rr, "DiluxOne/x", "")[0], False)
    check("lane_of: one lane", lane_of(bug), ("bugfix-reproduced", None))
    check("lane_of: none", lane_of(issue(labels=("bug",)))[0], None)

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
    if mode == "lane-open":
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        ok, why = lane_open(policy_in_force(), name, os.environ["GITHUB_REPOSITORY"], os.environ.get("DX_AUTOPILOT", ""))
        print(why)
        return 0 if ok else 1
    if mode == "lane-accept":
        repository = os.environ["GITHUB_REPOSITORY"]
        issue = load_json(os.environ["LANE_ISSUE"]) if os.environ.get("LANE_ISSUE") else read_issue(repository, os.environ.get("NUMBER", ""))
        if not issue:
            print("the issue could not be read")
            return 1
        ok, why = lane_accepts(policy_in_force(), issue, read_run(issue, repository), repository, os.environ.get("DX_AUTOPILOT", ""))
        print(why)
        return 0 if ok else 1
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main())
