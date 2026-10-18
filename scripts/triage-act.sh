#!/usr/bin/env bash
# What the issue triage does with a verdict: creates its labels, applies the
# one the category maps to, posts the reply with the AI line and a record,
# locks a security report. Both triage jobs act here. A vulnerability posted
# in a public repository's issue (#287) is moved out of sight, into the
# organisation's private security repository (SECURITY_REPO, with
# SECURITY_TOKEN, which writes the issues of both), where a private security
# advisory is opened for it, its author credited (advisory.py intake); the
# author does not have to delete anything. If the move fails, the issue is
# locked and the author asked to report it privately, as before.
#
# Environment: VERDICT (JSON: category, exists_in_pro, duplicate_of), REPLY
# and SUMMARY (the public text; an empty reply posts a plain one), PRIVATE
# (true in a private repository: a security report stays as the issue), NUMBER,
# MAINTAINER, MODEL, COST (optional), GITHUB_REPOSITORY, GH_TOKEN; AUTHOR (the
# issue's author), SECURITY_REPO and SECURITY_TOKEN (optional). A verdict
# with no category labels the issue needs-triage and stops.
#
#   triage-act.sh          act
#   triage-act.sh --test   self-test, with a stand-in for gh
set -euo pipefail

act() {
  local category label reply record dup kind
  if ! printf '%s' "${VERDICT:-}" | jq -e .category >/dev/null 2>&1; then
    echo "::warning::No classification came back; the issue stays as it is for a human."
    gh issue edit "$NUMBER" --repo "$GITHUB_REPOSITORY" --add-label needs-triage >/dev/null 2>&1 || true
    return 0
  fi
  for l in "bug:unconfirmed|D93F0B|A bug report: a reproduction starts on its own (repro:run starts one by hand)" "needs-info|E4E669|Waiting for versions, steps or logs" "by-design|BFDADC|Works as documented, or a known limitation" "pro-feature|5319E7|Needs the paid service or add-on" "planned|0E8A16|Already planned" "exists-in-pro|5319E7|A paid product already has it" "question|D876E3|A usage question; the support channel has it" "security|B60205|A vulnerability report; a person merges its fix" "enhancement|A2EEEF|New feature or request" "duplicate|CFD3D7|An open issue already covers it" "needs-triage|E4E669|Not looked at yet"; do
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
  # An issue opened outside the forms (an agent, the API) has no Type: the
  # category gives it one. A bug report that is really a request (#84: a
  # feature, a planned or a paid one) is retyped Feature, so no fix and no
  # reproduction carries it in; it waits for a person's acceptance like any
  # request. Any other Type someone set is never changed.
  case $category in
    bug_unconfirmed|needs_info) kind=Bug;;
    # In a private repository the issue is the report (#194): a Bug.
    security) [ "${PRIVATE:-false}" = true ] && kind=Bug || kind="";;
    pro_feature|planned|enhancement) kind=Feature;;
    *) kind="";;
  esac
  local have retyped=""
  have=$(gh api "repos/$GITHUB_REPOSITORY/issues/$NUMBER" --jq '.type.name // ""' 2>/dev/null || true)
  if [ -n "$kind" ] && { [ -z "$have" ] || { [ "$have" = Bug ] && [ "$kind" = Feature ]; }; }; then
    if gh api -X PATCH "repos/$GITHUB_REPOSITORY/issues/$NUMBER" -f type="$kind" >/dev/null 2>&1; then
      [ -z "$have" ] || retyped=yes
    else
      echo "::warning::Could not set #$NUMBER's Type to $kind."
    fi
  fi
  reply=${REPLY:-}
  [ -n "${reply//[[:space:]]/}" ] || reply="Thanks! A maintainer will take a look."
  if [ -n "$retyped" ]; then
    reply="$reply"$'\n\n'"This reads as a request for something new rather than a defect, so its Type is now Feature: a maintainer decides whether to accept it."
  fi
  # The original is named only when it is an open issue of this repository,
  # other than this one: a number is all the classifier hands over, and a
  # made-up one names nothing.
  dup=$(jq -r '.duplicate_of // 0' <<<"$VERDICT")
  if [ "$category" = duplicate ] && [[ "$dup" =~ ^[1-9][0-9]{0,5}$ ]] && [ "$dup" != "$NUMBER" ] \
     && [ "$(gh issue view "$dup" --repo "$GITHUB_REPOSITORY" --json state --jq .state 2>/dev/null)" = OPEN ]; then
    reply="$reply"$'\n\n'"Duplicate of #$dup."
  else
    dup=""
  fi
  # A private repository has no private reporting (#194): only those with
  # access see the issue, so it stays, unlocked, as the report; it follows
  # the usual lane once accepted, and a person merges its fix.
  if [ "$category" = security ] && [ "${PRIVATE:-false}" = true ]; then
    reply="Thanks for reporting this. This repository is private, so this issue is the report: a maintainer will look at it, and the fix is always merged by a person."
  fi
  # A public one is moved where only the maintainers see it (#287): the
  # reply says so, in our words, never the classifier's.
  local move=""
  if [ "$category" = security ] && [ "${PRIVATE:-false}" != true ] && [ -n "${SECURITY_REPO:-}" ] && [ -n "${SECURITY_TOKEN:-}" ]; then
    move=yes
    reply="Thanks for reporting this. Security reports are handled in private: this issue is being moved where only the maintainers can see it, and a private security advisory is opened for it, with you credited and invited to follow it there. Please do not post more details here."
  fi
  if [ "$category" = security ]; then reply="$reply"$'\n\n'"@$MAINTAINER"; fi
  # The record is public too: only the checked duplicate goes in it.
  record=$(jq -c --arg cost "${COST:-}" --arg summary "${SUMMARY:-}" --arg dup "$dup" '{category, exists_in_pro: (.exists_in_pro == true), duplicate_of: (if $dup == "" then null else ($dup | tonumber) end), summary: $summary, cost: $cost}' <<<"$VERDICT")
  local intake=""
  if [ -n "$move" ] && [[ "${AUTHOR:-}" =~ ^[A-Za-z0-9-]+$ ]]; then
    intake=$'\n'"<!-- dx-security-intake: repo=$GITHUB_REPOSITORY reporter=$AUTHOR -->"
  elif [ -n "$move" ]; then
    intake=$'\n'"<!-- dx-security-intake: repo=$GITHUB_REPOSITORY reporter= -->"
  fi
  gh issue comment "$NUMBER" --repo "$GITHUB_REPOSITORY" --body "$(printf '%s\n\n<sub>🤖 AI triage · %s (Anthropic)</sub>\n<!-- dx-triage-record %s -->%s' "$reply" "$MODEL" "$record" "$intake")" >/dev/null
  if [ -n "$move" ] && move_private; then
    echo "Issue #$NUMBER: security, moved to $SECURITY_REPO."
    return 0
  fi
  if [ "$category" = security ] && [ "${PRIVATE:-false}" != true ]; then
    [ -z "$move" ] || gh issue comment "$NUMBER" --repo "$GITHUB_REPOSITORY" --body "$(printf 'It could not be moved: please report it privately instead (this repository'"'"'s Security tab, "Report a vulnerability"), and remove the details from here.\n\n<sub>🤖 AI triage · %s (Anthropic)</sub>' "$MODEL")" >/dev/null
    gh issue lock "$NUMBER" --repo "$GITHUB_REPOSITORY" --reason off_topic >/dev/null \
      || echo "::warning::#$NUMBER could not be locked: a maintainer locks it and hides the details."
  fi
  echo "Issue #$NUMBER: $category ($label)${COST:+, \$$COST}."
}

