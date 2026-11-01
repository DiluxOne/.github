#!/usr/bin/env python3
"""Where a shared job runs: the organisation's VM or GitHub's runners (#167).

A private repository's jobs run on the organisation's VM when the
organisation variable DX_RUNNER_HEAVY names it (runner-vm.yml): the runs-on
value as JSON, `["self-hosted","linux","x64","diluxone"]` here, so another
organisation names its own runners without touching a workflow (#190). A job
there reaches the VM's Docker socket. A pull request that dilux-bot opened
from a reproduction never runs there: its test was written from an issue's
text, which anyone can write, so it runs on GitHub's fresh runners whatever
DX_RUNNER_HEAVY says. Those pull requests are, by their head branch and their
author (never by anything the pull request changes):

  - the reproduction's draft (issue-repro.yml): `test/repro-issue-<n>`;
  - the fix of the `bugfix-reproduced` lane (autopilot.yml, #84), which
    starts at the reproduction's commit: `<type>/<m>-the-bug-reproduced-from-<n>`
    (scripts/autopilot.py names it after its issue, "The bug reproduced
    from #<n>"; the type is `fix` when the issue's Type was set, another
    when setting it failed), with `-<run id>` when an earlier attempt left
    the branch;

both opened by dilux-bot[bot]. A comment on a pull request (issue_comment)
does not name the branch, so a comment on any of dilux-bot's pull requests
runs on GitHub's runners too. So does every job of an issues event on the
lane's own issue, the one dilux-bot opens titled "The bug reproduced from
#<n>" (scripts/repro-lane.py of #166; keep the two in step): the autopilot that writes the fix from the
reproduction's commit runs on it. A person's pull request or issue, or
anything else, keeps DX_RUNNER_HEAVY's choice.

`runs-on` cannot call a script, so the decision is one expression, the same
in every job of a shared workflow; this script writes it and checks that
every job carries it.

Usage:
  runner-route.py expression [FALLBACK]   print the runs-on value
                                          (FALLBACK: ubuntu-latest)
  runner-route.py check [FILE...]         every job of a shared workflow
                                          carries the expression, except
                                          those that always stay on GitHub's
                                          runners (no DX_RUNNER_HEAVY at all);
                                          default: .github/workflows/*.yml
  runner-route.py write [FILE...]         rewrite every DX_RUNNER_HEAVY runs-on
                                          line to the expression, keeping
                                          its fallback
  runner-route.py --test                  self-test: the expression, read
                                          as GitHub reads it, against events
"""

import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import org  # noqa: E402  the organisation, from org.yml (#191)
BOT = org.BOT
REPRO_PREFIX = "test/repro-issue-"
LANE_MARK = "-the-bug-reproduced-from-"
# No "#": in a plain YAML value, " #" starts a comment and cuts the expression.
LANE_TITLE = "The bug reproduced from "
VM_LABELS = ["self-hosted", "linux", "x64", "diluxone"]
FALLBACKS = ("ubuntu-latest", "ubuntu-24.04")

# Shared workflows that never run on the VM: they hold secrets (the release,
# the credentials check) or run code written from an issue (the reproduction).
GITHUB_ONLY = ("plugin-release-wp.yml", "plugin-publish-wp.yml", "svn-auth-check.yml", "issue-repro.yml",
               # A plugin for coding agents' release and its catalog bump (#552).
               "plugin-release-ai.yml", "plugin-publish-ai.yml",
               # It wakes the VM (#154): it cannot wait for the VM it starts.
               "runner-wake.yml",
               # An agent works on a stranger's report, and the job holds an
               # embargoed fix (#194): a fresh runner each time.
               "security-fix.yml",
               # It holds an embargoed fix and pushes it out (#247): a fresh runner.
               "security-patch.yml",
               # What it finds can be a vulnerability (#234): a fresh runner.
               "nightly-review.yml",
               # It holds dilux-bot's key on a fork's pull request
               # (pull_request_target, #488): a fresh runner.
               "issue-claim.yml")

