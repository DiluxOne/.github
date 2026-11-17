#!/usr/bin/env bash
# The week's decisions by policy, as Markdown, for autonomy-digest.yml, read
# from each repository's receipts (#804; scripts/receipts.py `decisions`),
# never from a label: issues a lane of policy/autonomy.yml accepted since
# SINCE (the lane decision in force), and pull requests merged since then
# whose last merge decision was the policy's, for the head that merged, in
# the organisation OWNER. The digest goes on a public issue, so a repository
# the organisation does not list as public is only counted, never named (no
# repository, title or link). A repository whose receipts could not be read
# is said so (a private one only counted), never taken for an empty week.
#
#   policy-digest.sh          print the digest (GH_TOKEN, OWNER, SINCE)
#   policy-digest.sh --test   self-test
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# Lines of JSON ({url, title, repository: {nameWithOwner}}) on stdin, the
# public repositories' names in $2 (one per line): prints the heading $1 and
# the public lines, and the private ones' count on fd 3.
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

digest() { # accepted rows, merged rows, public names, since[, unread names]
  local out p1 p2 tmp
  tmp=$(mktemp)
  local a m
  a=$(section "Accepted by policy" "$3" <<<"$1" 3>"$tmp"); p1=$(cat "$tmp")
  m=$(section "Merged by policy" "$3" <<<"$2" 3>"$tmp"); p2=$(cat "$tmp")
  # $( ) drops trailing newlines: join the two with a blank line between.
  out=$a
  [ -z "$m" ] || out+="${out:+$'\n\n'}$m"
  rm -f "$tmp"
  [ -n "$out" ] || out="Nothing in a public repository was accepted or merged by policy since $4."
  local private=$((p1 + p2))
  [ "$private" -eq 0 ] || out+=$'\n\n'"And ${private} in private repositories (not named here, since this issue is public)."
  # Receipts that could not be read: said, never an empty week (#804).
  local unread_pub="" unread_priv=0 name
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    if grep -qxF "$name" <<<"$3"; then unread_pub+="${unread_pub:+, }$name"; else unread_priv=$((unread_priv + 1)); fi
  done <<<"${5:-}"
  if [ -n "$unread_pub" ] || [ "$unread_priv" -gt 0 ]; then
    local which=$unread_pub
    [ "$unread_priv" -eq 0 ] || which+="${which:+, and }${unread_priv} private"
    out+=$'\n\n'"The receipts of ${which} could not be read: what the policy decided there is missing from this list."
  fi
  printf '%s\n' "$out"
}

# What the live run reads; the self-test puts its own in their place.
list_repos() { # "owner/name VISIBILITY" per line
  gh repo list "$OWNER" --no-archived --limit 500 --json nameWithOwner,visibility --jq '.[] | "\(.nameWithOwner) \(.visibility)"'
}
read_decisions() { # repo, since: receipts.py's rows; exit 2 when unreadable
  GITHUB_REPOSITORY=$1 python3 "$HERE/receipts.py" decisions --since "$2"
}
fetch_item() { # repo, kind, number: {title, url[, merged_at, head]}
  if [ "$2" = accepted ]; then
    gh api "repos/$1/issues/$3" --jq '{title, url: .html_url}'
  else
    gh api "repos/$1/pulls/$3" --jq '{title, url: .html_url, merged_at, head: .head.sha}'
  fi
}

