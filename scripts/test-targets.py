#!/usr/bin/env python3
"""The jobs plugin-tests-wp.yml runs: one per integration target, one per E2E suite.

Reads the workflow's inputs from the environment and writes two JSON
matrices to $GITHUB_OUTPUT, `integration` and `e2e`, each a list of
entries whose `check` is the job's name, the status check a ruleset
requires. Names are stable: they come from the inputs, never from the
order or the run.

  INTEGRATION          true | false   run the integration suite at all
  MULTISITE            true | false   the old switch: the one target is the network
  INTEGRATION_TARGETS  JSON list of "single" and/or "network"; empty: the old
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


def integration(env):
    enabled = as_bool(env.get("INTEGRATION"))
    targets = as_list("integration-targets", env.get("INTEGRATION_TARGETS"))
    if targets is None:
        site = "network" if as_bool(env.get("MULTISITE")) else "single"
        return [{"check": LEGACY_INTEGRATION, "site": site, "enabled": enabled}]
    if not targets:
        raise InputError("integration-targets is empty: leave it out, or turn integration off.")
    out = []
    for target in targets:
        if target not in SITES:
            raise InputError(f"integration-targets: '{target}' is not single or network.")
        if any(t["site"] == target for t in out):
            raise InputError(f"integration-targets: '{target}' is listed twice.")
        out.append({"check": "Integration (single site)" if target == "single" else "Integration (network)", "site": target, "enabled": enabled})
    return out


def e2e(env):
    enabled = as_bool(env.get("E2E"))
    suites = as_list("e2e-suites", env.get("E2E_SUITES"))
    if suites is None:
        return [{"check": LEGACY_E2E, "name": "playwright", "site": "single", "run": "npx playwright test", "results": "build/e2e-results", "artifact": "playwright-results", "timeout": 25, "enabled": enabled}]
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
        timeout = suite.get("timeout", 25)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or not 5 <= timeout <= 120:
            raise InputError(f"e2e-suites, '{name}': timeout is whole minutes, from 5 to 120.")
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
        ("a timeout out of range", {"E2E_SUITES": '[{"name":"a","site":"single","run":"x","timeout":600}]'}, "timeout"),
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
    if not failed:
        print("all tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--test"]:
        sys.exit(self_test())
    sys.exit(main())
