#!/usr/bin/env bash
# A plugin's changelog, one file per change (#452), so two pull requests
# never edit the same lines of readme.txt.
#
# A pull request that changes what a user sees adds changelog.d/<n>.md,
# <n> the number of the issue it closes, with its lines: one bullet each
# (`* Fixed …`), as readme.txt's lines are written. Nothing in readme.txt's
# `== Changelog ==` changes by hand. The release pull request writes them
# under the version's heading and removes them (scripts/release-markers.sh
# prepare); while any is there, the readme is held: the next version is
# not ready (scripts/release-ready.sh).
#
#   changelog-fragments.sh check <dir>
#       every file of <dir>/changelog.d is <n>.md and holds bullets only;
#       exit 1, saying which, otherwise
#   changelog-fragments.sh collect <dir>
#       their lines, by number, for the release
#   changelog-fragments.sh any <dir>
#       exit 0 when there is at least one, 1 when there is none
#   changelog-fragments.sh pull-request <base-readme> <head-dir>
#       the check of a pull request, its `git diff --name-status` against
#       its base on stdin: the release (it removes fragments and leaves none)
#       may write readme.txt's changelog; any other pull request gets
#       `hand-edit`
#   changelog-fragments.sh hand-edit <base-readme> <head-readme>
#       exit 1 when the head's changelog has a line the base's lacks or
#       lacks one it has, beside headings, blank lines and the
#       `Unreleased.` hold; the pull request that removes fragments (the
#       release) is the one that may write them there
#   changelog-fragments.sh --test
#
# Runs its own tests.
set -euo pipefail

files() { # <dir>: every file of changelog.d, by number
  [ -d "$1/changelog.d" ] || return 0
  find "$1/changelog.d" -maxdepth 1 -type f ! -name '.gitkeep' -printf '%f\n' | sort -n
}

check() {
  local dir=$1 f fail=0 n=0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    n=$((n + 1))
    case "$f" in
      *[!0-9]*.md | .md) echo "::error file=changelog.d/$f::Not <number>.md: a fragment is named after the issue its pull request closes (changelog.d/123.md)." >&2; fail=1; continue ;;
      *.md) ;;
      *) echo "::error file=changelog.d/$f::Not <number>.md: a fragment is named after the issue its pull request closes (changelog.d/123.md)." >&2; fail=1; continue ;;
    esac
    if ! grep -q '[^[:space:]]' "$dir/changelog.d/$f"; then
      echo "::error file=changelog.d/$f::Empty: a fragment holds the change's lines, one bullet each." >&2; fail=1; continue
    fi
    if grep -nv -e '^[[:space:]]*$' -e '^\* [^[:space:]]' "$dir/changelog.d/$f" | sed 's/\r$//' | grep -q .; then
      echo "::error file=changelog.d/$f::Every line is a bullet (\`* …\`), as readme.txt's changelog lines are written." >&2; fail=1
    fi
  done < <(files "$dir")
  [ "$fail" -eq 0 ] && echo "Changelog fragments OK ($n)."
  return "$fail"
}

collect() {
  local f
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    # One line each, whether or not the file ends in a newline.
    awk '{ sub(/\r$/, "") } NF' "$1/changelog.d/$f"
  done < <(files "$1")
}

any() { [ -n "$(files "$1")" ]; }

lines() { # <readme>: the changelog's lines that are a change's own
  awk '
    { sub(/\r$/, "") }
    /^== Changelog ==$/ { c = 1; next }
    c && /^== .* ==$/ { exit }
    c && NF && !/^= .* =$/ && !/^Unreleased\.?$/ { print }
  ' "$1"
}

hand_edit() {
  if [ "$(lines "$1")" != "$(lines "$2")" ]; then
    echo "::error file=readme.txt::The changelog in readme.txt changed by hand: write this change's lines in changelog.d/<issue>.md instead (DiluxOne/.github#452); the release writes them into readme.txt." >&2
    return 1
  fi
  echo "readme.txt's changelog unchanged by hand."
}

pull_request() { # <base-readme> <head-dir>, the name-status on stdin
  # Read whole first: the writer of the pipe never meets a closed end.
  local diff; diff=$(cat)
  if grep -qE '^D[[:space:]]+changelog\.d/[0-9]+\.md$' <<<"$diff" && ! any "$2"; then
    echo "This pull request removes the changelog fragments and leaves none: the release, which writes them into readme.txt."
    return 0
  fi
  hand_edit "$1" "$2/readme.txt"
}

