#!/usr/bin/env bash
# Who an issue is assigned to (#73): whoever works it, so a Project shows who
# owns each accepted issue.
#
#   issue-assignee.sh accepted   when a person adds `accepted`: the issue is
#                                assigned to that person, unless it already
#                                has an assignee (issue-accepted.yml)
#   issue-assignee.sh pr         when a pull request opens (or its description
#                                changes): each open issue of this repository
#                                it closes is reassigned to its author, when
#                                the author is a member of the organisation
#                                and not already among the assignees
#                                (pull-request-assignee.yml)
#   issue-assignee.sh --test     self-test against fixtures
#
# A bot is never made an assignee. A lane's issue (accepted by policy,
# policy/autonomy.yml) carries no `accepted` from a person, so it stays
# unassigned; the autopilot's pull requests are dilux-bot's, not a member's,
# so the person who accepted the issue stays its assignee, also once a
# maintainer takes such a pull request over (its author is still the bot).
# An outside contributor's pull request leaves the assignee as it is: the
# member who accepted the issue still answers for it.
#
# Environment: GITHUB_REPOSITORY (owner/name), GH_TOKEN (issues: write, and
# pull-requests: read for `pr`). `accepted`: NUMBER, SENDER, SENDER_TYPE.
# `pr`: PR, PR_AUTHOR, PR_AUTHOR_TYPE, AUTHOR_ASSOCIATION (the event's, OWNER
# or MEMBER for a member). ASSIGNEE_JSON, a file holding the answer GitHub
# would give (the issue's assignees for `accepted`, the GraphQL answer for
# `pr`), replaces the read; ASSIGNEE_DRY=1 prints the plan and changes
# nothing. A failure to read or write is a warning, never a failed run: an
# assignee is bookkeeping, not a check.
set -euo pipefail

# shellcheck disable=SC2016 # GraphQL variables, not shell ones.
QUERY='query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      closingIssuesReferences(first: 10) {
        nodes {
          number
          state
          repository { nameWithOwner }
          assignees(first: 20) { nodes { login } }
        }
      }
    }
  }
}'

is_bot() { [ "$2" = Bot ] || [[ "$1" == *"[bot]" ]]; }

# The plan for an issue just accepted: "assign <login>" or "keep <why>".
# $1 a JSON array of the current assignees' logins, $2 who added the label,
# $3 their type (User or Bot).
plan_accepted() {
  if [ -z "$2" ] || is_bot "$2" "$3"; then echo "keep a bot accepted it; a bot is never the assignee"
  elif [ "$(jq 'length' <<<"$1")" -gt 0 ]; then echo "keep it already has an assignee ($(jq -r 'join(", ")' <<<"$1"))"
  else echo "assign $2"; fi
}

# The plan for the issues a pull request closes, from the GraphQL answer in
# $1, one line each: "<number> assign <login> <others to remove, comma-separated>"
# or "<number> keep <why>". Nothing when the author is not a member.
plan_pr() {
  # shellcheck disable=SC2016 # jq variables, not shell ones.
  jq -r --arg repo "$GITHUB_REPOSITORY" --arg me "$PR_AUTHOR" '
    (.data.repository.pullRequest.closingIssuesReferences.nodes // [])[]
    | [.assignees.nodes[]?.login] as $a
    | "\(.number) " + (
        if .repository.nameWithOwner != $repo then "keep it is in another repository"
        elif .state != "OPEN" then "keep it is closed"
        elif ($a | index($me)) != null then "keep \($me) is already assigned"
        else "assign \($me) " + ($a | join(",")) end)' "$1"
}

# Whether the pull request's author may take its issues: a person who is a
# member of the organisation. Prints why not.
author_takes() {
  if is_bot "$PR_AUTHOR" "${PR_AUTHOR_TYPE:-User}"; then echo "the author is a bot; its issues keep their assignee"; return 1; fi
  case "${AUTHOR_ASSOCIATION:-}" in
    OWNER|MEMBER) return 0 ;;
    *) echo "$PR_AUTHOR is not a member of the organisation (${AUTHOR_ASSOCIATION:-NONE}); an outside contributor's pull request leaves the assignee as it is"; return 1 ;;
  esac
}

