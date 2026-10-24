#!/usr/bin/env bash
# The weekly full run failed (weekly-failure.yml): record it on the one open
# `ci:weekly` issue, or open that issue, with the Type Bug (#375). The pull
# request that fixes the failure is a `fix`, and the conventions gate wants a
# `fix` to close a Bug, so an issue without the Type would stop its fix until
# a person set it by hand.
#
#   weekly-failure.sh          records the failure
#   weekly-failure.sh --test   self-test against a stand-in for gh
#
# With no open `ci:weekly` issue it opens one with the Type Bug; when GitHub
# refuses the issue with a Type (the repository has no Bug type), it opens it
# without one, so the failure is never lost. With one open, it comments the
# run on it and sets the Type Bug only when it has none: a Type a person set
# stays. GitHub drops a Type a token without push access sends, without an
# error, so the Type is read back from GitHub's answer and a Type that did
# not stick is a warning, never a failed run: the record matters more than
# its Type.
#
# Environment: GITHUB_REPOSITORY (owner/name), GH_TOKEN (issues: write; to
# set a Type, dilux-bot's), RUN_URL (the failed run), SHA (the commit it ran).
set -euo pipefail

LABEL=ci:weekly
TITLE="The weekly full run failed"
NOTE="Nothing merged caused this: the run tests the code of \`main\` as it was already tested, against today's WordPress, PHP and tools. Read the run, fix what drifted in a pull request, and close this issue when a scheduled run is green again."

# Set issue $1's Type to Bug and say whether GitHub kept it.
set_bug() {
  local got
  got=$(gh api -X PATCH "repos/$GITHUB_REPOSITORY/issues/$1" -f type=Bug --jq '.type.name // ""' 2>/dev/null) || got=""
  if [ "$got" = Bug ]; then echo "#$1: Type Bug."
  else echo "::warning::#$1: GitHub did not set the Type Bug (no Bug type in the repository, or a token without push access: pass DILUX_BOT_PRIVATE_KEY); set it by hand so its fix passes the conventions gate."; fi
}

record() {
  local body open type answer number err
  gh label create "$LABEL" --repo "$GITHUB_REPOSITORY" --color B60205 --description "The weekly full run failed" --force >/dev/null || return 1
  body="The scheduled run of the full pipeline failed on $(date -u +%F) at \`${SHA:0:7}\`: $RUN_URL"
  open=$(gh issue list --repo "$GITHUB_REPOSITORY" --label "$LABEL" --state open --json number --jq '.[0].number // empty') || return 1
  if [ -n "$open" ]; then
    gh issue comment "$open" --repo "$GITHUB_REPOSITORY" --body "$body" >/dev/null || return 1
    echo "Added to #$open."
    if ! type=$(gh api "repos/$GITHUB_REPOSITORY/issues/$open" --jq '.type.name // ""' 2>/dev/null); then
      echo "::warning::#$open: could not read its Type; left as it is."; return 0
    fi
    if [ -n "$type" ]; then echo "#$open: keeps its Type $type."; else set_bug "$open"; fi
    return 0
  fi
  body=$(printf '%s\n\n%s' "$body" "$NOTE")
  err=$(mktemp)
  if answer=$(gh api -X POST "repos/$GITHUB_REPOSITORY/issues" -f title="$TITLE" -f body="$body" -f "labels[]=$LABEL" -f type=Bug --jq '"\(.number) \(.type.name // "")"' 2>"$err"); then
    number=${answer%% *}
    echo "Opened #$number."
    if [ "${answer#* }" = Bug ]; then echo "#$number: Type Bug."; else set_bug "$number"; fi
    rm -f "$err"; return 0
  fi
  answer=$(cat "$err" - <<<"$answer"); rm -f "$err"
  if grep -q 'HTTP 422' <<<"$answer"; then
    # Only a refusal (the repository has no Bug type) is retried without the
    # Type: any other failure may have opened the issue already.
    echo "::warning::GitHub refused the issue with the Type Bug ($(head -c 200 <<<"$answer")); opening it without one."
    gh issue create --repo "$GITHUB_REPOSITORY" --label "$LABEL" --title "$TITLE" --body "$body" || return 1
  else
    echo "::error::Could not open the issue: $(head -c 300 <<<"$answer")"; return 1
  fi
}

