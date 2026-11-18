# Testing and quality

How a change proves what it does, in every DiluxOne repository. The rule is [test first](../rules/test-first.md): a change that alters behaviour starts with the test that shows it. It is enforced by the "Test first" check, and the review checks it too: the check proves the test fails before the change and passes after it; the review reads whether the test is the right one (it tests the cause, not the symptom, and what must not change).

## The "Test first" check

[`test-first.yml`](../.github/workflows/test-first.yml) runs on every pull request of every repository (from [`org-pull-request.yml`](../.github/workflows/org-pull-request.yml), the required workflow, and from this repository's own `pull-request.yml`). [`scripts/test-first.py`](../scripts/test-first.py) decides:

| The pull request | The check |
| --- | --- |
| `docs`, `style`, `ci`, `chore`, or any type but `fix` and `feat` | Passes, running nothing: "a `<type>` pull request alters no behaviour the check tests: no test is run". |
| `fix` or `feat` (with a `!` too) in a repository that declares no `test-first:` | Fails, saying how to declare it; the daily drift check lists the repository. |
| `fix` or `feat` that adds or changes no test | Fails: "A test that fails before the change is missing", with where its tests go. A release scenario, a fixture or an expected output is never a test. |
| A test that does not pass at the head | Fails, naming it. |
| `fix` whose tests all pass at the base, or only break there (an import error) | Fails: "The test does not show the bug", naming it. A fix's test fails on an assertion at the base. |
| `feat` whose tests all pass at the base | Fails as a missing test: the test tests nothing the feature adds. |
| A test that could not run (its setup failed, or it took longer than its way's `minutes`) | Fails as "could not run": no verdict never passes. |
| Otherwise | Passes: "Test first: `<test>` fails at the base and passes at the head". |

Each test it finds runs twice, at the base's tree with the head's test file in its own place, and at the head, through the reproduction's sandboxes ([`scripts/repro-sandbox.sh`](../scripts/repro-sandbox.sh) and [`scripts/repro-run.sh`](../scripts/repro-run.sh) `run-ref`, with `TEST_REF`): on GitHub's fresh runner, with no secret, no network for the test and a read-only token, so a fork's tests run as safely as a report's reproduction. The verdict, and each test's outcome at the base and at the head, go to the job summary. A pull request with more than 20 tests is asked to split.

## How a repository declares its tests

Where tests are and how they run is data: `test-first:` in its kind's pack (`kinds/<kind>/pack.yml`), then in `repos.yml` under its name, then in its own `.github/review-policy.yml`, each adding to the one before, read from the pull request's base so it cannot exempt itself.

```yaml
test-first:
  setup: [composer install --no-interaction --prefer-dist --no-progress]   # its dev tools, with the network, on the base's checkout, before any test is in place
  tests:
    - paths: ["tests/Unit/**/*Test.php"]   # a file under these is a test
      way: unit                            # run by this way of its `repro:`
  not-tests: ["tests/**/fixtures/**"]      # never a test, whatever `tests` says
```

Each `way` is a reproduction way of the same declaration's `repro:` ([`scripts/repro-ways.py`](../scripts/repro-ways.py)), so a kind says how it runs a test in one place, and the check reuses its sandbox, command, report and time limit. Every pack declares one; so does this repository.

## In this repository

A fix or a feature here comes with a pytest test under `tests/repro/` or `tests/workflows/`, run by the `python` way of `.github/review-policy.yml`. A script's own `--test` case cannot run at the base apart from the script's code, so a self-test case alone fails the check; keep adding them, beside the pytest. The release scenarios (`tests/release/`), fixtures, the reproduction's examples (`tests/examples/`) and the AI's evaluation sets (`evals/`, below) are never a test.

The scripts job of `pull-request.yml` runs every script's `--test` and the whole of `tests/` with pytest; `make pre-pr` runs what the pull request and the merge queue run.

## How the AI is measured

Every AI step of the flow has its evaluation set (#735), so a change to a step's AI is scored before it merges, not found out from the flow's failures. A set is data under `evals/<step>/`: `cases.json`, real cases from the organisation's public repositories (a private one's code would show in this public repository's logs), each with its `expect`ed outcome, and `baseline.json`, the score of the last whole run. One runner, [`scripts/evals.py`](../scripts/evals.py), replays each case with the step as the pull request has it (its own prompt and its workflow's arguments: what is measured is what ships) and grades it deterministically wherever a grade exists; a model judges only where none does, with its rubric in the case.

[`evals.yml`](../.github/workflows/evals.yml) runs on a pull request that changes a path that counts for a step, and by hand for one step. `evals.py steps` maps the changed files to steps; the workflow's `paths:` are the union of every step's (a test holds them equal), so a pull request that touches none runs no set, and one that touches one step's paths runs that step alone, as the check "AI evaluation (<step>)". Each case is replayed in a job of its own (`evals.py matrix`, `evals.py run <step> <case>`), with its step's time for one case, and a job per step merges their results (`evals.py merge`) and scores them. A step's set fails the check when its score is worse than its baseline by more than one case (a model does not answer the same twice). A case left not replayed (its job ran out of time, or failed) fails the check too, by its name, as the runner's failure and not the step's score (the review keeps its slack of one, as before). Paid: each case is one model run (an autopilot case, a whole work round), so it runs only from a branch of this repository, never a fork's.

What counts for each step, beside `policy/autonomy.yml` (the model and AI settings, which count for all six) and its own set, `evals/<step>/**`:

| Step | Its paths | The grade | Where its cases come from |
| --- | --- | --- | --- |
| `triage` | `.github/workflows/issue-triage.yml`, `scripts/triage-brief.sh` | The verdict's `category`, `duplicate_of` and `exists_in_pro` equal the case's record. | _Its own issue: the cases come from GitHub (dilux-bot's triage records)._ |
| `repro` | `.github/workflows/issue-repro.yml`, `scripts/repro-ways.py`, `scripts/repro-brief.sh` | The test the step writes fails at the case's base on an assertion (`reproduced`), run as the "Test first" check runs it. | `collect`: the reproduced bugs (`the bug reproduced from #N`, with `tests/repro/test_issue_N.py`), at the commit before the fix. |
| `spec` | `.github/workflows/autopilot.yml`, `scripts/autopilot.py` | The PRD and the Spec pass the issue schema (G3), and `### Spec: files` names at least half of the files the merged pull request changed (tests and the changelog aside). | `collect`: the accepted issues whose merged pull request changed tests (at most 20 files, never a revert), at its parent. |
| `autopilot` | `.github/workflows/autopilot.yml`, `scripts/autopilot.py` | The merged pull request's tests pass on the tree the step leaves, through the same sandboxes. | `collect`: the same issues; the case's tests are the merged pull request's. |
| `review` | `review-profiles/**`, `kinds/*/review-profile.md`, `kinds/*/rules.yml`, `policy/review-policy.default.yml`, `scripts/review-brief.sh`, `scripts/local-review.sh`, `scripts/review-verify.py`, `scripts/review-count.py`, `.github/workflows/claude-review.yml` | `flag`: a known bug is found on its file again; `clean`: the pull request is not blocked (#234, unchanged). | `collect`: the review's threads on the public repositories' merged pull requests (GitHub, `GH_TOKEN`). |
| `reply` | `.github/workflows/review-reply.yml` | A model judges, with the case's `rubric` (the only judged step: the outcome is words): the thread is resolved, and no further change is asked. | _Its own issue: the cases come from GitHub (review threads a mention answered, then resolved)._ |

The steps with no set yet (`triage`, `reply`) are in the runner's table, with their paths and grades; `evals.py steps` lists only a step with a set, so a change to them runs nothing until their set lands.

**Adding a case.** Run `evals.py collect <step> [N]` (N cases, 6 by default; the review's, N of each kind), read what it wrote to `evals/<step>/cases.json`, keep the real cases that say what the step must do, and commit them in a pull request a person merges, like any change to `evals/` (high risk). A case written by hand has the same shape: `id`, `repo`, the refs (`base`, and `merge` or `head`), the step's own fields (`issue`, `test`, `type` and `files`, `tests`, `pr`, `thread`), and `expect`.

**The baseline.** A new set's `baseline.json` is `{"pending": ...}` until its first whole run. A step with no baseline (missing, or pending) is not gated: its check passes with a warning, and its summary and log carry the whole run's results, in the format `evals.py baseline` reads, between the lines `--- baseline <step> ---` and `--- end ---`. Saved as FILE, `evals.py baseline <step> FILE` writes the baseline (only from a whole run, every case replayed), in a commit a person reviews; the workflow never pushes it. A change that should move a score does the same from its run's results (the artifact `evals-<step>`). `evals.py run <step>` and `evals.py score <step> FILE` do by hand what the workflow does; `evals.py --test` checks every grade, the mapping and the review's gate offline, in the scripts job. `scripts/review-eval.py` still answers its old commands, over `evals.py ... review`.
