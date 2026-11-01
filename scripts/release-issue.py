#!/usr/bin/env python3
"""The release issue (#82): publishing X.Y.Z is a person's decision, and
accepting the issue "Release X.Y.Z" is it.

A release issue is titled exactly `Release X.Y.Z` and carries the label
`lane:release` (the Release form, .github/ISSUE_TEMPLATE/release.yml, sets
both; policy/issue-schema.yml writes the form). The release lane of
policy/autonomy.yml is never accepted by policy: only a person's `accepted`
counts, read from the issue's timeline, never from its text.

  release-issue.py plan     when a person accepts a release issue: what the
                            release pull request is (the version, its branch,
                            title and body, and the kind's command that
                            prepares the tree), or why there is none; JSON on
                            stdout, exit 0 when there is one, 1 when not
  release-issue.py verify   before anything is published: whether a release
                            issue for VERSION exists, a person accepted it who
                            has the admin or maintain role on the repository
                            now, and its title still names VERSION; JSON on stdout,
                            exit 0 when it approves the release, 1 when not,
                            2 when the issues could not be read
  release-issue.py argv     the kind's command that prepares VERSION in ROOT
                            (a checkout of the repository), as a JSON list:
                            what auto-merge.yml runs again on the release
                            pull request's base to prove its tree (#247)
  release-issue.py --test   self-test

Environment:
  plan:   TITLE (the issue's title), NUMBER (the issue), NEXT_JSON (a file
          holding `scripts/next-version.py --json`), ROOT (the repository's
          checkout, default .), CENTRAL (the checkout of DiluxOne/.github,
          default this script's repository), CENTRAL_PATH (how the command
          names CENTRAL, default CENTRAL)
  verify: VERSION, LABEL (the accepting label, default accepted),
          GITHUB_REPOSITORY, GH_TOKEN (issues: read); RELEASE_ISSUES_JSON, a
          file holding the GraphQL answer, replaces the call, and
          RELEASE_ROLES_JSON, a file mapping a login to its role_name (or to
          null for an answer that failed), replaces the permission calls
          (the self-test uses both)

What the kind contributes is data: kinds/<kind>/pack.yml, `release:` says
where a version goes (`publishes-to`), which reusable workflow publishes it
(`workflow`; the repository's caller of it holds the inputs, its `with:`),
and the command that turns the default branch into the release pull request
(`prepare`, a list of arguments with {placeholders}). Nothing here knows
WordPress.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import org  # noqa: E402  the organisation's App, from org.yml (#191, #197)
TITLE = re.compile(r"^Release (\d+\.\d+\.\d+)$")
AI_LINE = "🤖 AI-generated · Claude Opus 5.5 (Anthropic)"
# Who may approve a release: the roles that administer or maintain the
# repository, read at verify time. Triage and write may accept an ordinary
# issue; publishing to users takes more (#82).
RELEASE_ROLES = ("admin", "maintain")
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9-]*)\}")

_spec = importlib.util.spec_from_file_location("issue_schema", os.path.join(HERE, "issue-schema.py"))
schema = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(schema)
# The release lane's label, as the schema (and so the Release form) sets it.
LANE_LABEL = (schema.schema().get("release") or {}).get("label") or "lane:release"


def version_of(title):
    """X.Y.Z from a title that is exactly `Release X.Y.Z`, else None."""
    m = TITLE.match((title or "").strip())
    return m.group(1) if m else None


def engine_issue(version, why, lane_run=""):
    """The release issue the engine's release lane opens for a person when
    what it would release is breaking (#563, scripts/release-lane.py): the
    Release form's title and label, so accepting it is the person's
    decision, as for any release."""
    run = f"\n\nThe lane's run: {lane_run}" if lane_run else ""
    return {"title": f"Release {version}", "labels": [LANE_LABEL],
            "body": f"Every release scenario passed in the test repository, and v{version} is breaking ({why}): "
                    f"it reaches the repositories only once a person accepts this issue and releases it.{run}\n"}


# --- plan: the release pull request ---------------------------------------

def kind_of(root):
    policy = schema.read_yaml(os.path.join(root, ".github", "review-policy.yml")) or {}
    return str(policy.get("kind") or "").strip()


def pack_release(central, kind):
    if not kind or not re.fullmatch(r"[a-z0-9-]+", kind):
        return None
    pack = schema.read_yaml(os.path.join(central, "kinds", kind, "pack.yml")) or {}
    return pack.get("release") or None


def caller_inputs(root, workflow):
    """The `with:` of the repository's job that calls `workflow` (a reusable
    workflow of DiluxOne/.github), from its .github/workflows/; None when no
    job calls it. Two callers with different inputs are refused: which one
    publishes is not guessed."""
    found = []
    wdir = os.path.join(root, ".github", "workflows")
    if not os.path.isdir(wdir):
        return None
    needle = re.compile(r"^DiluxOne/\.github/\.github/workflows/" + re.escape(workflow) + r"@")
    for name in sorted(os.listdir(wdir)):
        if not name.endswith((".yml", ".yaml")):
            continue
        doc = schema.read_yaml(os.path.join(wdir, name)) or {}
        for job in (doc.get("jobs") or {}).values():
            if isinstance(job, dict) and needle.match(str(job.get("uses") or "")):
                # As the workflow reads them: a boolean is true or false
                # (yq and PyYAML agree on the value, not on its spelling).
                found.append({k: "" if v is None else v if isinstance(v, str) else json.dumps(v) for k, v in (job.get("with") or {}).items()})
    if not found:
        return None
    if any(f != found[0] for f in found):
        raise ValueError(f"more than one job calls {workflow}, with different inputs")
    return found[0]


def fill(arg, values):
    """An argument with its {placeholders} filled; KeyError names the first
    one that has no value."""
    def one(m):
        if m.group(1) not in values:
            raise KeyError(m.group(1))
        return values[m.group(1)]
    return PLACEHOLDER.sub(one, arg)


def prepare_argv(release, inputs, version, central_path):
    """The kind's `prepare` command, filled: {version}, {central}, and the
    caller's inputs, an empty or missing one taking the pack's default (which
    may name other inputs)."""
    values = {k: v for k, v in (inputs or {}).items() if v != ""}
    for k, default in (release.get("defaults") or {}).items():
        if k not in values:
            values[k] = fill(str(default), values)
    values.update({"version": version, "central": central_path})
    argv = [fill(str(a), values) for a in release.get("prepare") or []]
    # Only what the command uses: an expression elsewhere in the caller is
    # the caller's business.
    for a in argv:
        if "${{" in a:
            raise ValueError(f"an input the release pull request needs is an expression ({shown(a)}); write its value out in the caller")
    return argv


def plan(title, number, nxt, kind, release, inputs, central_path):
    """What the release pull request is, or why there is none (pure)."""
    version = version_of(title)
    if not version:
        return {"ok": False, "why": f"the title must be exactly `Release X.Y.Z` (three numbers), and it is `{shown(title)}`: a person corrects it and accepts the issue again"}
    if not kind:
        return {"ok": False, "version": version, "why": "this repository declares no kind of project (`kind:` in `.github/review-policy.yml`), so nothing says where a version goes"}
    if not release or not release.get("prepare") or not release.get("workflow"):
        return {"ok": False, "version": version, "why": f"the `{kind}` kind publishes nothing (no `release:` in `kinds/{kind}/pack.yml`)"}
    if inputs is None:
        return {"ok": False, "version": version, "why": f"no workflow of this repository calls `{release['workflow']}`, which publishes a `{kind}`; add its caller first (`workflow-templates/` in DiluxOne/.github)"}
    if not nxt.get("pending"):
        return {"ok": False, "version": version, "why": f"nothing merged since {nxt.get('last')} asks for a version (no `type:breaking`, `type:feat`, `type:fix` or `type:perf` label, no `version:*` label), so there is no {version} to release"}
    if nxt.get("next") != version:
        return {"ok": False, "version": version, "why": f"the labels of what merged since {nxt.get('last')} give {nxt.get('next')} (a {nxt.get('bump')} release), not {version}. Either retitle this issue `Release {nxt.get('next')}`, or label a merged pull request `version:major`, `version:minor` or `version:patch` so the labels reach {version}; then accept it again"}
    try:
        argv = prepare_argv(release, inputs, version, central_path)
    except KeyError as e:
        return {"ok": False, "version": version, "why": f"the caller of `{release['workflow']}` has no `{e.args[0]}` input, which `kinds/{kind}/pack.yml` needs to prepare the release"}
    except ValueError as e:
        return {"ok": False, "version": version, "why": str(e)}
    where = org.publishes_to(release.get("publishes-to"), kind) or "where the kind publishes"
    branch = f"chore/{number}-release-{version.replace('.', '-')}"
    pr_title = f"chore(release): {version}"
    body = f"""## 📝 What changes

