#!/usr/bin/env python3
"""The autonomy policy (policy/autonomy.yml): what may proceed without a person.

  autonomy.py policy        print the policy in force as JSON: the
                            organisation's, made stricter by a repository's own
                            file, never looser but up to a lane's ceiling
  autonomy.py check         hold the organisation's policy to its schema;
                            exit 1, with the reasons, when it does not
  autonomy.py lane-accept   say whether an issue is accepted by a lane; exit 0
                            when it is, 1 when not (the issue gate, the
                            autopilot and the reproduction call it)
  autonomy.py lane-open NAME
                            say whether the lane NAME may accept an issue of
                            this repository now, before one is opened; exit
                            0 when it may (the reproduction asks it)
  autonomy.py lane-announce what a lane's label on an issue means, as JSON
                            for issue-accepted.yml: {"act": "skip", "accept"
                            or "refuse", "comment": what to say on the issue}
  autonomy.py lane-merge    whether a sync lane's pull request (org-sync)
                            merges on its own: exit 0 when it does, 1 when a
                            person merges it, 2 when it is no sync lane's
                            (auto-merge.yml then decides it as any other)
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
  NUMBER           the issue, read from the API, when LANE_ISSUE is unset
  For a sync lane (org-sync, a lane whose origin has `runs`):
  LANE_SCOPE       "issue": the issue alone (lane-announce, when it is
                   labelled, before its pull request exists). Anything else
                   judges the pull request too, and refuses without it
  LANE_PR          a file holding the pull request ({number, author: {login},
                   headRefName, headRefOid, baseRefOid}); else PR,
                   PR_AUTHOR, HEAD_REF, HEAD_SHA and BASE_SHA
  LANE_CHANGE      a file holding what it changes ({files: [{status, path,
                   previous}], head: {path: text}, base: {path: text}});
                   read from the API when unset
  LANE_ORG         a file holding what DiluxOne/.github has at the commit
                   the issue names ({merged, repos.yml, agents-block.md,
                   templates: {name: text}}); read from the API when unset
  For lane-announce: LANE (the label added, lane:<name>) and POLICY_SHA (the
  commit of the policy read, for its link). For lane-merge: RISK,
  COMPLEXITY, BLOCKING, DESCRIPTION_OK (the review's outputs).
"""
import copy
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import org  # noqa: E402  the organisation, from org.yml (#191)
LEVELS = ["none", "low", "medium", "high"]
CENTRAL = org.CENTRAL
MARKER = re.compile(r"<!--\s*dx-lane:\s*([a-z0-9-]+)\s+run:\s*(https://github\.com/([^/\s]+)/([^/\s]+)/actions/runs/(\d+))\s*-->")
# What a run of scripts/sync-repos.py writes in the issue it opens (sync
# lanes): the lane, the kind of run, the commit of DiluxOne/.github it brings
# the repository in line with, and the run's fingerprint (fingerprint()).
SYNC_MARKER = re.compile(r"<!--\s*dx-lane:\s*([a-z0-9-]+)\s+sync:\s*([a-z-]+)\s+org:\s*([0-9a-f]{40})\s+files:\s*([0-9a-f]{64})\s*-->")
# A call of a shared workflow at a version tag, the only call a sync lane's
# caller may make in a job it changes.
SHARED_USES = re.compile(r"DiluxOne/\.github/\.github/workflows/[\w.-]+\.ya?ml@v\d+")


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


def parse_text(text):
    """A YAML text as data, through yq or PyYAML like read_yaml(); a text
    that does not parse raises ValueError."""
    if shutil.which("yq"):
        out = subprocess.run(["yq", "-o=json", ".", "-"], input=text, capture_output=True, text=True)
        if out.returncode != 0:
            raise ValueError(f"not YAML: {out.stderr.strip()[:200]}")
        return json.loads(out.stdout or "null")
    import yaml
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"not YAML: {exc}") from exc


def stricter_level(a, b):
    """The lower of two levels; an unknown one counts as none."""
    ia = LEVELS.index(a) if a in LEVELS else 0
    ib = LEVELS.index(b) if b in LEVELS else 0
    return LEVELS[min(ia, ib)]


def merge(org, repo):
    """The organisation's policy, made stricter by a repository's: never
    looser, but what a lane merges may rise up to the lane's `ceiling`."""
    out = copy.deepcopy(org)
    out.setdefault("lanes", {})
    out["autopilot"] = bool(org.get("autopilot", False)) and repo.get("autopilot", True) is not False
    if repo.get("autopilot") is True and not org.get("autopilot", False):
        warn("autopilot: the organisation has it off; a repository cannot turn it on. Ignored.")
    extra = [p for p in (repo.get("constitution") or []) if isinstance(p, str)]
    out["constitution"] = list(org.get("constitution") or []) + [p for p in extra if p not in (org.get("constitution") or [])]
    # How the autopilot settles a choice (#247): `guided` asks a maintainer,
    # `full` decides and logs it. A repository may choose up to the
    # organisation's ceiling; guided is always allowed (it is stricter).
    org_mode = dict(org.get("autopilot-mode") or {"default": "guided", "ceiling": "guided"})
    want = repo.get("autopilot-mode")
    mode = org_mode.get("default", "guided")
    if want in MODES:
        if want == "guided" or org_mode.get("ceiling", mode) == "full":
            mode = want
        else:
            warn("autopilot-mode: the organisation's ceiling is guided; a repository cannot choose full. Kept guided.")
    out["autopilot-mode"] = {**org_mode, "mode": mode}
    # Labels whose issue a person always merges (#194): a repository adds to
    # them, never takes one away.
    more = [l for l in (repo.get("person-merges") or []) if isinstance(l, str) and l]
    out["person-merges"] = list(org.get("person-merges") or []) + [l for l in more if l not in (org.get("person-merges") or [])]
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
                # Up to the lane's ceiling; without one, the default is the most.
                ceiling = (lane.get("ceiling") or {}).get(key, have)
                most = ceiling if stricter_level(have, ceiling) == have else have
                got = stricter_level(want, most)
                lane.setdefault("merge", {})[key] = got
                if got != want:
                    warn(f"lanes.{name}.merge.{key}: a repository can raise it only up to the lane's ceiling ({most}); kept {got}.")
        for key in mine:
            if key not in ("enabled", "accept", "repositories", "merge"):
                warn(f"lanes.{name}.{key}: a repository cannot set it; ignored.")
    for name, lane in out["lanes"].items():
        lane.setdefault("enabled", True)
    return out


TOP_KEYS = {"autopilot", "autopilot-rounds", "autopilot-runs", "autopilot-mode", "constitution", "person-merges", "planned-release", "security-patch", "lanes"}
MODES = ("guided", "full")
LANE_KEYS = {"description", "accept", "type", "origin", "repositories", "evidence", "merge", "ceiling", "enabled"}


