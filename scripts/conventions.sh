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
# optional), COMMENTS_FILE and REVIEW_BOT (the pull request's comments as the
# REST API lists them, and the login of the App whose review records count;
# optional), AUTHOR_TYPE (Bot skips the sections), MAX_LINES (the most lines
# the branch may change, lock files and translations aside; empty for no
# limit: CI sets it for authors who are not trusted; composer.lock,
# package-lock.json and the .po, .pot and .mo files of a languages/ directory
# do not count).
# Run from the repository.
#
# A pull request titled docs may change only documentation: Markdown, the
# images under docs/, readme.txt, licence files and the issue templates. That is
# where a code change would hide behind the lightest review.
#
#   conventions.sh          check (exit 1 on any broken rule)
#   conventions.sh --test   self-test against a scratch repository
set -euo pipefail

# Whether the review is still to read HEAD_REF: its last record (only the
# review App's own comment counts, and only a 40-hex commit) names another
# commit, and the review is not capped (count below max, 5 by default: a
# capped review reads no new commit, so its label stands). Without a
# readable record the comparison runs: nothing here can switch it off.
review_pending() {
  local record sha count max
  [ -n "$COMMENTS_FILE" ] && [ -s "$COMMENTS_FILE" ] || return 1
  # shellcheck disable=SC2016 # jq variables, not shell ones.
  record=$(jq -r --arg bot "$REVIEW_BOT" '[.[] | select(.user.login == $bot and (.body | startswith("<!-- dx-review -->"))) | .body] | last // ""' "$COMMENTS_FILE" 2>/dev/null \
    | sed -n 's/^.*<!-- dx-review-record \(.*\) -->.*$/\1/p' | tail -1 || true)
  sha=$(jq -r '.sha // ""' <<<"${record:-null}" 2>/dev/null || true)
  count=$(jq -r '.count // 0' <<<"${record:-null}" 2>/dev/null || echo 0)
  max=$(jq -r '.max // 5' <<<"${record:-null}" 2>/dev/null || echo 5)
  [[ "$sha" =~ ^[0-9a-f]{40}$ ]] && [[ "$count" =~ ^[0-9]+$ ]] && [[ "$max" =~ ^[0-9]+$ ]] || return 1
  [ "$sha" != "$HEAD_REF" ] && [ "$count" -lt "$max" ]
}

