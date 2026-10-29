#!/usr/bin/env bash
# Squash-merges a pull request by hand the way auto-merge does: the PR title,
# the description verbatim (GitHub's own squash message hard-wraps it at 72
# columns) and the credits' trailers (scripts/credits.py body, #491): the
# description's Credits block and the branch commits' human co-authors,
# never a model, a bot, the maintainer who accepted the issue or you, who
# merge it.
#
#   scripts/squash-merge.sh <owner/repo> <number>
set -euo pipefail
if [ $# -ne 2 ]; then echo "usage: $0 <owner/repo> <number>" >&2; exit 2; fi
repo="$1"; pr="$2"
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
merger=$(gh api user --jq .login)
body=$(python3 "$here/credits.py" body "$repo" "$pr" "$merger")
gh pr merge "$pr" --repo "$repo" --squash --delete-branch --body "$body"
