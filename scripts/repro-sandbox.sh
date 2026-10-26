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
# but a scratch /tmp and an empty build/ (both discarded with the container),
# no capabilities, 1 GB and 256 processes at most, five minutes alone and
# seven with the rest of tests/Unit (the run job has 15; the suite runs
# whatever the test alone says, its verdict compared only with one that is
# not broken). The checkout's vendor/ must be installed already (by the caller,
# with the repository's own Composer scripts, before the test is anywhere
# near). It refuses to run on a self-hosted runner: such code runs on
# GitHub's fresh runners only (autopilot.yml sends a reproduced bug's work
# there). The scratch folder lives under $RUNNER_TEMP, or TMPDIR elsewhere.
#
#   repro-sandbox.sh run FILE NAME [DIR]  run the test in FILE as NAME
#                                         (IssueNTest.php), then again with
#                                         the rest of tests/Unit; print
#                                         outcome=reproduced|passed|broken
#                                         (also to $GITHUB_OUTPUT when set),
#                                         and keep PHPUnit's last lines in
#                                         DIR/phpunit-tail.txt
#   repro-sandbox.sh run-ref REF PATH     the test at PATH as committed at
#                                         REF (the autopilot: the file is
#                                         never in its working tree), run
#                                         against a clean copy of REF's tree
#                                         (git archive), never the working
#                                         tree, with the working tree's
#                                         vendor/; same output
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

# The same test run with the rest of the unit suite (tests/Unit): its
# verdict stands only if the suite gives the same one, every failure in it
# being the test's own (CLASS). A test that breaks the others (a Brain Monkey
# stub of a function the code defines, declared for the rest of the run, so
# the next test that loads the real file dies with "Cannot redeclare", #259)
# proves nothing: whatever fixes the bug, the suite stays red.
suite_verdict() {
  local rc=$1 out=$2 class=$3 v
  v=$(verdict "$rc" "$out")
  # A whole suite may be green with skipped, incomplete or risky tests
  # ("OK, but ..."): still a pass.
  if [ "$v" = broken ] && [ "$rc" -eq 0 ] && grep -qE '^OK, but ' "$out" && ! grep -qE '^(Errors|ERRORS)|There w(as|ere) [0-9]+ errors?' "$out"; then v=passed; fi
  # Only the entries listed under PHPUnit's failures count; a warning or a
  # deprecation elsewhere in the suite is not the test's doing.
  if [ "$v" = reproduced ] && awk '/^There w(as|ere) [0-9]+ failures?:/{f=1;next} /^There w(as|ere) /||/^FAILURES!/{f=0} f&&/^[0-9]+\) /' "$out" | grep -qv "$class::"; then v=broken; fi
  echo "$v"
}

say() {
  echo "outcome=$1"
  if [ -n "${GITHUB_OUTPUT:-}" ]; then echo "outcome=$1" >> "$GITHUB_OUTPUT"; fi
}

