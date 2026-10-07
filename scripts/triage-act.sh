#!/usr/bin/env bash
# What the issue triage does with a verdict: creates its labels, applies the
# one the category maps to, posts the reply with the AI line and a record,
# locks a security report. Both triage jobs act here.
#
# Environment: VERDICT (JSON: category, exists_in_pro, duplicate_of), REPLY
# and SUMMARY (the public text; an empty reply posts a plain one), NUMBER,
# MAINTAINER, MODEL, COST (optional), GITHUB_REPOSITORY, GH_TOKEN. A verdict
# with no category labels the issue needs-triage and stops.
#
#   triage-act.sh          act
#   triage-act.sh --test   self-test, with a stand-in for gh
set -euo pipefail

act() {
  local category label reply record dup
  if ! printf '%s' "${VERDICT:-}" | jq -e .category >/dev/null 2>&1; then
    echo "::warning::No classification came back; the issue stays as it is for a human."
    gh issue edit "$NUMBER" --repo "$GITHUB_REPOSITORY" --add-label needs-triage >/dev/null 2>&1 || true
    return 0
  fi
  for l in "bug:unconfirmed|D93F0B|A bug report worth a reproduction attempt (repro:run starts one)" "needs-info|E4E669|Waiting for versions, steps or logs" "by-design|BFDADC|Works as documented, or a known limitation" "pro-feature|5319E7|Needs the paid service or add-on" "planned|0E8A16|Already planned" "exists-in-pro|5319E7|A paid product already has it" "question|D876E3|A usage question; the support channel has it" "security|B60205|A vulnerability; report it privately" "enhancement|A2EEEF|New feature or request" "duplicate|CFD3D7|An open issue already covers it" "needs-triage|E4E669|Not looked at yet"; do
    IFS='|' read -r name color desc <<<"$l"
    gh label create "$name" --repo "$GITHUB_REPOSITORY" --color "$color" --description "$desc" --force >/dev/null
  done
  category=$(jq -r .category <<<"$VERDICT")
  case $category in
    bug_unconfirmed) label="bug:unconfirmed";;
    needs_info) label="needs-info";;
    by_design) label="by-design";;
    pro_feature) label="pro-feature";;
    planned) label="planned";;
    enhancement) label="enhancement"; [ "$(jq -r '.exists_in_pro // false' <<<"$VERDICT")" = true ] && label="enhancement,exists-in-pro";;
    question) label="question";;
    duplicate) label="duplicate";;
    security) label="security";;
    *) echo "::warning::Unknown category '$category'; the issue waits for a person."; label="needs-triage";;
  esac
  gh issue edit "$NUMBER" --repo "$GITHUB_REPOSITORY" --add-label "$label" --remove-label needs-triage >/dev/null 2>&1 || gh issue edit "$NUMBER" --repo "$GITHUB_REPOSITORY" --add-label "$label" >/dev/null
  reply=${REPLY:-}
  [ -n "${reply//[[:space:]]/}" ] || reply="Thanks! A maintainer will take a look."
  # The original is named only when it is an open issue of this repository,
  # other than this one: a number is all the classifier hands over, and a
  # made-up one names nothing.
  dup=$(jq -r '.duplicate_of // 0' <<<"$VERDICT")
  if [ "$category" = duplicate ] && [[ "$dup" =~ ^[1-9][0-9]{0,5}$ ]] && [ "$dup" != "$NUMBER" ] \
     && [ "$(gh issue view "$dup" --repo "$GITHUB_REPOSITORY" --json state --jq .state 2>/dev/null)" = OPEN ]; then
    reply="$reply"$'\n\n'"Duplicate of #$dup."
  fi
  if [ "$category" = security ]; then reply="$reply"$'\n\n'"@$MAINTAINER"; fi
  record=$(jq -c --arg cost "${COST:-}" --arg summary "${SUMMARY:-}" '{category, exists_in_pro: (.exists_in_pro // false), duplicate_of: (.duplicate_of // null), summary: $summary, cost: $cost}' <<<"$VERDICT")
  gh issue comment "$NUMBER" --repo "$GITHUB_REPOSITORY" --body "$(printf '%s\n\n<sub>🤖 AI triage · %s (Anthropic)</sub>\n<!-- dx-triage-record %s -->' "$reply" "$MODEL" "$record")" >/dev/null
  if [ "$category" = security ]; then gh issue lock "$NUMBER" --repo "$GITHUB_REPOSITORY" --reason off-topic >/dev/null; fi
  echo "Issue #$NUMBER: $category ($label)${COST:+, \$$COST}."
}

if [ "${1:-}" = "--test" ]; then
  fail=0
  log=$(mktemp)
  # A stand-in for gh that records every call, one line each.
  gh() { printf '%s\n' "$*" | tr '\n' ' ' >> "$log"; echo >> "$log"; case "$*" in "issue view 3 "*) echo OPEN;; "issue view 4 "*) echo CLOSED;; esac; }
  t() {
    local name=$1 want=$2
    : > "$log"
    ( NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1 ) || true
    if grep -qE -- "$want" "$log"; then echo "ok   $name"; else echo "FAIL $name: no call matching $want in"; cat "$log"; fail=1; fi
  }
  VERDICT='{"category":"needs_info"}' REPLY="Which version?" SUMMARY=s t "a verdict labels the issue" "issue edit 7 --repo o/r --add-label needs-info"
  VERDICT='{"category":"needs_info"}' REPLY="Which version?" SUMMARY=s t "and posts the reply with the AI line" "issue comment 7 .*Which version\?.*AI triage · m"
  VERDICT='{"category":"pro_feature"}' REPLY="" SUMMARY=pro_feature t "an empty reply posts a plain one" "Thanks! A maintainer will take a look"
  VERDICT='{"category":"enhancement","exists_in_pro":true}' REPLY=x SUMMARY=s t "a paid product's feature gets both labels" "--add-label enhancement,exists-in-pro"
  VERDICT='{"category":"duplicate","duplicate_of":3}' REPLY=x SUMMARY=s t "a duplicate names the original" "Duplicate of #3"
  VERDICT='{"category":"duplicate","duplicate_of":4}' REPLY=x SUMMARY=s t "a closed original is not named" "issue comment 7 --repo o/r --body x  <sub>"
  VERDICT='{"category":"duplicate","duplicate_of":31337}' REPLY=x SUMMARY=s t "a number that is no open issue names nothing" "issue comment 7 --repo o/r --body x  <sub>"
  VERDICT='{"category":"security"}' REPLY=x SUMMARY=s t "a security report is locked" "issue lock 7"
  VERDICT='' REPLY=x SUMMARY=s t "no verdict waits for a person" "--add-label needs-triage"
  VERDICT='{"category":"nonsense"}' REPLY=x SUMMARY=s t "an unknown category waits for a person" "--add-label needs-triage"
  rm -f "$log"
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

act
