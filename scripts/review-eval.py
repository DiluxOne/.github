#!/usr/bin/env python3
"""The review's evaluation set (#234), now one step of scripts/evals.py (#735).

Its cases (evals/review/cases.json), baseline and slack of one case are
unchanged, and so is its grading (`verdict`, `score`, `worse`, which moved
to evals.py); evals.yml runs it with the other steps. This wrapper keeps
the commands people know:

  review-eval.py collect [N]    evals.py collect review [N]
  review-eval.py run            evals.py run review
  review-eval.py score FILE     evals.py score review FILE
  review-eval.py baseline FILE  evals.py baseline review FILE
  review-eval.py --test         evals.py --test
"""
import os
import subprocess
import sys

EVALS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evals.py")


def args_for(argv):
    """evals.py's arguments for review-eval.py's, or None."""
    if argv == ["--test"]:
        return ["--test"]
    if argv[:1] == ["collect"] and len(argv) <= 2:
        return ["collect", "review", *argv[1:]]
    if argv == ["run"]:
        return ["run", "review"]
    if argv[:1] in (["score"], ["baseline"]) and len(argv) == 2:
        return [argv[0], "review", argv[1]]
    return None


def main(argv):
    args = args_for(argv)
    if args is None:
        print(__doc__, file=sys.stderr)
        return 64
    if args == ["--test"]:
        want = {("collect",): ["collect", "review"], ("collect", "4"): ["collect", "review", "4"], ("run",): ["run", "review"],
                ("score", "f"): ["score", "review", "f"], ("baseline", "f"): ["baseline", "review", "f"], ("score",): None, ("x",): None}
        bad = [k for k, v in want.items() if args_for(list(k)) != v]
        print("ok   the verbs map to evals.py's review" if not bad else f"FAIL the verbs: {bad}")
        if bad:
            return 1
    return subprocess.run([sys.executable, EVALS, *args]).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
