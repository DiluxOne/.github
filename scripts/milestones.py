#!/usr/bin/env python3
"""A done version milestone opens its release issue (#192, #247).

A repository whose kind releases versions (its pack has `release:`,
kinds/<kind>/pack.yml) plans a version as a milestone titled X.Y.Z. When
every issue on that milestone is closed, or a person closes it, this opens
the issue "Release X.Y.Z" on the milestone, as dilux-bot, with the Release
form's label and Type, and closes a milestone that was done but still open.
With `planned-release: auto` (policy/autonomy.yml) approving the plan was
approving the release: when the milestone's creator has the admin or
maintain role, dilux-bot marks the issue `accepted-by:policy`, which opens
the release pull request, and scripts/release-issue.py verify approves it as
that person's. With `confirm` (the default) a person accepts the issue, the
last click. Nothing opens for a milestone not named as a version, one
closed long ago, one with no issue, one whose release issue exists (in any
state) or whose version is already tagged.

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


def done(m):
    """A milestone still open whose issues are all closed, at least one."""
    return m.get("state") == "open" and (m.get("open_issues") or 0) == 0 and (m.get("closed_issues") or 0) > 0


def due(milestones, titles, tags, now):
    """The versions to open a release issue for: version milestones done
    (every issue closed) or closed within RECENT_DAYS, with no "Release
    X.Y.Z" issue and no tag."""
    out = []
    for m in milestones:
        v = VERSION.match((m.get("title") or "").strip())
        if not v:
            continue
        if not done(m):
            if m.get("state") != "closed" or not m.get("closed_at"):
                continue
            closed = datetime.datetime.fromisoformat(m["closed_at"].replace("Z", "+00:00"))
            if (now - closed).days > RECENT_DAYS:
                continue
        version = v.group(1)
        if f"Release {version}" in titles or version in tags or f"v{version}" in tags:
            continue
        out.append((version, m))
    return out


def body(version, milestone, auto=False):
    how = (f"It was planned by {(milestone.get('creator') or {}).get('login') or 'a maintainer'}: approving the milestone was approving {version}, so it is accepted by policy and its release pull request opens."
           if auto else f"Accepting it is the decision to publish {version}; until then nothing is published.")
    what = "Every issue of the milestone {v} is closed" if done(milestone) else "The milestone {v} was closed"
    return ("### Notes\n\n"
            f"{what.format(v=version)} ({milestone.get('html_url', '')}): this opens its release. "
            f"{how}\n\n{AI}\n")


def planned_mode(root):
    mode = str((load(os.path.join(root, "policy", "autonomy.yml")) or {}).get("planned-release") or "confirm")
    return mode if mode in ("auto", "confirm") else "confirm"


PLANNERS = ("admin", "maintain")
BOTS = ("dilux-bot[bot]",)


def plan_kept(issues, removed, role_of):
    """(ok, why): whether the plan is still the planner's when the milestone
    is done (#247). Every issue on it closed as completed, each closed by the
    bot (a merged pull request it merged) or by someone with the admin or
    maintain role; and no issue taken off it by anyone else. Otherwise a
    person accepts the release. role_of(login) is the role now, or None."""
    def trusted(login):
        return login in BOTS or role_of(login) in PLANNERS
    for i in issues:
        if i.get("state_reason") != "completed":
            return False, f"#{i.get('number')} was closed as {i.get('state_reason') or 'not completed'}"
        if not trusted(i.get("closed_by") or ""):
            return False, f"#{i.get('number')} was closed by {i.get('closed_by') or 'someone unknown'}, not a maintainer"
    for who in removed:
        if not trusted(who):
            return False, f"{who}, not a maintainer, took an issue off the milestone"
    return True, "every issue closed as completed by a maintainer or the bot, none taken off by anyone else"


def gh(*args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"gh {args[0]} {args[1] if len(args) > 1 else ''}: {out.stderr.strip()[:200]}")
    return out.stdout


def lines(*args):
    return [json.loads(l) for l in gh(*args).splitlines() if l.strip()]


