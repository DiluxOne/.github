#!/usr/bin/env python3
"""Deterministic review policy: the ceiling no reviewer can lower.

Reads the organisation defaults (policy/review-policy.default.yml in this
repository) and the calling repository's .github/review-policy.yml, matches
the pull request's changed files against them, and writes to $GITHUB_OUTPUT:

  floor     low | medium | high   the minimum risk this PR can be rated
  trusted   true | false          the author may have a PR auto-merged
  reasons   one line saying why the floor is what it is
  model     the model for this floor (the repository's choice, else the default)
  effort    the reasoning effort for this floor
  budget    the most one review run may spend, in USD
  auto_merge  true | false     whether qualifying pull requests merge on their own

With POLICY_LEVEL=low|medium|high set, the floor is that level (a job that
has no diff, such as the issue triage, asks for the reviewer of a level).

With POLICY_MODE=changes it answers a different question from the same
files and writes instead:

  code          true | false   a changed file matches a `code` pattern
  plugin_check  true | false   a changed file matches a `plugin-check` pattern
  reasons       one line saying which files decided it

That is what the slow suites and Plugin Check are gated on. When no file
could be listed the answer is true for both: an unknown change runs
everything.

Every review setting lives in these two files and nowhere else: `review:`
(`{low|medium|high: {model, effort}}`), `budget-usd:` and `auto-merge:`. The
repository's value wins key by key; what it leaves out stays as the default.

Rules, in order:
  1. Any changed file matching a `high-risk` pattern  -> floor high.
  2. Every changed file matching a `low-risk-eligible` pattern -> floor low.
  3. Anything else -> floor medium.

The model's rating can raise the floor, never lower it. Nothing here reads
the PR title, body or code: only paths and the author's login.
"""
import fnmatch
import json
import os
import re
import subprocess
import sys


def load_yaml(path):
    if not os.path.exists(path):
        return {}
    out = subprocess.run(["yq", "-o=json", ".", path], check=True, capture_output=True, text=True).stdout
    return json.loads(out or "{}") or {}


def glob_to_regex(pattern):
    # ** crosses directories, * and ? do not. "docs/**" matches everything under docs/.
    i, out = 0, ""
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile("^" + out + "$")


def matches(path, patterns):
    return any(glob_to_regex(p).match(path) for p in patterns)


def changes(defaults, repo, files):
    code = defaults.get("code", []) + repo.get("code", [])
    plugin_check = defaults.get("plugin-check", []) + repo.get("plugin-check", [])
    if not files:
        hit_code, hit_check = True, True
        reasons = "no changed files could be listed; everything runs"
    else:
        code_hits = [f for f in files if matches(f, code)]
        check_hits = [f for f in files if matches(f, plugin_check)]
        hit_code, hit_check = bool(code_hits), bool(check_hits)
        if code_hits:
            reasons = "code changed: " + ", ".join(code_hits[:5]) + (" …" if len(code_hits) > 5 else "")
        elif check_hits:
            reasons = "no code changed; Plugin Check reads: " + ", ".join(check_hits[:5])
        else:
            reasons = "no code changed"
    with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
        fh.write(f"code={'true' if hit_code else 'false'}\nplugin_check={'true' if hit_check else 'false'}\nreasons={reasons}\n")
    print(f"code={'true' if hit_code else 'false'} plugin_check={'true' if hit_check else 'false'} ({reasons})")
    return 0


def main():
    defaults = load_yaml(os.environ["DEFAULT_POLICY"])
    repo = load_yaml(os.environ.get("REPO_POLICY", ".github/review-policy.yml"))
    files = [f for f in os.environ.get("CHANGED_FILES", "").splitlines() if f.strip()]
    if os.environ.get("POLICY_MODE", "") == "changes":
        return changes(defaults, repo, files)
    author = os.environ.get("PR_AUTHOR", "")
    forced = os.environ.get("POLICY_LEVEL", "")
    if forced and forced not in ("low", "medium", "high"):
        print(f"::error::POLICY_LEVEL '{forced}' is not low, medium or high.")
        return 1

    high = defaults.get("high-risk", []) + repo.get("high-risk", [])
    low = defaults.get("low-risk-eligible", []) + repo.get("low-risk-eligible", [])
    trusted_authors = repo.get("trusted-authors", defaults.get("trusted-authors", []))

    high_hits = [f for f in files if matches(f, high)]
    if forced:
        floor, reasons = forced, f"level {forced} requested by the caller"
    elif not files:
        floor, reasons = "high", "no changed files could be listed"
    elif high_hits:
        floor = "high"
        shown = ", ".join(high_hits[:5]) + (" …" if len(high_hits) > 5 else "")
        reasons = f"touches high-risk paths: {shown}"
    elif all(matches(f, low) for f in files):
        floor, reasons = "low", "every changed file is low-risk eligible"
    else:
        others = [f for f in files if not matches(f, low)]
        floor = "medium"
        reasons = "changes code outside the low-risk paths: " + ", ".join(others[:5]) + (" …" if len(others) > 5 else "")

    trusted = "true" if author in trusted_authors else "false"
    level = {**((defaults.get("review") or {}).get(floor) or {}), **((repo.get("review") or {}).get(floor) or {})}
    model = str(level.get("model") or "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", model):
        print(f"::error::review.{floor}.model '{model}' is not a model id.")
        return 1
    effort = str(level.get("effort") or "medium")
    if effort not in ("low", "medium", "high", "xhigh", "max"):
        print(f"::warning::review.{floor}.effort '{effort}' is not low, medium, high, xhigh or max; using medium.")
        effort = "medium"
    budget = repo.get("budget-usd", defaults.get("budget-usd", 3))
    try:
        value = float(budget)
        if not (0 < value < 1000):
            raise ValueError
        budget = f"{value:g}"
    except (TypeError, ValueError):
        print(f"::warning::budget-usd '{budget}' is not a positive number below 1000; using 3.")
        budget = "3"
    # The organisation's false stops every repository; a repository can only
    # turn auto-merge off for itself, never on when the organisation says no.
    auto_merge = defaults.get("auto-merge", False) is True and repo.get("auto-merge", True) is not False
    auto_merge = "true" if auto_merge else "false"
    with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
        fh.write(f"floor={floor}\ntrusted={trusted}\nreasons={reasons}\nmodel={model}\neffort={effort}\nbudget={budget}\nauto_merge={auto_merge}\n")
    print(f"floor={floor} trusted={trusted} ({reasons}) model={model} effort={effort} budget={budget} auto-merge={auto_merge}")


if __name__ == "__main__":
    sys.exit(main())
