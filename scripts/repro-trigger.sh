#!/usr/bin/env bash
# Decides whether a reproduction starts (issue-repro.yml, its write job).
#   decide  reads TRIGGER, EVENT, ACTION, COMMENT, IS_PR, SENDER_TYPE,
#           SENDER_LOGIN, ROLE and TRIAGE_BUG from the environment and
#           prints go=yes or go=no, and kind=<what started it> (appended to
#           $GITHUB_OUTPUT when it is set).
#   bug     reads VERDICT (the triage's verdict JSON) and prints true when
#           it is bug_unconfirmed: the triage's `bug` output, whether or not
#           the classifier read a paid add-on's roadmap (#247).
#   --test  the cases behind each acceptance criterion of the issue.
# Whether the repository can reproduce the bug, and how, is
# scripts/repro-ways.py (#352).
#
# trigger "triage": the triage classified the report as a bug (TRIAGE_BUG),
#   on the event that opened it. Nobody's permission is asked: the report's
#   author is not a writer by definition. kind=triage.
# trigger "command" (`label`, its old name, reads the same): a person with
#   write access comments `/repro` on the issue, the comment's first line
#   (#564: it replaces the repro:run and repro:again labels). ROLE is that
#   person's permission on the repository. kind=command.
# A bot as the sender never starts one, on either trigger, but for the
# organisation's App's own comments that say so on their first line (#564,
# no label): `<!-- dx-repro-unblocked -->` when what blocked it is fixed
# (issue-triage.yml, unblock; kind=unblocked) and `<!-- dx-repro-retry -->`
# when its first test was written wrong (#261; kind=retry).
#
# The organisation's App is DX_BOT_LOGIN, the calling organisation's (the
# workflow's env, #197), DiluxOne's dilux-bot by default.
set -euo pipefail

# What a comment asks for, from its first line: retry or unblocked (the
# App's markers), command (`/repro`, alone or followed by a space), or
# nothing.
kind_of() {
  local first=${1%%$'\n'*}
  first=${first%$'\r'}
  case "$first" in
    "<!-- dx-repro-retry -->"*) echo retry ;;
    "<!-- dx-repro-unblocked -->"*) echo unblocked ;;
    /repro | "/repro "* | /repro$'\t'*) echo command ;;
    *) echo "" ;;
  esac
}

# Prints "yes KIND" or "no".
decide() {
  local trigger=$1 event=$2 action=$3 comment=$4 sender=$5 role=$6 triage_bug=$7 nightly=${8:-false} login=${9:-} is_pr=${10:-false} bot=${DX_BOT_LOGIN:-dilux-bot[bot]} kind
  [ "$trigger" != label ] || trigger="command"
  case "$trigger:$event" in
    triage:issues) ;;
    command:issue_comment) if [ "$action" != created ] || [ "$is_pr" = true ]; then echo no; return; fi ;;
    *) echo no; return ;;
  esac
  # A bot starts one in a single case (#247): the nightly review's own Bug
  # issue, opened by the organisation's App with its marker, which the
  # triage vouched for. Any other bot, comment or event starts nothing.
  if [ "$sender" = Bot ]; then
    if [ "$nightly" = true ] && [ "$trigger" = triage ] && [ "$action" = opened ] && [ "$triage_bug" = true ]; then echo "yes triage"; return; fi
    # ...and the App's own comments: what blocked it is fixed, or its first
    # test was written wrong (#261).
    kind=$(kind_of "$comment")
    if [ "$trigger" = command ] && [ "$login" = "$bot" ] && { [ "$kind" = unblocked ] || [ "$kind" = retry ]; }; then echo "yes $kind"
    else echo no; fi
    return
  fi
  case "$trigger" in
    triage)
      if [ "$action" = opened ] && [ "$triage_bug" = true ]; then echo "yes triage"; else echo no; fi ;;
    command)
      [ "$(kind_of "$comment")" = command ] || { echo no; return; }
      case "$role" in admin | maintain | write) echo "yes command" ;; *) echo no ;; esac ;;
  esac
}

