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
# optional), AUTHOR_TYPE (Bot skips the sections; on a dependabot/ branch it
# also leaves the commits' length unmeasured and lets a title through whose
# shortened form, below, fits), MAX_LINES (the most lines
# the branch may change, lock files and translations aside; empty for no
# limit: CI sets it for authors who are not trusted; composer.lock,
# package-lock.json and the .po, .pot and .mo files of a languages/ directory
# do not count), TAKEN_OVER (the maintainer who took a bot's pull request
# over, as the policy found; MAX_LINES is then empty, and the log says why),
# KIND (the repository's kind, as the policy found; empty for none) and
# TRUSTED (false for an author who is not trusted: only then is the surface,
# below, checked; empty or true skips it) and PRE_PR (`required` where the
# repository must have a `make pre-pr`, the one check before a pull request:
# scripts/pre-pr.py required, from org.yml `pre-pr` and repos.yml; anything
# else checks nothing, #479).
#
# `conventions.sh --head-facts REPO PR SHA DIR` writes, for the gate that
# decides a take-over (#130), what GitHub says about a pull request: the
# head commit's author and committer logins (DIR/head-author,
# DIR/head-committer), who last added `needs-human` (DIR/needs-human-by)
# and the labels as they are now (DIR/labels, comma-separated). A read that
# fails leaves its file empty, which keeps the cap, never lifts it.
# Run from the repository.
#
# A pull request titled docs may change only documentation: the
# organisation's `docs-paths` (Markdown, the images under docs/, licence files
# and the issue templates) and the kind's (kinds/<kind>/surface.yml; a
# WordPress plugin's readme.txt). That is where a code change would hide
# behind the lightest review.
#
# A pull request from an author who is not trusted (TRUSTED=false, never a
# bot) whose type is not feat (and has no "!") may not add public surface:
# what the kind's pack lists (a WordPress plugin's settings, options, REST
# routes, AJAX endpoints, admin pages, post types, taxonomies, hooks,
# shortcodes and blocks), read from the diff by
# scripts/surface.py, which runs nothing of the pull request (#144). New
# functionality needs a Feature issue a maintainer accepted.
#
# A grouped Dependabot pull request comes titled past the limit ("Bump x
# from 1.0 to 1.1 in the dev group across 1 directory") and its commit says
# the same. The merge is a squash, so only the title reaches main: the
# check measures the title in its shortened form (dependabot_title), and
# the review's "Correct the title's type" step sets that form as the title.
#
#   conventions.sh                          check (exit 1 on any broken rule)
#   conventions.sh --dependabot-title <t>   print <t> shortened to MAX_HEADER
#   conventions.sh --test                   self-test against a scratch repository
set -euo pipefail

# The other scripts it calls (surface.py), wherever it is run from.
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

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