if [ "${1:-}" = "--test" ]; then
  fail=0
  t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
  ok()    { if "${@:2}" >/dev/null 2>&1; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
  fails() { if "${@:2}" >/dev/null 2>&1; then echo "FAIL $1"; fail=1; else echo "ok   $1"; fi; }
  mkdir -p "$t/p/changelog.d"
  ok    "no fragment is fine"                      check "$t/p"
  fails "any: none"                                any "$t/p"
  printf '* Fixed the second.\n' > "$t/p/changelog.d/12.md"
  printf '* Added the first.\n\n* And its detail.\n' > "$t/p/changelog.d/9.md"
  ok    "two fragments of bullets"                 check "$t/p"
  ok    "any: two"                                 any "$t/p"
  got=$(collect "$t/p" | tr '\n' '|')
  if [ "$got" = "* Added the first.|* And its detail.|* Fixed the second.|" ]; then echo "ok   collect: by number, blank lines out"; else echo "FAIL collect: $got"; fail=1; fi
  touch "$t/p/changelog.d/.gitkeep"
  ok    ".gitkeep is not a fragment"               check "$t/p"
  printf 'Fixed it.\n' > "$t/p/changelog.d/13.md"
  fails "a line that is not a bullet"              check "$t/p"
  rm "$t/p/changelog.d/13.md"; printf '* x\n' > "$t/p/changelog.d/fix.md"
  fails "a name that is not a number"              check "$t/p"
  rm "$t/p/changelog.d/fix.md"; : > "$t/p/changelog.d/14.md"
  fails "an empty fragment"                        check "$t/p"
  rm "$t/p/changelog.d/14.md"; printf '* CRLF.\r\n' > "$t/p/changelog.d/15.md"
  ok    "CRLF bullets"                             check "$t/p"
  rm -f "$t/p/changelog.d/"*.md; printf '* No newline' > "$t/p/changelog.d/1.md"; printf '* Next.\n' > "$t/p/changelog.d/2.md"
  got=$(collect "$t/p" | tr '\n' '|')
  if [ "$got" = "* No newline|* Next.|" ]; then echo "ok   collect: a file with no final newline stays its own line"; else echo "FAIL collect: $got"; fail=1; fi
  printf '== Changelog ==\n\n= 2.0.0 =\nUnreleased.\n\n* Old.\n\n= 1.0.0 =\n* First.\n\n== Upgrade Notice ==\nx\n' > "$t/base.txt"
  cp "$t/base.txt" "$t/head.txt"
  ok    "hand-edit: same changelog"                hand_edit "$t/base.txt" "$t/head.txt"
  sed 's/^\* Old\.$/* Old.\n* New by hand./' "$t/base.txt" > "$t/head.txt"
  fails "hand-edit: a bullet added"                hand_edit "$t/base.txt" "$t/head.txt"
  sed '/^Unreleased\.$/d' "$t/base.txt" > "$t/head.txt"
  ok    "hand-edit: the hold removed is not a change's line" hand_edit "$t/base.txt" "$t/head.txt"
  sed 's/^= 2.0.0 =$/= Unreleased =/' "$t/base.txt" > "$t/head.txt"
  ok    "hand-edit: a heading renamed"             hand_edit "$t/base.txt" "$t/head.txt"
  sed 's/^x$/y/' "$t/base.txt" > "$t/head.txt"
  ok    "hand-edit: another section changed"       hand_edit "$t/base.txt" "$t/head.txt"
  mkdir -p "$t/h/changelog.d"
  sed 's/^\* Old\.$/* Old.\n* Written by the release./' "$t/base.txt" > "$t/h/readme.txt"
  pr() { printf '%s\n' "$1" | pull_request "$t/base.txt" "$t/h"; }
  ok    "pull-request: the release removes every fragment and writes them in" pr $'D\tchangelog.d/9.md\nM\treadme.txt'
  printf '* Left.\n' > "$t/h/changelog.d/10.md"
  fails "pull-request: removing one fragment and leaving another is no release" pr $'D\tchangelog.d/9.md\nM\treadme.txt'
  rm "$t/h/changelog.d/10.md"
  fails "pull-request: no fragment removed, the changelog edited by hand" pr $'M\treadme.txt'
  fails "pull-request: a file that is not a fragment removed is no release" pr $'D\tchangelog.d/notes.txt\nM\treadme.txt'
  cp "$t/base.txt" "$t/h/readme.txt"
  ok    "pull-request: an ordinary one with a fragment"  pr $'A\tchangelog.d/11.md'
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

case "${1:-}" in
  check)     shift; [ $# -eq 1 ] || { echo "usage: changelog-fragments.sh check <dir>" >&2; exit 64; }; check "$1" ;;
  collect)   shift; [ $# -eq 1 ] || { echo "usage: changelog-fragments.sh collect <dir>" >&2; exit 64; }; collect "$1" ;;
  any)       shift; [ $# -eq 1 ] || { echo "usage: changelog-fragments.sh any <dir>" >&2; exit 64; }; any "$1" ;;
  pull-request) shift; [ $# -eq 2 ] || { echo "usage: changelog-fragments.sh pull-request <base-readme> <head-dir> < name-status" >&2; exit 64; }; pull_request "$1" "$2" ;;
  hand-edit) shift; [ $# -eq 2 ] || { echo "usage: changelog-fragments.sh hand-edit <base-readme> <head-readme>" >&2; exit 64; }; hand_edit "$1" "$2" ;;
  *) echo "usage: changelog-fragments.sh check|collect|any|pull-request|hand-edit … | --test" >&2; exit 64 ;;
esac