# A job that holds a key beside an agent's work, in a workflow that is
# otherwise shared (autopilot.yml's prep, draft and apply, #287): a fresh
# runner, never one an agent's job may have run on before. Its line says so.
FRESH = re.compile(r"^ubuntu-latest\s+#\s*fresh: .*\(#287\)$")

# A job whose runner an earlier job of the same run decided (autopilot.yml's
# `where`, #84: a reproduced bug's work never runs on the VM) keeps that
# choice: `runs-on` names the earlier job's `github-hosted` output.
DECIDED = re.compile(r"^\$\{\{ \(vars\.DX_RUNNER_HEAVY != '' && needs\.[a-z0-9_-]+\.outputs\.github-hosted == 'false'\) && fromJSON\(vars\.DX_RUNNER_HEAVY\) \|\| '([^']+)' \}\}$")


def decide(heavy, event, bot=None):
    """The runner a job gets: DX_RUNNER_HEAVY's (a runs-on value as JSON), or
    None for GitHub's (the fallback). `bot`: the calling organisation's App
    login (DX_BOT_LOGIN, #197), this one's by default."""
    bot = (bot or BOT).lower()
    if not heavy:
        return None
    pr = event.get("pull_request") or {}
    author = ((pr.get("user") or {}).get("login") or "").lower()
    head = ((pr.get("head") or {}).get("ref") or "").lower()
    if author == bot and (head.startswith(REPRO_PREFIX) or ("/" in head and LANE_MARK in head)):
        return None
    issue = event.get("issue") or {}
    by_bot = ((issue.get("user") or {}).get("login") or "").lower() == bot
    if by_bot and (issue.get("pull_request") or (issue.get("title") or "").lower().startswith(LANE_TITLE.lower())):
        return None
    return json.loads(heavy)


def expression(fallback="ubuntu-latest"):
    pr = "github.event.pull_request"
    head = f"{pr}.head.ref"
    # The calling organisation's App (#197): its DX_BOT_LOGIN, else ours.
    bot = f"(vars.DX_BOT_LOGIN || '{BOT}')"
    repro = (f"({pr}.user.login == {bot} && (startsWith({head}, '{REPRO_PREFIX}')"
             f" || (contains({head}, '/') && contains({head}, '{LANE_MARK}'))))")
    issue = "github.event.issue"
    comment = f"({issue}.user.login == {bot} && ({issue}.pull_request || startsWith({issue}.title, '{LANE_TITLE}')))"
    return (f"${{{{ vars.DX_RUNNER_HEAVY != '' && !({repro} || {comment})"
            f" && fromJSON(vars.DX_RUNNER_HEAVY) || '{fallback}' }}}}")


RUNS_ON = re.compile(r"^(\s+)runs-on:\s*(.*?)\s*$")
FALLBACK_OF = re.compile(r"\|\|\s*'([^']+)'\s*}}$")


def workflow_files(args):
    return args or sorted(glob.glob(".github/workflows/*.yml"))


def is_shared(text):
    return re.search(r"^  workflow_call:", text, re.M) is not None


def problems(path, text):
    name = os.path.basename(path)
    out = []
    if not is_shared(text):
        return out
    if name in GITHUB_ONLY:
        # Only the runs-on lines: a comment or an `if:` may name DX_RUNNER_HEAVY.
        for n, line in enumerate(text.splitlines(), 1):
            m = RUNS_ON.match(line)
            if m and ("DX_RUNNER" in m.group(2) or "self-hosted" in m.group(2)):
                out.append(f"{path}:{n}: stays on GitHub's runners: no DX_RUNNER_HEAVY here")
        return out
    for n, line in enumerate(text.splitlines(), 1):
        m = RUNS_ON.match(line)
        if not m:
            continue
        value = m.group(2)
        decided = DECIDED.match(value)
        if decided and decided.group(1) in FALLBACKS:
            continue
        if FRESH.match(value):
            continue
        fb = FALLBACK_OF.search(value)
        if not fb or fb.group(1) not in FALLBACKS or value != expression(fb.group(1)):
            out.append(f"{path}:{n}: a job without the runner choice of scripts/runner-route.py (run `python3 scripts/runner-route.py write`)")
    return out