def problems(policy):
    """What keeps the organisation's policy from its schema; empty when it holds."""
    out = []
    if not isinstance(policy, dict):
        return ["the policy is not a mapping"]
    for key in sorted(set(policy) - TOP_KEYS):
        out.append(f"{key}: not a key of the policy")
    if not isinstance(policy.get("autopilot"), bool):
        out.append("autopilot: true or false")
    for key in ("autopilot-rounds", "autopilot-runs"):
        if key in policy and not (isinstance(policy[key], int) and not isinstance(policy[key], bool) and policy[key] > 0):
            out.append(f"{key}: a whole number above 0")
    constitution = policy.get("constitution")
    if not isinstance(constitution, list) or not constitution or not all(isinstance(p, str) and p for p in constitution):
        out.append("constitution: a list of paths")
    else:
        for path in ("policy/**", "rules/**"):
            if path not in constitution:
                out.append(f"constitution: {path} is always protected")
    am = policy.get("autopilot-mode", {"default": "guided", "ceiling": "guided"})
    if not isinstance(am, dict) or am.get("default") not in MODES or am.get("ceiling", am.get("default")) not in MODES:
        out.append("autopilot-mode: default and ceiling, each guided or full")
    elif am.get("default") == "full" and am.get("ceiling", "full") == "guided":
        out.append("autopilot-mode: a ceiling below the default")
    held = policy.get("person-merges", [])
    if not isinstance(held, list) or not all(isinstance(l, str) and l for l in held):
        out.append("person-merges: a list of labels")
    elif "security" not in held:
        out.append("person-merges: security is always there")
    if policy.get("planned-release", "confirm") not in ("auto", "confirm"):
        out.append("planned-release: auto or confirm")
    sp = policy.get("security-patch", {"veto-hours": 6})
    hrs = sp.get("veto-hours") if isinstance(sp, dict) else None
    if not isinstance(sp, dict) or set(sp) - {"veto-hours"} or isinstance(hrs, bool) or not isinstance(hrs, (int, float)) or not 0 < hrs <= 720:
        out.append("security-patch: veto-hours, a number of hours above 0 and at most 720")
    lanes = policy.get("lanes")
    if not isinstance(lanes, dict) or not lanes:
        return out + ["lanes: at least one"]
    for name, lane in lanes.items():
        if not isinstance(lane, dict):
            out.append(f"lanes.{name}: a mapping")
            continue
        for key in sorted(set(lane) - LANE_KEYS):
            out.append(f"lanes.{name}.{key}: not a key of a lane")
        if lane.get("accept") not in ("human", "policy"):
            out.append(f"lanes.{name}.accept: human or policy")
        if not isinstance(lane.get("description"), str) or not lane.get("description"):
            out.append(f"lanes.{name}.description: says what the lane covers")
        repos = lane.get("repositories")
        if not isinstance(repos, list) or not repos or not all(isinstance(r, str) and r for r in repos):
            out.append(f"lanes.{name}.repositories: a list of names, or [\"*\"]")
        if lane.get("accept") == "policy" and not isinstance(lane.get("origin"), dict):
            out.append(f"lanes.{name}.origin: a lane that accepts by policy names who opens its issues")
        for part in ("merge", "ceiling"):
            if part not in lane:
                if part == "merge":
                    out.append(f"lanes.{name}.merge: max-risk and max-complexity")
                continue
            caps = lane[part]
            if not isinstance(caps, dict) or set(caps) != {"max-risk", "max-complexity"}:
                out.append(f"lanes.{name}.{part}: max-risk and max-complexity")
                continue
            for key, level in caps.items():
                if level not in LEVELS:
                    out.append(f"lanes.{name}.{part}.{key}: one of {', '.join(LEVELS)}")
        merge_caps, ceiling = lane.get("merge") or {}, lane.get("ceiling")
        if isinstance(ceiling, dict) and isinstance(merge_caps, dict):
            for key in ("max-risk", "max-complexity"):
                have, most = merge_caps.get(key), ceiling.get(key)
                if have in LEVELS and most in LEVELS and LEVELS.index(have) > LEVELS.index(most):
                    out.append(f"lanes.{name}.ceiling.{key}: {most} is below the lane's merge ({have})")
    release = lanes.get("release")
    if isinstance(release, dict):
        if release.get("accept") != "human":
            out.append("lanes.release.accept: publishing is always a person's decision")
        if release.get("merge") != {"max-risk": "none", "max-complexity": "none"} or "ceiling" in release:
            out.append("lanes.release: never merges on its own, and has no ceiling")
    return out


def last_label_event(issue, label):
    events = [e for e in ((issue.get("timelineItems") or {}).get("nodes") or []) if (e.get("label") or {}).get("name") == label]
    return events[-1] if events else None


def login(name):
    """A login as both APIs give it: dilux-bot and dilux-bot[bot] are one."""
    name = (name or "").strip().lower()
    return name[: -len("[bot]")] if name.endswith("[bot]") else name


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
    when it names none or more than one. A sub-issue with no lane label is
    the delegated lane's (#189): its parent is what it is recognised by."""
    labels = [n.get("name") for n in ((issue.get("labels") or {}).get("nodes") or [])]
    lanes = [l[len("lane:"):] for l in labels if l and l.startswith("lane:")]
    if not lanes and issue.get("parent"):
        return DELEGATED, None
    if len(lanes) != 1:
        return None, ("the issue needs exactly one lane:<name> label" if not lanes else "the issue carries more than one lane")
    return lanes[0], None


def lane_accepts(policy, issue, run, repository, autopilot_var, sync=None):
    """(True, why) when a lane accepts the issue; (False, why) otherwise.
    Pure: what a sync lane reads (sync_accepts()) comes in `sync`."""
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
    if origin.get("runs"):
        return sync_accepts(name, lane, issue, repository, sync or {})
    if origin.get("parent"):
        return delegated_accepts(name, lane, issue, repository)
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


DELEGATED = "delegated"
MEMBERS = {"OWNER", "MEMBER"}


def delegated_accepts(name, lane, issue, repository):
    """(True, why) when the issue is a sub-issue the delegated lane accepts:
    its parent open, in the organisation, accepted by a person (the last
    `accepted` event a person's, the label still there); the sub-issue
    opened by a member or the lane's App, and not edited after it was
    linked. Pure: everything comes in `issue` (ISSUE_QUERY)."""
    parent = issue.get("parent") or {}
    if not parent:
        return False, "the issue is no sub-issue"
    where = ((parent.get("repository") or {}).get("nameWithOwner") or "")
    if where.split("/", 1)[0].lower() != repository.split("/", 1)[0].lower():
        return False, "its parent is outside the organisation"
    ref = f"{where}#{parent.get('number')}"
    if parent.get("state") != "OPEN":
        return False, f"its parent {ref} is not open"
    if "accepted" not in [n.get("name") for n in ((parent.get("labels") or {}).get("nodes") or [])]:
        return False, f"its parent {ref} is not accepted"
    event = last_label_event(parent, "accepted")
    if not event or event.get("__typename") != "LabeledEvent" or (event.get("actor") or {}).get("__typename") != "User":
        return False, f"its parent {ref} was not accepted by a person"
    app = (lane.get("origin") or {}).get("app", "")
    author = login((issue.get("author") or {}).get("login"))
    if issue.get("authorAssociation") not in MEMBERS and author != login(app):
        return False, "the sub-issue was not opened by a member of the organisation"
    linked = [e.get("createdAt") for e in ((issue.get("timelineItems") or {}).get("nodes") or []) if e.get("__typename") == "ParentIssueAddedEvent"]
    if not linked:
        return False, "its link to the parent could not be read"
    edited = issue.get("lastEditedAt")
    if edited and edited > linked[-1]:
        return False, "the sub-issue was edited after it was linked to its parent"
    return True, f"accepted by policy: lane {name}, a sub-issue of {ref}, which {(event.get('actor') or {}).get('login')} accepted"


# --- sync lanes (org-sync): what scripts/sync-repos.py opens ---------------
#
# A sync run is not a workflow run: a maintainer runs the script from their
# machine, signed in to gh as themselves, so there is no run to read from
# the API and its issue is not dilux-bot's. What stands in for the run, all
# read from GitHub, never from the issue's text alone:
#   - who: the issue's author is the lane's App or a person the lane names
#     (origin.people), and that same account added lane:<name> last;
#   - what: the issue's text is as the run wrote it (never edited), with the
#     run's marker: its kind (origin.runs), the commit of DiluxOne/.github
#     it brings the repository in line with, merged into main, and the run's
#     fingerprint, a SHA-256 over the repository, the kind, that commit and
#     each file it wrote with its own SHA-256 (fingerprint());
#   - its pull request: opened by the same account, from the branch the run
#     names for the issue, changing only the paths that kind of run writes
#     (added or modified, never removed or renamed), whose files at its head
#     give the same fingerprint. A push that changes any of them after the
#     run breaks it, and the issue waits for a person.
# The fingerprint is a hash, not a signature: anyone could compute it. It
# binds the issue to the exact files the run wrote; who wrote them is the
# author check. Someone the lane names could forge a run by hand, and could
# as well accept the issue: the lane gives nobody a power they lacked.


def fingerprint(repository, mode, org, files):
    """The run's fingerprint: what scripts/sync-repos.py writes in the issue
    and the pull request's files must give again. `files` is {path: text}."""
    data = {"repository": repository.lower(), "mode": mode, "org": org,
            "files": {p: hashlib.sha256(t.encode("utf-8")).hexdigest() for p, t in files.items()}}
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sync_marker(lane, repository, mode, org, files):
    """The marker a sync run writes in the issue it opens."""
    return f"<!-- dx-lane: {lane} sync: {mode} org: {org} files: {fingerprint(repository, mode, org, files)} -->"


def path_matches(path, pattern):
    """A glob, segment by segment: `*` never crosses a `/`."""
    a, b = path.split("/"), pattern.split("/")
    return len(a) == len(b) and all(fnmatch.fnmatchcase(x, y) for x, y in zip(a, b))


