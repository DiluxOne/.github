#!/usr/bin/env bash
# One issue per run of the bots' recurring work (#188): the runner image's
# build (runner-image.yml) and the week's decisions by policy
# (autonomy-digest.yml). Each run opens its own issue, labelled `run:<kind>`;
# it closes as completed when the run needs no one, and stays open with
# `needs:maintainer` when it does. The closed issues are the record and the
# statistics: `is:issue label:run:<kind>` lists every run, and the open ones
# are what waits on a person.
#
#   run-issue.sh open KIND TITLE   reads the body on stdin; NEEDS=1 when the
#                                  run needs a person, LABELS for any other
#                                  labels (comma-separated); prints the
#                                  issue's number
#   run-issue.sh --test            self-test, with a stand-in for gh
#
# Environment: GITHUB_REPOSITORY, GH_TOKEN (issues: write). The labels are
# created when missing (labels.yml has them; the sync brings them to every
# repository), so a run never fails for a label.
set -euo pipefail

# The labels for a run's issue: its kind's, the caller's, and needs:maintainer
# when it needs a person. $1 kind, $2 extra labels (comma-separated), $3 1
# when it needs a person.
labels_for() {
  local out="run:$1"
  [ -z "$2" ] || out+=",$2"
  [ "$3" != 1 ] || out+=",needs:maintainer"
  printf '%s' "$out"
}

open_run() {
  local kind=$1 title=$2 body labels url n
  body=$(cat)
  labels=$(labels_for "$kind" "${LABELS:-}" "${NEEDS:-0}")
  IFS=, read -ra each <<<"$labels"
  for l in "${each[@]}"; do
    gh label create "$l" --repo "$GITHUB_REPOSITORY" --color C5DEF5 --description "A run's record (#188)" >/dev/null 2>&1 || true
  done
  url=$(gh issue create --repo "$GITHUB_REPOSITORY" --title "$title" --label "$labels" --body "$body")
  n=${url##*/}
  if [ "${NEEDS:-0}" != 1 ]; then
    gh issue close "$n" --repo "$GITHUB_REPOSITORY" --reason completed >/dev/null
  fi
  printf '%s\n' "$n"
}

self_test() {
  local fails=0 log got
  log=$(mktemp); trap 'rm -f "$log"' RETURN
  check() { if [ "$2" = "$3" ]; then echo "ok    $1"; else echo "FAIL  $1: got [$2], want [$3]"; fails=$((fails + 1)); fi; }
  gh() { printf '%s\n' "$*" >> "$log"; if [ "$1 $2" = "issue create" ]; then echo "https://github.com/o/r/issues/12"; fi; }
  export -f gh 2>/dev/null || true
  GITHUB_REPOSITORY=o/r

  check "labels: the kind's alone" "$(labels_for runner-image "" 0)" "run:runner-image"
  check "labels: with the caller's and needs:maintainer" "$(labels_for runner-image "lane:platform,accepted-by:policy" 1)" "run:runner-image,lane:platform,accepted-by:policy,needs:maintainer"

  : > "$log"
  got=$(printf 'All good.\n' | NEEDS=0 open_run runner-image "Runner image, run 7: promoted")
  check "a run that needs no one: its number" "$got" "12"
  check "a run that needs no one: opened with its kind's label" "$(grep -c '^issue create --repo o/r --title Runner image, run 7: promoted --label run:runner-image --body All good.$' "$log")" 1
  check "a run that needs no one: closed as completed" "$(grep -c '^issue close 12 --repo o/r --reason completed$' "$log")" 1

  : > "$log"
  printf 'Failed.\n' | NEEDS=1 LABELS="lane:platform" open_run runner-image "Runner image, run 8: build failed" >/dev/null
  check "a run that needs a person: labelled needs:maintainer" "$(grep -c -- '--label run:runner-image,lane:platform,needs:maintainer ' "$log")" 1
  check "a run that needs a person: stays open" "$(grep -c '^issue close' "$log")" 0
  check "every label is created when missing" "$(grep -c '^label create' "$log")" 3

  unset -f gh
  if [ "$fails" -ne 0 ]; then echo "$fails failed"; return 1; fi
  echo "all passed"
}

case "${1:-}" in
  --test) self_test ;;
  open) [ $# -eq 3 ] || { echo "usage: run-issue.sh open KIND TITLE < body" >&2; exit 64; }; open_run "$2" "$3" ;;
  *) sed -n '2,19p' "$0" >&2; exit 64 ;;
esac
