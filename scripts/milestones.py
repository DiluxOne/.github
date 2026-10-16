#!/usr/bin/env python3
"""A closed version milestone opens its release issue (#192).

A repository whose kind releases versions (its pack has `release:`,
kinds/<kind>/pack.yml) plans a version as a milestone titled X.Y.Z. When a
person closes that milestone, this opens the issue "Release X.Y.Z" in the
repository, as dilux-bot, with the Release form's label and Type: accepting
it is still a person's decision, and publishing waits for it
(scripts/release-issue.py). Nothing opens for a milestone not named as a
version, one closed long ago, one whose release issue exists (in any state)
or whose version is already tagged.

  milestones.py open    every repository of repos.yml with such a kind
                        (org-drift.yml, every day)
  milestones.py --test  self-test

Environment: GH_TOKEN (issues: write, contents: read on every repository).
"""
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import org  # noqa: E402  the organisation, from org.yml (#191)

VERSION = re.compile(r"^v?(\d+\.\d+\.\d+)$")
RECENT_DAYS = 30
AI = "🤖 AI-generated · scripts/milestones.py"


def load(path):
    import yaml
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def releasing(conf, root):
    """The repositories whose kinds release versions (their pack's `release`)."""
    out = []
    for name, entry in (conf.get("repos") or {}).items():
        for k in (entry or {}).get("kinds") or []:
            pack = os.path.join(root, "kinds", k.get("kind") or "", "pack.yml")
            if os.path.isfile(pack) and load(pack).get("release"):
                out.append(name)
                break
    return sorted(out)


def due(milestones, titles, tags, now):
    """The versions to open a release issue for: closed version milestones,
    closed within RECENT_DAYS, with no "Release X.Y.Z" issue and no tag."""
    out = []
    for m in milestones:
        v = VERSION.match((m.get("title") or "").strip())
        if not v or m.get("state") != "closed" or not m.get("closed_at"):
            continue
        closed = datetime.datetime.fromisoformat(m["closed_at"].replace("Z", "+00:00"))
        if (now - closed).days > RECENT_DAYS:
            continue
        version = v.group(1)
        if f"Release {version}" in titles or version in tags or f"v{version}" in tags:
            continue
        out.append((version, m))
    return out


def body(version, milestone):
    return ("### Notes\n\n"
            f"The milestone {version} closed ({milestone.get('html_url', '')}): this opens its release. "
            f"Accepting it is the decision to publish {version}; until then nothing is published.\n\n{AI}\n")


def gh(*args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"gh {args[0]} {args[1] if len(args) > 1 else ''}: {out.stderr.strip()[:200]}")
    return out.stdout


def lines(*args):
    return [json.loads(l) for l in gh(*args).splitlines() if l.strip()]


def open_due(full, now, io=None):
    """Open what is due in one repository; returns the versions opened."""
    io = io or {
        # Every closed milestone, newest first, every page.
        "milestones": lambda: lines("api", f"repos/{full}/milestones?state=closed&sort=updated&direction=desc&per_page=100", "--paginate", "--jq", ".[] | @json"),
        # Every issue titled like a release, every page: a partial list could open a second one.
        "titles": lambda: {i["title"] for i in lines("api", f"repos/{full}/issues?state=all&per_page=100", "--paginate", "--jq",
                                                       '.[] | select(.title | startswith("Release ")) | {title} | @json')},
        "tags": lambda: set(gh("api", f"repos/{full}/tags?per_page=100", "--paginate", "--jq", ".[].name").split()),
        "open": lambda version, m: gh("issue", "create", "--repo", full, "--title", f"Release {version}", "--label", "lane:release", "--body", body(version, m)).strip(),
        "type": lambda url: gh("api", "-X", "PATCH", f"repos/{full}/issues/{url.rsplit('/', 1)[-1]}", "-f", "type=Task"),
    }
    opened = []
    for version, m in due(io["milestones"](), io["titles"](), io["tags"](), now):
        url = io["open"](version, m)
        # The Release form's Type: a failure fails the run, so it is seen
        # (the issue stands; its Type is set by hand).
        io["type"](url)
        print(f"  {full}: Release {version}, {url}")
        opened.append(version)
    return opened


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    now = datetime.datetime(2026, 10, 16, tzinfo=datetime.timezone.utc)
    m = lambda title, state="closed", days=1: {"title": title, "state": state, "closed_at": (now - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"), "html_url": f"u/{title}"}
    ms = [m("1.4.0"), m("v2.0.0"), m("Backlog"), m("1.5.0", state="open"), m("0.9.0", days=90), m("1.3.0"), m("1.2.0")]
    got = [v for v, _ in due(ms, {"Release 1.3.0"}, {"1.2.0"}, now)]
    check("due: closed version milestones without their release issue or tag", got, ["1.4.0", "2.0.0"])
    root = os.path.join(HERE, "..")
    conf = load(os.path.join(root, "repos.yml"))
    check("releasing: the plugins, not the unclassified ones", ("diluxone-offload-wordpress" in releasing(conf, root), "diluxone-website" in releasing(conf, root)), (True, False))
    text = body("1.4.0", m("1.4.0"))
    check("body: the Release form's section", text.startswith("### Notes\n\n"), True)
    opened = []
    typed = []
    io = {"milestones": lambda: ms, "titles": lambda: {"Release 1.3.0"}, "tags": lambda: {"1.2.0"},
          "open": lambda v, mm: opened.append(v) or f"https://github.com/o/r/issues/{len(opened)}", "type": typed.append}
    import contextlib
    import io as _io
    with contextlib.redirect_stdout(_io.StringIO()):
        got = open_due("o/r", now, io)
    check("open: one issue per version due, each given the Release form's Type", (got, typed), (["1.4.0", "2.0.0"], ["https://github.com/o/r/issues/1", "https://github.com/o/r/issues/2"]))
    check("due: a version milestone closed 30 days ago still counts; 31 no", ([v for v, _ in due([m("3.0.0", days=30)], set(), set(), now)], due([m("3.0.0", days=31)], set(), set(), now)), (["3.0.0"], []))
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv == ["open"]:
        root = os.path.join(HERE, "..")
        now = datetime.datetime.now(datetime.timezone.utc)
        bad = 0
        for name in releasing(load(os.path.join(root, "repos.yml")), root):
            try:
                open_due(f"{org.ORG}/{name}", now)
            except RuntimeError as exc:
                bad += 1
                print(f"  {name}: failed ({exc})")
        return 1 if bad else 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
