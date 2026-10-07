#!/usr/bin/env python3
"""Whether a public text repeats a confidential one.

The issue triage reads a paid add-on's private roadmap to classify a request,
and its reply is public. The prompt tells the model never to quote it; this
is the check that does not depend on the model obeying. A reply that shares
a run of RUN words (6 by default, case and punctuation ignored) with the
confidential file is refused, and the workflow posts a neutral reply instead.
A false positive costs a plainer reply; a miss would publish the reasoning.

  confidential.py <confidential-file> <public-file>   exit 1 when it repeats it
  confidential.py --test                              self-test
"""
import os
import re
import sys

RUN = int(os.environ.get("CONFIDENTIAL_RUN", "6"))


def words(text):
    return re.findall(r"\w+", text.lower())


def runs(text, n=RUN):
    w = words(text)
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def repeats(confidential, public, n=RUN):
    """The first run of n words the public text shares with the confidential one, or None."""
    secret = runs(confidential, n)
    for run in runs(public, n):
        if run in secret:
            return " ".join(run)
    return None


def self_test():
    roadmap = "| People | Author labels | @mentions of people and comments, follow a person, online now |\nWhen in doubt a feature starts in Pro: giving it away later is easy."
    cases = [
        ("a neutral reply passes", "Thanks! This is not planned for the free plugin.", False),
        ("a quoted row is caught", "Pro has @mentions of people and comments, follow a person.", True),
        ("case and punctuation do not hide it", "WHEN IN DOUBT, a feature starts in pro!", True),
        ("five shared words are not a quote", "giving it away later is fine", False),
        ("an empty reply passes", "", False),
    ]
    failed = 0
    for name, reply, want in cases:
        got = repeats(roadmap, reply) is not None
        print(("ok   " if got == want else "FAIL ") + name)
        failed += got != want
    if not failed:
        print("all tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--test"]:
        sys.exit(self_test())
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    with open(sys.argv[1], encoding="utf-8") as fh:
        confidential = fh.read()
    with open(sys.argv[2], encoding="utf-8") as fh:
        public = fh.read()
    # Never print the run itself: a workflow's log is public on a public
    # repository.
    if repeats(confidential, public):
        print("The text repeats the confidential file.")
        sys.exit(1)
    print("The text repeats nothing of the confidential file.")
