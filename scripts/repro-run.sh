#!/usr/bin/env bash
# Runs ONE reproduction test of a way that is a command (#352): a browser
# test on wp-env, a command's output, an API. issue-repro.yml's run job, on
# a GitHub runner with no secret and a read-only token. The test was written
# from an outsider's report, so it is untrusted code:
#   1. the way's `setup` runs first, with the network, before the test is in
#      the tree (installing the repository's own tools, starting its site),
#      and then `theme`, when the report named one (a slug, nothing else);
#   2. the test is copied into place and the network is cut for it: the
#      command runs with no environment (none of the runner's variables, its
#      tokens among them) as a user of its own, `dxrepro`, with no sudo, who
#      can read the checkout and write only build/, and whose packets reach
#      only this machine (loopback and Docker's own networks); the site's
#      containers reach nothing outside either (DOCKER-USER). The runner's
#      own user could sudo its way around all of that, so it never runs the
#      test;
#   3. the verdict is the way's JUnit report (scripts/repro-ways.py verdict):
#      outcome=reproduced|passed|broken, or `limit` when setup failed, the
#      repository's own test setup (or its teardown, when the test reached
#      no verdict) failed around the test, or setup and run took longer than
#      the way's `minutes`: the environment, not the bug, so no verdict (its
#      reason in DIR/reason.txt). The test is handed the site's addresses
#      (WP_BASE_URL, WP_NETWORK_URL, WP_ENV_PORT, WP_ENV_TESTS_PORT) only
#      when they are set, so the repository's configuration keeps its own
#      defaults otherwise.
# The command's last lines are kept in DIR/output-tail.txt (untrusted text).
#
#   repro-run.sh run SRC DIR   SPEC (the way, JSON from repro-ways.py
#                              resolve), TEST (where the test goes), THEME
#   repro-run.sh run-ref REF PATH [DIR]
#                              the test at PATH as committed at REF, run the
#                              same way against a clean copy of REF's tree
#                              (git archive: no uncommitted change, no .git,
#                              the test taken out until setup is done), with
#                              the working tree's vendor/ when REF has none
#                              (installed by the caller, as the run job of
#                              issue-repro.yml does); SPEC or REPRO_SPEC,
#                              THEME or REPRO_THEME. The bugfix-reproduced
#                              lane (#397): the autopilot against its fix,
#                              and gate G7 at the pull request's head
#                              (auto-merge.yml), as repro-sandbox.sh run-ref
#                              does for a unit test
#   repro-run.sh --test        self-test (no network change, no Docker)
#
# It refuses a self-hosted runner, as scripts/repro-sandbox.sh does.
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

say() {
  echo "outcome=$1"
  if [ -n "${GITHUB_OUTPUT:-}" ]; then echo "outcome=$1" >> "$GITHUB_OUTPUT"; fi
}

# The dxrepro user: no sudo, the checkout and the browsers readable (every
# folder above them traversable), build/ writable, and its packets to this
# machine only. The runner keeps its own network (it reports the job), and
# so does everything else on it.
isolate() {
  local uid p
  id dxrepro >/dev/null 2>&1 || sudo useradd --create-home --shell /bin/bash dxrepro
  uid=$(id -u dxrepro)
  for p in "$PWD" "$PLAYWRIGHT_BROWSERS_PATH"; do
    while [ "$p" != / ]; do sudo chmod o+x "$p"; p=$(dirname "$p"); done
  done
  chmod -R o+rX . "$PLAYWRIGHT_BROWSERS_PATH" 2>/dev/null || true
  sudo iptables -I OUTPUT 1 -m owner --uid-owner "$uid" -j REJECT
  sudo iptables -I OUTPUT 1 -m owner --uid-owner "$uid" -d 172.16.0.0/12 -j ACCEPT
  sudo iptables -I OUTPUT 1 -m owner --uid-owner "$uid" -o lo -j ACCEPT
  sudo ip6tables -I OUTPUT 1 -m owner --uid-owner "$uid" -j REJECT 2>/dev/null || true
  sudo ip6tables -I OUTPUT 1 -m owner --uid-owner "$uid" -o lo -j ACCEPT 2>/dev/null || true
  # The site's containers: their own networks and nothing else.
  if sudo iptables -L DOCKER-USER -n >/dev/null 2>&1; then
    sudo iptables -I DOCKER-USER 1 -i br-+ ! -d 172.16.0.0/12 -j REJECT
    sudo iptables -I DOCKER-USER 1 -i docker0 ! -d 172.16.0.0/12 -j REJECT
  fi
}