# Assign issue $1 to $2 and then, once GitHub has them as an assignee, drop
# the others in $3 (comma-separated): never left with nobody.
apply() {
  local n=$1 who=$2 others=${3:-} got args
  if [ "${ASSIGNEE_DRY:-}" = 1 ]; then echo "#$n: would assign $who${others:+, unassign $others}."; return 0; fi
  if ! got=$(gh api -X POST "repos/$GITHUB_REPOSITORY/issues/$n/assignees" -f "assignees[]=$who" --jq '[.assignees[].login]' 2>&1); then
    echo "::warning::#$n: could not assign $who ($(head -c 200 <<<"$got"))."; return 0
  fi
  # GitHub ignores, without an error, someone who cannot be assigned here.
  if ! jq -e --arg w "$who" 'index($w) != null' <<<"$got" >/dev/null 2>&1; then
    echo "::warning::#$n: GitHub did not assign $who (no access to this repository?); the assignees stay as they were."; return 0
  fi
  echo "#$n: assigned to $who."
  [ -n "$others" ] || return 0
  args=()
  while read -r o; do [ -n "$o" ] && args+=(-f "assignees[]=$o"); done < <(tr ',' '\n' <<<"$others")
  if gh api -X DELETE "repos/$GITHUB_REPOSITORY/issues/$n/assignees" "${args[@]}" >/dev/null 2>&1; then
    echo "#$n: unassigned $others."
  else
    echo "::warning::#$n: could not unassign $others."
  fi
}

accepted() {
  local current plan
  if [ -n "${ASSIGNEE_JSON:-}" ]; then current=$(cat "$ASSIGNEE_JSON")
  elif ! current=$(gh api "repos/$GITHUB_REPOSITORY/issues/$NUMBER" --jq '[.assignees[].login]' 2>&1); then
    echo "::warning::#$NUMBER: could not read its assignees ($(head -c 200 <<<"$current")); left as it is."; return 0
  fi
  plan=$(plan_accepted "$current" "${SENDER:-}" "${SENDER_TYPE:-User}")
  case "$plan" in
    assign\ *) apply "$NUMBER" "${plan#assign }" ;;
    *) echo "#$NUMBER: ${plan#keep }." ;;
  esac
}

pr() {
  local why answer n verb who others
  if ! why=$(author_takes); then echo "$why."; return 0; fi
  # The same closing references the accepted-issue gate reads on the same
  # event (scripts/issue-gate.sh): a description it can read, so can this.
  answer=${ASSIGNEE_JSON:-}
  if [ -z "$answer" ]; then
    answer=$(mktemp)
    if ! gh api graphql -f query="$QUERY" -F owner="${GITHUB_REPOSITORY%%/*}" -F name="${GITHUB_REPOSITORY#*/}" -F number="$PR" > "$answer" 2>&1 \
      || jq -e '.errors' "$answer" >/dev/null 2>&1; then
      echo "::warning::Could not read the issues this pull request closes ($(head -c 200 "$answer")); no assignee changed."; return 0
    fi
  fi
  local lines
  lines=$(plan_pr "$answer")
  [ -n "$lines" ] || { echo "This pull request closes no issue."; return 0; }
  while read -r n verb who others; do
    [ -n "$n" ] || continue
    if [ "$verb" = assign ]; then apply "$n" "$who" "$others"; else echo "#$n: $who $others."; fi
  done <<< "$lines"
}

