#!/usr/bin/env python3
"""The installer (#197, phase 12): an organisation's configuration of the
engine, in its own `.github` repository.

The engine (the workflows, scripts, gates and kinds) stays here and is called
by tag; the configuration is the organisation's (docs/plans/autonomy.md,
phase 12), and scripts/config-overlay.sh lays it over the engine's defaults
in every run. This writes that configuration:

  org.yml             who the organisation is and its App
  repos.yml           every repository and its kinds, from detection
                      (scripts/detect.py, each pack's `detect`)
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


def plan(owner, app, app_id, target, repos, found_of, engine=ENGINE):
    """Writes the configuration into `target` and returns what it did, one
    line each: "kept PATH", "wrote PATH" or "added NAME to repos.yml"."""
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
    with open(os.path.join(engine, ".github", "workflows", "org-pull-request.yml"), encoding="utf-8") as fh:
        pipeline = fh.read()
    write(os.path.join(".github", "workflows", "org-pull-request.yml"), render(pipeline, owner))
    templates = os.path.join(engine, "workflow-templates")
    for name in sorted(os.listdir(templates)):
        with open(os.path.join(templates, name), encoding="utf-8") as fh:
            text = fh.read()
        write(os.path.join("workflow-templates", name), render(text, owner) if name.endswith(".yml") else text)
    return did


def material(did):
    """What installing again changed: anything but a kept file."""
    return [d for d in did if not d.startswith("kept ")]


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
    if a.mode in ("plan", "diff"):
        if not a.dir:
            ap.error("--dir is required for plan and diff")
        target = a.dir
        if a.mode == "diff":
            tmp = tempfile.mkdtemp()
            shutil.copytree(a.dir, tmp, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
            target = tmp
        did = plan(a.org, a.app, a.app_id, target, repos, found_of)
        print("\n".join(did))
        if a.mode == "diff":
            print("\nWhat installing again would change: " + ("nothing." if not material(did) else ", ".join(material(did))))
            shutil.rmtree(target)
        return 0
    # apply: one pull request in ORG/.github.
    full = f"{a.org}/.github"
    rc, _, _ = run_gh("repo", "view", full, "--json", "name")
    if rc != 0:
        # With a first commit, so the pull request has a branch to go into.
        rc, _, err = run_gh("repo", "create", full, "--public", "--add-readme", "--description", "The organisation's configuration of the engine")
        if rc != 0:
            print(f"Could not create {full}: {err.strip()[:200]}", file=sys.stderr)
            return 1
    work = tempfile.mkdtemp()
    subprocess.run(["gh", "repo", "clone", full, work, "--", "-q"], check=True)
    g = lambda *x: subprocess.run(["git", "-C", work, *x], check=True, capture_output=True, text=True)  # noqa: E731
    # Run again while its pull request is open: on top of that branch, so a
    # correction made there is kept (plan never replaces what is there).
    pushed = subprocess.run(["git", "-C", work, "ls-remote", "--exit-code", "--heads", "origin", BRANCH], capture_output=True).returncode == 0
    if pushed:
        g("fetch", "-q", "origin", BRANCH)
        g("checkout", "-q", "-B", BRANCH, "FETCH_HEAD")
    else:
        g("checkout", "-q", "-B", BRANCH)
    did = plan(a.org, a.app, a.app_id, work, repos, found_of)
    print("\n".join(did))
    if material(did):
        g("add", "-A")
        g("commit", "-q", "-m", "chore: install the engine's configuration")
        g("push", "-q", "-u", "origin", BRANCH)
    elif not pushed:
        print("Nothing to change: the configuration is installed.")
        return 0
    # A branch pushed by an earlier run whose pull request was never opened
    # (or a run that changes nothing more) still gets its pull request.
    body = ("## What changes\n\n" + "\n".join(f"- {d}" for d in material(did)) +
            f"\n\n## Why\n\nThe configuration of the engine in {org.CENTRAL} for {a.org}: the engine is called by tag and reads this repository's "
            "configuration over its own defaults. Correct the kinds detection proposed in repos.yml before merging.\n\n" + steps(a.org, a.app))
    # Run again while its pull request is open: the push updated it.
    rc, out, err = run_gh("pr", "list", "--repo", full, "--head", BRANCH, "--state", "open", "--json", "url", "--jq", ".[0].url // empty")
    if rc == 0 and out.strip():
        print(f"Updated {out.strip()}")
    else:
        rc, out, err = run_gh("pr", "create", "--repo", full, "--head", BRANCH, "--title", "chore: install the engine's configuration", "--body", body)
        print(out.strip() or err.strip())
    print("\n" + steps(a.org, a.app))
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
