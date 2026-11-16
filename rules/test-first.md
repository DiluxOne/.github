---
id: test-first
level: mandatory
applies_to: {all: true}
enforced_by: [review, {check: test-first}]
---
# Test first

A change that alters behaviour starts with the test that shows it: a bug fix with a test that fails on the code as it was and passes with the fix, a feature with a test for each acceptance criterion of its issue. The test is written before the code it proves, and it lands in the same pull request.

A fix also carries the test of what must not change, when the fix touches behaviour that other code relies on.

A change that alters no behaviour (text, docs, a refactor that keeps every test passing unchanged) needs no new test, and says so in its pull request.

How it is held: it is enforced by the "Test first" check, and the review checks it too. The check ([`test-first.yml`](../.github/workflows/test-first.yml), [`scripts/test-first.py`](../scripts/test-first.py)) runs on every pull request: a `fix` or `feat` pull request must add or change a test under the paths its repository declares (`test-first:`, its kind's pack), which fails at the base and passes at the head; a release scenario, a fixture or an expected output is never that test. The review reads whether the test proves the cause and not the symptom, and the test of what must not change. What each message means: [docs/testing-and-quality.md](../docs/testing-and-quality.md).

Why: the test is the specification an agent can verify on its own, and what lets a change merge without a person reading the code. A problem a review finds that a test could have caught comes with that test, in the same pull request.
