#!/usr/bin/env bash
# Decides whether a reproduction starts (issue-repro.yml, its write job).
#   decide  reads TRIGGER, EVENT, ACTION, LABEL, SENDER_TYPE, ROLE and
#           TRIAGE_BUG from the environment and prints go=yes or go=no
#           (appended to $GITHUB_OUTPUT when it is set).
#   bug     reads VERDICT (the triage's verdict JSON) and prints true when
#           it is bug_unconfirmed: the triage's `bug` output, whether or not
#           the classifier read a paid add-on's roadmap (#247).
#   --test  the cases behind each acceptance criterion of the issue.
# Whether the repository can reproduce the bug, and how, is
# scripts/repro-ways.py (#352).
#
# trigger "triage": the triage classified the report as a bug (TRIAGE_BUG),
#   on the event that opened it. Nobody's permission is asked: the report's
#   author is not a writer by definition.
# trigger "label": a person with write access labels the issue repro:run or
#   repro:again. ROLE is that person's permission on the repository.
# A bot as the sender never starts one, on either trigger.
#
# The organisation's App is DX_BOT_LOGIN, the calling organisation's (the
# workflow's env, #197), DiluxOne's dilux-bot by default.
set -euo pipefail

decide() {
  local trigger=$1 event=$2 action=$3 label=$4 sender=$5 role=$6 triage_bug=$7 nightly=${8:-false} login=${9:-} bot=${DX_BOT_LOGIN:-dilux-bot[bot]}
  [ "$event" = issues ] || { echo no; return; }
  # A bot starts one in a single case (#247): the nightly review's own Bug
  # issue, opened by the organisation's App with its marker, which the
  # triage vouched for. Any other bot, label or event starts nothing.
  if [ "$sender" = Bot ]; then
    if [ "$nightly" = true ] && [ "$trigger" = triage ] && [ "$action" = opened ] && [ "$triage_bug" = true ]; then echo yes
    # ...and when what blocked a reproduction is fixed: the App's own
    # repro:unblocked (issue-triage.yml, unblock).
    elif [ "$trigger" = label ] && [ "$action" = labeled ] && [ "$label" = repro:unblocked ] && [ "$login" = "$bot" ]; then echo yes
    # ...and once more when its first test was written wrong (#261).
    elif [ "$trigger" = label ] && [ "$action" = labeled ] && [ "$label" = repro:retry ] && [ "$login" = "$bot" ]; then echo yes
    else echo no; fi
    return
  fi
  case "$trigger" in
    triage)
      if [ "$action" = opened ] && [ "$triage_bug" = true ]; then echo yes; else echo no; fi ;;
    label)
      [ "$action" = labeled ] || { echo no; return; }
      case "$label" in repro:run | repro:again) ;; *) echo no; return ;; esac
      case "$role" in admin | maintain | write) echo yes ;; *) echo no ;; esac ;;
    *) echo no ;;
  esac
}

test_all() {
  local failed=0 total=0 got
  # check NAME WANT TRIGGER EVENT ACTION LABEL SENDER ROLE TRIAGE_BUG [NIGHTLY]
  check() {
    total=$((total + 1))
    got=$(decide "$3" "$4" "$5" "$6" "$7" "$8" "$9" "${10:-false}" "${11:-}")
    if [ "$got" != "$2" ]; then
      failed=$((failed + 1))
      echo "not ok $total - $1 (want $2, got $got)"
    else
      echo "ok $total - $1"
    fi
  }

  # C1: a report the triage calls a bug starts on its own, with no label added.
  check "C1 a bug the triage opens starts a reproduction" yes triage issues opened "" User "" true
  # C2: a person with write access starts one by hand, as before.
  check "C2 repro:run from a writer starts one" yes label issues labeled repro:run User write ""
  check "C2 repro:again from an admin starts one" yes label issues labeled repro:again User admin ""
  check "C2 repro:run from a maintainer starts one" yes label issues labeled repro:run User maintain ""
  # C3: a report that is not a bug starts nothing.
  check "C3 an enhancement the triage opens starts nothing" no triage issues opened "" User "" false
  check "C3 a question the triage opens starts nothing" no triage issues opened "" User "" false
  check "C3 a bug the triage has not classified starts nothing" no triage issues opened "" User "" ""
  # C4: a label a bot adds is the only trigger, so it starts nothing.
  check "C4 repro:run added by a bot starts nothing" no label issues labeled repro:run Bot write ""
  check "C4 bug:unconfirmed added by a bot starts nothing" no triage issues labeled "bug:unconfirmed" Bot "" true
  check "C4 a bot that opens a bug report starts nothing" no triage issues opened "" Bot "" true
  # #247: the nightly review's Bug issue, and only that, on the event that opened it.
  check "#247 the nightly review's bug starts a reproduction" yes triage issues opened "" Bot "" true true
  check "#247 not without the triage's verdict" no triage issues opened "" Bot "" false true
  check "#247 not by a label" no label issues labeled repro:run Bot write "" true
  check "#247 not on another event" no triage issues labeled "" Bot "" true true
  check "#247 the App's repro:unblocked runs it again" yes label issues labeled repro:unblocked Bot "" "" false "dilux-bot[bot]"
  check "#247 another bot's repro:unblocked does not" no label issues labeled repro:unblocked Bot "" "" false "other[bot]"
  check "#247 a person's repro:unblocked is not a trigger" no label issues labeled repro:unblocked User write ""
  check "#261 the App's repro:retry runs it once more" yes label issues labeled repro:retry Bot "" "" false "dilux-bot[bot]"
  check "#261 another bot's repro:retry does not" no label issues labeled repro:retry Bot "" "" false "other[bot]"
  check "#261 a person's repro:retry is not a trigger" no label issues labeled repro:retry User write ""
  # #197: another organisation's App, named by its DX_BOT_LOGIN.
  DX_BOT_LOGIN="acme-bot[bot]" check "#197 another organisation's App's repro:retry runs it" yes label issues labeled repro:retry Bot "" "" false "acme-bot[bot]"
  DX_BOT_LOGIN="acme-bot[bot]" check "#197 there, dilux-bot's repro:unblocked does not" no label issues labeled repro:unblocked Bot "" "" false "dilux-bot[bot]"
  # Guards that keep the rest closed.
  check "repro:run from a reader starts nothing" no label issues labeled repro:run User read ""
  check "repro:run from a triager starts nothing" no label issues labeled repro:run User triage ""
  check "repro:run whose permission could not be read starts nothing" no label issues labeled repro:run User unknown ""
  check "repro:run from a stranger starts nothing" no label issues labeled repro:run User none ""
  check "a bug label added by a writer does not start one" no label issues labeled bug:unconfirmed User write ""
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

case "${1:-}" in
  bug) bug_output ;;
  decide)
    go=$(decide "${TRIGGER:-label}" "${EVENT:-}" "${ACTION:-}" "${LABEL:-}" "${SENDER_TYPE:-}" "${ROLE:-}" "${TRIAGE_BUG:-false}" "${NIGHTLY:-false}" "${SENDER_LOGIN:-}")
    echo "go=$go"
    if [ -n "${GITHUB_OUTPUT:-}" ]; then echo "go=$go" >> "$GITHUB_OUTPUT"; fi
    ;;
  --test) test_all ;;
  *) echo "usage: repro-trigger.sh decide | bug | --test" >&2; exit 2 ;;
esac