def scope_problem(change, patterns):
    """Why a pull request changes more than a sync run writes; None when it
    does not."""
    files = change.get("files") or []
    if not files:
        return "the pull request changes nothing"
    for f in files:
        if f.get("status") not in ("added", "modified"):
            return f"it has {f.get('path')} {f.get('status') or 'changed'}: a sync run only adds or modifies files"
        for p in (f.get("path"), f.get("previous")):
            if p and not any(path_matches(p, pat) for pat in patterns or []):
                return f"it changes {p}, outside the files this kind of sync run writes ({', '.join(patterns or [])})"
    return None


def sync_accepts(name, lane, issue, repository, sync):
    """A sync lane's verdict, as the comment above says. `sync` holds
    issue_only (judge the issue alone), pr (the pull request's facts),
    change() (what it changes) and org(sha) (DiluxOne/.github at sha)."""
    origin = lane.get("origin") or {}
    if repository.lower() == CENTRAL.lower():
        return False, f"the lane {name} never applies to {CENTRAL}, whose own changes a person accepts"
    app = origin.get("app", "")
    allowed = {login(app)} | {login(p) for p in origin.get("people") or []}
    allowed.discard("")
    author = login((issue.get("author") or {}).get("login"))
    if not author or author not in allowed:
        return False, f"the issue was not opened by {app} or a person the lane names"
    event = last_label_event(issue, f"lane:{name}")
    if not event or event.get("__typename") != "LabeledEvent" or login((event.get("actor") or {}).get("login")) != author:
        return False, f"the last to add lane:{name} was not whoever opened the issue"
    if "lastEditedAt" not in issue:
        return False, "the issue's edit history could not be read"
    if issue.get("lastEditedAt"):
        return False, "the issue's text was edited after the run opened it"
    want = lane.get("type")
    if want and (issue.get("issueType") or {}).get("name") != want:
        return False, f"the issue's Type is not {want}"
    m = SYNC_MARKER.search(issue.get("body") or "")
    if not m or m.group(1) != name:
        return False, "the issue does not carry a sync run's marker"
    mode, org, fp = m.group(2), m.group(3), m.group(4)
    runs = origin.get("runs") or {}
    if mode not in runs:
        return False, f"a {mode} run is not one of the lane's ({', '.join(sorted(runs))})"
    facts = sync["org"](org) if sync.get("org") else None
    if not facts or facts.get("merged") is not True:
        return False, f"{CENTRAL}@{org[:12]}, the change it names, is not merged into main (or could not be read)"
    what = f"lane {name}, a {mode} run of sync-repos.py by {author} bringing it in line with {CENTRAL}@{org[:12]}"
    if sync.get("issue_only"):
        return True, f"accepted by policy: {what}"
    pr = sync.get("pr")
    if not pr:
        return False, "the pull request was not read"
    if login((pr.get("author") or {}).get("login")) != author:
        return False, "the pull request was not opened by whoever opened the issue"
    branch = (runs[mode] or {}).get("branch", "").format(issue=issue.get("number"))
    if not branch or pr.get("headRefName") != branch:
        return False, f"its branch is not the run's ({branch or 'none named'})"
    change = sync["change"]() if sync.get("change") else None
    if not change:
        return False, "what the pull request changes could not be read"
    why = scope_problem(change, (runs[mode] or {}).get("paths"))
    if why:
        return False, why
    head = change.get("head") or {}
    files = {f["path"]: head.get(f["path"]) for f in change["files"]}
    if any(t is None for t in files.values()):
        return False, "its files at its head could not be read"
    if fingerprint(repository, mode, org, files) != fp:
        return False, "its files are not the ones the run wrote (they changed since, or it wrote others)"
    return True, f"accepted by policy: {what}"


def plain(value):
    """A value as a comparison reads it: booleans as YAML writes them, an
    expression without its ${{ }} and its spacing."""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = " ".join(str(value if value is not None else "").split())
    m = re.fullmatch(r"\$\{\{\s*(.*?)\s*\}\}", text)
    return m.group(1) if m else text


def jobs_of(data):
    jobs = (data or {}).get("jobs") if isinstance(data, dict) else None
    return jobs if isinstance(jobs, dict) else {}


def needs_of(job):
    needs = job.get("needs") or []
    return {needs} if isinstance(needs, str) else set(needs)


CALLER_KEYS = ("uses", "with", "needs", "if", "permissions", "secrets")


def job_vs_template(have, before, want, owned):
    """Why a caller's job, as a sync run changed it, is not its template's
    job (`want`); None when it is. The inputs the template says to fill in
    (`owned`) and the inputs it does not set are the repository's: they
    keep the values they had."""
    if plain(have.get("if", "")) != plain(want.get("if", "")):
        return f"runs if `{plain(have.get('if', '')) or 'always'}`, not the template's"
    if not needs_of(want) <= needs_of(have):
        return "does not wait for every job the template's waits for"
    tw, hw, bw = want.get("with") or {}, have.get("with") or {}, (before or {}).get("with") or {}
    for key, value in tw.items():
        if key in owned:
            if before is not None and key in bw and plain(hw.get(key)) != plain(bw[key]):
                return f"changes `{key}`, which is the repository's to fill in"
        elif key not in hw or plain(hw[key]) != plain(value):
            return f"passes `{key}` other than the template does"
    for key in set(hw) - set(tw):
        if key not in bw or plain(hw[key]) != plain(bw[key]):
            return f"changes `{key}`, an input the template does not set"
    dropped = sorted(set(bw) - set(hw))
    if dropped:
        return f"drops `{dropped[0]}`, an input the repository passed"
    for key in (set(have) | set(want)) - set(CALLER_KEYS):
        if have.get(key) != want.get(key) and (before is None or have.get(key) != before.get(key)):
            return f"sets `{key}` other than the template and the repository did"
    return None


def caller_problem(path, base_text, head_text, templates, owned):
    """(why, high): why a caller the pull request changes is more than a
    sync run of the callers writes, and whether that is a change of
    permissions or secrets (high risk); (None, False) when it is not.
    `templates` is {name: data} at the commit the issue names; `owned` is
    {template: [inputs]} from repos.yml there (`callers.repository-owned`)."""
    if base_text is None:
        return f"{path} is a new workflow: a sync run only changes callers that exist", False
    try:
        base, head = parse_text(base_text), parse_text(head_text)
    except ValueError:
        return f"{path} does not parse", False
    if not isinstance(base, dict) or not isinstance(head, dict):
        return f"{path} is not a workflow", False
    if {k: v for k, v in base.items() if k != "jobs"} != {k: v for k, v in head.items() if k != "jobs"}:
        return f"{path} changes more than its jobs (its triggers, permissions or settings)", False
    bj, hj = jobs_of(base), jobs_of(head)
    gone = sorted(set(bj) - set(hj))
    if gone:
        return f"{path} removes the job {gone[0]}", False
    for job in sorted(hj):
        have, before = hj[job], bj.get(job)
        if have == before:
            continue
        if not isinstance(have, dict) or (before is not None and not isinstance(before, dict)):
            return f"{path}: the job {job} is not a mapping", False
        uses = str(have.get("uses") or "")
        if not SHARED_USES.fullmatch(uses):
            return f"{path}: the job {job} calls `{uses or 'nothing'}`, not a shared workflow at a version tag", False
        found = [(t, jobs_of(d)[job]) for t, d in sorted(templates.items())
                 if isinstance(jobs_of(d).get(job), dict) and jobs_of(d)[job].get("uses") == uses]
        if not found:
            return f"{path}: the job {job} is no template's job (workflow-templates/ at the commit named)", False
        whys = [job_vs_template(have, before, want, set(owned.get(t) or [])) for t, want in found]
        if all(whys):
            return f"{path}: the job {job} {whys[0]}", False
        # A new job is a grant of its own, whatever it asks for.
        if before is None:
            return f"{path}: the job {job} is new, with the permissions and secrets it gets: high risk, a person merges it", True
        if have.get("permissions") != before.get("permissions") or have.get("secrets") != before.get("secrets"):
            return f"{path}: the job {job} changes its permissions or the secrets it passes: high risk, a person merges it", True
    return None, False


