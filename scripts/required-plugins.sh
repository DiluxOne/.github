#!/usr/bin/env bash
# The plugins a plugin requires (its `Requires Plugins` header) that
# wordpress.org does not have yet, provided from the organisation's own
# repositories (`requires-plugins-from`): for Plugin Check
# (plugin-checks-wp.yml) and for the wp-env suites (plugin-tests-wp.yml).
#
# Plugin Check's action installs every required plugin with
# `wp plugin install --activate <slug>`, which asks wordpress.org first and
# fails with "Plugin not found" for one it does not list, even when it is
# already installed. So the required plugin is mounted beside the one being
# checked and a must-use plugin answers wordpress.org's question for those
# slugs alone: WP-CLI finds them installed and activates them. The suites
# need no such answer: they mount the plugins, activate them with WP-CLI,
# and keep the repository's own must-use plugins.
#
#   required-plugins.sh repos         The repositories, comma-separated (for
#                                     the token that reads them).
#   required-plugins.sh slugs         The slugs, space-separated, in the
#                                     order given (to activate them).
#   required-plugins.sh fetch <dir>   Clone each one at its ref and copy its
#                                     shipped tree (its .distignore) to
#                                     <dir>/<slug>; the must-use plugin goes
#                                     to <dir>/mu-plugins.
#   required-plugins.sh wp-env <dir>  Merge into ./.wp-env.override.json
#                                     (which wp-env merges into .wp-env.json;
#                                     what it already says is kept) each
#                                     <dir>/<slug> as wp-content/plugins/<slug>,
#                                     and <dir>/mu-plugins (Plugin Check).
#   required-plugins.sh mount <dir>   The same without the must-use plugins
#                                     (the suites).
#
# repos, slugs and fetch expect REQUIRES (one `<slug>=<owner>/<repo>@<ref>` per line or comma),
# and OWNER (the organisation: no other owner is accepted); fetch also
# GH_TOKEN (contents read on those repositories); GIT_BASE overrides https://github.com for the
# tests. fetch writes nothing outside <dir>; wp-env and mount, nothing but
# ./.wp-env.override.json.
#
# `required-plugins.sh --test` checks them against scratch repositories.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if [ "${1:-}" = "--test" ]; then
  dir=$(mktemp -d); fail=0
  (
    set -euo pipefail
    mkdir -p "$dir/git/Org" && cd "$dir/git/Org"
    git init -q base-repo && cd base-repo && git config user.email t@t && git config user.name t && git config commit.gpgsign false
    printf '<?php\n/* Plugin Name: Base */\n' > base.php
    printf 'notes\n' > README.md
    printf 'README.md\n.distignore\n' > .distignore
    git add -A && git commit -q -m "feat: base" && git branch -q -M main
  ) || { echo "FAIL the scratch repository could not be set up"; rm -rf "$dir"; exit 1; }
  fetch() { ( cd "$dir" && rm -rf out && REQUIRES=$1 OWNER=Org GH_TOKEN=t GIT_BASE=file://$dir/git bash "$here/required-plugins.sh" fetch out >/dev/null 2>&1 ); }
  ok() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
  fetch "base=Org/base-repo@main" || { echo "FAIL fetch failed"; fail=1; }
  ok "the shipped tree, under its slug"        '[ -f "$dir/out/base/base.php" ]'
  ok "without what .distignore leaves out"     '[ ! -e "$dir/out/base/README.md" ] && [ ! -e "$dir/out/base/.git" ]'
  ok "the must-use plugin names the slug"      'grep -q "\"base\"" "$dir/out/mu-plugins/dx-required-plugins.php"'
  ok "the must-use plugin parses"              '! command -v php >/dev/null || php -l "$dir/out/mu-plugins/dx-required-plugins.php" >/dev/null'
  sha=$(git -C "$dir/git/Org/base-repo" rev-parse HEAD)
  fetch " base = Org/base-repo@$sha , " || { echo "FAIL fetch failed"; fail=1; }
  ok "a commit, spaces and a trailing comma"   '[ -f "$dir/out/base/base.php" ]'
  if fetch "base=Other/base-repo@main"; then echo "FAIL another owner is refused"; fail=1; else echo "ok   another owner is refused"; fi
  if fetch "Org/base-repo@main"; then echo "FAIL a line without its slug is refused"; fail=1; else echo "ok   a line without its slug is refused"; fi
  if fetch "Base=Org/base-repo@main"; then echo "FAIL a slug that is not one is refused"; fail=1; else echo "ok   a slug that is not one is refused"; fi
  ok "a ref that reads as an option is refused" 'grep -q "is not <slug>=" <(REQUIRES="base=Org/base-repo@-x" OWNER=Org GH_TOKEN=t GIT_BASE=file://$dir/git bash "$here/required-plugins.sh" fetch "$dir/out" 2>&1)'
  if fetch "base=Org/base-repo@no-such-ref"; then echo "FAIL a ref that is not there fails"; fail=1; else echo "ok   a ref that is not there fails"; fi
  if fetch ""; then echo "FAIL nothing to fetch fails"; fail=1; else echo "ok   nothing to fetch fails"; fi
  ok "repos: the names, once, for the token"  '[ "$(REQUIRES="a=Org/one@main
b=Org/two@v1,c=Org/one@x" OWNER=Org bash "$here/required-plugins.sh" repos 2>/dev/null)" = "one,two" ]'
  ok "repos: another owner is refused"         '! REQUIRES="a=Other/one@main" OWNER=Org bash "$here/required-plugins.sh" repos >/dev/null 2>&1'
  fetch "base=Org/base-repo@main" >/dev/null 2>&1 || true
  ( cd "$dir" && bash "$here/required-plugins.sh" wp-env "$dir/out" >/dev/null 2>&1 ) || { echo "FAIL wp-env failed"; fail=1; }
  ok "wp-env: the plugin mounted under its slug" "jq -e --arg d '$dir/out' '.mappings[\"wp-content/plugins/base\"] == (\$d + \"/base\")' '$dir/.wp-env.override.json' >/dev/null"
  ok "wp-env: the must-use plugins mounted"     "jq -e --arg d '$dir/out' '.mappings[\"wp-content/mu-plugins\"] == (\$d + \"/mu-plugins\")' '$dir/.wp-env.override.json' >/dev/null"
  ok "wp-env: nothing else"                     "jq -e '.mappings | length == 2' '$dir/.wp-env.override.json' >/dev/null"
  # The suites (plugin-tests-wp.yml, #148): mounted beside the plugin under
  # test, without the must-use plugins, keeping what the repository's own
  # override already says (C1).
  printf '%s\n' '{"port":8888,"mappings":{"wp-content/mu-plugins/own.php":"./own.php"},"config":{"WP_DEBUG":true}}' > "$dir/.wp-env.override.json"
  ( cd "$dir" && bash "$here/required-plugins.sh" mount "$dir/out" >/dev/null 2>&1 ) || { echo "FAIL mount failed"; fail=1; }
  ok "C1 (#148) mount: the plugin under wp-content/plugins/<slug>" "jq -e --arg d '$dir/out' '.mappings[\"wp-content/plugins/base\"] == (\$d + \"/base\")' '$dir/.wp-env.override.json' >/dev/null"
  ok "C1 (#148) mount: no must-use plugins of its own"   "jq -e '.mappings | has(\"wp-content/mu-plugins\") | not' '$dir/.wp-env.override.json' >/dev/null"
  ok "C1 (#148) mount: the repository's override kept"   "jq -e '.port == 8888 and .config.WP_DEBUG == true and .mappings[\"wp-content/mu-plugins/own.php\"] == \"./own.php\" and (.mappings | length == 2)' '$dir/.wp-env.override.json' >/dev/null"
  ( cd "$dir" && bash "$here/required-plugins.sh" wp-env "$dir/out" >/dev/null 2>&1 ) || { echo "FAIL wp-env over an override failed"; fail=1; }
  ok "wp-env: an existing override kept, the must-use plugins added" "jq -e --arg d '$dir/out' '.port == 8888 and .mappings[\"wp-content/mu-plugins/own.php\"] == \"./own.php\" and .mappings[\"wp-content/mu-plugins\"] == (\$d + \"/mu-plugins\") and (.mappings | length == 3)' '$dir/.wp-env.override.json' >/dev/null"
  ok "C1 (#148) slugs: in the order given, once" '[ "$(REQUIRES="b=Org/two@v1
a=Org/one@main,b=Org/two@v1" OWNER=Org bash "$here/required-plugins.sh" slugs 2>/dev/null)" = "b a" ]'
  ok "C1 (#148) slugs: another owner is refused" '! REQUIRES="a=Other/one@main" OWNER=Org bash "$here/required-plugins.sh" slugs >/dev/null 2>&1'
  # C3 (#148): a repository that cannot be read stops the job, naming it.
  ok "C3 (#148) an unreadable repository fails, naming it" '! out=$(cd "$dir" && REQUIRES="gone=Org/no-such-repo@main" OWNER=Org GH_TOKEN=t GIT_BASE=file://$dir/git bash "$here/required-plugins.sh" fetch "$dir/out3" 2>&1) && grep -q "::error::.*Org/no-such-repo@main" <<<"$out"'
  rm -rf "$dir"
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