# The issue, moved into the security repository (GitHub keeps its comments
# and history there and shows a "moved" banner here), labelled for the
# intake that opens its advisory. Fails, saying nothing, when it cannot.
move_private() {
  local issue_id repo_id moved
  issue_id=$(gh api "repos/$GITHUB_REPOSITORY/issues/$NUMBER" --jq .node_id) || return 1
  repo_id=$(GH_TOKEN="$SECURITY_TOKEN" gh api "repos/$SECURITY_REPO" --jq .node_id) || return 1
  # shellcheck disable=SC2016 # GraphQL variables, not shell ones.
  moved=$(GH_TOKEN="$SECURITY_TOKEN" gh api graphql -f query='mutation($i:ID!,$r:ID!){transferIssue(input:{issueId:$i,repositoryId:$r,createLabelsIfMissing:true}){issue{number}}}' \
    -f i="$issue_id" -f r="$repo_id" --jq .data.transferIssue.issue.number) || return 1
  [[ "$moved" =~ ^[0-9]+$ ]] || return 1
  GH_TOKEN="$SECURITY_TOKEN" gh label create "security:intake" --repo "$SECURITY_REPO" --color B60205 --description "A vulnerability moved here from a public issue: its advisory opens next" --force >/dev/null 2>&1 || true
  # Moved is what matters here: a label that does not stick is said, and
  # the issue is out of sight either way.
  GH_TOKEN="$SECURITY_TOKEN" gh issue edit "$moved" --repo "$SECURITY_REPO" --add-label "security:intake" >/dev/null \
    || echo "::warning::$SECURITY_REPO#$moved could not be labelled security:intake: a maintainer adds it, and its advisory opens on the next run."
}