def sync_merge(policy, issue, repository, autopilot_var, sync, review):
    """(True, why) when a sync lane's pull request merges on its own; (False,
    why) when a person merges it. Pure: `sync` as sync_accepts() reads it,
    its org(sha, True) with the files too; `review` holds the review's
    risk, complexity, blocking and description_ok."""
    ok, why = lane_accepts(policy, issue, None, repository, autopilot_var, dict(sync, issue_only=False))
    if not ok:
        return False, why
    name = next(l[len("lane:"):] for l in (n.get("name") or "" for n in issue["labels"]["nodes"]) if l.startswith("lane:"))
    lane = policy["lanes"][name]
    if review.get("blocking") != "false":
        return False, "the review is blocking"
    if review.get("description_ok") != "true":
        return False, "the description does not match the code"
    caps = lane.get("merge") or {}
    for key, cap in (("risk", caps.get("max-risk", "none")), ("complexity", caps.get("max-complexity", "none"))):
        level = review.get(key) or ""
        if level not in LEVELS or cap not in LEVELS or level == "none" or LEVELS.index(level) > LEVELS.index(cap):
            return False, f"{key} {level or 'unknown'} is above the lane's {cap}"
    m = SYNC_MARKER.search(issue.get("body") or "")
    mode, org = m.group(2), m.group(3)
    facts = sync["org"](org, True) or {}
    change = sync["change"]()
    head, base = change.get("head") or {}, change.get("base") or {}
    now = facts.get("main") or {}
    try:
        conf = parse_text(facts.get("repos.yml")) if facts.get("repos.yml") is not None else None
        conf_now = parse_text(now.get("repos.yml")) if now.get("repos.yml") is not None else None
        templates = {n: parse_text(t) for n, t in (facts.get("templates") or {}).items()}
    except ValueError:
        return False, f"{CENTRAL}@{org[:12]} could not be read"
    if not isinstance(conf, dict) or not isinstance(conf_now, dict):
        return False, f"repos.yml at {CENTRAL}@{org[:12]} or at main could not be read"
    # A run from a commit main has since moved past would roll back what
    # changed after it: what it writes from must be the same at main now.
    if mode == "files":
        stale = conf.get("files") != conf_now.get("files") or facts.get("agents-block.md") != now.get("agents-block.md")
    else:
        stale = facts.get("templates") != now.get("templates") or conf.get("callers") != conf_now.get("callers")
    if stale:
        return False, f"what a {mode} run writes from changed in {CENTRAL} after {org[:12]}: the run is stale"
    for f in change["files"]:
        path = f["path"]
        if mode == "files":
            if path == "AGENTS.md":
                block = facts.get("agents-block.md")
                if block is None or base.get(path) is None:
                    return False, "AGENTS.md: its base or the organisation's block could not be read"
                try:
                    want = sync_module().with_block(base[path], block)
                except ValueError as exc:
                    return False, f"AGENTS.md: {exc}"
                if head[path] != want:
                    return False, f"AGENTS.md changes more than the organisation's block at {CENTRAL}@{org[:12]}"
            elif head[path] != (conf.get("files") or {}).get(path):
                return False, f"{path} is not what repos.yml holds at {CENTRAL}@{org[:12]}"
        elif mode == "callers":
            owned = (conf.get("callers") or {}).get("repository-owned") or {}
            problem, _ = caller_problem(path, base.get(path), head[path], templates, owned)
            if problem:
                return False, problem
        else:
            return False, f"no rule says what a {mode} run may write"
    return True, f"merges by policy: lane {name}, risk {review.get('risk')}, complexity {review.get('complexity')}, every file what {CENTRAL}@{org[:12]} holds"


def sync_lane_of(policy, issue):
    """The sync lane an issue's lane:<name> label names, or None."""
    for n in ((issue.get("labels") or {}).get("nodes") or []):
        name = (n.get("name") or "")
        if name.startswith("lane:") and ((((policy.get("lanes") or {}).get(name[len("lane:"):]) or {}).get("origin") or {}).get("runs")):
            return name[len("lane:"):]
    return None


def announce(policy, issue, run, repository, autopilot_var, label, policy_sha, sync):
    """(act, comment) for a sync lane's label added to an issue: "accept" or
    "refuse" with the comment that says so, linking the policy at the
    commit read. "skip" for any other lane: a person accepts it, or the
    workflow that opens its issues labels them itself."""
    name = label[len("lane:"):] if label.startswith("lane:") else ""
    lane = (policy.get("lanes") or {}).get(name)
    if not lane or lane.get("accept") != "policy" or not (lane.get("origin") or {}).get("runs"):
        return "skip", ""
    ok, why = lane_accepts(policy, issue, run, repository, autopilot_var, dict(sync, issue_only=True))
    link = f"[policy/autonomy.yml at {policy_sha[:12]}](https://github.com/{CENTRAL}/blob/{policy_sha}/policy/autonomy.yml)"
    if ok:
        return "accept", (f"**Accepted by policy:** {why}. The lane `{name}` of {link} accepts it, so no person needs to; "
                          "its pull request still goes through the checks and the review, and merges on its own only within the lane's limits.")
    return "refuse", (f"**Not accepted by policy:** `{why}`. The lane `{name}` of {link} does not accept it, "
                      "so it waits for a maintainer, who accepts it by hand (`accepted`) or closes it.")


