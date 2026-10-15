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
                            issue for VERSION exists, a person accepted it and
                            its title still names VERSION; JSON on stdout,
                            exit 0 when it approves the release, 1 when not,
                            2 when the issues could not be read
  release-issue.py --test   self-test

Environment:
  plan:   TITLE (the issue's title), NUMBER (the issue), NEXT_JSON (a file
          holding `scripts/next-version.py --json`), ROOT (the repository's
          checkout, default .), CENTRAL (the checkout of DiluxOne/.github,
          default this script's repository), CENTRAL_PATH (how the command
          names CENTRAL, default CENTRAL)
  verify: VERSION, LABEL (the accepting label, default accepted),
          GITHUB_REPOSITORY, GH_TOKEN (issues: read); RELEASE_ISSUES_JSON, a
          file holding the GraphQL answer, replaces the call (the self-test
          uses it)

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
TITLE = re.compile(r"^Release (\d+\.\d+\.\d+)$")
AI_LINE = "🤖 AI-generated · Claude Opus 5.5 (Anthropic)"
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
    for k, v in values.items():
        if "${{" in v:
            raise ValueError(f"the caller's input {k} is an expression ({v}); the release pull request needs its value written out")
    for k, default in (release.get("defaults") or {}).items():
        if k not in values:
            values[k] = fill(str(default), values)
    values.update({"version": version, "central": central_path})
    return [fill(str(a), values) for a in release.get("prepare") or []]


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
    where = release.get("publishes-to") or "where the kind publishes"
    branch = f"chore/{number}-release-{version.replace('.', '-')}"
    pr_title = f"chore(release): {version}"
    body = f"""## 📝 What changes

The tree says {version}: the hold on the newest changelog entry is removed and the version markers name {version}, as `kinds/{kind}/pack.yml` prepares a release.

## 💡 Why

Closes #{number}. A person accepted the release issue, which is the decision to publish {version}. Once this pull request merges, the release workflow checks that the issue is still accepted by a person and that its version is the one computed, then publishes {version} to {where}.

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


def verify(answer, version, label="accepted"):
    """Whether a person approved releasing `version` (pure)."""
    if not isinstance(answer, dict) or answer.get("errors") or not isinstance(((answer.get("data") or {}).get("repository") or {}).get("issues"), dict):
        why = json.dumps(answer.get("errors"))[:300] if isinstance(answer, dict) and answer.get("errors") else "no answer"
        return {"ok": False, "unreadable": True, "version": version, "why": f"the release issues could not be read ({why}); the caller's release job needs `issues: read`"}
    nodes = answer["data"]["repository"]["issues"].get("nodes") or []
    wanted = f"Release {version}"
    mine = [x for x in nodes if (x.get("title") or "").strip() == wanted]
    if not mine:
        return {"ok": False, "version": version, "why": f"no issue titled `{wanted}` with the `{LANE_LABEL}` label exists"}
    whys = []
    for node in mine:
        ok, why, by, at = judge(node, label)
        if ok:
            return {"ok": True, "version": version, "issue": node.get("number"), "by": by, "at": at,
                    "why": f"issue #{node.get('number')} `{wanted}`, accepted by {by} at {at}"}
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


# --- the command line -------------------------------------------------------

def main(argv):
    if argv[:1] == ["--test"]:
        return self_test()
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
        result = verify(answer, version, os.environ.get("LABEL") or "accepted")
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

    def ev(kind, at, label="accepted", who="User", **extra):
        e = {"__typename": kind, "createdAt": at, "actor": {"__typename": who, "login": "dilux-bot" if who == "Bot" else "soydiloreto"}}
        if kind != "RenamedTitleEvent":
            e["label"] = {"name": label}
        e.update(extra)
        return e

    r = verify(answer(node()), "1.2.0")
    check("C1: an open release issue a person accepted approves its version", (r["ok"], r["issue"], r["by"]), (True, 12, "soydiloreto"))
    check("C1: closed as completed (its pull request merged) still approves", verify(answer(node(state="CLOSED", reason="COMPLETED")), "1.2.0")["ok"], True)
    r = verify(answer(node(state="CLOSED", reason="NOT_PLANNED")), "1.2.0")
    check("C2: closed as not planned approves nothing", (r["ok"], "not planned" in r["why"]), (False, True))
    r = verify(answer(node()), "1.3.0")
    check("C3: another version is not approved by it", (r["ok"], "Release 1.3.0" in r["why"]), (False, True))
    check("C3: a title that only starts with the version does not count", verify(answer(node(title="Release 1.2.0 and more")), "1.2.0")["ok"], False)
    r = verify(answer(node(events=[ev("LabeledEvent", "2026-10-02T10:00:00Z", who="Bot")])), "1.2.0")
    check("C4: accepted by a bot approves nothing", (r["ok"], "not a person" in r["why"]), (False, True))
    check("C4: a person's acceptance after a bot's counts", verify(answer(node(events=[ev("LabeledEvent", "2026-10-02T10:00:00Z", who="Bot"), ev("UnlabeledEvent", "2026-10-02T11:00:00Z"), ev("LabeledEvent", "2026-10-02T12:00:00Z")])), "1.2.0")["ok"], True)
    check("C4: a bot's after a person's does not", verify(answer(node(events=[ev("LabeledEvent", "2026-10-02T10:00:00Z"), ev("UnlabeledEvent", "2026-10-02T11:00:00Z"), ev("LabeledEvent", "2026-10-02T12:00:00Z", who="Bot")])), "1.2.0")["ok"], False)
    check("C4: the label with no event that says who added it", verify(answer(node(events=[])), "1.2.0")["ok"], False)
    check("C4: a person's event for another label does not count", verify(answer(node(events=[ev("LabeledEvent", "2026-10-02T10:00:00Z", label="approved")])), "1.2.0")["ok"], False)
    check("C4: not accepted at all", verify(answer(node(labels=("lane:release",))), "1.2.0")["ok"], False)
    check("C4: an issue without the lane's label is not a release issue", verify(answer(node(labels=("accepted",))), "1.2.0")["ok"], False)
    renamed = node(events=[ev("LabeledEvent", "2026-10-02T10:00:00Z"), ev("RenamedTitleEvent", "2026-10-03T10:00:00Z", previousTitle="Release 1.1.9", currentTitle="Release 1.2.0")])
    r = verify(answer(renamed), "1.2.0")
    check("C5: a title changed after the acceptance approves nothing", (r["ok"], "accepts it again" in r["why"]), (False, True))
    odd = node(events=[ev("LabeledEvent", "2026-10-02T10:00:00Z"), ev("RenamedTitleEvent", "2026-10-03T10:00:00Z", previousTitle="a `b`\nc", currentTitle="Release 1.2.0")])
    check("C5: a former title quoted back cannot close its code span", "`b`" in verify(answer(odd), "1.2.0")["why"], False)
    check("C5: a title changed in the same second as the acceptance approves nothing", verify(answer(node(events=[ev("LabeledEvent", "2026-10-02T10:00:00Z"), ev("RenamedTitleEvent", "2026-10-02T10:00:00Z", previousTitle="Release 1.1.9", currentTitle="Release 1.2.0")])), "1.2.0")["ok"], False)
    check("C5: a title changed before it was accepted is fine", verify(answer(node(events=[ev("RenamedTitleEvent", "2026-10-01T10:00:00Z", previousTitle="Release ", currentTitle="Release 1.2.0"), ev("LabeledEvent", "2026-10-02T10:00:00Z")])), "1.2.0")["ok"], True)
    r = verify(answer(node(number=3, state="CLOSED", reason="NOT_PLANNED"), node(number=9)), "1.2.0")
    check("one accepted issue among several for the version is enough", (r["ok"], r["issue"]), (True, 9))
    check("no release issue at all", verify(answer(), "1.2.0")["ok"], False)
    r = verify({"errors": [{"message": "Resource not accessible by integration"}]}, "1.2.0")
    check("C6: an error is unreadable, never approved, and names the permission", (r["ok"], r.get("unreadable"), "issues: read" in r["why"]), (False, True, True))
    check("C6: no answer is unreadable", verify(None, "1.2.0").get("unreadable"), True)
    check("a custom accepting label", verify(answer(node(labels=("lane:release", "ok"), events=[ev("LabeledEvent", "2026-10-02T10:00:00Z", label="ok")])), "1.2.0", "ok")["ok"], True)

    # the command line, end to end
    me = os.path.abspath(__file__)
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, "a.json")
        json.dump(answer(node()), open(f, "w"))
        run = lambda env: subprocess.run([sys.executable, me, "verify"], env={**os.environ, **env}, capture_output=True, text=True)
        out = run({"RELEASE_ISSUES_JSON": f, "VERSION": "1.2.0"})
        check("cli: verify approves, exit 0", (out.returncode, json.loads(out.stdout)["issue"]), (0, 12))
        check("cli: verify, another version, exit 1", run({"RELEASE_ISSUES_JSON": f, "VERSION": "9.9.9"}).returncode, 1)
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
    print("all tests passed" if not failed else f"{failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
