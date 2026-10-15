#!/usr/bin/env python3
"""The jobs plugin-tests-wp.yml runs: one per integration target, one per E2E suite.

Reads the workflow's inputs from the environment and writes two JSON
matrices to $GITHUB_OUTPUT, `integration` and `e2e`, each a list of
entries whose `check` is the job's name, the status check a ruleset
requires. Names are stable: they come from the inputs, never from the
order or the run.

  INTEGRATION          true | false   run the integration suite at all
  MULTISITE            true | false   the old switch: the one target is the network
  INTEGRATION_TARGETS  JSON list of targets, each "single" or "network", or
                       {name, timeout?} with the same name; empty: the old
                       behaviour, one job named "Integration tests (wp-env)"
                       on the network (MULTISITE true) or a single site
  E2E                  true | false   run the end-to-end suites at all
  E2E_SUITES           JSON list of {name, site, run, results?, timeout?}; empty:
                       the old behaviour, one job named "E2E (Playwright)" that
                       runs `npx playwright test` on a single site

Check names:
  integration targets  "Integration (single site)", "Integration (network)"
  E2E suites           "E2E (<name>)"

An E2E suite's `site` is where the plugin is activated before `run`: `single`
is the wp-env development site; `network` is the wp-env tests site turned into
a subdirectory network, with WordPress's rewrite rules and the plugin
network-activated. `run` is the command, run by bash from the checkout (an
npm script, `npx playwright test -c <config>`, variables in front of it);
`results` the folder kept when it fails (default build/e2e-results);
`timeout` its minutes (default 25).

An integration target's `timeout` is its job's minutes too (default 40: on
the organisation's VM, whose four runners share four cores, the network
suite takes up to twice what it takes on GitHub's). Both timeouts are whole
minutes, from 5 to 120.

Every entry has `enabled`: a suite turned off (`integration: false`,
`e2e: false`) is still an entry, with `enabled` false, and its job runs no
step. A job skipped by a condition before its matrix is expanded reports a
check under its unexpanded name, which no ruleset can require; a job that
always exists and skips its steps reports the name the ruleset expects,
green.

An input that is not what this says fails here, with the reason, before any
suite starts. `test-targets.py --test` checks these rules.
"""
import json
import os
import re
import sys

NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
SITES = ("single", "network")
LEGACY_INTEGRATION = "Integration tests (wp-env)"
LEGACY_E2E = "E2E (Playwright)"
INTEGRATION_TIMEOUT = 40
E2E_TIMEOUT = 25


class InputError(Exception):
    pass


def as_bool(value, default=True):
    if value in (None, ""):
        return default
    return str(value).strip().lower() == "true"


def as_list(name, value):
    if value in (None, ""):
        return None
    try:
        data = json.loads(value)
    except ValueError as err:
        raise InputError(f"{name} is not JSON: {err}")
    if not isinstance(data, list):
        raise InputError(f"{name} is a JSON list.")
    return data


def minutes(entry, default, where):
    """A job's `timeout`, whole minutes from 5 to 120; `where` names the entry in the error."""
    timeout = entry.get("timeout", default)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 5 <= timeout <= 120:
        raise InputError(f"{where}: timeout is whole minutes, from 5 to 120.")
    return timeout


def integration(env):
    enabled = as_bool(env.get("INTEGRATION"))
    targets = as_list("integration-targets", env.get("INTEGRATION_TARGETS"))
    if targets is None:
        site = "network" if as_bool(env.get("MULTISITE")) else "single"
        return [{"check": LEGACY_INTEGRATION, "site": site, "timeout": INTEGRATION_TIMEOUT, "enabled": enabled}]
    if not targets:
        raise InputError("integration-targets is empty: leave it out, or turn integration off.")
    out = []
    for n, target in enumerate(targets, 1):
        # A name alone, or {name, timeout?}.
        entry = {"name": target} if isinstance(target, str) else target
        if not isinstance(entry, dict):
            raise InputError(f"integration-targets, entry {n}: a site name, or an object with name and timeout.")
        unknown = set(entry) - {"name", "timeout"}
        if unknown:
            raise InputError(f"integration-targets, entry {n}: unknown key(s) {', '.join(sorted(unknown))}.")
        site = entry.get("name")
        if site not in SITES:
            raise InputError(f"integration-targets: '{site}' is not single or network.")
        if any(t["site"] == site for t in out):
            raise InputError(f"integration-targets: '{site}' is listed twice.")
        timeout = minutes(entry, INTEGRATION_TIMEOUT, f"integration-targets, '{site}'")
        out.append({"check": "Integration (single site)" if site == "single" else "Integration (network)", "site": site, "timeout": timeout, "enabled": enabled})
    return out