The tree says {version}: the hold on the newest changelog entry is removed and the version markers name {version}, as `kinds/{kind}/pack.yml` prepares a release.

## 💡 Why

Closes #{number}. The release issue was accepted, by a person or by the plan a maintainer approved as its milestone, which is the decision to publish {version}. Once this pull request merges, the release workflow checks that the issue is still accepted by a person and that its version is the one computed, then publishes {version} to {where}.

{AI_LINE}"""
    return {"ok": True, "version": version, "branch": branch, "title": pr_title, "body": body, "argv": argv,
            "publishes_to": where, "kind": kind}


# --- verify: the approval before publishing --------------------------------

# The issues labelled lane:release, newest first, with the events that say
# who accepted each and whether its title changed since.
QUERY = """query($owner: String!, $name: String!, $label: String!) {
  repository(owner: $owner, name: $name) {
    issues(labels: [$label], first: 50, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes {
        number
        title
        state
        stateReason
        labels(first: 50) { nodes { name } }
        author { login }
        milestone { title state creator { login } }
        timelineItems(itemTypes: [LABELED_EVENT, UNLABELED_EVENT, RENAMED_TITLE_EVENT], last: 100) {
          nodes {
            __typename
            ... on LabeledEvent { createdAt label { name } actor { __typename login } }
            ... on UnlabeledEvent { createdAt label { name } actor { __typename login } }
            ... on RenamedTitleEvent { createdAt previousTitle currentTitle actor { __typename login } }
          }
        }
      }
    }
  }
}"""


def shown(title):
    """A title quoted back in a code span: one line, no backtick, short."""
    return " ".join(str(title or "").split()).replace("`", "'")[:80]


def judge(node, label):
    """(ok, why, by, at) for one issue whose title names the version."""
    n = node.get("number")
    if node.get("state") == "CLOSED" and node.get("stateReason") != "COMPLETED":
        return False, f"#{n} was closed as {str(node.get('stateReason') or 'not completed').lower().replace('_', ' ')}", None, None
    labels = [l.get("name") for l in (node.get("labels") or {}).get("nodes") or []]
    if LANE_LABEL not in labels:
        return False, f"#{n} has no `{LANE_LABEL}` label", None, None
    if label not in labels:
        return False, f"#{n} is not accepted (no `{label}` label)", None, None
    events = (node.get("timelineItems") or {}).get("nodes") or []
    last = None
    for e in events:
        if e.get("__typename") in ("LabeledEvent", "UnlabeledEvent") and (e.get("label") or {}).get("name") == label:
            last = e
    if not last or last.get("__typename") != "LabeledEvent":
        return False, f"#{n} carries `{label}` but no event says who added it", None, None
    actor = last.get("actor") or {}
    if actor.get("__typename") != "User":
        return False, f"#{n} got `{label}` from {actor.get('login') or 'an unknown actor'}, not a person: only a person accepts a release", None, None
    at = last.get("createdAt") or ""
    for e in events:
        # The same second counts as after: the timeline cannot order them.
        if e.get("__typename") == "RenamedTitleEvent" and (e.get("createdAt") or "") >= at:
            was, now_ = (shown(e.get("previousTitle")), shown(e.get("currentTitle")))
            return False, f"#{n}'s title changed after it was accepted (`{was}` → `{now_}`): a person accepts it again (remove and add `{label}`)", None, None
    return True, f"#{n}", actor.get("login"), at


# A planned release (#247): the bot opens "Release X.Y.Z" when its version's
# milestone is done, and in `planned-release: auto` (policy/autonomy.yml) it
# marks it accepted by policy. Approving the plan was approving the release:
# the person is whoever created the milestone, and their role is read now.
PLANNED_LABEL = "accepted-by:policy"
BOT_LOGINS = (org.APP, org.BOT, f"app/{org.APP}")


def planned(node, version):
    """(ok, why, by, at) for a release issue the plan accepted."""
    n = node.get("number")
    # A release cancelled by closing its issue is no release, planned or not.
    if node.get("state") == "CLOSED" and node.get("stateReason") != "COMPLETED":
        return False, f"#{n} was closed as {str(node.get('stateReason') or 'not completed').lower().replace('_', ' ')}", None, None
    labels = [l.get("name") for l in (node.get("labels") or {}).get("nodes") or []]
    if PLANNED_LABEL not in labels or LANE_LABEL not in labels:
        return False, f"#{n} is not accepted by the plan", None, None
    if ((node.get("author") or {}).get("login") or "") not in BOT_LOGINS:
        return False, f"#{n} carries `{PLANNED_LABEL}` but was not opened by the bot for a milestone", None, None
    events = (node.get("timelineItems") or {}).get("nodes") or []
    last = None
    for e in events:
        if e.get("__typename") in ("LabeledEvent", "UnlabeledEvent") and (e.get("label") or {}).get("name") == PLANNED_LABEL:
            last = e
    if not last or last.get("__typename") != "LabeledEvent" or ((last.get("actor") or {}).get("login") or "") not in BOT_LOGINS:
        return False, f"#{n}'s `{PLANNED_LABEL}` was not added by the bot", None, None
    ms = node.get("milestone") or {}
    if (ms.get("title") or "").strip().lstrip("v") != version:
        return False, f"#{n} is not on the milestone {version}", None, None
    # Done, as the plan said (#287): the bot closes the milestone when its
    # last issue closes; one still open was not done when it was accepted.
    if ms.get("state") != "CLOSED":
        return False, f"#{n}'s milestone {version} is not done", None, None
    at = last.get("createdAt") or ""
    for e in events:
        if e.get("__typename") == "RenamedTitleEvent" and (e.get("createdAt") or "") >= at:
            return False, f"#{n}'s title changed after the plan accepted it", None, None
    creator = (ms.get("creator") or {}).get("login")
    if not creator:
        return False, f"#{n}'s milestone names no creator", None, None
    return True, f"#{n}", creator, at


def planned_mode(path=None, autopilot_var=None):
    """The organisation's `planned-release`: auto or confirm (the default);
    confirm whenever DX_AUTOPILOT is off (#287)."""
    var = os.environ.get("DX_AUTOPILOT", "") if autopilot_var is None else autopilot_var
    if var.strip().lower() == "off":
        return "confirm"
    path = path or os.path.join(HERE, "..", "policy", "autonomy.yml")
    try:
        mode = str((schema.read_yaml(path) or {}).get("planned-release") or "confirm")
    except Exception:  # noqa: BLE001  unreadable is the safe answer
        return "confirm"
    return mode if mode in ("auto", "confirm") else "confirm"


def verify(answer, version, label="accepted", role_of=None, mode=None, plan_holds=None):
    """Whether a person approved releasing `version`. `role_of(login)` is
    that person's role_name on the repository now, or None when it could not
    be read (which approves nothing)."""
    if not isinstance(answer, dict) or answer.get("errors") or not isinstance(((answer.get("data") or {}).get("repository") or {}).get("issues"), dict):
        why = json.dumps(answer.get("errors"))[:300] if isinstance(answer, dict) and answer.get("errors") else "no answer"
        return {"ok": False, "unreadable": True, "version": version, "why": f"the release issues could not be read ({why}); the caller's release job needs `issues: read`"}
    nodes = answer["data"]["repository"]["issues"].get("nodes") or []
    wanted = f"Release {version}"
    mine = [x for x in nodes if (x.get("title") or "").strip() == wanted]
    if not mine:
        return {"ok": False, "version": version, "why": f"no issue titled `{wanted}` with the `{LANE_LABEL}` label exists"}
    whys = []
    mode = mode or planned_mode()
    for node in mine:
        ok, why, by, at = judge(node, label)
        if not ok and mode == "auto":
            pok, pwhy, pby, pat = planned(node, version)
            # Only the plan ships (#287): read again now, since something
            # may have merged after the plan was accepted.
            if pok and plan_holds:
                hold, hwhy = plan_holds(version)
                if not hold:
                    pok, why = False, f"#{node.get('number')} was accepted by the plan, but {hwhy}"
            if pok:
                ok, why, by, at = pok, pwhy, pby, pat
        if ok:
            role = role_of(by) if role_of else None
            if role is None:
                whys.append(f"#{node.get('number')} was accepted by {by}, whose permission on the repository could not be read, so it approves nothing")
                continue
            if role not in RELEASE_ROLES:
                whys.append(f"#{node.get('number')} was accepted by {by}, whose role here is {shown(role)}: only a person with the admin or maintain role approves a release; one of them accepts it again (remove and add `{label}`)")
                continue
            return {"ok": True, "version": version, "issue": node.get("number"), "by": by, "at": at,
                    "why": f"issue #{node.get('number')} `{wanted}`, accepted by {by} ({role}) at {at}"}
        whys.append(why)
    return {"ok": False, "version": version, "why": f"no issue `{wanted}` is accepted by a person: " + "; ".join(whys)}


def fetch(repo, label):
    owner, name = repo.split("/", 1)
    out = subprocess.run(["gh", "api", "graphql", "-f", f"query={QUERY}", "-f", f"owner={owner}", "-f", f"name={name}", "-f", f"label={LANE_LABEL}"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return {"errors": [{"message": (out.stderr or out.stdout).strip()[:300]}]}
    try:
        return json.loads(out.stdout)
    except ValueError:
        return {"errors": [{"message": "not JSON"}]}


def role(repo, login):
    """`login`'s role_name on `repo` now, or None when it cannot be read."""
    if not re.fullmatch(r"[A-Za-z0-9-]+", login or ""):
        return None
    out = subprocess.run(["gh", "api", f"repos/{repo}/collaborators/{login}/permission", "--jq", ".role_name"], capture_output=True, text=True)
    name = out.stdout.strip()
    return name if out.returncode == 0 and name and name != "null" else None


# --- the command line -------------------------------------------------------

def release_argv(root, version, central, central_path=None):
    """The kind's `prepare` command for `version`, filled from the
    repository's release caller, or ValueError saying why there is none.
    central is read for the pack; central_path is how the command names it."""
    kind = kind_of(root)
    release = pack_release(central, kind)
    if not release or not release.get("workflow"):
        raise ValueError(f"the kind {kind or '(none)'} publishes nothing")
    return prepare_argv(release, caller_inputs(root, release["workflow"]) or {}, version, central_path or central)


def main(argv):
    if argv[:1] == ["--test"]:
        return self_test()
    if argv[:1] == ["argv"]:
        central = os.environ.get("CENTRAL") or os.path.join(HERE, "..")
        try:
            print(json.dumps(release_argv(os.environ.get("ROOT", "."), os.environ["VERSION"], central)))
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        return 0
    if argv[:1] == ["plan"]:
        root = os.environ.get("ROOT", ".")
        central = os.environ.get("CENTRAL") or os.path.join(HERE, "..")
        with open(os.environ["NEXT_JSON"], encoding="utf-8") as fh:
            nxt = json.load(fh)
        kind = kind_of(root)
        release = pack_release(central, kind)
        try:
            inputs = caller_inputs(root, release["workflow"]) if release and release.get("workflow") else None
        except ValueError as e:
            result = {"ok": False, "version": version_of(os.environ.get("TITLE", "")), "why": str(e)}
        else:
            result = plan(os.environ.get("TITLE", ""), os.environ.get("NUMBER", "0"), nxt, kind, release, inputs,
                          os.environ.get("CENTRAL_PATH") or central)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1
    if argv[:1] == ["verify"]:
        version = os.environ.get("VERSION", "")
        fixture = os.environ.get("RELEASE_ISSUES_JSON")
        if fixture:
            try:
                with open(fixture, encoding="utf-8") as fh:
                    answer = json.load(fh)
            except (OSError, ValueError):
                answer = None
        else:
            answer = fetch(os.environ.get("GITHUB_REPOSITORY", "/"), os.environ.get("LABEL") or "accepted")
        roles_file = os.environ.get("RELEASE_ROLES_JSON")
        if roles_file:
            try:
                with open(roles_file, encoding="utf-8") as fh:
                    roles = json.load(fh)
            except (OSError, ValueError):
                roles = {}
            role_of = lambda who: roles.get(who) if isinstance(roles, dict) else None  # noqa: E731
        else:
            role_of = lambda who: role(os.environ.get("GITHUB_REPOSITORY", "/"), who)  # noqa: E731
        def plan_holds(v):
            # What merged since the last version, read now: anything outside
            # the milestone sends the release back to a person (#287).
            import importlib.util as iu
            spec = iu.spec_from_file_location("milestones", os.path.join(HERE, "milestones.py"))
            ms = iu.module_from_spec(spec)
            spec.loader.exec_module(ms)
            try:
                outside = ms.outside_plan(ms.merged_since(os.environ.get("GITHUB_REPOSITORY", "/")), v)
            except (RuntimeError, ValueError, KeyError) as exc:
                return False, f"what merged since the last version could not be read ({str(exc)[:200]})"
            return (False, "merged outside the plan: " + ", ".join(f"#{n}" for n in outside[:10])) if outside else (True, "")
        result = verify(answer, version, os.environ.get("LABEL") or "accepted", role_of, plan_holds=None if fixture else plan_holds)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else (2 if result.get("unreadable") else 1)
    print(__doc__, file=sys.stderr)
    return 64


def self_test():
    import tempfile
    failed = 0

    def check(name, got, want):
        nonlocal failed
        ok = got == want
        failed += 0 if ok else 1
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": got {got!r}, want {want!r}"))

    check("the version from the title", version_of("Release 1.2.0"), "1.2.0")
    check("the title, with spaces around", version_of("  Release 1.2.0 "), "1.2.0")
    check("not a version: two numbers", version_of("Release 1.2"), None)
    check("not a version: a suffix", version_of("Release 1.2.0-beta"), None)
    check("not a version: anything else around it", version_of("Release 1.2.0 now"), None)
    check("not a version: another word", version_of("Ship 1.2.0"), None)

    # plan
    release = {"publishes-to": "wordpress.org", "workflow": "plugin-release-wp.yml",
               "prepare": ["bash", "{central}/scripts/release-markers.sh", "prepare", ".", "{version}", "{main-file}", "{version-constant}"],
               "defaults": {"main-file": "{slug}.php", "version-constant": ""}}
    nxt = {"last": "1.1.0", "next": "1.2.0", "bump": "minor", "pending": True}
    inputs = {"slug": "my-plugin", "version-constant": "MY_PLUGIN_VERSION", "dry-run": "true"}
    p = plan("Release 1.2.0", "7", nxt, "wordpress-plugin", release, inputs, ".dx-central")
    check("plan: the pull request for an accepted version", (p["ok"], p["branch"], p["title"]), (True, "chore/7-release-1-2-0", "chore(release): 1.2.0"))
    check("plan: the kind's command, filled, the main file from the slug", p["argv"], ["bash", ".dx-central/scripts/release-markers.sh", "prepare", ".", "1.2.0", "my-plugin.php", "MY_PLUGIN_VERSION"])
    eng = engine_issue("8.0.0", "feat!: x")
    check("#563: the engine's breaking release issue is the Release form's", (version_of(eng["title"]), eng["labels"]), ("8.0.0", [LANE_LABEL]))
    check("plan: the body closes the issue and says where it goes", ("Closes #7." in p["body"], "wordpress.org" in p["body"], p["body"].endswith(AI_LINE)), (True, True, True))
    check("plan: the title is a Conventional Commit of 72 characters or fewer", len(p["title"]) <= 72 and p["title"].startswith("chore(release): "), True)
    p = plan("Release 1.2.0", "7", nxt, "wordpress-plugin", release, {"slug": "s", "main-file": "plugin.php", "version-constant": ""}, "c")
    check("plan: a main file the caller names wins; no constant is an empty argument", p["argv"][-2:], ["plugin.php", ""])
    p = plan("Release 2.0.0", "7", nxt, "wordpress-plugin", release, inputs, "c")
    check("plan: a version the labels do not give is refused, saying what they give", (p["ok"], "give 1.2.0" in p["why"], "version:major" in p["why"]), (False, True, True))
    p = plan("Release 1.2.0", "7", dict(nxt, pending=False), "wordpress-plugin", release, inputs, "c")
    check("plan: nothing pending, nothing to release", (p["ok"], "asks for a version" in p["why"]), (False, True))
    check("plan: a title that is not a version", plan("Release next", "7", nxt, "wordpress-plugin", release, inputs, "c")["ok"], False)
    check("plan: a title quoted back cannot close its code span", "`x` @all" in plan("Release `x` @all", "7", nxt, "", None, None, "c")["why"], False)
    check("plan: no kind declared", "declares no kind" in plan("Release 1.2.0", "7", nxt, "", None, None, "c")["why"], True)
    check("plan: a kind that publishes nothing", "publishes nothing" in plan("Release 1.2.0", "7", nxt, "node-app", None, None, "c")["why"], True)
    check("plan: no caller of the publishing workflow", "calls `plugin-release-wp.yml`" in plan("Release 1.2.0", "7", nxt, "wordpress-plugin", release, None, "c")["why"], True)
    p = plan("Release 1.2.0", "7", nxt, "wordpress-plugin", release, {"version-constant": "X"}, "c")
    check("plan: an input the command needs and nobody gives", (p["ok"], "no `slug` input" in p["why"]), (False, True))
    p = plan("Release 1.2.0", "7", nxt, "wordpress-plugin", release, {"slug": "${{ vars.SLUG }}"}, "c")
    check("plan: an input that is an expression is refused, not passed on", (p["ok"], "expression" in p["why"]), (False, True))
    check("plan: an expression in an input the command does not use is fine", plan("Release 1.2.0", "7", nxt, "wordpress-plugin", release, dict(inputs, **{"dry-run": "${{ github.ref != 'refs/heads/main' }}"}), "c")["ok"], True)
    check("plan: an argument is one argument, whatever it holds", prepare_argv({"prepare": ["x", "{a}"]}, {"a": "b; rm -rf /"}, "1.0.0", "c"), ["x", "b; rm -rf /"])

    # the caller's inputs, read from the repository's workflows
    with tempfile.TemporaryDirectory() as root:
        wdir = os.path.join(root, ".github", "workflows")
        os.makedirs(wdir)
        check("caller: no workflows that call it", caller_inputs(root, "plugin-release-wp.yml"), None)
        with open(os.path.join(wdir, "release.yml"), "w") as fh:
            fh.write("on: push\njobs:\n  release:\n    uses: DiluxOne/.github/.github/workflows/plugin-release-wp.yml@v5\n    with:\n      slug: my-plugin\n      dry-run: false\n    secrets: inherit\n")
        with open(os.path.join(wdir, "checks.yml"), "w") as fh:
            fh.write("on: push\njobs:\n  checks:\n    uses: DiluxOne/.github/.github/workflows/plugin-checks-wp.yml@v5\n    with:\n      slug: other\n")
        check("caller: its with, as strings", caller_inputs(root, "plugin-release-wp.yml"), {"slug": "my-plugin", "dry-run": "false"})
        with open(os.path.join(wdir, "fork.yml"), "w") as fh:
            fh.write("on: push\njobs:\n  release:\n    uses: someone/.github/.github/workflows/plugin-release-wp.yml@v5\n    with:\n      slug: evil\n")
        check("caller: a workflow of another owner is not the organisation's", caller_inputs(root, "plugin-release-wp.yml"), {"slug": "my-plugin", "dry-run": "false"})
        with open(os.path.join(wdir, "again.yml"), "w") as fh:
            fh.write("on: push\njobs:\n  release:\n    uses: DiluxOne/.github/.github/workflows/plugin-release-wp.yml@v5\n    with:\n      slug: another\n")
        try:
            caller_inputs(root, "plugin-release-wp.yml")
            check("caller: two callers that disagree are refused", "no error", "error")
        except ValueError:
            check("caller: two callers that disagree are refused", True, True)
        os.makedirs(os.path.join(root, ".github"), exist_ok=True)
        with open(os.path.join(root, ".github", "review-policy.yml"), "w") as fh:
            fh.write("kind: wordpress-plugin\n")
        check("the kind, from the repository's policy", kind_of(root), "wordpress-plugin")
    central = os.path.join(HERE, "..")
    real = pack_release(central, "wordpress-plugin")
    check("the wordpress-plugin pack says where it publishes and how it prepares", (real or {}).get("publishes-to") == "wordpress.org" and "{version}" in (real or {}).get("prepare", []), True)
    check("the pack's command is a script of this repository", os.path.isfile(os.path.join(central, fill(real["prepare"][1], {"central": "."}))) if real else False, True)
    check("the pack's publishing workflow exists", os.path.isfile(os.path.join(central, ".github", "workflows", (real or {}).get("workflow", "-"))), True)
    check("no pack for a name that is not a kind", pack_release(central, "../x"), None)

    # verify
    def node(number=12, title="Release 1.2.0", state="OPEN", reason=None, labels=("lane:release", "accepted"), events=None):
        return {"number": number, "title": title, "state": state, "stateReason": reason,
                "labels": {"nodes": [{"name": l} for l in labels]},
                "timelineItems": {"nodes": events if events is not None else [
                    {"__typename": "LabeledEvent", "createdAt": "2026-10-01T10:00:00Z", "label": {"name": "lane:release"}, "actor": {"__typename": "User", "login": "soydiloreto"}},
                    {"__typename": "LabeledEvent", "createdAt": "2026-10-02T10:00:00Z", "label": {"name": "accepted"}, "actor": {"__typename": "User", "login": "soydiloreto"}}]}}

    def answer(*nodes):
        return {"data": {"repository": {"issues": {"nodes": list(nodes)}}}}

    def vfy(a, version, label="accepted", roles=None, mode="confirm"):
        roles = {"soydiloreto": "admin"} if roles is None else roles
        return verify(a, version, label, lambda who: roles.get(who), mode)

    def ev(kind, at, label="accepted", who="User", **extra):
        e = {"__typename": kind, "createdAt": at, "actor": {"__typename": who, "login": "dilux-bot" if who == "Bot" else "soydiloreto"}}
        if kind != "RenamedTitleEvent":
            e["label"] = {"name": label}
        e.update(extra)
        return e

    r = vfy(answer(node()), "1.2.0")
    check("C1: an open release issue a person accepted approves its version", (r["ok"], r["issue"], r["by"]), (True, 12, "soydiloreto"))
    check("C1: closed as completed (its pull request merged) still approves", vfy(answer(node(state="CLOSED", reason="COMPLETED")), "1.2.0")["ok"], True)
    r = vfy(answer(node(state="CLOSED", reason="NOT_PLANNED")), "1.2.0")
    check("C2: closed as not planned approves nothing", (r["ok"], "not planned" in r["why"]), (False, True))
    r = vfy(answer(node()), "1.3.0")
    check("C3: another version is not approved by it", (r["ok"], "Release 1.3.0" in r["why"]), (False, True))
    check("C3: a title that only starts with the version does not count", vfy(answer(node(title="Release 1.2.0 and more")), "1.2.0")["ok"], False)
    r = vfy(answer(node(events=[ev("LabeledEvent", "2026-10-02T10:00:00Z", who="Bot")])), "1.2.0")
    check("C4: accepted by a bot approves nothing", (r["ok"], "not a person" in r["why"]), (False, True))
    check("C4: a person's acceptance after a bot's counts", vfy(answer(node(events=[ev("LabeledEvent", "2026-10-02T10:00:00Z", who="Bot"), ev("UnlabeledEvent", "2026-10-02T11:00:00Z"), ev("LabeledEvent", "2026-10-02T12:00:00Z")])), "1.2.0")["ok"], True)
    check("C4: a bot's after a person's does not", vfy(answer(node(events=[ev("LabeledEvent", "2026-10-02T10:00:00Z"), ev("UnlabeledEvent", "2026-10-02T11:00:00Z"), ev("LabeledEvent", "2026-10-02T12:00:00Z", who="Bot")])), "1.2.0")["ok"], False)
    check("C4: the label with no event that says who added it", vfy(answer(node(events=[])), "1.2.0")["ok"], False)
    check("C4: a person's event for another label does not count", vfy(answer(node(events=[ev("LabeledEvent", "2026-10-02T10:00:00Z", label="approved")])), "1.2.0")["ok"], False)
    check("C4: not accepted at all", vfy(answer(node(labels=("lane:release",))), "1.2.0")["ok"], False)
    check("C4: an issue without the lane's label is not a release issue", vfy(answer(node(labels=("accepted",))), "1.2.0")["ok"], False)
    renamed = node(events=[ev("LabeledEvent", "2026-10-02T10:00:00Z"), ev("RenamedTitleEvent", "2026-10-03T10:00:00Z", previousTitle="Release 1.1.9", currentTitle="Release 1.2.0")])
    r = vfy(answer(renamed), "1.2.0")
    check("C5: a title changed after the acceptance approves nothing", (r["ok"], "accepts it again" in r["why"]), (False, True))
    odd = node(events=[ev("LabeledEvent", "2026-10-02T10:00:00Z"), ev("RenamedTitleEvent", "2026-10-03T10:00:00Z", previousTitle="a `b`\nc", currentTitle="Release 1.2.0")])
    check("C5: a former title quoted back cannot close its code span", "`b`" in vfy(answer(odd), "1.2.0")["why"], False)
    check("C5: a title changed in the same second as the acceptance approves nothing", vfy(answer(node(events=[ev("LabeledEvent", "2026-10-02T10:00:00Z"), ev("RenamedTitleEvent", "2026-10-02T10:00:00Z", previousTitle="Release 1.1.9", currentTitle="Release 1.2.0")])), "1.2.0")["ok"], False)
    check("C5: a title changed before it was accepted is fine", vfy(answer(node(events=[ev("RenamedTitleEvent", "2026-10-01T10:00:00Z", previousTitle="Release ", currentTitle="Release 1.2.0"), ev("LabeledEvent", "2026-10-02T10:00:00Z")])), "1.2.0")["ok"], True)
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, ".github", "workflows"))
        open(os.path.join(root, ".github", "review-policy.yml"), "w").write("kind: wordpress-plugin\n")
        open(os.path.join(root, ".github", "workflows", "release.yml"), "w").write(
            "jobs:\n  r:\n    uses: DiluxOne/.github/.github/workflows/plugin-release-wp.yml@v5\n    with:\n      slug: dx\n")
        a = release_argv(root, "3.0.0", os.path.join(HERE, ".."), "/c")
        check("#247 argv: the kind's command for the version, as the release pull request ran it", (a[1], a[2:5], a[5]), ("/c/scripts/release-markers.sh", ["prepare", ".", "3.0.0"], "dx.php"))
        open(os.path.join(root, ".github", "review-policy.yml"), "w").write("kind: nothing-here\n")
        try:
            release_argv(root, "3.0.0", os.path.join(HERE, ".."))
            check("#247 argv: a kind that publishes nothing has none", "an argv", "an error")
        except ValueError:
            check("#247 argv: a kind that publishes nothing has none", True, True)
    # #247: a planned release, accepted by the plan.
    def plan_node(author="dilux-bot", ms_title="1.2.0", creator="soydiloreto", added_by="Bot", extra=(), ms_state="CLOSED"):
        n = node(labels=("lane:release", "accepted-by:policy"),
                 events=[ev("LabeledEvent", "2026-10-02T10:00:00Z", label="accepted-by:policy", who=added_by), *extra])
        n["author"] = {"login": author}
        n["milestone"] = {"title": ms_title, "state": ms_state, "creator": {"login": creator}} if ms_title else None
        return n
    r = vfy(answer(plan_node()), "1.2.0", mode="auto")
    check("#247 planned: the bot's issue on the version's milestone, in auto, approves it as its planner", (r["ok"], r["by"]), (True, "soydiloreto"))
    check("#247 planned: in confirm it approves nothing", vfy(answer(plan_node()), "1.2.0")["ok"], False)
    check("#287 planned: a milestone still open was not done, and approves nothing", vfy(answer(plan_node(ms_state="OPEN")), "1.2.0", mode="auto")["ok"], False)
    held = verify(answer(plan_node()), "1.2.0", role_of=lambda who: "admin", mode="auto", plan_holds=lambda v: (False, "merged outside the plan: #9"))
    check("#287 planned: something merged outside the plan since it was accepted sends it back to a person", (held["ok"], "#9" in held["why"]), (False, True))
    check("#287 planned: a person's acceptance is not held by the plan", verify(answer(node()), "1.2.0", role_of=lambda who: "admin", mode="auto", plan_holds=lambda v: (False, "x"))["ok"], True)
    closed = plan_node(); closed["state"], closed["stateReason"] = "CLOSED", "NOT_PLANNED"
    check("#247 planned: a release cancelled by closing it as not planned approves nothing", vfy(answer(closed), "1.2.0", mode="auto")["ok"], False)
    check("#247 planned: a planner who is not admin or maintain approves nothing", vfy(answer(plan_node()), "1.2.0", roles={"soydiloreto": "write"}, mode="auto")["ok"], False)
    check("#247 planned: not opened by the bot, another milestone, no milestone, the label by a person: nothing",
          [vfy(answer(n), "1.2.0", mode="auto")["ok"] for n in (plan_node(author="someone"), plan_node(ms_title="1.3.0"), plan_node(ms_title=None), plan_node(added_by="User"))],
          [False] * 4)
    check("#247 planned: a title changed after the plan accepted it approves nothing",
          vfy(answer(plan_node(extra=[ev("RenamedTitleEvent", "2026-10-03T10:00:00Z", previousTitle="Release 1.1.0", currentTitle="Release 1.2.0")])), "1.2.0", mode="auto")["ok"], False)
    r = vfy(answer(node(number=3, state="CLOSED", reason="NOT_PLANNED"), node(number=9)), "1.2.0")
    check("one accepted issue among several for the version is enough", (r["ok"], r["issue"]), (True, 9))
    check("no release issue at all", vfy(answer(), "1.2.0")["ok"], False)
    r = vfy({"errors": [{"message": "Resource not accessible by integration"}]}, "1.2.0")
    check("C6: an error is unreadable, never approved, and names the permission", (r["ok"], r.get("unreadable"), "issues: read" in r["why"]), (False, True, True))
    check("C6: no answer is unreadable", vfy(None, "1.2.0").get("unreadable"), True)
    r = vfy(answer(node()), "1.2.0", roles={"soydiloreto": "admin"})
    check("C7: an admin's acceptance approves, and says the role", (r["ok"], "(admin)" in r["why"]), (True, True))
    check("C7: a maintainer's acceptance approves", vfy(answer(node()), "1.2.0", roles={"soydiloreto": "maintain"})["ok"], True)
    r = vfy(answer(node()), "1.2.0", roles={"soydiloreto": "write"})
    check("C7: a writer's acceptance approves nothing, saying who may", (r["ok"], "role here is write" in r["why"], "admin or maintain" in r["why"]), (False, True, True))
    check("C7: a triager's acceptance approves nothing", vfy(answer(node()), "1.2.0", roles={"soydiloreto": "triage"})["ok"], False)
    check("C7: a custom role approves nothing", vfy(answer(node()), "1.2.0", roles={"soydiloreto": "release-manager"})["ok"], False)
    r = vfy(answer(node()), "1.2.0", roles={})
    check("C7: a permission that cannot be read fails closed", (r["ok"], "could not be read" in r["why"]), (False, True))
    check("C7: no way to read permissions at all fails closed", verify(answer(node()), "1.2.0")["ok"], False)
    r = vfy(answer(node(number=3), node(number=9, events=[ev("LabeledEvent", "2026-10-02T10:00:00Z")])), "1.2.0", roles={"soydiloreto": "admin"})
    check("C7: the role is read for the person who accepted", r["by"], "soydiloreto")
    check("C7: a login that is not one is never asked about", role("o/r", "x/../y"), None)
    check("a custom accepting label", vfy(answer(node(labels=("lane:release", "ok"), events=[ev("LabeledEvent", "2026-10-02T10:00:00Z", label="ok")])), "1.2.0", "ok")["ok"], True)

    # the command line, end to end
    me = os.path.abspath(__file__)
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, "a.json")
        json.dump(answer(node()), open(f, "w"))
        rf = os.path.join(tmp, "roles.json")
        json.dump({"soydiloreto": "maintain"}, open(rf, "w"))
        run = lambda env: subprocess.run([sys.executable, me, "verify"], env={**os.environ, "RELEASE_ROLES_JSON": rf, **env}, capture_output=True, text=True)
        out = run({"RELEASE_ISSUES_JSON": f, "VERSION": "1.2.0"})
        check("cli: verify approves, exit 0", (out.returncode, json.loads(out.stdout)["issue"]), (0, 12))
        check("cli: verify, another version, exit 1", run({"RELEASE_ISSUES_JSON": f, "VERSION": "9.9.9"}).returncode, 1)
        json.dump({"soydiloreto": "triage"}, open(rf, "w"))
        check("cli: verify, accepted by a triager, exit 1", run({"RELEASE_ISSUES_JSON": f, "VERSION": "1.2.0"}).returncode, 1)
        json.dump({"soydiloreto": None}, open(rf, "w"))
        check("cli: verify, the role's answer failed, exit 1", run({"RELEASE_ISSUES_JSON": f, "VERSION": "1.2.0"}).returncode, 1)
        json.dump({"errors": [{"message": "x"}]}, open(f, "w"))
        check("cli: verify, unreadable, exit 2", run({"RELEASE_ISSUES_JSON": f, "VERSION": "1.2.0"}).returncode, 2)
        root = os.path.join(tmp, "repo")
        os.makedirs(os.path.join(root, ".github", "workflows"))
        open(os.path.join(root, ".github", "review-policy.yml"), "w").write("kind: wordpress-plugin\n")
        open(os.path.join(root, ".github", "workflows", "release.yml"), "w").write("on: push\njobs:\n  release:\n    uses: DiluxOne/.github/.github/workflows/plugin-release-wp.yml@v5\n    with:\n      slug: my-plugin\n      version-constant: MY_VERSION\n")
        nf = os.path.join(tmp, "next.json")
        json.dump(nxt, open(nf, "w"))
        out = subprocess.run([sys.executable, me, "plan"], env={**os.environ, "ROOT": root, "NEXT_JSON": nf, "TITLE": "Release 1.2.0", "NUMBER": "4", "CENTRAL_PATH": ".dx-central"}, capture_output=True, text=True)
        p = json.loads(out.stdout or "{}")
        check("cli: plan, from a repository's files and the pack", (out.returncode, p.get("argv", [])[4:]), (0, ["1.2.0", "my-plugin.php", "MY_VERSION"]))
    # The workflows name the label in their conditions, where no script runs.
    for wf in ("issue-accepted.yml", "issue-triage.yml"):
        text = open(os.path.join(central, ".github", "workflows", wf), encoding="utf-8").read()
        check(f"{wf} names the schema's release label", f"'{LANE_LABEL}'" in text, True)
    import tempfile as _tf
    with _tf.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh_:
        fh_.write("planned-release: auto\n")
    check("#287: DX_AUTOPILOT=off makes a planned release confirm", (planned_mode(fh_.name, "OFF"), planned_mode(fh_.name, ""), planned_mode(fh_.name, "on")), ("confirm", "auto", "auto"))
    os.unlink(fh_.name)
    print("all tests passed" if not failed else f"{failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