def rewrite(text):
    lines = []
    for line in text.splitlines(keepends=True):
        m = RUNS_ON.match(line.rstrip("\n"))
        if m and "DX_RUNNER" in m.group(2) and not DECIDED.match(m.group(2)):
            fb = FALLBACK_OF.search(m.group(2))
            line = f"{m.group(1)}runs-on: {expression(fb.group(1) if fb else 'ubuntu-latest')}\n"
        lines.append(line)
    return "".join(lines)


# --- GitHub's expressions, the part the runs-on value uses ----------------
# Enough to read the expression the way GitHub does: property paths (a
# missing one is null), '...' strings, == != ! && || and parentheses,
# startsWith, contains and fromJSON. Strings compare ignoring case, as on
# GitHub; && and || return one of their operands.

TOKEN = re.compile(r"\s*(?:(?P<str>'(?:[^']|'')*')|(?P<op>==|!=|&&|\|\||[!(),])|(?P<name>[A-Za-z_][A-Za-z0-9_\-]*(?:\.[A-Za-z_][A-Za-z0-9_\-]*)*))")


def tokens(src):
    pos, out = 0, []
    src = src.strip()
    while pos < len(src):
        m = TOKEN.match(src, pos)
        if not m or m.end() == pos:
            raise ValueError(f"cannot read the expression at: {src[pos:pos + 30]}")
        pos = m.end()
        if m.group("str") is not None:
            out.append(("str", m.group("str")[1:-1].replace("''", "'")))
        elif m.group("op"):
            out.append(("op", m.group("op")))
        else:
            out.append(("name", m.group("name")))
    return out


def truthy(v):
    return v not in (None, False, 0, "")