run() {
  local file=$1 name=$2 keep=${3:-} php=${PHP_VERSION:-8.5} scratch rc out
  case "$name" in *[!A-Za-z0-9_.]* | "" | .*) echo "::error::Not a test file name: $name" >&2; return 2 ;; esac
  [ -f "$file" ] || { echo "::error::No test at $file" >&2; return 2; }
  # Code written from an outsider's text runs on GitHub's fresh runners only,
  # never on the organisation's shared VM (its Docker is root there).
  if [ "${RUNNER_ENVIRONMENT:-}" = self-hosted ]; then
    echo "::error::A reproduction test runs on GitHub's runners only, not on a self-hosted one." >&2; return 2
  fi
  # The dev tools: the checkout's own vendor/, or REPRO_VENDOR (run-ref:
  # the working tree's, mounted read-only over the clean copy's).
  local vendor=${REPRO_VENDOR:-$PWD/vendor} tools=()
  if [ ! -f "$vendor/bin/phpunit" ]; then
    echo "::warning::vendor/bin/phpunit is missing: run composer install first."; say broken; return 0
  fi
  if [ -n "${REPRO_VENDOR:-}" ]; then mkdir -p vendor && tools=(-v "$REPRO_VENDOR:/app/vendor:ro"); fi
  scratch=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/repro.XXXXXX")
  mkdir -p "$scratch/test"
  cp "$file" "$scratch/test/$name"
  chmod -R a+rX "$scratch"
  out="$scratch/phpunit.txt"
  # The mount point, so Docker never has to create one inside the
  # read-only checkout. An empty folder: git does not see it.
  mkdir -p tests/Unit/Repro
  # The same for build/, where PHPUnit or a test may write: an empty tmpfs
  # in the container (#443), so nothing written there reaches the checkout.
  mkdir -p build
  # The checkout's .git is hidden behind an empty folder: where a checkout
  # kept its token (the autopilot's), the test never sees it.
  local hide=()
  if [ -d .git ]; then hide=(--tmpfs /app/.git:ro); fi
  docker pull --quiet "php:${php}-cli" >/dev/null
  set +e
  docker run --rm --network none --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
    --user "$(id -u):$(id -g)" --memory 1g --pids-limit 256 \
    -v "$PWD:/app:ro" --tmpfs /app/build "${hide[@]}" "${tools[@]}" -v "$scratch/test:/app/tests/Unit/Repro:ro" -w /app "php:${php}-cli" \
    timeout 300 php vendor/bin/phpunit --no-coverage --do-not-cache-result "tests/Unit/Repro/$name" > "$out" 2>&1
  rc=$?
  set -e
  if [ "$rc" -ge 125 ] && [ "$rc" -le 127 ]; then echo "::warning::The container did not run the test (exit $rc)."; fi
  local v suite="$scratch/suite.txt" src
  v=$(verdict "$rc" "$out")
  if [ -d tests/Unit ]; then
    set +e
    docker run --rm --network none --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
      --user "$(id -u):$(id -g)" --memory 1g --pids-limit 256 \
      -v "$PWD:/app:ro" --tmpfs /app/build "${hide[@]}" "${tools[@]}" -v "$scratch/test:/app/tests/Unit/Repro:ro" -w /app "php:${php}-cli" \
      timeout 420 php vendor/bin/phpunit --no-coverage --do-not-cache-result tests/Unit > "$suite" 2>&1
    src=$?
    set -e
    if [ "$v" != broken ] && [ "$(suite_verdict "$src" "$suite" "${name%.php}")" != "$v" ]; then
      echo "::warning::Alone the test says $v; with the rest of the unit suite it does not (exit $src): it breaks other tests, so it proves nothing."
      { echo "Alone: $v. With the rest of tests/Unit:"; tail -22 "$suite"; } > "$out"
      v=broken
    fi
  fi
  tail -25 "$out"
  if [ -n "$keep" ]; then mkdir -p "$keep" && tail -25 "$out" > "$keep/phpunit-tail.txt"; fi
  say "$v"
  rm -rf "$scratch"
}

# REF's tree, exactly as committed, into DIR: what a verdict "at REF" is
# about, whatever the working tree holds besides (an uncommitted fix, a
# stray change). No .git in it, so no token either.
tree_at() {
  local ref=$1 dir=$2
  mkdir -p "$dir"
  git archive --format=tar "$ref" | tar -x -C "$dir"
}

