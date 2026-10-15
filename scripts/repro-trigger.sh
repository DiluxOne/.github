#!/usr/bin/env bash
# Decides whether a reproduction starts (issue-repro.yml, its write job).
#   decide  reads TRIGGER, EVENT, ACTION, LABEL, SENDER_TYPE, ROLE and
#           TRIAGE_BUG from the environment and prints go=yes or go=no
#           (appended to $GITHUB_OUTPUT when it is set).
#   bug     reads VERDICT (the triage's verdict JSON) and PAID, and prints
#           true when the verdict is bug_unconfirmed and the report is not
#           paid: the triage's `bug` output.
#   setup   reads DIR (default: the current directory) and prints ready=yes
#           when it has the unit-test setup a reproduction writes into
#           (tests/bootstrap.php and tests/Unit/), ready=no otherwise
#           (appended to $GITHUB_OUTPUT when it is set). A repository
#           without one has nothing to reproduce against: the run ends
#           there, green, and the report waits for a person.
#   --test  the cases behind each acceptance criterion of the issue.
#
# trigger "triage": the triage classified the report as a bug (TRIAGE_BUG),
#   on the event that opened it. Nobody's permission is asked: the report's
#   author is not a writer by definition.
# trigger "label": a person with write access labels the issue repro:run or
#   repro:again. ROLE is that person's permission on the repository.
# A bot as the sender never starts one, on either trigger.
set -euo pipefail

decide() {
  local trigger=$1 event=$2 action=$3 label=$4 sender=$5 role=$6 triage_bug=$7
  [ "$event" = issues ] || { echo no; return; }
  [ "$sender" != Bot ] || { echo no; return; }
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

# setup_ready DIR: yes when DIR has tests/bootstrap.php and tests/Unit/.
setup_ready() {
  if [ -f "$1/tests/bootstrap.php" ] && [ -d "$1/tests/Unit" ]; then echo yes; else echo no; fi
}

test_all() {
  local failed=0 total=0 got
  # check NAME WANT TRIGGER EVENT ACTION LABEL SENDER ROLE TRIAGE_BUG
  check() {
    total=$((total + 1))
    got=$(decide "$3" "$4" "$5" "$6" "$7" "$8" "$9")
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
  bug_from '{"category":"bug_unconfirmed"}' true false
  bug_from '{"category":"enhancement"}' false false
  bug_from '{"category":"needs_info"}' false false
  bug_from '' false false
  bug_from 'not json' false false

  # ready NAME WANT PATHS...: a scratch repository with these paths (a
  # trailing / is a directory).
  ready() {
    local name=$1 want=$2 dir path
    shift 2
    total=$((total + 1))
    dir=$(mktemp -d)
    for path in "$@"; do
      case "$path" in */) mkdir -p "$dir/$path" ;; *) mkdir -p "$dir/$(dirname "$path")"; : > "$dir/$path" ;; esac
    done
    got=$(DIR=$dir bash "${BASH_SOURCE[0]}" setup)
    rm -rf "$dir"
    if [ "$got" != "ready=$want" ]; then
      failed=$((failed + 1))
      echo "not ok $total - $name (want ready=$want, got $got)"
    else
      echo "ok $total - $name"
    fi
  }
  ready "a plugin with tests/bootstrap.php and tests/Unit/ is ready" yes tests/bootstrap.php tests/Unit/
  ready "a repository with no tests is not ready (the run skips, green)" no README.md
  ready "tests/Unit/ without its bootstrap is not ready" no tests/Unit/
  ready "a bootstrap without tests/Unit/ is not ready" no tests/bootstrap.php

  echo "$((total - failed))/$total passed"
  [ "$failed" -eq 0 ]
}

# bug_output reads VERDICT and PAID from the environment.
bug_output() {
  if [ "${PAID:-false}" = true ]; then echo false; return; fi
  jq -r 'if .category == "bug_unconfirmed" then "true" else "false" end' <<<"${VERDICT:-null}" 2>/dev/null || echo false
}

case "${1:-}" in
  bug) bug_output ;;
  setup)
    ready=$(setup_ready "${DIR:-.}")
    echo "ready=$ready"
    if [ -n "${GITHUB_OUTPUT:-}" ]; then echo "ready=$ready" >> "$GITHUB_OUTPUT"; fi
    ;;
  decide)
    go=$(decide "${TRIGGER:-label}" "${EVENT:-}" "${ACTION:-}" "${LABEL:-}" "${SENDER_TYPE:-}" "${ROLE:-}" "${TRIAGE_BUG:-false}")
    echo "go=$go"
    if [ -n "${GITHUB_OUTPUT:-}" ]; then echo "go=$go" >> "$GITHUB_OUTPUT"; fi
    ;;
  --test) test_all ;;
  *) echo "usage: repro-trigger.sh decide | bug | setup | --test" >&2; exit 2 ;;
esac
