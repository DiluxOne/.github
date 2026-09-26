#!/usr/bin/env bash
# Whether a readme says its next version is ready.
#
#   release-ready.sh readme.txt
#
# Reads the newest entry under `== Changelog ==`: its heading (`= X.Y.Z =` or
# `= Unreleased =`) and the first non-blank line under it, before the next
# heading. Prints "<heading>\t<first line>" and exits 0 when the entry is
# ready, 1 when that first line is `Unreleased.` (or `Unreleased`): the hold
# that keeps the release job from creating a deployment. Exits 2 when the
# readme has no changelog entry at all, which the release job treats as
# ready (its own changelog step then refuses the missing entry).
#
#   release-ready.sh --test
#
# Runs its own tests.
set -euo pipefail

# "<heading>\t<first non-blank line before the next heading>"; the line is
# empty when the entry has nothing under it; nothing at all when there is
# no entry under `== Changelog ==`.
first_entry() {
  awk '
    /^== Changelog ==$/ { c = 1; next }
    c && /^= .* =$/ { if (h) exit; h = 1; heading = $0; next }
    h && NF { out = heading "\t" $0; exit }
    END { if (h) print (out == "" ? heading "\t" : out) }
  ' "$1"
}

ready() {
  local line
  line=$(first_entry "$1")
  [ -n "$line" ] || return 2
  printf '%s\n' "$line"
  case "${line#*	}" in
    Unreleased.|Unreleased) return 1 ;;
  esac
  return 0
}

test_case() {
  local name=$1 expected=$2 body=$3 tmp rc
  tmp=$(mktemp)
  printf '%s\n' "$body" > "$tmp"
  rc=0; ready "$tmp" >/dev/null || rc=$?
  rm -f "$tmp"
  if [ "$rc" -eq "$expected" ]; then echo "ok   $name"; else echo "FAIL $name: exit $rc, expected $expected"; return 1; fi
}

if [ "${1:-}" = "--test" ]; then
  fail=0
  test_case "held: Unreleased. under the version"    1 $'== Changelog ==\n\n= 2.0.0 =\nUnreleased.\n\n* A bullet.\n\n= 1.0.0 =\nFirst.' || fail=1
  test_case "held: no dot"                            1 $'== Changelog ==\n\n= 2.0.0 =\nUnreleased\n\n= 1.0.0 =\nFirst.' || fail=1
  test_case "held: under = Unreleased = heading"      1 $'== Changelog ==\n\n= Unreleased =\nUnreleased.\n* A bullet.' || fail=1
  test_case "ready: notes written"                    0 $'== Changelog ==\n\n= 2.0.0 =\n\n* A bullet.\n* Another.\n\n= 1.0.0 =\nFirst.' || fail=1
  test_case "ready: empty newest entry is not held by the previous one" 0 $'== Changelog ==\n\n= 2.0.0 =\n\n= 1.0.0 =\nUnreleased.\nFirst.' || fail=1
  test_case "ready: Unreleased. only in an older entry" 0 $'== Changelog ==\n\n= 2.0.0 =\n* Done.\n\n= 1.0.0 =\nUnreleased.' || fail=1
  test_case "ready: Unreleased. as a bullet is a bullet" 0 $'== Changelog ==\n\n= 2.0.0 =\n* Unreleased.' || fail=1
  test_case "no entry"                                2 $'== Description ==\nNothing here.' || fail=1
  test_case "no changelog section"                    2 $'= 2.0.0 =\nUnreleased.' || fail=1
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

[ $# -eq 1 ] && [ -f "$1" ] || { echo "usage: release-ready.sh <readme.txt> | --test" >&2; exit 64; }
ready "$1"
