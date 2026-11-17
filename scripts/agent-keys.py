#!/usr/bin/env python3
"""An agent that can run commands never shares a job with a key (#287).

A shell in a job that holds a secret can read it out of the runner's
memory, whatever the scope of the token the agent is given: that is how
the tj-actions compromise took secrets. So a job with a Claude step whose
tools include Bash (or that names no tools, which allows them all) may hold
no secret but the model's (CLAUDE_CODE_OAUTH_TOKEN, ANTHROPIC_API_KEY),
mint no App token, and its own token may write nothing. Every Claude step,
with a shell or not, names its tools.

And keeps that list strict (#793): from claude-code-action v1.0.273 a step
that states no permission mode may run tools its --allowedTools does not
list. So every Claude step states `--permission-mode default` or
`--permission-mode dontAsk` (what the workflows here use: nothing may
prompt in a headless run), or a --disallowedTools list; any other mode
(bypassPermissions, acceptEdits, auto, plan, ...) or
--dangerously-skip-permissions widens it and is refused, list or not.

Every step pins the action the same way: one 40-hex commit SHA with its
`# vX.Y.Z` in a comment, the same in every step of every workflow.

And keeps the action's own guard (v1.0.273 and later): on a pull request
whose author has no write access, `restrict_untrusted_prs` denies the
commands that run code from the checkout. Its author is never trusted when
it is a bot, so the autopilot's two steps (autopilot.yml's `spec` and
`work`) turn it off only when the pull request is dilux-bot's own, the
exact expression BOT_ONLY; any other value there, and the input set to
anything but "true" in any other step, is refused.

    agent-keys.py [workflow.yml ...]   default: .github/workflows/*.yml
    agent-keys.py --test
"""
import glob
import json
import re
import sys

import yaml

MODEL_SECRETS = {"CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"}
TOOLS = re.compile(r'--allowedTools\s+"([^"]*)"')
MODES = {"default", "dontAsk"}
MODE = re.compile(r'--permission-mode(?:\s+|=)["\']?([^\s"\']*)')
DISALLOWED = re.compile(r'--disallowedTools(?:\s+|=)"[^"]*[^"\s][^"]*"')
USES = re.compile(r'^\s*(?:-\s+)?uses:\s*["\']?([^\s"\'#]*anthropics/claude-code-action[^\s"\'#]*)["\']?[ \t]*(?:#[ \t]*(\S*))?', re.M)
SHA = re.compile(r"[0-9a-f]{40}")
VERSION = re.compile(r"v\d+\.\d+\.\d+")
# The one value the autopilot's steps may give restrict_untrusted_prs:
# "false" only on a pull request (or a comment on one) that dilux-bot opened.
BOT_ONLY = ("${{ vars.DX_BOT_LOGIN != '' && (github.event.pull_request.user.login"
            " || (github.event.issue.pull_request && github.event.issue.user.login))"
            " == vars.DX_BOT_LOGIN && 'false' || 'true' }}")
BOT_STEPS = {("autopilot.yml", "spec"), ("autopilot.yml", "work")}


def tools(step):
    """The step's allowed tools, or None when it names none."""
    m = TOOLS.search(str((step.get("with") or {}).get("claude_args", "")))
    return [t.strip() for t in m.group(1).split(",")] if m else None


def strictness(step):
    """What is wrong with the step's permission mode, or None (#793)."""
    args = str((step.get("with") or {}).get("claude_args", ""))
    if "--dangerously-skip-permissions" in args:
        return "skips its permissions (--dangerously-skip-permissions)"
    wide = [m for m in MODE.findall(args) if m not in MODES]
    if wide:
        return f"states a permission mode that widens --allowedTools ({', '.join(wide)})"
    if MODE.search(args) or DISALLOWED.search(args):
        return None
    return "states no permission mode (--permission-mode dontAsk or default) and no --disallowedTools"


def untrusted(path, step):
    """What is wrong with the step's restrict_untrusted_prs, or None."""
    w = step.get("with") or {}
    if "restrict_untrusted_prs" not in w:
        return None
    value = str(w["restrict_untrusted_prs"]).strip()
    if value == "true":
        return None
    where = (path.replace("\\", "/").rsplit("/", 1)[-1], step.get("id"))
    if where in BOT_STEPS and value == BOT_ONLY:
        return None
    if where in BOT_STEPS:
        return "turns off restrict_untrusted_prs other than on dilux-bot's own pull request (BOT_ONLY)"
    return "turns off restrict_untrusted_prs, which only the autopilot's spec and work steps may, on dilux-bot's pull request"


def pins(texts):
    """What is wrong with how the workflows pin claude-code-action."""
    out, seen = [], {}
    for path, text in texts.items():
        for m in USES.finditer(text):
            ref, comment = m.group(1), m.group(2) or ""
            line = text.count("\n", 0, m.start(1)) + 1
            sha = ref.partition("@")[2]
            if not SHA.fullmatch(sha):
                out.append(f"{path}:{line}: claude-code-action is not pinned to a full commit SHA ({ref})")
            elif not VERSION.fullmatch(comment):
                out.append(f"{path}:{line}: claude-code-action's pin has no `# vX.Y.Z` comment")
            else:
                seen.setdefault((sha, comment), f"{path}:{line}")
    if len(seen) > 1:
        out.append("claude-code-action is pinned to more than one version: " + "; ".join(f"{v} {s[:12]} at {w}" for (s, v), w in sorted(seen.items(), key=lambda kv: kv[1])))
    return out