test_all() {
  local failed=0 total=0 got
  # check NAME WANT TRIGGER EVENT ACTION COMMENT SENDER ROLE TRIAGE_BUG [NIGHTLY] [LOGIN] [IS_PR]
  check() {
    total=$((total + 1))
    got=$(decide "$3" "$4" "$5" "$6" "$7" "$8" "$9" "${10:-false}" "${11:-}" "${12:-false}")
    if [ "$got" != "$2" ]; then
      failed=$((failed + 1))
      echo "not ok $total - $1 (want $2, got $got)"
    else
      echo "ok $total - $1"
    fi
  }
  local retry=$'<!-- dx-repro-retry -->\nThe test did not run.' unblocked=$'<!-- dx-repro-unblocked -->\n#3 is closed.'

  # C1: a report the triage calls a bug starts on its own, with no label added.
  check "C1 a bug the triage opens starts a reproduction" "yes triage" triage issues opened "" User "" true
  # C2: a person with write access starts one by hand, with `/repro` (#564).
  check "C2 /repro from a writer starts one" "yes command" command issue_comment created "/repro" User write ""
  check "C2 /repro from an admin starts one" "yes command" command issue_comment created $'/repro\r\nthe steps are above' User admin ""
  check "C2 /repro from a maintainer starts one" "yes command" command issue_comment created "/repro please" User maintain ""
  check "#564 the old trigger name reads as the command" "yes command" label issue_comment created "/repro" User write ""
  # C3: a report that is not a bug starts nothing.
  check "C3 an enhancement the triage opens starts nothing" no triage issues opened "" User "" false
  check "C3 a question the triage opens starts nothing" no triage issues opened "" User "" false
  check "C3 a bug the triage has not classified starts nothing" no triage issues opened "" User "" ""
  # C4: a bot's command starts nothing.
  check "C4 /repro from a bot starts nothing" no command issue_comment created "/repro" Bot write ""
  check "C4 a bot that opens a bug report starts nothing" no triage issues opened "" Bot "" true
  # #247: the nightly review's Bug issue, and only that, on the event that opened it.
  check "#247 the nightly review's bug starts a reproduction" "yes triage" triage issues opened "" Bot "" true true
  check "#247 not without the triage's verdict" no triage issues opened "" Bot "" false true
  check "#247 not by a command" no command issue_comment created "/repro" Bot write "" true
  check "#247 not on another event" no triage issues labeled "" Bot "" true true
  check "#247 the App's unblocked comment runs it again" "yes unblocked" command issue_comment created "$unblocked" Bot "" "" false "dilux-bot[bot]"
  check "#247 another bot's unblocked comment does not" no command issue_comment created "$unblocked" Bot "" "" false "other[bot]"
  check "#247 a person's unblocked comment is not a trigger" no command issue_comment created "$unblocked" User write ""
  check "#261 the App's retry comment runs it once more" "yes retry" command issue_comment created "$retry" Bot "" "" false "dilux-bot[bot]"
  check "#261 another bot's retry comment does not" no command issue_comment created "$retry" Bot "" "" false "other[bot]"
  check "#261 a person's retry comment is not a trigger" no command issue_comment created "$retry" User write ""
  check "#261 the marker counts on the first line only" no command issue_comment created $'thanks\n<!-- dx-repro-retry -->' Bot "" "" false "dilux-bot[bot]"
  # #197: another organisation's App, named by its DX_BOT_LOGIN.
  DX_BOT_LOGIN="acme-bot[bot]" check "#197 another organisation's App's retry comment runs it" "yes retry" command issue_comment created "$retry" Bot "" "" false "acme-bot[bot]"
  DX_BOT_LOGIN="acme-bot[bot]" check "#197 there, dilux-bot's unblocked comment does not" no command issue_comment created "$unblocked" Bot "" "" false "dilux-bot[bot]"
  # Guards that keep the rest closed.
  check "/repro from a reader starts nothing" no command issue_comment created "/repro" User read ""
  check "/repro from a triager starts nothing" no command issue_comment created "/repro" User triage ""
  check "/repro whose permission could not be read starts nothing" no command issue_comment created "/repro" User unknown ""
  check "/repro from a stranger starts nothing" no command issue_comment created "/repro" User none ""
  check "/repro past the first line starts nothing" no command issue_comment created $'please\n/repro' User write ""
  check "/reproduce is not /repro" no command issue_comment created "/reproduce" User write ""
  check "/repro on a pull request starts nothing" no command issue_comment created "/repro" User write "" false "" true
  check "an edited comment starts nothing" no command issue_comment edited "/repro" User write ""
  check "#564 a label starts nothing any more" no command issues labeled "" User write ""
  check "a re-triage on a label event does not start one" no triage issues labeled "" User "" true
  check "a closed issue starts nothing" no triage issues closed "" User "" true
  check "a pull request event starts nothing" no triage pull_request opened "" User "" true

  # bug_from VERDICT PAID WANT
  bug_from() {
    total=$((total + 1))
    got=$(VERDICT=$1 PAID=$2 bug_output)
    if [ "$got" != "$3" ]; then
      failed=$((failed + 1))
      echo "not ok $total - bug output for '$1' paid=$2 (want $3, got $got)"
    else
      echo "ok $total - bug output for '$1' paid=$2"
    fi
  }
  bug_from '{"category":"bug_unconfirmed"}' false true
  bug_from '{"category":"bug_unconfirmed"}' true true
  bug_from '{"category":"enhancement"}' false false
  bug_from '{"category":"needs_info"}' false false
  bug_from '' false false
  bug_from 'not json' false false

  # The output decide writes: go and kind.
  total=$((total + 1))
  got=$(TRIGGER=command EVENT=issue_comment ACTION=created COMMENT=/repro SENDER_TYPE=User ROLE=write GITHUB_OUTPUT='' main decide | tr '\n' ' ')
  if [ "$got" != "go=yes kind=command " ]; then failed=$((failed + 1)); echo "not ok $total - decide prints go and kind (got $got)"; else echo "ok $total - decide prints go and kind"; fi

  echo "$((total - failed))/$total passed"
  [ "$failed" -eq 0 ]
}

