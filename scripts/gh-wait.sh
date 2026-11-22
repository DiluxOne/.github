#!/usr/bin/env bash
# dx-gh-wait: the marker by which this wrapper finds the real gh, not itself.
#
# gh, waiting on GitHub's API rate limit (#925). The organisation's App has a
# fixed number of calls an hour; on a busy day it runs out, and a run that
# failed on "API rate limit already exceeded for installation ID …" stopped
# its issue or pull request until a person re-ran it. Every job of
# autopilot.yml, claude-review.yml, review-reply.yml and release-lane.yml
# installs this as the `gh` first on its PATH (`--install`), so the bash
# steps and the Python scripts' gh calls all go through it:
#
#   gh-wait.sh <gh's arguments>   runs the real gh (the next `gh` on PATH
#       that is not this wrapper). On GitHub's rate-limit answer (the
#       primary limit: "API rate limit (already) exceeded"; a secondary one:
#       "secondary rate limit", "abuse detection", HTTP 429), it reads
#       `gh api rate_limit` (a call the limit does not count), sleeps until
#       the reset of the exhausted resource plus DX_RATE_SLACK seconds (5),
#       and runs the same command again, its stdin replayed when it reads
#       one (an argument `-`, `…=-` or `…@-`). A secondary limit, or no
#       reset given, backs off DX_RATE_BACKOFF seconds (60), then twice
#       that, and so on. Any other answer is gh's own, at once.
#       The wait is bounded by DX_RATE_DEADLINE (epoch seconds; the job's
#       end less 3 minutes, written by --install; an hour from the first
#       limit when unset): a reset after it is not waited for: it prints
#       `::error::GitHub's API rate limit for the App resets at <time>,
#       after this job's time: left for the next run`, writes the reset
#       (epoch seconds, the latest one) to DX_RATE_NOTE, and exits 1. It
#       calls no API to note it: the limit is spent then. The job reads the
#       note into its outputs, and a later job writes `rate_limited=<reset>`
#       on the issue's board once the reset passed (autopilot.yml
#       `rate-limited`, `--until`), so the hourly sweep continues the issue.
#   gh-wait.sh --until RESET      sleeps until RESET (epoch seconds) plus
#       DX_RATE_SLACK, at most DX_RATE_UNTIL_MAX seconds (4500): the job
#       that writes the board waits there for a fresh limit. A RESET that is
#       not a number is an error.
#   gh-wait.sh --install MINUTES  copies itself to $RUNNER_TEMP/dx-gh/gh
#       (outside the workspace, so a later checkout cannot remove it), puts
#       that directory on $GITHUB_PATH and writes DX_RATE_DEADLINE (now +
#       MINUTES less 3 minutes) and DX_RATE_NOTE ($RUNNER_TEMP/dx-gh/
#       rate-limited) to $GITHUB_ENV.
#   gh-wait.sh --test             its own checks, with a fake gh.
set -uo pipefail

MARK="dx-gh-wait"
SELF="${BASH_SOURCE[0]}"

real_gh() {
  local dir
  local IFS=:
  for dir in $PATH; do
    [ -n "$dir" ] && [ -x "$dir/gh" ] && [ ! -d "$dir/gh" ] || continue
    grep -q "^# $MARK" "$dir/gh" 2>/dev/null && continue
    printf '%s\n' "$dir/gh"
    return 0
  done
  return 1
}

# Whether gh reads its stdin for these arguments.
reads_stdin() {
  local a
  for a in "$@"; do
    case $a in -|*=-|*@-) return 0 ;; esac
  done
  return 1
}

iso() { date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -r "$1" +%Y-%m-%dT%H:%M:%SZ; }

# "primary", "secondary" or nothing, from a failed call's stderr and stdout:
# on stdout only GitHub's own answer counts (its JSON `message`), never an
# issue's text that a failed call happened to print.
limit_of() {
  local err=$1 out=$2
  if grep -qiE 'API rate limit (already )?exceeded' "$err" 2>/dev/null \
    || grep -qiE '"message": *"API rate limit (already )?exceeded' "$out" 2>/dev/null; then echo primary
  elif grep -qiE 'secondary rate limit|abuse detection|HTTP 429|rate limit exceeded' "$err" 2>/dev/null \
    || grep -qiE '"message": *"[^"]*(secondary rate limit|abuse detection)' "$out" 2>/dev/null; then echo secondary
  fi
}

# The latest reset among the exhausted resources, or nothing.
reset_of() {
  "$1" api rate_limit 2>/dev/null | python3 -c '
import json, sys
try:
    res = json.load(sys.stdin).get("resources") or {}
except ValueError:
    sys.exit(0)
out = [int(r.get("reset") or 0) for r in res.values() if isinstance(r, dict) and r.get("remaining") == 0]
if out:
    print(max(out))'
}

