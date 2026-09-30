#!/usr/bin/env bash
# The conventions every pull request is held to: the branch name, the title
# and every commit header (Conventional Commits, at most MAX_HEADER long), no
# session links in commits, the description's required sections filled in,
# and the AI line instead of a "Generated with" footer. The conventions
# workflow runs it on a pull request, scripts/local-review.sh before one is
# opened, so both give the same answer.
#
# Environment: BRANCH, TITLE, BODY, BASE and HEAD_REF (the commits between
# them are checked), MAX_HEADER (default 100), SECTIONS (comma-separated
# headings, default "What changes,Why"; empty skips), LABELS (comma-separated,
# optional), REVIEWED_SHA (the commit the last review read, optional),
# AUTHOR_TYPE (Bot skips the sections). Run from the repository.
#
#   conventions.sh          check (exit 1 on any broken rule)
#   conventions.sh --test   self-test against a scratch repository
set -euo pipefail

check() {
  MAX_HEADER=${MAX_HEADER:-100}
  SECTIONS=${SECTIONS-What changes,Why}
  LABELS=${LABELS:-}
  REVIEWED_SHA=${REVIEWED_SHA:-}
  AUTHOR_TYPE=${AUTHOR_TYPE:-User}
  TYPES='feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert'
  HEADER_RE="^(${TYPES})(\([a-z0-9._/-]+\))?!?: [^ ].*[^.]$"
  BRANCH_RE="^((${TYPES})/[a-z0-9][a-z0-9._-]*|dependabot/.+)$"
  fail=0
  error() { echo "::error::$1"; fail=1; }
  check_header() {
    if ! [[ "$2" =~ $HEADER_RE ]]; then
      error "$1 is not a Conventional Commit header (\"type(scope): subject\", type one of ${TYPES//|/, }, no trailing period): \"$2\""
    elif (( ${#2} > MAX_HEADER )); then
      error "$1 is ${#2} characters; the limit is ${MAX_HEADER}: \"$2\""
    fi
  }
  [[ "$BRANCH" =~ $BRANCH_RE ]] || error "Branch \"$BRANCH\" must be <type>/<kebab-case-description>, type one of ${TYPES//|/, }."
  check_header "The pull request title" "$TITLE"
  # The type:* label is the review's reading of the diff (or a person's
  # override); the title, which becomes the commit on main, must say the
  # same. The review corrects the title itself; this catches a later
  # hand edit that undoes it. A label the review set on an earlier commit
  # is not its reading of this one: until the review has read this commit
  # (it runs after this check and relabels), the comparison waits.
  typelabel=$(tr ',' '\n' <<<"$LABELS" | grep -m1 '^type:' | sed 's/^type://' || true)
  TYPE_RE='^([a-z]+)(\([^)]*\))?(!?): '
  if [ -n "$typelabel" ] && [ -n "$REVIEWED_SHA" ] && [ "$REVIEWED_SHA" != "$HEAD_REF" ]; then
    echo "The review has not read ${HEAD_REF:0:7} yet (last: ${REVIEWED_SHA:0:7}); the title's type is checked against its reading once it has."
  elif [ -n "$typelabel" ] && [[ "$TITLE" =~ $TYPE_RE ]]; then
    token=${BASH_REMATCH[1]}; bang=${BASH_REMATCH[3]}
    if [ "$typelabel" = breaking ]; then
      [ "$bang" = '!' ] || error "The pull request is labelled type:breaking, so its title needs the \"!\" of a breaking change: \"$token$bang:\"."
    elif [ "$token" != "$typelabel" ]; then
      error "The pull request is labelled type:$typelabel but its title says \"$token:\"; the title must carry the labelled type (the review sets it; change the label if the review is wrong)."
    fi
  fi
  while read -r sha; do
    [ -z "$sha" ] && continue
    check_header "Commit ${sha:0:7}" "$(git log -1 --format=%s "$sha")"
    if git log -1 --format=%B "$sha" | grep -qiE '^Claude-Session:'; then
      error "Commit ${sha:0:7} carries a Claude-Session trailer; session links stay out of the history."
    fi
  done < <(git rev-list --no-merges "${BASE}..${HEAD_REF}")
  # The description becomes the commit body on main: its required
  # sections must say something. Bots (Dependabot) write their own.
  section() { printf '%s\n' "$BODY" | awk -v h="$1" 'index($0, h) && /^## / { on = 1; next } /^## / { on = 0 } on' | sed 's/<!--.*-->//g' | tr -d '[:space:]'; }
  # AI involvement is disclosed in one sober line, not a product ad
  # (CONTRIBUTING.md, "Saying that AI was involved").
  if printf '%s\n' "$BODY" | grep -qiE 'generated (with|by) \[?(claude|copilot|chatgpt|cursor|codex)'; then
    error "Replace the \"Generated with …\" footer with the AI line, e.g. \"🤖 AI-assisted · Claude Opus 5.5 (Anthropic)\"."
  fi
  if [ "$AUTHOR_TYPE" != Bot ] && [ -n "$SECTIONS" ]; then
    IFS=, read -ra required <<< "$SECTIONS"
    for h in "${required[@]}"; do
      [ -n "$(section "$h")" ] || error "The description's \"$h\" section is empty."
    done
  fi
  if [ "$fail" -ne 0 ]; then
    echo "See CONTRIBUTING.md: \"Branch names\", \"Commit messages and PR titles\", \"Writing the pull request\" and \"Saying that AI was involved\"."
    return 1
  fi
  echo "Conventions OK."
}

# One case: a scratch repository whose branch adds one commit with this
# message; expect 0 (passes) or 1 (fails).
test_case() {
  local name=$1 want=$2 branch=$3 title=$4 message=$5 body=$6 labels=${7:-} reviewed=${8:-} got dir
  dir=$(mktemp -d)
  (
    cd "$dir" && git init -q && git config user.email t@t && git config user.name t
    git commit -q --allow-empty -m "chore: base" && git checkout -q -b topic
    git commit -q --allow-empty -m "$message"
    [ "$reviewed" = head ] && reviewed=$(git rev-parse HEAD)
    BRANCH=$branch TITLE=$title BODY=$body LABELS=$labels REVIEWED_SHA=$reviewed BASE=$(git rev-parse HEAD~1) HEAD_REF=$(git rev-parse HEAD) check >/dev/null 2>&1
  ) && got=0 || got=1
  rm -rf "$dir"
  if [ "$got" = "$want" ]; then echo "ok   $name"; else echo "FAIL $name (want $want, got $got)"; return 1; fi
}

if [ "${1:-}" = "--test" ]; then
  good=$'## 📝 What changes\n\nA thing.\n\n## 💡 Why\n\nA reason.\n\n🤖 AI-assisted · Claude Opus 5.5 (Anthropic)'
  long="fix(sync): $(printf 'x%.0s' $(seq 1 95))"
  fail=0
  test_case "passes: everything right"            0 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" || fail=1
  test_case "passes: the matching type label"     0 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "type:fix,risk:low" || fail=1
  test_case "fails: branch without a type"        1 a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" || fail=1
  test_case "fails: title with a trailing period" 1 fix/a-thing "fix(sync): a thing." "fix(sync): a thing" "$good" || fail=1
  test_case "fails: title over 100 characters"    1 fix/a-thing "$long" "fix(sync): a thing" "$good" || fail=1
  test_case "fails: a commit that is not a header" 1 fix/a-thing "fix(sync): a thing" "Fixed a thing" "$good" || fail=1
  test_case "fails: a Claude-Session trailer"     1 fix/a-thing "fix(sync): a thing" $'fix(sync): a thing\n\nClaude-Session: https://claude.ai/code/x' "$good" || fail=1
  test_case "fails: an empty Why"                 1 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" $'## 📝 What changes\n\nA thing.\n\n## 💡 Why\n\n<!-- say why -->' || fail=1
  test_case "fails: a Generated with footer"      1 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good"$'\n🤖 Generated with [Claude Code](https://claude.com/claude-code)' || fail=1
  test_case "fails: title type unlike the label"  1 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "type:feat" || fail=1
  test_case "fails: unlike the label the review set on this commit" 1 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "type:feat" head || fail=1
  test_case "passes: a label from a commit the review has not read" 0 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "type:feat" 0123456789abcdef0123456789abcdef01234567 || fail=1
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

check
