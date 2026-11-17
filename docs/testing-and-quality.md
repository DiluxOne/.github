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

A fix or a feature here comes with a pytest test under `tests/repro/` or `tests/workflows/`, run by the `python` way of `.github/review-policy.yml`. A script's own `--test` case cannot run at the base apart from the script's code, so a self-test case alone fails the check; keep adding them, beside the pytest. The release scenarios (`tests/release/`), fixtures, the reproduction's examples (`tests/examples/`) and the AI's evaluation sets (`evals/`) are never a test.

The scripts job of `pull-request.yml` runs every script's `--test` and the whole of `tests/` with pytest; `make pre-pr` runs what the pull request and the merge queue run.

## How the AI is measured

Every step of the engine that calls a model has an evaluation set (#735): real cases from the organisation's public repositories, replayed with the prompts, workflows and policy of the pull request, and scored against the step's last run. A change to the AI is then known to improve or worsen the flow before it merges, instead of being found out by a person and a paid run. One runner does it all, [`scripts/evals.py`](../scripts/evals.py), and one workflow gates it, [`evals.yml`](../.github/workflows/evals.yml) (it replaced `review-eval.yml`; [`scripts/review-eval.py`](../scripts/review-eval.py) is a wrapper over the runner's review step).

Each step's set is data: `evals/<step>/cases.json` (each case's `id`, `repo`, refs, `expect`, and the step's own fields) and `evals/<step>/baseline.json` (the score of the last run, with the cases it did not reach). A case is graded by a program wherever its outcome can be checked; a model judges only where the outcome is words, with the case's `rubric`.

| Step | The paths that run its set | A case | It passes when |
| --- | --- | --- | --- |
| `triage` | `.github/workflows/issue-triage.yml`, `scripts/triage-brief.sh` (the Classify prompt, `triage-brief.sh prompt classify`) | an issue with dilux-bot's triage record, the issues open then, the commit then | the classifier, on the public brief alone, gives the record's `category`, `duplicate_of` and `exists_in_pro` |
| `repro` | `.github/workflows/issue-repro.yml`, `scripts/repro-ways.py` (the "Write the test" prompts, `repro-ways.py prompt`) | a `bugfix-reproduced` issue, the test that reproduced it, its `base` | the test the agent writes fails at the base on an assertion (`reproduced`, as the "Test first" check reads it), through the same sandboxes |
| `spec` | `.github/workflows/autopilot.yml`, `scripts/autopilot.py` (`autopilot.py prompt spec`) | an accepted issue whose merged pull request changed tests | the PRD and the Spec pass `issue-schema.py`, and `### Spec: files` names at least `min_recall` of the files the merged pull request changed |
| `autopilot` | `.github/workflows/autopilot.yml`, `scripts/autopilot.py` (`autopilot.py prompt work`) | the same kind of issue, with the merged pull request's `tests` | those tests pass on the tree the agent leaves |
| `review` | `review-profiles/**`, `kinds/*/review-profile.md`, `kinds/*/rules.yml`, `policy/review-policy.default.yml`, `scripts/review-brief.sh`, `scripts/local-review.sh`, `scripts/review-verify.py`, `scripts/review-count.py`, `.github/workflows/claude-review.yml` | a `flag` commit (a blocker or major the review raised, then fixed) or a `clean` one (no thread) | it raises a blocker or major on the flagged file again; it does not block the clean one |
| `reply` | `.github/workflows/review-reply.yml`, `scripts/autopilot.py` (`autopilot.py prompt reply`) | a review thread someone answered with a mention, then resolved, cut at the mention | the reply resolves it, and a model judging with the case's `rubric` finds no further change asked |

`policy/autonomy.yml` (the models and AI settings) runs every set, and `evals/<step>/**` runs its own. `evals.py steps` maps a pull request's files to the steps they run and `evals.py paths` prints the union, which is `evals.yml`'s `paths:` (a test holds them equal): a pull request that touches none of them runs no set, one that touches one step's runs that step alone, each as a check "AI evaluation (<step>)". The check fails when the score is worse than the baseline by more than one case (a model does not answer the same twice), when more cases could not be replayed than in the baseline by more than one, or when there is no baseline: no gate never passes quietly. The table of cases goes to the job summary, the results to an artifact for 30 days.

The prompts the sets measure are the ones that ship: each lives in a script the workflow calls (`triage-brief.sh prompt classify`, `repro-ways.py prompt`, `autopilot.py prompt spec|work|reply`), and a replay reads the step's `claude_args` (model, tools, turns, budget, schema) from its workflow. A case runs on its repository at its ref, with no GitHub token in the model's environment; each has a time limit, and so has each set: its job's 30 minutes for the autopilot's and 15 for every other, which `evals.py run` ends inside, leaving the cases it did not reach as not replayed. A fork's pull request never runs the sets (they hold the model's keys).

### Adding a case, and moving a baseline

- `evals.py collect <step> [N]` writes `evals/<step>/cases.json` from history: git for `repro`, `spec` and `autopilot` (reproduced issues and their tests; squashed pull requests that closed an issue and changed a test), the API for `triage`, `review` and `reply` (dilux-bot's triage records; the review's threads). Only public, non-archived repositories of `repos.yml` give cases. `evals.yml`'s collect job collects the triage's and the reply's with its own read-only token and no model, and leaves them as an artifact (`evals-collected`) to commit: it runs by hand with `collect`, and on a pull request from a branch of this repository while either cases file is missing.
- A case added by hand follows its step's shape (the table above, and the cases already in its file). It is reviewed like code, in a pull request a person merges.
- `evals.py baseline <step> FILE` writes the baseline from a run's results (the check's artifact): the review's only from a whole run, another step's from a run cut at its job's limit too, whose baseline records how many cases it did not reach (`unreplayed`) and holds the next run to as many. A change that should move a score writes it in the same pull request, visible in the diff.
- `evals.py run <step>` and `evals.py score <step> FILE` run and score a set by hand; `evals.py --test` checks the mapping and every grade, offline, in the scripts job.

A new step is one entry in `STEPS` of `scripts/evals.py` (its paths, its replay, its grade) and one folder under `evals/`.
