#!/usr/bin/env bash
# What the issue triage does with a verdict: creates its labels, applies the
# one the category maps to, posts the reply with the AI line and a record,
# locks a security report. Both triage jobs act here. A vulnerability posted
# in a public repository's issue (#287) is moved out of sight, into the
# organisation's private security repository (SECURITY_REPO, with
# SECURITY_TOKEN, which writes the issues and the contents of both, as an
# App needs to transfer an issue), where a private security
# advisory is opened for it, its author credited (advisory.py intake); the
# author does not have to delete anything. If the move fails, the issue is
# locked and the author asked to report it privately, as before.
#
# A defect gets the layer it shows in as a label too, `layer:<logic|browser|
# cli|api|workflow>` (#352; `workflow`, a CI workflow's wiring, #376), which
# the reproduction reads; one already there stays.
#
# Environment: VERDICT (JSON: category, layer, exists_in_pro, duplicate_of), REPLY
# and SUMMARY (the public text; an empty reply posts a plain one), PRIVATE
# (true in a private repository: a security report stays as the issue), NUMBER,
# MAINTAINER (who a security report mentions; else org.yml `maintainers`),
# MODEL, COST (optional), GITHUB_REPOSITORY, GH_TOKEN; AUTHOR (the
# issue's author), SECURITY_REPO and SECURITY_TOKEN (optional). A verdict
# with no category labels the issue needs-triage and stops.
#
# A maintainer's own Bug (C2, #564) is not an outside reporter's report:
# `own-bug` runs before the triage, and when the issue's Type is Bug and its
# author's role on the repository is maintain or admin, nothing classifies
# it, no `bug:unconfirmed` nor `layer:` goes on, and no reproduction starts
# (the autopilot's test-first still writes its failing test). Complete (G1,
# scripts/issue-schema.py), it is accepted with its writing: its PRD sealed
# on the receipts branch in its author's name (receipts.py seal-prd,
# ACCEPTED_HOW=own-bug, with SEAL_TOKEN, which writes contents), then
# `accepted`, and the board; the gate (issue-gate.sh) and the autopilot
# (autopilot.py lane) read that seal as the author's acceptance.
# Incomplete, it gets `incomplete` from the G1 check and waits on its author
# like any other. It writes own=true|false and accepted=true|false to
# GITHUB_OUTPUT; a read that fails is no maintainer's: the triage reads it.
# `own-bug-check` only prints yes or no (issue-accepted.yml's G1 check
# leaves a complete one to the triage). Environment: AUTHOR, BODY (a file
# holding the issue's body), NUMBER, GITHUB_REPOSITORY, GH_TOKEN, SEAL_TOKEN,
# POLICY_REF (optional).
#
#   triage-act.sh                 act
#   triage-act.sh own-bug         a maintainer's own Bug: accept it, or not
#   triage-act.sh own-bug-check   whether the issue is one (yes|no)
#   triage-act.sh --test          self-test, with a stand-in for gh
set -euo pipefail

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

# What happens next (C5, #564): the triage's first reply opens with it, and
# README.md, CONTRIBUTING.md and agents-block.md (every repository's
# AGENTS.md) open with the same words (the self-test keeps them in step).
NEXT="Then a maintainer decides whether to accept it (the \`accepted\` label); once it is accepted, the autopilot writes the code in the organisation's runners (GitHub Actions) and opens the pull request. If you want to write the code yourself, comment \`/claim\` on the issue (or tick \"I want to work on this myself\" in its form) before it is accepted, and the autopilot steps aside."

# The opening of the first reply: what happens next, and whom it waits on
# now ($1, the category: a report missing something waits on its author).
next_steps() {
  local who="It waits on a maintainer's acceptance now; the issue's board says whom it waits on as it moves."
  [ "$1" != needs_info ] || who="It waits on you now: the reply below says what is missing; the issue's board says whom it waits on as it moves."
  printf '**What happens next.** This triage reads every new issue first. %s %s' "$NEXT" "$who"
}

