#!/usr/bin/env bash
# Runs ONE reproduction test where it can reach nothing, and reads PHPUnit's
# verdict. A reproduction test is written by Claude from an issue's text, so
# it is untrusted code: it runs only here, never with a secret around it.
# Two callers, one sandbox: issue-repro.yml's run job (the verdict on the
# report) and the autopilot in the `bugfix-reproduced` lane (the same test,
# against its fix: it must pass before the pull request is ready).
#
# The sandbox: the stock php:<version>-cli image, no network, no environment
# (none of the runner's variables, its tokens among them), the checkout in
# the current directory mounted read-only, the test mounted read-only as
# tests/Unit/Repro/<name> (the one file in that folder), nothing writable
# but a scratch /tmp, no capabilities, 1 GB and 256 processes at most, ten
# minutes. The checkout's vendor/ must be installed already (by the caller,
# with the repository's own Composer scripts, before the test is anywhere
# near). The scratch folder lives under $RUNNER_TEMP, a path the organisation's
# runners share with the Docker host, so the bind mounts work there too.
#
#   repro-sandbox.sh run FILE NAME [DIR]  run the test in FILE as NAME
#                                         (IssueNTest.php); print
#                                         outcome=reproduced|passed|broken
#                                         (also to $GITHUB_OUTPUT when set),
#                                         and keep PHPUnit's last lines in
#                                         DIR/phpunit-tail.txt
#   repro-sandbox.sh run-ref REF PATH     the test at PATH as committed at
#                                         REF (the autopilot: the file is
#                                         never in its working tree), same
#                                         output
#   repro-sandbox.sh verdict RC FILE      the verdict alone, from PHPUnit's
#                                         exit code and output
#   repro-sandbox.sh --test               self-test (fixtures, no Docker)
#
# Environment: PHP_VERSION (default 8.5).
set -euo pipefail

# Only PHPUnit's own verdicts count: exit 1 with a failure and no error is
# the bug; exit 0 with "OK" is a pass. An error (a wrong class, a missing
# stub), a timeout (124), a kill (137, memory), a PHP fatal (255), Docker
# not running the test at all (125 to 127) or anything else proves nothing.
verdict() {
  local rc=$1 out=$2
  if [ "$rc" -ge 124 ] && [ "$rc" -le 127 ]; then echo broken
  elif grep -qE '^(Errors|ERRORS)|There w(as|ere) [0-9]+ errors?' "$out"; then echo broken
  elif [ "$rc" -eq 1 ] && grep -qE '^FAILURES!' "$out"; then echo reproduced
  elif [ "$rc" -eq 0 ] && grep -qE '^OK \(' "$out"; then echo passed
  else echo broken
  fi
}

say() {
  echo "outcome=$1"
  if [ -n "${GITHUB_OUTPUT:-}" ]; then echo "outcome=$1" >> "$GITHUB_OUTPUT"; fi
}

run() {
  local file=$1 name=$2 keep=${3:-} php=${PHP_VERSION:-8.5} scratch rc out
  case "$name" in *[!A-Za-z0-9_.]* | "" | .*) echo "::error::Not a test file name: $name" >&2; return 2 ;; esac
  [ -f "$file" ] || { echo "::error::No test at $file" >&2; return 2; }
  if [ ! -x vendor/bin/phpunit ] && [ ! -f vendor/bin/phpunit ]; then
    echo "::warning::vendor/bin/phpunit is missing: run composer install first."; say broken; return 0
  fi
  scratch=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/repro.XXXXXX")
  mkdir -p "$scratch/test"
  cp "$file" "$scratch/test/$name"
  chmod -R a+rX "$scratch"
  out="$scratch/phpunit.txt"
  # The mount point, so Docker never has to create one inside the
  # read-only checkout. An empty folder: git does not see it.
  mkdir -p tests/Unit/Repro
  docker pull --quiet "php:${php}-cli" >/dev/null
  set +e
  docker run --rm --network none --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
    --user "$(id -u):$(id -g)" --memory 1g --pids-limit 256 \
    -v "$PWD:/app:ro" -v "$scratch/test:/app/tests/Unit/Repro:ro" -w /app "php:${php}-cli" \
    timeout 600 php vendor/bin/phpunit --no-coverage --do-not-cache-result "tests/Unit/Repro/$name" > "$out" 2>&1
  rc=$?
  set -e
  if [ "$rc" -ge 125 ] && [ "$rc" -le 127 ]; then echo "::warning::The container did not run the test (exit $rc)."; fi
  tail -25 "$out"
  if [ -n "$keep" ]; then mkdir -p "$keep" && tail -25 "$out" > "$keep/phpunit-tail.txt"; fi
  say "$(verdict "$rc" "$out")"
  rm -rf "$scratch"
}

