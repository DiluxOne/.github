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
  autonomy.py lane-merge    whether a sync lane's pull request (org-sync), or
                            a security patch's carry (security-carry, #287),
                            merges on its own: exit 0 when it does, 1 when a
                            person merges it, 2 when it is neither lane's
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
  For the security-carry lane (#287): LANE_ADVISORY (a file holding the
                   advisory), LANE_RELEASED (true or false), LANE_EQUIVALENT
                   (a file holding {ok, why}); each read from GitHub, or
                   with git, when unset
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
import repos_conf  # noqa: E402  repos.yml's one entry per repository (#562)
LEVELS = ["none", "low", "medium", "high"]
CENTRAL = org.CENTRAL
MARKER = re.compile(r"<!--\s*dx-lane:\s*([a-z0-9-]+)\s+run:\s*(https://github\.com/([^/\s]+)/([^/\s]+)/actions/runs/(\d+))\s*-->")
# What a run of scripts/sync-repos.py writes in the issue it opens (sync
# lanes): the lane, the kind of run, the commit of DiluxOne/.github it brings
# the repository in line with, and the run's fingerprint (fingerprint()).
# A security patch's carry (#287): the issue security-patch.yml opens in the
# public repository, naming the version released and its advisory.
CARRY_MARKER = re.compile(r"<!--\s*dx-lane:\s*([a-z0-9-]+)\s+version:\s*(\d+\.\d+\.\d+)\s+ghsa:\s*(GHSA(?:-[a-z0-9]{4}){3})\s*-->")
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


# What every repository protects, whatever its policy says (#561): its
# workflows, which the autopilot cannot push, and the files that say what
# merges there and who reviews it, so no change merges a widening of them.
ALWAYS_PROTECTED = [".github/workflows/**", ".github/autonomy.yml", ".github/review-policy.yml", ".github/CODEOWNERS"]


def protected_paths(org_constitution, declared, where=""):
    """The paths whose change G7 leaves to a person in the repository
    `where` (#561 C4). In the organisation's own repository (org.CENTRAL),
    or one not named (failing closed), the whole constitution: its
    policy/, scripts/ and kinds/ are the engine. In any other,
    ALWAYS_PROTECTED (its workflows and its own policy files) and the
    paths it declares in its own policy
    (`constitution:`): there scripts/ is ordinary code, under the lane's
    caps like any other path. Pure."""
    declared = [p for p in declared or [] if isinstance(p, str) and p]
    base = list(org_constitution or []) if not where or where == org.CENTRAL else list(ALWAYS_PROTECTED)
    return base + [p for p in declared if p not in base]


def merge(org, repo, where=""):
    """The organisation's policy, made stricter by a repository's: never
    looser, but what a lane merges may rise up to the lane's `ceiling`.
    `constitution` stays the organisation's, added to; `protected` is what
    G7 holds for a person in the repository `where` (protected_paths)."""
    out = copy.deepcopy(org)
    out.setdefault("lanes", {})
    out["autopilot"] = bool(org.get("autopilot", False)) and repo.get("autopilot", True) is not False
    if repo.get("autopilot") is True and not org.get("autopilot", False):
        warn("autopilot: the organisation has it off; a repository cannot turn it on. Ignored.")
    extra = [p for p in (repo.get("constitution") or []) if isinstance(p, str)]
    out["constitution"] = list(org.get("constitution") or []) + [p for p in extra if p not in (org.get("constitution") or [])]
    out["protected"] = protected_paths(org.get("constitution"), extra, where)
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
    # What an agent's run may cost (#287): a repository only lowers it.
    mine = repo.get("budgets-usd") if isinstance(repo.get("budgets-usd"), dict) else {}
    budgets = dict(org.get("budgets-usd") or {})
    for key, value in mine.items():
        if key in budgets and isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value < budgets[key]:
            budgets[key] = value
        elif key in budgets and value != budgets[key]:
            warn(f"budgets-usd.{key}: a repository can only lower it; kept {budgets[key]}.")
    if budgets:
        out["budgets-usd"] = budgets
    # A claim's days and limits (#488): a repository only lowers them.
    mine = repo.get("claims") if isinstance(repo.get("claims"), dict) else {}
    claims = dict(org.get("claims") or {})
    for key, value in mine.items():
        if key in claims and isinstance(value, int) and not isinstance(value, bool) and 0 < value < claims[key]:
            claims[key] = value
        elif key in claims and value != claims[key]:
            warn(f"claims.{key}: a repository can only lower it; kept {claims[key]}.")
    if claims:
        out["claims"] = claims
    for name, lane in out["lanes"].items():
        lane.setdefault("enabled", True)
    return out


TOP_KEYS = {"claims", "autopilot", "autopilot-rounds", "autopilot-runs", "autopilot-mode", "budgets-usd", "constitution", "person-merges", "planned-release", "security-patch", "lanes"}
BUDGETS = ("autopilot-spec", "autopilot-work", "autopilot-fix", "security-fix")
CLAIMS = ("remind-days", "release-days", "cap-days", "pr-remind-days", "pr-close-days", "newcomer-claims", "contributor-claims", "open-prs")
MODES = ("guided", "full")
# What merge() lets a repository's own file do with each key, as
# policy/settings-schema.yml says it (#568, its `repo:`); any other key is
# never a repository's. The self-test holds the two together.
REPO_RULES = {"autopilot": "stricter", "autopilot-mode": "up-to-ceiling", "budgets-usd.*": "lower-only",
              "claims.*": "lower-only", "constitution": "add-only", "person-merges": "add-only",
              "lanes.*.enabled": "stricter", "lanes.*.accept": "stricter", "lanes.*.repositories": "stricter",
              "lanes.*.merge": "up-to-ceiling"}
LANE_KEYS = {"description", "accept", "type", "origin", "repositories", "evidence", "merge", "ceiling", "constitution-merge", "enabled"}
# The one lane whose fix may merge in a protected path, and only when it
# widens nothing (#397, constitution_merge()).
CONSTITUTION_LANE = "bugfix-reproduced"


def problems(policy):
    """What keeps the organisation's policy from its schema; empty when it holds."""
    out = []
    if not isinstance(policy, dict):
        return ["the policy is not a mapping"]
    for key in sorted(set(policy) - TOP_KEYS):
        out.append(f"{key}: not a key of the policy")
    if not isinstance(policy.get("autopilot"), bool):
        out.append("autopilot: true or false")
    b = policy.get("budgets-usd", {})
    if not isinstance(b, dict) or set(b) - set(BUDGETS) or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v <= 200 for v in b.values()):
        out.append(f"budgets-usd: {', '.join(BUDGETS)}, each a number of dollars above 0 and at most 200")
    c = policy.get("claims", {})
    if not isinstance(c, dict) or set(c) - set(CLAIMS) or not all(isinstance(v, int) and not isinstance(v, bool) and 0 < v <= 365 for v in c.values()):
        out.append(f"claims: {', '.join(CLAIMS)}, each a whole number from 1 to 365")
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
    sp = policy.get("security-patch", {})
    count = lambda v, top: isinstance(v, int) and not isinstance(v, bool) and 0 < v <= top
    if (not isinstance(sp, dict) or set(sp) - {"max-files", "max-lines", "forbidden", "reviewer-model"}
            or not count(sp.get("max-files", 1), 100) or not count(sp.get("max-lines", 1), 5000)
            or not (isinstance(sp.get("forbidden", []), list) and all(isinstance(g, str) and g for g in sp.get("forbidden", [])))
            or not (isinstance(sp.get("reviewer-model", "x"), str) and re.fullmatch(r"claude-[a-z0-9.-]+", sp.get("reviewer-model", "claude-x")))):
        out.append("security-patch: max-files (1 to 100), max-lines (1 to 5000), forbidden (a list of globs), reviewer-model (a Claude model)")
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
        if "constitution-merge" in lane and name != CONSTITUTION_LANE:
            out.append(f"lanes.{name}.constitution-merge: only the {CONSTITUTION_LANE} lane may merge in a protected path")
        for part in ("merge", "ceiling", "constitution-merge"):
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


def constitution_merge(policy, lane_name, protected, widening):
    """(may it merge, the caps or why not) for a pull request of LANE_NAME
    that touches the protected paths PROTECTED (the golden rule, #397).
    Nothing protected: the lane's own `merge`. Otherwise only a lane with
    `constitution-merge`, and only when WIDENING (scripts/no-widening.py's
    lines, ["unknown"] when it could not tell) is empty: a change that widens
    a permission, a lane or a limit is always a person's. Pure."""
    lane = (policy.get("lanes") or {}).get(lane_name) or {}
    if not protected:
        return True, lane.get("merge") or {}
    shown = ", ".join(protected[:3])
    caps = lane.get("constitution-merge") if lane_name == CONSTITUTION_LANE else None
    if not caps:
        return False, f"it touches rules that govern autonomy ({shown}): a person merges it"
    if widening:
        return False, f"it touches rules that govern autonomy ({shown}) and widens them ({'; '.join(widening)[:300]}): a person merges it"
    return True, caps


def lane_app(origin):
    """The App that opens a lane's issues: its origin's `app`, else the
    organisation's own (org.yml, or the caller's DX_BOT_APP, #568); "" when
    neither names one, which every lane check refuses (NO_APP)."""
    return str((origin or {}).get("app") or org.APP)


NO_APP = "no App opens this lane's issues (the lane's origin `app`, org.yml's bot or DX_BOT_APP): a person takes it"


