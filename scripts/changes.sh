#!/usr/bin/env bash
# Answers "did this pull request change code?" for the workflows that gate
# the slow suites on it. Reads the diff with git (no API, no permission
# beyond contents: read, no size cap), lists both paths of a rename, takes
# the repository's policy from the base branch so a change cannot exempt
# itself, and lets policy.py match the paths against the `code` and
# `plugin-check` lists. Anything but a pull request runs everything; so
# does a diff that cannot be read.
#
# The checkout is the pull request's merge commit (what a pull_request run
# tests) at depth 2, so its first parent is the base branch as it stands:
# the diff between the two is exactly what the merge would change, and the
# policy is read from that parent. Nothing here depends on the event's
# shas, which can lag behind the merge ref.
#
# Expects: EVENT, DEFAULT_POLICY, GITHUB_OUTPUT, RUNNER_TEMP; the repository
# checked out at fetch-depth 2, and DiluxOne/.github under .dx-central.
set -euo pipefail

everything() {
  echo "code=true" >> "$GITHUB_OUTPUT"
  echo "plugin_check=true" >> "$GITHUB_OUTPUT"
  echo "$1: everything runs"
}

if [ "${EVENT:-}" != "pull_request" ]; then
  everything "not a pull request"
  exit 0
fi

if ! BASE="$(git rev-parse --verify HEAD^1 2>/dev/null)"; then
  everything "the base of the merge commit is not available"
  exit 0
fi

REPO_POLICY="$RUNNER_TEMP/repo-policy.yml"
git show "$BASE:.github/review-policy.yml" > "$REPO_POLICY" 2>/dev/null || : > "$REPO_POLICY"
export REPO_POLICY

# -z: paths are NUL-separated and never quoted, so a name with a space or
# an accent survives. Each record is a status (M, A, D, R100, …) followed
# by one path, or two for a rename or a copy; the statuses are dropped.
if ! CHANGED_FILES="$(git diff -z --name-status -M "$BASE" HEAD | tr '\0' '\n' | grep -vE '^[ACDMRTUXB][0-9]{0,3}$' || true)"; then
  everything "the diff could not be read"
  exit 0
fi
export CHANGED_FILES
POLICY_MODE=changes python3 .dx-central/scripts/policy.py
