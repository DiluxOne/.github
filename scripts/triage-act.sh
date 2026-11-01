#!/usr/bin/env bash
# What the issue triage does with a verdict: writes the category it maps to
# in the board's state (#564, `verdict`, scripts/receipts.py: no label but
# `security`), posts the reply with the AI line and a record, locks a
# security report. Both triage jobs act here. A vulnerability posted
# in a public repository's issue (#287) is moved out of sight, into the
# organisation's private security repository (SECURITY_REPO, with
# SECURITY_TOKEN, which writes the issues and the contents of both, as an
# App needs to transfer an issue), where a private security
# advisory is opened for it, its author credited (advisory.py intake); the
# author does not have to delete anything. If the move fails, the issue is
# locked and the author asked to report it privately, as before.
#
# A defect gets the layer it shows in too, `layer` in the board's state
# (logic, browser, cli, api or workflow; #352; `workflow`, a CI workflow's
# wiring, #376), which the reproduction reads; one already there stays. A
# bug to reproduce gets `repro=unconfirmed` there (#564).
#
# Environment: VERDICT (JSON: category, layer, exists_in_pro, duplicate_of), REPLY
# and SUMMARY (the public text; an empty reply posts a plain one), PRIVATE
# (true in a private repository: a security report stays as the issue), NUMBER,
# MAINTAINER, MODEL, COST (optional), GITHUB_REPOSITORY, GH_TOKEN; AUTHOR (the
# issue's author), SECURITY_REPO and SECURITY_TOKEN (optional), DX_BOT_APP
# (whose board holds the state). A verdict with no category leaves the issue
# as it is, for a person, and stops.
#
#   triage-act.sh          act
#   triage-act.sh --test   self-test, with a stand-in for gh
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)

# The board's state of the issue (#564): `state get KEY`, `state set K=V…`.
state() { python3 "$HERE/receipts.py" state "$@"; }

# Whether the issue's Type was last set by a person who can write to the
# repository (#341): a maintainer's Type is theirs to change, their own
# report through a form included. No Type event (a form that set it at
# opening) or a bot's is not a maintainer's: #84 still retypes it. A read
# that fails counts as a maintainer's, so nothing is overwritten.
set_by_maintainer() {
  local who perm
  # shellcheck disable=SC2016 # GraphQL variables, not shell ones.
  who=$(gh api graphql -f query='query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){issue(number:$n){timelineItems(last:1,itemTypes:[ISSUE_TYPE_ADDED_EVENT,ISSUE_TYPE_CHANGED_EVENT]){nodes{... on IssueTypeAddedEvent{actor{__typename login}} ... on IssueTypeChangedEvent{actor{__typename login}}}}}}}' \
    -f o="${GITHUB_REPOSITORY%%/*}" -f r="${GITHUB_REPOSITORY#*/}" -F n="$NUMBER" \
    --jq '.data.repository.issue.timelineItems.nodes[0].actor | if . == null then "" elif .__typename == "Bot" then "bot" else .login end' 2>/dev/null) || return 0
  case $who in "" | bot | *"[bot]") return 1;; esac
  perm=$(gh api "repos/$GITHUB_REPOSITORY/collaborators/$who/permission" --jq .permission 2>/dev/null) || return 0
  case $perm in admin | maintain | write) return 0;; *) return 1;; esac
}