def sync_module():
    """scripts/sync-repos.py, for its with_block()."""
    spec = importlib.util.spec_from_file_location("sync_repos", os.path.join(HERE, "sync-repos.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- reading GitHub ---------------------------------------------------------

ISSUE_QUERY = """query($o: String!, $n: String!, $i: Int!) {
  repository(owner: $o, name: $n) {
    issue(number: $i) {
      number body lastEditedAt authorAssociation author { login } issueType { name }
      labels(first: 50) { nodes { name } }
      timelineItems(itemTypes: [LABELED_EVENT, UNLABELED_EVENT, PARENT_ISSUE_ADDED_EVENT], last: 100) {
        nodes {
          __typename
          ... on LabeledEvent { label { name } actor { __typename login } }
          ... on UnlabeledEvent { label { name } actor { __typename login } }
          ... on ParentIssueAddedEvent { createdAt }
        }
      }
      parent {
        number state repository { nameWithOwner }
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
  }
}"""


def gh_bytes(*args):
    """gh's output as text, its bytes as they are (no newline translation);
    None when it fails."""
    out = subprocess.run(["gh", *args], capture_output=True)
    return out.stdout.decode("utf-8") if out.returncode == 0 else None


def read_issue(repository, number):
    owner, name = repository.split("/", 1)
    out = gh_bytes("api", "graphql", "-f", f"query={ISSUE_QUERY}", "-F", f"o={owner}", "-F", f"n={name}", "-F", f"i={number}")
    if out is None:
        raise RuntimeError(f"could not read issue #{number}")
    return json.loads(out)["data"]["repository"]["issue"]


def raw(repository, path, ref):
    return gh_bytes("api", f"repos/{repository}/contents/{urllib.parse.quote(path)}?ref={ref}", "-H", "Accept: application/vnd.github.raw")


def read_change(repository, pr):
    """The pull request's files, their text at its head, and at its base."""
    out = gh_bytes("api", "--paginate", "--slurp", f"repos/{repository}/pulls/{pr['number']}/files?per_page=100")
    if out is None:
        return None
    rows = [r for page in json.loads(out) for r in page]
    if len(rows) >= 3000:
        return None
    files = [{"status": r.get("status"), "path": r.get("filename"), "previous": r.get("previous_filename")} for r in rows]
    head, base = {}, {}
    for f in files:
        if f["status"] in ("added", "modified"):
            head[f["path"]] = raw(repository, f["path"], pr["headRefOid"])
        if f["status"] == "modified":
            base[f["path"]] = raw(repository, f["path"], pr["baseRefOid"])
    return {"files": files, "head": head, "base": base}


def org_sources(ref):
    """The files a sync run writes from, in DiluxOne/.github at `ref`;
    repos.yml None when any could not be read."""
    out = {"repos.yml": raw(CENTRAL, "repos.yml", ref), "agents-block.md": raw(CENTRAL, "agents-block.md", ref)}
    listing = gh_bytes("api", f"repos/{CENTRAL}/contents/workflow-templates?ref={ref}")
    names = [e["name"] for e in json.loads(listing)] if listing else []
    out["templates"] = {n: raw(CENTRAL, f"workflow-templates/{n}", ref) for n in names if n.endswith((".yml", ".yaml"))}
    if listing is None or any(t is None for t in out["templates"].values()):
        out["repos.yml"] = None
    return out


def read_org(sha, contents=False):
    """Whether a commit of DiluxOne/.github is merged into main, and with
    `contents`, the files a sync run writes from at that commit, and at
    main now (`main`): what a stale run would roll back shows there."""
    status = gh_bytes("api", f"repos/{CENTRAL}/compare/{sha}...main", "--jq", ".status")
    facts = {"merged": (status or "").strip() in ("ahead", "identical")}
    if contents:
        facts.update(org_sources(sha))
        facts["main"] = org_sources("main")
    return facts


def sync_from_env(repository, issue_only):
    """What a sync lane reads, from the fixtures the environment names or
    from GitHub, each read once and only when needed."""
    env = os.environ
    pr = None
    if env.get("LANE_PR"):
        pr = load_json(env["LANE_PR"])
    elif env.get("PR"):
        pr = {"number": int(env["PR"]), "author": {"login": env.get("PR_AUTHOR", "")}, "headRefName": env.get("HEAD_REF", ""),
              "headRefOid": env.get("HEAD_SHA", ""), "baseRefOid": env.get("BASE_SHA", "")}
    cache = {}

    def change():
        if "change" not in cache:
            cache["change"] = load_json(env["LANE_CHANGE"]) if env.get("LANE_CHANGE") else (read_change(repository, pr) if pr else None)
        return cache["change"]

    def org(sha, contents=False):
        key = (sha, contents)
        if key not in cache:
            cache[key] = load_json(env["LANE_ORG"]) if env.get("LANE_ORG") else read_org(sha, contents)
        return cache[key]
    return {"issue_only": issue_only, "pr": pr, "change": change, "org": org}


def issue_from_env(repository):
    if os.environ.get("LANE_ISSUE"):
        return load_json(os.environ["LANE_ISSUE"])
    return read_issue(repository, int(os.environ["NUMBER"]))


def issue_settled(issue, read, label, tries=5, wait=3, sleep=None):
    """The issue once GitHub shows `label`'s event (#263). A label added a
    moment ago can be missing from the timeline the API returns: reading
    again for a few seconds tells that apart from a label nobody added."""
    sleep = sleep or time.sleep
    for _ in range(tries - 1):
        if not issue or last_label_event(issue, label):
            break
        sleep(wait)
        # A read that fails keeps the last good one.
        try:
            issue = read() or issue
        except (RuntimeError, OSError, ValueError, KeyError):
            pass
    return issue


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
    # issue-accepted.yml's lane job fetches autonomy.py alone: whatever it
    # imports from this directory must be fetched with it.
    with open(os.path.join(HERE, "..", ".github", "workflows", "issue-accepted.yml"), encoding="utf-8") as fh:
        fetched = next((l for l in fh if "for f in scripts/autonomy.py" in l), "")
    local = sorted(set(re.findall(r"^import (\w+)", open(__file__, encoding="utf-8").read(), re.M)) & {f[:-3] for f in os.listdir(HERE) if f.endswith(".py")})
    check("#191: the lane job fetches what autonomy.py imports from here, and org.yml", (all(f"scripts/{m}.py" in fetched for m in local), "org.yml" in fetched), (True, True))
    check("the organisation's policy has the six lanes", sorted(org.get("lanes", {})), ["bugfix-reproduced", "delegated", "human-issue", "org-sync", "platform", "release"])

    # #189: a sub-issue of an issue a person accepted.
    def child(parent_labels=("accepted",), actor="User", state="OPEN", where="DiluxOne/.github", assoc="MEMBER",
              author="someone", edited=None, linked="2026-10-16T10:00:00Z", labels=(), parent=True, unlabeled=False):
        events = [{"__typename": "LabeledEvent", "label": {"name": "accepted"}, "actor": {"__typename": actor, "login": "soydiloreto" if actor == "User" else "dilux-bot"}}]
        if unlabeled:
            events.append({"__typename": "UnlabeledEvent", "label": {"name": "accepted"}, "actor": {"__typename": "User", "login": "soydiloreto"}})
        return {"number": 9, "body": "Carry it out here.", "author": {"login": author}, "authorAssociation": assoc, "lastEditedAt": edited,
                "labels": {"nodes": [{"name": n} for n in labels]},
                "timelineItems": {"nodes": [{"__typename": "ParentIssueAddedEvent", "createdAt": linked}] if linked else []},
                "parent": {"number": 189, "state": state, "repository": {"nameWithOwner": where},
                           "labels": {"nodes": [{"name": n} for n in parent_labels]}, "timelineItems": {"nodes": events}} if parent else None}
    dpol = merge(org, {})
    acc = lambda i, var="": lane_accepts(dpol, i, None, "DiluxOne/diluxone-mail-wordpress", var)
    check("#189 C1: a member's sub-issue of a person's accepted issue is accepted by policy", acc(child()), (True, "accepted by policy: lane delegated, a sub-issue of DiluxOne/.github#189, which soydiloreto accepted"))
    check("#189 C1: one the lane's App opened is too", acc(child(assoc="NONE", author="dilux-bot[bot]"))[0], True)
    check("#189 C2: a parent nobody accepted", acc(child(parent_labels=()))[0], False)
    check("#189 C2: a parent a bot accepted", acc(child(actor="Bot"))[0], False)
    check("#189 C3: a sub-issue from outside the organisation", acc(child(assoc="CONTRIBUTOR"))[0], False)
    check("#189 C3: a sub-issue edited after it was linked", acc(child(edited="2026-10-16T11:00:00Z"))[0], False)
    check("#189 C3: edited before it was linked counts as written then", acc(child(edited="2026-10-16T09:00:00Z"))[0], True)
    check("#189 C3: no link event read, no acceptance", acc(child(linked=None))[0], False)
    check("#189 C4: a closed parent takes it back", acc(child(state="CLOSED"))[0], False)
    check("#189 C4: a parent whose accepted was removed takes it back", acc(child(parent_labels=(), unlabeled=True))[0], False)
    check("#189: a parent in another organisation", acc(child(where="Other/.github"))[0], False)
    check("#189: an issue with no parent and no lane is no lane's", acc(child(parent=False))[0], False)
    check("#189: a lane label wins over the parent", lane_of(child(labels=("lane:platform",))), ("platform", None))
    check("#189: DX_AUTOPILOT off stops it", acc(child(), "off")[0], False)
    check("#189: a repository switches it off", lane_accepts(merge(org, {"lanes": {"delegated": {"enabled": False}}}), child(), None, "DiluxOne/x", "")[0], False)
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
    check("a repository cannot raise what a lane without a ceiling merges", m["lanes"]["platform"]["merge"]["max-risk"], "medium")
    check("#188: the organisation's policy holds to its schema", problems(org), [])
    check("#188: human-issue merges up to medium by default, high at most", (org["lanes"]["human-issue"]["merge"]["max-risk"], org["lanes"]["human-issue"]["ceiling"]["max-risk"]), ("medium", "high"))
    m = merge(org, {"lanes": {"human-issue": {"merge": {"max-risk": "high"}}}})
    check("#188: a repository raises a lane up to its ceiling", m["lanes"]["human-issue"]["merge"]["max-risk"], "high")
    capped = merge({**org, "lanes": {**org["lanes"], "human-issue": {**org["lanes"]["human-issue"], "merge": {"max-risk": "low", "max-complexity": "low"}, "ceiling": {"max-risk": "medium", "max-complexity": "medium"}}}},
                   {"lanes": {"human-issue": {"merge": {"max-risk": "high", "max-complexity": "medium"}}}})
    check("#188: never past the ceiling", (capped["lanes"]["human-issue"]["merge"]["max-risk"], capped["lanes"]["human-issue"]["merge"]["max-complexity"]), ("medium", "medium"))
    m = merge(org, {"lanes": {"human-issue": {"merge": {"max-risk": "low"}}}})
    check("#188: a repository still lowers a lane with a ceiling", m["lanes"]["human-issue"]["merge"]["max-risk"], "low")
    m = merge(org, {"lanes": {"release": {"merge": {"max-risk": "high"}}}})
    check("#188: a release never merges on its own, whatever a repository says", m["lanes"]["release"]["merge"]["max-risk"], "none")
    lane = lambda **k: {"lanes": {**org["lanes"], "human-issue": {**org["lanes"]["human-issue"], **k}}}
    check("#188 schema: a key the policy does not know", problems({**org, "owner": "me"}), ["owner: not a key of the policy"])
    check("#247 schema: a planned release is auto or confirm", [problems({**org, "planned-release": v}) for v in ("auto", "confirm", "yes")],
          [[], [], ["planned-release: auto or confirm"]])
    check("#247 schema: the veto window is hours, above 0, at most 720",
          [problems({**org, "security-patch": v}) for v in ({"veto-hours": 2}, {"veto-hours": 0}, {"veto-hours": True}, {"veto-hours": 721}, {"hours": 6})],
          [[]] + [["security-patch: veto-hours, a number of hours above 0 and at most 720"]] * 4)
    check("#188 schema: a lane's unknown key", problems({**org, **lane(budget=5)}), ["lanes.human-issue.budget: not a key of a lane"])
    check("#188 schema: an unknown level", problems({**org, **lane(merge={"max-risk": "huge", "max-complexity": "low"})}), ["lanes.human-issue.merge.max-risk: one of none, low, medium, high"])
    check("#188 schema: a ceiling below the default", problems({**org, **lane(ceiling={"max-risk": "low", "max-complexity": "high"})}), ["lanes.human-issue.ceiling.max-risk: low is below the lane's merge (medium)"])
    check("#188 schema: merge names both caps", problems({**org, **lane(merge={"max-risk": "low"})}), ["lanes.human-issue.merge: max-risk and max-complexity"])
    check("#188 schema: the policy and the rules are always protected", problems({**org, "constitution": [".github/**"]}), ["constitution: policy/** is always protected", "constitution: rules/** is always protected"])
    check("#194 schema: security is always a label a person merges", (problems({**org, "person-merges": []}), problems({**org, "person-merges": "security"})), (["person-merges: security is always there"], ["person-merges: a list of labels"]))
    check("#194 merge: a repository adds labels a person merges, never takes security away", merge(org, {"person-merges": ["payments"]})["person-merges"][-2:], ["security", "payments"])
    check("#194 merge: an empty list in a repository keeps security", "security" in merge(org, {"person-merges": []})["person-merges"], True)
    g = {**org, "autopilot-mode": {"default": "guided", "ceiling": "full"}}
    check("#247 mode: the organisation's default; a repository chooses up to the ceiling",
          (merge(g, {})["autopilot-mode"]["mode"], merge(g, {"autopilot-mode": "full"})["autopilot-mode"]["mode"],
           merge({**org, "autopilot-mode": {"default": "full", "ceiling": "full"}}, {"autopilot-mode": "guided"})["autopilot-mode"]["mode"]), ("guided", "full", "guided"))
    check("#247 mode: never past a guided ceiling", merge({**org, "autopilot-mode": {"default": "guided", "ceiling": "guided"}}, {"autopilot-mode": "full"})["autopilot-mode"]["mode"], "guided")
    check("#247 schema: modes and their order", (problems({**org, "autopilot-mode": {"default": "auto"}}), problems({**org, "autopilot-mode": {"default": "full", "ceiling": "guided"}})),
          (["autopilot-mode: default and ceiling, each guided or full"], ["autopilot-mode: a ceiling below the default"]))
    with tempfile.TemporaryDirectory() as tmp:
        bad_policy = os.path.join(tmp, "autonomy.yml")
        with open(bad_policy, "w", encoding="utf-8") as fh:
            fh.write("autopilot: true\nconstitution: [\"policy/**\", \"rules/**\"]\nlanes: {x: {accept: maybe}}\n")
        run_check = lambda path: subprocess.run([sys.executable, os.path.abspath(__file__), "check"], env={**os.environ, "ORG_AUTONOMY": path}, capture_output=True, text=True)
        got, good = run_check(bad_policy), run_check(os.path.join(HERE, "..", "policy", "autonomy.yml"))
    check("#188 check: a policy off its schema exits 1 and says why", (got.returncode, "lanes.x.accept: human or policy" in got.stdout), (1, True))
    check("#188 check: the organisation's policy passes", (good.returncode, good.stdout), (0, ""))
    rel = {**org, "lanes": {**org["lanes"], "release": {**org["lanes"]["release"], "ceiling": {"max-risk": "high", "max-complexity": "high"}}}}
    check("#188 schema: a release lane with a ceiling", problems(rel), ["lanes.release: never merges on its own, and has no ceiling"])
    check("#188 schema: a policy lane without an origin", problems({**org, **lane(accept="policy")}), ["lanes.human-issue.origin: a lane that accepts by policy names who opens its issues"])
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

    # The org-sync lane (#155): what scripts/sync-repos.py opens.
    sr = "DiluxOne/diluxone-offload-wordpress"
    sha = "0123456789abcdef0123456789abcdef01234567"
    block = "<!-- dx:org:start (x) -->\nRULES\n<!-- dx:org:end -->\n"
    owners = "* @soydiloreto\n"
    agents_base = "# AGENTS.md\n\nMine.\n"
    agents_head = sync_module().with_block(agents_base, block)
    template = ("on:\n  issues:\n    types: [opened]\npermissions:\n  contents: read\njobs:\n"
                "  triage:\n    permissions:\n      issues: write\n    uses: DiluxOne/.github/.github/workflows/issue-triage.yml@v5\n"
                "    with:\n      support-url: https://example.com\n      mode: full\n    secrets: inherit\n"
                "  repro-triaged:\n    needs: triage\n    if: needs.triage.outputs.bug == 'true'\n    permissions:\n      contents: write\n"
                "    uses: DiluxOne/.github/.github/workflows/issue-repro.yml@v5\n    secrets: inherit\n")
    caller_base = ("on:\n  issues:\n    types: [opened]\npermissions:\n  contents: read\njobs:\n"
                   "  triage:\n    permissions:\n      issues: write\n    uses: DiluxOne/.github/.github/workflows/issue-triage.yml@v5\n"
                   "    with:\n      support-url: https://mine.example\n      own-input: mine\n    secrets: inherit\n"
                   "  mine:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo mine\n")
    caller_head = caller_base.replace("      support-url: https://mine.example\n", "      support-url: https://mine.example\n      mode: full\n")
    org_facts = {"merged": True, "repos.yml": json.dumps({"files": {".github/CODEOWNERS": owners}, "callers": {"repository-owned": {"issues.yml": ["support-url"]}}}),
                 "agents-block.md": block, "templates": {"issues.yml": template}}
    org_facts["main"] = {k: org_facts[k] for k in ("repos.yml", "agents-block.md", "templates")}
    runs = org["lanes"]["org-sync"]["origin"]["runs"]

    def sync_case(mode="files", files=None, base=None, author="soydiloreto", actor=None, edited=None, typ="Task", number=31,
                  labels=("lane:org-sync",), marker_files=None, merged=True, pr_author=None, branch=None, status=None, body=None, main=None):
        files = files if files is not None else ({".github/CODEOWNERS": owners, "AGENTS.md": agents_head} if mode == "files" else {".github/workflows/issues.yml": caller_head})
        base = base if base is not None else ({"AGENTS.md": agents_base} if mode == "files" else {".github/workflows/issues.yml": caller_base})
        text = body if body is not None else ("The organisation keeps some files the same.\n\n🤖 AI-generated · scripts/sync-repos.py\n\n"
                                               + sync_marker("org-sync", sr, mode, sha, marker_files if marker_files is not None else files))
        i = {"number": number, "author": {"login": author}, "body": text, "lastEditedAt": edited, "issueType": {"name": typ},
             "labels": {"nodes": [{"name": n} for n in labels]},
             "timelineItems": {"nodes": [{"__typename": "LabeledEvent", "label": {"name": "lane:org-sync"}, "actor": {"__typename": "User", "login": actor or author}}]}}
        change = {"files": [{"status": (status or {}).get(p) or ("modified" if p in base else "added"), "path": p} for p in files], "head": dict(files), "base": dict(base)}
        pr = {"number": 32, "author": {"login": pr_author or author}, "headRefName": branch or runs[mode]["branch"].format(issue=number)}
        facts = dict(org_facts, merged=merged)
        if main:
            facts["main"] = dict(org_facts["main"], **main)
        s = {"pr": pr, "change": lambda: change, "org": lambda _sha, _contents=False: facts}
        return i, s

    def sync_ok(case, scope="pr", p=pol, repository=sr, var=""):
        i, s = case
        return lane_accepts(p, i, None, repository, var, dict(s, issue_only=scope == "issue"))[0]

    green = {"risk": "high", "complexity": "low", "blocking": "false", "description_ok": "true"}

    def merges(case, review=None, p=pol):
        i, s = case
        return sync_merge(p, i, sr, "", s, review or green)

    check("the lane names who may run the sync, and only a policy file can", org["lanes"]["org-sync"]["origin"].get("people"), ["soydiloreto"])
    m = merge(org, {"lanes": {"org-sync": {"origin": {"people": ["someone"]}}}})
    check("a repository cannot add a person to a sync lane", m["lanes"]["org-sync"]["origin"]["people"], ["soydiloreto"])
    check("the marker a run writes is the one the lane reads", bool(SYNC_MARKER.fullmatch(sync_marker("org-sync", sr, "callers", sha, {"a": "b"}))), True)
    check("the fingerprint changes with any byte of any file", fingerprint(sr, "files", sha, {"a": "b"}) != fingerprint(sr, "files", sha, {"a": "b "}), True)
    # C1: a callers run's issue, naming a merged commit here, is accepted by
    # policy when it is labelled, with a link to the policy at its commit.
    check("C1: a callers run's issue is accepted by policy", sync_ok(sync_case("callers"), scope="issue"), True)
    act, said = announce(pol, sync_case("callers")[0], None, sr, "", "lane:org-sync", sha, dict(sync_case("callers")[1]))
    check("C1: it is announced as accepted, with the policy at its commit", (act, f"https://github.com/{CENTRAL}/blob/{sha}/policy/autonomy.yml" in said), ("accept", True))
    check("C1: and its pull request passes the gate", sync_ok(sync_case("callers")), True)
    check("C1: a files run's pull request passes the gate", sync_ok(sync_case("files")), True)
    check("C1: a lane a person accepts is not announced", announce(pol, issue(labels=("lane:release",)), None, repo, "", "lane:release", sha, {})[0], "skip")
    check("C1: nor a lane whose own workflow labels its issues", announce(pol, issue(), run, repo, "", "lane:platform", sha, {})[0], "skip")
    act, said = announce(pol, sync_case(edited="2026-10-15T00:00:00Z")[0], None, sr, "", "lane:org-sync", sha, sync_case()[1])
    check("C1: a refusal is announced with why", (act, "edited" in said), ("refuse", True))
    # C2: opened by hand, or the marker without the run in its history.
    check("C2: opened by someone the lane does not name", sync_ok(sync_case(author="someone"), scope="issue"), False)
    check("C2: the label added by someone other than whoever opened it", sync_ok(sync_case(actor="dilux-bot"), scope="issue"), False)
    check("C2: no marker (an issue opened by hand)", sync_ok(sync_case(body="Please sync the files."), scope="issue"), False)
    check("C2: the text edited after the run", sync_ok(sync_case(edited="2026-10-15T00:00:00Z"), scope="issue"), False)
    no_history = sync_case()
    del no_history[0]["lastEditedAt"]
    check("C2: an edit history that was not read", sync_ok(no_history, scope="issue"), False)
    check("C2: a commit that is not merged here", sync_ok(sync_case(merged=False), scope="issue"), False)
    check("C2: a kind of run the lane does not know", sync_ok(sync_case(body=sync_marker("org-sync", sr, "labels", sha, {})), scope="issue"), False)
    check("C2: a Type other than Task", sync_ok(sync_case(typ="Feature"), scope="issue"), False)
    check("C2: the marker copied into another issue: its pull request's files are not the run's", sync_ok(sync_case(marker_files={".github/CODEOWNERS": "* @other\n", "AGENTS.md": agents_head})), False)
    check("C2: a pull request from a branch the run does not name", sync_ok(sync_case(branch="chore/31-mine")), False)
    check("C2: a pull request someone else opened", sync_ok(sync_case(pr_author="someone")), False)
    check("C2: the gate without the pull request refuses", lane_accepts(pol, sync_case()[0], None, sr, "", {"org": sync_case()[1]["org"]})[0], False)
    check("C2: never in DiluxOne/.github", sync_ok(sync_case(), repository=CENTRAL), False)
    check("C2: DX_AUTOPILOT off stops the lane", sync_ok(sync_case(), var="off"), False)
    check("C2: a repository that switched the lane off", sync_ok(sync_case(), p=merge(org, {"lanes": {"org-sync": {"enabled": False}}})), False)
    check("C2: a repository that made the lane human", sync_ok(sync_case(), p=merge(org, {"lanes": {"org-sync": {"accept": "human"}}})), False)
    check("C2: the label alone is nothing", sync_ok(sync_case(body="<!-- dx-lane: org-sync -->"), scope="issue"), False)
    check("a person the lane names, through dilux-bot's login forms", sync_ok(sync_case(author="dilux-bot", actor="dilux-bot[bot]", pr_author="dilux-bot[bot]")), True)
    # C3: a file outside what the run writes fails the lane, at the gate and at the merge.
    extra = {".github/CODEOWNERS": owners, "AGENTS.md": agents_head, "README.md": "x\n"}
    check("C3: a file outside the sync's set fails the gate", sync_ok(sync_case(files=extra)), False)
    check("C3: and the merge", merges(sync_case(files=extra))[0], False)
    check("C3: a workflow in a files run fails the lane", sync_ok(sync_case(files={".github/workflows/x.yml": "on: push\n"})), False)
    check("C3: a workflow under a subdirectory is outside the set", sync_ok(sync_case("callers", files={".github/workflows/sub/x.yml": caller_head}, base={})), False)
    check("C3: a removed file fails the lane", sync_ok(sync_case(status={"AGENTS.md": "removed"})), False)
    check("C3: a renamed file fails the lane", sync_ok(sync_case(status={"AGENTS.md": "renamed"})), False)
    # C4: green, but a caller that changes a job's permissions or secrets waits for a person.
    check("a files run's pull request, green, merges by policy", merges(sync_case())[0], True)
    check("a callers run's pull request, green, merges by policy", merges(sync_case("callers"))[0], True)
    perms = caller_head.replace("      issues: write\n", "      issues: write\n      contents: write\n", 1)
    ok, why = merges(sync_case("callers", files={".github/workflows/issues.yml": perms}))
    check("C4: a caller that changes a job's permissions does not merge on its own", (ok, "high risk" in why), (False, True))
    secrets = caller_head.replace("    secrets: inherit\n", "    secrets:\n      TOKEN: ${{ secrets.TOKEN }}\n", 1)
    ok, why = merges(sync_case("callers", files={".github/workflows/issues.yml": secrets}))
    check("C4: a caller that changes the secrets it passes does not merge on its own", (ok, "high risk" in why), (False, True))
    new_job = caller_head + ("  repro-triaged:\n    needs: triage\n    if: needs.triage.outputs.bug == 'true'\n    permissions:\n      contents: write\n"
                             "    uses: DiluxOne/.github/.github/workflows/issue-repro.yml@v5\n    secrets: inherit\n")
    ok, why = merges(sync_case("callers", files={".github/workflows/issues.yml": new_job}))
    check("C4: a new job, with permissions and secrets, does not merge on its own", (ok, "high risk" in why), (False, True))
    bare_job = caller_head + "  plain:\n    uses: DiluxOne/.github/.github/workflows/issue-triage.yml@v5\n"
    plain_template = template + "  plain:\n    uses: DiluxOne/.github/.github/workflows/issue-triage.yml@v5\n"
    case = sync_case("callers", files={".github/workflows/issues.yml": bare_job})
    case[1]["org"] = lambda _sha, _contents=False: dict(org_facts, templates={"issues.yml": plain_template}, main=dict(org_facts["main"], templates={"issues.yml": plain_template}))
    ok, why = merges(case)
    check("C4: a new job asking for no permission nor secret still waits for a person", (ok, "high risk" in why), (False, True))
    check("C4: the same pull request is still accepted (a person merges it)", sync_ok(sync_case("callers", files={".github/workflows/issues.yml": new_job})), True)
    check("C4: nor does one the review blocks", merges(sync_case(), dict(green, blocking="true"))[0], False)
    check("C4: nor one whose description is not true", merges(sync_case(), dict(green, description_ok="false"))[0], False)
    check("C4: nor one above the lane's complexity", merges(sync_case(), dict(green, complexity="medium"))[0], False)
    check("C4: nor with DX_AUTOPILOT off", sync_merge(pol, sync_case()[0], sr, "off", sync_case()[1], green)[0], False)
    for name, text in (("calls another workflow", caller_head.replace("issue-triage.yml@v5", "issue-triage.yml@main")),
                       ("calls someone else's workflow", caller_head.replace("DiluxOne/.github/.github/workflows/issue-triage.yml@v5", "evil/x/.github/workflows/issue-triage.yml@v5")),
                       ("passes an input other than the template", caller_head.replace("mode: full", "mode: lite")),
                       ("changes the repository's own input", caller_head.replace("https://mine.example", "https://other.example")),
                       ("changes a job of its own", caller_head.replace("echo mine", "echo theirs")),
                       ("changes its triggers", caller_head.replace("types: [opened]", "types: [opened, edited]")),
                       ("removes a job", caller_head.split("  mine:")[0]),
                       ("drops an input of the repository's own", caller_head.replace("      own-input: mine\n", "")),
                       ("drops an input the repository fills in", caller_head.replace("      support-url: https://mine.example\n", ""))):
        check(f"a caller that {name} does not merge on its own", merges(sync_case("callers", files={".github/workflows/issues.yml": text}))[0], False)
    check("a CODEOWNERS that is not repos.yml's does not merge on its own", merges(sync_case(files={".github/CODEOWNERS": "* @someone\n", "AGENTS.md": agents_head}))[0], False)
    check("an AGENTS.md changed outside its block does not merge on its own", merges(sync_case(files={".github/CODEOWNERS": owners, "AGENTS.md": agents_head + "\nMore.\n"}))[0], False)
    check("a stale files run (main's repos.yml moved on) does not merge on its own",
          merges(sync_case(main={"repos.yml": json.dumps({"files": {".github/CODEOWNERS": "* @someone\n"}})}))[0], False)
    check("a stale callers run (main's templates moved on) does not merge on its own",
          merges(sync_case("callers", main={"templates": {"issues.yml": template + "  more:\n    uses: DiluxOne/.github/.github/workflows/x.yml@v5\n"}}))[0], False)
    check("a files run is not stale for a change of main elsewhere in repos.yml",
          merges(sync_case(main={"repos.yml": json.dumps({"files": {".github/CODEOWNERS": owners}, "projects": {"x": 1}})}))[0], True)
    check("the lane merges what the review rates high only because of its paths", (org["lanes"]["org-sync"]["merge"]["max-risk"], org["lanes"]["org-sync"]["merge"]["max-complexity"]), ("high", "low"))

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

    # The sync lane's step in auto-merge.yml reads the repository's policy
    # as the revert's does: only a missing file reads as none.
    am = open(os.path.join(HERE, "..", ".github", "workflows", "auto-merge.yml"), encoding="utf-8").read()
    step = am[am.index("name: A sync run's pull request"):am.index("name: Enable or disable")]
    check("auto-merge.yml: the sync lane reads only a missing .github/autonomy.yml as none",
          ("|| : >" not in step, "grep -qE '404|Not Found'" in step, "autonomy.py\" lane-merge" in step), (True, True, True))
    # #283: a release pull request is decided by its own proof, before the
    # lane and the usual decision, which both stand aside once it handled it.
    rel = am[am.index("name: A release pull request"):am.index("name: A sync run's pull request")]
    gated_by_release = lambda name: "steps.release.outputs.handled != 'true'" in am[am.index(f"name: {name}"):][:400]
    check("#283 auto-merge.yml: a release pull request merges only by its proof, and nothing else decides it",
          (gated_by_release("A sync run's pull request"), gated_by_release("Enable or disable"), "release-issue.py\" verify" in rel,
           "release-issue.py\" argv" in rel, "git write-tree" in rel, "--match-head-commit \"$HEAD_SHA\"" in rel, 'person "' in rel, '.issue "$RUNNER_TEMP/verify.json")" = "$issues"' in rel),
          (True, True, True, True, True, True, True, True))
    merges = [l for l in am.splitlines() if "gh pr merge" in l and "--auto" in l and "--disable-auto" not in l]
    check("auto-merge.yml: every auto-merge is tied to the head it decided on", (len(merges) >= 4, all("--match-head-commit" in l for l in merges)), (True, True))
    held = am[am.index("name: Labels a person merges"):am.index("name: A sync run's pull request")]
    gated = lambda name: "steps.held.outputs.label == ''" in am[am.index(f"name: {name}"):][:400]
    check("#194 auto-merge.yml: an issue a person merges holds the sync lane and the usual decision, and a read that fails holds them too",
          (gated("A sync run's pull request"), gated("Enable or disable"), "could not be read" in held, "|| : >" not in held, '"person-merges"' in held), (True, True, True, True, True))

    # #263: a label just added, missing from the first read, is read again.
    labelled = {"timelineItems": {"nodes": [{"__typename": "LabeledEvent", "label": {"name": "lane:x"}}]}}
    bare = {"timelineItems": {"nodes": []}}
    reads = iter([bare, labelled])
    waits = []
    check("#263 issue_settled reads again until the label's event shows", (issue_settled(bare, lambda: next(reads), "lane:x", sleep=waits.append) is labelled, len(waits)), (True, 2))
    waits = []
    check("#263 issue_settled gives up after its tries", (last_label_event(issue_settled(bare, lambda: bare, "lane:x", tries=3, sleep=waits.append), "lane:x"), len(waits)), (None, 2))
    def fails():
        raise RuntimeError("gh failed")
    check("#263 a re-read that fails keeps the read in hand", issue_settled(bare, fails, "lane:x", tries=2, sleep=lambda _: None) is bare, True)
    waits = []
    check("#263 a label already shown is not read again", (issue_settled(labelled, fails, "lane:x", sleep=waits.append) is labelled, waits), (True, []))

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
    if mode == "check":
        found = problems(load(os.environ.get("ORG_AUTONOMY") or os.path.join(HERE, "..", "policy", "autonomy.yml")))
        for line in found:
            print(line)
        return 1 if found else 0
    var = os.environ.get("DX_AUTOPILOT", "")
    if mode == "lane-open":
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        ok, why = lane_open(policy_in_force(), name, os.environ["GITHUB_REPOSITORY"], var)
        print(why)
        return 0 if ok else 1
    if mode == "lane-accept":
        repository = os.environ["GITHUB_REPOSITORY"]
        try:
            first = issue_from_env(repository)
            # Only a lane named by its label waits for that label's event.
            names = [n.get("name") for n in ((first or {}).get("labels") or {}).get("nodes") or []]
            name = lane_of(first)[0] if first else None
            issue = issue_settled(first, lambda: issue_from_env(repository), f"lane:{name}") if f"lane:{name}" in names and not os.environ.get("LANE_ISSUE") else first
        except (RuntimeError, OSError, ValueError, KeyError):
            issue = None
        if not issue:
            print("the issue could not be read")
            return 1
        sync = sync_from_env(repository, os.environ.get("LANE_SCOPE") == "issue")
        ok, why = lane_accepts(policy_in_force(), issue, read_run(issue, repository), repository, var, sync)
        print(why)
        return 0 if ok else 1
    if mode == "lane-announce":
        repository = os.environ["GITHUB_REPOSITORY"]
        sha = os.environ.get("POLICY_SHA", "")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            print("POLICY_SHA must be the policy's full commit", file=sys.stderr)
            return 64
        issue = issue_from_env(repository)
        act, comment = announce(policy_in_force(), issue, read_run(issue, repository), repository, var,
                                os.environ.get("LANE", ""), sha, sync_from_env(repository, True))
        print(json.dumps({"act": act, "comment": comment}))
        return 0
    if mode == "lane-merge":
        repository = os.environ["GITHUB_REPOSITORY"]
        # An issue that cannot be read is no sync lane's: the usual decision
        # takes it, and that one never merges the paths a sync run writes
        # (their floor is high).
        try:
            issue = issue_from_env(repository)
            policy = policy_in_force()
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            print(f"the issue could not be read ({exc}): no sync lane's")
            return 2
        if not sync_lane_of(policy, issue):
            print("no sync lane's issue")
            return 2
        review = {"risk": os.environ.get("RISK", ""), "complexity": os.environ.get("COMPLEXITY", ""),
                  "blocking": os.environ.get("BLOCKING", ""), "description_ok": os.environ.get("DESCRIPTION_OK", "")}
        try:
            ok, why = sync_merge(policy, issue, repository, var, sync_from_env(repository, False), review)
        except Exception as exc:  # any failure is a person's merge, said as a failure
            print(f"the decision failed: {exc}")
            return 3
        print(why)
        return 0 if ok else 1
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main())