def e2e(env):
    enabled = as_bool(env.get("E2E"))
    suites = as_list("e2e-suites", env.get("E2E_SUITES"))
    if suites is None:
        return [{"check": LEGACY_E2E, "name": "playwright", "site": "single", "run": "npx playwright test", "results": "build/e2e-results", "artifact": "playwright-results", "timeout": E2E_TIMEOUT, "enabled": enabled}]
    if not suites:
        raise InputError("e2e-suites is empty: leave it out, or turn e2e off.")
    out = []
    for n, suite in enumerate(suites, 1):
        if not isinstance(suite, dict):
            raise InputError(f"e2e-suites, entry {n}: an object with name, site and run.")
        unknown = set(suite) - {"name", "site", "run", "results", "timeout"}
        if unknown:
            raise InputError(f"e2e-suites, entry {n}: unknown key(s) {', '.join(sorted(unknown))}.")
        name = suite.get("name")
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise InputError(f"e2e-suites, entry {n}: name '{name}' is lower-case letters, digits and hyphens (it names the check).")
        if any(s["name"] == name for s in out):
            raise InputError(f"e2e-suites: the name '{name}' is used twice.")
        if suite.get("site") not in SITES:
            raise InputError(f"e2e-suites, '{name}': site is single or network.")
        run = suite.get("run")
        if not isinstance(run, str) or not run.strip() or "\n" in run:
            raise InputError(f"e2e-suites, '{name}': run is one command line.")
        results = suite.get("results", "build/e2e-results")
        if not isinstance(results, str) or results.startswith("/") or ".." in results.split("/"):
            raise InputError(f"e2e-suites, '{name}': results is a folder inside the checkout.")
        timeout = minutes(suite, E2E_TIMEOUT, f"e2e-suites, '{name}'")
        out.append({"check": f"E2E ({name})", "name": name, "site": suite["site"], "run": run.strip(), "results": results, "artifact": f"playwright-results-{name}", "timeout": timeout, "enabled": enabled})
    return out


def plan(env):
    return {"integration": integration(env), "e2e": e2e(env)}


def main():
    try:
        result = plan(os.environ)
    except InputError as err:
        print(f"::error::{err}")
        return 1
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
        for key, value in result.items():
            fh.write(f"{key}={json.dumps(value, separators=(',', ':'))}\n")
    for key, value in result.items():
        print(f"{key}: " + (", ".join(v["check"] for v in value) or "none"))
    return 0


