#!/usr/bin/env python3
"""The installer (#197, phase 12): an organisation's configuration of the
engine, in its own `.github` repository.

The engine (the workflows, scripts, gates and kinds) stays here and is called
by tag; the configuration is the organisation's (docs/plans/autonomy.md,
phase 12), and scripts/config-overlay.sh lays it over the engine's defaults
in every run. This writes that configuration:

  org.yml             who the organisation is and its App
  repos.yml           every repository and its kinds, from detection
                      (scripts/detect.py, each pack's `detect`), and, in
                      `repro:`, the way to reproduce a bug its stack
                      proposes for each one that declares none (#377:
                      policy/repro-stacks.yml); one no stack is recognised
                      in is said, to be declared by hand
  .github/workflows/org-pull-request.yml
                      the pull request pipeline its ruleset requires of every
                      repository, calling the engine's workflows
  workflow-templates/ the callers a repository adds (Actions, New workflow)

What it leaves out keeps the engine's default (policy/, labels.yml, kinds/):
an organisation adds those files when it wants its own. On an existing
configuration nothing is replaced: what is there stays, a repository that
repos.yml lacks is added, and a file that is missing is written. So
installing again loses nothing.

  install.py plan  --org ORG --app SLUG --app-id ID --dir DIR
      write the configuration into DIR (a checkout of ORG/.github, or an
      empty directory) and print what it kept, added and wrote
  install.py diff  --org ORG --app SLUG --app-id ID --dir DIR
      the same, in a copy: what installing again would change, DIR untouched
  install.py apply --org ORG --app SLUG --app-id ID
      plan in a clone of ORG/.github (created, public, when missing), on the
      branch chore/install-engine, and open that single pull request; then
      print the organisation's own steps (its App's key, its variables, the
      ruleset), which no pull request can do
  install.py --test   self-test

Environment: GH_TOKEN, as the organisation's administrator (repositories:
read, and for apply contents and pull requests: write on ORG/.github).
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import org  # noqa: E402  the engine's organisation, from org.yml (#191)

BRANCH = "chore/install-engine"

# What the organisation's App needs for the engine's workflows: the one
# list the creation link and the steps are written from.
APP_PERMISSIONS = {
    "actions": "write",
    "checks": "read",
    "contents": "write",
    "issues": "write",
    "metadata": "read",
    "organization_administration": "read",
    "organization_projects": "write",
    "pull_requests": "write",
    "repository_projects": "write",
}


def app_url(owner, name=None):
    """GitHub's form to create the organisation's App, filled in: private,
    with no webhook, and APP_PERMISSIONS."""
    from urllib.parse import urlencode
    query = {"name": name or f"{owner}-bot", "url": f"https://github.com/{owner}", "public": "false", "webhook_active": "false", **APP_PERMISSIONS}
    return f"https://github.com/organizations/{owner}/settings/apps/new?" + urlencode(query)


def _module(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


detect = _module("detect", "detect.py")
repro_ways = _module("repro_ways", "repro-ways.py")


def run_gh(*args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return out.returncode, out.stdout, out.stderr


# A security advisory's temporary private fork, which GitHub names after
# its repository and the advisory and does not mark as a fork.
ADVISORY_FORK = re.compile(r"-ghsa(-[23456789cfghjmpqrvwx]{4}){3}$")


def repositories(owner, run=run_gh):
    """{name: default branch} of the organisation's own repositories: not
    archived, not forks, not an advisory's temporary fork."""
    rc, out, err = run("repo", "list", owner, "--limit", "1000", "--no-archived", "--json", "name,isFork,defaultBranchRef")
    if rc != 0:
        raise RuntimeError(f"could not list {owner}'s repositories: {err.strip()[:200]}")
    if len(json.loads(out or "[]")) >= 1000:
        raise RuntimeError("1000 repositories or more: the list would be cut; raise the limit")
    return {r["name"]: (r.get("defaultBranchRef") or {}).get("name") or "main" for r in json.loads(out or "[]")
            if not r.get("isFork") and not ADVISORY_FORK.search(r["name"])}


