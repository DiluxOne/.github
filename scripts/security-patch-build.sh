#!/usr/bin/env bash
# The tree of a security patch (#247): the version in production, the fix
# on top, and the release of the patch prepared as a release pull request
# would (a held changelog entry, then the kind's `prepare` command). Run in
# a clone of the public repository; security-patch.yml builds it twice, to
# check it when the window opens and to push it when it closes, and both
# times it is the same tree.
#
#   security-patch-build.sh TAG VERSION PATCH NOTE
#     TAG the version in production's tag, VERSION the patch, PATCH the fix
#     (git format-patch), NOTE its changelog line. Leaves the branch
#     security/VERSION checked out with the fix's commits and one release
#     commit; exit 1 when the fix does not apply on TAG.
#   security-patch-build.sh --test
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
BOT="dilux-bot[bot]"
BOT_EMAIL="333187390+dilux-bot[bot]@users.noreply.github.com"

g() { git -c core.hooksPath=/dev/null -c "user.name=$BOT" -c "user.email=$BOT_EMAIL" "$@"; }

build() {
  local tag=$1 version=$2 patch=$3 note=$4 argv
  [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "::error::Not a version: $version" >&2; return 1; }
  g checkout -q -B "security/$version" "refs/tags/$tag" || return 1
  # The release command is read from the production tag's tree, before the
  # fix: what the fix changes never steers it.
  argv=$(ROOT=. VERSION="$version" python3 "$HERE/security-patch.py" release | jq -r '.argv[]') || return 1
  [ -n "$argv" ] || return 1
  if ! g am -q --3way "$patch"; then
    g am --abort >/dev/null 2>&1 || true
    echo "::error::The fix does not apply on $tag." >&2; return 1
  fi
  # Each step stops the build itself: errexit does not hold where a caller
  # tests the build in an `if`.
  README=readme.txt VERSION_TEXT="$note" python3 "$HERE/security-patch.py" entry || return 1
  mapfile -t cmd <<<"$argv"
  "${cmd[@]}" || return 1
  g add -A || return 1
  g commit -q -m "chore(release): $version, a security patch" || return 1
}

self_test() {
  local dir fail=0
  # The fixtures' commits are local and thrown away: no global config (and
  # no signing key) of whoever runs the test applies to them.
  export GIT_CONFIG_GLOBAL=/dev/null
  dir=$(mktemp -d)
  (
    cd "$dir"
    git init -q .
    mkdir -p .github/workflows
    printf 'kind: wordpress-plugin\n' > .github/review-policy.yml
    printf 'jobs:\n  r:\n    uses: DiluxOne/.github/.github/workflows/plugin-release-wp.yml@v5\n    with:\n      slug: x\n' > .github/workflows/release.yml
    git add -A && g commit -q -m init
    git tag 1.0.0
    printf 'a\n' > f.txt && git add f.txt && g commit -q -m "fix: x"
    git format-patch -q -1 --stdout > "$dir/fix.patch"
    g commit -q --allow-empty -m later
  ) >/dev/null 2>&1
  # Without a readme the build stops after applying: enough to see it apply on the tag.
  if (cd "$dir" && build 1.0.0 1.0.1 "$dir/fix.patch" "x" >/dev/null 2>&1); then echo "FAIL a tree with no readme builds"; fail=1; else echo "ok   a tree with no readme does not build"; fi
  if [ "$(cd "$dir" && git rev-parse --abbrev-ref HEAD)" = security/1.0.1 ] && [ -f "$dir/f.txt" ] && [ "$(cd "$dir" && git log -1 --format=%an)" = "$BOT" ]; then
    echo "ok   the fix goes on the tag, on security/VERSION, authored by dilux-bot (dilux-security pushes it)"
  else echo "FAIL the fix on the tag"; fail=1; fi
  if (cd "$dir" && build 1.0.0 nope "$dir/fix.patch" x >/dev/null 2>&1); then echo "FAIL a version that is not one builds"; fail=1; else echo "ok   a version that is not one is refused"; fi
  rm -rf "$dir"
  [ "$fail" = 0 ] && echo "all tests passed"
  return "$fail"
}

case "${1:-}" in
  --test) self_test ;;
  *) [ $# -eq 4 ] || { echo "usage: security-patch-build.sh TAG VERSION PATCH NOTE | --test" >&2; exit 2; }; build "$@" ;;
esac
