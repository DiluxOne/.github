# tests/repro/

One pytest test per bug, `test_issue_<n>.py`, written by the reproduction (`.github/review-policy.yml`, `repro.ways`) or by the fix that closed issue `<n>`. Each one belongs to a fix that was merged: its issue is closed, so the reproduction lane never runs it again, and every pull request runs them all as regression tests (`.github/workflows/pull-request.yml`, its `tests/ (pytest)` step).

Since #841 the `workflow` way declares `runs-step: true`: a reproduction of a workflow's bug runs the step's script with stubs on PATH and asserts on what it did, and a test that runs no process is broken, "the test runs no step" (`scripts/repro-ways.py`, `runs_step`). These tests, written before it, only read a workflow's or a script's file and assert on its text. None is open, so they are kept as they are, as regression tests; the way would no longer take any of them as a reproduction:

415, 427, 487, 506, 524, 540, 549, 556, 575, 577, 585, 607, 610, 615, 633, 641, 696, 720, 807.