def secrets_of(workflow):
    """The secrets an engine workflow declares (workflow_call), in order."""
    import yaml
    with open(os.path.join(ENGINE, ".github", "workflows", workflow), encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    on = doc.get(True) or doc.get("on") or {}
    return list(((on.get("workflow_call") or {}).get("secrets") or {}).keys())


USES = re.compile(r"^\s+uses: " + re.escape(org.CENTRAL) + r"/\.github/workflows/([\w.-]+\.yml)@")


def render(text, owner):
    """An engine caller made another organisation's: its own `.github` in the
    guards, its App through DX_BOT_LOGIN, and each `secrets: inherit` (which
    does not cross organisations) as the secrets the called workflow asks for."""
    text = text.replace(f"github.repository != '{org.CENTRAL}'", f"github.repository != '{owner}/.github'")
    text = text.replace(f"== '{org.BOT}'", f"== (vars.DX_BOT_LOGIN || '{org.BOT}')")
    out, called = [], None
    for line in text.split("\n"):
        m = USES.match(line)
        if m:
            called = m.group(1)
        elif re.match(r"^  [\w-]+:\s*$", line):
            called = None
        s = re.match(r"^(\s+)secrets: inherit\s*$", line)
        if s and called:
            names = secrets_of(called)
            # A workflow that declares none reads its environment's secrets
            # (the release's wordpress-org: SVN, the release App's key), which
            # only `inherit` hands over, and only within one organisation: it
            # stays, and docs/installing.md says what that leaves out.
            if names:
                out.append(f"{s.group(1)}secrets:")
                out += [f"{s.group(1)}  {n}: ${{{{ secrets.{n} }}}}" for n in names]
                continue
        out.append(line)
    return "\n".join(out)


def org_yml(owner, app, app_id):
    return (f"# Who the organisation is, for the engine's scripts (written by\n"
            f"# {org.CENTRAL}'s scripts/install.py, #197). The engine lays this\n"
            f"# repository's configuration over its own defaults in every run\n"
            f"# (scripts/config-overlay.sh).\n"
            f"org: {owner}\ncentral: {owner}/.github\nbot:\n  app: {app}\n  id: {int(app_id)}\n")


def repos_yml(lines):
    return ("# Every repository of the organisation and what it is: its kinds of\n"
            "# project (a pack of the engine's kinds/, or one of this repository's),\n"
            "# each over the paths it covers, with their roles. Written by the\n"
            "# installer from detection; correct what it got wrong. A repository\n"
            "# with no kinds is unclassified.\n"
            "repos:\n" + "".join(l + "\n" for l in sorted(lines, key=lambda l: l.strip().lower())))


REPRO_HEAD = ("\n# How a repository reproduces a bug when neither its kind's pack nor its\n"
              "# own .github/review-policy.yml says (#377): its `repro:` as that file\n"
              "# takes it (scripts/repro-ways.py), proposed by the installer from its\n"
              "# stack (policy/repro-stacks.yml). Correct it; the repository's own\n"
              "# policy goes over it.\nrepro:\n")


def with_repro(text, proposals):
    """repos.yml with a `repro:` entry for each (name, way's name, way),
    in its section (written at the end when there is none)."""
    block = "".join(f"  {name}:\n    ways:\n" + detect.way_yaml(wname, way, 6) for name, wname, way in proposals)
    lines = text.split("\n")
    if "repro:" in lines:
        i = lines.index("repro:") + 1
        return "\n".join(lines[:i]) + "\n" + block + "\n".join(lines[i:])
    return text.rstrip("\n") + "\n" + REPRO_HEAD + block


def declares(conf, name, own, engine=ENGINE):
    """The ways a repository declares (scripts/repro-ways.py declares): its
    kind's pack, repos.yml `repro:` and its own policy (`own`)."""
    return repro_ways.declares(conf, name, own or {}, os.path.join(engine, "kinds"))


def plan(owner, app, app_id, target, repos, found_of, engine=ENGINE, policy_of=None, way_of=None):
    """Writes the configuration into `target` and returns what it did, one
    line each: "kept PATH", "wrote PATH", "added NAME to repos.yml",
    "proposed …" or "lacks a way: …". `policy_of(name)` is a repository's
    own .github/review-policy.yml, `way_of(name)` what its stack proposes
    (detect.stack_way); without them no way is proposed."""
    import yaml
    did = []
    rules = detect.packs()

    def write(path, text):
        full = os.path.join(target, path)
        if os.path.exists(full):
            did.append(f"kept {path}")
            return
        os.makedirs(os.path.dirname(full) or target, exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(text)
        did.append(f"wrote {path}")

    write("org.yml", org_yml(owner, app, app_id))
    path = os.path.join(target, "repos.yml")
    known = set()
    excluded = set()
    if os.path.exists(path):
        conf = detect.load(path)
        known = set((conf.get("repos") or {}).keys())
        excluded = set(conf.get("exclude") or [])
    new = sorted(n for n in repos if n not in known and n not in excluded)
    lines = []
    unread = []
    for name in new:
        # One that cannot be read (a rate limit, a permission) is written
        # unclassified and said so, not taken for a repository of no kind.
        try:
            lines.append(detect.entry(name, found_of(name), rules))
        except Exception as exc:  # noqa: BLE001  any failure to read it, said and not fatal
            lines.append(detect.entry(name, [], rules) + "   # detection could not read it: classify it by hand")
            unread.append(f"could not read {name} ({str(exc)[:80]}): unclassified")
    if os.path.exists(path):
        if lines:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(detect.with_entries(text, lines))
            did += [f"added {n} to repos.yml" for n in new]
        else:
            did.append("kept repos.yml")
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(repos_yml(lines))
        yaml.safe_load(open(path, encoding="utf-8"))
        did.append(f"wrote repos.yml ({len(lines)} repositories)")
    did += unread
    if policy_of and way_of:
        did += propose_ways(path, [n for n in sorted(repos) if n not in excluded], policy_of, way_of, engine)
    with open(os.path.join(engine, ".github", "workflows", "org-pull-request.yml"), encoding="utf-8") as fh:
        pipeline = fh.read()
    write(os.path.join(".github", "workflows", "org-pull-request.yml"), render(pipeline, owner))
    templates = os.path.join(engine, "workflow-templates")
    for name in sorted(os.listdir(templates)):
        with open(os.path.join(templates, name), encoding="utf-8") as fh:
            text = fh.read()
        write(os.path.join("workflow-templates", name), render(text, owner) if name.endswith(".yml") else text)
    return did


def propose_ways(path, names, policy_of, way_of, engine=ENGINE):
    """For each repository that declares no way to reproduce a bug, the way
    its stack proposes, added to repos.yml `repro:`; what it did, one line
    each. One that cannot be read is said, never taken for one with none."""
    conf = detect.load(path)
    did, proposals = [], []
    for name in names:
        try:
            if repro_ways.by_design(conf, name) or declares(conf, name, policy_of(name), engine):
                continue
            found = way_of(name)
        except Exception as exc:  # noqa: BLE001  any failure to read it, said and not fatal
            did.append(f"lacks a way? {name} could not be read ({str(exc)[:80]})")
            continue
        if found:
            proposals.append((name, found[1], found[2]))
            did.append(f"proposed the {found[1]} way ({found[0]}) for {name} in repos.yml `repro:`")
        else:
            did.append(f"lacks a way: {name} declares none to reproduce a bug, and no stack of policy/repro-stacks.yml is recognised in it: declare one by hand")
    if proposals:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(with_repro(text, proposals))
    return did


def material(did):
    """What installing again changed: anything but a kept file, or what it
    only says (a repository it proposes no way for)."""
    return [d for d in did if not d.startswith(("kept ", "lacks a way"))]


def steps(owner, app):
    """What only the organisation's administrator can do: no pull request
    holds a secret, a variable or a ruleset."""
    perms = ", ".join(f"{k} {v}" for k, v in APP_PERMISSIONS.items())
    return f"""The organisation's own steps, after merging the pull request:

1. Its App ({app}): create it with the form filled in ({perms}), generate its private key, and install it on all repositories. {app_url(owner, app)}
2. Organisation secrets: DILUX_BOT_PRIVATE_KEY (the App's private key), CLAUDE_CODE_OAUTH_TOKEN (`claude setup-token`) or ANTHROPIC_API_KEY. https://github.com/organizations/{owner}/settings/secrets/actions
3. Organisation variables: DILUX_BOT_CLIENT_ID (the App's client ID), DX_BOT_LOGIN ({app}[bot]), DX_BOT_APP ({app}), DX_BOT_ID (the App's bot user id: gh api users/{app}%5Bbot%5D --jq .id). https://github.com/organizations/{owner}/settings/variables/actions
4. An organisation ruleset on every repository's default branch that requires the workflow {owner}/.github/.github/workflows/org-pull-request.yml (GitHub Team; on Free, each repository adds a copy of it as .github/workflows/pull-request.yml). https://github.com/organizations/{owner}/settings/rules
"""


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        ok = got == want
        failed += 0 if ok else 1
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": got {got!r}, want {want!r}"))

    import yaml
    with open(os.path.join(ENGINE, ".github", "workflows", "org-pull-request.yml"), encoding="utf-8") as fh:
        pipeline = render(fh.read(), "Acme")
    check("render: the guards name the organisation's own .github", (f"'{org.CENTRAL}'" in pipeline, "github.repository != 'Acme/.github'" in pipeline), (False, True))
    check("render: no secrets: inherit, which does not cross organisations", "secrets: inherit" in pipeline, False)
    doc = yaml.safe_load(pipeline)
    review = doc["jobs"]["review"]
    check("render: the review gets the secrets claude-review.yml asks for", sorted(review.get("secrets") or {}), sorted(secrets_of("claude-review.yml")))
    check("render: the engine is still called by tag", review["uses"].startswith(f"{org.CENTRAL}/.github/workflows/claude-review.yml@v"), True)
    check("render: the App is the organisation's variable", f"== '{org.BOT}'" in pipeline, False)
    with open(os.path.join(ENGINE, "workflow-templates", "release-wp.yml"), encoding="utf-8") as fh:
        release = yaml.safe_load(render(fh.read(), "Acme"))
    check("render: a caller of a workflow that declares no secrets keeps inherit (its environment's secrets)",
          sorted((j, job.get("secrets")) for j, job in release["jobs"].items() if "uses" in job),
          [("publish", "inherit"), ("release", "inherit")])

    found = {"plugin-a": ["wordpress-plugin"], "site": []}
    with tempfile.TemporaryDirectory() as t:
        did = plan("Acme", "acme-bot", 7, t, {"plugin-a": "main", "site": "main"}, lambda n: found[n])
        check("a new configuration: every file is written", sorted(d.split(" ")[1] for d in did if d.startswith("wrote ")),
              sorted(["org.yml", "repos.yml", os.path.join(".github", "workflows", "org-pull-request.yml")] +
                     [os.path.join("workflow-templates", n) for n in os.listdir(os.path.join(ENGINE, "workflow-templates"))]))
        conf = yaml.safe_load(open(os.path.join(t, "org.yml")))
        check("org.yml names the organisation and its App", (conf["org"], conf["central"], conf["bot"]), ("Acme", "Acme/.github", {"app": "acme-bot", "id": 7}))
        repos = yaml.safe_load(open(os.path.join(t, "repos.yml")))["repos"]
        check("repos.yml holds what detection found", (repos["plugin-a"]["kinds"][0]["kind"], repos["site"]["kinds"]), ("wordpress-plugin", []))
        rc = _module("repos_config", "repos-config.py")
        check("repos.yml is to the schema", rc.problems(rc.load(os.path.join(t, "repos.yml")), rc.dirs(os.path.join(ENGINE, "kinds")), rc.dirs(os.path.join(ENGINE, "design-systems"))), [])
        again = plan("Acme", "acme-bot", 7, t, {"plugin-a": "main", "site": "main"}, lambda n: found[n])
        check("installing again changes nothing", material(again), [])
        found["new-one"] = []
        more = plan("Acme", "acme-bot", 7, t, {"plugin-a": "main", "site": "main", "new-one": "main"}, lambda n: found[n])
        check("a new repository is added, the rest kept", material(more), ["added new-one to repos.yml"])

    # #377: every repository that declares no way to reproduce a bug gets
    # the one its stack proposes, in repos.yml `repro:`.
    files = {"api-py": {"pyproject.toml": "[project]\nname = 'api'\n\n[tool.pytest.ini_options]\ntestpaths = ['tests']\n"},
             "svc-net": {"Svc.sln": "", "src/Svc/Svc.csproj": "<Project/>", "tests/Svc.Tests/Svc.Tests.csproj": "<PackageReference Include=\"Microsoft.NET.Test.Sdk\" />"},
             "plugin-a": {"composer.json": "phpunit"}, "own": {"pyproject.toml": "pytest"}, "site": {"index.html": ""}}
    kinds_of = {"plugin-a": ["wordpress-plugin"]}
    own = {"own": {"repro": {"ways": {"cli": {"layer": ["logic", "cli"], "test": "t/{n}.sh", "run": "bash {test}", "junit": "build/j.xml"}}}}}
    way_of = lambda n: detect.stack_way(set(files[n]), lambda p: files[n].get(p, ""))  # noqa: E731
    with tempfile.TemporaryDirectory() as t:
        names = {n: "main" for n in files}
        did = plan("Acme", "acme-bot", 7, t, names, lambda n: kinds_of.get(n, []), policy_of=lambda n: own.get(n, {}), way_of=way_of)
        conf = yaml.safe_load(open(os.path.join(t, "repos.yml")))
        py = conf["repro"]["api-py"]["ways"]["pytest"]
        check("C1 a pytest repository with no way: its pull request adds a Python way that writes a JUnit report",
              (py["test"], "--junitxml=build/repro.xml" in py["run"], py["junit"]), ("tests/repro/test_issue_{n}.py", True, "build/repro.xml"))
        net = conf["repro"]["svc-net"]["ways"]["dotnet-test"]
        check("C2 a .NET test project: a dotnet test way with a JUnit logger",
              ("dotnet test tests/Svc.Tests/Svc.Tests.csproj" in net["run"], '--logger "junit;' in net["run"], net["test"]),
              (True, True, "tests/Svc.Tests/Repro/Issue{n}Tests.cs"))
        check("a repository whose pack or own policy declares a way gets none proposed", sorted(conf["repro"]), ["api-py", "svc-net"])
        check("one no stack is recognised in is said, by name", [d.split(":")[0] for d in did if d.startswith("lacks a way")], ["lacks a way"])
        check("what it proposes is said, by repository", sorted(d.split(" for ")[1].split(" ")[0] for d in did if d.startswith("proposed ")), ["api-py", "svc-net"])
        check("repos.yml with its ways is to the schema",
              rc.problems(rc.load(os.path.join(t, "repos.yml")), rc.dirs(os.path.join(ENGINE, "kinds")), rc.dirs(os.path.join(ENGINE, "design-systems"))), [])
        again = plan("Acme", "acme-bot", 7, t, names, lambda n: kinds_of.get(n, []), policy_of=lambda n: own.get(n, {}), way_of=way_of)
        check("installing again proposes nothing more: the ways are declared now", material(again), [])
        files["new-py"] = {"pytest.ini": "[pytest]"}
        more = plan("Acme", "acme-bot", 7, t, dict(names, **{"new-py": "main"}), lambda n: kinds_of.get(n, []), policy_of=lambda n: own.get(n, {}), way_of=way_of)
        check("a new repository's way joins the others in `repro:`", (material(more), sorted(yaml.safe_load(open(os.path.join(t, "repos.yml")))["repro"])),
              (["added new-py to repos.yml", "proposed the pytest way (python-pytest) for new-py in repos.yml `repro:`"], ["api-py", "new-py", "svc-net"]))

        files["scratch"] = {"go.mod": "module x"}
        text = open(os.path.join(t, "repos.yml")).read()
        open(os.path.join(t, "repos.yml"), "w").write(text.replace("\nrepro:\n", "\nrepro:\n  scratch: false\n"))
        none = plan("Acme", "acme-bot", 7, t, dict(names, scratch="main"), lambda n: kinds_of.get(n, []), policy_of=lambda n: own.get(n, {}), way_of=way_of)
        check("a repository repos.yml says has no way by design gets none proposed", (material(none), yaml.safe_load(open(os.path.join(t, "repos.yml")))["repro"]["scratch"]),
              (["added scratch to repos.yml"], False))

        def unreadable_policy(n):
            raise RuntimeError("HTTP 502")
        files["late"] = {"go.mod": "module x"}
        said = plan("Acme", "acme-bot", 7, t, {"late": "main"}, lambda n: [], policy_of=unreadable_policy, way_of=way_of)
        check("a repository whose policy cannot be read is said, never given a way it may not need",
              ([d for d in said if d.startswith("lacks a way? late")] != [], "late" in (yaml.safe_load(open(os.path.join(t, "repos.yml"))).get("repro") or {})), (True, False))

    def unreadable(name):
        raise RuntimeError("HTTP 403: rate limit")
    with tempfile.TemporaryDirectory() as t:
        did = plan("Acme", "acme-bot", 7, t, {"locked": "main"}, unreadable)
        text = open(os.path.join(t, "repos.yml")).read()
        check("a repository detection cannot read is unclassified and said so",
              ("# detection could not read it" in text, any(d.startswith("could not read locked") for d in did)), (True, True))

    # DiluxOne's own configuration, installed again over itself: nothing
    # of it is lost (the "done when" of phase 12).
    with tempfile.TemporaryDirectory() as t:
        for f in ("org.yml", "repos.yml"):
            shutil.copy(os.path.join(ENGINE, f), t)
        before = {f: open(os.path.join(ENGINE, f)).read() for f in ("org.yml", "repos.yml")}
        conf = detect.load(os.path.join(ENGINE, "repos.yml"))
        did = plan(org.ORG, org.APP, org.BOT_ID, t, {n: "main" for n in conf["repos"]}, lambda n: [])
        check("DiluxOne again: org.yml and repos.yml kept as they are", {f: open(os.path.join(t, f)).read() for f in before}, before)
        check("DiluxOne again: nothing of its configuration changes", [d for d in material(did) if not d.startswith("wrote .github/") and not d.startswith("wrote workflow-templates/")], [])

    listing = json.dumps([{"name": "plugin-a", "isFork": False, "defaultBranchRef": {"name": "trunk"}},
                          {"name": "someone-else", "isFork": True, "defaultBranchRef": {"name": "main"}},
                          {"name": "plugin-a-ghsa-jg3v-wpv3-q3cc", "isFork": False, "defaultBranchRef": {"name": "main"}}])
    check("repositories: its own, not forks nor an advisory's temporary fork", repositories("Acme", lambda *a: (0, listing, "")), {"plugin-a": "trunk"})
    # apply against a local stand-in for ORG/.github and for gh.
    with tempfile.TemporaryDirectory() as t:
        env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        old = dict(os.environ)
        os.environ.update(env)
        try:
            origin = os.path.join(t, "origin.git")
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
            seed = os.path.join(t, "seed")
            subprocess.run(["git", "clone", "-q", origin, seed], check=True, capture_output=True)
            open(os.path.join(seed, "README.md"), "w").write("x\n")
            subprocess.run(["git", "-C", seed, "add", "-A"], check=True)
            subprocess.run(["git", "-C", seed, "commit", "-q", "-m", "init"], check=True)
            subprocess.run(["git", "-C", seed, "push", "-q", "origin", "HEAD:main"], check=True, capture_output=True)
            calls, state = [], {"open": ""}

            def fake(*args):
                calls.append(args[:2])
                if args[:2] == ("pr", "list"):
                    return 0, state["open"], ""
                if args[:2] == ("pr", "create"):
                    return 0, "https://github.com/Acme/.github/pull/1", ""
                return 0, "", ""
            heads = lambda: subprocess.run(["git", "--git-dir", origin, "rev-parse", BRANCH], capture_output=True, text=True).stdout.strip()  # noqa: E731
            rc, out = apply("Acme", "acme-bot", 7, {"plugin-a": "main"}, lambda n: [], run=fake, clone_url=origin)
            check("apply: the first run pushes the branch and opens its pull request", (rc, bool(heads()), ("pr", "create") in calls), (0, True, True))
            first = heads()
            # Its pull request was merged and the branch left: start again from main.
            subprocess.run(["git", "-C", seed, "pull", "-q", "origin", BRANCH], check=True, capture_output=True)
            open(os.path.join(seed, "org.yml"), "w").write(open(os.path.join(seed, "org.yml")).read().replace("id: 7", "id: 8"))
            subprocess.run(["git", "-C", seed, "commit", "-q", "-am", "merged, then corrected"], check=True)
            subprocess.run(["git", "-C", seed, "push", "-q", "origin", "HEAD:main"], check=True, capture_output=True)
            calls.clear()
            rc, out = apply("Acme", "acme-bot", 7, {"plugin-a": "main", "plugin-b": "main"}, lambda n: [], run=fake, clone_url=origin)
            log = subprocess.run(["git", "--git-dir", origin, "log", "--format=%s", BRANCH], capture_output=True, text=True).stdout
            check("apply: a stale branch of a merged pull request starts again from main, keeping main's corrections",
                  (rc, "merged, then corrected" in log, ("pr", "create") in calls, heads() != first), (0, True, True, True))
            # With its pull request open, a run builds on it and pushes, no new one.
            state["open"] = "https://github.com/Acme/.github/pull/2"
            calls.clear()
            before = heads()
            rc, out = apply("Acme", "acme-bot", 7, {"plugin-a": "main", "plugin-b": "main", "plugin-c": "main"}, lambda n: [], run=fake, clone_url=origin)
            parent = subprocess.run(["git", "--git-dir", origin, "rev-parse", BRANCH + "^"], capture_output=True, text=True).stdout.strip()
            check("apply: with its pull request open, it builds on that branch and opens none", (rc, parent == before, ("pr", "create") in calls, "Updated" in out), (0, True, False, True))
            before = heads()
            rc, out = apply("Acme", "acme-bot", 7, {"plugin-d": "main"}, lambda n: [], run=lambda *a: (1, "", "HTTP 502") if a[:2] == ("pr", "list") else fake(*a), clone_url=origin)
            check("apply: open pull requests that cannot be read stop it, nothing pushed", (rc, heads() == before), (1, True))
            calls.clear()
            rc, out = apply("Acme", "acme-bot", 7, {"plugin-a": "main", "plugin-b": "main", "plugin-c": "main"}, lambda n: [], run=fake, clone_url=origin)
            check("apply: nothing more to change pushes and opens nothing", (rc, ("pr", "create") in calls, "Nothing to change" in out), (0, False, True))
        finally:
            os.environ.clear()
            os.environ.update(old)

    check("the steps name each URL of the organisation", all(f"/organizations/Acme/settings/{p}" in steps("Acme", "acme-bot") for p in ("apps/new", "secrets/actions", "variables/actions", "rules")), True)
    from urllib.parse import parse_qs, urlparse
    q = {k: v[0] for k, v in parse_qs(urlparse(app_url("Acme")).query).items()}
    check("the App's form: named, private, no webhook, every permission the engine needs",
          (q.pop("name"), q.pop("url"), q.pop("public"), q.pop("webhook_active"), q), ("Acme-bot", "https://github.com/Acme", "false", "false", APP_PERMISSIONS))
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    ap = argparse.ArgumentParser(prog="install.py")
    ap.add_argument("mode", choices=["plan", "diff", "apply"])
    ap.add_argument("--org", required=True)
    ap.add_argument("--app", required=True)
    ap.add_argument("--app-id", required=True, type=int)
    ap.add_argument("--dir")
    a = ap.parse_args(argv)
    repos = repositories(a.org)
    found_of = lambda name: detect.remote(f"{a.org}/{name}", repos[name])  # noqa: E731
    policy_of = lambda name: detect.remote_policy(f"{a.org}/{name}", repos[name])  # noqa: E731
    way_of = lambda name: detect.remote_way(f"{a.org}/{name}", repos[name])  # noqa: E731
    if a.mode in ("plan", "diff"):
        if not a.dir:
            ap.error("--dir is required for plan and diff")
        target = a.dir
        if a.mode == "diff":
            tmp = tempfile.mkdtemp()
            shutil.copytree(a.dir, tmp, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
            target = tmp
        try:
            did = plan(a.org, a.app, a.app_id, target, repos, found_of, policy_of=policy_of, way_of=way_of)
        finally:
            if a.mode == "diff":
                shutil.rmtree(target, ignore_errors=True)
        print("\n".join(did))
        if a.mode == "diff":
            print("\nWhat installing again would change: " + ("nothing." if not material(did) else ", ".join(material(did))))
        return 0
    rc, out = apply(a.org, a.app, a.app_id, repos, found_of, policy_of=policy_of, way_of=way_of)
    print(out)
    return rc


def apply(owner, app, app_id, repos, found_of, run=run_gh, clone_url=None, policy_of=None, way_of=None):
    """The one pull request in OWNER/.github: (exit code, what it says).
    `run` calls gh and `clone_url` is where to clone from (the self-test's
    stand-ins). The install branch is built on only while its pull request
    is open (a correction made there is kept, since plan never replaces
    what is there); one left by a merged or closed pull request is started
    again from the default branch."""
    full = f"{owner}/.github"
    said = []
    rc, _, _ = run("repo", "view", full, "--json", "name")
    if rc != 0:
        # With a first commit, so the pull request has a branch to go into.
        rc, _, err = run("repo", "create", full, "--public", "--add-readme", "--description", "The organisation's configuration of the engine")
        if rc != 0:
            return 1, f"Could not create {full}: {err.strip()[:200]}"
    # Unread is not "none open": that would force-push over an open one.
    rc, out, err = run("pr", "list", "--repo", full, "--head", BRANCH, "--state", "open", "--json", "url", "--jq", ".[0].url // empty")
    if rc != 0:
        return 1, f"Could not read {full}'s open pull requests: {err.strip()[:200]}"
    open_pr = out.strip()
    work = tempfile.mkdtemp()
    try:
        g = lambda *x: subprocess.run(["git", "-C", work, *x], check=True, capture_output=True, text=True)  # noqa: E731
        subprocess.run(["git", "clone", "-q", clone_url or f"https://github.com/{full}", work], check=True, capture_output=True)
        if open_pr:
            g("fetch", "-q", "origin", BRANCH)
            g("checkout", "-q", "-B", BRANCH, "FETCH_HEAD")
        else:
            g("checkout", "-q", "-B", BRANCH)
        did = plan(owner, app, app_id, work, repos, found_of, policy_of=policy_of, way_of=way_of)
        said.append("\n".join(did))
        if not material(did):
            said.append(f"Nothing to change: {open_pr} already holds it." if open_pr else "Nothing to change: the configuration is installed.")
            return 0, "\n".join(said)
        g("add", "-A")
        g("commit", "-q", "-m", "chore: install the engine's configuration")
        # Over a stale branch only when no pull request is open on it.
        g("push", "-q", "-u", "origin", BRANCH, *([] if open_pr else ["--force"]))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if open_pr:
        said.append(f"Updated {open_pr}")
        rc = 0
    else:
        body = ("## What changes\n\n" + "\n".join(f"- {d}" for d in material(did)) +
                f"\n\n## Why\n\nThe configuration of the engine in {org.CENTRAL} for {owner}: the engine is called by tag and reads this repository's "
                "configuration over its own defaults. Correct the kinds detection proposed in repos.yml, and the ways to reproduce a bug in its `repro:`, before merging.\n\n" + steps(owner, app))
        rc, out, err = run("pr", "create", "--repo", full, "--head", BRANCH, "--title", "chore: install the engine's configuration", "--body", body)
        said.append(out.strip() or err.strip())
    said.append("\n" + steps(owner, app))
    return (0 if rc == 0 else 1), "\n".join(said)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
