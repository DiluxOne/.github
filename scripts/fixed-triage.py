#!/usr/bin/env python3
"""A scenario's fixed triage in the test repository (#946).

As the autopilot and the review there (kinds/engine-test/pack.yml,
scripts/fixed-review.py), the triage of an issue a release scenario opened
answers without the model: a `fix` title is an unconfirmed bug of the logic
layer (its fixed reproduction decides it, #707), anything else an
enhancement. That is what the model answered on those issues; the scenarios
try the flow, never the model. A scenario that tests the triage says
`triage: model` in tests/release/scenarios.yml and keeps the model's.

  fixed-triage.py answer     print `hit=true` and `answer=<json>` (the
        triage's answer, in its full schema) when the issue is a scenario's in
        the test repository and its scenario does not keep the model's;
        else `hit=false`. Environment: FIXED (autopilot.py fixed: empty
        outside the test repository), TITLE, BODY, SCENARIOS (tests/release/
        scenarios.yml of the engine's checkout), REPLY (the canned reply,
        scripts/triage-reply.sh).
  fixed-triage.py --test     self-test

Anything it cannot read gives `hit=false`: the model triages, as before.
"""
import json
import os
import re
import sys

SCENARIO = re.compile(r"^\s*<!--\s*dx-scenario:\s*([a-z0-9-]+)\s*-->", re.M)


def scenario_of(body):
    m = SCENARIO.search(body or "")
    return m.group(1) if m else ""


def keeps_model(scenarios, sid):
    """Whether scenario `sid` keeps the model's triage (`triage: model`), or
    is not known (then the model triages, as before). Pure."""
    for s in scenarios or []:
        if s.get("id") == sid:
            return s.get("triage") == "model"
    return True


def answer(sid, title, reply):
    """The fixed triage's answer, in the triage's full schema. Pure."""
    bug = bool(re.match(r"^fix(\([^)]*\))?!?:", title or ""))
    out = {"category": "bug_unconfirmed" if bug else "enhancement", "language": "en",
           "reply": reply or "Thanks! A maintainer will take a look.",
           "summary": f"Fixed triage (#946) of the release scenario {sid}: no model."}
    if bug:
        out["layer"] = "logic"
    return out


def decide(env, load=None):
    if not env.get("FIXED"):
        return False, None
    sid = scenario_of(env.get("BODY", ""))
    if not sid:
        return False, None
    try:
        import yaml
        scenarios = (load or (lambda p: yaml.safe_load(open(p, encoding="utf-8"))))(env["SCENARIOS"]).get("scenarios") or []
    except Exception as e:  # unreadable: the model triages, as before
        print(f"::notice::fixed triage: {str(e)[:200]}; the model triages", file=sys.stderr)
        return False, None
    if keeps_model(scenarios, sid):
        return False, None
    return True, answer(sid, env.get("TITLE", ""), env.get("REPLY", ""))


def main(argv):
    if argv[:1] == ["--test"]:
        return test()
    if argv[:1] != ["answer"]:
        print(__doc__, file=sys.stderr)
        return 2
    hit, ans = decide(dict(os.environ))
    print(f"hit={'true' if hit else 'false'}")
    if hit:
        print("answer=" + json.dumps(ans, separators=(",", ":")))
    return 0


def test():
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append(f"{name}: got {got!r}, want {want!r}")
        else:
            print(f"ok   {name}")

    scen = {"scenarios": [{"id": "issue-complete"}, {"id": "bug-reproduced"}, {"id": "kept", "triage": "model"}]}
    env = {"FIXED": "scenarios/{scenario}/{n}.test.md", "SCENARIOS": "x", "REPLY": "Thanks!"}
    hit, ans = decide(dict(env, TITLE="feat: a greeting", BODY="<!-- dx-scenario: issue-complete -->\nx"), lambda p: scen)
    check("a feature's scenario: an enhancement, no model", (hit, ans["category"], "layer" in ans), (True, "enhancement", False))
    hit, ans = decide(dict(env, TITLE="fix: the greeting says helo", BODY="<!-- dx-scenario: bug-reproduced -->"), lambda p: scen)
    check("a bug's scenario: an unconfirmed bug of the logic layer", (hit, ans["category"], ans["layer"]), (True, "bug_unconfirmed", "logic"))
    check("a kept scenario: the model", decide(dict(env, TITLE="feat: x", BODY="<!-- dx-scenario: kept -->"), lambda p: scen), (False, None))
    check("an unknown scenario: the model", decide(dict(env, TITLE="feat: x", BODY="<!-- dx-scenario: other -->"), lambda p: scen), (False, None))
    check("no mark: the model", decide(dict(env, TITLE="feat: x", BODY="a person's issue"), lambda p: scen), (False, None))
    check("outside the test repository: the model", decide(dict(env, FIXED="", BODY="<!-- dx-scenario: issue-complete -->"), lambda p: scen), (False, None))

    def boom(p):
        raise OSError("no file")
    check("an unreadable scenarios file: the model", decide(dict(env, BODY="<!-- dx-scenario: issue-complete -->"), boom), (False, None))
    # The answer fits the triage's full schema (issue-triage.yml DX_FULL_SCHEMA).
    here = os.path.dirname(os.path.abspath(__file__))
    wf = open(os.path.join(here, "..", ".github", "workflows", "issue-triage.yml"), encoding="utf-8").read()
    schema = json.loads(re.search(r"DX_FULL_SCHEMA: '(.*?)'\n", wf).group(1))
    a = answer("s", "fix: y", "r")
    check("the answer has every required key and no other", (set(schema["required"]) <= set(a), set(a) <= set(schema["properties"])), (True, True))
    if fails:
        print("\n".join(fails))
        return 1
    print("all tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