if [ "${1:-}" = "--test" ]; then
  fail=0
  export GITHUB_REPOSITORY=DiluxOne/example RUN_URL=https://github.com/DiluxOne/example/actions/runs/42 SHA=0123456789abcdef
  is() { if [ "$2" = "$3" ]; then echo "ok   $1"; else printf 'FAIL %s\n  want: %s\n  got:  %s\n' "$1" "$3" "$2"; fail=1; fi; }
  has() { if grep -qF -- "$3" <<<"$2"; then echo "ok   $1"; else printf 'FAIL %s\n  want a line with: %s\n  got:\n%s\n' "$1" "$3" "$2"; fail=1; fi; }
  hasnt() { if grep -qF -- "$3" <<<"$2"; then printf 'FAIL %s\n  did not want: %s\n  got:\n%s\n' "$1" "$3" "$2"; fail=1; else echo "ok   $1"; fi; }
  # A stand-in for gh: logs each call on one line and answers from the
  # variables below. OPEN: the open ci:weekly issue's number (empty: none).
  # TYPE: its Type ("unreadable": the read fails). CREATE: the Type GitHub
  # keeps on create ("refuse": a 422, "down": a 502).
  # PATCH: the Type GitHub keeps on a PATCH.
  log=$(mktemp)
  gh() {
    echo "$*" >> "$log"
    case "$1 $2 $3" in
      "issue list "*) echo "${OPEN:-}" ;;
      "api -X POST") case "${CREATE:-}" in refuse) echo "gh: Validation Failed (HTTP 422)" >&2; return 1 ;; down) echo "gh: Bad Gateway (HTTP 502)" >&2; return 1 ;; esac; echo "7 ${CREATE:-}" ;;
      "issue comment "*) [ "${COMMENT:-}" = fails ] && return 1; true ;;
      "api -X PATCH") echo "${PATCH:-}" ;;
      "api repos/"*) [ "${TYPE:-}" = unreadable ] && return 1; echo "${TYPE:-}" ;;
      "issue create "*) echo "https://github.com/$GITHUB_REPOSITORY/issues/7" ;;
    esac
  }
  run() { : > "$log"; status=0; out=$(record 2>&1) || status=$?; calls=$(cat "$log"); }

  OPEN="" CREATE=Bug run
  has "C1: no open issue, so it is opened with the Type Bug" "$calls" "api -X POST repos/$GITHUB_REPOSITORY/issues -f title=$TITLE"
  has "C1: with the Type Bug" "$calls" "-f type=Bug"
  has "C1: and the ci:weekly label" "$calls" "-f labels[]=ci:weekly"
  has "C1: the body links the run" "$calls" "at \`0123456\`: $RUN_URL"
  hasnt "C1: a Type kept on create needs no PATCH" "$calls" "-X PATCH"
  is "C1: the run passes" "$status" 0
  is "C1: says what it did" "$out" "$(printf 'Opened #7.\n#7: Type Bug.')"

  OPEN="" CREATE="" PATCH="" run
  has "a Type dropped on create is set again" "$calls" "api -X PATCH repos/$GITHUB_REPOSITORY/issues/7 -f type=Bug"
  has "and one that does not stick is a warning" "$out" "::warning::#7: GitHub did not set the Type Bug"

  OPEN="" CREATE=refuse run
  has "a refused Type still opens the issue, without one" "$calls" "issue create --repo $GITHUB_REPOSITORY --label ci:weekly --title $TITLE"
  has "and says so" "$out" "::warning::GitHub refused the issue with the Type Bug"
  is "and the run passes" "$status" 0

  OPEN="" CREATE=down run
  hasnt "any other failure opens no second issue" "$calls" "issue create"
  has "and is an error" "$out" "::error::Could not open the issue: gh: Bad Gateway (HTTP 502)"
  is "that fails the run" "$status" 1

  OPEN=12 TYPE="" PATCH=Bug run
  has "C2: an open issue gets the run as a comment" "$calls" "issue comment 12 --repo $GITHUB_REPOSITORY --body"
  has "C2: and, with no Type, the Type Bug" "$calls" "api -X PATCH repos/$GITHUB_REPOSITORY/issues/12 -f type=Bug"
  hasnt "C2: and no new issue" "$calls" "-X POST"
  is "C2: says what it did" "$out" "$(printf 'Added to #12.\n#12: Type Bug.')"

  OPEN=12 TYPE=Task run
  has "C3: an open issue with a Type gets the comment" "$calls" "issue comment 12"
  hasnt "C3: and keeps its Type" "$calls" "-X PATCH"
  has "C3: and says so" "$out" "#12: keeps its Type Task."

  OPEN=12 TYPE=unreadable run
  has "a Type it cannot read still gets the comment" "$calls" "issue comment 12"
  hasnt "and is left as it is" "$calls" "-X PATCH"
  has "with a warning" "$out" "::warning::#12: could not read its Type"

  OPEN=12 COMMENT=fails run
  is "a comment GitHub refuses fails the run" "$status" 1
  hasnt "and touches no Type" "$calls" "-X PATCH"

  unset -f gh; rm -f "$log"
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

case "${1:-}" in
  "") record ;;
  *) echo "usage: weekly-failure.sh [--test]" >&2; exit 2 ;;
esac