check() {
  MAX_HEADER=${MAX_HEADER:-100}
  SECTIONS=${SECTIONS-What changes,Why}
  LABELS=${LABELS:-}
  COMMENTS_FILE=${COMMENTS_FILE:-}
  REVIEW_BOT=${REVIEW_BOT:-dilux-bot[bot]}
  AUTHOR_TYPE=${AUTHOR_TYPE:-User}
  MAX_LINES=${MAX_LINES:-}
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
  if [ -n "$typelabel" ] && review_pending; then
    echo "The review has not read ${HEAD_REF:0:7} yet; the title's type is checked against its reading once it has."
  elif [ -n "$typelabel" ] && [[ "$TITLE" =~ $TYPE_RE ]]; then
    token=${BASH_REMATCH[1]}; bang=${BASH_REMATCH[3]}
    if [ "$typelabel" = breaking ]; then
      [ "$bang" = '!' ] || error "The pull request is labelled type:breaking, so its title needs the \"!\" of a breaking change: \"$token$bang:\"."
    elif [ "$token" != "$typelabel" ]; then
      error "The pull request is labelled type:$typelabel but its title says \"$token:\"; the title must carry the labelled type (the review sets it; change the label if the review is wrong)."
    fi
  fi
  # Documentation only, when the title says docs.
  DOCS_RE='^docs(\([^)]*\))?!?: '
  if [[ "$TITLE" =~ $DOCS_RE ]]; then
    while IFS= read -r f; do
      case "$f" in
        ''|*.md|docs/*.png|docs/*.jpg|docs/*.jpeg|docs/*.gif|docs/*.webp|readme.txt|LICENSE|LICENSE.*|COPYING|.github/ISSUE_TEMPLATE/*) ;;
        *) error "The title says docs, but $f is not documentation: give the title the type of the change it carries." ;;
      esac
    # --no-renames: a code file renamed into a .md shows as the code file
    # deleted, which is not documentation.
    done < <(git diff --no-renames --name-only "${BASE}...${HEAD_REF}")
  fi
  # A size an author who is not trusted may change at once.
  if [[ "$MAX_LINES" =~ ^[0-9]+$ ]] && [ "$MAX_LINES" -gt 0 ]; then
    changed=$(git diff --numstat "${BASE}...${HEAD_REF}" | awk -F'\t' '$3 !~ /(^|\/)(composer\.lock|package-lock\.json)$/ && $3 !~ /(^|\/)languages\/[^\/]+\.(po|pot|mo)$/ && $1 != "-" { n += $1 + $2 } END { print n + 0 }')
    if [ "$changed" -gt "$MAX_LINES" ]; then
      error "This pull request changes $changed lines; one from an author outside the maintainers may change at most $MAX_LINES. Split it into smaller pull requests, each closing its accepted issue, or ask a maintainer to take it over."
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
  local name=$1 want=$2 branch=$3 title=$4 message=$5 body=$6 labels=${7:-} comments=${8:-} files=${9:-} max=${10:-} got dir
  dir=$(mktemp -d)
  (
    cd "$dir" && git init -q && git config user.email t@t && git config user.name t
    git commit -q --allow-empty -m "chore: base" && git checkout -q -b topic
    # files: "path:lines,path:lines", each written with that many lines.
    if [ -n "$files" ]; then
      IFS=, read -ra specs <<< "$files"
      for spec in "${specs[@]}"; do
        mkdir -p "$(dirname "${spec%%:*}")"; seq 1 "${spec##*:}" > "${spec%%:*}"; git add "${spec%%:*}"
      done
    fi
    git commit -q --allow-empty -m "$message"
    file=""
    if [ -n "$comments" ]; then
      file=$(mktemp); printf '%s' "${comments//HEADSHA/$(git rev-parse HEAD)}" > "$file"
    fi
    BRANCH=$branch TITLE=$title BODY=$body LABELS=$labels COMMENTS_FILE=$file REVIEW_BOT='dilux-bot[bot]' MAX_LINES=$max BASE=$(git rev-parse HEAD~1) HEAD_REF=$(git rev-parse HEAD) check >/dev/null 2>&1
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
  # One page of comments holding the review App's record: login, sha, count
  # and, optionally, the cap.
  rec() {
    local max=""; [ -n "${4:-}" ] && max=",\\\"max\\\":$4"
    printf '[{"user":{"login":"%s"},"body":"<!-- dx-review -->\\n<!-- dx-review-record {\\"sha\\":\\"%s\\",\\"count\\":%s%s} -->"}]' "$1" "$2" "$3" "$max"
  }
  other=0123456789abcdef0123456789abcdef01234567
  test_case "fails: unlike the label the review set on this commit" 1 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "type:feat" "$(rec 'dilux-bot[bot]' HEADSHA 1 '')" || fail=1
  test_case "passes: a label from a commit the review has not read" 0 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "type:feat" "$(rec 'dilux-bot[bot]' "$other" 1 '')" || fail=1
  test_case "fails: a record anyone else posted counts for nothing" 1 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "type:feat" "$(rec 'someone' "$other" 1 '')" || fail=1
  test_case "fails: a capped review reads no new commit"          1 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "type:feat" "$(rec 'dilux-bot[bot]' "$other" 3 3)" || fail=1
  test_case "passes: under a cap of its own, the review is still to come" 0 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "type:feat" "$(rec 'dilux-bot[bot]' "$other" 3 8)" || fail=1
  test_case "fails: a record whose sha is not a commit"           1 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "type:feat" "$(rec 'dilux-bot[bot]' 'abc\\nx' 1 '')" || fail=1
  test_case "passes: the last page's record (paginated arrays)"    0 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "type:feat" "$(rec 'dilux-bot[bot]' HEADSHA 1 '')$(rec 'dilux-bot[bot]' "$other" 2 '')" || fail=1
  test_case "passes: docs that change only docs"   0 docs/guide "docs(guide): a thing" "docs(guide): a thing" "$good" "" "" "docs/a.md:3,README.md:2,readme.txt:1" || fail=1
  test_case "fails: docs that change code"         1 docs/guide "docs(guide): a thing" "docs(guide): a thing" "$good" "" "" "docs/a.md:3,includes/a.php:2" || fail=1
  test_case "passes: a fix may change code"        0 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "" "" "includes/a.php:2" || fail=1
  test_case "passes: under the size limit"         0 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "" "" "includes/a.php:50" 100 || fail=1
  test_case "fails: over the size limit"           1 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "" "" "includes/a.php:150" 100 || fail=1
  test_case "passes: lock files and translations do not count" 0 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "" "" "includes/a.php:50,composer.lock:500,languages/x.po:500" 100 || fail=1
  # A docs title over a code file renamed into a .md: the base has the code.
  dir=$(mktemp -d)
  if (
    cd "$dir" && git init -q && git config user.email t@t && git config user.name t
    mkdir includes && seq 1 40 > includes/a.php && git add . && git commit -q -m "chore: base" && git checkout -q -b docs/x
    git mv includes/a.php notes.md && git commit -q -m "docs: notes"
    BRANCH=docs/x TITLE="docs: notes" BODY=$good BASE=$(git rev-parse HEAD~1) HEAD_REF=$(git rev-parse HEAD) check >/dev/null 2>&1
  ); then echo "FAIL fails: docs that rename code into Markdown (want 1, got 0)"; fail=1; else echo "ok   fails: docs that rename code into Markdown"; fi
  rm -rf "$dir"
  test_case "passes: translations at any depth do not count" 0 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "" "" "includes/a.php:50,includes/languages/x.po:500" 100 || fail=1
  test_case "fails: code under languages/ counts"  1 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "" "" "languages/loader.php:500" 100 || fail=1
  test_case "fails: a script under docs/ is not docs" 1 docs/guide "docs(guide): a thing" "docs(guide): a thing" "$good" "" "" "docs/build.sh:3" || fail=1
  test_case "passes: no limit for a trusted author" 0 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "" "" "includes/a.php:5000" "" || fail=1
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

check