# The test at PATH as committed at REF, run against REF's own tree (a clean
# copy, never the working tree), with the working tree's vendor/ (installed
# by the caller from the repository's own Composer files).
run_ref() {
  local ref=$1 path=$2 tmp tree rc=0 work=$PWD
  case "$path" in tests/Unit/Repro/*Test.php) ;; *) echo "::error::Not a reproduction test: $path" >&2; return 2 ;; esac
  tmp=$(mktemp "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/repro-test.XXXXXX")
  tree=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/repro-tree.XXXXXX")
  git show "$ref:$path" > "$tmp"
  tree_at "$ref" "$tree"
  chmod -R a+rX "$tree"
  (cd "$tree" && REPRO_VENDOR="$work/vendor" run "$tmp" "$(basename "$path")") || rc=$?
  rm -rf "$tmp" "$tree"
  return "$rc"
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
  # case_suite NAME WANT RC OUTPUT: the run with the rest of tests/Unit (#259).
  case_suite() {
    printf '%s\n' "$4" > "$dir/out"
    got=$(suite_verdict "$3" "$dir/out" Issue12Test)
    if [ "$got" = "$2" ]; then echo "ok   $1"; else echo "FAIL $1: got $got, want $2"; fail=1; fi
  }
  case_suite "the suite failing only on the test is still the bug" reproduced 1 $'There was 1 failure:\n\n1) Tests\\Unit\\Repro\\Issue12Test::test_it\nFailed.\n\nFAILURES!\nTests: 90, Assertions: 200, Failures: 1.'
  case_suite "another test failing beside it is no verdict" broken 1 $'There were 2 failures:\n\n1) Tests\\Unit\\Repro\\Issue12Test::test_it\nFailed.\n\n2) Tests\\Unit\\FieldsTest::test_key\nFailed.\n\nFAILURES!\nTests: 90, Assertions: 200, Failures: 2.'
  case_suite "a redeclared function killing the suite is no verdict" broken 255 $'....\nPHP Fatal error:  Cannot redeclare diluxone_users_posted_fields() in includes/fields.php on line 792'
  case_suite "a warning elsewhere in the suite is not the test's doing" reproduced 1 $'There was 1 warning:\n\n1) Tests\\Unit\\FieldsTest::test_key\nDeprecated.\n\nThere was 1 failure:\n\n1) Tests\\Unit\\Repro\\Issue12Test::test_it\nFailed.\n\nFAILURES!\nTests: 90, Assertions: 200, Failures: 1, Warnings: 1.'
  case_suite "a green suite with skipped tests is a pass" passed 0 $'....S\n\nOK, but incomplete, skipped, or risky tests!\nTests: 90, Assertions: 200, Skipped: 1.'
  case_suite "PHPUnit 10's OK with issues is a pass" passed 0 $'....\n\nOK, but there were issues!\nTests: 90, Assertions: 200, Deprecations: 1.'
  case_suite "a green suite is a pass" passed 0 $'....\n\nOK (90 tests, 200 assertions)'
  # The guards that keep the file where it belongs.
  if (run_ref HEAD "src/evil.php" >/dev/null 2>&1); then echo "FAIL run-ref refuses a path outside tests/Unit/Repro"; fail=1; else echo "ok   run-ref refuses a path outside tests/Unit/Repro"; fi
  if (run "$dir/out" "../x.php" >/dev/null 2>&1); then echo "FAIL run refuses a name with a path in it"; fail=1; else echo "ok   run refuses a name with a path in it"; fi
  if (RUNNER_ENVIRONMENT=self-hosted run "$dir/out" "Issue1Test.php" >/dev/null 2>&1); then echo "FAIL run refuses a self-hosted runner"; fail=1; else echo "ok   run refuses a self-hosted runner"; fi
  # A verdict "at REF" is about REF's tree, not the working tree (PR #166).
  local repo="$dir/repo" copy="$dir/copy"
  mkdir -p "$repo/src" && printf 'committed\n' > "$repo/src/fix.php"
  (cd "$repo" && git init -q . && git add -A && git -c commit.gpgsign=false -c core.hooksPath=/dev/null -c user.name=t -c user.email=t@t commit -qm "test: base") >/dev/null 2>&1 || true
  printf 'uncommitted\n' > "$repo/src/fix.php"; printf 'stray\n' > "$repo/src/stray.php"
  (cd "$repo" && tree_at HEAD "$copy") 2>/dev/null || true
  got="$(cat "$copy/src/fix.php" 2>/dev/null || true)|$([ ! -e "$copy/src/stray.php" ] || echo stray)|$([ ! -e "$copy/.git" ] || echo git)"
  if [ "$got" = "committed||" ]; then echo "ok   run-ref runs against REF's tree: no uncommitted change, no stray file, no .git"; else echo "FAIL run-ref's tree: got $got"; fail=1; fi
  if [ "$( (cd "$copy" && REPRO_VENDOR="$dir/none" run "$dir/out" Issue1Test.php) 2>/dev/null | tail -1)" = "outcome=broken" ]; then echo "ok   run-ref without the working tree's dev tools is no verdict"; else echo "FAIL run-ref without dev tools"; fail=1; fi
  # Both runs get a writable, empty build/ over the read-only checkout, its
  # mount point made outside the container, even when the test alone is
  # broken (#443). A stand-in docker logs its arguments.
  local co="$dir/co" fake="$dir/fakebin" runs
  mkdir -p "$co/vendor/bin" "$co/tests/Unit" "$fake" && : > "$co/vendor/bin/phpunit"
  printf '#!/usr/bin/env bash\n[ "$1" = run ] && printf "%%s\\n" "$*" >> "%s"\nexit 0\n' "$dir/docker.log" > "$fake/docker"
  chmod +x "$fake/docker"
  (cd "$co" && PATH="$fake:$PATH" run "$dir/out" Issue1Test.php) >/dev/null 2>&1 || true
  runs=$(grep -c . "$dir/docker.log" 2>/dev/null || true)
  if [ "$runs" = 2 ] && [ "$(grep -c -- '--tmpfs /app/build ' "$dir/docker.log")" = 2 ] && [ -d "$co/build" ]; then echo "ok   both runs get a writable, empty build/ over the read-only checkout"; else echo "FAIL build/ in the sandbox: $runs runs"; fail=1; fi
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
