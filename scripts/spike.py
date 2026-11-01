#!/usr/bin/env python3
"""A spike's answer, as the comment on its issue (#193).

A spike is a step of the triage, not a type of work: when an issue cannot be
classified, or something must be found out before deciding, a person who
can write to the repository comments `/spike` (#564) and an agent investigates, read-only and for a capped time
(issue-triage.yml, job `spike`). It ends in one of three ways, and a person
decides what follows:

  do       it is a bug, a minor change or a feature: say which, and the
           issue follows that path once a maintainer accepts it
  clarify  something is missing: what, and from whom
  discard  it is not worth doing: why

  spike.py comment   the agent's structured answer (JSON) on stdin, the
                     comment on stdout; only the schema's values are used
  spike.py --test    self-test
"""
import json
import sys

OUTCOMES = {"do": "Do it", "clarify": "Clarify first", "discard": "Discard"}
TYPES = {"bug": "a bug", "minor": "a minor change", "feature": "a feature", "none": ""}
MARK = "<!-- dx-spike -->"
AI = "🤖 AI-generated · Claude (Anthropic), a read-only spike"


def comment(answer):
    """The comment, from the agent's answer; None when it is not one."""
    if not isinstance(answer, dict) or answer.get("outcome") not in OUTCOMES:
        return None
    kind = TYPES.get(answer.get("type") or "none", "")
    head = f"**Spike: {OUTCOMES[answer['outcome']]}**" + (f", as {kind}" if answer["outcome"] == "do" and kind else "")
    # Shaped by an issue anyone wrote: no @mention notifies anyone from here.
    quiet = lambda t: str(t or "").strip().replace("@", "@\u200b")
    findings = quiet(answer.get("findings"))[:3000]
    nxt = quiet(answer.get("next"))[:800]
    body = [MARK, head, "", findings or "_No findings._"]
    if nxt:
        body += ["", f"**Next:** {nxt}"]
    body += ["", "A maintainer decides what follows: accepting the issue (with its PRD), asking, or closing it. The spike changed nothing.", "", AI]
    return "\n".join(body)


def self_test():
    failed = 0

    def check(name, got, want):
        nonlocal failed
        print(("ok   " if got == want else "FAIL ") + name + ("" if got == want else f": got {got!r}, want {want!r}"))
        failed |= got != want

    c = comment({"outcome": "do", "type": "bug", "findings": "The cache key ignores the locale.", "next": "Accept it as a Bug."})
    check("do: says it is a bug, with its findings and next step", (c.startswith(MARK + "\n**Spike: Do it**, as a bug"), "ignores the locale" in c, "**Next:** Accept it" in c), (True, True, True))
    check("clarify: no type in the heading", comment({"outcome": "clarify", "type": "feature", "findings": "x"}).split("\n")[1], "**Spike: Clarify first**")
    check("discard", "**Spike: Discard**" in comment({"outcome": "discard", "findings": "x"}), True)
    check("an answer outside the schema is none", (comment({"outcome": "merge it"}), comment(None), comment("x")), (None, None, None))
    check("never says it decided", "A maintainer decides what follows" in c, True)
    check("an @mention notifies no one", "@\u200bsomeone" in comment({"outcome": "do", "findings": "ask @someone"}), True)
    import subprocess as _sp
    import os as _os
    cli = lambda text: _sp.run([sys.executable, _os.path.abspath(__file__), "comment"], input=text, capture_output=True, text=True).returncode
    check("cli: an answer, an empty one, and one that is not JSON", (cli('{"outcome": "do", "findings": "x"}'), cli(""), cli("not json")), (0, 1, 1))
    check("long findings are cut", len(comment({"outcome": "do", "findings": "a" * 9000})) < 4000, True)
    print("all tests passed" if not failed else "some tests failed")
    return 1 if failed else 0


def main(argv):
    if argv == ["--test"]:
        return self_test()
    if argv == ["comment"]:
        try:
            answer = json.loads(sys.stdin.read() or "null")
        except ValueError:
            answer = None
        text = comment(answer)
        if text is None:
            print("The spike gave no answer the schema allows.", file=sys.stderr)
            return 1
        print(text)
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
