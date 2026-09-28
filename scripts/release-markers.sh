#!/usr/bin/env bash
# The version a plugin's files say, against the version that was released.
#
# The three markers (the `Version:` header of the main file, its PHP
# constant, `Stable tag:` in readme.txt) always name a real version on the
# default branch: the last one released, or, from the moment the pull
# request that releases the next one merges, that next one. The release
# pull request (the one that removes the `Unreleased.` line) sets them; no
# other pull request touches them.
#
#   release-markers.sh check <dir> <main-file> <constant> <last> <next> <pending>
#
# <last> is the last X.Y.Z released, <next> the version the labels give and
# <pending> whether anything asks for it (true/false), all three from
# scripts/next-version.py. The markers must equal <next> when something is
# pending and the readme is ready (a release pull request, or main after it
# merged and before the release job ran), and <last> otherwise. When <next>
# is the target the newest changelog entry must be headed `= <next> =`.
# With no release yet (<last> is 0.0.0) there is nothing to compare with and
# the check passes. Prints what it compared; exits 1 on a mismatch, with an
# error annotation saying what to set.
#
#   release-markers.sh prepare <dir> <version> <main-file> [<constant>]
#
# Turns a tree into its release pull request: removes the `Unreleased.` line
# of the newest changelog entry, then stamps the three markers and a
# `= Unreleased =` heading to <version> (scripts/stamp-version.sh). Refuses a
# readme that is not held (nothing to release) and fails when the result is
# not ready.
#
#   release-markers.sh --test
#
# Runs its own tests.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

marker() { # <dir> <main-file> <constant> <which>
  case "$4" in
    version)  grep -oP '^\s*\*\s*Version:\s*\K\S+' "$1/$2" || true ;;
    stable)   grep -oP '^Stable tag:\s*\K\S+' "$1/readme.txt" || true ;;
    constant) [ -n "$3" ] && { grep -oP "^define\(\s*'${3}',\s*'\K[^']+" "$1/$2" || true; } ;;
  esac
}

check() {
  local dir=$1 main=$2 constant=$3 last=$4 next=$5 pending=$6 held=false rc heading expected why fail=0 v
  if [ "$last" = "0.0.0" ]; then
    echo "No release yet: the markers have nothing to match."
    return 0
  fi
  rc=0; heading=$(bash "$here/release-ready.sh" "$dir/readme.txt") || rc=$?
  case "$rc" in 0|2) ;; 1) held=true ;; *) echo "::error::release-ready.sh failed ($rc)." >&2; return 1 ;; esac
  heading=${heading%%	*}
  if [ "$pending" = true ] && [ "$held" = false ]; then
    expected=$next; why="this releases $next (the readme is ready and the labels give $next)"
  else
    expected=$last; why="$last is the last release and nothing is being released"
  fi
  for which in version stable constant; do
    [ "$which" = constant ] && [ -z "$constant" ] && continue
    v=$(marker "$dir" "$main" "$constant" "$which")
    if [ "$v" != "$expected" ]; then
      case "$which" in
        version)  echo "::error file=$main::The Version header says '${v:-nothing}' but $why: it must say $expected." >&2 ;;
        stable)   echo "::error file=readme.txt::Stable tag says '${v:-nothing}' but $why: it must say $expected." >&2 ;;
        constant) echo "::error file=$main::$constant says '${v:-nothing}' but $why: it must say $expected." >&2 ;;
      esac
      fail=1
    fi
  done
  if [ "$expected" = "$next" ] && [ "$next" != "$last" ] && [ "$heading" != "= $next =" ]; then
    echo "::error file=readme.txt::The newest changelog entry is headed '${heading:-nothing}' but this releases $next: head it '= $next ='." >&2
    fail=1
  fi
  if [ "$fail" -ne 0 ]; then
    if [ "$expected" = "$next" ]; then
      echo "The release pull request sets them: scripts/release-markers.sh prepare <dir> $next <main-file> [<constant>], from a checkout of DiluxOne/.github." >&2
    else
      echo "Set the three markers to $expected in a pull request of their own: main records the version it was released as." >&2
    fi
    return 1
  fi
  echo "Markers OK: $expected ($why)."
}

prepare() {
  local dir=$1 version=$2 main=$3 constant=${4:-} rc=0
  [ -f "$dir/readme.txt" ] || { echo "::error::$dir/readme.txt does not exist." >&2; return 1; }
  sed -i 's/\r$//' "$dir/readme.txt"
  bash "$here/release-ready.sh" "$dir/readme.txt" >/dev/null || rc=$?
  [ "$rc" -eq 1 ] || { echo "::error file=readme.txt::The newest changelog entry does not start with 'Unreleased.': there is no held version to release." >&2; return 1; }
  # The first non-blank line of the newest entry is the hold: it goes, and
  # only it (a bullet that reads "Unreleased." further down stays).
  awk '
    /^== Changelog ==$/ { c = 1; print; next }
    c && !done && /^= .* =$/ { h = 1; print; next }
    h && !done && NF { done = 1; if ($0 ~ /^Unreleased\.?$/) next }
    { print }
  ' "$dir/readme.txt" > "$dir/readme.txt.tmp" && mv "$dir/readme.txt.tmp" "$dir/readme.txt"
  bash "$here/stamp-version.sh" "$dir" "$version" "$main" "$constant"
  rc=0; bash "$here/release-ready.sh" "$dir/readme.txt" >/dev/null || rc=$?
  [ "$rc" -eq 0 ] || { echo "::error file=readme.txt::The readme is still not ready after removing the hold." >&2; return 1; }
  echo "Prepared $version: the hold removed, the markers stamped."
}