give_up() {
  local at=$1 was
  echo "::error::GitHub's API rate limit for the App resets at $(iso "$at"), after this job's time: left for the next run" >&2
  if [ -n "${DX_RATE_NOTE:-}" ]; then
    was=$(cat "$DX_RATE_NOTE" 2>/dev/null || echo 0)
    case $was in ''|*[!0-9]*) was=0 ;; esac
    [ "$was" -ge "$at" ] || echo "$at" > "$DX_RATE_NOTE" 2>/dev/null || true
  fi
  exit 1
}

until_reset() {
  local at=${1:-} now wait max=${DX_RATE_UNTIL_MAX:-4500}
  case $at in ''|*[!0-9]*) echo "gh-wait.sh --until needs the reset, in epoch seconds (got [$at])." >&2; exit 64 ;; esac
  now=$(date +%s)
  wait=$((at - now + ${DX_RATE_SLACK:-5}))
  [ "$wait" -le "$max" ] || wait=$max
  if [ "$wait" -gt 0 ]; then
    echo "GitHub's API rate limit for the App resets at $(iso "$at"): it waits ${wait} s."
    sleep "$wait"
  fi
}

run() {
  local gh rc kind reset wait now deadline tries=0
  gh=$(real_gh) || { echo "gh-wait.sh: no gh on PATH but this wrapper." >&2; exit 127; }
  TMP_DIR=$(mktemp -d)
  trap 'rm -rf "$TMP_DIR"' EXIT
  local tmp=$TMP_DIR
  local feed=/dev/stdin
  if reads_stdin "$@"; then cat > "$tmp/in"; feed="$tmp/in"; fi
  while :; do
    rc=0
    if [ "$feed" = /dev/stdin ]; then "$gh" "$@" > "$tmp/out" 2> "$tmp/err" || rc=$?
    else "$gh" "$@" < "$feed" > "$tmp/out" 2> "$tmp/err" || rc=$?
    fi
    kind=""
    [ "$rc" -eq 0 ] || kind=$(limit_of "$tmp/err" "$tmp/out")
    if [ -z "$kind" ]; then
      cat "$tmp/out"; cat "$tmp/err" >&2
      return "$rc"
    fi
    tries=$((tries + 1))
    now=$(date +%s)
    deadline=${DX_RATE_DEADLINE:-$((now + 3600))}
    reset=""
    [ "$kind" != primary ] || reset=$(reset_of "$gh")
    if [ -n "$reset" ] && [ "$reset" -gt "$now" ]; then
      wait=$((reset - now + ${DX_RATE_SLACK:-5}))
    else
      wait=$(( ${DX_RATE_BACKOFF:-60} * tries ))
      reset=$((now + wait))
    fi
    [ $((now + wait)) -le "$deadline" ] || give_up "$reset"
    echo "gh: GitHub's API rate limit ($kind) is spent: it waits ${wait} s, until $(iso $((now + wait))), and runs \`gh ${1:-} ${2:-}…\` again." >&2
    sleep "$wait"
  done
}

install() {
  local minutes=${1:-} dir
  case $minutes in ''|*[!0-9]*) echo "gh-wait.sh --install needs the job's timeout-minutes." >&2; exit 64 ;; esac
  : "${GITHUB_PATH:?gh-wait.sh --install runs in a job (GITHUB_PATH)}" "${GITHUB_ENV:?}" "${RUNNER_TEMP:?}"
  dir="$RUNNER_TEMP/dx-gh"
  mkdir -p "$dir" && cp "$SELF" "$dir/gh" && chmod 755 "$dir/gh"
  echo "$dir" >> "$GITHUB_PATH"
  {
    echo "DX_RATE_DEADLINE=$(( $(date +%s) + minutes * 60 - 180 ))"
    echo "DX_RATE_NOTE=$dir/rate-limited"
  } >> "$GITHUB_ENV"
  echo "gh waits on the API's rate limit in this job, until $(iso $(( $(date +%s) + minutes * 60 - 180 )))."
}

