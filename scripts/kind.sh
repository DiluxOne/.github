#!/usr/bin/env bash
# The kind of project a check runs for, and its settings: what
# scripts/policy.py says in POLICY_MODE=kind, from the repository's policy as
# it stands on the base branch. A pull request cannot declare its own kind or
# add its own exceptions (`kind-settings:`): they apply once merged.
#
# On a pull request the checkout is its merge commit at depth 2, so its
# first parent is the base branch. On a push, the weekly run or a run by hand
# (EVENT push, schedule or workflow_dispatch) the checkout is the commit being checked, whose
# policy is already merged, and that is the one read; so is the policy of a
# checkout without a parent (a first commit, depth 1).
#
# Expects: DEFAULT_POLICY, GITHUB_OUTPUT, RUNNER_TEMP, KIND_DEFAULT (the
# workflow's kind), EVENT (github.event_name; pull_request when unset), and
# DiluxOne/.github under .dx-central (or CENTRAL).
# Writes kind, rules, profile and settings to $GITHUB_OUTPUT.
#
# `kind.sh --test` checks it against a scratch repository.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if [ "${1:-}" = "--test" ]; then
  dir=$(mktemp -d); fail=0
  (
    set -euo pipefail
    cd "$dir" && git init -q && git config user.email t@t && git config user.name t
    mkdir .github
    printf 'kind: wordpress-plugin\nkind-settings:\n  plugin-check:\n    ignore-codes: [from_the_base]\n' > .github/review-policy.yml
    git add -A && git commit -q -m "chore: base"
    printf 'kind: wordpress-plugin\nkind-settings:\n  plugin-check:\n    ignore-codes: [from_the_change]\n' > .github/review-policy.yml
    git add -A && git commit -q -m "feat: change"
  ) || { echo "FAIL the scratch repository could not be set up"; rm -rf "$dir"; exit 1; }
  run() { ( cd "$dir" && : > out && GITHUB_OUTPUT=$dir/out RUNNER_TEMP=$dir DEFAULT_POLICY=$here/../policy/review-policy.default.yml KIND_DEFAULT=${1:-} bash "$here/kind.sh" >/dev/null 2>&1 ); }
  has() { if grep -q -- "$2" "$dir/out"; then echo "ok   $1"; else echo "FAIL $1 (no \"$2\" in: $(cat "$dir/out"))"; fail=1; fi; }
  lacks() { if grep -q -- "$2" "$dir/out"; then echo "FAIL $1 (\"$2\" is there)"; fail=1; else echo "ok   $1"; fi; }
  run wordpress-plugin || { echo "FAIL kind.sh failed"; fail=1; }
  has "the kind"                              "kind=wordpress-plugin"
  has "the pack's settings"                   '"strict":true'
  has "the base's exceptions"                 "from_the_base"
  lacks "never the change's own exceptions"   "from_the_change"
  ( cd "$dir" && : > out && GITHUB_OUTPUT=$dir/out RUNNER_TEMP=$dir DEFAULT_POLICY=$here/../policy/review-policy.default.yml KIND_DEFAULT=wordpress-plugin EVENT=push bash "$here/kind.sh" >/dev/null 2>&1 ) || { echo "FAIL kind.sh failed on a push"; fail=1; }
  has "on a push, the merged policy"          "from_the_change"
  lacks "on a push, never the commit before"  "from_the_base"
  ( cd "$dir" && : > out && GITHUB_OUTPUT=$dir/out RUNNER_TEMP=$dir DEFAULT_POLICY=$here/../policy/review-policy.default.yml KIND_DEFAULT=wordpress-plugin EVENT=pull_request_target bash "$here/kind.sh" >/dev/null 2>&1 ) || { echo "FAIL kind.sh failed on pull_request_target"; fail=1; }
  has "any other event reads the base"        "from_the_base"
  ( cd "$dir" && git checkout -q --orphan lone && git commit -q -m "chore: lone" )
  run wordpress-plugin || { echo "FAIL kind.sh failed without a parent"; fail=1; }
  has "without a parent, the commit's own policy" "from_the_change"
  if run node-app; then echo "FAIL a workflow of another kind fails"; fail=1; else echo "ok   a workflow of another kind fails"; fi
  rm -rf "$dir"
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

central=${CENTRAL:-.dx-central}
REPO_POLICY="$RUNNER_TEMP/kind-policy.yml"
# On a pull request the checkout is the merge commit, and its first parent is
# the base branch: the policy comes from there, so a change cannot exempt
# itself. On a push to main, the weekly run or a run by hand the checkout is
# the commit being checked and its policy is already merged: read it as it is.
# Only the events that check what is already merged read the checkout's own
# policy; any other (pull_request, pull_request_target, …) reads the base.
case "${EVENT:-pull_request}" in
  push|schedule|workflow_dispatch) own=1 ;;
  *) own=0 ;;
esac
if [ "$own" = 0 ] && git rev-parse --verify -q HEAD^1 >/dev/null; then
  git show "HEAD^1:.github/review-policy.yml" > "$REPO_POLICY" 2>/dev/null || : > "$REPO_POLICY"
else
  git show "HEAD:.github/review-policy.yml" > "$REPO_POLICY" 2>/dev/null || : > "$REPO_POLICY"
fi
export REPO_POLICY
[ -f "$central/scripts/policy.py" ] || central=$here/..
POLICY_MODE=kind python3 "$central/scripts/policy.py"
