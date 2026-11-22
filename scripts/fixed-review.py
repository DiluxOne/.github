#!/usr/bin/env python3
"""A scenario's fixed review in the test repository (#943).

The autopilot there already writes a fixed change that calls no model
(kinds/engine-test/pack.yml `autopilot: fixed-change`), so the release
scenarios try the flow, never the model. Most scenarios do not test the
review either: on their pull requests the review writes its answer without
calling the model. A scenario that tests the review, or reads its verdict,
says `review: model` in tests/release/scenarios.yml and keeps the model's.

  fixed-review.py answer     print `hit=true` and `answer=<json>` (the
        review's answer, in the schema claude-review.yml asks the model for)
        when the pull request is a scenario's in the test repository and its
        scenario does not keep the model's review; else `hit=false`.
        Environment: FIXED (autopilot.py fixed: the fixed change's file,
        empty outside the test repository), REPO, PR, TITLE, FLOOR (the
        policy floor: low, medium or high), SCENARIOS (tests/release/
        scenarios.yml of the engine's checkout), SHOWN (the brief's
        shown-files.txt: the answer examines each of its files, #953),
        GH_TOKEN.
  fixed-review.py --test     self-test

A read that fails gives `hit=false`: the model reviews, as before.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCENARIO = re.compile(r"^\s*<!--\s*dx-scenario:\s*([a-z0-9-]+)\s*-->", re.M)
CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.I)
TYPES = ("feat", "fix", "perf", "refactor", "style", "docs", "test", "ci", "build", "chore", "revert")
CRITERION = re.compile(r"^\s*-\s*(C\d+)\s*:", re.M)


def scenario_of(body):
    """The release scenario that opened an issue: its `dx-scenario` mark,
    or "". Pure."""
    m = SCENARIO.search(body or "")
    return m.group(1) if m else ""


TITLE_SCENARIO = re.compile(r"\[([a-z0-9-]+)\]\s*$")


def title_scenario(title):
    """The scenario a scenario's pull request names at the end of its title
    (`feat: a greeting, claimed [claim-and-release]`), or "". Pure."""
    m = TITLE_SCENARIO.search(title or "")
    return m.group(1) if m else ""


def closes(body):
    """The issue numbers a pull request's body closes, in order. Pure."""
    seen = []
    for n in CLOSES.findall(body or ""):
        if int(n) not in seen:
            seen.append(int(n))
    return seen


def keeps_model(scenarios, sid):
    """Whether scenario `sid` keeps the model's review (`review: model`), or
    is not known (then the model reviews, as before). Pure."""
    for s in scenarios or []:
        if s.get("id") == sid:
            return s.get("review") == "model"
    return True


def title_type(title):
    """The review's type from a Conventional Commit title; chore when it has
    none. Pure."""
    m = re.match(r"^([a-z]+)(\([^)]*\))?(!)?:", title or "")
    if not m:
        return "chore"
    if m.group(3):
        return "breaking"
    return m.group(1) if m.group(1) in TYPES else "chore"


def criteria(issue_body):
    """The PRD's criteria IDs, in order. Pure."""
    text = issue_body or ""
    at = text.find("### Acceptance criteria")
    if at < 0:
        return []
    end = text.find("\n### ", at + 1)
    return CRITERION.findall(text[at:end if end > 0 else None])


def answer(sid, title, floor, ids, shown=()):
    """The fixed review's answer, in the schema the model answers in, with
    an `examined` entry for each of the brief's shown files (#953). Pure."""
    risk = floor if floor in ("low", "medium", "high") else "high"
    return {
        "risk": risk, "complexity": "low", "blocking": False, "type": title_type(title),
        "description_matches": True,
        "summary": f"Fixed review (#943): the release scenario `{sid}` does not test the review, so no model reviewed this pull request in the test repository. Risk is the policy floor.",
        "findings": [], "lessons": [], "resolved_threads": [],
        "criteria": [{"id": c, "met": True, "evidence": f"fixed review of scenario {sid} (#943)"} for c in ids],
        "examined": [{"file": f, "checked": "fixed review (#943)"} for f in shown],
    }


def shown_files(path):
    """The brief's shown files, one path per line (#953). Raises when the
    list cannot be read, so the model reviews."""
    with open(path, encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip()]


def gh_json(*args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200])
    return json.loads(out.stdout or "null")


