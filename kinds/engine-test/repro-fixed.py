#!/usr/bin/env python3
"""The test repository's fixed reproduction (#707, kinds/engine-test/pack.yml
`repro`): no model writes it, as no model writes the test repository's
change. scripts/repro-ways.py fixed copies it in place of the writer's test,
`{n}` the issue's number and `{scenario}` the release scenario of its
`dx-scenario` mark. It fails while scenarios/{scenario}/greeting.md says
"helo" (the file `bug-reproduced` lands on main first) and passes otherwise
(`bug-not-reproduced` lands none), and writes the JUnit report the way's
`junit` names, which gives the verdict (scripts/repro-run.sh)."""
import os
import re
import sys
from xml.sax.saxutils import quoteattr

GREETING = "scenarios/{scenario}/greeting.md"
REPORT = "build/repro-{n}.xml"


def main():
    try:
        with open(GREETING, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        text = ""
    failure = ""
    if re.search(r"\bhelo\b", text):
        failure = f"<failure message={quoteattr('AssertionError: ' + GREETING + ' says helo, not hello')}/>"
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write(f'<testsuites><testsuite name="repro" tests="1" failures="{1 if failure else 0}">'
                 f'<testcase classname={quoteattr(os.path.basename(__file__))} name="test_the_greeting_says_hello">{failure}</testcase>'
                 "</testsuite></testsuites>\n")
    print(f"{GREETING}: {'says helo' if failure else 'does not say helo'}")
    return 1 if failure else 0


if __name__ == "__main__":
    sys.exit(main())
