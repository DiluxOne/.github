#!/usr/bin/env bash
# Whose type a pull request carries, for claude-review.yml: the review's,
# read from the diff, unless a person set a type:* label by hand. Then the
# person's stands: the last one a person added that is still on the pull
# request. A label any bot set is never a person's. The workflow asks
# twice: when it labels the verdict, and again just before it
# retitles the pull request, so a label a person changed in between (or a
# reused verdict) never puts the review's type back over theirs.
#
#   review-type.sh TYPE BOT TIMELINE LABELS   print the type to apply
#     TYPE      the review's type (feat, fix, ci, ...)
#     BOT       the review's bot login (any other *[bot] is not a person either)
#     TIMELINE  a file with the pull request's issue timeline, as
#               `gh api .../timeline --paginate` writes it (one or more arrays)
#     LABELS    its type:* labels now, comma-separated
#   review-type.sh TYPE BOT TIMELINE LABELS --diff KIND BASE HEAD
#               the same, with the review's docs bounded by the diff (#720):
#               when a file of BASE...HEAD is outside the docs paths
#               conventions.sh holds a docs title to (`surface.py
#               --docs-paths KIND`), the review's docs becomes chore. A
#               person's type:* label still wins; the conventions check then
#               tells them. An empty KIND: the organisation's paths alone.
#   review-type.sh --test                     self-test
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# The review's type, docs only when every changed file is documentation by
# the conventions check's own paths and its own `case` match.
bounded() {
  local type=$1 kind=$2 base=$3 head=$4 globs files f g is_doc
  [ "$type" = docs ] || { echo "$type"; return 0; }
  globs=$(python3 "$here/surface.py" --docs-paths "$kind") || return 1
  # --no-renames: a code file renamed into a .md is the code file deleted.
  files=$(git diff --no-renames --name-only "${base}...${head}") || return 1
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    is_doc=false
    while IFS= read -r g; do
      # shellcheck disable=SC2254 # the glob is the point.
      [ -n "$g" ] && case "$f" in $g) is_doc=true; break ;; esac
    done <<<"$globs"
    [ "$is_doc" = true ] || { echo chore; return 0; }
  done <<<"$files"
  echo docs
}