# The week's decisions from the receipts, into DIR: accepted and merged
# (rows as digest() reads them), publics and unread (names, one per line).
from_receipts() { # since, dir
  local since=$1 dir=$2 repo vis rows row kind n item
  : >"$dir/accepted"; : >"$dir/merged"; : >"$dir/publics"; : >"$dir/unread"
  while read -r repo vis; do
    [ -n "$repo" ] || continue
    [ "$vis" != PUBLIC ] || echo "$repo" >>"$dir/publics"
    if ! rows=$(read_decisions "$repo" "$since"); then
      echo "$repo" >>"$dir/unread"
      continue
    fi
    while IFS= read -r row; do
      [ -n "$row" ] || continue
      kind=$(jq -r .kind <<<"$row")
      n=$(jq -r .number <<<"$row")
      [[ "$n" =~ ^[0-9]+$ ]] || continue
      if ! item=$(fetch_item "$repo" "$kind" "$n"); then
        grep -qxF "$repo" "$dir/unread" || echo "$repo" >>"$dir/unread"
        continue
      fi
      case "$kind" in
        accepted)
          jq -c --arg r "$repo" '{url, title, repository: {nameWithOwner: $r}}' <<<"$item" >>"$dir/accepted" ;;
        merged)
          # Merged since SINCE, at the head the policy decided: a decision
          # for another head, or a pull request not merged, is no merge by
          # policy (receipts.py merge_in_force).
          jq -c --arg r "$repo" --arg s "$since" --argjson d "$row" \
            'select(.merged_at != null and .merged_at >= $s and .head == $d.head) | {url, title, repository: {nameWithOwner: $r}}' <<<"$item" >>"$dir/merged" ;;
      esac
    done <<<"$rows"
  done < <(list_repos)
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
  check "a section with only private entries has no heading" "$(grep -c 'Accepted by policy' <<<"$got")" 0
  check "a repository named like a public one's prefix stays private" "$(digest '{"url":"u","title":"t","repository":{"nameWithOwner":"DiluxOne/.github-private"}}' "" "$pub" d | grep -c 'github-private')" 0
  m='{"url":"u9","title":"merged one","repository":{"nameWithOwner":"DiluxOne/.github"}}'
  got=$(digest "$a" "$m" "$pub" d)
  check "both sections: the second heading starts its own line" "$(grep -c '^\*\*Merged by policy\*\*$' <<<"$got")" 1
  sync='{"url":"u3","title":"Keep the organisation'"'"'s shared files in step","repository":{"nameWithOwner":"DiluxOne/diluxone-offload-wordpress"}}'
  check "a sync run's issue the org-sync lane accepted is listed (#155)" "$(digest "$sync" "" "$pub" d | grep -c "shared files in step (u3)")" 1
  check "an empty week says so" "$(digest "" "" "$pub" 2026-10-04)" "Nothing in a public repository was accepted or merged by policy since 2026-10-04."

  # C2 (#804): the same week's decisions, once read from the labels (the
  # rows above) and now from the receipts, give the same digest.
  labels_digest=$(digest "$a"$'\n'"$sync" "$m" "$pub" 2026-10-04)
  fx=$(mktemp -d)
  trap 'rm -rf "$fx"' EXIT
  rec() { mkdir -p "$fx/$1/$(dirname "$2")"; printf '%s\n' "$3" >"$fx/$1/$2"; }
  lane() { printf '{"kind":"lane-decision","issue":%s,"lane":"%s","decided_by":"policy","decided":"%s","rule":"policy/autonomy.yml#lanes.%s","policy":"DiluxOne/.github@abc","at":"%s"}' "$1" "$2" "$3" "$2" "$4"; }
  merge() { printf '{"kind":"merge-decision","pull_request":%s,"decided":"%s","rule":"policy/autonomy.yml#lanes.platform.merge","head":"%s","policy":"DiluxOne/.github@abc","at":"%s"}' "$1" "$2" "$3" "$4"; }
  rec .github issues/1/lane-2026-10-05T10:00:00Z.json "$(lane 1 platform policy 2026-10-05T10:00:00Z)"
  rec .github pulls/9/merge-2026-10-06T10:00:00Z.json "$(merge 9 policy h9 2026-10-06T10:00:00Z)"
  # Not decisions of the week: withdrawn, before SINCE, another head, not merged.
  rec .github issues/4/lane-2026-10-05T10:00:00Z.json "$(lane 4 platform policy 2026-10-05T10:00:00Z)"
  rec .github issues/4/lane-2026-10-06T10:00:00Z.json "$(lane 4 platform withdrawn 2026-10-06T10:00:00Z)"
  rec .github issues/5/lane-2026-09-20T10:00:00Z.json "$(lane 5 platform policy 2026-09-20T10:00:00Z)"
  rec .github pulls/10/merge-2026-10-06T10:00:00Z.json "$(merge 10 policy old 2026-10-06T10:00:00Z)"
  rec .github pulls/11/merge-2026-10-06T10:00:00Z.json "$(merge 11 policy h11 2026-10-06T10:00:00Z)"
  rec diluxone-mail-wordpress issues/2/lane-2026-10-05T10:00:00Z.json "$(lane 2 platform policy 2026-10-05T10:00:00Z)"
  rec diluxone-offload-wordpress issues/3/lane-2026-10-07T10:00:00Z.json "$(lane 3 org-sync policy 2026-10-07T10:00:00Z)"
  list_repos() { printf '%s\n' "DiluxOne/.github PUBLIC" "DiluxOne/diluxone-mail-wordpress PRIVATE" "DiluxOne/diluxone-offload-wordpress PUBLIC"; }
  read_decisions() { RECEIPTS_FIXTURE="$fx/${1#DiluxOne/}" GITHUB_REPOSITORY=$1 python3 "$HERE/receipts.py" decisions --since "$2"; }
  fetch_item() {
    case "$1#$3" in
      DiluxOne/.github#1) echo '{"title":"Runner image: build failed","url":"u1"}' ;;
      DiluxOne/diluxone-mail-wordpress#2) echo '{"title":"a private title","url":"u2"}' ;;
      DiluxOne/diluxone-offload-wordpress#3) echo '{"title":"Keep the organisation'"'"'s shared files in step","url":"u3"}' ;;
      DiluxOne/.github#9) echo '{"title":"merged one","url":"u9","merged_at":"2026-10-06T11:00:00Z","head":"h9"}' ;;
      DiluxOne/.github#10) echo '{"title":"merged at another head","url":"u10","merged_at":"2026-10-06T11:00:00Z","head":"new"}' ;;
      DiluxOne/.github#11) echo '{"title":"still open","url":"u11","merged_at":null,"head":"h11"}' ;;
      *) echo "unexpected item $1#$3" >&2; return 1 ;;
    esac
  }
  out=$(mktemp -d)
  from_receipts 2026-10-04 "$out"
  receipts_digest=$(digest "$(cat "$out/accepted")" "$(cat "$out/merged")" "$(cat "$out/publics")" 2026-10-04 "$(cat "$out/unread")")
  check "C2: the receipts give the same digest as the labels did" "$receipts_digest" "$labels_digest"
  check "C2: a private repository is still counted, never named" "$(grep -c 'And 1 in private repositories' <<<"$receipts_digest"),$(grep -c 'private title\|diluxone-mail\|u2' <<<"$receipts_digest")" "1,0"
  # Receipts that cannot be read are said, a private repository's counted.
  read_decisions() { [ "$1" = DiluxOne/.github ] || return 2; RECEIPTS_FIXTURE="$fx/.github" GITHUB_REPOSITORY=$1 python3 "$HERE/receipts.py" decisions --since "$2"; }
  from_receipts 2026-10-04 "$out"
  got=$(digest "$(cat "$out/accepted")" "$(cat "$out/merged")" "$(cat "$out/publics")" 2026-10-04 "$(cat "$out/unread")")
  check "C2: unreadable receipts are said, never an empty week" "$(grep -c 'The receipts of DiluxOne/diluxone-offload-wordpress, and 1 private could not be read' <<<"$got"),$(grep -c 'diluxone-mail' <<<"$got")" "1,0"
  rm -rf "$out"
  [ "$fail" = 0 ] && echo "all tests passed"
  exit "$fail"
fi

out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
from_receipts "$SINCE" "$out"
digest "$(cat "$out/accepted")" "$(cat "$out/merged")" "$(cat "$out/publics")" "$SINCE" "$(cat "$out/unread")"