def open_due(full, now, io=None, mode="confirm"):
    """Open what is due in one repository; returns the versions opened."""
    io = io or {
        # Every milestone, open and closed, newest first, every page.
        "milestones": lambda: lines("api", f"repos/{full}/milestones?state=all&sort=updated&direction=desc&per_page=100", "--paginate", "--jq", ".[] | @json"),
        # Every issue titled like a release, every page: a partial list could open a second one.
        "titles": lambda: {i["title"] for i in lines("api", f"repos/{full}/issues?state=all&per_page=100", "--paginate", "--jq",
                                                       '.[] | select(.title | startswith("Release ")) | {title} | @json')},
        "tags": lambda: set(gh("api", f"repos/{full}/tags?per_page=100", "--paginate", "--jq", ".[].name").split()),
        "open": lambda version, m, auto: gh("issue", "create", "--repo", full, "--title", f"Release {version}", "--label", "lane:release",
                                            "--milestone", m["title"], "--body", body(version, m, auto)).strip(),
        "type": lambda url: gh("api", "-X", "PATCH", f"repos/{full}/issues/{url.rsplit('/', 1)[-1]}", "-f", "type=Task"),
        "role": lambda login: gh("api", f"repos/{full}/collaborators/{login}/permission", "--jq", ".role_name").strip(),
        # The milestone's issues, with who closed each (the issue's own
        # `closed_by`), and who took any issue off it.
        "issues": lambda m: lines("api", f"repos/{full}/issues?milestone={m['number']}&state=all&per_page=100", "--paginate", "--jq",
                                  '.[] | select(.pull_request | not) | {number, state_reason, closed_by: (.closed_by.login // "")} | @json'),
        "removed": lambda m: [e["actor"] for e in lines("api", f"repos/{full}/issues/events?per_page=100", "--paginate", "--jq",
                                                       f'.[] | select(.event == "demilestoned" and .milestone.title == {json.dumps(m["title"])}) | {{actor: (.actor.login // "")}} | @json')],
        "accept": lambda url: gh("issue", "edit", url, "--add-label", "accepted-by:policy"),
        "close": lambda m: gh("api", "-X", "PATCH", f"repos/{full}/milestones/{m['number']}", "-f", "state=closed"),
    }
    roles = {}

    def role_of(login):
        # Read once each; one that cannot be read is no role (never fatal).
        if login not in roles:
            try:
                roles[login] = io["role"](login) if login else None
            except RuntimeError:
                roles[login] = None
        return roles[login]

    opened = []
    for version, m in due(io["milestones"](), io["titles"](), io["tags"](), now):
        creator = (m.get("creator") or {}).get("login") or ""
        # Only a milestone done by its plan: one a person closed early, or
        # one changed by someone else, waits for a person's acceptance.
        auto = mode == "auto" and done(m) and role_of(creator) in PLANNERS
        if auto:
            try:
                auto, why = plan_kept(io["issues"](m), io["removed"](m), role_of)
            except RuntimeError as exc:
                auto, why = False, f"the milestone's issues could not be read ({exc})"
            if not auto:
                print(f"  {full}: {version} waits for a person: {why}")
        url = io["open"](version, m, auto)
        # The Release form's Type: a failure fails the run, so it is seen
        # (the issue stands; its Type is set by hand).
        io["type"](url)
        if auto:
            # Last, once the issue is whole: this label opens the release pull
            # request (issue-accepted.yml).
            io["accept"](url)
        if done(m):
            io["close"](m)
        print(f"  {full}: Release {version}, {url}{' (accepted by the plan of ' + creator + ')' if auto else ''}")
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
          "open": lambda v, mm, auto: opened.append(v) or f"https://github.com/o/r/issues/{len(opened)}", "type": typed.append,
          "role": lambda who: "admin", "accept": lambda url: None, "close": lambda mm: None,
          "issues": lambda mm: [], "removed": lambda mm: []}
    import contextlib
    import io as _io
    with contextlib.redirect_stdout(_io.StringIO()):
        got = open_due("o/r", now, io)
    check("open: one issue per version due, each given the Release form's Type", (got, typed), (["1.4.0", "2.0.0"], ["https://github.com/o/r/issues/1", "https://github.com/o/r/issues/2"]))
    check("due: a version milestone closed 30 days ago still counts; 31 no", ([v for v, _ in due([m("3.0.0", days=30)], set(), set(), now)], due([m("3.0.0", days=31)], set(), set(), now)), (["3.0.0"], []))
    # #247: a milestone done is due while still open; auto accepts a planner's.
    d = {"title": "1.6.0", "state": "open", "open_issues": 0, "closed_issues": 3, "number": 7, "html_url": "u", "creator": {"login": "boss"}}
    check("due: an open version milestone with every issue closed is due", [v for v, _ in due([d, {**d, "title": "1.7.0", "open_issues": 1}, {**d, "title": "1.8.0", "closed_issues": 0}], set(), set(), now)], ["1.6.0"])
    seen = {"accept": [], "close": [], "auto": []}
    def run(mode, role, issues=None, removed=(), ms=None):
        for k in seen:
            seen[k] = []
        def role_fn(who):
            if role == "boom":
                raise RuntimeError("HTTP 502")
            return role if who == "boss" else {"bot": None}.get(who, "write")
        io2 = {"milestones": lambda: [ms or d], "titles": lambda: set(), "tags": lambda: set(),
               "open": lambda v, mm, auto: seen["auto"].append(auto) or "https://github.com/o/r/issues/5", "type": lambda url: None,
               "role": role_fn, "accept": seen["accept"].append, "close": lambda mm: seen["close"].append(mm["number"]),
               "issues": lambda mm: issues if issues is not None else [{"number": 1, "state_reason": "completed", "closed_by": "dilux-bot[bot]"}],
               "removed": lambda mm: list(removed)}
        with contextlib.redirect_stdout(_io.StringIO()):
            open_due("o/r", now, io2, mode)
        return (seen["auto"], len(seen["accept"]), seen["close"])
    check("#247 auto: a maintainer's plan is accepted by policy, and the done milestone closes", run("auto", "maintain"), ([True], 1, [7]))
    check("#247 auto: a writer's plan waits for a person", run("auto", "write"), ([False], 0, [7]))
    check("#247 confirm: a person accepts, the last click", run("confirm", "admin"), ([False], 0, [7]))
    check("#247 auto: an issue closed as not planned, or closed by a writer, waits for a person",
          [run("auto", "admin", issues=[{"number": 1, "state_reason": "not_planned", "closed_by": "boss"}])[0],
           run("auto", "admin", issues=[{"number": 1, "state_reason": "completed", "closed_by": "someone"}])[0]], [[False], [False]])
    check("#247 auto: an issue a writer took off the milestone waits for a person", run("auto", "admin", removed=["someone"])[0], [False])
    check("#247 auto: closed by a maintainer and taken off by one is still the plan", run("auto", "admin", issues=[{"number": 1, "state_reason": "completed", "closed_by": "boss"}], removed=["boss"])[0], [True])
    check("#247 auto: a milestone a person closed early is never the plan", run("auto", "admin", ms={**d, "state": "closed", "closed_at": "2026-10-15T00:00:00Z", "open_issues": 2})[0], [False])
    check("#247 auto: a role that cannot be read waits for a person, and stops nothing", run("auto", "boom"), ([False], 0, [7]))
    check("#247 body: says which", ("accepted by policy" in body("1.6.0", d, True), "Accepting it is the decision" in body("1.6.0", d, False)), (True, True))
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv == ["open"]:
        root = os.path.join(HERE, "..")
        now = datetime.datetime.now(datetime.timezone.utc)
        bad = 0
        mode = planned_mode(root)
        for name in releasing(load(os.path.join(root, "repos.yml")), root):
            try:
                open_due(f"{org.ORG}/{name}", now, mode=mode)
            except RuntimeError as exc:
                bad += 1
                print(f"  {name}: failed ({exc})")
        return 1 if bad else 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
