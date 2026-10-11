#!/usr/bin/env bash
# The week's decisions by policy, as Markdown, for autonomy-digest.yml: issues
# labelled `accepted-by:policy` opened since SINCE and pull requests labelled
# `merged-by:policy` merged since then, in the organisation OWNER. The digest
# goes on a public issue, so a repository the organisation does not list as
# public is only counted, never named (no repository, title or link).
#
#   policy-digest.sh          print the digest (GH_TOKEN, OWNER, SINCE)
#   policy-digest.sh --test   self-test
set -euo pipefail

# Lines of JSON ({url, title, repository: {nameWithOwner}}) on stdin, the
# public repositories' names in $2 (one per line): prints the heading and
# the public lines for label $1, and the private ones' count on fd 3.
section() {
  local label=$1 publics=$2 mine="" private=0 row name
  while IFS= read -r row; do
    [ -n "$row" ] || continue
    name=$(jq -r '.repository.nameWithOwner' <<<"$row")
    if grep -qxF "$name" <<<"$publics"; then
      mine+="- $(jq -r '"[\(.repository.nameWithOwner)] \(.title) (\(.url))"' <<<"$row")"$'\n'
    else
      private=$((private + 1))
    fi
  done
  [ -z "$mine" ] || printf '**%s**\n%s\n' "$label" "$mine"
  echo "$private" >&3
}

digest() { # accepted rows, merged rows, public names, since
  local out p1 p2 tmp
  tmp=$(mktemp)
  local a m
  a=$(section accepted-by:policy "$3" <<<"$1" 3>"$tmp"); p1=$(cat "$tmp")
  m=$(section merged-by:policy "$3" <<<"$2" 3>"$tmp"); p2=$(cat "$tmp")
  # $( ) drops trailing newlines: join the two with a blank line between.
  out=$a
  [ -z "$m" ] || out+="${out:+$'\n\n'}$m"
  rm -f "$tmp"
  [ -n "$out" ] || out="Nothing in a public repository was accepted or merged by policy since $4."
  local private=$((p1 + p2))
  [ "$private" -eq 0 ] || out+=$'\n\n'"And ${private} in private repositories (not named here, since this issue is public)."
  printf '%s\n' "$out"
}

if [ "${1:-}" = --test ]; then
  fail=0
  check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1"; printf 'got:\n%s\nwant:\n%s\n' "$2" "$3"; fail=1; fi; }
  pub=$'DiluxOne/.github\nDiluxOne/diluxone-offload-wordpress'
  a='{"url":"u1","title":"Runner image: build failed","repository":{"nameWithOwner":"DiluxOne/.github"}}
{"url":"u2","title":"a private title","repository":{"nameWithOwner":"DiluxOne/diluxone-mail-wordpress"}}'
  got=$(digest "$a" "" "$pub" 2026-10-04)
  check "a public decision is named" "$(grep -c 'Runner image: build failed' <<<"$got")" 1
  check "a private one is never named" "$(grep -c 'private title\|diluxone-mail\|u2' <<<"$got")" 0
  check "a private one is counted" "$(grep -c 'And 1 in private repositories' <<<"$got")" 1
  got=$(digest '{"url":"u2","title":"x","repository":{"nameWithOwner":"DiluxOne/secret"}}' "" "$pub" 2026-10-04)
  check "a label with only private entries has no heading" "$(grep -c 'accepted-by:policy' <<<"$got")" 0
  check "a repository named like a public one's prefix stays private" "$(digest '{"url":"u","title":"t","repository":{"nameWithOwner":"DiluxOne/.github-private"}}' "" "$pub" d | grep -c 'github-private')" 0
  m='{"url":"u9","title":"merged one","repository":{"nameWithOwner":"DiluxOne/.github"}}'
  got=$(digest "$a" "$m" "$pub" d)
  check "both sections: the second heading starts its own line" "$(grep -c '^\*\*merged-by:policy\*\*$' <<<"$got")" 1
  check "an empty week says so" "$(digest "" "" "$pub" 2026-10-04)" "Nothing in a public repository was accepted or merged by policy since 2026-10-04."
  [ "$fail" = 0 ] && echo "all tests passed"
  exit "$fail"
fi

publics=$(gh repo list "$OWNER" --visibility public --limit 500 --json nameWithOwner --jq '.[].nameWithOwner')
accepted=$(gh search issues --owner "$OWNER" --label accepted-by:policy --created ">=$SINCE" --limit 200 --json url,title,repository --jq '.[] | @json')
merged=$(gh search prs --owner "$OWNER" --label merged-by:policy --merged-at ">=$SINCE" --limit 200 --json url,title,repository --jq '.[] | @json')
digest "$accepted" "$merged" "$publics" "$SINCE"
