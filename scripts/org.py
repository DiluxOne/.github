#!/usr/bin/env python3
"""The organisation's identity, from org.yml (#191).

  ORG          its login on GitHub
  CENTRAL      owner/name of the repository holding its configuration
  APP          its App's slug; BOT the App's login as GitHub shows a commit
               or a comment ("<slug>[bot]"); BOT_ID its user id

  org.py --test   self-test
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


_conf = load()
ORG = _conf["org"]
CENTRAL = _conf["central"]
APP = _conf["bot"]["app"]
BOT = f"{APP}[bot]"
BOT_ID = int(_conf["bot"]["id"])
# The private repository security work happens in (#287); "" when none.
SECURITY = str(_conf.get("security") or "")


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
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(self_test() if sys.argv[1:] == ["--test"] else 64)
