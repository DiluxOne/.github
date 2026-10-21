#!/usr/bin/env bash
# The calling organisation's configuration over the engine's (#197): the
# engine is ours, the configuration is theirs (docs/plans/autonomy.md,
# phase 12). Every workflow checks the engine out as .dx-central and its
# scripts read org.yml, repos.yml, labels.yml, policy/ and kinds/ from
# there. When the repository that called the workflow belongs to another
# organisation, this lays that organisation's own `.github` repository over
# those paths, so the scripts read its configuration and the engine's code.
# A path the organisation does not have keeps the engine's default (a kind
# it does not define, a policy file it leaves out); one it has replaces the
# engine's whole. The engine's own organisation is its own configuration:
# nothing is laid over.
#
#   config-overlay.sh [DIR]   DIR the engine's checkout (.dx-central)
#   config-overlay.sh --test  self-test, against local repositories
#
# Environment: GITHUB_REPOSITORY_OWNER (the caller's organisation, set by
# Actions). The configuration repository is read without a token, so it
# must be public (GitHub's own `.github` repositories are). A checkout that
# a skipped step never made (no DIR/org.yml) is left alone. An org.yml laid
# over that does not name the caller's organisation stops the run: the
# configuration would be another organisation's. DX_CONFIG_SOURCE (tests
# only) is a path to clone instead of GitHub's.
set -euo pipefail

# The configuration an organisation holds in its `.github`, nothing else:
# the engine's scripts, workflows and gates are never replaced.
PATHS=(org.yml repos.yml labels.yml policy kinds)

org_of() { sed -n "s/^org:[[:space:]]*[\"']\{0,1\}\([A-Za-z0-9-]*\).*/\1/p" "$1" | head -n 1; }