act() {
  local category verdict reply record dup kind
  if ! printf '%s' "${VERDICT:-}" | jq -e .category >/dev/null 2>&1; then
    echo "::warning::No classification came back; the issue stays as it is for a human."
    return 0
  fi
  category=$(jq -r .category <<<"$VERDICT")
  # An issue opened outside the forms (an agent, the API) has no Type: the
  # category gives it one. A bug report that is really a request (#84: a
  # feature, a planned or a paid one) is retyped Feature, so no fix and no
  # reproduction carries it in; it waits for a person's acceptance like any
  # request. Any other Type someone set is never changed, and neither is one
  # a maintainer set (#341): only a reporter's (the form's) or a bot's Bug.
  # A Bug a maintainer set is kept and recorded as a bug to reproduce
  # (#496), never as the request the classifier read: the state and the
  # layer follow the Type it keeps, the record still says what was read.
  # Only the state changes: the triage's `bug` output (repro-trigger.sh bug)
  # still reads the category, so no reproduction starts on its own; the
  # reply says a maintainer starts it with `/repro`.
  case $category in
    bug_unconfirmed|needs_info) kind=Bug;;
    # In a private repository the issue is the report (#194): a Bug.
    security) [ "${PRIVATE:-false}" = true ] && kind=Bug || kind="";;
    pro_feature|planned|enhancement) kind=Feature;;
    *) kind="";;
  esac
  local have retyped="" kept="" effective=$category
  have=$(gh api "repos/$GITHUB_REPOSITORY/issues/$NUMBER" --jq '.type.name // ""' 2>/dev/null || true)
  if [ "$have" = Bug ] && [ "$kind" = Feature ] && set_by_maintainer; then kind=""; kept=yes; effective=bug_unconfirmed; fi
  # The verdict, in the board's state (#564): `verdict`, and for a bug to
  # reproduce `repro=unconfirmed`. A security report keeps its label, a
  # warning a person reads at a glance.
  local sets=()
  case $effective in
    bug_unconfirmed) verdict=bug; sets+=(repro=unconfirmed);;
    needs_info) verdict=needs-info;;
    by_design) verdict=by-design;;
    pro_feature) verdict=pro-feature;;
    planned) verdict=planned;;
    enhancement) verdict=enhancement; [ "$(jq -r '.exists_in_pro // false' <<<"$VERDICT")" = true ] && verdict=exists-in-pro;;
    question) verdict=question;;
    duplicate) verdict=duplicate;;
    security) verdict=security;;
    *) echo "::warning::Unknown category '$category'; the issue waits for a person."; verdict="";;
  esac
  if [ "$verdict" = security ]; then
    gh label create security --repo "$GITHUB_REPOSITORY" --color B60205 --description "A vulnerability report; a person merges its fix" --force >/dev/null
    gh issue edit "$NUMBER" --repo "$GITHUB_REPOSITORY" --add-label security >/dev/null
  fi
  [ -z "$verdict" ] || sets+=("verdict=$verdict")
  # Where a defect shows (#352): the reproduction reads it to pick the way
  # the repository declares for that layer (scripts/repro-ways.py). Written
  # before the reproduction starts; one already there stays.
  local layer
  layer=$(jq -r '.layer // ""' <<<"$VERDICT")
  case "$effective:$layer" in
    bug_unconfirmed:logic | bug_unconfirmed:browser | bug_unconfirmed:cli | bug_unconfirmed:api | bug_unconfirmed:workflow | \
    needs_info:logic | needs_info:browser | needs_info:cli | needs_info:api | needs_info:workflow)
      [ -n "$(state get layer 2>/dev/null)" ] || sets+=("layer=$layer") ;;
  esac
  if [ "${#sets[@]}" -gt 0 ]; then
    state set "${sets[@]}" >/dev/null || echo "::warning::Could not write #$NUMBER's verdict on its board (${sets[*]})."
  fi
  if [ -n "$kind" ] && { [ -z "$have" ] || { [ "$have" = Bug ] && [ "$kind" = Feature ]; }; }; then
    if gh api -X PATCH "repos/$GITHUB_REPOSITORY/issues/$NUMBER" -f type="$kind" >/dev/null 2>&1; then
      [ -z "$have" ] || retyped=yes
    else
      echo "::warning::Could not set #$NUMBER's Type to $kind."
    fi
  fi
  reply=${REPLY:-}
  [ -n "${reply//[[:space:]]/}" ] || reply="Thanks! A maintainer will take a look."
  if [ -n "$kept" ]; then
    reply="$reply"$'\n\n'"A maintainer set this issue's Type to Bug, so it stays a Bug, unconfirmed. Its reproduction does not start on its own: a maintainer starts it by commenting /repro."
  fi
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
  echo "Issue #$NUMBER: $category (${verdict:-no verdict})${COST:+, \$$COST}."
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
  # And for the board's state (#564): `state get layer` answers HAS_LAYER.
  state() { printf 'state %s\n' "$*" >> "$log"; [ "$1 ${2:-}" != "get layer" ] || echo "${HAS_LAYER:-}"; }
  gh() { printf '%s\n' "$*" | tr '\n' ' ' >> "$log"; echo >> "$log"; case "$*" in "issue view 3 "*) echo OPEN;; "issue view 4 "*) echo CLOSED;; "api repos/o/r/issues/7 --jq .node_id") echo I_7;; "api repos/o/r/issues/7 --jq"*) echo "${HAS_TYPE:-}";; "api repos/o/sec --jq .node_id") echo R_1;; "api graphql -f query=query"*) [ -z "${GQL_FAILS:-}" ] || return 1; echo "${TYPE_BY:-}";; "api repos/o/r/collaborators/"*) [ -z "${PERM_FAILS:-}" ] || return 1; echo "${PERM:-read}";; "api graphql "*) [ -z "${MOVE_FAILS:-}" ] || return 1; echo 12;; "issue lock "*) [ -z "${LOCK_FAILS:-}" ] || return 1;; esac; }
  t() {
    local name=$1 want=$2
    : > "$log"
    ( NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1 ) || true
    if grep -qE -- "$want" "$log"; then echo "ok   $name"; else echo "FAIL $name: no call matching $want in"; cat "$log"; fail=1; fi
  }
  VERDICT='{"category":"needs_info"}' REPLY="Which version?" SUMMARY=s t "#564 a verdict is written in the board's state, not as a label" "^state set verdict=needs-info$"
  VERDICT='{"category":"needs_info"}' REPLY="Which version?" SUMMARY=s t "and posts the reply with the AI line" "issue comment 7 .*Which version\?.*AI triage · m"
  VERDICT='{"category":"pro_feature"}' REPLY="" SUMMARY=pro_feature t "an empty reply posts a plain one" "Thanks! A maintainer will take a look"
  VERDICT='{"category":"enhancement","exists_in_pro":true}' REPLY=x SUMMARY=s t "#564 a paid product's feature is recorded so" "^state set verdict=exists-in-pro$"
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
  # #341: a Bug a maintainer set stays; one the reporter's form or a bot set is retyped.
  : > "$log"; if ( VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s HAS_TYPE=Bug TYPE_BY=boss PERM=write NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1; grep -q "type=Feature" "$log" ); then echo "FAIL #341 a Bug a maintainer set is kept"; fail=1; else echo "ok   #341 a Bug a maintainer set is kept"; fi
  HAS_TYPE=Bug TYPE_BY=alice PERM=read VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s t "#341 a Bug the reporter set is still retyped" "api -X PATCH repos/o/r/issues/7 -f type=Feature"
  HAS_TYPE=Bug TYPE_BY=bot VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s t "#341 and so is one a bot set" "api -X PATCH repos/o/r/issues/7 -f type=Feature"
  HAS_TYPE=Bug TYPE_BY="" VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s t "#341 and one with no Type event (the form's at opening)" "api -X PATCH repos/o/r/issues/7 -f type=Feature"
  # #496: and it is recorded as the bug its maintainer says it is, never as a request.
  for v in '{"category":"enhancement"}' '{"category":"planned"}' '{"category":"pro_feature"}' '{"category":"enhancement","exists_in_pro":true}'; do
    : > "$log"; ( VERDICT=$v REPLY=x SUMMARY=s HAS_TYPE=Bug TYPE_BY=boss PERM=write NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1 ) || true
    if grep -q -- "^state set repro=unconfirmed verdict=bug" "$log" && ! grep -qE -- "verdict=(enhancement|exists-in-pro|planned|pro-feature)|--add-label" "$log"; then echo "ok   #496 a maintainer's Bug read as $v is recorded as a bug to reproduce"; else echo "FAIL #496 a maintainer's Bug read as $v is recorded as a bug to reproduce, and only that:"; cat "$log"; fail=1; fi
  done
  HAS_TYPE=Bug TYPE_BY=boss PERM=write VERDICT='{"category":"enhancement","layer":"cli"}' REPLY=x SUMMARY=s t "#496 and gets the layer the verdict names" "^state set repro=unconfirmed verdict=bug layer=cli$"
  HAS_TYPE=Bug TYPE_BY=boss PERM=write VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s t "#496 the record still says what the classifier read" '"category":"enhancement"'
  HAS_TYPE=Bug TYPE_BY=boss PERM=write VERDICT='{"category":"planned"}' REPLY=x SUMMARY=s t "#496 the reply says the Bug is kept and /repro starts its reproduction" "it stays a Bug, unconfirmed. Its reproduction does not start on its own: a maintainer starts it by commenting /repro."
  : > "$log"; ( VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s HAS_TYPE=Bug TYPE_BY=alice PERM=read NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1 ) || true
  if grep -q "starts it by commenting /repro" "$log"; then echo "FAIL #496 a retyped Bug's reply does not mention /repro"; fail=1; else echo "ok   #496 a retyped Bug's reply does not mention /repro"; fi
  HAS_TYPE=Bug TYPE_BY=alice PERM=read VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s t "#496 a reporter's Bug is still recorded as a request" "^state set verdict=enhancement$"
  for fails in GQL_FAILS PERM_FAILS; do
    : > "$log"; ( export "$fails=1"; VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s HAS_TYPE=Bug TYPE_BY=boss NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1 ) || true
    if grep -q -- "^state set repro=unconfirmed verdict=bug" "$log"; then echo "ok   #496 a read that fails ($fails) records the kept Bug as one to reproduce"; else echo "FAIL #496 a read that fails ($fails) records the kept Bug as one to reproduce"; fail=1; fi
  done
  for fails in GQL_FAILS PERM_FAILS; do
    : > "$log"; if ( export "$fails=1"; VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s HAS_TYPE=Bug TYPE_BY=boss NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1; grep -q "type=Feature" "$log" ); then echo "FAIL #341 a read that fails ($fails) keeps the Type"; fail=1; else echo "ok   #341 a read that fails ($fails) keeps the Type"; fi
  done
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
  # #352: the layer the defect shows in, in the board's state the reproduction reads (#564).
  VERDICT='{"category":"bug_unconfirmed","layer":"browser"}' REPLY=x SUMMARY=s t "#352 a browser bug gets layer=browser" "^state set repro=unconfirmed verdict=bug layer=browser$"
  VERDICT='{"category":"bug_unconfirmed","layer":"logic"}' REPLY=x SUMMARY=s t "#352 a logic bug gets layer=logic" "^state set repro=unconfirmed verdict=bug layer=logic$"
  VERDICT='{"category":"bug_unconfirmed","layer":"workflow"}' REPLY=x SUMMARY=s t "#376 a bug in a workflow's wiring gets layer=workflow" "^state set repro=unconfirmed verdict=bug layer=workflow$"
  VERDICT='{"category":"needs_info","layer":"cli"}' REPLY=x SUMMARY=s t "#352 a report that needs info keeps its layer" "^state set verdict=needs-info layer=cli$"
  : > "$log"; if ( VERDICT='{"category":"enhancement","layer":"browser"}' REPLY=x SUMMARY=s NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1; grep -q "layer=" "$log" ); then echo "FAIL #352 a request gets no layer"; fail=1; else echo "ok   #352 a request gets no layer"; fi
  : > "$log"; if ( VERDICT='{"category":"bug_unconfirmed","layer":"screen"}' REPLY=x SUMMARY=s NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1; grep -q "layer=" "$log" ); then echo "FAIL #352 an unknown layer is none"; fail=1; else echo "ok   #352 an unknown layer is none"; fi
  : > "$log"; if ( HAS_LAYER=browser VERDICT='{"category":"bug_unconfirmed","layer":"logic"}' REPLY=x SUMMARY=s NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1; grep -q "layer=logic" "$log" ); then echo "FAIL #352 a layer already there stays"; fail=1; else echo "ok   #352 a layer already there stays"; fi
  # #564: no label but security, ever; a verdict that never came writes nothing.
  for v in '{"category":"needs_info"}' '{"category":"bug_unconfirmed","layer":"cli"}' '{"category":"duplicate","duplicate_of":3}' '{"category":"question"}' '' '{"category":"nonsense"}'; do
    : > "$log"; ( VERDICT=$v REPLY=x SUMMARY=s NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1 ) || true
    if grep -qE -- "--add-label|--remove-label|label create" "$log"; then echo "FAIL #564 $v adds or creates no label:"; cat "$log"; fail=1; else echo "ok   #564 $v adds or creates no label"; fi
  done
  VERDICT='{"category":"security"}' REPLY=x SUMMARY=s t "#564 a security report keeps its label" "issue edit 7 --repo o/r --add-label security"
  : > "$log"; ( VERDICT='' REPLY=x SUMMARY=s NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1 ) || true
  if [ -s "$log" ]; then echo "FAIL no verdict leaves the issue as it is, for a person"; cat "$log"; fail=1; else echo "ok   no verdict leaves the issue as it is, for a person"; fi
  : > "$log"; ( VERDICT='{"category":"nonsense"}' REPLY=x SUMMARY=s NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1 ) || true
  if grep -q "^state set" "$log"; then echo "FAIL an unknown category records no verdict"; fail=1; else echo "ok   an unknown category records no verdict"; fi
  # The state for real: receipts.py writes it on the issue's board (a fixture for GitHub's comments).
  fx=$(mktemp -d)
  ( state() { python3 "$HERE/receipts.py" state "$@"; }; gh() { :; }; VERDICT='{"category":"bug_unconfirmed","layer":"api"}' REPLY=x SUMMARY=s NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m DX_BOT_APP=dilux-bot STATE_FIXTURE="$fx/c.json" act >/dev/null 2>&1 ) || true
  got=$(STATE_FIXTURE="$fx/c.json" NUMBER=7 GITHUB_REPOSITORY=o/r DX_BOT_APP=dilux-bot python3 "$HERE/receipts.py" state get 2>/dev/null || true)
  if [ "$(jq -c . <<<"${got:-null}" 2>/dev/null)" = '{"layer":"api","repro":"unconfirmed","verdict":"bug"}' ]; then echo "ok   #564 the verdict lands on the issue's board"; else echo "FAIL #564 the verdict lands on the issue's board (got $got)"; fail=1; fi
  rm -rf "$fx"
  rm -f "$log"
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

act