def self_test():
    cases = [
        # (name, env, expected checks or an error substring)
        ("the old defaults: one network integration job, one single-site E2E job", {}, {"integration": [LEGACY_INTEGRATION], "e2e": [LEGACY_E2E]}),
        ("multisite false keeps the old name, on a single site", {"MULTISITE": "false"}, {"integration": [LEGACY_INTEGRATION]}),
        ("suites off keep their jobs, which run nothing", {"INTEGRATION": "false", "E2E": "false"}, {"integration": [LEGACY_INTEGRATION], "e2e": [LEGACY_E2E]}),
        ("both integration targets", {"INTEGRATION_TARGETS": '["single","network"]'}, {"integration": ["Integration (single site)", "Integration (network)"]}),
        ("a list of E2E suites", {"E2E_SUITES": json.dumps([{"name": "single", "site": "single", "run": "npx playwright test"}, {"name": "network", "site": "network", "run": "npx playwright test -c playwright.network.config.ts", "results": "build/e2e-network-results", "timeout": 40}])}, {"e2e": ["E2E (single)", "E2E (network)"]}),
        ("a target that is not one", {"INTEGRATION_TARGETS": '["cluster"]'}, "not single or network"),
        ("a target twice", {"INTEGRATION_TARGETS": '["single","single"]'}, "listed twice"),
        ("an empty target list", {"INTEGRATION_TARGETS": "[]"}, "is empty"),
        ("not JSON", {"E2E_SUITES": "single"}, "is not JSON"),
        ("a suite name that is not a check name", {"E2E_SUITES": '[{"name":"Single Site","site":"single","run":"x"}]'}, "lower-case"),
        ("a suite name twice", {"E2E_SUITES": '[{"name":"a","site":"single","run":"x"},{"name":"a","site":"network","run":"y"}]'}, "used twice"),
        ("a suite with no site", {"E2E_SUITES": '[{"name":"a","run":"x"}]'}, "site is single or network"),
        ("a suite with two lines", {"E2E_SUITES": json.dumps([{"name": "a", "site": "single", "run": "x\ny"}])}, "one command line"),
        ("results outside the checkout", {"E2E_SUITES": '[{"name":"a","site":"single","run":"x","results":"../x"}]'}, "inside the checkout"),
        ("an unknown key", {"E2E_SUITES": '[{"name":"a","site":"single","run":"x","env":{}}]'}, "unknown key"),
        ("a timeout out of range", {"E2E_SUITES": '[{"name":"a","site":"single","run":"x","timeout":600}]'}, "from 5 to 120"),
        ("an integration target as an object", {"INTEGRATION_TARGETS": '["single",{"name":"network","timeout":60}]'}, {"integration": ["Integration (single site)", "Integration (network)"]}),
        ("an integration target with an unknown key", {"INTEGRATION_TARGETS": '[{"name":"network","minutes":60}]'}, "unknown key"),
        ("an integration target that is neither a name nor an object", {"INTEGRATION_TARGETS": '[["network"]]'}, "a site name, or an object"),
        ("an integration timeout too long", {"INTEGRATION_TARGETS": '[{"name":"network","timeout":600}]'}, "from 5 to 120"),
        ("an integration timeout too short", {"INTEGRATION_TARGETS": '[{"name":"network","timeout":2}]'}, "from 5 to 120"),
        ("an integration timeout that is not whole minutes", {"INTEGRATION_TARGETS": '[{"name":"network","timeout":"40"}]'}, "whole minutes"),
    ]
    failed = 0
    for name, env, want in cases:
        try:
            got = plan(env)
            if isinstance(want, str):
                ok, detail = False, f"no error, got {got}"
            else:
                checks = {k: [v["check"] for v in got[k]] for k in got}
                ok = all(checks[k] == v for k, v in want.items())
                detail = checks
        except InputError as err:
            ok = isinstance(want, str) and want in str(err)
            detail = str(err)
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
        failed += 0 if ok else 1
    off = plan({"INTEGRATION": "false", "E2E": "false", "INTEGRATION_TARGETS": '["single","network"]'})
    if any(t["enabled"] for t in off["integration"] + off["e2e"]) or len(off["integration"]) != 2:
        failed += 1
        print("FAIL a suite turned off keeps every job, disabled")
    else:
        print("ok   a suite turned off keeps every job, disabled")
    legacy = plan({})["e2e"][0]
    if legacy["artifact"] != "playwright-results" or legacy["results"] != "build/e2e-results":
        failed += 1
        print("FAIL the old E2E job keeps its artifact and results folder")
    else:
        print("ok   the old E2E job keeps its artifact and results folder")
    # C1 (#127): names only, and the old single job, each get the default timeout.
    by_name = plan({"INTEGRATION_TARGETS": '["single","network"]'})["integration"]
    if [t["timeout"] for t in by_name] != [INTEGRATION_TIMEOUT, INTEGRATION_TIMEOUT] or plan({})["integration"][0]["timeout"] != INTEGRATION_TIMEOUT:
        failed += 1
        print("FAIL C1 (#127): an integration target named alone, and the old single job, get a 40-minute timeout")
    else:
        print("ok   C1 (#127): an integration target named alone, and the old single job, get a 40-minute timeout")
    # C2 (#127): the caller's timeout reaches the job.
    by_object = plan({"INTEGRATION_TARGETS": '["single",{"name":"network","timeout":60}]'})["integration"]
    if {t["check"]: t["timeout"] for t in by_object} != {"Integration (single site)": INTEGRATION_TIMEOUT, "Integration (network)": 60}:
        failed += 1
        print("FAIL C2 (#127): {name, timeout} sets that target's timeout and no other's")
    else:
        print("ok   C2 (#127): {name, timeout} sets that target's timeout and no other's")
    # #140: the job that runs a suite's command sets PHP and Composer up when the repository uses them.
    workflow = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".github", "workflows", "plugin-tests-wp.yml")
    try:
        text = open(workflow, encoding="utf-8").read()
        e2e = text[text.index("\n  e2e:\n"):]
        before_run = e2e[:e2e.index("- name: Run the suite")]
        ok = "shivammathur/setup-php" in before_run and "hashFiles('composer.json')" in before_run and "tools: composer:v2" in before_run
    except (OSError, ValueError):
        ok = False
    print(("ok   " if ok else "FAIL ") + "C1/C2 (#140): the E2E job sets PHP and Composer up, only with a composer.json, before it runs the suite")
    failed += 0 if ok else 1
    # C2 (#148): without requires-plugins-from nothing of it runs. Every step
    # of the suites that fetches, mounts or checks the required plugins is
    # guarded by the input, and so is the job that fetches them.
    guard = "inputs.requires-plugins-from != ''"
    try:
        jobs = text[text.index("\njobs:\n"):]
        fetch_job = jobs[jobs.index("\n  required-plugins:\n"):jobs.index("\n  integration:\n")]
        ok = guard in fetch_job.split("\n    if:", 1)[1].split("\n", 1)[0]
        for name in ("integration", "e2e"):
            job = jobs[jobs.index(f"\n  {name}:\n") + 1:]
            following = re.search(r"\n  [\w-]+:\n", job)
            job = job[:following.start()] if following else job
            code = "\n".join(line for line in job.split("\n") if not line.strip().startswith("#"))
            steps = code.split("\n      - ")[1:]
            ours = [s for s in steps if "required-plugins" in s or ".dx-central" in s]
            ifs = [[line for line in s.split("\n") if line.strip().startswith("if:")] for s in ours]
            ok = ok and len(ours) == 4 and all(i and guard in i[0] for i in ifs)
    except (ValueError, IndexError):
        ok = False
    print(("ok   " if ok else "FAIL ") + "C2 (#148): every required-plugins step of the suites, and its job, runs only with requires-plugins-from")
    failed += 0 if ok else 1
    if not failed:
        print("all tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--test"]:
        sys.exit(self_test())
    sys.exit(main())
