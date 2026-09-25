#!/usr/bin/env bash
# Squash-merges a pull request by hand the way auto-merge does: the PR title,
# the description verbatim (GitHub's own squash message hard-wraps it at 72
# columns) and the branch commits' Co-authored-by trailers.
#
#   scripts/squash-merge.sh <owner/repo> <number>
set -euo pipefail
if [ $# -ne 2 ]; then echo "usage: $0 <owner/repo> <number>" >&2; exit 2; fi
repo="$1"; pr="$2"
body=$(gh pr view "$pr" --repo "$repo" --json body --jq .body | tr -d '\r')
messages=$(gh api "repos/$repo/pulls/$pr/commits" --paginate --jq '.[].commit.message')
coauthors=$(printf '%s\n' "$messages" | tr -d '\r' | grep -iE '^co-authored-by:' | awk '!seen[tolower($0)]++' || true)
if [ -n "$coauthors" ]; then
  if [ -n "$body" ]; then body+=$'\n\n'; fi
  body+=$'---------\n\n'"$coauthors"
fi
gh pr merge "$pr" --repo "$repo" --squash --delete-branch --body "$body"