# bug_output reads VERDICT from the environment. PAID (the classifier read
# the paid add-on's private roadmap) no longer stops it (#247): the
# reproduction writes its test from the report, never from that roadmap,
# and a repository with a paid add-on reproduced no bug on its own.
bug_output() {
  jq -r 'if .category == "bug_unconfirmed" then "true" else "false" end' <<<"${VERDICT:-null}" 2>/dev/null || echo false
}

main() {
  case "${1:-}" in
    bug) bug_output ;;
    decide)
      local out go kind
      out=$(decide "${TRIGGER:-command}" "${EVENT:-}" "${ACTION:-}" "${COMMENT:-}" "${SENDER_TYPE:-}" "${ROLE:-}" "${TRIAGE_BUG:-false}" "${NIGHTLY:-false}" "${SENDER_LOGIN:-}" "${IS_PR:-false}")
      go=${out%% *}; kind=""; [ "$go" = no ] || kind=${out#* }
      printf 'go=%s\nkind=%s\n' "$go" "$kind"
      if [ -n "${GITHUB_OUTPUT:-}" ]; then printf 'go=%s\nkind=%s\n' "$go" "$kind" >> "$GITHUB_OUTPUT"; fi
      ;;
    --test) test_all ;;
    *) echo "usage: repro-trigger.sh decide | bug | --test" >&2; exit 2 ;;
  esac
}

main "$@"
