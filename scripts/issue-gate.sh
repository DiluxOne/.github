#!/usr/bin/env bash
# The accepted-issue gate: a pull request must close an issue a maintainer
# accepted. Its description closes it ("Closes #12", or a link under
# Development), and the issue is in the same repository, open, and carries
# the policy's label (`issue-gate.label`, "accepted"), added last by a person:
# a label a bot added does not count, so no automation (the triage reads
# untrusted issue text) can accept an issue. Only people with triage access or
# more can label an issue, so the label is a maintainer's decision.
#
# Bots (Dependabot, release pull requests) are exempt. With REQUIRED other
# than true, the gate is off and says so.
#
# GitHub reads "Closes #12" only in a pull request into the default branch.
# One into another branch links its issue by hand, under Development in the
# pull request's sidebar; the gate reads both.
#
# Environment: REQUIRED (true|false), LABEL, AUTHOR_TYPE (User|Bot),
# GITHUB_REPOSITORY (owner/name), PR (the pull request's number), GH_TOKEN
# (issues: read and pull-requests: read). ISSUE_GATE_JSON, a file holding the
# GraphQL answer, replaces the call (the self-test uses it).
#
#   issue-gate.sh          check (exit 1 when no accepted issue is closed)
#   issue-gate.sh --test   self-test against fixtures
set -euo pipefail

# shellcheck disable=SC2016 # GraphQL variables, not shell ones.
QUERY='query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      closingIssuesReferences(first: 10) {
        totalCount
        nodes {
          number
          state
          repository { nameWithOwner }
          labels(first: 50) { nodes { name } }
          timelineItems(itemTypes: [LABELED_EVENT, UNLABELED_EVENT], last: 100) {
            nodes {
              __typename
              ... on LabeledEvent { label { name } actor { __typename login } }
              ... on UnlabeledEvent { label { name } actor { __typename login } }
            }
          }
        }
      }
    }
  }
}'

# The issues the pull request closes, one line each: "<number> <verdict>",
# verdict one of ok, other-repo, closed, no-label, bot-label.
verdicts() {
  # shellcheck disable=SC2016 # jq variables, not shell ones.
  jq -r --arg repo "$GITHUB_REPOSITORY" --arg label "$LABEL" '
    (.data.repository.pullRequest.closingIssuesReferences.nodes // [])[]
    | . as $i
    | ([.timelineItems.nodes[]? | select(.label.name == $label)] | last) as $last
    | "\(.number) " + (
        if .repository.nameWithOwner != $repo then "other-repo"
        elif .state != "OPEN" then "closed"
        elif ([.labels.nodes[]?.name] | index($label)) == null then "no-label"
        elif $last == null or $last.__typename != "LabeledEvent" or $last.actor.__typename != "User" then "bot-label"
        else "ok" end)' "$1"
}

check() {
  REQUIRED=${REQUIRED:-true}
  LABEL=${LABEL:-accepted}
  AUTHOR_TYPE=${AUTHOR_TYPE:-User}
  if [ "$REQUIRED" != true ]; then
    echo "The accepted-issue gate is off for this repository."
    return 0
  fi
  if [ "$AUTHOR_TYPE" = Bot ]; then
    echo "A bot's pull request (Dependabot, a release) needs no issue."
    return 0
  fi
  local answer=${ISSUE_GATE_JSON:-}
  if [ -z "$answer" ]; then
    answer=$(mktemp)
    if ! gh api graphql -f query="$QUERY" -F owner="${GITHUB_REPOSITORY%%/*}" -F name="${GITHUB_REPOSITORY#*/}" -F number="$PR" > "$answer" 2>"$answer.err"; then
      echo "::error::Could not read the issues this pull request closes ($(head -c 300 "$answer.err")). The caller's conventions job needs issues: read and pull-requests: read."
      return 1
    fi
  fi
  if jq -e '.errors' "$answer" >/dev/null 2>&1; then
    echo "::error::Could not read the issues this pull request closes ($(jq -c '.errors' "$answer" | head -c 300)). The caller's conventions job needs issues: read and pull-requests: read."
    return 1
  fi
  local lines ok=0 n v total
  total=$(jq -r '.data.repository.pullRequest.closingIssuesReferences.totalCount // 0' "$answer")
  if [ "$total" -gt 10 ]; then
    echo "::error::This pull request closes $total issues; the gate reads at most 10. Split it, one pull request per accepted issue or a few."
    return 1
  fi
  lines=$(verdicts "$answer")
  while read -r n v; do
    [ -z "$n" ] && continue
    case "$v" in
      ok) echo "#$n is accepted."; ok=1 ;;
      other-repo) echo "#$n is in another repository; the issue must be in this one." ;;
      closed) echo "#$n is closed; the issue must be open." ;;
      no-label) echo "#$n has no \"$LABEL\" label yet: a maintainer has not accepted it." ;;
      bot-label) echo "#$n got its \"$LABEL\" label from a bot; only a person accepts an issue." ;;
    esac
  done <<< "$lines"
  if [ "$ok" -eq 1 ]; then
    echo "Accepted issue: OK."
    return 0
  fi
  [ -n "$lines" ] || echo "This pull request closes no issue."
  echo "::error::Every pull request closes an issue a maintainer accepted (label \"$LABEL\"). Open an issue (or find one), wait until it is accepted, and write \"Closes #<number>\" in the description (into a branch other than the default, link it under Development instead); then edit the description or re-run this check. See CONTRIBUTING.md, \"Start from an issue\"."
  return 1
}