overlay() {
  local dir=${1:-.dx-central} owner=${GITHUB_REPOSITORY_OWNER:-} engine src tmp
  [ -f "$dir/org.yml" ] || return 0
  engine=$(org_of "$dir/org.yml")
  [ -n "$owner" ] || { echo "::error::GITHUB_REPOSITORY_OWNER is not set: whose configuration to read is unknown."; return 1; }
  if [ "${owner,,}" = "${engine,,}" ]; then
    echo "The engine's own organisation ($engine): its configuration is the engine's."
    return 0
  fi
  src=${DX_CONFIG_SOURCE:-https://github.com/$owner/.github}
  tmp=$(mktemp -d)
  local rc=0
  lay "$dir" "$owner" "$src" "$tmp" || rc=$?
  rm -rf "$tmp"
  return "$rc"
}

# Clones the organisation's configuration into $4/config and lays it over
# the engine's checkout $1 ($2 the organisation, $3 where to clone from).
lay() {
  local dir=$1 owner=$2 src=$3 tmp=$4 p theirs
  if ! git clone -q --depth 1 "$src" "$tmp/config" 2>/dev/null; then
    echo "::error::The engine reads $owner's configuration from $owner/.github, which could not be read without a token: create it, public, with the installer (docs/installing.md)."
    return 1
  fi
  [ -f "$tmp/config/org.yml" ] || { echo "::error::$owner/.github has no org.yml: run the installer (docs/installing.md)."; return 1; }
  theirs=$(org_of "$tmp/config/org.yml")
  [ "${theirs,,}" = "${owner,,}" ] \
    || { echo "::error::$owner/.github's org.yml names '$theirs', not $owner."; return 1; }
  # A link would lay a file of anywhere over the engine's: none is taken.
  for p in "${PATHS[@]}"; do
    if [ -n "$(find "$tmp/config/$p" -type l 2>/dev/null | head -n 1)" ]; then
      echo "::error::$owner/.github's $p holds a symbolic link: the configuration is plain files."
      return 1
    fi
  done
  for p in "${PATHS[@]}"; do
    [ -e "$tmp/config/$p" ] || continue
    if [ -d "$tmp/config/$p" ]; then
      mkdir -p "$dir/$p"
      cp -R "$tmp/config/$p/." "$dir/$p/"
    else
      cp "$tmp/config/$p" "$dir/$p"
    fi
    echo "$owner's $p"
  done
  echo "Configuration: $owner/.github at $(git -C "$tmp/config" rev-parse --short=12 HEAD), over the engine's defaults."
}

self_test() {
  local t fail=0 out
  # The fixtures' commits are local and thrown away: no global config (and
  # no signing key) of whoever runs the test applies to them.
  export GIT_CONFIG_GLOBAL=/dev/null
  t=$(mktemp -d)
  # shellcheck disable=SC2064
  trap "rm -rf '$t'" RETURN
  ok() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: got '$2', want '$3'"; fail=1; fi; }
  engine() {
    rm -rf "$t/e"; mkdir -p "$t/e/policy" "$t/e/kinds/wordpress-plugin" "$t/e/scripts"
    printf 'org: DiluxOne\ncentral: DiluxOne/.github\n' > "$t/e/org.yml"
    echo 'repos: {a: {}}' > "$t/e/repos.yml"
    echo 'budgets-usd: {autopilot-work: 20}' > "$t/e/policy/autonomy.yml"
    echo 'default: 1' > "$t/e/policy/review-policy.default.yml"
    echo 'name: WP' > "$t/e/kinds/wordpress-plugin/pack.yml"
    echo 'engine' > "$t/e/scripts/x.sh"
  }
  config() {
    rm -rf "$t/c"; mkdir -p "$t/c/policy" "$t/c/kinds/web-app" "$t/c/scripts"
    printf 'org: %s\ncentral: %s/.github\n' "$1" "$1" > "$t/c/org.yml"
    echo 'repos: {b: {}}' > "$t/c/repos.yml"
    echo 'budgets-usd: {autopilot-work: 5}' > "$t/c/policy/autonomy.yml"
    echo 'name: Web app' > "$t/c/kinds/web-app/pack.yml"
    echo 'theirs' > "$t/c/scripts/x.sh"
    git -C "$t/c" init -q && git -C "$t/c" add -A && git -C "$t/c" -c user.name=t -c user.email=t@t commit -qm c
  }

  engine
  out=$(GITHUB_REPOSITORY_OWNER=DiluxOne DX_CONFIG_SOURCE=/nonexistent overlay "$t/e")
  ok "the engine's organisation: nothing laid over" "$(cat "$t/e/repos.yml")" 'repos: {a: {}}'
  ok "the engine's organisation: said so" "$(grep -c "its configuration is the engine's" <<<"$out")" 1
  out=$(GITHUB_REPOSITORY_OWNER=diluxone DX_CONFIG_SOURCE=/nonexistent overlay "$t/e")
  ok "the engine's organisation, any case" "$(cat "$t/e/repos.yml")" 'repos: {a: {}}'

  engine; config Acme
  GITHUB_REPOSITORY_OWNER=Acme DX_CONFIG_SOURCE="$t/c" overlay "$t/e" >/dev/null
  ok "another organisation: its org.yml" "$(org_of "$t/e/org.yml")" Acme
  ok "another organisation: its repos.yml" "$(cat "$t/e/repos.yml")" 'repos: {b: {}}'
  ok "another organisation: its policy file replaces the engine's" "$(cat "$t/e/policy/autonomy.yml")" 'budgets-usd: {autopilot-work: 5}'
  ok "a policy file it leaves out keeps the engine's" "$(cat "$t/e/policy/review-policy.default.yml")" 'default: 1'
  ok "its own kind is added" "$(cat "$t/e/kinds/web-app/pack.yml")" 'name: Web app'
  ok "the engine's kinds stay" "$(cat "$t/e/kinds/wordpress-plugin/pack.yml")" 'name: WP'
  ok "never the engine's scripts" "$(cat "$t/e/scripts/x.sh")" engine

  engine; config Other
  if GITHUB_REPOSITORY_OWNER=Acme DX_CONFIG_SOURCE="$t/c" overlay "$t/e" >/dev/null 2>&1; then ok "an org.yml of another organisation stops it" ran stopped; else ok "an org.yml of another organisation stops it" stopped stopped; fi
  ok "and nothing was laid over" "$(cat "$t/e/repos.yml")" 'repos: {a: {}}'

  engine
  if GITHUB_REPOSITORY_OWNER=Acme DX_CONFIG_SOURCE="$t/missing" overlay "$t/e" >/dev/null 2>&1; then ok "no configuration repository stops it" ran stopped; else ok "no configuration repository stops it" stopped stopped; fi

  rm -rf "$t/none"; mkdir -p "$t/none"
  GITHUB_REPOSITORY_OWNER=Acme overlay "$t/none" >/dev/null
  engine; config Acme; mkdir -p "$t/c/kinds/evil"; ln -s /etc/passwd "$t/c/kinds/evil/pack.yml"
  git -C "$t/c" add -A && git -C "$t/c" -c user.name=t -c user.email=t@t commit -qm link
  if GITHUB_REPOSITORY_OWNER=Acme DX_CONFIG_SOURCE="$t/c" overlay "$t/e" >/dev/null 2>&1; then ok "a symbolic link in the configuration stops it" ran stopped; else ok "a symbolic link in the configuration stops it" stopped stopped; fi
  ok "and nothing was laid over" "$(cat "$t/e/repos.yml")" 'repos: {a: {}}'

  engine; config Acme; printf 'org: "Acme"\ncentral: Acme/.github\n' > "$t/c/org.yml"
  git -C "$t/c" add -A && git -C "$t/c" -c user.name=t -c user.email=t@t commit -qm quoted
  GITHUB_REPOSITORY_OWNER=Acme DX_CONFIG_SOURCE="$t/c" overlay "$t/e" >/dev/null
  ok "a quoted org in its org.yml is read" "$(cat "$t/e/repos.yml")" 'repos: {b: {}}'

  ok "a checkout that was never made is left alone" "$(find "$t/none" -mindepth 1 | wc -l)" 0

  # Every full checkout of the engine in the shared workflows is followed by
  # this script, with the checkout's own condition; a sparse one (a single
  # script, no configuration read) is not, since the script is not there.
  out=$(python3 - "$(dirname "${BASH_SOURCE[0]}")/../.github/workflows" <<'PY'
import glob, os, re, sys
bad = []
for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.yml"))):
    lines = open(f, encoding="utf-8").read().split("\n")
    name = os.path.basename(f)
    for p, line in enumerate(lines):
        if re.match(r"^\s*path: \.dx-central$", line):
            ind = len(line) - len(line.lstrip())
            s = p
            while s > 0 and not (re.match(r"^\s*- ", lines[s]) and len(lines[s]) - len(lines[s].lstrip()) < ind):
                s -= 1
            step = len(lines[s]) - len(lines[s].lstrip())
            e = s + 1
            while e < len(lines) and (not lines[e].strip() or len(lines[e]) - len(lines[e].lstrip()) > step):
                e += 1
            block = "\n".join(lines[s:e])
            cond = re.search(r"^\s*(?:- )?if: (.*)$", block, re.M)
            following = "\n".join(lines[e:e + 3])
            follows = "config-overlay.sh" in following
            if "sparse-checkout" in block:
                if follows:
                    bad.append(f"{name}:{p + 1}: a sparse checkout followed by the overlay")
            elif not follows:
                bad.append(f"{name}:{p + 1}: no overlay after the engine's checkout")
            elif cond and "if: " + cond.group(1) not in following:
                bad.append(f"{name}:{p + 1}: the overlay does not carry the checkout's condition")
        # The engine cloned or fetched by git anywhere (.dx-central,
        # $RUNNER_TEMP/central): the overlay on that line or the next.
        if re.search(r"git (-C \S+ )?(clone|fetch)\b.*github\.com/DiluxOne/\.github", line) and not line.rstrip().endswith("\\"):
            if "config-overlay.sh" not in line and "config-overlay.sh" not in lines[p + 1]:
                bad.append(f"{name}:{p + 1}: no overlay after the engine's clone")
        # Its files fetched one by one, configuration among them.
        if "raw.githubusercontent.com/DiluxOne/.github" in line and any(c in "\n".join(lines[p:p + 3]) for c in ("org.yml", "policy/")):
            if "config-overlay.sh" not in "\n".join(lines[p:p + 8]):
                bad.append(f"{name}:{p + 1}: no overlay after the engine's files")
print("\n".join(bad))
PY
)
  ok "every full engine checkout is followed by the overlay" "$out" ""

  [ "$fail" = 0 ] && echo "all tests passed" || echo "some tests failed"
  return "$fail"
}

if [ "${1:-}" = --test ]; then self_test; else overlay "${1:-.dx-central}"; fi