def writes(permissions):
    if permissions == "write-all":
        return True
    return isinstance(permissions, dict) and any(v == "write" for v in permissions.values())


def problems(workflow, path=""):
    out = []
    jobs = (workflow or {}).get("jobs") or {}
    for name, job in jobs.items():
        steps = job.get("steps") or []
        agents = [s for s in steps if "claude-code-action" in str(s.get("uses", ""))]
        if not agents:
            continue
        shell = False
        for s in agents:
            for why in (strictness(s), untrusted(path, s)):
                if why:
                    out.append(f"{name}: the Claude step {s.get('name') or s.get('id') or ''!r} {why}")
            t = tools(s)
            if t is None:
                out.append(f"{name}: the Claude step {s.get('name') or s.get('id') or ''!r} names no tools (--allowedTools)")
                shell = True
            elif any(x == "Bash" or x.startswith("Bash(") for x in t):
                shell = True
        if not shell:
            continue
        # The job, and what it inherits from the workflow's own env.
        text = json.dumps(job) + json.dumps(workflow.get("env") or {})
        secrets = set(re.findall(r"secrets\.([A-Za-z_][A-Za-z0-9_]*)", text))
        secrets |= set(re.findall(r"secrets\[\s*['\"]([^'\"]+)['\"]\s*\]", text))
        secrets -= MODEL_SECRETS
        # Any other use of the context (toJSON, format, an expression key)
        # can reach every secret.
        if re.search(r"\bsecrets\b(?!\.[A-Za-z_]|\[\s*['\"])", re.sub(r"secrets\.(CLAUDE_CODE_OAUTH_TOKEN|ANTHROPIC_API_KEY)\b", "", text)):
            secrets.add("every secret")
        if secrets:
            out.append(f"{name}: an agent with a shell shares the job with {', '.join(sorted(secrets))}")
        if any("create-github-app-token" in str(s.get("uses", "")) for s in steps):
            out.append(f"{name}: an agent with a shell shares the job with an App token")
        perms = job.get("permissions", workflow.get("permissions"))
        if writes(perms):
            out.append(f"{name}: an agent with a shell runs with a token that writes ({perms})")
    return out


