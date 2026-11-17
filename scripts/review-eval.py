#!/usr/bin/env python3
"""The review's evaluation set (#234), now one step of scripts/evals.py
(#735), which holds its cases' collection and its grading unchanged: a
`flag` case is a commit where the review raised a blocker or major that was
then fixed, which it must raise again on that file; a `clean` one, the last
commit of a merged pull request it left no thread on, which it must not
block. evals.yml runs it, and fails a change to the review whose score is
worse than evals/review/baseline.json by more than one case on either side.

This wrapper keeps the commands as they were documented:

  review-eval.py collect [N]   evals.py collect review [N]
  review-eval.py run           evals.py run review
  review-eval.py score FILE    evals.py score review FILE
  review-eval.py baseline FILE evals.py baseline review FILE
  review-eval.py --test        evals.py --test
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("evals", os.path.join(HERE, "evals.py"))
evals = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(evals)

# The review's grading, where it always was.
cases_from, pick, verdict, score, worse, table, SLACK = (evals.cases_from, evals.pick, evals.verdict, evals.score, evals.worse,
                                                         evals.table, evals.SLACK)


def main(argv):
    if argv == ["--test"]:
        return evals.self_test()
    if argv[:1] == ["collect"] and len(argv) <= 2:
        return evals.main(["collect", "review", *argv[1:]])
    if argv == ["run"]:
        return evals.main(["run", "review"])
    if argv[:1] in (["score"], ["baseline"]) and len(argv) == 2:
        return evals.main([argv[0], "review", argv[1]])
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