self_test() {
  local t fails=0 out rc
  TMP_DIR=$(mktemp -d)
  trap 'rm -rf "$TMP_DIR"' EXIT
  t=$TMP_DIR
  mkdir -p "$t/bin"
  cat > "$t/bin/gh" <<'FAKE'
#!/usr/bin/env bash
if [ "$1 $2" = "api rate_limit" ]; then
  echo "{\"resources\": {\"core\": {\"remaining\": 0, \"reset\": $RESET}, \"search\": {\"remaining\": 3, \"reset\": 1}}}"; exit 0
fi
n=$(cat "$T/n" 2>/dev/null || echo 0); echo $((n + 1)) > "$T/n"
in=""; for a in "$@"; do [ "$a" != - ] || in=$(cat); done
echo "$in" >> "$T/stdin"
if [ "$n" -lt "${FAILS:-1}" ]; then echo "gh: $LIMIT (HTTP 403)" >&2; exit 1; fi
echo ok
FAKE
  chmod 755 "$t/bin/gh"
  check() { if [ "$1" = "$2" ]; then echo "ok: $3"; else echo "FAIL: $3 (got [$1], want [$2])"; fails=$((fails + 1)); fi; }
  local base=(env PATH="$t/bin:$PATH" T="$t" DX_RATE_SLACK=0 LIMIT="API rate limit already exceeded for installation ID 1")
  # The reset is one second ahead: it may have passed when the wrapper reads
  # it, and then it backs off instead (#954), one second, not the default 60.
  rc=0; out=$(printf 'body' | "${base[@]}" RESET=$(( $(date +%s) + 1 )) DX_RATE_BACKOFF=1 DX_RATE_DEADLINE=$(( $(date +%s) + 60 )) bash "$SELF" api x --input - 2>/dev/null) || rc=$?
  check "$rc $out $(cat "$t/n")" "0 ok 2" "a primary limit: waits for the reset and runs it again"
  check "$(tr '\n' ' ' < "$t/stdin")" "body body " "its stdin, replayed"
  rm -f "$t/n" "$t/stdin"
  rc=0; out=$("${base[@]}" RESET=$(( $(date +%s) + 900 )) DX_RATE_DEADLINE=$(( $(date +%s) + 10 )) bash "$SELF" pr view 1 2>&1) || rc=$?
  check "$rc $(cat "$t/n")" "1 1" "a reset after the deadline: fails at once"
  case $out in *"::error::GitHub's API rate limit for the App resets at "*", after this job's time: left for the next run"*) check y y "it names the reset" ;; *) check "$out" "the ::error:: line" "it names the reset" ;; esac
  rm -f "$t/n"
  local at=$(( $(date +%s) + 900 ))
  rc=0; "${base[@]}" RESET=$at DX_RATE_DEADLINE=$(( $(date +%s) + 10 )) DX_RATE_NOTE="$t/note" bash "$SELF" pr view 1 >/dev/null 2>&1 || rc=$?
  check "$rc $(cat "$t/n") $(cat "$t/note" 2>/dev/null)" "1 1 $at" "giving up: the reset noted in DX_RATE_NOTE, with no other call"
  rm -f "$t/n"
  rc=0; "${base[@]}" RESET=$((at - 100)) DX_RATE_DEADLINE=$(( $(date +%s) + 10 )) DX_RATE_NOTE="$t/note" bash "$SELF" pr view 1 >/dev/null 2>&1 || rc=$?
  check "$(cat "$t/note")" "$at" "an earlier reset leaves the later one noted"
  rm -f "$t/n"
  rc=0; out=$(DX_RATE_SLACK=0 bash "$SELF" --until $(( $(date +%s) - 10 ))) || rc=$?
  check "$rc $out" "0 " "--until a reset passed: no wait"
  rc=0; out=$(DX_RATE_SLACK=0 DX_RATE_UNTIL_MAX=1 bash "$SELF" --until $(( $(date +%s) + 900 ))) || rc=$?
  case $out in *"it waits 1 s."*) check "$rc" 0 "--until: at most DX_RATE_UNTIL_MAX" ;; *) check "$rc $out" "0 …it waits 1 s." "--until: at most DX_RATE_UNTIL_MAX" ;; esac
  rc=0; bash "$SELF" --until soon >/dev/null 2>&1 || rc=$?
  check "$rc" 64 "--until with no number: an error"
  rc=0; out=$("${base[@]}" RESET=0 DX_RATE_BACKOFF=1 DX_RATE_DEADLINE=$(( $(date +%s) + 60 )) LIMIT="You have exceeded a secondary rate limit" bash "$SELF" issue list 2>/dev/null) || rc=$?
  check "$rc $out" "0 ok" "a secondary limit: backs off and runs it again"
  rm -f "$t/n"
  rc=0; out=$("${base[@]}" RESET=0 FAILS=0 bash "$SELF" issue list 2>/dev/null) || rc=$?
  check "$rc $out $(cat "$t/n")" "0 ok 1" "no limit: one call"
  printf 'title: API rate limit exceeded again\n' > "$t/o"; printf 'gh: Not Found (HTTP 404)\n' > "$t/e"
  check "$(limit_of "$t/e" "$t/o")" "" "an issue's text on stdout is not GitHub's answer"
  printf '{"message": "API rate limit already exceeded for installation ID 1."}\n' > "$t/o"
  check "$(limit_of "$t/e" "$t/o")" "primary" "GitHub's JSON answer on stdout is"
  check "$(PATH="$t/bin:$PATH" real_gh)" "$t/bin/gh" "the real gh is the next one on PATH"
  mkdir -p "$t/wrap" && cp "$SELF" "$t/wrap/gh"
  check "$(PATH="$t/wrap:$t/bin:$PATH" real_gh)" "$t/bin/gh" "never this wrapper"
  rc=0; reads_stdin api x -F "body=@-" || rc=1; check "$rc" 0 "body=@- reads stdin"
  rc=0; reads_stdin pr view 1 || rc=1; check "$rc" 1 "pr view reads none"
  [ "$fails" -eq 0 ] || { echo "$fails failed"; exit 1; }
  echo "gh-wait.sh: all passed"
}

case "${1:-}" in
  --install) shift; install "$@" ;;
  --until) shift; until_reset "$@" ;;
  --test) self_test ;;
  *) run "$@"; exit $? ;;
esac