# What a test may see of this environment: the site's addresses, and only
# when they are set. An empty WP_BASE_URL is not unset to a configuration
# that reads `process.env.WP_BASE_URL ?? 'http://localhost:8892'`: it would
# take the empty one, and every page.goto would fail.
passed_env() {
  local v
  for v in WP_BASE_URL WP_NETWORK_URL WP_ENV_PORT WP_ENV_TESTS_PORT; do
    [ -z "${!v:-}" ] || printf '%s=%s\n' "$v" "${!v}"
  done
}

# Run CMD as dxrepro with no environment but what a test needs.
confined() {
  local cmd=$1 secs=$2 extra=()
  mapfile -t extra < <(passed_env)
  if [ "${DX_REPRO_UNCONFINED:-}" = 1 ]; then
    timeout "$secs" env -i PATH="$PATH" HOME="${HOME:-/tmp}" CI=1 "${extra[@]}" bash -c "$cmd"; return
  fi
  sudo -u dxrepro timeout "$secs" env -i PATH="$PATH" HOME=/home/dxrepro CI=1 \
    PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" "${extra[@]}" \
    bash -c "cd $(printf '%q' "$PWD") && $cmd"
}

run() {
  local src=$1 dir=$2 spec=${SPEC:?} test=${TEST:?} theme=${THEME:-} minutes deadline left rc=0 cmd junit v case
  mkdir -p "$dir"
  : > "$dir/output-tail.txt"
  if [ "${RUNNER_ENVIRONMENT:-}" = self-hosted ]; then
    echo "::error::A reproduction test runs on GitHub's runners only, not on a self-hosted one." >&2; return 2
  fi
  case "$test" in /* | *..* | "") echo "::error::Not a test path: $test" >&2; return 2 ;; esac
  [ -f "$src" ] || { echo "::error::No test at $src" >&2; return 2; }
  minutes=$(jq -r '.minutes // 15' <<<"$spec")
  deadline=$(( $(date +%s) + minutes * 60 ))
  remaining() { left=$(( deadline - $(date +%s) )); [ "$left" -gt 0 ] || left=1; }
  limit() { printf '%s\n' "$1" > "$dir/reason.txt"; echo "$1"; say limit; }

  # Shared with the confined user: Playwright's browsers outside $HOME.
  export PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH:-${RUNNER_TEMP:-/tmp}/dx-browsers}
  mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"

  # 1. Setup, with the network, before the test is anywhere near.
  while IFS= read -r cmd; do
    [ -n "$cmd" ] || continue
    remaining
    echo "::group::$cmd"
    rc=0; timeout "$left" bash -c "$cmd" > "$dir/setup.log" 2>&1 || rc=$?
    if [ "$rc" -ne 0 ]; then
      tail -n 40 "$dir/setup.log" | tee -a "$dir/output-tail.txt"
      echo "::endgroup::"
      if [ "$rc" -eq 124 ]; then limit "Setting up took longer than the way's $minutes minutes ($cmd)."
      else limit "Setting up the way failed ($cmd, exit $rc): the repository's environment, not the report."; fi
      return 0
    fi
    tail -n 5 "$dir/setup.log"
    echo "::endgroup::"
  done < <(jq -r '(.setup // []) | if type == "array" then .[] else . end' <<<"$spec")
  if [ -n "$theme" ]; then
    if [[ "$theme" =~ ^[a-z0-9][a-z0-9-]{0,60}$ ]] && cmd=$(jq -r '.theme // empty' <<<"$spec") && [ -n "$cmd" ]; then
      remaining
      timeout "$left" bash -c "${cmd//\{theme\}/$theme}" > "$dir/setup.log" 2>&1 \
        || { tail -n 20 "$dir/setup.log" >> "$dir/output-tail.txt"; limit "The theme the report names ($theme) could not be installed."; return 0; }
    else
      echo "::warning::Not a theme slug, or no way to install one: $theme"
    fi
  fi

  # 2. The test, in place; the network cut for it.
  mkdir -p "$(dirname "$test")"
  cp "$src" "$test"
  junit=$(jq -r '.junit' <<<"$spec")
  rm -f "$junit"
  mkdir -p build "$(dirname "$junit")"
  chmod -R a+rwX build "$(dirname "$junit")"
  [ "${DX_REPRO_UNCONFINED:-}" = 1 ] || isolate
  remaining
  cmd=$(jq -r '.run' <<<"$spec")
  set +e
  confined "$cmd" "$left" > "$dir/run.log" 2>&1
  rc=$?
  set -e
  tail -c 6000 "$dir/run.log" >> "$dir/output-tail.txt"
  tail -n 60 "$dir/run.log"

  # 3. The verdict.
  # The repository's own setup or teardown failing around the test is the
  # environment, not a test written wrong: no verdict, said as such.
  if [ "$rc" -eq 124 ]; then
    limit "The test took longer than the way's $minutes minutes, setup included."
  else
    # What the report names the test by: the way's `case`, else its file.
    case=$(jq -r '.case // empty' <<<"$spec"); [ -n "$case" ] || case=$(basename "$test")
    v=$(python3 "$HERE/repro-ways.py" verdict "$junit" "$case" "$(jq -r '.assertion // empty' <<<"$spec")")
    if [ "$v" = environment ]; then
      limit "The repository's own test setup failed around the test (its setup or teardown project, before or after it): the environment, not the test or the report."
    else
      say "$v"
    fi
  fi
  cmd=$(jq -r '.teardown // empty' <<<"$spec")
  [ -z "$cmd" ] || timeout 120 bash -c "$cmd" >/dev/null 2>&1 || true
}

# The test at PATH as committed at REF, run against REF's own tree, never
# the working tree (#397).
run_ref() {
  local ref=$1 path=$2 dir=${3:-} tmp tree rc=0 work=$PWD
  case "$path" in /* | *..* | "") echo "::error::Not a test path: $path" >&2; return 2 ;; esac
  export SPEC=${SPEC:-${REPRO_SPEC:-}} THEME=${THEME:-${REPRO_THEME:-}}
  [ -n "$SPEC" ] || { echo "::error::No way to run it: SPEC (or REPRO_SPEC) is empty." >&2; return 2; }
  if [ "$(jq -r '.test // empty' <<<"$SPEC")" != "$path" ]; then echo "::error::$path is not the way's test." >&2; return 2; fi
  tmp=$(mktemp "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/repro-test.XXXXXX")
  tree=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/repro-tree.XXXXXX")
  [ -n "$dir" ] || dir="$tree.out"
  git show "$ref:$path" > "$tmp"
  git archive --format=tar "$ref" | tar -x -C "$tree"
  # Out of the tree until the way's setup is done, as in the reproduction.
  rm -f "$tree/$path"
  if [ -d "$work/vendor" ] && [ ! -e "$tree/vendor" ]; then cp -a "$work/vendor" "$tree/vendor"; fi
  (cd "$tree" && TEST=$path run "$tmp" "$dir") || rc=$?
  rm -rf "$tmp" "$tree"
  return "$rc"
}

self_test() {
  local d fail=0 got
  d=$(mktemp -d)
  cd "$d"
  printf 'x\n' > src.ts
  t() {
    local name=$1 want=$2 spec=$3
    got=$(DX_REPRO_UNCONFINED=1 SPEC=$spec TEST=tests/e2e/repro/issue-1.spec.ts THEME=${THEME:-} GITHUB_OUTPUT='' run "$d/src.ts" "$d/out" 2>/dev/null | grep '^outcome=' | tail -1)
    if [ "$got" = "outcome=$want" ]; then echo "ok   $name"; else echo "FAIL $name (want $want, got $got)"; fail=1; fi
  }
  pass='<testsuites><testsuite><testcase name="x" classname="issue-1.spec.ts"/></testsuite></testsuites>'
  fails='<testsuites><testsuite><testcase name="x" classname="issue-1.spec.ts"><failure message="expect(a).toBe(b)"/></testcase></testsuite></testsuites>'
  t "C1 a failing assertion reproduces" reproduced "$(jq -nc --arg x "$fails" '{run: ("printf %s " + ($x|@sh) + " > build/j.xml; exit 1"), junit: "build/j.xml", minutes: 1}')"
  gofail='<testsuites><testsuite><testcase name="TestIssue1" classname="example.com/m/repro"><failure message="Failed">issue1_test.go:9: got 1, want 2</failure></testcase></testsuite></testsuites>'
  t "#377 a report that names the test by the way's case (Go's TestIssue1) reproduces" reproduced "$(jq -nc --arg x "$gofail" '{run: ("printf %s " + ($x|@sh) + " > build/j.xml; exit 1"), junit: "build/j.xml", case: "TestIssue1", assertion: "_test\\.go:[0-9]+: ", minutes: 1}')"
  t "#377 without the case, the failure is no test of its own: no verdict (limit)" limit "$(jq -nc --arg x "$gofail" '{run: ("printf %s " + ($x|@sh) + " > build/j.xml; exit 1"), junit: "build/j.xml", minutes: 1}')"
  t "a passing test passes" passed "$(jq -nc --arg x "$pass" '{run: ("printf %s " + ($x|@sh) + " > build/j.xml"), junit: "build/j.xml", minutes: 1}')"
  t "C8 a setup that fails is no verdict (limit)" limit '{"setup":["exit 3"],"run":"true","junit":"build/j.xml","minutes":1}'
  t "C8 a run past the way's minutes is no verdict (limit)" limit '{"run":"sleep 5","junit":"build/j.xml","minutes":0}'
  t "C8 a setup past the way's minutes is no verdict (limit)" limit '{"setup":["sleep 5"],"run":"true","junit":"build/j.xml","minutes":0}'
  if grep -q "longer than" "$d/out/reason.txt"; then echo "ok   C8 its reason names the time"; else echo "FAIL C8 its reason names the time"; fail=1; fi
  t "a run that writes no report is broken" broken '{"run":"true","junit":"build/j.xml","minutes":1}'
  t "the test is in place when the command runs" passed "$(jq -nc --arg x "$pass" '{run: ("test -f tests/e2e/repro/issue-1.spec.ts && printf %s " + ($x|@sh) + " > build/j.xml"), junit: "build/j.xml", minutes: 1}')"
  t "but not while setup runs" limit '{"setup":["test ! -f tests/e2e/repro/issue-1.spec.ts && exit 9"],"run":"true","junit":"build/j.xml","minutes":1}'
  rm -rf tests build
  # #352: an unset address stays unset (an empty one breaks a config that
  # falls back with ??), and a set one reaches the test.
  t "an unset site address is not handed over empty" passed "$(jq -nc --arg x "$pass" '{run: ("[ -z \"${WP_BASE_URL+set}\" ] && printf %s " + ($x|@sh) + " > build/j.xml"), junit: "build/j.xml", minutes: 1}')"
  WP_BASE_URL=http://localhost:8892 t "a set site address reaches the test" passed "$(jq -nc --arg x "$pass" '{run: ("[ \"$WP_BASE_URL\" = http://localhost:8892 ] && printf %s " + ($x|@sh) + " > build/j.xml"), junit: "build/j.xml", minutes: 1}')"
  t "C8 the repository's setup failing around the test is the environment (limit)" limit "$(jq -nc '{run: "printf %s \"<testsuites><testsuite><testcase name=\\\"s\\\" classname=\\\"global.setup.ts\\\"><failure message=\\\"page.goto: Invalid URL\\\"/></testcase></testsuite></testsuites>\" > build/j.xml; exit 1", junit: "build/j.xml", minutes: 1}')"
  if grep -q "test setup failed" "$d/out/reason.txt"; then echo "ok   C8 and its reason says the environment"; else echo "FAIL C8 and its reason says the environment"; fail=1; fi
  t "the command sees none of the runner's variables" passed "$(jq -nc --arg x "$pass" '{run: ("[ -z \"${GH_TOKEN:-}\" ] && printf %s " + ($x|@sh) + " > build/j.xml"), junit: "build/j.xml", minutes: 1}')"
  THEME='x; rm -rf /' t "a theme that is not a slug is not installed" passed "$(jq -nc --arg x "$pass" '{theme: "exit 7", run: ("printf %s " + ($x|@sh) + " > build/j.xml"), junit: "build/j.xml", minutes: 1}')"
  THEME=astra t "a theme that cannot be installed is no verdict" limit "$(jq -nc --arg x "$pass" '{theme: "exit 7", run: ("printf %s " + ($x|@sh) + " > build/j.xml"), junit: "build/j.xml", minutes: 1}')"
  # #397 run-ref: the test as committed at REF, against REF's own tree.
  local repo="$d/repo" spec_ref
  mkdir -p "$repo/src" "$repo/tests/repro" && cd "$repo"
  git init -q . && printf 'committed\n' > src/code.txt && printf 'x\n' > tests/repro/issue-1.spec.ts
  git add -A && git -c commit.gpgsign=false -c core.hooksPath=/dev/null -c user.name=t -c user.email=t@t commit -qm "test: base"
  printf 'uncommitted\n' > src/code.txt
  spec_ref=$(jq -nc --arg x "$pass" '{setup: ["test ! -e tests/repro/issue-1.spec.ts && test ! -e .git"], run: ("grep -qx committed src/code.txt && test -f tests/repro/issue-1.spec.ts && printf %s " + ($x|@sh) + " > build/j.xml"), junit: "build/j.xml", minutes: 1, test: "tests/repro/issue-1.spec.ts"}')
  got=$(DX_REPRO_UNCONFINED=1 REPRO_SPEC=$spec_ref GITHUB_OUTPUT='' run_ref HEAD tests/repro/issue-1.spec.ts 2>/dev/null | grep '^outcome=' | tail -1)
  if [ "$got" = "outcome=passed" ]; then echo "ok   #397 run-ref runs the committed test against REF's tree, out of it during setup, no .git"; else echo "FAIL #397 run-ref ($got)"; fail=1; fi
  got=$(DX_REPRO_UNCONFINED=1 SPEC=$(jq -c '.run = ("grep -qx uncommitted src/code.txt; exit 1")' <<<"$spec_ref") GITHUB_OUTPUT='' run_ref HEAD tests/repro/issue-1.spec.ts 2>/dev/null | grep '^outcome=' | tail -1)
  if [ "$got" = "outcome=broken" ]; then echo "ok   #397 run-ref never sees the working tree's uncommitted change"; else echo "FAIL #397 run-ref saw the working tree ($got)"; fail=1; fi
  if (DX_REPRO_UNCONFINED=1 SPEC=$spec_ref run_ref HEAD tests/repro/other.spec.ts >/dev/null 2>&1); then echo "FAIL #397 run-ref refuses a test that is not the way's"; fail=1; else echo "ok   #397 run-ref refuses a test that is not the way's"; fi
  if (DX_REPRO_UNCONFINED=1 SPEC= REPRO_SPEC= run_ref HEAD tests/repro/issue-1.spec.ts >/dev/null 2>&1); then echo "FAIL #397 run-ref refuses to run with no way"; fail=1; else echo "ok   #397 run-ref refuses to run with no way"; fi
  if (DX_REPRO_UNCONFINED=1 SPEC=$spec_ref run_ref HEAD ../x >/dev/null 2>&1); then echo "FAIL #397 run-ref refuses a path outside the tree"; fail=1; else echo "ok   #397 run-ref refuses a path outside the tree"; fi
  cd "$d"
  if (DX_REPRO_UNCONFINED=1 SPEC='{}' TEST=../x run "$d/src.ts" "$d/out" >/dev/null 2>&1); then echo "FAIL a path outside the checkout is refused"; fail=1; else echo "ok   a path outside the checkout is refused"; fi
  if (RUNNER_ENVIRONMENT=self-hosted DX_REPRO_UNCONFINED=1 SPEC='{}' TEST=a/b run "$d/src.ts" "$d/out" >/dev/null 2>&1); then echo "FAIL a self-hosted runner is refused"; fail=1; else echo "ok   a self-hosted runner is refused"; fi
  cd / && rm -rf "$d"
  if [ "$fail" -eq 0 ]; then echo "all tests passed"; else return 1; fi
}

case "${1:-}" in
  run) shift; run "$@" ;;
  run-ref) shift; run_ref "$@" ;;
  --test) GH_TOKEN=secret self_test ;;
  *) echo "usage: repro-run.sh run SRC DIR | run-ref REF PATH [DIR] | --test" >&2; exit 2 ;;
esac