def self_test():
    failed = 0

    def check(label, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + label + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    agent = lambda t, extra="\n--permission-mode dontAsk": {"uses": "anthropics/claude-code-action@x", "with": {"claude_args": (f'--model m\n--allowedTools "{t}"' if t is not None else "--model m") + extra}}
    key = {"uses": "actions/create-github-app-token@x", "with": {"private-key": "${{ secrets.DILUX_BOT_PRIVATE_KEY }}"}}
    wf = lambda job, top=None: {"permissions": top or {}, "jobs": {"j": job}}
    check("a shell alone, reading: fine", problems(wf({"permissions": {"contents": "read"}, "steps": [agent("Bash,Read")]})), [])
    check("a shell beside the bot's key", len(problems(wf({"permissions": {}, "steps": [key, agent("Bash,Read")]}))), 2)
    check("a narrow shell counts too", problems(wf({"permissions": {}, "steps": [{"run": "x", "env": {"K": "${{ secrets.SVN_PASSWORD }}"}}, agent("Bash(git diff:*),Read")]})),
          ["j: an agent with a shell shares the job with SVN_PASSWORD"])
    check("the model's own secrets are fine", problems(wf({"steps": [{"with": {"claude_code_oauth_token": "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}"}}, agent("Bash")]})), [])
    check("a token that writes", problems(wf({"permissions": {"contents": "write"}, "steps": [agent("Bash")]})), ["j: an agent with a shell runs with a token that writes ({'contents': 'write'})"])
    check("the workflow's permissions when the job sets none", len(problems(wf({"steps": [agent("Bash")]}, {"issues": "write"}))), 1)
    check("no tools named is a shell, and said", len(problems(wf({"permissions": {}, "steps": [key, agent(None)]}))), 3)
    check("the workflow's env counts", problems({"env": {"K": "${{ secrets.DILUX_BOT_PRIVATE_KEY }}"}, "jobs": {"j": {"permissions": {}, "steps": [agent("Bash")]}}}),
          ["j: an agent with a shell shares the job with DILUX_BOT_PRIVATE_KEY"])
    check("secrets['X'] and toJSON(secrets) count",
          (problems(wf({"permissions": {}, "steps": [{"env": {"K": "${{ secrets['SVN_PASSWORD'] }}"}}, agent("Bash")]})),
           problems(wf({"permissions": {}, "steps": [{"env": {"K": "${{ toJSON(secrets) }}"}}, agent("Bash")]})),
           problems(wf({"permissions": {}, "steps": [{"env": {"K": "${{ format('{0}', secrets) }}"}}, agent("Bash")]}))),
          (["j: an agent with a shell shares the job with SVN_PASSWORD"], ["j: an agent with a shell shares the job with every secret"], ["j: an agent with a shell shares the job with every secret"]))
    check("no shell: a key in the job is allowed", problems(wf({"permissions": {"issues": "write"}, "steps": [key, agent("Read,Glob,Grep")]})), [])
    # The permission mode keeps --allowedTools strict (#793).
    reading = lambda extra: problems(wf({"permissions": {}, "steps": [agent("Read", extra)]}))
    check("neither a mode nor --disallowedTools fails", reading(""),
          ["j: the Claude step '' states no permission mode (--permission-mode dontAsk or default) and no --disallowedTools"])
    check("--permission-mode dontAsk passes", reading("\n--permission-mode dontAsk"), [])
    check("--permission-mode default passes", reading("\n--permission-mode default"), [])
    check("--permission-mode=dontAsk passes", reading(" --permission-mode=dontAsk"), [])
    check("--disallowedTools passes", reading('\n--disallowedTools "Bash,Write"'), [])
    check("an empty --disallowedTools is no list", len(reading('\n--disallowedTools ""')), 1)
    check("bypassPermissions fails", reading("\n--permission-mode bypassPermissions"),
          ["j: the Claude step '' states a permission mode that widens --allowedTools (bypassPermissions)"])
    check("acceptEdits fails, even with --disallowedTools", len(reading('\n--permission-mode acceptEdits\n--disallowedTools "Bash"')), 1)
    check("a quoted wide mode fails", len(reading('\n--permission-mode "auto"')), 1)
    check("a second, wider mode fails", len(reading("\n--permission-mode dontAsk\n--permission-mode plan")), 1)
    check("--dangerously-skip-permissions fails", len(reading("\n--permission-mode dontAsk\n--dangerously-skip-permissions")), 1)
    # The action's guard on outside pull requests stays on (#793).
    guarded = lambda value, path="x.yml", sid="work": problems(wf({"permissions": {}, "steps": [dict(agent("Read"), id=sid, **{"with": dict(agent("Read")["with"], restrict_untrusted_prs=value)})]}), path)
    check("restrict_untrusted_prs true passes anywhere", guarded("true"), [])
    check("BOT_ONLY passes on the autopilot's spec and work", (guarded(BOT_ONLY, ".github/workflows/autopilot.yml"), guarded(BOT_ONLY, "autopilot.yml", "spec")), ([], []))
    check("false is refused, even in the autopilot", (len(guarded("false")), len(guarded("false", "autopilot.yml")), len(guarded(False, "autopilot.yml", "spec"))), (1, 1, 1))
    check("BOT_ONLY is refused on any other step", (len(guarded(BOT_ONLY)), len(guarded(BOT_ONLY, "autopilot.yml", "fix")), len(guarded(BOT_ONLY, "claude-review.yml", "spec"))), (1, 1, 1))
    check("another condition is refused in the autopilot", len(guarded(BOT_ONLY.replace("vars.DX_BOT_LOGIN && 'false'", "'x' && 'false'"), "autopilot.yml")), 1)
    # One pin, the same in every step (#793).
    sha, other = "a" * 40, "b" * 40
    step = lambda ref, c="# v1.0.278": f"      - name: x\n        uses: anthropics/claude-code-action@{ref} {c}\n"
    check("one SHA and version everywhere passes", pins({"a.yml": step(sha) + step(sha), "b.yml": step(sha)}), [])
    check("a tag is no pin", pins({"a.yml": step("v1")}), ["a.yml:2: claude-code-action is not pinned to a full commit SHA (anthropics/claude-code-action@v1)"])
    check("a short SHA is no pin", len(pins({"a.yml": step(sha[:12])})), 1)
    check("a pin needs its version comment", (len(pins({"a.yml": step(sha, "")})), len(pins({"a.yml": step(sha, "# latest")}))), (1, 1))
    check("two versions fail", len(pins({"a.yml": step(sha), "b.yml": step(other, "# v1.0.271")})), 1)
    check("the same version on two SHAs fails", len(pins({"a.yml": step(sha), "b.yml": step(other)})), 1)
    check("a quoted uses counts", len(pins({"a.yml": "    - uses: 'anthropics/claude-code-action@v1'\n"})), 1)
    print("all tests passed" if not failed else "FAILED")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    bad = 0
    texts = {}
    for path in argv or sorted(glob.glob(".github/workflows/*.yml")):
        with open(path, encoding="utf-8") as fh:
            texts[path] = fh.read()
        for p in problems(yaml.safe_load(texts[path]), path):
            print(f"{path}: {p}")
            bad = 1
    for p in pins(texts):
        print(p)
        bad = 1
    if not bad:
        print("No agent with a shell shares a job with a key, every Claude step states a strict permission mode, and every one pins the same claude-code-action.")
    return bad


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
