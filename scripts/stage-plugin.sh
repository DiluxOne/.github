#!/usr/bin/env bash
# The shipped tree of a plugin: what wordpress.org receives.
#
#   stage-plugin.sh <slug> [<src>]
#
# Copies <src> (default: the current directory, the plugin's checkout) to
# <root>/<slug>, where <root> is $STAGE_ROOT, or $RUNNER_TEMP/dist on a
# runner, and prints that path. Left out: what the plugin's .distignore
# lists (when it has one), and what is never the plugin's: .git, .github
# and .dx-central (the organisation's checkout beside it). Nothing else is
# decided here: a `build/` the plugin commits and ships (the bundle
# @wordpress/scripts writes) is staged like any other folder unless the
# .distignore lists it. The tree lands outside the checkout, so nothing the
# workflows write there can end up in it, and it is replaced whole on every
# call. The release (plugin-release-wp.yml) packs its zip by the same rule.
#
#   stage-plugin.sh --test
#
# Runs its own tests, and checks that no workflow stages a plugin inside its
# checkout or leaves out a folder its .distignore does not list (#172).
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

stage() { # <slug> [<src>]
  local slug=${1:?slug} src=${2:-.} root
  root=${STAGE_ROOT:-${RUNNER_TEMP:?RUNNER_TEMP or STAGE_ROOT}/dist}
  case "$slug" in '' | */* | .*) echo "::error::Not a slug: '$slug'." >&2; return 1 ;; esac
  local exclude=()
  [ -f "$src/.distignore" ] && exclude=(--exclude-from="$src/.distignore")
  rm -rf "${root:?}/$slug"
  mkdir -p "$root/$slug"
  rsync -a "${exclude[@]}" --exclude=.git --exclude=.github --exclude=.dx-central "$src/" "$root/$slug/"
  printf '%s\n' "$root/$slug"
}

# The workflows: every rsync that stages a plugin writes outside the
# checkout and leaves out no folder by name beyond what never ships.
lint_workflows() { # <dir>
  local dir=$1 bad=0 line
  while IFS= read -r line; do
    case "$line" in
      *--exclude=build* | *' build/'* | *' "build/'*)
        echo "${line%%:*}: stages into the checkout or drops build/: ${line#*:}"; bad=1 ;;
    esac
  done < <(grep -Hn 'rsync ' "$dir"/*.yml || true)
  return "$bad"
}

# shellcheck disable=SC2016,SC2034 # the checks are strings ok() evaluates.
if [ "${1:-}" = --test ]; then
  fail=0
  ok() { # <name> <command>
    if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi
  }
  t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
  plugin() { # <dir> [<distignore lines>]
    mkdir -p "$1/build" "$1/.git" "$1/.github/workflows" "$1/.dx-central/scripts" "$1/tests"
    echo '<?php' > "$1/plugin.php"
    echo '<?php return array();' > "$1/build/index.asset.php"
    echo x > "$1/.git/HEAD"; echo x > "$1/.github/workflows/ci.yml"; echo x > "$1/.dx-central/scripts/a.sh"
    echo '<?php' > "$1/tests/a-test.php"
    if [ $# -gt 1 ]; then printf '%s\n' "${@:2}" > "$1/.distignore"; fi
  }

  # C1: a committed build/ the .distignore does not list ships.
  plugin "$t/c1" tests .distignore
  out=$(cd "$t/c1" && STAGE_ROOT="$t/out1" bash "$here/stage-plugin.sh" slider)
  ok "prints where it staged"                       '[ "$out" = "$t/out1/slider" ]'
  ok "C1: a committed build/ stays"                 '[ -f "$t/out1/slider/build/index.asset.php" ]'
  ok "the plugin's own files stay"                  '[ -f "$t/out1/slider/plugin.php" ]'
  ok ".distignore is honoured"                      '[ ! -e "$t/out1/slider/tests" ] && [ ! -e "$t/out1/slider/.distignore" ]'
  ok "never .git, .github or .dx-central"           '[ ! -e "$t/out1/slider/.git" ] && [ ! -e "$t/out1/slider/.github" ] && [ ! -e "$t/out1/slider/.dx-central" ]'

  # C2: a .distignore that lists build leaves it out.
  plugin "$t/c2" build tests
  STAGE_ROOT="$t/out2" bash "$here/stage-plugin.sh" offload "$t/c2" >/dev/null
  ok "C2: build/ listed in .distignore is left out" '[ ! -e "$t/out2/offload/build" ] && [ -f "$t/out2/offload/plugin.php" ]'

  # No .distignore: everything but what is never the plugin's.
  plugin "$t/c3"
  STAGE_ROOT="$t/out3" bash "$here/stage-plugin.sh" bare "$t/c3" >/dev/null
  ok "without a .distignore, all of it"             '[ -f "$t/out3/bare/build/index.asset.php" ] && [ -f "$t/out3/bare/tests/a-test.php" ] && [ ! -e "$t/out3/bare/.git" ]'

  # A second call replaces the tree: nothing stale survives.
  echo x > "$t/out1/slider/stale.php"
  STAGE_ROOT="$t/out1" bash "$here/stage-plugin.sh" slider "$t/c1" >/dev/null
  ok "replaced whole on every call"                 '[ ! -e "$t/out1/slider/stale.php" ] && [ -f "$t/out1/slider/plugin.php" ]'

  # On a runner, under $RUNNER_TEMP/dist.
  out=$(RUNNER_TEMP="$t/tmp" bash "$here/stage-plugin.sh" slider "$t/c1")
  ok "default root is \$RUNNER_TEMP/dist"           '[ "$out" = "$t/tmp/dist/slider" ] && [ -f "$t/tmp/dist/slider/build/index.asset.php" ]'
  ok "refuses a path for a slug"                    '! STAGE_ROOT="$t/out4" bash "$here/stage-plugin.sh" ../x "$t/c1" 2>/dev/null'

  # The lint: catches the old staging, passes the organisation's workflows.
  mkdir -p "$t/wf"
  printf '      - run: rsync -a --exclude-from=.distignore --exclude=build ./ "build/$SLUG/"\n' > "$t/wf/old.yml"
  ok "the lint catches staging into build/"         '! lint_workflows "$t/wf" >/dev/null'
  ok "C1/C2/C3: no workflow stages in the checkout" 'lint_workflows "$here/../.github/workflows"'
  # Its calls, not its mentions: syntax, i18n, Plugin Check, review rules
  # and translations each stage with it.
  call='bash .dx-central/scripts/stage-plugin.sh "$SLUG")'
  ok "the five checks stage with this script"       '[ "$(grep -cF "$call" "$here/../.github/workflows/plugin-checks-wp.yml")" -eq 5 ]'
  exit "$fail"
fi

stage "$@"
