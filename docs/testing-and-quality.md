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
| `feat` whose tests all pass at the base, or only break there (an import error, a missing file) | Fails as a missing test: the test tests nothing the feature adds. A feature's test asserts on what it runs (a script's exit code and output, a function's result), so it fails an assertion at the base, the same as a fix's (#845). |
| A test that could not run (its setup failed, or it took longer than its way's `minutes`) | Fails as "could not run": no verdict never passes. |
| Otherwise | Passes: "Test first: `<test>` fails at the base and passes at the head". |

The check a ruleset requires is the `verdict` job, "Test first" (#842): it reports on every pull request, green when the tests passed or there was nothing to run, red when the plan ("Test first (plan)") or the tests failed, were cancelled, or did not run while the plan said they would.

Each test it finds runs twice, at the base's tree with the head's test file in its own place, and at the head, through the reproduction's sandboxes ([`scripts/repro-sandbox.sh`](../scripts/repro-sandbox.sh) and [`scripts/repro-run.sh`](../scripts/repro-run.sh) `run-ref`, with `TEST_REF`): on GitHub's fresh runner, with no secret, no network for the test and a read-only token, so a fork's tests run as safely as a report's reproduction. The verdict, and each test's outcome at the base and at the head, go to the job summary. A pull request with more than 20 tests is asked to split.

## How a repository declares its tests

Where tests are and how they run is data: `test-first:` in its kind's pack (`kinds/<kind>/pack.yml`), then in `repos.yml` under its name, then in its own `.github/review-policy.yml`, each adding to the one before, read from the pull request's base so it cannot exempt itself.

```yaml
test-first:
  setup: [composer install --no-interaction --prefer-dist --no-progress]   # its dev tools, with the network, on the base's checkout, before any test is in place
  tests:
    - paths: ["tests/Unit/**/*Test.php"]   # a file under these is a test
      way: unit                            # run by this way of its `repro:`
      check: "tests / Unit"                # optional (#842): the required check that runs them, which gate G7 waits on
  not-tests: ["tests/**/fixtures/**"]      # never a test, whatever `tests` says
```

Each `way` is a reproduction way of the same declaration's `repro:` ([`scripts/repro-ways.py`](../scripts/repro-ways.py)), so a kind says how it runs a test in one place, and the check reuses its sandbox, command, report and time limit. Every pack declares one; so does this repository. `check:` (#842) names the required check that runs an entry's tests: gate G7 counts an autopilot pull request's criterion met only once that check concluded success at the head; an entry with none is "test-first / Test first"'s, for a `fix` or `feat` pull request only.

## In this repository

A fix or a feature here comes with a pytest test under `tests/repro/` or `tests/workflows/`, run by the `python` way of `.github/review-policy.yml`, and by "Scripts (self-tests)" (its `check:`). The ruleset "own checks" requires that check and "test-first / Test first" on main (repos.yml `required-checks`, written by `sync-repos.py own-checks`, #842): a pull request whose tests are red cannot merge. A script's own `--test` case cannot run at the base apart from the script's code, so a self-test case alone fails the check; keep adding them, beside the pytest. A test never cuts a workflow's text between two literals (`text[text.index("..."):text.index("...")]`, `text.split("...")[1]`): it breaks on a rewording and passes when the step breaks. It finds the step through YAML and runs its `run:` with stubs on PATH (`tests/workflows/steps.py`), or calls the script under `scripts/` that holds the logic; `scripts/literal-slices.py` fails the scripts job on a new one, naming the test, and its list of the files that did before (#845), each with its number of slices, only shrinks: a new slice in a listed file fails as well. The release scenarios (`tests/release/`), fixtures, the reproduction's examples (`tests/examples/`) and the review's evaluation set (`evals/`) are never a test.

The scripts job of `pull-request.yml` runs every script's `--test` and the whole of `tests/` with pytest; `make pre-pr` runs what the pull request and the merge queue run.