if [ "${1:-}" = "--test" ]; then
  fail=0
  t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
  tree() { # <markers> <newest heading> <first line>
    rm -rf "$t/p"; mkdir -p "$t/p"
    printf '<?php\n/**\n * Plugin Name: My Plugin\n * Version: %s\n */\n\ndefine( '"'"'MY_VERSION'"'"', '"'"'%s'"'"' );\n' "$1" "$1" > "$t/p/my-plugin.php"
    printf '=== My Plugin ===\nStable tag: %s\n\n== Changelog ==\n\n= %s =\n%s\n\n* A bullet.\n\n= 1.0.0 =\nFirst.\n' "$1" "$2" "$3" > "$t/p/readme.txt"
  }
  ok()   { if "${@:2}" >/dev/null 2>&1; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
  fails() { if "${@:2}" >/dev/null 2>&1; then echo "FAIL $1"; fail=1; else echo "ok   $1"; fi; }
  # shellcheck disable=SC2329 # called through ok/fails
  c() { check "$t/p" my-plugin.php MY_VERSION "$@"; }

  tree 2.0.0 2.1.0 "Unreleased."
  ok    "held, markers at the last release"             c 2.0.0 2.1.0 true
  ok    "held, nothing pending"                          c 2.0.0 2.0.1 false
  tree 1.0.0 2.1.0 "Unreleased."
  fails "held, markers behind the last release"          c 2.0.0 2.1.0 true
  tree 2.1.0 2.1.0 "Unreleased."
  fails "held, markers already at the next one"          c 2.0.0 2.1.0 true
  tree 2.1.0 2.1.0 "* Ready."
  ok    "ready and pending: markers at the next one"     c 2.0.0 2.1.0 true
  tree 2.0.0 2.1.0 "* Ready."
  fails "ready and pending: markers left at the last"    c 2.0.0 2.1.0 true
  tree 2.1.0 2.2.0 "* Ready."
  fails "ready and pending: heading is another version"  c 2.0.0 2.1.0 true
  tree 2.0.0 2.0.0 "* Shipped."
  ok    "after the release: markers at it"               c 2.0.0 2.0.1 false
  tree 1.0.0 2.0.0 "* Shipped."
  fails "after the release: markers never moved"         c 2.0.0 2.0.1 false
  tree 2.0.0 2.0.0 "* Shipped."; sed -i "s/'MY_VERSION', '2.0.0'/'MY_VERSION', '1.0.0'/" "$t/p/my-plugin.php"
  fails "the constant alone is behind"                   c 2.0.0 2.0.1 false
  ok    "no constant: only header and Stable tag"        check "$t/p" my-plugin.php "" 2.0.0 2.0.1 false
  tree 0.9.0 1.0.0 "Unreleased."
  ok    "no release yet: nothing to compare"             c 0.0.0 0.1.0 true

  tree 2.0.0 2.1.0 "Unreleased."
  ok    "prepare: a held readme"                         prepare "$t/p" 2.1.0 my-plugin.php MY_VERSION
  ok    "prepare: the hold is gone"                      bash -c "! grep -qx 'Unreleased.' '$t/p/readme.txt'"
  ok    "prepare: the bullet stays"                      grep -qx '\* A bullet.' "$t/p/readme.txt"
  ok    "prepare: the result passes the check"          c 2.0.0 2.1.0 true
  tree 2.0.0 Unreleased "Unreleased."
  ok    "prepare: = Unreleased = heading"                prepare "$t/p" 2.1.0 my-plugin.php MY_VERSION
  ok    "prepare: heading renamed"                       grep -qx '= 2.1.0 =' "$t/p/readme.txt"
  tree 2.0.0 2.1.0 "* Ready."
  fails "prepare: refuses a readme that is not held"     prepare "$t/p" 2.1.0 my-plugin.php MY_VERSION
  tree 2.0.0 2.1.0 "Unreleased."; sed -i 's/$/\r/' "$t/p/readme.txt"
  ok    "prepare: CRLF readme"                           prepare "$t/p" 2.1.0 my-plugin.php MY_VERSION

  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

case "${1:-}" in
  check)   shift; [ $# -eq 6 ] || { echo "usage: release-markers.sh check <dir> <main-file> <constant> <last> <next> <pending>" >&2; exit 64; }; check "$@" ;;
  prepare) shift; [ $# -ge 3 ] || { echo "usage: release-markers.sh prepare <dir> <version> <main-file> [<constant>]" >&2; exit 64; }; prepare "$@" ;;
  *) echo "usage: release-markers.sh check|prepare … | --test" >&2; exit 64 ;;
esac