# A Dependabot title shortened to fit MAX_HEADER (default 100), dropping
# boilerplate first: " in the <group> group" and " across N directories",
# then the version it bumps from, then the one it bumps to. Printed as is
# when it already fits, and as short as it gets when nothing more can go.
dependabot_title() {
  local t=$1 max=${MAX_HEADER:-100}
  (( ${#t} > max )) || { printf '%s\n' "$t"; return; }
  t=$(sed -E 's/ in the [^ ]+ group//; s/ across [0-9]+ director(y|ies)//' <<<"$t")
  (( ${#t} > max )) && t=$(sed -E 's/ from [^ ]+ to ([^ ]+)/ to \1/' <<<"$t")
  (( ${#t} > max )) && t=$(sed -E 's/ to [^ ]+$//' <<<"$t")
  printf '%s\n' "$t"
}

# What GitHub says about a pull request's head and its `needs-human` (#130):
# one file per fact under $4, empty when the read fails. `--paginate` with
# `--jq` prints each page's matches in order, so the last line is the last
# event (gh does not take `--slurp` together with `--jq`).
head_facts() { # repo pr sha dir
  local repo=$1 pr=$2 sha=$3 dir=$4 author_committer
  mkdir -p "$dir"
  author_committer=$(gh api "repos/$repo/commits/$sha" --jq '[(.author.login // ""), (.committer.login // "")] | join(" ")' 2>/dev/null) || author_committer=" "
  printf '%s' "${author_committer%% *}" > "$dir/head-author"
  printf '%s' "${author_committer#* }" > "$dir/head-committer"
  gh api "repos/$repo/issues/$pr/timeline" --paginate --jq '.[] | select(.event == "labeled" and .label.name == "needs-human") | .actor.login' 2>/dev/null | tail -n1 | tr -d '\n' > "$dir/needs-human-by" || : > "$dir/needs-human-by"
  gh api "repos/$repo/issues/$pr/labels" --jq '[.[].name] | join(",")' 2>/dev/null | tr -d '\n' > "$dir/labels" || : > "$dir/labels"
}

check() {
  MAX_HEADER=${MAX_HEADER:-100}
  SECTIONS=${SECTIONS-What changes,Why}
  LABELS=${LABELS:-}
  COMMENTS_FILE=${COMMENTS_FILE:-}
  REVIEW_BOT=${REVIEW_BOT:-${DX_BOT_LOGIN:-dilux-bot[bot]}}
  AUTHOR_TYPE=${AUTHOR_TYPE:-User}
  MAX_LINES=${MAX_LINES:-}
  TAKEN_OVER=${TAKEN_OVER:-}
  KIND=${KIND:-}
  TRUSTED=${TRUSTED:-}
  TYPES='feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert'
  HEADER_RE="^(${TYPES})(\([a-z0-9._/-]+\))?!?: [^ ].*[^.]$"
  BRANCH_RE="^((${TYPES})/[a-z0-9][a-z0-9._-]*|dependabot/.+)$"
  fail=0
  dependabot=false
  [ "$AUTHOR_TYPE" = Bot ] && [[ "$BRANCH" == dependabot/* ]] && dependabot=true
  error() { echo "::error::$1"; fail=1; }
  # $3, the length the header is held to: MAX_HEADER, or none.
  check_header() {
    if ! [[ "$2" =~ $HEADER_RE ]]; then
      error "$1 is not a Conventional Commit header (\"type(scope): subject\", type one of ${TYPES//|/, }, no trailing period): \"$2\""
    elif [ -n "${3-$MAX_HEADER}" ] && (( ${#2} > ${3-$MAX_HEADER} )); then
      error "$1 is ${#2} characters; the limit is ${MAX_HEADER}: \"$2\""
    fi
  }
  [[ "$BRANCH" =~ $BRANCH_RE ]] || error "Branch \"$BRANCH\" must be <type>/<kebab-case-description>, type one of ${TYPES//|/, }."
  short=$(dependabot_title "$TITLE")
  if [ "$dependabot" = true ] && (( ${#TITLE} > MAX_HEADER )) && (( ${#short} <= MAX_HEADER )); then
    echo "The title is ${#TITLE} characters; the review shortens it to \"$short\", which is what is checked."
    check_header "The pull request title" "$short"
  else
    check_header "The pull request title" "$TITLE"
  fi
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
    if ! docs_globs=$(python3 "$here/surface.py" --docs-paths "$KIND"); then
      error "The documentation paths could not be read (kind \"$KIND\"), so a docs title cannot be checked."
    else
      while IFS= read -r f; do
        [ -n "$f" ] || continue
        is_doc=false
        while IFS= read -r g; do
          # shellcheck disable=SC2254 # the glob is the point.
          [ -n "$g" ] && case "$f" in $g) is_doc=true; break ;; esac
        done <<<"$docs_globs"
        [ "$is_doc" = true ] || error "The title says docs, but $f is not documentation: give the title the type of the change it carries."
      # --no-renames: a code file renamed into a .md shows as the code file
      # deleted, which is not documentation.
      done < <(git diff --no-renames --name-only "${BASE}...${HEAD_REF}")
    fi
  fi
  # No new functionality behind a type that is not feat, from an author who
  # is not trusted (#144). Only the kind knows what its surface is.
  ptype=''
  [[ "$TITLE" =~ $TYPE_RE ]] && [ -z "${BASH_REMATCH[3]}" ] && ptype=${BASH_REMATCH[1]}
  if [ "$TRUSTED" = false ] && [ "$AUTHOR_TYPE" != Bot ] && [ -n "$KIND" ] && [ -n "$ptype" ] && [ "$ptype" != feat ]; then
    surface_code=0
    added=$(python3 "$here/surface.py" --check "$KIND" "$BASE" "$HEAD_REF") || surface_code=$?
    if [ "$surface_code" -eq 1 ]; then
      error "This pull request is titled $ptype, but it adds new functionality: ${added//$'\n'/; }. New functionality needs a Feature issue that a maintainer has accepted, and a feat pull request that closes it: take it out of this pull request, or open that issue first. See https://github.com/DiluxOne/.github/blob/main/CONTRIBUTING.md#start-from-an-issue."
    elif [ "$surface_code" -ne 0 ]; then
      error "What this pull request adds could not be read (kind \"$KIND\"), so it cannot be told apart from new functionality."
    fi
  fi
  # A size an author who is not trusted may change at once. A bot's pull
  # request a maintainer took over is the maintainer's: no cap.
  if [ -n "$TAKEN_OVER" ] && [ -z "$MAX_LINES" ]; then
    echo "The size cap does not apply: $TAKEN_OVER took this pull request over (the head commit is theirs)."
  fi
  if [[ "$MAX_LINES" =~ ^[0-9]+$ ]] && [ "$MAX_LINES" -gt 0 ]; then
    changed=$(git diff --numstat "${BASE}...${HEAD_REF}" | awk -F'\t' '$3 !~ /(^|\/)(composer\.lock|package-lock\.json)$/ && $3 !~ /(^|\/)languages\/[^\/]+\.(po|pot|mo)$/ && $1 != "-" { n += $1 + $2 } END { print n + 0 }')
    if [ "$changed" -gt "$MAX_LINES" ]; then
      error "This pull request changes $changed lines; one from an author outside the maintainers may change at most $MAX_LINES. Split it into smaller pull requests, each closing its accepted issue, or ask a maintainer to take it over: a maintainer takes an autopilot pull request over by adding \`needs-human\`, removing \`autopilot\` and then pushing a commit of their own to its branch (the push runs this check again); the cap no longer applies once the head is theirs."
    fi
  fi
  while read -r sha; do
    [ -z "$sha" ] && continue
    # Dependabot writes its commits; the squash keeps only the title.
    if [ "$dependabot" = true ]; then
      check_header "Commit ${sha:0:7}" "$(git log -1 --format=%s "$sha")" ""
    else
      check_header "Commit ${sha:0:7}" "$(git log -1 --format=%s "$sha")"
    fi
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
  # #479: `make pre-pr`, the one check before a pull request, where the
  # organisation requires it.
  if [ "${PRE_PR:-}" = required ] && ! python3 "$here/pre-pr.py" has . >/dev/null 2>&1; then
    error "This repository's Makefile has no \`pre-pr\` target: \`make pre-pr\` is the one check before a pull request (DiluxOne/.github#479, kinds/README.md \`pre-pr\`), every check the pull request and the merge queue run. Add it in a pull request of its own; a repository that has none by design is listed in DiluxOne/.github repos.yml \`pre-pr\`."
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
  local name=$1 want=$2 branch=$3 title=$4 message=$5 body=$6 labels=${7:-} comments=${8:-} files=${9:-} max=${10:-} author=${11:-User} got dir
  dir=$(mktemp -d)
  (
    cd "$dir" && git init -q && git config user.email t@t && git config user.name t && git config commit.gpgsign false
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
    BRANCH=$branch TITLE=$title BODY=$body LABELS=$labels COMMENTS_FILE=$file REVIEW_BOT='dilux-bot[bot]' MAX_LINES=$max AUTHOR_TYPE=$author BASE=$(git rev-parse HEAD~1) HEAD_REF=$(git rev-parse HEAD) check >/dev/null 2>&1
  ) && got=0 || got=1
  rm -rf "$dir"
  if [ "$got" = "$want" ]; then echo "ok   $name"; else echo "FAIL $name (want $want, got $got)"; return 1; fi
}

if [ "${1:-}" = "--dependabot-title" ]; then
  dependabot_title "${2:-}"
  exit 0
fi

if [ "${1:-}" = "--head-facts" ]; then
  head_facts "${2:?repo}" "${3:?pr}" "${4:?sha}" "${5:?dir}"
  exit 0
fi

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
  KIND=wordpress-plugin test_case "passes: docs that change only docs" 0 docs/guide "docs(guide): a thing" "docs(guide): a thing" "$good" "" "" "docs/a.md:3,README.md:2,readme.txt:1" || fail=1
  test_case "passes: docs with no kind, the organisation's paths" 0 docs/guide "docs(guide): a thing" "docs(guide): a thing" "$good" "" "" "docs/a.md:3,README.md:2,LICENSE:1,.github/ISSUE_TEMPLATE/bug.yml:2" || fail=1
  test_case "fails: readme.txt is a kind's documentation, not every repository's" 1 docs/guide "docs(guide): a thing" "docs(guide): a thing" "$good" "" "" "readme.txt:1" || fail=1
  test_case "fails: docs that change code"         1 docs/guide "docs(guide): a thing" "docs(guide): a thing" "$good" "" "" "docs/a.md:3,includes/a.php:2" || fail=1
  test_case "passes: a fix may change code"        0 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "" "" "includes/a.php:2" || fail=1
  test_case "passes: under the size limit"         0 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "" "" "includes/a.php:50" 100 || fail=1
  test_case "fails: over the size limit"           1 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "" "" "includes/a.php:150" 100 || fail=1
  test_case "passes: lock files and translations do not count" 0 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "" "" "includes/a.php:50,composer.lock:500,languages/x.po:500" 100 || fail=1
  # A docs title over a code file renamed into a .md: the base has the code.
  dir=$(mktemp -d)
  if (
    cd "$dir" && git init -q && git config user.email t@t && git config user.name t && git config commit.gpgsign false
    mkdir includes && seq 1 40 > includes/a.php && git add . && git commit -q -m "chore: base" && git checkout -q -b docs/x
    git mv includes/a.php notes.md && git commit -q -m "docs: notes"
    BRANCH=docs/x TITLE="docs: notes" BODY=$good BASE=$(git rev-parse HEAD~1) HEAD_REF=$(git rev-parse HEAD) check >/dev/null 2>&1
  ); then echo "FAIL fails: docs that rename code into Markdown (want 1, got 0)"; fail=1; else echo "ok   fails: docs that rename code into Markdown"; fi
  rm -rf "$dir"
  # #479: a repository the organisation requires a `make pre-pr` of; $3 the
  # Makefile's text ("" for none), $4 PRE_PR.
  pre_pr_case() { # name want makefile mode
    local dir got
    dir=$(mktemp -d)
    (
      cd "$dir" && git init -q && git config user.email t@t && git config user.name t && git config commit.gpgsign false
      if [ -n "$3" ]; then printf '%b' "$3" > Makefile && git add Makefile; fi
      git commit -q --allow-empty -m "chore: base" && git checkout -q -b fix/a-thing
      git commit -q --allow-empty -m "fix(sync): a thing"
      PRE_PR=$4 BRANCH=fix/a-thing TITLE="fix(sync): a thing" BODY=$good BASE=$(git rev-parse HEAD~1) HEAD_REF=$(git rev-parse HEAD) check >/dev/null 2>&1
    ) && got=0 || got=1
    rm -rf "$dir"
    if [ "$got" = "$2" ]; then echo "ok   $1"; else echo "FAIL $1 (want $2, got $got)"; return 1; fi
  }
  pre_pr_case "#479: required, a Makefile with pre-pr passes"     0 'check:\n\ttrue\npre-pr: check\n' required || fail=1
  pre_pr_case "#479: required, a Makefile with no pre-pr fails"   1 'check:\n\ttrue\n' required || fail=1
  pre_pr_case "#479: required, no Makefile fails"                 1 '' required || fail=1
  pre_pr_case "#479: optional (the switch off), none still passes" 0 '' optional || fail=1
  pre_pr_case "#479: exempt by design, none passes"               0 '' exempt || fail=1
  # #144: no new functionality behind a type that is not feat, from an
  # author who is not trusted. The base holds includes/a.php; the branch
  # writes $5 to $6 (a path) and is checked as $3 (title), with $4 TRUSTED
  # and $7 AUTHOR_TYPE, for the wordpress-plugin kind; the output must say
  # $8 when given.
  surface_case() { # name want title trusted content path author expect
    local dir got out
    dir=$(mktemp -d)
    out=$(
      cd "$dir" && git init -q && git config user.email t@t && git config user.name t && git config commit.gpgsign false
      mkdir includes && printf '<?php\nfunction dx_a() {\n  return 1;\n}\ndo_action( %s );\n' "'dx_ready'" > includes/a.php
      git add . && git commit -q -m "chore: base" && git checkout -q -b fix/a-thing
      mkdir -p "$(dirname "$6")" && printf '%b' "$5" > "$6" && git add . && git commit -q -m "$3"
      BRANCH=fix/a-thing TITLE=$3 BODY=$good KIND=wordpress-plugin TRUSTED=$4 AUTHOR_TYPE=${7:-User} BASE=$(git rev-parse HEAD~1) HEAD_REF=$(git rev-parse HEAD) check 2>&1
    ) && got=0 || got=1
    rm -rf "$dir"
    if [ "$got" = "$2" ] && { [ -z "${8:-}" ] || grep -qF -- "$8" <<<"$out"; }; then echo "ok   $1"; else echo "FAIL $1 (want $2, got $got: $out)"; return 1; fi
  }
  route='<?php\nadd_action( "rest_api_init", function () {\n  register_rest_route( "dx/v1", "/items", array() );\n} );\n'
  edit='<?php\nfunction dx_a() {\n  return 2;\n}\ndo_action( '"'dx_ready'"' );\n'
  neutral="needs a Feature issue that a maintainer has accepted"
  surface_case "C1 (#144): an untrusted fix that adds a REST route fails, neutrally" 1 "fix(sync): a thing" false "$route" includes/rest.php User "$neutral" || fail=1
  surface_case "C1 (#144): the message names what it adds" 1 "fix(sync): a thing" false "$route" includes/rest.php User "a REST route (register_rest_route) (includes/rest.php)" || fail=1
  surface_case "C1 (#144): and links the contribution guide" 1 "fix(sync): a thing" false "$route" includes/rest.php User "CONTRIBUTING.md#start-from-an-issue" || fail=1
  surface_case "C1 (#144): any type that is not feat, a refactor too" 1 "refactor(sync): a thing" false "$route" includes/rest.php User "$neutral" || fail=1
  surface_case "C2 (#144): an untrusted docs pull request that changes PHP fails" 1 "docs(guide): a thing" false "$edit" includes/a.php User "includes/a.php is not documentation" || fail=1
  surface_case "C3 (#144): an untrusted fix that only changes existing code passes" 0 "fix(sync): a thing" false "$edit" includes/a.php || fail=1
  surface_case "C3 (#144): firing an existing hook again is not new" 0 "fix(sync): a thing" false '<?php\ndo_action( '"'dx_ready'"' );\n' includes/b.php || fail=1
  surface_case "C3 (#144): surface in tests is not the plugin's" 0 "fix(sync): a thing" false "$route" tests/rest-test.php || fail=1
  surface_case "C4 (#144): the same from a trusted author passes" 0 "fix(sync): a thing" true "$route" includes/rest.php || fail=1
  surface_case "C4 (#144): and from a bot" 0 "fix(sync): a thing" false "$route" includes/rest.php Bot || fail=1
  surface_case "#144: a feat may add surface" 0 "feat(sync): a thing" false "$route" includes/rest.php || fail=1
  surface_case "#144: so may a breaking change" 0 "fix(sync)!: a thing" false "$route" includes/rest.php || fail=1
  surface_case "#144: unknown trust (a local run without a login) is not checked" 0 "fix(sync): a thing" "" "$route" includes/rest.php || fail=1
  test_case "passes: translations at any depth do not count" 0 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "" "" "includes/a.php:50,includes/languages/x.po:500" 100 || fail=1
  test_case "fails: code under languages/ counts"  1 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "" "" "languages/loader.php:500" 100 || fail=1
  test_case "fails: a script under docs/ is not docs" 1 docs/guide "docs(guide): a thing" "docs(guide): a thing" "$good" "" "" "docs/build.sh:3" || fail=1
  test_case "passes: no limit for a trusted author" 0 fix/a-thing "fix(sync): a thing" "fix(sync): a thing" "$good" "" "" "includes/a.php:5000" "" || fail=1
  # #130: a bot's pull request a maintainer took over, over the size, passes
  # and says why; with the cap, the error says how to take one over.
  over() { # $1 MAX_LINES, $2 TAKEN_OVER; prints the check's output, exits as it does
    local dir; dir=$(mktemp -d)
    (
      cd "$dir" && git init -q && git config user.email t@t && git config user.name t && git config commit.gpgsign false
      git commit -q --allow-empty -m "chore: base" && git checkout -q -b fix/a-thing
      mkdir includes && seq 1 5000 > includes/a.php && git add . && git commit -q -m "fix(sync): a thing"
      BRANCH=fix/a-thing TITLE="fix(sync): a thing" BODY=$good MAX_LINES=$1 TAKEN_OVER=$2 AUTHOR_TYPE=Bot BASE=$(git rev-parse HEAD~1) HEAD_REF=$(git rev-parse HEAD) check 2>&1
    ); local code=$?
    rm -rf "$dir"; return $code
  }
  if out=$(over "" soydiloreto) && grep -q "soydiloreto took this pull request over" <<<"$out"; then echo "ok   C1 (#130): a taken-over autopilot pull request over the size passes and says so"; else echo "FAIL C1 (#130): a taken-over autopilot pull request over the size passes and says so"; fail=1; fi
  if ! out=$(over 600 "") && grep -q "may change at most 600" <<<"$out" && grep -q 'needs-human' <<<"$out" && grep -q 'removing `autopilot`' <<<"$out" && grep -q "then pushing a commit of their own" <<<"$out"; then echo "ok   C2/C3 (#130): with the cap it fails as today, and the error says how a maintainer takes it over"; else echo "FAIL C2/C3 (#130): with the cap it fails as today, and the error says how a maintainer takes it over"; fail=1; fi
  # #130: the facts the gate reads, against a gh that answers like the real
  # one (fixtures run through jq; `--slurp` with `--jq` refused, as gh does).
  gh() {
    local endpoint=$2 expr="" slurp=false a
    for a in "$@"; do case "$a" in --slurp) slurp=true ;; esac; done
    while [ $# -gt 0 ]; do [ "$1" = --jq ] && expr=$2; shift; done
    if $slurp && [ -n "$expr" ]; then echo 'the `--slurp` option is not supported with `--jq` or `--template`' >&2; return 1; fi
    case "$endpoint" in
      */commits/*) jq -r "$expr" <<<'{"author":{"login":"soydiloreto"},"committer":{"login":"soydiloreto"}}' ;;
      */timeline) jq -r "$expr" <<<'[{"event":"labeled","label":{"name":"autopilot"},"actor":{"login":"dilux-bot[bot]"}},{"event":"labeled","label":{"name":"needs-human"},"actor":{"login":"dilux-bot[bot]"}},{"event":"unlabeled","label":{"name":"needs-human"},"actor":{"login":"soydiloreto"}},{"event":"labeled","label":{"name":"needs-human"},"actor":{"login":"soydiloreto"}}]' ;;
      */labels) jq -r "$expr" <<<'[{"name":"needs-human"},{"name":"type:fix"}]' ;;
      *) return 1 ;;
    esac
  }
  dir=$(mktemp -d)
  head_facts o/r 35 abc "$dir"
  facts="$(cat "$dir/head-author")|$(cat "$dir/head-committer")|$(cat "$dir/needs-human-by")|$(cat "$dir/labels")"
  if [ "$facts" = "soydiloreto|soydiloreto|soydiloreto|needs-human,type:fix" ]; then echo "ok   C1 (#130): the gate reads the head's logins, who last added needs-human and the labels"; else echo "FAIL C1 (#130): the gate reads the head's logins, who last added needs-human and the labels (got $facts)"; fail=1; fi
  gh() { return 1; }
  head_facts o/r 35 abc "$dir"
  if [ -z "$(cat "$dir/head-author" "$dir/head-committer" "$dir/needs-human-by" "$dir/labels")" ]; then echo "ok   C2 (#130): a read that fails leaves every fact empty (the cap stays)"; else echo "FAIL C2 (#130): a read that fails leaves every fact empty (the cap stays)"; fail=1; fi
  unset -f gh
  rm -rf "$dir"
  # Dependabot: a grouped title, and one too long even without its boilerplate.
  grouped="build(deps-dev): Bump @aws-sdk/client-s3 from 3.1141.0 to 3.1146.0 in the dev-dependencies group across 1 directory"
  huge="build(deps-dev): Bump @a-very-long-scope/$(printf 'x%.0s' $(seq 1 60)) from 1.0.0 to 2.0.0"
  test_case "passes: a grouped Dependabot title and commit"      0 dependabot/npm_and_yarn/dev-x "$grouped" "$grouped" "" "" "" "" "" Bot || fail=1
  test_case "fails: the same from a person"                       1 dependabot/npm_and_yarn/dev-x "$grouped" "$grouped" "$good" || fail=1
  test_case "fails: the same on a branch of a person's"           1 build/dev-x "$grouped" "$grouped" "" "" "" "" "" Bot || fail=1
  test_case "fails: a Dependabot title too long even shortened"   1 dependabot/npm_and_yarn/dev-x "$huge from 1.0.0 to 2.0.0" "$grouped" "" "" "" "" "" Bot || fail=1
  test_case "fails: a Dependabot commit that is not a header"     1 dependabot/npm_and_yarn/dev-x "$grouped" "Bump x" "" "" "" "" "" Bot || fail=1
  short() {
    local got; got=$(MAX_HEADER=${3:-100} dependabot_title "$1")
    if [ "$got" = "$2" ]; then echo "ok   shortens: \"$2\""; else echo "FAIL shortens: want \"$2\", got \"$got\""; return 1; fi
  }
  short "$grouped" "build(deps-dev): Bump @aws-sdk/client-s3 from 3.1141.0 to 3.1146.0" || fail=1
  short "ci(deps): Bump the github-actions group across 2 directories with 3 updates" "ci(deps): Bump the github-actions group across 2 directories with 3 updates" || fail=1
  short "ci(deps): Bump actions/checkout from 6.0.0 to 7.0.1 in the github-actions group" "ci(deps): Bump actions/checkout to 7.0.1" 50 || fail=1
  short "ci(deps): Bump actions/checkout from 6.0.0 to 7.0.1 across 3 directories" "ci(deps): Bump actions/checkout" 35 || fail=1
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

check