# Whether issue $NUMBER is a maintainer's own Bug (#564): its Type is Bug and
# AUTHOR's role on the repository is maintain or admin (the REST answer's
# role_name; its legacy `permission` says write for maintain). Prints yes or
# no; a read that fails prints no, so the triage reads it as any other.
own_bug() {
  local type role
  [[ "${AUTHOR:-}" =~ ^[A-Za-z0-9-]{1,39}$ ]] || { echo no; return 0; }
  type=$(gh api "repos/$GITHUB_REPOSITORY/issues/$NUMBER" --jq '.type.name // ""' 2>/dev/null) || { echo no; return 0; }
  [ "$type" = Bug ] || { echo no; return 0; }
  role=$(gh api "repos/$GITHUB_REPOSITORY/collaborators/$AUTHOR/permission" --jq '.role_name // .permission' 2>/dev/null) || { echo no; return 0; }
  case $role in admin | maintain) echo yes;; *) echo no;; esac
}

# The issue's board, created or updated (receipts.py board): the one bot
# comment that starts with its marker.
board_upsert() {
  local board id
  board=$(python3 "$(dirname "${BASH_SOURCE[0]}")/receipts.py" board) || return 1
  # shellcheck disable=SC2016 # jq's env, not the shell's.
  id=$(gh api "repos/$GITHUB_REPOSITORY/issues/$NUMBER/comments" --paginate --jq '.[] | select(.user.type == "Bot" and (.body | startswith("<!-- dx-board -->"))) | .id' 2>/dev/null | tail -1)
  if [ -n "$id" ]; then gh api -X PATCH "repos/$GITHUB_REPOSITORY/issues/comments/$id" -f body="$board" >/dev/null
  else gh issue comment "$NUMBER" --repo "$GITHUB_REPOSITORY" --body "$board" >/dev/null; fi
}

