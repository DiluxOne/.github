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


def writes(permissions):
    if permissions == "write-all":
        return True
    return isinstance(permissions, dict) and any(v == "write" for v in permissions.values())


def problems(workflow):
    out = []
    jobs = (workflow or {}).get("jobs") or {}
    for name, job in jobs.items():
        steps = job.get("steps") or []
        agents = [s for s in steps if "claude-code-action" in str(s.get("uses", ""))]
        if not agents:
            continue
        shell = False
        for s in agents:
            why = strictness(s)
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
    print("all tests passed" if not failed else "FAILED")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    bad = 0
    for path in argv or sorted(glob.glob(".github/workflows/*.yml")):
        with open(path, encoding="utf-8") as fh:
            for p in problems(yaml.safe_load(fh)):
                print(f"{path}: {p}")
                bad = 1
    if not bad:
        print("No agent with a shell shares a job with a key, and every Claude step states a strict permission mode.")
    return bad


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