def as_text(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def evaluate(src, context):
    src = src.strip()
    if src.startswith("${{") and src.endswith("}}"):
        src = src[3:-2]
    toks = tokens(src)
    i = 0

    def peek():
        return toks[i] if i < len(toks) else (None, None)

    def take(kind=None, value=None):
        nonlocal i
        t = peek()
        if (kind and t[0] != kind) or (value and t[1] != value):
            raise ValueError(f"expected {value or kind}, got {t[1]}")
        i += 1
        return t

    def lookup(path):
        v = context
        for part in path.split("."):
            v = v.get(part) if isinstance(v, dict) else None
        return v

    def primary():
        kind, value = peek()
        if (kind, value) == ("op", "("):
            take()
            v = or_()
            take("op", ")")
            return v
        if (kind, value) == ("op", "!"):
            take()
            return not truthy(primary())
        if kind == "str":
            take()
            return value
        if kind == "name":
            take()
            if peek() == ("op", "("):
                take()
                args = [or_()]
                while peek() == ("op", ","):
                    take()
                    args.append(or_())
                take("op", ")")
                fn = value.lower()
                if fn == "startswith":
                    return as_text(args[0]).lower().startswith(as_text(args[1]).lower())
                if fn == "contains":
                    return as_text(args[1]).lower() in as_text(args[0]).lower()
                if fn == "fromjson":
                    # This reader evaluates both sides of && and ||; GitHub
                    # stops at the first that decides, so it never reads an
                    # unset variable here.
                    return json.loads(args[0]) if args[0] else None
                raise ValueError(f"unknown function {value}")
            if value in ("true", "false"):
                return value == "true"
            if value == "null":
                return None
            return lookup(value)
        raise ValueError(f"unexpected {value}")

    def equality():
        v = primary()
        while peek() in (("op", "=="), ("op", "!=")):
            op = take()[1]
            w = primary()
            # As on GitHub: an unset variable is null, and null equals ''.
            v, w = ("" if v is None and isinstance(w, str) else v), ("" if w is None and isinstance(v, str) else w)
            same = (v.lower() == w.lower()) if isinstance(v, str) and isinstance(w, str) else v == w
            v = same if op == "==" else not same
        return v

    def and_():
        v = equality()
        while peek() == ("op", "&&"):
            take()
            w = equality()
            v = w if truthy(v) else v
        return v

    def or_():
        v = and_()
        while peek() == ("op", "||"):
            take()
            w = and_()
            v = v if truthy(v) else w
        return v

    out = or_()
    if i != len(toks):
        raise ValueError(f"left over: {toks[i:]}")
    return out


# --- self-test -------------------------------------------------------------

def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        ok = got == want
        failed += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f": got {got!r}, want {want!r}"))

    def pr(author, head, **extra):
        return {"pull_request": {"user": {"login": author}, "head": {"ref": head}, **extra}}

    vm, gh = VM_LABELS, "ubuntu-latest"
    VMJ = json.dumps(VM_LABELS)
    events = [
        ("C1: the reproduction's draft runs on GitHub's runners", VMJ, pr(BOT, "test/repro-issue-12"), gh),
        ("C1: the lane's fix runs on GitHub's runners", VMJ, pr(BOT, "fix/31-the-bug-reproduced-from-12"), gh),
        ("C1: the lane's fix on a second attempt's branch too", VMJ, pr(BOT, "fix/31-the-bug-reproduced-from-12-987654"), gh),
        ("C1: a comment on one of dilux-bot's pull requests (no branch in the event)", VMJ,
         {"issue": {"pull_request": {"url": "x"}, "user": {"login": BOT}}}, gh),
        ("C1: a review comment on the reproduction's draft", VMJ, pr(BOT, "test/repro-issue-12") | {"comment": {"body": "x"}}, gh),
        ("C2: a person's pull request keeps the VM", VMJ, pr("soydiloreto", "fix/40-the-login-loop"), vm),
        ("C2: a person's branch named like a reproduction keeps the VM (the author decides too)", VMJ, pr("soydiloreto", "test/repro-issue-12"), vm),
        ("C2: a person's lane-like branch keeps the VM", VMJ, pr("soydiloreto", "fix/31-the-bug-reproduced-from-12"), vm),
        ("dilux-bot's other autopilot pull requests keep the VM", VMJ, pr(BOT, "fix/40-the-login-loop"), vm),
        ("dilux-bot's feature from the autopilot keeps the VM", VMJ, pr(BOT, "feat/41-dark-mode"), vm),
        ("C1: the lane's fix under another type (its issue's Type was not set)", VMJ, pr(BOT, "chore/31-the-bug-reproduced-from-12"), gh),
        ("C1: the lane's fix under another type, second attempt", VMJ, pr(BOT, "feat/31-the-bug-reproduced-from-12-987654"), gh),
        ("the lane's words without a type are not the lane", VMJ, pr(BOT, "the-bug-reproduced-from-12"), vm),
        ("C2: a person's chore branch named like the lane keeps the VM", VMJ, pr("soydiloreto", "chore/31-the-bug-reproduced-from-12"), vm),
        ("the title or labels do not decide", VMJ, pr("soydiloreto", "fix/40-x", title="test(repro): failing test for #12", labels=[{"name": "autopilot"}]), vm),
        ("a comment on a person's pull request keeps the VM", VMJ, {"issue": {"pull_request": {"url": "x"}, "user": {"login": "soydiloreto"}}}, vm),
        ("an issue event of dilux-bot (not a pull request) keeps the VM", VMJ, {"issue": {"user": {"login": BOT}, "title": "Runner image: build failed"}}, vm),
        ("C1: the lane's issue (the autopilot writes the fix there) runs on GitHub's runners", VMJ,
         {"issue": {"user": {"login": BOT}, "title": "The bug reproduced from #12"}, "label": {"name": "accepted"}}, gh),
        ("a person's issue with the lane's title keeps the VM", VMJ, {"issue": {"user": {"login": "soydiloreto"}, "title": "The bug reproduced from #12"}}, vm),
        ("a push or a schedule keeps the VM", VMJ, {"ref": "refs/heads/main"}, vm),
        ("without DX_RUNNER_HEAVY, GitHub's runners", "", pr("soydiloreto", "fix/40-x"), gh),
        ("DX_RUNNER_HEAVY naming GitHub's runner sends the jobs there", '"ubuntu-24.04"', pr("soydiloreto", "fix/40-x"), "ubuntu-24.04"),
        ("the bot's login matches ignoring case, as on GitHub", VMJ, pr("Dilux-Bot[bot]", "test/repro-issue-12"), gh),
    ]
    expr = expression()
    for name, var, event, want in events:
        got = evaluate(expr, {"vars": {"DX_RUNNER_HEAVY": var} if var else {}, "github": {"event": event}})
        check(f"expression: {name}", got, want)
        check(f"decide: {name}", decide(var, event) or gh, want)

    # Another organisation's App, named by its DX_BOT_LOGIN (#197): its
    # reproduction leaves the VM, and ours is nobody special there.
    other = "acme-bot[bot]"
    for name, event, want in [
        ("#197: another organisation's bot's reproduction runs on GitHub's runners", pr(other, "test/repro-issue-12"), gh),
        ("#197: there, dilux-bot's is a stranger's branch and keeps the VM", pr(BOT, "test/repro-issue-12"), vm),
    ]:
        got = evaluate(expr, {"vars": {"DX_RUNNER_HEAVY": VMJ, "DX_BOT_LOGIN": other}, "github": {"event": event}})
        check(f"expression: {name}", got, want)
        check(f"decide: {name}", decide(VMJ, event, other) or gh, want)

    try:
        evaluate(expr, {"vars": {"DX_RUNNER_HEAVY": "github"}, "github": {"event": {}}})
        check("#190: a value that is not JSON fails, as on GitHub (so the docs name only JSON)", "read", "failed")
    except ValueError:
        check("#190: a value that is not JSON fails, as on GitHub (so the docs name only JSON)", "failed", "failed")
    check("the fallback is the one asked for", evaluate(expression("ubuntu-24.04"), {"vars": {}, "github": {"event": {}}}), "ubuntu-24.04")
    check("the expression is one line", "\n" in expr, False)
    check("the expression has no \" #\" (YAML would read the rest as a comment)", " #" in expr, False)

    old = "${{ vars.DX_RUNNER == 'self-hosted' && fromJSON('[\"self-hosted\",\"linux\",\"x64\",\"diluxone\"]') || 'ubuntu-24.04' }}"
    check("#190: the expression names no labels of its own: the variable holds them", "diluxone" in expr or "self-hosted" in expr, False)
    shared = "on:\n  workflow_call:\njobs:\n  a:\n    runs-on: " + old + "\n  b:\n    runs-on: ubuntu-latest\n"
    check("check: the old choice is a problem", len(problems("x.yml", shared)), 2)
    fixed = rewrite(shared)
    check("write: rewrites the DX_RUNNER_HEAVY line, keeping its fallback", f"    runs-on: {expression('ubuntu-24.04')}\n" in fixed, True)
    check("write: leaves a plain runs-on alone (check still names it)", "    runs-on: ubuntu-latest\n" in fixed and len(problems("x.yml", fixed)), 1)
    check("check: a workflow that is not shared is not read", problems("x.yml", "on:\n  push:\njobs:\n  a:\n    runs-on: ubuntu-latest\n"), [])
    check("check: the reproduction carries no DX_RUNNER_HEAVY", len(problems("issue-repro.yml", "on:\n  workflow_call:\n    runs-on: " + expression() + "\n")), 1)
    check("check: the reproduction's header may name DX_RUNNER_HEAVY (comments are not jobs)",
          problems("issue-repro.yml", "# whatever DX_RUNNER_HEAVY says\non:\n  workflow_call:\njobs:\n  a:\n    runs-on: ubuntu-latest\n"), [])
    check("check: an unknown fallback is a problem", len(problems("x.yml", "on:\n  workflow_call:\n    runs-on: " + expression("windows-latest") + "\n")), 1)

    decided = "${{ (vars.DX_RUNNER_HEAVY != '' && needs.where.outputs.github-hosted == 'false') && fromJSON(vars.DX_RUNNER_HEAVY) || 'ubuntu-latest' }}"
    later = "on:\n  workflow_call:\njobs:\n  run:\n    runs-on: " + decided + "\n"
    check("check: a job whose runner an earlier job decided keeps it", problems("autopilot.yml", later), [])
    check("write: leaves a job whose runner an earlier job decided alone", rewrite(later), later)
    fresh = "on:\n  workflow_call:\njobs:\n  apply:\n    runs-on: ubuntu-latest # fresh: it holds the key beside an agent's work (#287)\n"
    check("#287: a job that holds the key beside an agent's work stays on a fresh runner, said on its line",
          (problems("autopilot.yml", fresh), rewrite(fresh) == fresh, len(problems("autopilot.yml", fresh.replace(" # fresh: it holds the key beside an agent's work (#287)", "")))), ([], True, 1))
    check("check: a GitHub-only workflow may name DX_RUNNER_HEAVY outside runs-on", problems("runner-wake.yml", "# DX_RUNNER_HEAVY\non:\n  workflow_call:\njobs:\n  a:\n    if: vars.DX_RUNNER_HEAVY == 'self-hosted'\n    runs-on: ubuntu-latest\n"), [])
    check("check: the VM's wake-up stays on GitHub's runners", problems("runner-wake.yml", "on:\n  workflow_call:\njobs:\n  a:\n    runs-on: ubuntu-latest\n"), [])

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        shared_path = os.path.join(tmp, "x.yml")
        repro_path = os.path.join(tmp, "issue-repro.yml")
        with open(shared_path, "w") as f:
            f.write("on:\n  workflow_call:\njobs:\n  a:\n    runs-on: " + old + "\n")
        repro_text = "on:\n  workflow_call:\njobs:\n  a:\n    runs-on: " + old + "\n"
        with open(repro_path, "w") as f:
            f.write(repro_text)
        quiet = open(os.devnull, "w")
        stdout, sys.stdout = sys.stdout, quiet
        try:
            before = main(["check", shared_path])
            wrote = main(["write", shared_path, repro_path])
            after = main(["check", shared_path])
        finally:
            sys.stdout = stdout
            quiet.close()
        check("cli: check exits 1 on the old choice", before, 1)
        check("cli: write fixes a shared job, and still fails on the reproduction's DX_RUNNER_HEAVY", wrote, 1)
        check("cli: check exits 0 once written", after, 0)
        with open(repro_path) as f:
            check("cli: write never adds the choice to a GitHub-only workflow", f.read(), repro_text)

    print("all passed" if not failed else f"{failed} failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if not argv or argv[0] not in ("expression", "check", "write"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "expression":
        print(expression(rest[0] if rest else "ubuntu-latest"))
        return 0
    found = []
    for path in workflow_files(rest):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if cmd == "write" and is_shared(text) and os.path.basename(path) not in GITHUB_ONLY:
            new = rewrite(text)
            if new != text:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new)
                text = new
        found += problems(path, text)
    for p in found:
        print(f"::error::{p}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