decide() {
  local type=$1 bot=$2 timeline=$3 labels=$4 human
  # shellcheck disable=SC2016 # jq variables, not shell ones.
  human=$(jq -r -s --arg bot "$bot" --arg labels "$labels" '
    ($labels | split(",") | map(gsub("^ +| +$"; ""))) as $now
    # Who put each type:* label on last; one taken off is forgotten.
    | reduce (.[][] | select((.event == "labeled" or .event == "unlabeled") and ((.label.name // "") | startswith("type:")))) as $e
        ([]; map(select(.name != $e.label.name)) + (if $e.event == "labeled" then [{name: $e.label.name, by: $e.actor.login}] else [] end))
    | [.[] | select((.by // "") as $by | $by != $bot and ($by | endswith("[bot]") | not) and (.name as $l | $now | index($l))) | .name] | last // ""' "$timeline") || return 1
  if [ -n "$human" ]; then echo "${human#type:}"; else echo "$type"; fi
}

self_test() {
  local dir fails=0 bot='dilux-bot[bot]'
  dir=$(mktemp -d)
  trap 'rm -rf "$dir"' RETURN
  ev() { printf '{"event":"%s","label":{"name":"%s"},"actor":{"login":"%s"}}' "$1" "$2" "$3"; }
  check() {
    local name=$1 want=$2 got
    got=$(decide "${@:3}")
    if [ "$got" = "$want" ]; then echo "ok   $name"; else echo "FAIL $name: got '$got', want '$want'"; fails=$((fails + 1)); fi
  }
  printf '[%s,%s,%s]' "$(ev labeled type:feat "$bot")" "$(ev unlabeled type:feat soydiloreto)" "$(ev labeled type:ci soydiloreto)" > "$dir/person.json"
  printf '[%s]' "$(ev labeled type:feat "$bot")" > "$dir/bot.json"
  printf '[%s,%s]' "$(ev labeled type:ci soydiloreto)" "$(ev unlabeled type:ci soydiloreto)" > "$dir/removed.json"
  # Two pages, as --paginate writes them.
  printf '[%s]\n[%s]' "$(ev labeled type:feat "$bot")" "$(ev labeled type:docs soydiloreto)" > "$dir/pages.json"
  printf '[%s]' "$(ev labeled bug soydiloreto)" > "$dir/other.json"
  printf '[%s,%s,%s]' "$(ev labeled type:ci soydiloreto)" "$(ev labeled type:docs soydiloreto)" "$(ev unlabeled type:docs soydiloreto)" > "$dir/earlier.json"
  check "C1: a person's type:ci wins over the review's feat" ci feat "$bot" "$dir/person.json" type:ci
  check "C2: only the review's label: its type applies" feat feat "$bot" "$dir/bot.json" type:feat
  check "C3: a person's label later removed: the review's type" feat feat "$bot" "$dir/removed.json" ""
  check "a person's label across paginated pages" docs feat "$bot" "$dir/pages.json" type:docs
  check "a label that is not type:* is not a type" fix fix "$bot" "$dir/other.json" ""
  check "a person's earlier label still on wins after a later one is removed" ci feat "$bot" "$dir/earlier.json" type:ci
  printf '[%s,%s,%s]' "$(ev labeled type:ci soydiloreto)" "$(ev unlabeled type:ci soydiloreto)" "$(ev labeled type:ci "$bot")" > "$dir/readded.json"
  check "a person's label the bot put back later is the bot's" feat feat "$bot" "$dir/readded.json" type:ci
  check "labels with spaces after the commas" ci feat "$bot" "$dir/person.json" "type:feat, type:ci"
  printf '[%s]' "$(ev labeled type:docs 'github-actions[bot]')" > "$dir/otherbot.json"
  check "another bot's label is not a person's" feat feat "$bot" "$dir/otherbot.json" type:docs
  printf '[{"event":"labeled","label":{"name":"type:docs"},"actor":null}]' > "$dir/ghost.json"
  check "a label by a deleted account (no actor) is still a person's" docs feat "$bot" "$dir/ghost.json" type:docs
  check "no labels yet" feat feat "$bot" "$dir/bot.json" ""
  # The review's docs, bounded by the docs paths (#720), on a repository of
  # its own: a doc and a test, docs only, and a kind's own docs path.
  local repo=$dir/repo
  git init -q "$repo"
  git -C "$repo" -c user.name=t -c user.email=t@t commit -q --allow-empty -m base
  git -C "$repo" branch -q base
  git -C "$repo" checkout -q -b docsonly
  mkdir -p "$repo/docs"; echo a > "$repo/docs/a.md"; echo b > "$repo/README.md"
  git -C "$repo" add -A; git -C "$repo" -c user.name=t -c user.email=t@t commit -q -m docs
  git -C "$repo" checkout -q -b withtest
  mkdir -p "$repo/tests"; echo t > "$repo/tests/test_a.py"
  git -C "$repo" add -A; git -C "$repo" -c user.name=t -c user.email=t@t commit -q -m test
  git -C "$repo" checkout -q -b readme base
  echo r > "$repo/readme.txt"
  git -C "$repo" add -A; git -C "$repo" -c user.name=t -c user.email=t@t commit -q -m readme
  in_repo() { (cd "$repo" && bash "$here/review-type.sh" "$@"); }
  check2() {
    local name=$1 want=$2 got
    got=$(in_repo "${@:3}" 2>/dev/null) || got="(failed)"
    if [ "$got" = "$want" ]; then echo "ok   $name"; else echo "FAIL $name: got '$got', want '$want'"; fails=$((fails + 1)); fi
  }
  check2 "#720: the review's docs with a doc and a test is chore" chore docs "$bot" "$dir/bot.json" "" --diff "" base withtest
  check2 "#720: the review's docs with docs only stays docs" docs docs "$bot" "$dir/bot.json" "" --diff "" base docsonly
  check2 "#720: a kind's own docs path (readme.txt) is docs" docs docs "$bot" "$dir/bot.json" "" --diff wordpress-plugin base readme
  check2 "#720: readme.txt is not docs for a kind without it" chore docs "$bot" "$dir/bot.json" "" --diff "" base readme
  check2 "#720: a type that is not docs is untouched" test test "$bot" "$dir/bot.json" "" --diff "" base withtest
  check2 "#720: a person's type:docs label still stands" docs feat "$bot" "$dir/pages.json" type:docs --diff "" base withtest
  if in_repo docs "$bot" "$dir/bot.json" "" --diff nosuch base withtest >/dev/null 2>&1; then echo "FAIL #720: an unreadable kind passed"; fails=$((fails + 1)); else echo "ok   #720: an unreadable kind fails"; fi
  if in_repo docs "$bot" "$dir/bot.json" "" --diff "" base 2>/dev/null; then echo "FAIL usage: --diff without HEAD accepted"; fails=$((fails + 1)); else echo "ok   usage: --diff needs KIND BASE HEAD"; fi
  if bash "${BASH_SOURCE[0]}" feat 2>/dev/null; then echo "FAIL usage: three arguments accepted"; fails=$((fails + 1)); else echo "ok   usage: wrong arguments exit non-zero"; fi
  echo 'not json' > "$dir/bad.json"
  if decide feat "$bot" "$dir/bad.json" "" 2>/dev/null; then echo "FAIL an unreadable timeline passed"; fails=$((fails + 1)); else echo "ok   an unreadable timeline fails"; fi
  [ "$fails" -eq 0 ] || { echo "$fails failing"; return 1; }
  echo "All review-type checks passed."
}

if [ "${1:-}" = --test ]; then self_test; exit; fi
usage="usage: review-type.sh TYPE BOT TIMELINE LABELS [--diff KIND BASE HEAD] | --test"
if [ $# -eq 8 ] && [ "$5" = --diff ]; then
  type=$(bounded "$1" "$6" "$7" "$8")
  decide "$type" "$2" "$3" "$4"
else
  [ $# -eq 4 ] || { echo "$usage" >&2; exit 2; }
  decide "$@"
fi