def lane_people(origin):
    """Who may run a sync lane's script beside its App: its origin's
    `people`, else the organisation's maintainers (org.yml, #568)."""
    origin = origin or {}
    return list(origin.get("people") or []) if "people" in origin else list(org.MAINTAINERS)


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
    if origin.get("evidence") == "published-advisory":
        return carry_accepts(name, lane, issue, repository, sync or {})
    if origin.get("parent"):
        return delegated_accepts(name, lane, issue, repository)
    app = lane_app(origin)
    if not app:
        return False, NO_APP
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
    its parent open, or closed as completed (the decision carried out while
    its sub-issues elsewhere are still open, #572), in the organisation,
    accepted by a person (the last
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
    if parent.get("state") == "CLOSED" and parent.get("stateReason") != "COMPLETED":
        return False, f"its parent {ref} was closed without being completed"
    if parent.get("state") not in ("OPEN", "CLOSED"):
        return False, f"its parent {ref} is neither open nor closed as completed"
    if "accepted" not in [n.get("name") for n in ((parent.get("labels") or {}).get("nodes") or [])]:
        return False, f"its parent {ref} is not accepted"
    event = last_label_event(parent, "accepted")
    if not event or event.get("__typename") != "LabeledEvent" or (event.get("actor") or {}).get("__typename") != "User":
        return False, f"its parent {ref} was not accepted by a person"
    app = lane_app(lane.get("origin"))
    author = login((issue.get("author") or {}).get("login"))
    if issue.get("authorAssociation") not in MEMBERS and (not app or author != login(app)):
        return False, "the sub-issue was not opened by a member of the organisation"
    linked = [e.get("createdAt") for e in ((issue.get("timelineItems") or {}).get("nodes") or []) if e.get("__typename") == "ParentIssueAddedEvent"]
    if not linked:
        return False, "its link to the parent could not be read"
    edited = issue.get("lastEditedAt")
    if edited and edited > linked[-1]:
        return False, "the sub-issue was edited after it was linked to its parent"
    return True, f"accepted by policy: lane {name}, a sub-issue of {ref}, which {(event.get('actor') or {}).get('login')} accepted"


# --- the security-carry lane (#287): a published patch, into the default branch

def carry_branch(lane, issue_number, version):
    """The branch the lane's pull request comes from."""
    pattern = (lane.get("origin") or {}).get("branch") or "fix/{issue}-carry-security-fix-of-{version}"
    return pattern.format(issue=issue_number, version=version.replace(".", "-"))


def patched(advisory, version):
    """Whether a published advisory names `version` among its patched
    versions. Pure."""
    if not isinstance(advisory, dict) or advisory.get("state") != "published":
        return False
    for v in advisory.get("vulnerabilities") or []:
        names = [x.strip().lstrip("v=") for x in str((v or {}).get("patched_versions") or "").split(",")]
        if version in names:
            return True
    return False


def carry_accepts(name, lane, issue, repository, carry):
    """(True, why) when the security-carry lane accepts the issue: opened by
    the lane's App, which added its label last, never edited, a Bug, naming
    a version and its advisory; and GitHub shows that advisory published
    with that version patched and that version released. Only dilux-security
    publishes advisories, once a maintainer approved the patch (patch:go):
    that is the acceptance this lane carries. Pure: `carry` holds
    advisory(ghsa) and released(version)."""
    app = lane_app(lane.get("origin"))
    if not app:
        return False, NO_APP
    if login((issue.get("author") or {}).get("login")) != login(app):
        return False, f"the issue was not opened by {app}"
    event = last_label_event(issue, f"lane:{name}")
    if not event or event.get("__typename") != "LabeledEvent" or login((event.get("actor") or {}).get("login")) != login(app):
        return False, f"the last to add lane:{name} was not {app}"
    if issue.get("lastEditedAt"):
        return False, "the issue was edited after it was opened"
    if lane.get("type") and ((issue.get("issueType") or {}).get("name") or "") != lane["type"]:
        return False, f"the issue's Type is not {lane['type']}"
    m = CARRY_MARKER.search(issue.get("body") or "")
    if not m or m.group(1) != name:
        return False, "the issue does not name the version and the advisory it carries"
    version, ghsa = m.group(2), m.group(3)
    read_advisory, released = carry.get("advisory"), carry.get("released")
    if not read_advisory or not released:
        return False, "the advisory and the release could not be read"
    if not patched(read_advisory(ghsa), version):
        return False, f"{ghsa} is not a published advisory of this repository that names {version} patched"
    if not released(version):
        return False, f"{version} is not released"
    return True, f"accepted by policy: lane {name}, the fix of {version}, released, with {ghsa} published"


def carry_merge(policy, issue, repository, autopilot_var, carry, review):
    """(True, why) when the lane's pull request merges on its own: the lane
    accepts its issue, it is the App's, from the lane's branch, the review
    does not block, its description is true, within the lane's caps, and its
    commits are exactly the released patch's fix (each one patch-equivalent
    to a commit of the fix, and every commit of the fix carried). Pure:
    `carry` also holds pr and equivalent(version, base, head) -> (ok, why)."""
    ok, why = lane_accepts(policy, issue, None, repository, autopilot_var, carry)
    if not ok:
        return False, why
    name = next(l[len("lane:"):] for l in (n.get("name") or "" for n in issue["labels"]["nodes"]) if l.startswith("lane:"))
    lane = policy["lanes"][name]
    version = CARRY_MARKER.search(issue.get("body") or "").group(2)
    pr = carry.get("pr") or {}
    app = lane_app(lane.get("origin"))
    if not app:
        return False, NO_APP
    if login((pr.get("author") or {}).get("login")) != login(app):
        return False, f"the pull request was not opened by {app}"
    want = carry_branch(lane, issue.get("number"), version)
    if pr.get("headRefName") != want:
        return False, f"the pull request does not come from {want}"
    if review.get("blocking") != "false":
        return False, "the review is blocking"
    if review.get("description_ok") != "true":
        return False, "the description does not match the code"
    caps = lane.get("merge") or {}
    for key, cap in (("risk", caps.get("max-risk", "none")), ("complexity", caps.get("max-complexity", "none"))):
        level = review.get(key) or ""
        if level not in LEVELS or cap not in LEVELS or level == "none" or LEVELS.index(level) > LEVELS.index(cap):
            return False, f"{key} {level or 'unknown'} is above the lane's {cap}"
    equivalent = carry.get("equivalent")
    if not equivalent:
        return False, "the pull request's commits could not be compared with the patch"
    same, why = equivalent(version, pr.get("baseRefOid", ""), pr.get("headRefOid", ""))
    if not same:
        return False, why
    return True, f"merges by policy: lane {name}, the fix of {version} as it was released"


def carry_lane_of(policy, issue):
    """The security-carry lane an issue's lane:<name> label names, or None."""
    for n in ((issue.get("labels") or {}).get("nodes") or []):
        name = (n.get("name") or "")
        if name.startswith("lane:") and ((((policy.get("lanes") or {}).get(name[len("lane:"):]) or {}).get("origin") or {}).get("evidence")) == "published-advisory":
            return name[len("lane:"):]
    return None


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
    app = lane_app(origin)
    allowed = {login(app)} | {login(p) for p in lane_people(origin)}
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


def job_vs_template(have, before, want, owned, values=None):
    """Why a caller's job, as a sync run changed it, is not its template's
    job (`want`); None when it is. The inputs the template says to fill in
    (`owned`) and the inputs it does not set are the repository's: they
    keep the values they had, but a template's placeholder, which becomes
    the value repos.yml gives (`values`, #562); one left is refused."""
    if plain(have.get("if", "")) != plain(want.get("if", "")):
        return f"runs if `{plain(have.get('if', '')) or 'always'}`, not the template's"
    if not needs_of(want) <= needs_of(have):
        return "does not wait for every job the template's waits for"
    tw, hw, bw = want.get("with") or {}, have.get("with") or {}, (before or {}).get("with") or {}
    for key, value in tw.items():
        if key in owned:
            given = (values or {}).get(key)
            filled = key in (values or {}) and plain(bw.get(key)) == plain(value) and plain(hw.get(key)) == plain(given)
            if before is not None and key in bw and plain(hw.get(key)) != plain(bw[key]) and not filled:
                return f"changes `{key}`, which is the repository's to fill in"
            if key in (values or {}) and key in hw and plain(hw[key]) == plain(value) and plain(value) != plain(given):
                return f"still holds `{key}` at the template's placeholder, where repos.yml gives a value"
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


def moved_major(before, have, majors):
    """Whether the job have is before with its call of a shared workflow
    moved to a newer major of that same workflow, one of majors (those the
    templates call), and nothing else changed (#320: a callers-only major).
    Pure."""
    if not isinstance(before, dict) or not isinstance(have, dict):
        return False
    old, new = str(before.get("uses") or ""), str(have.get("uses") or "")
    if not (SHARED_USES.fullmatch(old) and SHARED_USES.fullmatch(new)):
        return False
    (wo, vo), (wn, vn) = old.rsplit("@v", 1), new.rsplit("@v", 1)
    return (wo == wn and int(vo) < int(vn) and int(vn) in majors
            and {k: v for k, v in before.items() if k != "uses"} == {k: v for k, v in have.items() if k != "uses"})


def caller_problem(path, base_text, head_text, templates, owned, values=None, texts=None):
    """(why, high): why a caller the pull request changes is more than a
    sync run of the callers writes, and whether that is a change of
    permissions or secrets (high risk); (None, False) when it is not.
    `templates` is {name: data} at the commit the issue names; `owned` is
    {template: [inputs]} from repos.yml there (`callers.repository-owned`);
    `values` the repository's caller values there (#562) and `texts` the
    templates' text: a new caller is its template with those values."""
    if base_text is None:
        if new_caller_ok(path, head_text, texts or {}, owned, values):
            return None, False
        return f"{path} is a new workflow, not its template with the values repos.yml gives", False
    try:
        base, head = parse_text(base_text), parse_text(head_text)
    except ValueError:
        return f"{path} does not parse", False
    if not isinstance(base, dict) or not isinstance(head, dict):
        return f"{path} is not a workflow", False
    if {k: v for k, v in base.items() if k != "jobs"} != {k: v for k, v in head.items() if k != "jobs"}:
        return f"{path} changes more than its jobs (its triggers, permissions or settings)", False
    bj, hj = jobs_of(base), jobs_of(head)
    # The majors the templates call: the one a callers-only move goes to.
    majors = {int(u.rsplit("@v", 1)[1]) for d in templates.values() for j in jobs_of(d).values()
              if isinstance(j, dict) and SHARED_USES.fullmatch(u := str(j.get("uses") or ""))}
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
        if moved_major(before, have, majors):
            # Its call at a newer major and nothing else (#320).
            continue
        found = [(t, jobs_of(d)[job]) for t, d in sorted(templates.items())
                 if isinstance(jobs_of(d).get(job), dict) and jobs_of(d)[job].get("uses") == uses]
        if not found:
            return f"{path}: the job {job} is no template's job (workflow-templates/ at the commit named)", False
        whys = [job_vs_template(have, before, want, set(owned.get(t) or []), values) for t, want in found]
        if all(whys):
            return f"{path}: the job {job} {whys[0]}", False
        # A new job is a grant of its own, whatever it asks for.
        if before is None:
            return f"{path}: the job {job} is new, with the permissions and secrets it gets: high risk, a person merges it", True
        if have.get("permissions") != before.get("permissions") or have.get("secrets") != before.get("secrets"):
            return f"{path}: the job {job} changes its permissions or the secrets it passes: high risk, a person merges it", True
    return None, False


def new_caller_ok(path, head_text, texts, owned, values):
    """Whether a new caller is what a sync run writes for a repository that
    lacks it (#552, #562): .github/workflows/<template>, the template's text
    at the commit with its default branch and the values repos.yml gives."""
    name = path.rsplit("/", 1)[-1]
    if values is None or path != f".github/workflows/{name}" or texts.get(name) is None or head_text is None:
        return False
    token = "DXDEFAULTBRANCHDX"
    want = sync_module().fill_inputs(texts[name].replace("$default-branch", token), set(owned.get(name) or []), values)
    first, *rest = re.escape(want).split(token)
    pattern = first + "".join(("([A-Za-z0-9._/-]+)" if i == 0 else "\\1") + part for i, part in enumerate(rest))
    return re.fullmatch(pattern, head_text) is not None


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
    short = repository.split("/")[-1]
    kind = entry_kind(conf, short)
    if mode == "files":
        stale = conf.get("files") != conf_now.get("files") or facts.get("agents-block.md") != now.get("agents-block.md")
    elif mode in ("pre-pr", "dependabot"):
        # That run's sources: the kind's pack and templates, the default
        # template and the repository's entry (#562).
        stale = (kind != entry_kind(conf_now, short) or (facts.get("kinds") or {}).get(kind) != (now.get("kinds") or {}).get(kind)
                 or facts.get("dependabot-default") != now.get("dependabot-default")
                 or repos_conf.entry(conf, short) != repos_conf.entry(conf_now, short))
    else:
        stale = (facts.get("templates") != now.get("templates") or conf.get("callers") != conf_now.get("callers")
                 or repos_conf.caller_values(conf, short) != repos_conf.caller_values(conf_now, short))
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
            problem, _ = caller_problem(path, base.get(path), head[path], templates, owned, repos_conf.caller_values(conf, short), facts.get("templates"))
            if problem:
                return False, problem
        elif mode == "pre-pr":
            problem = pre_pr_problem(path, base.get(path), head[path], ((facts.get("kinds") or {}).get(kind) or {}).get("pack.yml"))
            if problem:
                return False, problem
        elif mode == "dependabot":
            problem = dependabot_problem(path, head[path], facts, kind, repos_conf.value(conf, short, "dependabot") or {}, change.get("root"))
            if problem:
                return False, problem
        else:
            return False, f"no rule says what a {mode} run may write"
    return True, f"merges by policy: lane {name}, risk {review.get('risk')}, complexity {review.get('complexity')}, every file what {CENTRAL}@{org[:12]} holds"


def entry_kind(conf, name):
    """The kind repos.yml gives a repository with exactly one, else None."""
    kinds = repos_conf.value(conf, name, "kinds") or []
    return kinds[0].get("kind") if len(kinds) == 1 and isinstance(kinds[0], dict) else None


def pre_pr_module():
    spec = importlib.util.spec_from_file_location("pre_pr", os.path.join(HERE, "pre-pr.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pre_pr_problem(path, base_text, head_text, pack_text):
    """Why a file a pre-pr run's pull request writes is not what the run
    writes (#562): dx.mk is the kind's `pre-pr-make` rendered, the Makefile
    its base with `include dx.mk` added and nothing else; None when it is."""
    pre_pr = pre_pr_module()
    if path == pre_pr.FRAGMENT:
        try:
            pack = parse_text(pack_text) if pack_text is not None else None
        except ValueError:
            pack = None
        want = pre_pr.render((pack or {}).get("pre-pr-make")) if isinstance(pack, dict) else None
        if want is None:
            return f"{path}: the repository's kind has no `pre-pr-make` at the commit named"
        return None if head_text == want else f"{path} is not its kind's `pre-pr-make` at the commit named"
    if path == "Makefile":
        if pre_pr.own_recipe(base_text):
            return "Makefile: its own `pre-pr` has a recipe, which a pre-pr run never includes dx.mk over"
        return None if head_text == pre_pr.with_include(base_text) else "Makefile changes more than adding `include dx.mk`"
    return f"no rule says what a pre-pr run may write in {path}"


def dependabot_problem(path, head_text, facts, kind, extra, root):
    """Why .github/dependabot.yml is not what a dependabot run writes (#562):
    its kind's template (or the organisation's default) at the commit,
    rendered for the ecosystems the head's root has and what repos.yml adds;
    None when it is."""
    if path != ".github/dependabot.yml":
        return f"no rule says what a dependabot run may write in {path}"
    if root is None:
        return "the names at the root of its head could not be read"
    default = facts.get("dependabot-default")
    template = ((facts.get("kinds") or {}).get(kind) or {}).get("dependabot.yml") or default
    if template is None or default is None:
        return "the Dependabot templates at the commit named could not be read"
    sync = sync_module()
    try:
        want = sync.render_dependabot(template, sync.dependabot_ecosystems(set(root), extra), extra, default)
    except ValueError as exc:
        return f"{path}: {exc}"
    return None if head_text == want else f"{path} is not its kind's template at the commit named, for the ecosystems its head has"


def adopt_lane_of(policy, issue):
    """The adopt lane an issue's lane:<name> label names (#562), or None."""
    for n in ((issue.get("labels") or {}).get("nodes") or []):
        name = (n.get("name") or "")
        if name.startswith("lane:") and ((((policy.get("lanes") or {}).get(name[len("lane:"):]) or {}).get("origin") or {}).get("adopt")):
            return name[len("lane:"):]
    return None


def adopt_module():
    spec = importlib.util.spec_from_file_location("detect", os.path.join(HERE, "detect.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def adopt_issue(issue, repository, maintainer):
    """(name, entry, why) of an Adopt issue a maintainer accepted (#562):
    the repository it names and the entry its block proposes, as it was when
    `accepted` was added; (None, None, why) when it is not one."""
    if repository.lower() != CENTRAL.lower():
        return None, None, f"an Adopt issue is {CENTRAL}'s alone"
    name, entry = adopt_module().adopt_of(issue.get("body") or "")
    if not name or entry is None:
        return None, None, "the issue carries no dx-adopt marker and one entry for the repository it names"
    if issue.get("title") != f"Adopt {name}":
        return None, None, f"its title is not \"Adopt {name}\""
    event = last_label_event(issue, "accepted")
    actor = (event or {}).get("actor") or {}
    if not event or event.get("__typename") != "LabeledEvent" or actor.get("__typename") != "User" or not maintainer(actor.get("login") or ""):
        return None, None, "the last to add `accepted` was not a person with the admin or maintain role"
    if "lastEditedAt" not in issue:
        return None, None, "the issue's edit history could not be read"
    if issue.get("lastEditedAt") and (not event.get("createdAt") or issue["lastEditedAt"] > event["createdAt"]):
        return None, None, "the issue's text was edited after it was accepted"
    return name, entry, f"accepted by {actor.get('login')}"


def adopt_accepts(policy, issue, repository, autopilot_var, facts):
    """(True, why) when the adopt lane's pull request is the issue's entry
    and nothing else (#562); (False, why) otherwise. Pure: `facts` holds
    maintainer(login), pr (its author and branch), change() (its files, with
    repos.yml at its base and head) and problems(conf), repos-config.py's."""
    if (autopilot_var or "").strip().lower() == "off":
        return False, "the organisation's DX_AUTOPILOT is off"
    if not policy.get("autopilot", False):
        return False, "the autopilot is off in the policy"
    lane_name = adopt_lane_of(policy, issue)
    if not lane_name:
        return False, "the issue is no adopt lane's"
    lane = policy["lanes"][lane_name]
    # A maintainer accepts its issue (`accept: human`): the lane only merges.
    if not lane.get("enabled", True):
        return False, f"the lane {lane_name} is off"
    if repository.split("/", 1)[-1] not in (lane.get("repositories") or []):
        return False, f"the lane {lane_name} does not cover {repository}"
    origin = lane.get("origin") or {}
    want = lane.get("type")
    if want and (issue.get("issueType") or {}).get("name") != want:
        return False, f"the issue's Type is not {want}"
    name, entry, why = adopt_issue(issue, repository, facts["maintainer"])
    if not name:
        return False, why
    pr = facts.get("pr") or {}
    app = lane_app(origin)
    if not app:
        return False, NO_APP
    if login((pr.get("author") or {}).get("login")) != login(app):
        return False, f"the pull request was not opened by {app}"
    branch = (origin.get("branch") or "").format(issue=issue.get("number"))
    if not branch or pr.get("headRefName") != branch:
        return False, f"its branch is not the lane's ({branch or 'none named'})"
    change = facts["change"]() if facts.get("change") else None
    if not change:
        return False, "what the pull request changes could not be read"
    if [(f.get("path"), f.get("status")) for f in change.get("files") or []] != [("repos.yml", "modified")]:
        return False, "it changes more than repos.yml, or does not modify it"
    base_text, head_text = (change.get("base") or {}).get("repos.yml"), (change.get("head") or {}).get("repos.yml")
    if base_text is None or head_text is None:
        return False, "repos.yml at its base or head could not be read"
    import difflib
    ops = {op for op, *_ in difflib.SequenceMatcher(None, base_text.split("\n"), head_text.split("\n"), autojunk=False).get_opcodes()}
    if ops - {"equal", "insert"}:
        return False, "repos.yml changes lines of its base, not only adds"
    try:
        base, head = parse_text(base_text), parse_text(head_text)
    except ValueError:
        return False, "repos.yml does not parse"
    if not isinstance(base, dict) or not isinstance(head, dict) or not isinstance(head.get("repos"), dict):
        return False, "repos.yml is not a mapping with `repos:`"
    if name in (base.get("repos") or {}):
        return False, f"{name} is already in repos.yml"
    rest = dict(head, repos={k: v for k, v in head["repos"].items() if k != name})
    if rest != base or head["repos"].get(name) != entry:
        return False, f"repos.yml is not its base with {name}'s entry, as the issue proposes it, alone"
    found = facts["problems"](head)
    if found:
        return False, f"repos.yml does not hold to its schema: {found[0]}"
    return True, f"lane {lane_name}: {name}'s entry, as the Adopt issue {why} proposes it, and nothing else"


def adopt_merge(policy, issue, repository, autopilot_var, facts, review):
    """(True, why) when the adopt lane's pull request merges on its own."""
    ok, why = adopt_accepts(policy, issue, repository, autopilot_var, facts)
    if not ok:
        return False, why
    if review.get("blocking") != "false":
        return False, "the review is blocking"
    if review.get("description_ok") != "true":
        return False, "the description does not match the code"
    caps = policy["lanes"][adopt_lane_of(policy, issue)].get("merge") or {}
    for key, cap in (("risk", caps.get("max-risk", "none")), ("complexity", caps.get("max-complexity", "none"))):
        level = review.get(key) or ""
        if level not in LEVELS or cap not in LEVELS or level == "none" or LEVELS.index(level) > LEVELS.index(cap):
            return False, f"{key} {level or 'unknown'} is above the lane's {cap}"
    return True, f"merges by policy: {why}, risk {review.get('risk')}, complexity {review.get('complexity')}"


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
      number title body lastEditedAt authorAssociation author { login } issueType { name }
      labels(first: 50) { nodes { name } }
      timelineItems(itemTypes: [LABELED_EVENT, UNLABELED_EVENT, PARENT_ISSUE_ADDED_EVENT], last: 100) {
        nodes {
          __typename
          ... on LabeledEvent { createdAt label { name } actor { __typename login } }
          ... on UnlabeledEvent { label { name } actor { __typename login } }
          ... on ParentIssueAddedEvent { createdAt }
        }
      }
      parent {
        number state stateReason repository { nameWithOwner }
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
    # The names at its head's root: the ecosystems a dependabot run writes for.
    listing = gh_bytes("api", f"repos/{repository}/contents/?ref={pr['headRefOid']}")
    root = [e.get("name") for e in json.loads(listing)] if listing else None
    return {"files": files, "head": head, "base": base, "root": root}


def org_sources(ref):
    """The files a sync run writes from, in DiluxOne/.github at `ref`;
    repos.yml None when any could not be read."""
    out = {"repos.yml": raw(CENTRAL, "repos.yml", ref), "agents-block.md": raw(CENTRAL, "agents-block.md", ref)}
    listing = gh_bytes("api", f"repos/{CENTRAL}/contents/workflow-templates?ref={ref}")
    names = [e["name"] for e in json.loads(listing)] if listing else []
    out["templates"] = {n: raw(CENTRAL, f"workflow-templates/{n}", ref) for n in names if n.endswith((".yml", ".yaml"))}
    if listing is None or any(t is None for t in out["templates"].values()):
        out["repos.yml"] = None
    # The pre-pr and dependabot runs' sources (#562): each kind's pack and
    # Dependabot template, and the organisation's default template.
    out["dependabot-default"] = raw(CENTRAL, "policy/dependabot.default.yml", ref)
    kinds = gh_bytes("api", f"repos/{CENTRAL}/contents/kinds?ref={ref}")
    out["kinds"] = {e["name"]: {"pack.yml": raw(CENTRAL, f"kinds/{e['name']}/pack.yml", ref),
                                "dependabot.yml": raw(CENTRAL, f"kinds/{e['name']}/dependabot.yml", ref)}
                    for e in (json.loads(kinds) if kinds else []) if e.get("type") == "dir"}
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


def maintainer_of(repository):
    """login -> whether that person has the admin or maintain role in the
    repository, read from GitHub."""
    def has(name):
        out = gh_bytes("api", f"repos/{repository}/collaborators/{name}/permission", "--jq", ".role_name")
        return (out or "").strip() in ("admin", "maintain")
    return has


def adopt_from_env(repository):
    """What the adopt lane reads (#562), from GitHub, each read once."""
    sync = sync_from_env(repository, False)

    def problems(conf):
        spec = importlib.util.spec_from_file_location("repos_config", os.path.join(HERE, "repos-config.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        root = os.path.join(HERE, "..")
        return mod.problems(conf, mod.dirs(os.path.join(root, "kinds")), mod.dirs(os.path.join(root, "design-systems")))
    return {"maintainer": maintainer_of(repository), "pr": sync["pr"], "change": sync["change"], "problems": problems}


def carry_from_env(repository, pr=None):
    """What the security-carry lane reads, from fixtures the environment
    names (LANE_ADVISORY, LANE_RELEASED, LANE_EQUIVALENT) or from GitHub."""
    env = os.environ

    def advisory(ghsa):
        if env.get("LANE_ADVISORY"):
            return load_json(env["LANE_ADVISORY"])
        out = subprocess.run(["gh", "api", f"repos/{repository}/security-advisories/{ghsa}"], capture_output=True, text=True)
        return json.loads(out.stdout) if out.returncode == 0 else None

    def released(version):
        if env.get("LANE_RELEASED"):
            return env["LANE_RELEASED"] == "true"
        out = subprocess.run(["gh", "api", f"repos/{repository}/releases/tags/{version}", "--jq", ".tag_name"], capture_output=True, text=True)
        return out.returncode == 0 and out.stdout.strip() == version

    def equivalent(version, base, head):
        if env.get("LANE_EQUIVALENT"):
            got = load_json(env["LANE_EQUIVALENT"])
            return bool(got.get("ok")), got.get("why", "")
        return git_equivalent(repository, version, base, head)
    return {"advisory": advisory, "released": released, "equivalent": equivalent, "pr": pr}


def carry_module():
    spec = importlib.util.spec_from_file_location("carry_lock", os.path.join(HERE, "carry-lock.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git_equivalent(repository, version, base, head, cwd=None):
    """(ok, why): whether base..head is exactly the fix of the security
    patch `version` (scripts/carry-lock.py): no merge commit, and its whole
    diff has the patch id of the fix's whole diff, so nothing is added,
    left out or hidden. Fetched into a scratch repository with GH_TOKEN;
    anything that fails is a no."""
    import tempfile
    cl = carry_module()
    if not re.fullmatch(r"[0-9a-f]{40}", base or "") or not re.fullmatch(r"[0-9a-f]{40}", head or ""):
        return False, "the pull request's base and head could not be read"
    with tempfile.TemporaryDirectory() as d:
        work = cwd or d
        try:
            if not cwd:
                cl.git("init", "-q", cwd=work)
                auth = "AUTHORIZATION: basic " + __import__("base64").b64encode(f"x-access-token:{os.environ.get('GH_TOKEN', '')}".encode()).decode()
                cl.git("-c", f"http.extraheader={auth}", "fetch", "-q", f"https://github.com/{repository}", "+refs/tags/*:refs/tags/*", base, head, cwd=work)
            tag = version if version in cl.git("tag", "-l", cwd=work).split() else f"v{version}"
            merges = cl.git("rev-list", "--merges", f"{base}..{head}", cwd=work).split()
            commits = cl.git("rev-list", f"{base}..{head}", cwd=work).split()
            ours = cl.patch_id(cl.git("diff", base, head, cwd=work), work)
            want = cl.fix_id(tag, cwd=work)
        except RuntimeError as exc:
            return False, f"the patch could not be compared ({str(exc)[:160]})"
    if not commits:
        return False, "the pull request carries no commit"
    if merges:
        return False, f"the pull request holds a merge commit ({merges[0][:12]}): only the fix's commits"
    if not want or ours != want:
        return False, f"what the pull request changes is not the fix of {version} as it was released"
    return True, f"what it changes is the fix of {version} as it was released"


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
    pol = load(os.environ.get("ORG_AUTONOMY") or os.path.join(HERE, "..", "policy", "autonomy.yml"))
    return merge(pol, load(os.environ.get("REPO_AUTONOMY")), os.environ.get("GITHUB_REPOSITORY", ""))


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
    check("#488 claims: a repository lowers a limit, never raises it",
          [merge(org, {"claims": {"release-days": 5}})["claims"]["release-days"], merge(org, {"claims": {"release-days": 50}})["claims"]["release-days"]], [5, 10])
    check("#488 claims: an unknown key or a day count that is not a number", [problems({**org, "claims": {"x": 1}}) != [], problems({**org, "claims": {"remind-days": "7"}}) != []], [True, True])
    check("the organisation's policy has the eight lanes", sorted(org.get("lanes", {})), ["adopt", "bugfix-reproduced", "delegated", "human-issue", "org-sync", "platform", "release", "security-carry"])
    # The security-carry lane (#287).
    pol_c = merge(org, {})
    lane_c = pol_c["lanes"]["security-carry"]
    ghsa = "GHSA-abcd-efgh-ijkl"
    body_c = f"<!-- dx-lane: security-carry version: 2.1.1 ghsa: {ghsa} -->\nCarry it."
    issue_c = lambda **k: {"number": 9, "body": k.get("body", body_c), "lastEditedAt": k.get("edited"), "author": {"login": k.get("author", "dilux-bot")},
                           "issueType": {"name": k.get("type", "Bug")}, "labels": {"nodes": [{"name": "lane:security-carry"}]},
                           "timelineItems": {"nodes": [{"__typename": "LabeledEvent", "label": {"name": "lane:security-carry"}, "actor": {"__typename": "Bot", "login": k.get("actor", "dilux-bot")}}]}}
    adv = {"state": "published", "vulnerabilities": [{"patched_versions": "2.1.1"}]}
    carry_ok = {"advisory": lambda g: adv if g == ghsa else None, "released": lambda v: v == "2.1.1"}
    acc = lambda iss, c=carry_ok: lane_accepts(pol_c, iss, None, "DiluxOne/x", "", c)[0]
    check("#287 carry: the bot's untouched Bug naming a published, released patch is accepted", acc(issue_c()), True)
    check("#287 carry: another author, a person's label, an edit, another Type, no marker",
          [acc(issue_c(author="someone")), acc(issue_c(actor="someone")), acc(issue_c(edited="2026-10-18T00:00:00Z")), acc(issue_c(type="Feature")), acc(issue_c(body="Carry it."))],
          [False] * 5)
    check("#287 carry: an advisory not published, not naming the version, or no release",
          [acc(issue_c(), {**carry_ok, "advisory": lambda g: {**adv, "state": "draft"}}), acc(issue_c(), {**carry_ok, "advisory": lambda g: {**adv, "vulnerabilities": [{"patched_versions": "2.1.2"}]}}),
           acc(issue_c(), {**carry_ok, "released": lambda v: False})], [False, False, False])
    check("#287 carry: patched versions read from a list", (patched({"state": "published", "vulnerabilities": [{"patched_versions": "1.9.9, 2.1.1"}]}, "2.1.1"), patched(None, "2.1.1")), (True, False))
    pr_c = {"number": 10, "author": {"login": "dilux-bot[bot]"}, "headRefName": "fix/9-carry-security-fix-of-2-1-1", "baseRefOid": "a" * 40, "headRefOid": "b" * 40}
    review_ok = {"risk": "high", "complexity": "low", "blocking": "false", "description_ok": "true"}
    merge_c = lambda pr=pr_c, review=review_ok, same=(True, "same"): carry_merge(pol_c, issue_c(), "DiluxOne/x", "", {**carry_ok, "pr": pr, "equivalent": lambda v, b, h: same}, review)[0]
    check("#287 carry merge: the released fix, from the lane's branch, a review that does not block", merge_c(), True)
    check("#287 carry merge: another branch, another author, a blocking review, commits that are not the fix",
          [merge_c(pr={**pr_c, "headRefName": "fix/9-other"}), merge_c(pr={**pr_c, "author": {"login": "someone"}}), merge_c(review={**review_ok, "blocking": "true"}), merge_c(same=(False, "extra"))],
          [False] * 4)
    check("#287 carry merge: off with DX_AUTOPILOT", carry_merge(pol_c, issue_c(), "DiluxOne/x", "off", {**carry_ok, "pr": pr_c, "equivalent": lambda v, b, h: (True, "")}, review_ok)[0], False)
    import tempfile as _tfc
    with _tfc.TemporaryDirectory() as d:
        envg = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        g = lambda *a: subprocess.run(["git", *a], cwd=d, env=envg, capture_output=True, text=True, check=True).stdout.strip()

        def put(path, text):
            with open(os.path.join(d, path), "w", encoding="utf-8") as fh:
                fh.write(text)
        g("init", "-q", "-b", "main")
        put("a.php", "<?php\n$a = 1;\n")
        put("b.php", "<?php\n$b = 1;\n")
        g("add", "-A")
        g("commit", "-q", "-m", "feat: one")
        g("tag", "1.0.0")
        put("b.php", "<?php\n$b = 2;\n")
        g("commit", "-qam", "feat: two")
        main_sha = g("rev-parse", "HEAD")
        g("checkout", "-q", "-b", "security/1.0.1", "1.0.0")
        put("a.php", "<?php\n$a = esc_html( 1 );\n")
        g("commit", "-qam", "fix: escape a")
        fix_sha = g("rev-parse", "HEAD")
        g("commit", "-q", "--allow-empty", "-m", "chore(release): 1.0.1, a security patch")
        g("tag", "1.0.1")
        g("checkout", "-q", "-b", "carry", main_sha)
        g("cherry-pick", fix_sha)
        carried = g("rev-parse", "HEAD")
        g("checkout", "-q", "-b", "merged", main_sha)
        g("merge", "-q", "--no-ff", "-m", "merge", carried)
        put("b.php", "<?php\n$b = 9;\n")
        g("commit", "-q", "--amend", "-am", "merge, with something hidden")
        hidden = g("rev-parse", "HEAD")
        g("checkout", "-q", "carry")
        put("b.php", "<?php\n$b = 3;\n")
        g("commit", "-qam", "fix: something else")
        extra = g("rev-parse", "HEAD")
        kept = os.environ.get("GIT_CONFIG_GLOBAL")
        os.environ["GIT_CONFIG_GLOBAL"] = "/dev/null"
        try:
            check("#287 carry merge (git): the fix cherry-picked is the fix; one commit more is not; nothing is not",
                  (git_equivalent("o/r", "1.0.1", main_sha, carried, cwd=d)[0], git_equivalent("o/r", "1.0.1", main_sha, extra, cwd=d)[0],
                   git_equivalent("o/r", "1.0.1", main_sha, main_sha, cwd=d)[0]), (True, False, False))
            check("#287 carry merge (git): a merge commit, even one hiding a change, is not the fix", git_equivalent("o/r", "1.0.1", main_sha, hidden, cwd=d)[0], False)
        finally:
            if kept is None:
                os.environ.pop("GIT_CONFIG_GLOBAL", None)
            else:
                os.environ["GIT_CONFIG_GLOBAL"] = kept
    check("#287 carry: the lane is told apart from a sync lane", (carry_lane_of(pol_c, issue_c()), sync_lane_of(pol_c, issue_c())), ("security-carry", None))

    # #189: a sub-issue of an issue a person accepted.
    def child(parent_labels=("accepted",), actor="User", state="OPEN", where="DiluxOne/.github", assoc="MEMBER",
              author="someone", edited=None, linked="2026-10-16T10:00:00Z", labels=(), parent=True, unlabeled=False, reason=None):
        events = [{"__typename": "LabeledEvent", "label": {"name": "accepted"}, "actor": {"__typename": actor, "login": "soydiloreto" if actor == "User" else "dilux-bot"}}]
        if unlabeled:
            events.append({"__typename": "UnlabeledEvent", "label": {"name": "accepted"}, "actor": {"__typename": "User", "login": "soydiloreto"}})
        return {"number": 9, "body": "Carry it out here.", "author": {"login": author}, "authorAssociation": assoc, "lastEditedAt": edited,
                "labels": {"nodes": [{"name": n} for n in labels]},
                "timelineItems": {"nodes": [{"__typename": "ParentIssueAddedEvent", "createdAt": linked}] if linked else []},
                "parent": {"number": 189, "state": state, "stateReason": reason, "repository": {"nameWithOwner": where},
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
    check("#572: a parent closed as completed still stands", acc(child(state="CLOSED", reason="COMPLETED"))[0], True)
    check("#572: a parent closed as not planned takes it back", acc(child(state="CLOSED", reason="NOT_PLANNED")), (False, "its parent DiluxOne/.github#189 was closed without being completed"))
    check("#572: a parent closed as a duplicate takes it back", acc(child(state="CLOSED", reason="DUPLICATE"))[0], False)
    check("#572: a parent closed with no reason read takes it back", acc(child(state="CLOSED", reason=None))[0], False)
    check("#572: a parent in any other state is neither open nor closed as completed", acc(child(state="UNKNOWN")), (False, "its parent DiluxOne/.github#189 is neither open nor closed as completed"))
    check("#189 C4: a parent whose accepted was removed takes it back", acc(child(parent_labels=(), unlabeled=True))[0], False)
    check("#189: a parent in another organisation", acc(child(where="Other/.github"))[0], False)
    check("#189: an issue with no parent and no lane is no lane's", acc(child(parent=False))[0], False)
    check("#189: a lane label wins over the parent", lane_of(child(labels=("lane:platform",))), ("platform", None))
    check("#189: DX_AUTOPILOT off stops it", acc(child(), "off")[0], False)
    check("#189: a repository switches it off", lane_accepts(merge(org, {"lanes": {"delegated": {"enabled": False}}}), child(), None, "DiluxOne/x", "")[0], False)
    check("a release is never accepted by policy", org["lanes"]["release"]["accept"], "human")

    # The golden rule (#397): no lane merges a change that widens autonomy.
    # Every lane of the policy, given a protected path that widens it (or
    # one it could not tell), leaves it to a person; only the reproduced
    # bug's lane merges a protected path at all, and only widening nothing.
    for name in org.get("lanes") or {}:
        for widening in (["lanes.x added"], ["unknown"]):
            check(f"golden rule: lane {name} never merges a protected path that widens autonomy ({widening[0]})",
                  constitution_merge(org, name, ["policy/autonomy.yml"], widening)[0], False)
        check(f"golden rule: lane {name} merges a protected path only if it is {CONSTITUTION_LANE}",
              constitution_merge(org, name, ["scripts/x.py"], [])[0], name == CONSTITUTION_LANE)
    check("golden rule: the reproduced bug's fix in a protected path, widening nothing, within its constitution-merge caps",
          constitution_merge(org, CONSTITUTION_LANE, ["scripts/x.py"], []), (True, org["lanes"][CONSTITUTION_LANE]["constitution-merge"]))
    check("golden rule: nothing protected, the lane's own merge caps", constitution_merge(org, CONSTITUTION_LANE, [], []), (True, org["lanes"][CONSTITUTION_LANE]["merge"]))
    check("golden rule: no other lane may have constitution-merge",
          problems({**org, "lanes": {**org["lanes"], "human-issue": {**org["lanes"]["human-issue"], "constitution-merge": {"max-risk": "high", "max-complexity": "high"}}}}),
          ["lanes.human-issue.constitution-merge: only the bugfix-reproduced lane may merge in a protected path"])
    check("golden rule: a repository cannot set constitution-merge",
          merge(org, {"lanes": {CONSTITUTION_LANE: {"constitution-merge": {"max-risk": "high", "max-complexity": "high"}}}})["lanes"][CONSTITUTION_LANE]["constitution-merge"],
          org["lanes"][CONSTITUTION_LANE]["constitution-merge"])
    check("golden rule: a repository cannot give constitution-merge to another lane",
          "constitution-merge" in merge(org, {"lanes": {"human-issue": {"constitution-merge": {"max-risk": "high", "max-complexity": "high"}}}})["lanes"]["human-issue"], False)

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
    # #568 C2: what merge() lets a repository do is what the settings'
    # schema says of each key, and a key it says `never` of stays the
    # organisation's whatever the repository's file holds.
    import settings  # the schema's reader, here only: the lane job fetches autonomy.py's imports
    schema = {s["key"]: s.get("repo") for s in settings.entries(settings.schema(), "policy/autonomy.yml")}
    check("#568 C2: the schema's repo level of each key is merge()'s", schema, {**{k: "never" for k in schema}, **REPO_RULES})
    for key in (k for k, how in schema.items() if how == "never"):
        top, _, rest = key.partition(".")
        if top == "lanes":
            name, part = "human-issue", rest.split(".", 1)[1]
            repo = {"lanes": {name: {part: {"app": "someone"} if part == "origin" else "x"}}}
            got = merge(org, repo)["lanes"][name].get(part), org["lanes"][name].get(part)
        else:
            repo = {top: {"max-files": 1} if top == "security-patch" else 1}
            got = merge(org, repo).get(top), org.get(top)
        check(f"#568 C2: a repository cannot set {key}", got[0], got[1])
    acme = {**org, "lanes": {**org["lanes"], "human-issue": {**org["lanes"]["human-issue"], "merge": {"max-risk": "low", "max-complexity": "high"}, "ceiling": {"max-risk": "medium", "max-complexity": "high"}}}}
    check("#568 C2: a repository raises merge within its organisation's ceiling", merge(acme, {"lanes": {"human-issue": {"merge": {"max-risk": "medium"}}}})["lanes"]["human-issue"]["merge"], {"max-risk": "medium", "max-complexity": "high"})
    check("#568 C2: past it, the organisation's ceiling applies", merge(acme, {"lanes": {"human-issue": {"merge": {"max-risk": "high"}}}})["lanes"]["human-issue"]["merge"], {"max-risk": "medium", "max-complexity": "high"})
    lane = lambda **k: {"lanes": {**org["lanes"], "human-issue": {**org["lanes"]["human-issue"], **k}}}
    check("#188 schema: a key the policy does not know", problems({**org, "owner": "me"}), ["owner: not a key of the policy"])
    check("#247 schema: a planned release is auto or confirm", [problems({**org, "planned-release": v}) for v in ("auto", "confirm", "yes")],
          [[], [], ["planned-release: auto or confirm"]])
    check("#287 budgets: the organisation's, lowered by a repository and never raised",
          (merge({**org, "budgets-usd": {"autopilot-work": 20, "security-fix": 10}}, {"budgets-usd": {"autopilot-work": 5, "security-fix": 50}})["budgets-usd"],
           problems({**org, "budgets-usd": {"autopilot-work": 0}}) != [], problems({**org, "budgets-usd": {"other": 1}}) != [], problems({**org, "budgets-usd": {"autopilot-fix": 8}})),
          ({"autopilot-work": 5, "security-fix": 10}, True, True, []))
    sp_err = ["security-patch: max-files (1 to 100), max-lines (1 to 5000), forbidden (a list of globs), reviewer-model (a Claude model)"]
    check("#287 schema: a patch's limits and its reviewer; no veto window any more",
          [problems({**org, "security-patch": v}) for v in ({"max-files": 3, "max-lines": 100, "reviewer-model": "claude-sonnet-5-5"}, {}, {"veto-hours": 6},
                                                             {"max-files": 0}, {"max-lines": True}, {"forbidden": "x"}, {"reviewer-model": "gpt"})],
          [[], []] + [sp_err] * 5)
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
    # #561 C4: what G7 holds for a person depends on the repository.
    here_p = merge(org, {}, sys.modules["org"].CENTRAL)["protected"]
    there_p = merge(org, {}, "o/product")["protected"]
    declared_p = merge(org, {"constitution": ["scripts/**"]}, "o/product")["protected"]
    check("#561 C4: the organisation's own repository, or one not named, protects the whole constitution",
          (here_p == org["constitution"], merge(org, {})["protected"] == org["constitution"]), (True, True))
    check("#561 C4: another repository protects its workflows and what it declares, never the engine's scripts/ by default",
          (there_p, declared_p, merge(org, {}, "o/product")["constitution"] == org["constitution"]),
          (ALWAYS_PROTECTED, ALWAYS_PROTECTED + ["scripts/**"], True))
    check("#561 C4: another repository's own policy files and workflows stay a person's",
          [any(fnmatch.fnmatch(f, p) for p in there_p) for f in (".github/workflows/ci.yml", ".github/autonomy.yml", ".github/review-policy.yml", "scripts/x.py", ".github/ISSUE_TEMPLATE/bug.yml")],
          [True, True, True, False, False])
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

    import org as org_conf  # the module: `org` is the policy here
    check("#568: who may run the sync is org.yml's maintainers, unless the lane names them", (lane_people(org["lanes"]["org-sync"]["origin"]), lane_people({"people": ["x"]}), lane_people({"people": []})), (org_conf.MAINTAINERS, ["x"], []))
    m = merge(org, {"lanes": {"org-sync": {"origin": {"people": ["someone"]}}}})
    check("a repository cannot add a person to a sync lane", lane_people(m["lanes"]["org-sync"]["origin"]), org_conf.MAINTAINERS)
    # #568: DiluxOne's values in force are the same now they come from
    # org.yml: every lane's App is dilux-bot, and the sync's people the
    # maintainer, as the policy wrote them before.
    check("#568: DiluxOne's lanes are still opened by dilux-bot", {lane_app(lane.get("origin")) for lane in org["lanes"].values() if lane.get("origin")}, {"dilux-bot"} if not os.environ.get("DX_BOT_APP") else {os.environ["DX_BOT_APP"]})
    check("#568: and the sync is still run by its maintainer", lane_people(org["lanes"]["org-sync"]["origin"]), ["soydiloreto"])
    saved, org_conf.APP = org_conf.APP, ""
    try:
        check("#568: no App anywhere, the lane names none", lane_app({}), "")
        check("#568: and a lane check refuses it, not an issue whose author is empty",
              carry_accepts("x", {}, {"author": {"login": ""}, "body": ""}, "o/r", {}), (False, NO_APP))
        check("#568: nor does an empty App let a non-member's sub-issue through",
              delegated_accepts("x", {"origin": {"parent": True}}, {"authorAssociation": "NONE", "author": {"login": ""}, "parent": {
                  "repository": {"nameWithOwner": "o/p"}, "number": 1, "state": "OPEN", "labels": {"nodes": [{"name": "accepted"}]},
                  "timelineItems": {"nodes": [{"__typename": "LabeledEvent", "label": {"name": "accepted"}, "actor": {"__typename": "User", "login": "boss"}}]}}}, "o/r"),
              (False, "the sub-issue was not opened by a member of the organisation"))
    finally:
        org_conf.APP = saved
    check("#568: the policy names no App and no person of its own", [n for n, lane in org["lanes"].items() if {"app", "people"} & set(lane.get("origin") or {})], [])
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
    # #320: a callers-only major moves the repository's own jobs too (the
    # templates here call v5, the major moved to).
    own_at = lambda v, extra="": caller_head + f"  own:\n    uses: DiluxOne/.github/.github/workflows/svn-auth-check.yml@{v}\n{extra}"
    own_base = {".github/workflows/issues.yml": caller_base + own_at("v4")[len(caller_head):]}
    check("#320: a job of the repository's own whose only change is its call moved to the templates' newer major merges on its own",
          merges(sync_case("callers", files={".github/workflows/issues.yml": own_at("v5")}, base=own_base))[0], True)
    for name, head_own in (("an older major", own_at("v3")), ("a major no template calls", own_at("v99")),
                           ("another workflow", own_at("v5").replace("svn-auth-check.yml", "issue-triage.yml")),
                           ("a ref that is not a major", own_at("main")), ("more than its call", own_at("v5", "    with:\n      x: y\n"))):
        check(f"#320: a job of the repository's own moved to {name} does not merge on its own",
              merges(sync_case("callers", files={".github/workflows/issues.yml": head_own}, base=own_base))[0], False)
    # #562 C2: a template's placeholder becomes the value repos.yml gives,
    # and none is left; a new caller is its template with those values.
    support = "https://github.com/DiluxOne/.github/blob/main/SUPPORT.md"
    valued = dict(org_facts, **{"repos.yml": json.dumps({"files": {".github/CODEOWNERS": owners}, "callers": {
        "repository-owned": {"issues.yml": ["support-url"]}, "defaults": {"support-url": support}}})})
    valued["main"] = dict(org_facts["main"], **{"repos.yml": valued["repos.yml"]})

    def valued_case(head, base):
        case = sync_case("callers", files={".github/workflows/issues.yml": head}, base={".github/workflows/issues.yml": base} if base is not None else {})
        case[1]["org"] = lambda _sha, _contents=False: valued
        return case
    placeheld = caller_base.replace("https://mine.example", "https://example.com")
    check("#562 C2: a callers run that fills a template's placeholder with repos.yml's value merges on its own",
          merges(valued_case(caller_head.replace("https://mine.example", support), placeheld))[0], True)
    ok, why = merges(valued_case(caller_head.replace("https://mine.example", "https://example.com"), placeheld))
    check("#562 C2: one that leaves the placeholder does not", (ok, "placeholder" in why), (False, True))
    check("#562 C2: nor one that writes a value repos.yml does not give",
          merges(valued_case(caller_head.replace("https://mine.example", "https://other.example"), placeheld))[0], False)
    check("#562 C2: the repository's own value is still kept, never replaced",
          merges(valued_case(caller_head.replace("https://mine.example", support), caller_base))[0], False)
    new_caller = template.replace("https://example.com", support)
    check("#562 C2: a new caller that is its template with repos.yml's values merges on its own", merges(valued_case(new_caller, None))[0], True)
    for name, text in (("still holds the placeholder", template), ("adds a line", new_caller + "  more:\n    uses: x/y/.github/workflows/z.yml@v1\n")):
        check(f"#562 C2: a new caller that {name} does not merge on its own", merges(valued_case(text, None))[0], False)
    check("a CODEOWNERS that is not repos.yml's does not merge on its own", merges(sync_case(files={".github/CODEOWNERS": "* @someone\n", "AGENTS.md": agents_head}))[0], False)
    check("an AGENTS.md changed outside its block does not merge on its own", merges(sync_case(files={".github/CODEOWNERS": owners, "AGENTS.md": agents_head + "\nMore.\n"}))[0], False)
    check("a stale files run (main's repos.yml moved on) does not merge on its own",
          merges(sync_case(main={"repos.yml": json.dumps({"files": {".github/CODEOWNERS": "* @someone\n"}})}))[0], False)
    check("a stale callers run (main's templates moved on) does not merge on its own",
          merges(sync_case("callers", main={"templates": {"issues.yml": template + "  more:\n    uses: DiluxOne/.github/.github/workflows/x.yml@v5\n"}}))[0], False)
    check("a files run is not stale for a change of main elsewhere in repos.yml",
          merges(sync_case(main={"repos.yml": json.dumps({"files": {".github/CODEOWNERS": owners}, "projects": {"x": 1}})}))[0], True)
    check("the lane merges what the review rates high only because of its paths", (org["lanes"]["org-sync"]["merge"]["max-risk"], org["lanes"]["org-sync"]["merge"]["max-complexity"]), ("high", "low"))

    # #562 C1: the pre-pr and dependabot runs, as mechanical as the callers:
    # accepted and merged by policy, each file what the commit renders.
    def central_text(path):
        with open(os.path.join(HERE, "..", path), encoding="utf-8") as fh:
            return fh.read()
    pre_pr, sync = pre_pr_module(), sync_module()
    pack = central_text("kinds/wordpress-plugin/pack.yml")
    plugin_template, default_template = central_text("kinds/wordpress-plugin/dependabot.yml"), central_text("policy/dependabot.default.yml")
    ignore = {"composer": {"ignore": [{"dependency-name": "php"}]}}
    entry = {"kinds": [{"kind": "wordpress-plugin", "paths": ["**"]}], "dependabot": ignore}
    mech_conf = {"repos": {"diluxone-offload-wordpress": entry}}
    mech_facts = dict(org_facts, **{"repos.yml": json.dumps(mech_conf), "dependabot-default": default_template,
                                    "kinds": {"wordpress-plugin": {"pack.yml": pack, "dependabot.yml": plugin_template}}})
    mech_facts["main"] = {k: mech_facts[k] for k in ("repos.yml", "agents-block.md", "templates", "dependabot-default", "kinds")}
    makefile_base = "check:\n\tphpunit\n"
    dx = pre_pr.render(parse_text(pack)["pre-pr-make"])
    root = ["composer.json", "plugin.php", ".github"]
    dependabot = sync.render_dependabot(plugin_template, sync.dependabot_ecosystems(set(root), ignore), ignore, default_template)

    def mech_case(mode, files, base=None, main=None, root=root):
        case = sync_case(mode, files=files, base=base or {})
        facts = dict(mech_facts, main=dict(mech_facts["main"], **(main or {})))
        case[1]["org"] = lambda _sha, _contents=False: facts
        change = case[1]["change"]()
        change["root"] = root
        case[1]["change"] = lambda: change
        return case
    pre_files = {"dx.mk": dx, "Makefile": pre_pr.with_include(makefile_base)}
    pre_base = {"Makefile": makefile_base}
    check("#562 C1: the lane names a pre-pr and a dependabot run, each with its branch and paths",
          (runs["pre-pr"], runs["dependabot"]), ({"branch": "chore/{issue}-org-pre-pr", "paths": ["dx.mk", "Makefile"]},
                                                 {"branch": "chore/{issue}-org-dependabot", "paths": [".github/dependabot.yml"]}))
    check("#562 C1: a pre-pr run's issue is accepted by policy, and its pull request passes the gate",
          (sync_ok(mech_case("pre-pr", pre_files, pre_base), scope="issue"), sync_ok(mech_case("pre-pr", pre_files, pre_base))), (True, True))
    check("#562 C1: a pre-pr run's pull request, green, merges by policy", merges(mech_case("pre-pr", pre_files, pre_base)), (True, merges(mech_case("pre-pr", pre_files, pre_base))[1]))
    check("#562 C1: one for a repository with no Makefile yet merges by policy too",
          merges(mech_case("pre-pr", {"dx.mk": dx, "Makefile": pre_pr.INCLUDE + "\n"}))[0], True)
    check("#562 C1: a dependabot run's issue is accepted by policy, and its pull request merges by policy",
          (sync_ok(mech_case("dependabot", {".github/dependabot.yml": dependabot}), scope="issue"),
           merges(mech_case("dependabot", {".github/dependabot.yml": dependabot}))[0]), (True, True))
    for name, files in (("a Makefile line changed beside the include", {"dx.mk": dx, "Makefile": pre_pr.with_include(makefile_base).replace("phpunit", "true")}),
                        ("a dx.mk that is not the pack's", {"dx.mk": dx.replace("pre-pr:", "pre-pr: extra"), "Makefile": pre_pr.with_include(makefile_base)})):
        ok, why = merges(mech_case("pre-pr", files, pre_base))
        check(f"#562 C1: a pre-pr run with {name} does not merge on its own", (ok, bool(why)), (False, True))
    check("#562 C1: a Makefile whose own pre-pr has a recipe is not a pre-pr run's to include",
          merges(mech_case("pre-pr", {"dx.mk": dx, "Makefile": pre_pr.with_include("pre-pr:\n\tnpm test\n")}, {"Makefile": "pre-pr:\n\tnpm test\n"}))[0], False)
    for name, text in (("a changed entry", dependabot.replace("interval: daily", "interval: weekly", 1)),
                       ("an ecosystem its head does not have", sync.render_dependabot(plugin_template, sync.dependabot_ecosystems(set(root) | {"package.json"}, ignore), ignore, default_template)),
                       ("the repository's ignore dropped", sync.render_dependabot(plugin_template, sync.dependabot_ecosystems(set(root), {}), {}, default_template))):
        check(f"#562 C1: a dependabot run with {name} does not merge on its own", merges(mech_case("dependabot", {".github/dependabot.yml": text}))[0], False)
    check("#562 C1: a dependabot run whose head's root could not be read does not merge on its own",
          merges(mech_case("dependabot", {".github/dependabot.yml": dependabot}, root=None))[0], False)
    check("#562 C1: a pre-pr run's file outside its paths fails the gate", sync_ok(mech_case("pre-pr", dict(pre_files, **{".github/dependabot.yml": dependabot}), pre_base)), False)
    moved = dict(mech_facts["kinds"], **{"wordpress-plugin": {"pack.yml": pack + "\n# more\n", "dependabot.yml": plugin_template}})
    check("#562 C1: a stale pre-pr or dependabot run (the pack, the default template or the entry moved on) does not merge on its own",
          (merges(mech_case("pre-pr", pre_files, pre_base, main={"kinds": moved}))[0],
           merges(mech_case("dependabot", {".github/dependabot.yml": dependabot}, main={"dependabot-default": default_template + "\n"}))[0],
           merges(mech_case("dependabot", {".github/dependabot.yml": dependabot}, main={"repos.yml": json.dumps({"repos": {"diluxone-offload-wordpress": dict(entry, dependabot={})}})}))[0]),
          (False, False, False))

    # #562 C5: the adopt lane merges the pull request that adds the Adopt
    # issue's entry to repos.yml, and nothing else.
    detect = adopt_module()
    adopt_entry_ = {"kinds": [{"kind": "wordpress-plugin", "paths": ["**"], "roles": ["back", "front"]}]}
    adopt_body = detect.adopt_body("diluxone-new", ["wordpress-plugin"], detect.packs())
    with open(os.path.join(HERE, "..", "repos.yml"), encoding="utf-8") as fh:
        repos_base = fh.read()
    repos_head = detect.with_entries(repos_base, [detect.entry_text("diluxone-new", adopt_entry_)])
    spec = importlib.util.spec_from_file_location("repos_config", os.path.join(HERE, "repos-config.py"))
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    rc_problems = lambda conf: rc.problems(conf, rc.dirs(os.path.join(HERE, "..", "kinds")), rc.dirs(os.path.join(HERE, "..", "design-systems")))  # noqa: E731

    def adopt_case(body=adopt_body, title="Adopt diluxone-new", actor=("User", "soydiloreto"), edited=None, head=repos_head, files=None,
                   pr_author="dilux-bot[bot]", branch="chore/61-adopt", labels=("lane:adopt", "accepted"), typ="Task"):
        i = {"number": 61, "title": title, "author": {"login": "dilux-bot[bot]"}, "body": body, "lastEditedAt": edited, "issueType": {"name": typ},
             "labels": {"nodes": [{"name": n} for n in labels]},
             "timelineItems": {"nodes": [{"__typename": "LabeledEvent", "createdAt": "2026-11-01T10:00:00Z", "label": {"name": "accepted"},
                                          "actor": {"__typename": actor[0], "login": actor[1]}}]}}
        change = {"files": files or [{"status": "modified", "path": "repos.yml"}], "base": {"repos.yml": repos_base}, "head": {"repos.yml": head}}
        facts = {"maintainer": lambda who: who == "soydiloreto", "pr": {"author": {"login": pr_author}, "headRefName": branch},
                 "change": lambda: change, "problems": rc_problems}
        return i, facts

    def adopted(case, repository=CENTRAL, var="", p=pol):
        return adopt_accepts(p, case[0], repository, var, case[1])
    check("#562 C5: the adopt lane: a maintainer accepts its issue, nothing accepts it by policy", (org["lanes"]["adopt"]["accept"], org["lanes"]["adopt"]["repositories"]), ("human", [".github"]))
    ok, why = adopted(adopt_case())
    check("#562 C5: a pull request adding only the Adopt issue's entry passes", (ok, why), (True, why))
    check("#562 C5: and merges by policy, green", adopt_merge(pol, adopt_case()[0], CENTRAL, "", adopt_case()[1], green)[0], True)
    check("#562 C5: nor when the lane is switched off", adopted(adopt_case(), p=merge(org, {"lanes": {"adopt": {"enabled": False}}}))[0], False)
    edited_block = adopt_body.replace("{kinds: [", "{project: 16, kinds: [")
    check("#562 C5: the block as a maintainer corrected it before accepting is the entry",
          adopted(adopt_case(body=edited_block, edited="2026-11-01T09:00:00Z",
                             head=detect.with_entries(repos_base, [detect.entry_text("diluxone-new", dict(adopt_entry_, project=16))])))[0], True)
    other = detect.with_entries(repos_base, [detect.entry_text("diluxone-new", adopt_entry_), "  diluxone-more: {kinds: []}"])
    for name, case in (("another entry beside it", adopt_case(head=other)),
                       ("an entry other than the issue's", adopt_case(head=detect.with_entries(repos_base, [detect.entry_text("diluxone-new", {"kinds": []})]))),
                       ("another line of repos.yml changed", adopt_case(head=repos_head.replace("has_wiki: false", "has_wiki: true"))),
                       ("a comment changed", adopt_case(head=repos_head.replace("# Merging: squash only", "# Merging: any"))),
                       ("another file", adopt_case(files=[{"status": "modified", "path": "repos.yml"}, {"status": "modified", "path": "policy/autonomy.yml"}])),
                       ("an entry out of the schema", adopt_case(body=adopt_body.replace("{kinds: [", "{owner: me, kinds: ["),
                                                                 head=detect.with_entries(repos_base, [detect.entry_text("diluxone-new", dict(adopt_entry_, owner="me"))]))),
                       ("the text edited after it was accepted", adopt_case(edited="2026-11-01T11:00:00Z")),
                       ("`accepted` added by someone without the role", adopt_case(actor=("User", "someone"))),
                       ("`accepted` added by a bot", adopt_case(actor=("Bot", "soydiloreto"))),
                       ("a title that is not the marker's", adopt_case(title="Adopt diluxone-other")),
                       ("a pull request someone else opened", adopt_case(pr_author="someone")),
                       ("another branch", adopt_case(branch="chore/61-mine")),
                       ("no lane:adopt", adopt_case(labels=("accepted",))),
                       ("a Type other than Task", adopt_case(typ="Feature"))):
        check(f"#562 C5: the adopt lane refuses {name}", adopted(case)[0], False)
    check("#562 C5: never outside DiluxOne/.github, nor with DX_AUTOPILOT off",
          (adopted(adopt_case(), repository="DiluxOne/x"), adopted(adopt_case(), var="off")[0]), ((False, adopted(adopt_case(), repository="DiluxOne/x")[1]), False))
    check("#562 C5: nor one the review blocks or rates above the lane's complexity",
          (adopt_merge(pol, adopt_case()[0], CENTRAL, "", adopt_case()[1], dict(green, blocking="true"))[0],
           adopt_merge(pol, adopt_case()[0], CENTRAL, "", adopt_case()[1], dict(green, complexity="medium"))[0]), (False, False))

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
        ok, why = lane_accepts(policy_in_force(), issue, read_run(issue, repository), repository, var, {**carry_from_env(repository), **sync})
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
        review = {"risk": os.environ.get("RISK", ""), "complexity": os.environ.get("COMPLEXITY", ""),
                  "blocking": os.environ.get("BLOCKING", ""), "description_ok": os.environ.get("DESCRIPTION_OK", "")}
        if carry_lane_of(policy, issue):
            # A security patch's carry (#287): its commits must be the fix
            # that was released, nothing more and nothing less.
            try:
                ok, why = carry_merge(policy, issue, repository, var, carry_from_env(repository, sync_from_env(repository, False)["pr"]), review)
            except Exception as exc:  # any failure is a person's merge, said as a failure
                print(f"the decision failed: {exc}")
                return 3
            print(why)
            return 0 if ok else 1
        if adopt_lane_of(policy, issue):
            # An Adopt issue's pull request (#562): its entry, and nothing else.
            try:
                ok, why = adopt_merge(policy, issue, repository, var, adopt_from_env(repository), review)
            except Exception as exc:  # any failure is a person's merge, said as a failure
                print(f"the decision failed: {exc}")
                return 3
            print(why)
            return 0 if ok else 1
        if not sync_lane_of(policy, issue):
            print("no sync lane's issue")
            return 2
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
