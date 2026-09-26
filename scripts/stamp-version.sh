#!/usr/bin/env bash
# Stamp a WordPress plugin tree with a version.
#
#   stamp-version.sh <dir> <version> <main-file> [<constant>] [<build>]
#
# In the copy under <dir>, the `Version:` header of <main-file>, the PHP
# constant <constant> (when given) and `Stable tag:` in readme.txt become
# <version>; a changelog heading `= Unreleased =` becomes `= <version> =`.
# With <build>, a `Build: <build>` header line is added right under
# `Version:` (the tree never has one): a development build records the
# commit it was made from. Every marker is checked afterwards; a marker
# that did not take the version fails the script, so a file whose shape
# changed is caught before anything ships. Nothing outside <dir> is touched.
#
#   stamp-version.sh --test
#
# Runs its own tests.
set -euo pipefail

stamp() {
  local dir=$1 version=$2 main=$3 constant=${4:-} build=${5:-} fail=0
  [ -f "$dir/$main" ] || { echo "::error::$dir/$main does not exist." >&2; return 1; }
  [ -f "$dir/readme.txt" ] || { echo "::error::$dir/readme.txt does not exist." >&2; return 1; }
  if [ -n "$build" ]; then
    sed -i -E "s/^(\s*\*\s*Version:\s*).*$/\1$version\n * Build: $build/" "$dir/$main"
  else
    sed -i -E "s/^(\s*\*\s*Version:\s*).*$/\1$version/" "$dir/$main"
  fi
  if [ -n "$constant" ]; then
    sed -i -E "s/^(define\(\s*'${constant}',\s*').*('\s*\);)$/\1$version\2/" "$dir/$main"
  fi
  sed -i -E "s/^(Stable tag:\s*).*$/\1$version/; s/^= Unreleased =$/= $version =/" "$dir/readme.txt"

  grep -qE "^\s*\*\s*Version:\s*${version//./\\.}$" "$dir/$main" || { echo "::error file=$main::The Version header did not take $version." >&2; fail=1; }
  if [ -n "$build" ]; then
    grep -qE "^\s*\*\s*Build:\s*$build$" "$dir/$main" || { echo "::error file=$main::The Build header did not take $build." >&2; fail=1; }
  fi
  if [ -n "$constant" ]; then
    grep -qE "^define\(\s*'${constant}',\s*'${version//./\\.}'\s*\);" "$dir/$main" || { echo "::error file=$main::$constant did not take $version." >&2; fail=1; }
  fi
  grep -qE "^Stable tag:\s*${version//./\\.}$" "$dir/readme.txt" || { echo "::error file=readme.txt::Stable tag did not take $version." >&2; fail=1; }
  return "$fail"
}

if [ "${1:-}" = "--test" ]; then
  fail=0
  t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
  fresh() {
    rm -rf "$t/p"; mkdir -p "$t/p"
    printf '<?php\n/**\n * Plugin Name: My Plugin\n * Version: 1.0.0\n * Text Domain: my-plugin\n */\n\ndefine( '"'"'MY_PLUGIN_VERSION'"'"', '"'"'1.0.0'"'"' );\n' > "$t/p/my-plugin.php"
    printf '=== My Plugin ===\nStable tag: 1.0.0\n\n== Changelog ==\n\n= %s =\nUnreleased.\n\n* A bullet.\n\n= 1.0.0 =\nFirst.\n' "$1" > "$t/p/readme.txt"
  }
  check() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }

  fresh "2.0.0"; stamp "$t/p" 2.0.0 my-plugin.php MY_PLUGIN_VERSION >/dev/null
  check "release: Version header"      "grep -qx ' \* Version: 2.0.0' '$t/p/my-plugin.php'"
  check "release: constant"            "grep -qxF \"define( 'MY_PLUGIN_VERSION', '2.0.0' );\" '$t/p/my-plugin.php'"
  check "release: Stable tag"          "grep -qx 'Stable tag: 2.0.0' '$t/p/readme.txt'"
  check "release: no Build line"       "! grep -q 'Build:' '$t/p/my-plugin.php'"
  check "release: heading kept"        "grep -qx '= 2.0.0 =' '$t/p/readme.txt'"

  fresh "Unreleased"; stamp "$t/p" 2.0.0 my-plugin.php MY_PLUGIN_VERSION >/dev/null
  check "release: = Unreleased = renamed" "grep -qx '= 2.0.0 =' '$t/p/readme.txt' && ! grep -q '= Unreleased =' '$t/p/readme.txt'"
  check "release: Unreleased. line kept (the hold decides, not the stamp)" "grep -qx 'Unreleased.' '$t/p/readme.txt'"

  fresh "2.0.0"; stamp "$t/p" 2.0.0-dev.8 my-plugin.php MY_PLUGIN_VERSION abc1234 >/dev/null
  check "dev: Version header"          "grep -qx ' \* Version: 2.0.0-dev.8' '$t/p/my-plugin.php'"
  check "dev: Build line under it"     "grep -A1 'Version: 2.0.0-dev.8' '$t/p/my-plugin.php' | grep -qx ' \* Build: abc1234'"
  check "dev: constant"                "grep -qxF \"define( 'MY_PLUGIN_VERSION', '2.0.0-dev.8' );\" '$t/p/my-plugin.php'"
  check "dev: Stable tag"              "grep -qx 'Stable tag: 2.0.0-dev.8' '$t/p/readme.txt'"

  fresh "2.0.0"; stamp "$t/p" 2.0.0 my-plugin.php >/dev/null
  check "no constant: header stamped, constant untouched" "grep -qx ' \* Version: 2.0.0' '$t/p/my-plugin.php' && grep -qF \"'1.0.0'\" '$t/p/my-plugin.php'"

  fresh "2.0.0"; sed -i 's/^ \* Version:.*$/ * Versión: 1.0.0/' "$t/p/my-plugin.php"
  check "a header of another shape fails" "! stamp '$t/p' 2.0.0 my-plugin.php MY_PLUGIN_VERSION 2>/dev/null"
  fresh "2.0.0"
  check "a missing constant fails"     "! stamp '$t/p' 2.0.0 my-plugin.php OTHER_CONSTANT 2>/dev/null"
  fresh "2.0.0"; rm "$t/p/readme.txt"
  check "a missing readme fails"       "! stamp '$t/p' 2.0.0 my-plugin.php 2>/dev/null"

  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

[ $# -ge 3 ] || { echo "usage: stamp-version.sh <dir> <version> <main-file> [<constant>] [<build>] | --test" >&2; exit 64; }
stamp "$@"