# Each `<slug>=<owner>/<repo>@<ref>` of REQUIRES as `slug owner repo ref`;
# anything else, another owner or nothing at all fails.
parse() {
  local line n=0
  while IFS= read -r line; do
    line=$(printf '%s' "$line" | tr -d '[:space:]')
    [ -n "$line" ] || continue
    if ! [[ "$line" =~ ^([a-z0-9][a-z0-9-]*)=([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)@([A-Za-z0-9][A-Za-z0-9._/-]*)$ ]]; then
      echo "::error::requires-plugins-from: \"$line\" is not <slug>=<owner>/<repo>@<ref>." >&2; return 1
    fi
    [ "${BASH_REMATCH[2]}" = "$OWNER" ] || { echo "::error::requires-plugins-from: ${BASH_REMATCH[2]}/${BASH_REMATCH[3]} is not a repository of $OWNER." >&2; return 1; }
    echo "${BASH_REMATCH[1]} ${BASH_REMATCH[2]} ${BASH_REMATCH[3]} ${BASH_REMATCH[4]}"
    n=$((n + 1))
  done < <(printf '%s\n' "${REQUIRES:-}" | tr ',' '\n')
  [ "$n" -gt 0 ] || { echo "::error::requires-plugins-from names no plugin." >&2; return 1; }
}

mode=${1:-}; out=${2:-}
if [ "$mode" = repos ]; then
  # For the token: the repository names, comma-separated.
  list=$(parse) || exit 1
  printf '%s\n' "$list" | awk '{print $3}' | sort -u | paste -sd, -
  exit 0
fi
if [ "$mode" = slugs ]; then
  # For WP-CLI: the slugs, in the order given, each once.
  list=$(parse) || exit 1
  printf '%s\n' "$list" | awk '!seen[$1]++ {print $1}' | paste -sd' ' -
  exit 0
fi
usage="usage: required-plugins.sh repos | slugs | fetch|wp-env|mount <dir> | --test"
[ -n "$out" ] || { echo "$usage" >&2; exit 2; }

case "$mode" in
  fetch)
    base=${GIT_BASE:-https://github.com}
    mkdir -p "$out/mu-plugins"
    slugs=()
    list=$(parse) || exit 1
    while read -r slug owner repo ref; do
      src=$(mktemp -d)
      git -C "$src" init -q
      # The token goes in a header for this fetch alone, never in a URL or a config file.
      auth=$(printf 'x-access-token:%s' "$GH_TOKEN" | base64 -w0)
      echo "::add-mask::$auth"
      git -C "$src" -c "http.extraheader=AUTHORIZATION: basic $auth" fetch -q --depth 1 "$base/$owner/$repo" "$ref" \
        || { echo "::error::requires-plugins-from: $owner/$repo@$ref could not be fetched (does the ref exist, and can dilux-bot read the repository?)." >&2; exit 1; }
      git -C "$src" checkout -q FETCH_HEAD
      mkdir -p "$out/$slug"
      excludes=()
      [ -f "$src/.distignore" ] && excludes=(--exclude-from="$src/.distignore")
      rsync -a --exclude=.git "${excludes[@]}" "$src/" "$out/$slug/"
      rm -rf "$src"
      echo "$slug: $owner/$repo@$ref ($(find "$out/$slug" -type f | wc -l) files)"
      slugs+=("$slug")
    done <<<"$list"
    list=$(printf '"%s",' "${slugs[@]}"); list=${list%,}
    cat > "$out/mu-plugins/dx-required-plugins.php" <<PHP
<?php
/**
 * Plugin Name: Required plugins from the organisation (CI only)
 * Description: Answers wordpress.org's plugin_information for the required plugins this run mounted, so \`wp plugin install --activate\` finds them installed. DiluxOne/.github scripts/required-plugins.sh.
 */

add_filter(
	'plugins_api',
	static function ( \$result, \$action, \$args ) {
		\$slug = isset( \$args->slug ) ? \$args->slug : '';
		if ( 'plugin_information' !== \$action || ! in_array( \$slug, array( $list ), true ) ) {
			return \$result;
		}
		return (object) array(
			'slug'          => \$slug,
			'name'          => \$slug,
			'version'       => '0',
			'download_link' => '',
		);
	},
	10,
	3
);
PHP
    ;;
  wp-env|mount)
    out=$(cd "$out" && pwd)
    mapfile -t slugs < <(find "$out" -mindepth 1 -maxdepth 1 -type d ! -name mu-plugins -printf '%f\n' | sort)
    mu=false; [ "$mode" = wp-env ] && mu=true
    # Merged into the override the repository may already have (its ports,
    # constants and mappings stay); a mapping of the same path is ours.
    existing='{}'
    [ -f .wp-env.override.json ] && existing=$(cat .wp-env.override.json)
    jq -n --arg dir "$out" --argjson mu "$mu" --argjson existing "$existing" '
      $existing * { mappings: (
          [ $ARGS.positional[] | { key: "wp-content/plugins/\(.)", value: "\($dir)/\(.)" } ]
          + (if $mu then [ { key: "wp-content/mu-plugins", value: "\($dir)/mu-plugins" } ] else [] end)
        | from_entries) }' \
      --args "${slugs[@]}" \
      > .wp-env.override.json.new
    mv .wp-env.override.json.new .wp-env.override.json
    cat .wp-env.override.json
    ;;
  *) echo "$usage" >&2; exit 2 ;;
esac