own_accept() {
  local out=${GITHUB_OUTPUT:-/dev/null} here ready reply
  here=$(dirname "${BASH_SOURCE[0]}")
  if [ "$(own_bug)" != yes ]; then
    { echo "own=false"; echo "accepted=false"; } >> "$out"
    echo "Issue #$NUMBER: not a maintainer's own Bug; the triage reads it."
    return 0
  fi
  echo "own=true" >> "$out"
  ready=$(python3 "$here/issue-schema.py" check < "$BODY" 2>/dev/null | jq -r '.ok // false' 2>/dev/null || true)
  if [ "$ready" != true ]; then
    echo "accepted=false" >> "$out"
    reply="You wrote this Bug with the maintain or admin role, so it skips the outside reporter's triage and reproduction. It is \`incomplete\` for now: the G1 comment says what is missing. Once it is complete, add \`accepted\` and the autopilot codes it in the organisation's runners, starting from a failing test."
    gh issue comment "$NUMBER" --repo "$GITHUB_REPOSITORY" --body "$(printf '%s\n\n🤖 AI-generated · Claude Opus 5.5 (Anthropic)' "$reply")" >/dev/null
    echo "Issue #$NUMBER: a maintainer's own Bug, incomplete; it waits on its author."
    return 0
  fi
  # The seal first: the gate and the autopilot read the acceptance from it.
  if ! GH_TOKEN=${SEAL_TOKEN:-${GH_TOKEN:-}} ACCEPTED_BY=$AUTHOR ACCEPTED_HOW=own-bug python3 "$here/receipts.py" seal-prd >/dev/null; then
    echo "accepted=false" >> "$out"
    echo "::warning::#$NUMBER's PRD could not be sealed; it waits for its author's \`accepted\`."
    gh issue comment "$NUMBER" --repo "$GITHUB_REPOSITORY" --body "$(printf '%s\n\n🤖 AI-generated · Claude Opus 5.5 (Anthropic)' "You wrote this Bug with the maintain or admin role, so it skips the outside reporter's triage and reproduction; its PRD could not be sealed now, so add \`accepted\` yourself to start the autopilot.")" >/dev/null
    return 0
  fi
  gh label create accepted --repo "$GITHUB_REPOSITORY" --color 0E8A16 --description "A maintainer accepted it: the autopilot may start" >/dev/null 2>&1 || true
  gh issue edit "$NUMBER" --repo "$GITHUB_REPOSITORY" --add-label accepted >/dev/null
  for l in awaiting-acceptance incomplete needs-triage; do
    gh issue edit "$NUMBER" --repo "$GITHUB_REPOSITORY" --remove-label "$l" >/dev/null 2>&1 || true
  done
  echo "accepted=true" >> "$out"
  board_upsert || echo "::warning::#$NUMBER's board could not be written."
  reply="You wrote this Bug with the maintain or admin role, so it is accepted with its writing: no triage classifies it and no reproduction runs, and its PRD is sealed in your name. The autopilot codes it now in the organisation's runners, starting from a failing test."
  gh issue comment "$NUMBER" --repo "$GITHUB_REPOSITORY" --body "$(printf '%s\n\n🤖 AI-generated · Claude Opus 5.5 (Anthropic)' "$reply")" >/dev/null
  echo "Issue #$NUMBER: a maintainer's own Bug, accepted and sealed by @$AUTHOR."
}

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
  # An issue opened outside the forms (an agent, the API) has no Type: the
  # category gives it one. A bug report that is really a request (#84: a
  # feature, a planned or a paid one) is retyped Feature, so no fix and no
  # reproduction carries it in; it waits for a person's acceptance like any
  # request. Any other Type someone set is never changed, and neither is one
  # a maintainer set (#341): only a reporter's (the form's) or a bot's Bug.
  # A Bug a maintainer set is kept and labelled bug:unconfirmed (#496),
  # never as the request the classifier read: the labels and the layer
  # follow the Type it keeps, the record still says what was read. Only the
  # label changes: the triage's `bug` output (repro-trigger.sh bug) still
  # reads the category, so no reproduction starts on its own; the reply
  # says a maintainer starts it with repro:run.
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
  case $effective in
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
  # Where a defect shows (#352): the reproduction reads it to pick the way
  # the repository declares for that layer (scripts/repro-ways.py). Added
  # before the reproduction starts; one a person set already stays.
  local layer
  layer=$(jq -r '.layer // ""' <<<"$VERDICT")
  case "$effective:$layer" in
    bug_unconfirmed:logic | bug_unconfirmed:browser | bug_unconfirmed:cli | bug_unconfirmed:api | bug_unconfirmed:workflow | \
    needs_info:logic | needs_info:browser | needs_info:cli | needs_info:api | needs_info:workflow)
      if ! gh issue view "$NUMBER" --repo "$GITHUB_REPOSITORY" --json labels --jq '.labels[].name' 2>/dev/null | grep -q '^layer:'; then
        gh label create "layer:$layer" --repo "$GITHUB_REPOSITORY" --color C5DEF5 --description "Where the defect shows: the reproduction uses the way the repository declares for it" --force >/dev/null 2>&1 || true
        gh issue edit "$NUMBER" --repo "$GITHUB_REPOSITORY" --add-label "layer:$layer" >/dev/null 2>&1 || echo "::warning::Could not label #$NUMBER layer:$layer."
      fi ;;
  esac
  if [ -n "$kind" ] && { [ -z "$have" ] || { [ "$have" = Bug ] && [ "$kind" = Feature ]; }; }; then
    if gh api -X PATCH "repos/$GITHUB_REPOSITORY/issues/$NUMBER" -f type="$kind" >/dev/null 2>&1; then
      [ -z "$have" ] || retyped=yes
    else
      echo "::warning::Could not set #$NUMBER's Type to $kind."
    fi
  fi
  reply=${REPLY:-}
  [ -n "${reply//[[:space:]]/}" ] || reply="Thanks! A maintainer will take a look."
  # Every new issue's first reply says what happens next (C5, #564); a
  # security report's has its own words below.
  [ "$category" = security ] || reply="$(next_steps "$category")"$'\n\n'"$reply"
  if [ -n "$kept" ]; then
    reply="$reply"$'\n\n'"A maintainer set this issue's Type to Bug, so it stays a Bug, labelled bug:unconfirmed. Its reproduction does not start on its own: a maintainer starts it with the repro:run label."
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
  if [ "$category" = security ]; then
    # The caller's maintainer, else org.yml's maintainers (#568).
    local who mentions
    who=${MAINTAINER:-$(python3 "$(dirname "${BASH_SOURCE[0]}")/org.py" maintainers 2>/dev/null || true)}
    mentions=$(tr -s ' \n' '\n' <<<"$who" | sed -n 's/^\([A-Za-z0-9-]\{1,39\}\)$/@\1/p' | paste -sd' ' -)
    [ -z "$mentions" ] || reply="$reply"$'\n\n'"$mentions"
  fi
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
  gh() { printf '%s\n' "$*" | tr '\n' ' ' >> "$log"; echo >> "$log"; case "$*" in "issue view 7 "*) [ -z "${HAS_LAYER:-}" ] || echo layer:browser;; "issue view 3 "*) echo OPEN;; "issue view 4 "*) echo CLOSED;; "api repos/o/r/issues/7 --jq .node_id") echo I_7;; "api repos/o/r/issues/7 --jq"*) echo "${HAS_TYPE:-}";; "api repos/o/sec --jq .node_id") echo R_1;; "api graphql -f query=query"*) [ -z "${GQL_FAILS:-}" ] || return 1; echo "${TYPE_BY:-}";; "api repos/o/r/collaborators/"*) [ -z "${PERM_FAILS:-}" ] || return 1; echo "${PERM:-read}";; "api graphql "*) [ -z "${MOVE_FAILS:-}" ] || return 1; echo 12;; "issue lock "*) [ -z "${LOCK_FAILS:-}" ] || return 1;; esac; }
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
  VERDICT='{"category":"duplicate","duplicate_of":4}' REPLY=x SUMMARY=s t "a closed original is not named" "issue comment 7 --repo o/r --body .*as it moves\.  x  <sub>"
  VERDICT='{"category":"duplicate","duplicate_of":31337}' REPLY=x SUMMARY=s t "a number that is no open issue names nothing" "issue comment 7 --repo o/r --body .*as it moves\.  x  <sub>"
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
  # #496: and it is labelled as the bug its maintainer says it is, never as a request.
  for v in '{"category":"enhancement"}' '{"category":"planned"}' '{"category":"pro_feature"}' '{"category":"enhancement","exists_in_pro":true}'; do
    : > "$log"; ( VERDICT=$v REPLY=x SUMMARY=s HAS_TYPE=Bug TYPE_BY=boss PERM=write NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1 ) || true
    if grep -q -- "--add-label bug:unconfirmed" "$log" && ! grep -qE -- "--add-label [^ ]*(enhancement|exists-in-pro|planned|pro-feature)" "$log"; then echo "ok   #496 a maintainer's Bug read as $v is labelled bug:unconfirmed"; else echo "FAIL #496 a maintainer's Bug read as $v is labelled bug:unconfirmed, and only that:"; cat "$log"; fail=1; fi
  done
  HAS_TYPE=Bug TYPE_BY=boss PERM=write VERDICT='{"category":"enhancement","layer":"cli"}' REPLY=x SUMMARY=s t "#496 and gets the layer the verdict names" "issue edit 7 --repo o/r --add-label layer:cli"
  HAS_TYPE=Bug TYPE_BY=boss PERM=write VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s t "#496 the record still says what the classifier read" '"category":"enhancement"'
  HAS_TYPE=Bug TYPE_BY=boss PERM=write VERDICT='{"category":"planned"}' REPLY=x SUMMARY=s t "#496 the reply says the Bug is kept and repro:run starts its reproduction" "it stays a Bug, labelled bug:unconfirmed. Its reproduction does not start on its own: a maintainer starts it with the repro:run label."
  : > "$log"; ( VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s HAS_TYPE=Bug TYPE_BY=alice PERM=read NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1 ) || true
  if grep -q "starts it with the repro:run label" "$log"; then echo "FAIL #496 a retyped Bug's reply does not mention repro:run"; fail=1; else echo "ok   #496 a retyped Bug's reply does not mention repro:run"; fi
  HAS_TYPE=Bug TYPE_BY=alice PERM=read VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s t "#496 a reporter's Bug is still labelled enhancement" "issue edit 7 --repo o/r --add-label enhancement"
  for fails in GQL_FAILS PERM_FAILS; do
    : > "$log"; ( export "$fails=1"; VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s HAS_TYPE=Bug TYPE_BY=boss NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1 ) || true
    if grep -q -- "--add-label bug:unconfirmed" "$log"; then echo "ok   #496 a read that fails ($fails) labels the kept Bug bug:unconfirmed"; else echo "FAIL #496 a read that fails ($fails) labels the kept Bug bug:unconfirmed"; fail=1; fi
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
  if [ "$(awk '/id: sectoken/{s=1} s&&/permission-contents: write/{n++; s=0} /^      - name:/&&!/App token \(this repository and the security one\)/{s=0} END{print n+0}' "$wf")" = 2 ] && [ "$(grep -c 'id: sectoken' "$wf")" = 2 ]; then echo "ok   #311 both security tokens can transfer an issue (issues and contents write)"; else echo "FAIL #311 a security token lacks contents: write, so transferIssue is refused"; fail=1; fi
  MOVE_FAILS=1 VERDICT='{"category":"security"}' REPLY=x SUMMARY=s AUTHOR=alice SECURITY_REPO=o/sec SECURITY_TOKEN=t t "#287 a move that fails locks it and asks for a private report" "issue lock 7 .*--reason off_topic"
  PRIVATE=true VERDICT='{"category":"security"}' REPLY=x SUMMARY=s t "#194 in a private repository a security report is a Bug" "api -X PATCH repos/o/r/issues/7 -f type=Bug"
  PRIVATE=true VERDICT='{"category":"security"}' REPLY="report it privately" SUMMARY=s t "#194 and the reply says the issue is the report" "issue comment 7 .*this issue is the report.*@boss"
  : > "$log"; ( PRIVATE=true VERDICT='{"category":"security"}' REPLY="report it privately" SUMMARY=s NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER="" MODEL=m act >/dev/null 2>&1 ) || true
  if grep -q "issue comment 7 .*@$(python3 "$(dirname "${BASH_SOURCE[0]}")/org.py" maintainers | head -n 1)" "$log"; then echo "ok   #568 without a maintainer given, org.yml's are mentioned"; else echo "FAIL #568 without a maintainer given, org.yml's are mentioned"; fail=1; fi
  : > "$log"; if ( PRIVATE=true VERDICT='{"category":"security"}' REPLY="report it privately" SUMMARY=s NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1; grep -qE "issue lock|issue comment .*report it privately" "$log" ); then echo "FAIL #194 nor locked, nor sent to private reporting"; fail=1; else echo "ok   #194 nor locked, nor sent to private reporting"; fi
  # #352: the layer the defect shows in, as a label the reproduction reads.
  VERDICT='{"category":"bug_unconfirmed","layer":"browser"}' REPLY=x SUMMARY=s t "#352 a browser bug gets layer:browser" "issue edit 7 --repo o/r --add-label layer:browser"
  VERDICT='{"category":"bug_unconfirmed","layer":"logic"}' REPLY=x SUMMARY=s t "#352 a logic bug gets layer:logic" "issue edit 7 --repo o/r --add-label layer:logic"
  VERDICT='{"category":"bug_unconfirmed","layer":"workflow"}' REPLY=x SUMMARY=s t "#376 a bug in a workflow's wiring gets layer:workflow" "issue edit 7 --repo o/r --add-label layer:workflow"
  : > "$log"; if ( VERDICT='{"category":"enhancement","layer":"browser"}' REPLY=x SUMMARY=s NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1; grep -q "add-label layer:" "$log" ); then echo "FAIL #352 a request gets no layer"; fail=1; else echo "ok   #352 a request gets no layer"; fi
  : > "$log"; if ( VERDICT='{"category":"bug_unconfirmed","layer":"screen"}' REPLY=x SUMMARY=s NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1; grep -q "add-label layer:" "$log" ); then echo "FAIL #352 an unknown layer is no label"; fail=1; else echo "ok   #352 an unknown layer is no label"; fi
  : > "$log"; if ( HAS_LAYER=1 VERDICT='{"category":"bug_unconfirmed","layer":"logic"}' REPLY=x SUMMARY=s NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1; grep -q "add-label layer:logic" "$log" ); then echo "FAIL #352 a layer a person set stays"; fail=1; else echo "ok   #352 a layer a person set stays"; fi
  # C2 (#564): a maintainer's own Bug is accepted with its writing.
  prd=$(mktemp); printf '### Problem\n\nIt breaks.\n\n### Scope\n\n- Fix it.\n\n### Out of scope\n\n- Nothing.\n\n### Acceptance criteria\n\n- C1: Given a page, when it loads, then it does not break.\n\n### Criticality\n\nNormal\n' > "$prd"
  half=$(mktemp); printf '### Problem\n\nIt breaks.\n' > "$half"
  o() {
    : > "$log"; seals=$(mktemp -d); outf=$(mktemp)
    ( export RECEIPTS_FIXTURE=$seals AUTOPILOT_JSON=null LABELS_JSON='[]' HELD='' GITHUB_OUTPUT=$outf NUMBER=7 GITHUB_REPOSITORY=o/r AUTHOR=${WHO:-boss} BODY=${B:-$prd}; own_accept >/dev/null 2>&1 ) || true
  }
  for role in maintain admin; do
    HAS_TYPE=Bug PERM=$role o
    sealed=$(cat "$seals"/issues/7/prd-*.json 2>/dev/null || echo '{}')
    if grep -q "^own=true" "$outf" && grep -q "^accepted=true" "$outf" && grep -q -- "--add-label accepted" "$log" \
       && [ "$(jq -r '.accepted_by + " " + .how' <<<"$sealed")" = "boss own-bug" ] \
       && ! grep -qE -- "--add-label [^ ]*(bug:unconfirmed|repro:no-way|layer:|needs-triage)" "$log"; then
      echo "ok   C2 a Bug by a $role author: accepted and sealed by the author, no bug:unconfirmed, no repro:no-way"
    else echo "FAIL C2 a Bug by a $role author: accepted and sealed by the author, no bug:unconfirmed, no repro:no-way:"; cat "$log" "$outf"; fail=1; fi
  done
  HAS_TYPE=Bug PERM=maintain o
  if grep -q "issue comment 7 .*accepted with its writing" "$log" && grep -q "issue comment 7 .*dx-board" "$log" && grep -q -- "--remove-label awaiting-acceptance" "$log"; then echo "ok   C2 its reply says so, its board shows the seal, awaiting-acceptance comes off"; else echo "FAIL C2 its reply says so, its board shows the seal, awaiting-acceptance comes off:"; cat "$log"; fail=1; fi
  for case_ in "write Bug" "maintain Feature" "admin " "read Bug"; do
    HAS_TYPE=${case_#* } PERM=${case_%% *} o
    if grep -q "^own=false" "$outf" && ! grep -qE -- "add-label|issue comment" "$log" && [ -z "$(ls "$seals")" ]; then echo "ok   C2 role ${case_%% *}, Type ${case_#* }: left to the triage, unchanged"; else echo "FAIL C2 role ${case_%% *}, Type ${case_#* }: left to the triage, unchanged:"; cat "$log" "$outf"; fail=1; fi
  done
  HAS_TYPE=Bug PERM_FAILS=1 o
  if grep -q "^own=false" "$outf"; then echo "ok   C2 a role that cannot be read is no maintainer's"; else echo "FAIL C2 a role that cannot be read is no maintainer's"; fail=1; fi
  HAS_TYPE=Bug PERM=maintain B=$half o
  if grep -q "^own=true" "$outf" && grep -q "^accepted=false" "$outf" && ! grep -qE -- "--add-label" "$log" && [ -z "$(ls "$seals")" ] && grep -q "issue comment 7 .*incomplete" "$log"; then echo "ok   C2 an incomplete one is not accepted, gets no triage label, and waits on its author"; else echo "FAIL C2 an incomplete one is not accepted, gets no triage label, and waits on its author:"; cat "$log" "$outf"; fail=1; fi
  if [ "$(HAS_TYPE=Bug PERM=admin NUMBER=7 GITHUB_REPOSITORY=o/r AUTHOR=boss own_bug)" = yes ] && [ "$(HAS_TYPE=Bug PERM=write NUMBER=7 GITHUB_REPOSITORY=o/r AUTHOR=alice own_bug)" = no ] && [ "$(HAS_TYPE=Bug PERM=admin NUMBER=7 GITHUB_REPOSITORY=o/r AUTHOR='a b' own_bug)" = no ]; then echo "ok   C2 own-bug-check: yes for a maintainer's Bug only"; else echo "FAIL C2 own-bug-check: yes for a maintainer's Bug only"; fail=1; fi
  rm -f "$prd" "$half"
  # C5 (#564): the first reply says what happens next and whom it waits on.
  VERDICT='{"category":"enhancement"}' REPLY="Nice idea." SUMMARY=s t "C5 the first reply opens with what happens next" "issue comment 7 --repo o/r --body \*\*What happens next.\*\* This triage reads every new issue first. Then a maintainer decides whether to accept it .*Nice idea"
  VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s t "C5 the triage, then the acceptance, then the autopilot in the organisation's runners" "triage reads.*decides whether to accept it.*the autopilot writes the code in the organisation's runners"
  VERDICT='{"category":"bug_unconfirmed"}' REPLY=x SUMMARY=s t "C5 and /claim before it is accepted" 'comment `/claim` on the issue .*before it is accepted, and the autopilot steps aside'
  VERDICT='{"category":"enhancement"}' REPLY=x SUMMARY=s t "C5 a request waits on a maintainer's acceptance" "It waits on a maintainer's acceptance now"
  VERDICT='{"category":"needs_info"}' REPLY=x SUMMARY=s t "C5 a report missing something waits on its author" "It waits on you now"
  : > "$log"; ( VERDICT='{"category":"security"}' REPLY=x SUMMARY=s NUMBER=7 GITHUB_REPOSITORY=o/r MAINTAINER=boss MODEL=m act >/dev/null 2>&1 ) || true
  if grep -q "/claim" "$log"; then echo "FAIL C5 a security report is never invited to claim"; fail=1; else echo "ok   C5 a security report is never invited to claim"; fi
  root="$(dirname "${BASH_SOURCE[0]}")/.."
  for doc in README.md CONTRIBUTING.md agents-block.md AGENTS.md; do
    if tr '\n' ' ' < "$root/$doc" | tr -s ' ' | grep -qF "$NEXT"; then echo "ok   C5 $doc says the same"; else echo "FAIL C5 $doc does not open with what happens next, in the triage's words"; fail=1; fi
  done
  VERDICT='' REPLY=x SUMMARY=s t "no verdict waits for a person" "--add-label needs-triage"
  VERDICT='{"category":"nonsense"}' REPLY=x SUMMARY=s t "an unknown category waits for a person" "--add-label needs-triage"
  rm -f "$log"
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

case "${1:-}" in
  own-bug) own_accept ;;
  own-bug-check) own_bug ;;
  *) act ;;
esac