def decide(env, read=gh_json, load=None):
    """(hit, answer) for the pull request the environment names."""
    if not env.get("FIXED"):
        return False, None
    try:
        import yaml
        scenarios = (load or (lambda p: yaml.safe_load(open(p, encoding="utf-8"))))(env["SCENARIOS"]).get("scenarios") or []
        repo, pr = env["REPO"], env["PR"]
        body = read("api", f"repos/{repo}/pulls/{pr}", "--jq", "{body: .body}")["body"]
        for n in closes(body):
            issue = read("api", f"repos/{repo}/issues/{n}", "--jq", "{body: .body}")["body"]
            sid = scenario_of(issue) or title_scenario(env.get("TITLE", ""))
            if not sid:
                continue
            if keeps_model(scenarios, sid):
                return False, None
            return True, answer(sid, env.get("TITLE", ""), env.get("FLOOR", ""), criteria(issue), shown_files(env["SHOWN"]))
    except Exception as e:  # a failed read: the model reviews, as before
        print(f"::notice::fixed review: {str(e)[:200]}; the model reviews", file=sys.stderr)
    return False, None


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

    issue = "<!-- dx-scenario: claim-and-release -->\n### Problem\n\nx\n\n### Acceptance criteria\n\n- C1: Given a, when b, then c.\n- C2: Given d, when e, then f.\n\n### Criticality\n\nNormal\n"
    scen = {"scenarios": [{"id": "claim-and-release"}, {"id": "low-risk-merges", "review": "model"}]}
    reads = {"pulls/7": {"body": "Closes #5"}, "issues/5": {"body": issue}}

    def read(*args):
        for k, v in reads.items():
            if args[1].endswith(k):
                return v
        raise RuntimeError("404")

    import tempfile
    shown = os.path.join(tempfile.mkdtemp(), "shown-files.txt")
    with open(shown, "w", encoding="utf-8") as fh:
        fh.write("a.py\n\nlib/b.py\n")
    env = {"FIXED": "scenarios/{scenario}/{n}.test.md", "REPO": "o/t", "PR": "7", "TITLE": "feat: a greeting", "FLOOR": "medium", "SCENARIOS": "x", "SHOWN": shown}
    hit, ans = decide(env, read, lambda p: scen)
    check("it examines each of the brief's shown files (#953)", [e["file"] for e in ans["examined"]], ["a.py", "lib/b.py"])
    check("an unreadable list of shown files: the model", decide(dict(env, SHOWN=shown + ".none"), read, lambda p: scen), (False, None))
    check("no list of shown files: the model", decide({k: v for k, v in env.items() if k != "SHOWN"}, read, lambda p: scen), (False, None))
    check("a scenario that does not test the review: fixed, no model", hit, True)
    check("its risk is the floor, not blocking, matching", (ans["risk"], ans["blocking"], ans["description_matches"], ans["type"]), ("medium", False, True, "feat"))
    check("its criteria are the PRD's, met", [c["id"] for c in ans["criteria"] if c["met"]], ["C1", "C2"])
    reads["issues/5"] = {"body": issue.replace("claim-and-release", "low-risk-merges")}
    check("a scenario that keeps the model's review: the model", decide(env, read, lambda p: scen), (False, None))
    reads["issues/5"] = {"body": issue.replace("claim-and-release", "not-listed")}
    check("a scenario not listed: the model", decide(env, read, lambda p: scen), (False, None))
    reads["issues/5"] = {"body": "no mark"}
    check("no scenario mark: the model", decide(env, read, lambda p: scen), (False, None))
    hit, ans = decide(dict(env, TITLE="feat: a greeting, claimed [claim-and-release]"), read, lambda p: scen)
    check("no mark, the scenario in the title: fixed", (hit, ans and ans["criteria"]), (True, []))
    check("no mark, a kept scenario in the title: the model", decide(dict(env, TITLE="docs: x [low-risk-merges]"), read, lambda p: scen), (False, None))
    check("outside the test repository: the model", decide(dict(env, FIXED=""), read, lambda p: scen), (False, None))
    reads.clear()
    check("a failed read: the model", decide(env, read, lambda p: scen), (False, None))
    check("type: breaking", title_type("feat!: x"), "breaking")
    check("type: none is chore", title_type("a greeting"), "chore")
    check("closes: once each", closes("Closes #3, fixes #3 and resolves #4"), [3, 4])
    check("an unknown floor is high", answer("s", "x", "", [])["risk"], "high")
    # The answer fits the schema claude-review.yml gives the model.
    wf = open(os.path.join(HERE, "..", ".github", "workflows", "claude-review.yml"), encoding="utf-8").read()
    schema = json.loads(re.search(r"--json-schema '(\{\"type\":\"object\",\"additionalProperties\":false,\"required\":\[\"risk\".*?)'\n", wf).group(1))
    a = answer("s", "fix: y", "low", ["C1"])
    check("the answer has every required key and no other", (set(schema["required"]) <= set(a), set(a) <= set(schema["properties"])), (True, True))
    if fails:
        print("\n".join(fails))
        return 1
    print("all tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
