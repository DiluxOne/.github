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
# Expects: EVENT, DEFAULT_POLICY, GITHUB_OUTPUT, RUNNER_TEMP; on a push, HEAD_SHA
# and GH_TOKEN (read) too; the repository checked out at fetch-depth 2, and
# DiluxOne/.github under .dx-central.
set -euo pipefail

everything() {
  echo "code=true" >> "$GITHUB_OUTPUT"
  echo "plugin_check=true" >> "$GITHUB_OUTPUT"
  echo "$1: everything runs"
}

tested() {
  echo "code=false" >> "$GITHUB_OUTPUT"
  echo "plugin_check=false" >> "$GITHUB_OUTPUT"
  echo "$1: the slow suites do not run again"
}

# A push to main after a squash merge carries exactly the tree the pull
# request's run tested: the ruleset requires the branch to be up to date,
# so the squash commit's tree equals the head's. The job checks that
# rather than trusting it: the pull request the commit came from must be
# merged, from this repository (a fork's code never had the real suite),
# its head's tree must equal this commit's tree, and every check on that
# head must have passed. Then nothing needs to run again. Any doubt, or an
# API that does not answer, runs everything.
if [ "${EVENT:-}" = "push" ] && [ -n "${HEAD_SHA:-}" ] && [ -n "${GH_TOKEN:-}" ]; then
  # shellcheck disable=SC2016 # jq variables, not shell ones.
  pr=$(gh api "repos/$GITHUB_REPOSITORY/commits/$HEAD_SHA/pulls" 2>/dev/null \
        | jq -r --arg sha "$HEAD_SHA" --arg repo "$GITHUB_REPOSITORY" \
          '[.[] | select(.merged_at != null and .merge_commit_sha == $sha and (.head.repo.full_name // "") == $repo)] | first // empty | "\(.number) \(.head.sha)"' 2>/dev/null || true)
  if [ -n "$pr" ]; then
    number=${pr%% *}; head=${pr##* }
    tree_here=$(git rev-parse "HEAD^{tree}" 2>/dev/null || true)
    tree_pr=$(gh api "repos/$GITHUB_REPOSITORY/git/commits/$head" --jq .tree.sha 2>/dev/null || true)
    if [ -z "$tree_here" ] || [ "$tree_here" != "$tree_pr" ]; then
      everything "this commit's tree differs from what #$number tested"
      exit 0
    fi
    # The checks of that head must all have passed (a merge that bypassed the
    # ruleset, or a suite that was still running, is not a tested tree).
    # shellcheck disable=SC2016 # jq variable, not a shell one.
    runs=$(gh api "repos/$GITHUB_REPOSITORY/commits/$head/check-runs?per_page=100" --paginate 2>/dev/null | jq -s '[.[].check_runs[]]' 2>/dev/null || echo "")
    if [ -z "$runs" ] || [ "$(jq length <<<"$runs")" -eq 0 ]; then
      everything "the checks of #$number's head could not be read, or there were none"
      exit 0
    fi
    bad=$(jq -r '[.[] | select(.status != "completed" or (.conclusion | IN("success", "skipped", "neutral") | not)) | .name] | unique | join(", ")' <<<"$runs")
    if [ -n "$bad" ]; then
      everything "the checks of #$number's head did not all pass ($bad)"
      exit 0
    fi
    tested "this commit is the squash merge of #$number, its tree is the one #$number's checks ran on, and they passed"
    exit 0
  fi
  everything "no merged pull request of this repository produced this commit"
  exit 0
fi

if [ "${EVENT:-}" != "pull_request" ]; then
  everything "a ${EVENT:-?} run"
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
# by one path, or by two for a rename or a copy; the records are walked,
# not filtered, so a file that happens to be called "M" is a file.
DIFF="$RUNNER_TEMP/changes.diff"
if ! git diff -z --name-status -M "$BASE" HEAD > "$DIFF"; then
  everything "the diff could not be read"
  exit 0
fi
CHANGED_FILES="$(
  while IFS= read -r -d '' status; do
    IFS= read -r -d '' path && printf '%s\n' "$path"
    case "$status" in
      R*|C*) IFS= read -r -d '' path && printf '%s\n' "$path" ;;
    esac
  done < "$DIFF"
)"
export CHANGED_FILES
POLICY_MODE=changes python3 .dx-central/scripts/policy.py
