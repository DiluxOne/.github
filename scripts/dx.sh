#!/usr/bin/env bash
# dx: the DiluxOne flow, one command per step, for a person or an agent, in
# a clone of any DiluxOne repository or in a fork of one. The flow and why
# it is so: docs/agents.md in DiluxOne/.github.
#
#   dx issue --bug|--feature|--docs|--task --title T [--body-file F]
#                       open the issue upstream; a maintainer accepts it
#   dx start <number> [--type T]
#                       check the issue is accepted, create the branch
#                       <type>/<number>-<slug> and the pull request's
#                       description (.git/dx/pr.md, closing the issue)
#   dx check            the local review on this branch, with that description
#   dx pr [--title T]   open the pull request upstream (only when the person
#                       you work for says so)
#   dx --test           self-test
#
# Run from the repository, with this repository (DiluxOne/.github) checked
# out beside it:  bash ../.github/scripts/dx.sh <step>. Needs git and gh.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)

die() { echo "dx: $*" >&2; exit 1; }

# The repository issues and pull requests go to: the parent of a fork, this
# repository otherwise.
upstream() {
  gh repo view --json nameWithOwner,isFork,parent --jq 'if .isFork then "\(.parent.owner.login)/\(.parent.name)" else .nameWithOwner end'
}

# The pull request type an issue's Type asks for.
type_for() {
  case "$1" in
    Bug) echo fix ;; Feature) echo feat ;; Docs) echo docs ;; Task|"") echo chore ;; *) echo chore ;;
  esac
}

# A branch-safe slug of a title: lower case, words joined by dashes, short.
slug() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' | cut -c1-40 | sed -E 's/-+$//'
}

cmd_issue() {
  local kind="" title="" body="" up type
  while [ $# -gt 0 ]; do
    case "$1" in
      --bug) kind=Bug ;; --feature) kind=Feature ;; --docs) kind=Docs ;; --task) kind=Task ;;
      --title) title=$2; shift ;; --body-file) body=$(cat "$2"); shift ;;
      *) die "unknown option $1" ;;
    esac
    shift
  done
  [ -n "$kind" ] && [ -n "$title" ] || die "usage: dx issue --bug|--feature|--docs|--task --title T [--body-file F]"
  up=$(upstream)
  [ -n "$body" ] || body="(Describe the problem, what you expected and why it matters.)"
  url=$(gh issue create --repo "$up" --title "$title" --body "$body")
  # Setting the Type needs triage access; the issue triage sets it otherwise.
  gh api -X PATCH "repos/$up/issues/${url##*/}" -f type="$kind" >/dev/null 2>&1 || true
  echo "$url"
  echo "Next: wait until a maintainer accepts it (the \"accepted\" label), then: dx start ${url##*/}"
}

cmd_start() {
  local n="${1:-}" type="" up info title kind accepted state branch
  [[ "$n" =~ ^[0-9]+$ ]] || die "usage: dx start <issue number> [--type T]"
  shift
  [ "${1:-}" = --type ] && type=$2
  up=$(upstream)
  info=$(gh api "repos/$up/issues/$n" --jq '{title, state, type: (.type.name // ""), accepted: ([.labels[].name] | index("accepted") != null), pr: (.pull_request != null)}')
  [ "$(jq -r .pr <<<"$info")" = false ] || die "#$n is a pull request, not an issue."
  title=$(jq -r .title <<<"$info"); state=$(jq -r .state <<<"$info"); kind=$(jq -r .type <<<"$info"); accepted=$(jq -r .accepted <<<"$info")
  [ "$state" = open ] || die "#$n is $state; work starts from an open issue."
  [ "$accepted" = true ] || die "#$n is not accepted yet: wait until a maintainer adds the \"accepted\" label."
  type=${type:-$(type_for "$kind")}
  branch="$type/$n-$(slug "$title")"
  git fetch -q origin
  base=$(git symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null || echo origin/main)
  git switch -q -c "$branch" "$base"
  mkdir -p "$(git rev-parse --git-dir)/dx"
  cat > "$(git rev-parse --git-dir)/dx/pr.md" <<EOF
## 📝 What changes



## 💡 Why

Closes #$n

## 🧪 How I tested it


EOF
  echo "On $branch, for #$n ($kind: $title)."
  echo "The pull request's description is $(git rev-parse --git-dir)/dx/pr.md: fill in What changes and Why."
  echo "Commit with \"$type(<scope>): <subject>\" (72 characters or fewer), then: dx check"
}

cmd_check() {
  local body
  body="$(git rev-parse --git-dir)/dx/pr.md"
  [ -f "$body" ] || die "no $body: start with dx start <issue number>."
  bash "$here/local-review.sh" --body-file "$body" "$@"
}

cmd_pr() {
  local title="" up head owner body
  [ "${1:-}" = --title ] && title=$2
  body="$(git rev-parse --git-dir)/dx/pr.md"
  [ -f "$body" ] || die "no $body: start with dx start <issue number>."
  up=$(upstream)
  owner=$(gh repo view --json owner --jq .owner.login)
  head=$(git branch --show-current)
  [ -n "$title" ] || title=$(git log -1 --format=%s)
  git push -q -u origin "$head"
  gh pr create --repo "$up" --head "$owner:$head" --title "$title" --body-file "$body"
}

if [ "${1:-}" = "--test" ]; then
  fail=0
  t() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: got \"$2\", want \"$3\""; fail=1; fi; }
  t "a Bug asks for a fix"            "$(type_for Bug)" fix
  t "a Feature asks for a feat"       "$(type_for Feature)" feat
  t "a Docs issue asks for docs"      "$(type_for Docs)" docs
  t "a Task asks for a chore"         "$(type_for Task)" chore
  t "no Type asks for a chore"        "$(type_for "")" chore
  t "a slug is lower case and dashed" "$(slug 'Adopt the shared v4 workflows!')" adopt-the-shared-v4-workflows
  t "a slug is short"                 "$(slug 'A very long title that goes on and on about many many things')" a-very-long-title-that-goes-on-and-on-ab
  t "a slug has no edge dashes"       "$(slug '  -- Fix: the thing --')" fix-the-thing
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

case "${1:-}" in
  issue) shift; cmd_issue "$@" ;;
  start) shift; cmd_start "$@" ;;
  check) shift; cmd_check "$@" ;;
  pr) shift; cmd_pr "$@" ;;
  *) sed -n '2,20p' "$0"; exit 64 ;;
esac
