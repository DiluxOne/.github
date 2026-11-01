#!/usr/bin/env python3
"""The organisation's identity, from org.yml (#191).

  ORG          its login on GitHub
  CENTRAL      owner/name of the repository holding its configuration
  APP          its App's slug; BOT the App's login as GitHub shows a commit
               or a comment ("<slug>[bot]"); BOT_ID its user id

  MAINTAINERS  the logins of its maintainers (#568); CATALOGS the catalog
               each kind publishes to

  org.py maintainers   its maintainers, one per line
  org.py bot app|login|id
                       its App's slug, login or id: DX_BOT_APP, DX_BOT_LOGIN
                       or DX_BOT_ID when set, else org.yml's; nothing (and
                       exit 1) when it names none
  org.py publishes-to KIND
                       where the kind KIND publishes a release: its pack's
                       `release.publishes-to`, with `{catalog}` the kind's
                       catalog in org.yml `catalogs`; nothing when none
  org.py attribution   `warn` or `required`: what the conventions check
                       does with a model named as a co-author (#491)
  org.py who-decides   `codeowners` (the default), `acceptor` or
                       `writers`: who steers the autopilot (#588; a
                       repository's exception is repos.yml's, read by
                       scripts/deciders.py)
  org.py --test        self-test
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path=os.path.join(HERE, "..", "org.yml")):
    """org.yml as data, with yq where it is or PyYAML."""
    import json
    import shutil
    import subprocess
    if shutil.which("yq"):
        return json.loads(subprocess.run(["yq", "-o=json", ".", path], check=True, capture_output=True, text=True).stdout or "{}")
    import yaml
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def app(conf, env):
    """(slug, login, id) of the organisation's App: the calling
    organisation's DX_BOT_APP, DX_BOT_LOGIN and DX_BOT_ID, which every
    shared workflow sets in its env (#197), else org.yml's; none at all
    names no App ("", "", 0), which nothing recognises."""
    bot = conf.get("bot") or {}
    slug = env.get("DX_BOT_APP") or str(bot.get("app") or "")
    return slug, env.get("DX_BOT_LOGIN") or (f"{slug}[bot]" if slug else ""), int(env.get("DX_BOT_ID") or bot.get("id") or 0)


_conf = load()
ORG = _conf["org"]
CENTRAL = _conf["central"]
APP, BOT, BOT_ID = app(_conf, os.environ)
# The private repository security work happens in (#287); "" when none.
SECURITY = str(_conf.get("security") or "")
# Who the organisation's maintainers are and where each kind publishes
# (#568): DiluxOne's own values live here, never in the engine's code.
MAINTAINERS = [str(m) for m in (_conf.get("maintainers") or [])]
CATALOGS = {str(k): str(v) for k, v in (_conf.get("catalogs") or {}).items()}


def publishes_to(value, kind, catalogs=None):
    """A pack's `release.publishes-to` with `{catalog}` resolved (#568): the
    organisation's catalog for the kind (org.yml `catalogs`); "" when it
    names one and the organisation has none."""
    value = str(value or "")
    if "{catalog}" not in value:
        return value
    catalog = (CATALOGS if catalogs is None else catalogs).get(kind, "")
    return value.replace("{catalog}", catalog) if catalog else ""


def pack_publishes_to(kind, root=os.path.join(HERE, "..")):
    if not kind or not all(c.isalnum() or c == "-" for c in kind):
        return ""
    path = os.path.join(root, "kinds", kind, "pack.yml")
    pack = load(path) if os.path.exists(path) else {}
    return publishes_to(((pack or {}).get("release") or {}).get("publishes-to"), kind)


def attribution(conf):
    """org.yml `attribution` (#491): `required` refuses a model named as a
    co-author, `warn` (the default) only warns."""
    mode = conf.get("attribution") or "warn"
    if mode not in ("warn", "required"):
        raise ValueError(f"org.yml `attribution` is `{mode}`: warn or required")
    return mode


def who_decides(conf):
    """org.yml `who-decides` (#588): `codeowners` (the default), `acceptor`
    or `writers`; anything else is an error, never a guess."""
    value = conf.get("who-decides") or "codeowners"
    if value not in ("codeowners", "acceptor", "writers"):
        raise ValueError(f"org.yml `who-decides` is `{value}`: codeowners, acceptor or writers")
    return value


def hardwired_bot(root=os.path.join(HERE, "..", ".github", "workflows")):
    """Where a shared workflow writes this organisation's App in (#197):
    another organisation calls them with its own App, named by its variables
    DX_BOT_LOGIN, DX_BOT_APP and DX_BOT_ID, which every organisation sets
    (#568: not even as their fallback; only in a comment or a message)."""
    import glob
    import re
    found = []
    if not APP:
        return found
    for path in sorted(glob.glob(os.path.join(root, "*.yml"))):
        text = open(path, encoding="utf-8").read()
        if not re.search(r"^  workflow_call:", text, re.M):
            continue
        for n, line in enumerate(text.split("\n"), 1):
            code = line.strip()
            if code.startswith("#") or re.match(r"(- )?name: ", code):
                continue
            # The slug as a value (quoted, a path, a pattern, a YAML value),
            # not as a word in a message ("opened by dilux-bot").
            if BOT in code or str(BOT_ID) in code or re.search(r"(^|[\"'/?|(@=]|: )" + re.escape(APP) + r"(?![\w-])", code):
                found.append(f"{os.path.basename(path)}:{n}")
    return found


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    check("the central repository is the organisation's", CENTRAL.split("/", 1)[0], ORG)
    check("the bot's login is the App's", BOT, f"{APP}[bot]")
    check("a numeric bot id", BOT_ID > 0, True)
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
        fh.write("org: X\ncentral: X/.github\nbot: {app: x-bot, id: 7}\n")
    try:
        check("load: reads an org.yml", load(fh.name)["bot"], {"app": "x-bot", "id": 7})
    finally:
        os.unlink(fh.name)
    conf = {"bot": {"app": "dilux-bot", "id": 1}}
    check("#197: the App from org.yml when no variable is set", app(conf, {}), ("dilux-bot", "dilux-bot[bot]", 1))
    check("#568: an org.yml without an App names none", app({}, {}), ("", "", 0))
    check("#197: the calling organisation's variables win", app(conf, {"DX_BOT_APP": "acme-bot", "DX_BOT_LOGIN": "acme-bot[bot]", "DX_BOT_ID": "7"}), ("acme-bot", "acme-bot[bot]", 7))
    check("#491: attribution defaults to warn", attribution({}), "warn")
    check("#491: attribution required", attribution({"attribution": "required"}), "required")
    try:
        attribution({"attribution": "off"})
        check("#491: an unknown attribution fails", "no error", "ValueError")
    except ValueError:
        check("#491: an unknown attribution fails", "ValueError", "ValueError")
    check("#491: org.yml starts at warn", attribution(_conf), "warn")
    check("C2 (#588): who-decides defaults to codeowners, and takes the three values",
          (who_decides({}), [who_decides({"who-decides": v}) for v in ("codeowners", "acceptor", "writers")]), ("codeowners", ["codeowners", "acceptor", "writers"]))
    try:
        who_decides({"who-decides": "everyone"})
        check("C2 (#588): an unknown who-decides fails", "no error", "ValueError")
    except ValueError:
        check("C2 (#588): an unknown who-decides fails", "ValueError", "ValueError")
    check("C2 (#588): org.yml keeps the default", who_decides(_conf), "codeowners")
    check("#568: {catalog} is the kind's catalog", publishes_to("{catalog}", "k", {"k": "acme-plugins"}), "acme-plugins")
    check("#568: no catalog for the kind publishes nowhere", publishes_to("{catalog}", "k", {}), "")
    check("#568: a place with no placeholder stays", publishes_to("wordpress.org", "k", {}), "wordpress.org")
    check("#568: the ai-agent-plugin kind publishes to org.yml's catalog", pack_publishes_to("ai-agent-plugin"), CATALOGS.get("ai-agent-plugin", ""))
    check("#568: a kind that is not one publishes nowhere", pack_publishes_to("../x"), "")
    import subprocess

    def bot(field, **env):
        out = subprocess.run([sys.executable, os.path.abspath(__file__), "bot", field], capture_output=True, text=True,
                             env={**{k: v for k, v in os.environ.items() if not k.startswith("DX_BOT_")}, **env})
        return out.stdout.strip(), out.returncode
    mine = app(_conf, {})
    check("#568: `bot` is org.yml's App when no variable is set", (bot("app"), bot("login"), bot("id")),
          ((mine[0], 0), (mine[1], 0), (str(mine[2]), 0)))
    check("#568: `bot` reads the calling organisation's variables first", (bot("login", DX_BOT_LOGIN="acme-bot[bot]"), bot("id", DX_BOT_ID="7"), bot("app", DX_BOT_APP="acme-bot")),
          (("acme-bot[bot]", 0), ("7", 0), ("acme-bot", 0)))
    check("#197, #568: the shared workflows never name the App, not even as a fallback", hardwired_bot(), [])
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["publishes-to"] and len(sys.argv) == 3:
        print(pack_publishes_to(sys.argv[2]))
        sys.exit(0)
    if sys.argv[1:2] == ["bot"] and len(sys.argv) == 3 and sys.argv[2] in ("app", "login", "id"):
        value = dict(zip(("app", "login", "id"), (APP, BOT, BOT_ID or "")))[sys.argv[2]]
        if value:
            print(value)
        sys.exit(0 if value else 1)
    if sys.argv[1:] == ["maintainers"]:
        print("\n".join(MAINTAINERS))
        sys.exit(0)
    if sys.argv[1:] == ["who-decides"]:
        print(who_decides(_conf))
        sys.exit(0)
    if sys.argv[1:] == ["attribution"]:
        print(attribution(_conf))
        sys.exit(0)
    sys.exit(self_test() if sys.argv[1:] == ["--test"] else 64)