if [ "${1:-}" = "--test" ]; then
  fail=0
  export GITHUB_REPOSITORY=DiluxOne/example
  is() { if [ "$2" = "$3" ]; then echo "ok   $1"; else printf 'FAIL %s\n  want: %s\n  got:  %s\n' "$1" "$3" "$2"; fail=1; fi; }
  # plan_accepted
  is "C1: the person who accepts an unassigned issue is assigned" "$(plan_accepted '[]' soydiloreto User)" "assign soydiloreto"
  is "C1: an issue with an assignee keeps it" "$(plan_accepted '["someone"]' soydiloreto User)" "keep it already has an assignee (someone)"
  is "a bot that adds the label is never assigned" "$(plan_accepted '[]' 'dilux-bot[bot]' Bot)" "keep a bot accepted it; a bot is never the assignee"
  is "a [bot] login is a bot whatever its type says" "$(plan_accepted '[]' 'dilux-bot[bot]' User)" "keep a bot accepted it; a bot is never the assignee"
  # plan_pr: one closing issue (number, repository, state, assignees comma-separated).
  issue() {
    jq -n --argjson n "$1" --arg r "$2" --arg s "$3" --arg a "${4:-}" \
      '{number: $n, state: $s, repository: {nameWithOwner: $r}, assignees: {nodes: [$a | split(",")[] | select(length > 0) | {login: .}]}}'
  }
  answer() { jq -s '{data: {repository: {pullRequest: {closingIssuesReferences: {nodes: .}}}}}'; }
  plan() { local f; f=$(mktemp); cat > "$f"; PR_AUTHOR=${ME:-maria} plan_pr "$f"; rm -f "$f"; }
  is "C2: a member's pull request takes the issue from its assignee" "$(issue 12 "$GITHUB_REPOSITORY" OPEN soydiloreto | answer | plan)" "12 assign maria soydiloreto"
  is "C2: an unassigned issue goes to the member who works it" "$(issue 12 "$GITHUB_REPOSITORY" OPEN | answer | plan)" "12 assign maria "
  is "C2: every other assignee is replaced" "$(issue 12 "$GITHUB_REPOSITORY" OPEN a,b | answer | plan)" "12 assign maria a,b"
  is "the author already assigned keeps it as it is" "$(issue 12 "$GITHUB_REPOSITORY" OPEN soydiloreto,maria | answer | plan)" "12 keep maria is already assigned"
  is "an issue in another repository is left alone" "$(issue 12 Other/repo OPEN soydiloreto | answer | plan)" "12 keep it is in another repository"
  is "a closed issue is left alone" "$(issue 12 "$GITHUB_REPOSITORY" CLOSED soydiloreto | answer | plan)" "12 keep it is closed"
  is "several issues, each on its own" "$({ issue 3 "$GITHUB_REPOSITORY" OPEN maria; issue 12 "$GITHUB_REPOSITORY" OPEN x; } | answer | plan | tr '\n' '|')" "3 keep maria is already assigned|12 assign maria x|"
  is "no closing issue, no plan" "$(echo '{"data":{"repository":{"pullRequest":{"closingIssuesReferences":{"nodes":[]}}}}}' | plan)" ""
  # author_takes, and the whole `pr` mode dry.
  takes() { PR_AUTHOR=$1 PR_AUTHOR_TYPE=$2 AUTHOR_ASSOCIATION=$3 author_takes >/dev/null && echo yes || echo no; }
  is "an organisation member takes the issue" "$(takes maria User MEMBER)" yes
  is "an owner takes the issue" "$(takes soydiloreto User OWNER)" yes
  is "C2: an outside contributor does not" "$(takes someone User CONTRIBUTOR)" no
  is "a collaborator who is not a member does not" "$(takes someone User COLLABORATOR)" no
  is "nor a first-time contributor" "$(takes someone User FIRST_TIME_CONTRIBUTOR)" no
  is "nor the autopilot, a bot" "$(takes 'dilux-bot[bot]' Bot NONE)" no
  is "nor a bot that GitHub calls a member" "$(takes 'dilux-bot[bot]' Bot MEMBER)" no
  f=$(mktemp); issue 12 "$GITHUB_REPOSITORY" OPEN soydiloreto | answer > "$f"
  is "the pr mode, dry: a member reassigns" "$(ASSIGNEE_DRY=1 ASSIGNEE_JSON=$f PR=1 PR_AUTHOR=maria PR_AUTHOR_TYPE=User AUTHOR_ASSOCIATION=MEMBER pr)" "#12: would assign maria, unassign soydiloreto."
  is "the pr mode, dry: an outsider changes nothing" "$(ASSIGNEE_DRY=1 ASSIGNEE_JSON=$f PR=1 PR_AUTHOR=someone PR_AUTHOR_TYPE=User AUTHOR_ASSOCIATION=CONTRIBUTOR pr | grep -c 'would' || true)" 0
  echo '[]' > "$f"
  is "the accepted mode, dry: assigns the person" "$(ASSIGNEE_DRY=1 ASSIGNEE_JSON=$f NUMBER=7 SENDER=soydiloreto SENDER_TYPE=User accepted)" "#7: would assign soydiloreto."
  echo '["maria"]' > "$f"
  is "the accepted mode, dry: keeps an assignee" "$(ASSIGNEE_DRY=1 ASSIGNEE_JSON=$f NUMBER=7 SENDER=soydiloreto SENDER_TYPE=User accepted)" "#7: it already has an assignee (maria)."
  rm -f "$f"
  # apply, against a stand-in for gh that logs each call: the author is added
  # first, and the others go only once GitHub has the author.
  log=$(mktemp)
  gh() {
    local a line=$3
    for a in "$@"; do case "$a" in assignees*) line="$line $a" ;; esac; done
    echo "$line" >> "$log"
    if [ "$3" = POST ]; then echo "${GH_ANSWER:-[]}"; fi
  }
  : > "$log"; GH_ANSWER='["soydiloreto","maria"]' apply 12 maria soydiloreto >/dev/null
  is "apply: adds the author, then removes the others" "$(cut -d' ' -f1,2 "$log" | tr '\n' '|')" "POST assignees[]=maria|DELETE assignees[]=soydiloreto|"
  : > "$log"; GH_ANSWER='["soydiloreto"]' apply 12 maria soydiloreto >/dev/null
  is "apply: GitHub did not take the author, so nobody is removed" "$(cut -d' ' -f1 "$log" | tr '\n' '|')" "POST|"
  : > "$log"; GH_ANSWER='["maria"]' apply 12 maria "" >/dev/null
  is "apply: nobody else to remove, no DELETE" "$(cut -d' ' -f1 "$log" | tr '\n' '|')" "POST|"
  unset -f gh; rm -f "$log"
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

case "${1:-}" in
  accepted) accepted ;;
  pr) pr ;;
  *) echo "usage: issue-assignee.sh accepted|pr|--test" >&2; exit 2 ;;
esac