if [ "${1:-}" = "--test" ]; then
  fail=0
  log=$(mktemp)
  # A stand-in for gh that records every call, one line each.
  gh() { printf '%s\n' "$*" | tr '\n' ' ' >> "$log"; echo >> "$log"; case "$*" in "issue view 3 "*) echo OPEN;; "issue view 4 "*) echo CLOSED;; "api repos/o/r/issues/7 --jq .node_id") echo I_7;; "api repos/o/r/issues/7 --jq"*) echo "${HAS_TYPE:-}";; "api repos/o/sec --jq .node_id") echo R_1;; "api graphql "*) [ -z "${MOVE_FAILS:-}" ] || return 1; echo 12;; "issue lock "*) [ -z "${LOCK_FAILS:-}" ] || return 1;; esac; }
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
  VERDICT='{"category":"duplicate","duplicate_of":31337}' REPLY=x SUMMARY=s t "nor does the record carry it" '"duplicate_of":null'
  VERDICT='{"category":"needs_info","duplicate_of":3}' REPLY=x SUMMARY=s t "a number outside a duplicate is not recorded" '"duplicate_of":null'
  VERDICT='{"category":"duplicate","duplicate_of":3}' REPLY=x SUMMARY=s t "a real duplicate is recorded" '"duplicate_of":3'
  VERDICT='{"category":"needs_info"}' REPLY=x SUMMARY=s t "an issue with no Type gets the category's" "api -X PATCH repos/o/r/issues/7 -f type=Bug"
  VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s t "a request gets Feature" "api -X PATCH repos/o/r/issues/7 -f type=Feature"
  : > "$log"; if ( VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s HAS_TYPE=Task NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1; grep -q "type=Feature" "$log" ); then echo "FAIL a Type someone set is kept"; fail=1; else echo "ok   a Type someone set is kept"; fi
  : > "$log"; if ( VERDICT='{"category":"needs_info"}' REPLY=x SUMMARY=s HAS_TYPE=Feature NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1; grep -q "type=Bug" "$log" ); then echo "FAIL a Feature is never made a Bug"; fail=1; else echo "ok   a Feature is never made a Bug"; fi
  # #84: a bug report that is really a request is retyped, says so, and waits.
  HAS_TYPE=Bug VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s t "#84 a Bug the triage reads as a request becomes a Feature" "api -X PATCH repos/o/r/issues/7 -f type=Feature"
  HAS_TYPE=Bug VERDICT='{"category":"planned"}' REPLY=x SUMMARY=s t "#84 and the reply says so, and that a maintainer decides" "issue comment 7 .*its Type is now Feature: a maintainer decides"
  HAS_TYPE=Bug VERDICT='{"category":"pro_feature"}' REPLY=x SUMMARY=s t "#84 a paid request too" "-f type=Feature"
  : > "$log"; if ( VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s HAS_TYPE=Bug NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1; grep -q "add-label accepted" "$log" ); then echo "FAIL #84 a retyped request is never accepted"; fail=1; else echo "ok   #84 a retyped request is never accepted"; fi
  : > "$log"; if ( VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s HAS_TYPE="" NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1; grep -q "its Type is now Feature" "$log" ); then echo "FAIL an issue with no Type gets one without the retype sentence"; fail=1; else echo "ok   an issue with no Type gets one without the retype sentence"; fi
  VERDICT='{"category":"security"}' REPLY=x SUMMARY=s t "a security report is locked, for a reason gh takes (#311)" "issue lock 7 .*--reason off_topic"
  VERDICT='{"category":"security"}' REPLY="the AI's words" SUMMARY=s AUTHOR=alice SECURITY_REPO=o/sec SECURITY_TOKEN=t t "#287 a public one is moved to the security repository" "transferIssue"
  VERDICT='{"category":"security"}' REPLY="the AI's words" SUMMARY=s AUTHOR=alice SECURITY_REPO=o/sec SECURITY_TOKEN=t t "#287 with the intake marker naming its author" "dx-security-intake: repo=o/r reporter=alice"
  VERDICT='{"category":"security"}' REPLY="the AI's words" SUMMARY=s AUTHOR=alice SECURITY_REPO=o/sec SECURITY_TOKEN=t t "#287 and labelled for the intake there" "issue edit 12 --repo o/sec --add-label security:intake"
  : > "$log"; if ( VERDICT='{"category":"security"}' REPLY="the AI's words" SUMMARY=s AUTHOR=alice SECURITY_REPO=o/sec SECURITY_TOKEN=t NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1; grep -qE "issue lock|the AI's words" "$log" ); then echo "FAIL #287 moved: not locked, and the reply is ours"; fail=1; else echo "ok   #287 moved: not locked, and the reply is ours"; fi
  # Outside a condition, where bash would suspend `set -e`.
  set +e; ( set -e; LOCK_FAILS=1 VERDICT='{"category":"security"}' REPLY=x SUMMARY=s NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1 ); rc=$?; set -e
  if [ "$rc" = 0 ]; then echo "ok   #311 a lock that fails is said, and the run goes on"; else echo "FAIL #311 a lock that fails ends the run"; fail=1; fi
  wf="$(dirname "$0")/../.github/workflows/issue-triage.yml"
  if [ "$(awk '/id: sectoken/{s=1} s&&/permission-contents: write/{n++; s=0} /^      - name:/&&!/dilux-bot token \(this repository and the security one\)/{s=0} END{print n+0}' "$wf")" = 2 ] && [ "$(grep -c 'id: sectoken' "$wf")" = 2 ]; then echo "ok   #311 both security tokens can transfer an issue (issues and contents write)"; else echo "FAIL #311 a security token lacks contents: write, so transferIssue is refused"; fail=1; fi
  MOVE_FAILS=1 VERDICT='{"category":"security"}' REPLY=x SUMMARY=s AUTHOR=alice SECURITY_REPO=o/sec SECURITY_TOKEN=t t "#287 a move that fails locks it and asks for a private report" "issue lock 7 .*--reason off_topic"
  PRIVATE=true VERDICT='{"category":"security"}' REPLY=x SUMMARY=s t "#194 in a private repository a security report is a Bug" "api -X PATCH repos/o/r/issues/7 -f type=Bug"
  PRIVATE=true VERDICT='{"category":"security"}' REPLY="report it privately" SUMMARY=s t "#194 and the reply says the issue is the report" "issue comment 7 .*this issue is the report.*@boss"
  : > "$log"; if ( PRIVATE=true VERDICT='{"category":"security"}' REPLY="report it privately" SUMMARY=s NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1; grep -qE "issue lock|issue comment .*report it privately" "$log" ); then echo "FAIL #194 nor locked, nor sent to private reporting"; fail=1; else echo "ok   #194 nor locked, nor sent to private reporting"; fi
  VERDICT='' REPLY=x SUMMARY=s t "no verdict waits for a person" "--add-label needs-triage"
  VERDICT='{"category":"nonsense"}' REPLY=x SUMMARY=s t "an unknown category waits for a person" "--add-label needs-triage"
  rm -f "$log"
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

act
