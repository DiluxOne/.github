#!/usr/bin/env bash
# An installation token of the organisation's App with exactly the
# permissions asked for (#194). actions/create-github-app-token takes one
# input per permission and has none for some (repository_advisories, up to
# v3.3.0): asking for others then leaves those out, and the call that needs
# them reads an empty list instead of failing. This signs the App's JWT with
# openssl (RS256, the App's client ID as issuer), finds the installation on
# the owner and asks GitHub for a token with the permissions given, nothing
# more. The token is masked in the log and printed on stdout.
#
#   app-token.sh mint PERMISSIONS   PERMISSIONS as JSON, e.g.
#                                   '{"repository_advisories":"write"}'
#   app-token.sh --test             self-test, with a key it makes and a
#                                   stand-in for GitHub
#
# Environment: CLIENT_ID, PRIVATE_KEY (PEM), OWNER; REPOSITORIES (optional,
# space-separated names) narrows the token to them. API (optional) is
# GitHub's API URL.
set -euo pipefail

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

jwt() {
  local now header payload key sig
  now=$(date +%s)
  header=$(printf '{"alg":"RS256","typ":"JWT"}' | b64url)
  # 60 seconds back for clock drift, 9 minutes ahead (GitHub allows 10).
  payload=$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' "$((now - 60))" "$((now + 540))" "$CLIENT_ID" | b64url)
  key=$(mktemp); trap 'rm -f "$key"' RETURN
  printf '%s\n' "$PRIVATE_KEY" > "$key"
  sig=$(printf '%s.%s' "$header" "$payload" | openssl dgst -sha256 -sign "$key" -binary | b64url)
  printf '%s.%s.%s' "$header" "$payload" "$sig"
}

api() { # METHOD PATH [BODY]; JWT in $bearer
  local url="${API:-https://api.github.com}$2"
  if [ -n "${3:-}" ]; then
    curl -fsS -X "$1" -H "Authorization: Bearer $bearer" -H "Accept: application/vnd.github+json" -d "$3" "$url"
  else
    curl -fsS -X "$1" -H "Authorization: Bearer $bearer" -H "Accept: application/vnd.github+json" "$url"
  fi
}

mint() {
  local perms=$1 bearer id body token resp missing
  jq -e 'type == "object" and length > 0 and all(.[]; . == "read" or . == "write")' <<<"$perms" >/dev/null \
    || { echo "app-token.sh: the permissions are a JSON object of read or write" >&2; return 1; }
  bearer=$(jwt)
  id=$(api GET "/orgs/$OWNER/installation" | jq -r .id)
  body=$(jq -cn --argjson p "$perms" --arg r "${REPOSITORIES:-}" '{permissions: $p} + (if $r == "" then {} else {repositories: ($r | split(" ") | map(select(. != "")))} end)')
  resp=$(api POST "/app/installations/$id/access_tokens" "$body")
  token=$(jq -r .token <<<"$resp")
  [ -n "$token" ] && [ "$token" != null ] || { echo "app-token.sh: GitHub gave no token" >&2; return 1; }
  # Every permission asked for, at its level: an App that lacks one fails
  # here, loudly, instead of reading an empty list later.
  missing=$(jq -r --argjson want "$perms" '.permissions as $got | $want | to_entries[] | select(($got[.key] // "") as $g | ($g != .value and ($g != "write" or .value != "read"))) | .key' <<<"$resp")
  [ -z "$missing" ] || { echo "app-token.sh: the App's token lacks: $(tr '\n' ' ' <<<"$missing")" >&2; return 1; }
  [ -z "${GITHUB_ACTIONS:-}" ] || echo "::add-mask::$token" >&2
  printf '%s\n' "$token"
}

if [ "${1:-}" = "--test" ]; then
  fail=0
  dir=$(mktemp -d); trap 'rm -rf "$dir"' EXIT
  openssl genrsa -out "$dir/key.pem" 2048 2>/dev/null
  openssl rsa -in "$dir/key.pem" -pubout -out "$dir/pub.pem" 2>/dev/null
  t=$(CLIENT_ID=Iv1.abc PRIVATE_KEY=$(cat "$dir/key.pem") jwt)
  IFS=. read -r h p s <<<"$t"
  unb64() { local x=$1; x=$(tr -- '-_' '+/' <<<"$x"); while [ $(( ${#x} % 4 )) -ne 0 ]; do x+="="; done; openssl base64 -d -A <<<"$x"; }
  if [ "$(unb64 "$h" | jq -r .alg)" = RS256 ] && [ "$(unb64 "$p" | jq -r .iss)" = Iv1.abc ]; then echo "ok   the JWT names RS256 and the client ID"; else echo "FAIL the JWT's header or issuer"; fail=1; fi
  if [ $(( $(unb64 "$p" | jq '.exp - .iat') )) -le 600 ]; then echo "ok   it lives 10 minutes at most"; else echo "FAIL it lives too long"; fail=1; fi
  unb64 "$s" > "$dir/sig"
  if printf '%s.%s' "$h" "$p" | openssl dgst -sha256 -verify "$dir/pub.pem" -signature "$dir/sig" >/dev/null 2>&1; then echo "ok   the signature verifies with the App's public key"; else echo "FAIL the signature does not verify"; fail=1; fi
  # A stand-in for GitHub: what mint asks for.
  curl() { local a; for a in "$@"; do last=$a; done; printf '%s\n' "$*" >> "$dir/calls"
    case "$last" in */installation) echo '{"id":42}';; */access_tokens) echo "{\"token\":\"ghs_x\",\"permissions\":${GRANTED:-{\"repository_advisories\":\"write\",\"contents\":\"write\"\}}}";; esac; }
  got=$(CLIENT_ID=Iv1.abc PRIVATE_KEY=$(cat "$dir/key.pem") OWNER=o REPOSITORIES="a b" mint '{"repository_advisories":"write","contents":"read"}' 2>/dev/null)
  if [ "$got" = ghs_x ] && grep -q '/app/installations/42/access_tokens' "$dir/calls" && grep -q '"repository_advisories":"write"' "$dir/calls" && grep -q '"repositories":\["a","b"\]' "$dir/calls"; then
    echo "ok   mint asks for exactly the permissions and repositories given"; else echo "FAIL mint's request"; cat "$dir/calls"; fail=1; fi
  if (GRANTED='{"contents":"read"}' CLIENT_ID=Iv1.abc PRIVATE_KEY=$(cat "$dir/key.pem") OWNER=o mint '{"repository_advisories":"write","contents":"read"}' >/dev/null 2>&1); then echo "FAIL a token without a permission asked for is refused"; fail=1; else echo "ok   a token without a permission asked for is refused"; fi
  if (CLIENT_ID=x PRIVATE_KEY=x OWNER=o mint '{"contents":"admin"}' >/dev/null 2>&1); then echo "FAIL a level other than read or write is refused"; fail=1; else echo "ok   a level other than read or write is refused"; fi
  if (CLIENT_ID=x PRIVATE_KEY=x OWNER=o mint '{}' >/dev/null 2>&1); then echo "FAIL no permission at all is refused"; fail=1; else echo "ok   no permission at all is refused"; fi
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

case "${1:-}" in
  mint) mint "${2:?the permissions, as JSON}" ;;
  *) sed -n '2,19p' "$0" >&2; exit 64 ;;
esac
