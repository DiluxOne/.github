#!/usr/bin/env python3
"""The organisation's identity, from org.yml (#191).

  ORG          its login on GitHub
  CENTRAL      owner/name of the repository holding its configuration
  APP          its App's slug; BOT the App's login as GitHub shows a commit
               or a comment ("<slug>[bot]"); BOT_ID its user id

  org.py attribution   `warn` or `required`: what the conventions check
                       does with a model named as a co-author (#491)
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


def attribution(conf):
    """org.yml `attribution` (#491): `required` refuses a model named as a
    co-author, `warn` (the default) only warns."""
    mode = conf.get("attribution") or "warn"
    if mode not in ("warn", "required"):
        raise ValueError(f"org.yml `attribution` is `{mode}`: warn or required")
    return mode


def hardwired_bot(root=os.path.join(HERE, "..", ".github", "workflows")):
    """Where a shared workflow writes this organisation's App in (#197):
    another organisation calls them with its own App, named by its variables
    DX_BOT_LOGIN, DX_BOT_APP and DX_BOT_ID, so the App's login, slug or id
    may stand only as their fallback (or in a comment or a message)."""
    import glob
    import re
    fallbacks = (f"vars.DX_BOT_LOGIN || '{BOT}'", f"vars.DX_BOT_APP || '{APP}'", f"vars.DX_BOT_ID || '{BOT_ID}'",
                 f"inputs.review-bot != '{BOT}'", f"default: '{BOT}'")
    found = []
    for path in sorted(glob.glob(os.path.join(root, "*.yml"))):
        text = open(path, encoding="utf-8").read()
        if not re.search(r"^  workflow_call:", text, re.M):
            continue
        for n, line in enumerate(text.split("\n"), 1):
            code = line.strip()
            if code.startswith("#") or re.match(r"(- )?name: ", code):
                continue
            for f in fallbacks:
                code = code.replace(f, "")
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
    check("#197: the shared workflows name the App only as the caller's variables' fallback", hardwired_bot(), [])
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["attribution"]:
        print(attribution(_conf))
        sys.exit(0)
    sys.exit(self_test() if sys.argv[1:] == ["--test"] else 64)
