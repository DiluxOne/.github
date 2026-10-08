#!/usr/bin/env bash
# The plugins a plugin requires (its `Requires Plugins` header) that
# wordpress.org does not have yet, provided from the organisation's own
# repositories for Plugin Check (plugin-checks-wp.yml, `requires-plugins-from`).
#
# Plugin Check's action installs every required plugin with
# `wp plugin install --activate <slug>`, which asks wordpress.org first and
# fails with "Plugin not found" for one it does not list, even when it is
# already installed. So the required plugin is mounted beside the one being
# checked and a must-use plugin answers wordpress.org's question for those
# slugs alone: WP-CLI finds them installed and activates them.
#
#   required-plugins.sh repos         The repositories, comma-separated (for
#                                     the token that reads them).
#   required-plugins.sh fetch <dir>   Clone each one at its ref and copy its
#                                     shipped tree (its .distignore) to
#                                     <dir>/<slug>; the must-use plugin goes
#                                     to <dir>/mu-plugins.
#   required-plugins.sh wp-env <dir>  Write ./.wp-env.override.json, which
#                                     wp-env merges into the action's
#                                     .wp-env.json: each <dir>/<slug> as
#                                     wp-content/plugins/<slug>, and
#                                     <dir>/mu-plugins.
#
# repos and fetch expect REQUIRES (one `<slug>=<owner>/<repo>@<ref>` per line or comma),
# and OWNER (the organisation: no other owner is accepted); fetch also
# GH_TOKEN (contents read on those repositories); GIT_BASE overrides https://github.com for the
# tests. It writes nothing outside <dir>.
#
# `required-plugins.sh --test` checks both against scratch repositories.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if [ "${1:-}" = "--test" ]; then
  dir=$(mktemp -d); fail=0
  (
    set -euo pipefail
    mkdir -p "$dir/git/Org" && cd "$dir/git/Org"
    git init -q base-repo && cd base-repo && git config user.email t@t && git config user.name t
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
  if fetch "base=Org/base-repo@--upload-pack=touch"; then echo "FAIL a ref that reads as an option is refused"; fail=1; else echo "ok   a ref that reads as an option is refused"; fi
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
[ -n "$out" ] || { echo "usage: required-plugins.sh repos | fetch|wp-env <dir> | --test" >&2; exit 2; }

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
  wp-env)
    out=$(cd "$out" && pwd)
    mapfile -t slugs < <(find "$out" -mindepth 1 -maxdepth 1 -type d ! -name mu-plugins -printf '%f\n' | sort)
    jq -n --arg dir "$out" '
      { mappings: (
          [ $ARGS.positional[] | { key: "wp-content/plugins/\(.)", value: "\($dir)/\(.)" } ]
          + [ { key: "wp-content/mu-plugins", value: "\($dir)/mu-plugins" } ]
        | from_entries) }' \
      --args "${slugs[@]}" \
      > .wp-env.override.json
    cat .wp-env.override.json
    ;;
  *) echo "usage: required-plugins.sh repos | fetch|wp-env <dir> | --test" >&2; exit 2 ;;
esac
