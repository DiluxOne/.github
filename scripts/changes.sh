#!/usr/bin/env bash
# Answers "did this pull request change code?" for the workflows that gate
# the slow suites on it. Reads the diff with git (no API, no permission
# beyond contents: read, no size cap), lists both paths of a rename, takes
# the repository's policy from the base branch so a change cannot exempt
# itself, and lets policy.py match the paths against the `code` and
# `plugin-check` lists. Anything but a pull request runs everything; so
# does a diff that cannot be read.
#
# Expects: EVENT, BASE (base sha), HEAD (head sha), DEFAULT_POLICY,
# GITHUB_OUTPUT; the repository checked out with its history, and
# DiluxOne/.github under .dx-central.
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

REPO_POLICY="$RUNNER_TEMP/repo-policy.yml"
git show "$BASE:.github/review-policy.yml" > "$REPO_POLICY" 2>/dev/null || : > "$REPO_POLICY"
export REPO_POLICY

if ! CHANGED_FILES="$(git diff --name-status -M "$BASE...$HEAD" | awk '{ for (i = 2; i <= NF; i++) print $i }')"; then
  everything "the diff could not be read"
  exit 0
fi
export CHANGED_FILES
POLICY_MODE=changes python3 .dx-central/scripts/policy.py