if [ "${1:-}" = "--test" ]; then
  fail=0
  repo=DiluxOne/example
  # One closing issue: number, repository, state, its labels (comma-separated)
  # and its label events, "type:label:actor-type" separated by commas.
  issue() {
    local labels events
    labels=$(tr ',' '\n' <<<"$4" | jq -R 'select(length > 0) | {name: .}' | jq -s '{nodes: .}')
    events=$(tr ',' '\n' <<<"$5" | jq -R 'select(length > 0) | split(":") | {__typename: .[0], label: {name: .[1]}, actor: {__typename: .[2], login: "x"}}' | jq -s '{nodes: .}')
    jq -n --argjson n "$1" --arg r "$2" --arg s "$3" --argjson l "$labels" --argjson e "$events" '{number: $n, state: $s, repository: {nameWithOwner: $r}, labels: $l, timelineItems: $e}'
  }
  answer() { jq -s '{data: {repository: {pullRequest: {closingIssuesReferences: {nodes: .}}}}}'; }
  case_() {
    local name=$1 want=$2 file got
    file=$(mktemp); cat > "$file"
    ( REQUIRED=${REQ:-true} LABEL=accepted AUTHOR_TYPE=${WHO:-User} GITHUB_REPOSITORY=$repo PR=1 ISSUE_GATE_JSON=$file check >/dev/null 2>&1 ) && got=0 || got=1
    rm -f "$file"
    if [ "$got" = "$want" ]; then echo "ok   $name"; else echo "FAIL $name (want $want, got $got)"; return 1; fi
  }
  issue 12 "$repo" OPEN accepted,bug LabeledEvent:accepted:User | answer | case_ "passes: an open issue a person accepted" 0 || fail=1
  issue 12 "$repo" OPEN bug "" | answer | case_ "fails: an issue nobody accepted" 1 || fail=1
  echo '{"data":{"repository":{"pullRequest":{"closingIssuesReferences":{"nodes":[]}}}}}' | case_ "fails: no closing issue" 1 || fail=1
  issue 12 "$repo" OPEN accepted LabeledEvent:accepted:Bot | answer | case_ "fails: a bot added the label" 1 || fail=1
  issue 12 "$repo" OPEN accepted LabeledEvent:accepted:Bot,UnlabeledEvent:accepted:User,LabeledEvent:accepted:User | answer | case_ "passes: a person added it again after a bot" 0 || fail=1
  issue 12 "$repo" OPEN accepted LabeledEvent:accepted:User,UnlabeledEvent:accepted:User,LabeledEvent:accepted:Bot | answer | case_ "fails: the last to add it was a bot" 1 || fail=1
  issue 12 "$repo" OPEN accepted "" | answer | case_ "fails: the label with no event to say who added it" 1 || fail=1
  issue 12 "$repo" CLOSED accepted LabeledEvent:accepted:User | answer | case_ "fails: a closed issue" 1 || fail=1
  issue 12 "Other/repo" OPEN accepted LabeledEvent:accepted:User | answer | case_ "fails: an issue in another repository" 1 || fail=1
  { issue 3 "$repo" OPEN bug ""; issue 12 "$repo" OPEN accepted LabeledEvent:accepted:User; } | answer | case_ "passes: one accepted among several" 0 || fail=1
  issue 12 "$repo" OPEN accepted LabeledEvent:approved:User,LabeledEvent:accepted:Bot | answer | case_ "fails: a person's event for another label does not count" 1 || fail=1
  echo '{"errors":[{"message":"Resource not accessible by integration"}]}' | case_ "fails: an answer that is an error" 1 || fail=1
  echo '{"data":{"repository":{"pullRequest":{"closingIssuesReferences":{"totalCount":11,"nodes":[]}}}}}' | case_ "fails: more closing issues than it reads" 1 || fail=1
  echo '{}' | WHO=Bot case_ "passes: a bot's pull request" 0 || fail=1
  echo '{}' | REQ=false case_ "passes: the gate is off" 0 || fail=1
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

check