run_ref() {
  local ref=$1 path=$2 tmp
  case "$path" in tests/Unit/Repro/*Test.php) ;; *) echo "::error::Not a reproduction test: $path" >&2; return 2 ;; esac
  tmp=$(mktemp "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/repro-test.XXXXXX")
  git show "$ref:$path" > "$tmp"
  run "$tmp" "$(basename "$path")"
  rm -f "$tmp"
}

self_test() {
  local fail=0 dir got
  dir=$(mktemp -d)
  # case NAME WANT RC OUTPUT
  case_() {
    printf '%s\n' "$4" > "$dir/out"
    got=$(verdict "$3" "$dir/out")
    if [ "$got" = "$2" ]; then echo "ok   $1"; else echo "FAIL $1: got $got, want $2"; fail=1; fi
  }
  case_ "a failing assertion is the bug, reproduced" reproduced 1 $'There was 1 failure:\n\n1) Issue12Test::test_it\nFailed asserting that false is true.\n\nFAILURES!\nTests: 1, Assertions: 1, Failures: 1.'
  case_ "a green run is a pass" passed 0 $'.\n\nTime: 00:00.010\n\nOK (1 test, 1 assertion)'
  case_ "an error is no verdict, even with a failure beside it" broken 1 $'There was 1 error:\n\n1) Error: Class "Nope" not found\n\nThere was 1 failure:\n\nERRORS!\nTests: 2, Errors: 1, Failures: 1.'
  case_ "PHPUnit 9's error summary is no verdict" broken 2 $'There were 2 errors:\n\nERRORS!'
  case_ "a timeout is no verdict" broken 124 'OK (1 test, 1 assertion)'
  case_ "Docker not running it is no verdict" broken 125 'FAILURES!'
  case_ "a kill (memory) is no verdict" broken 137 'FAILURES!'
  case_ "a PHP fatal is no verdict" broken 255 'PHP Parse error: syntax error'
  case_ "exit 1 without PHPUnit's own word is no verdict" broken 1 'Segmentation fault'
  case_ "exit 0 without OK is no verdict" broken 0 'No tests executed!'
  case_ "OK that is not PHPUnit's summary line is no verdict" broken 0 '  OK (printed by the test)'
  # The guards that keep the file where it belongs.
  if (run_ref HEAD "src/evil.php" >/dev/null 2>&1); then echo "FAIL run-ref refuses a path outside tests/Unit/Repro"; fail=1; else echo "ok   run-ref refuses a path outside tests/Unit/Repro"; fi
  if (run "$dir/out" "../x.php" >/dev/null 2>&1); then echo "FAIL run refuses a name with a path in it"; fail=1; else echo "ok   run refuses a name with a path in it"; fi
  rm -rf "$dir"
  [ "$fail" -eq 0 ] && echo "all tests passed"
  return "$fail"
}

case "${1:-}" in
  run) shift; run "$@" ;;
  run-ref) shift; run_ref "$@" ;;
  verdict) shift; verdict "$@" ;;
  --test) self_test ;;
  *) echo "usage: repro-sandbox.sh run FILE NAME [DIR] | run-ref REF PATH | verdict RC FILE | --test" >&2; exit 2 ;;
esac
