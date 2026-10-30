#!/usr/bin/env bash
# Runs one end-to-end suite of plugin-tests-wp.yml: whole, or only what a
# pull request touches (#352, scripts/repro-ways.py affected).
#
#   e2e-run.sh run     RUN (the suite's command), TARGETED (the plan JSON, or
#                      empty), SITE (single or network), CENTRAL (the
#                      organisation's checkout), LEVEL (empty, or `pr`),
#                      FLAKY_REPORT (where Playwright's JSON report goes, or
#                      empty)
#   e2e-run.sh --test  self-test, with a stand-in for npx
#
# Targeted: the mapped tests through the suite's own command, when that
# command is Playwright's own (`npx playwright test ...`, which takes file
# filters and --pass-with-no-tests, so a suite they are not part of runs
# none), alone: any other command (an npm script, a wrapper, a list of
# commands) runs whole, as the filters could land on the wrong part. The reproduction tests run on the single site, in
# chromium, through the kind's playwright.dx-repro.config.ts.
#
# LEVEL=pr (#479): a pull request in a repository with a merge queue, whose
# group runs every suite whole. It runs the mapped tests and the smoke set
# (the plan's `smoke`, repro.smoke) and the reproduction tests, whether the
# plan is targeted or not (a path nothing maps is the queue's to cover), and
# nothing when there are none; a suite whose command is not Playwright's
# own still runs whole.
#
# FLAKY_REPORT (#479): a command that is Playwright's own runs with one retry
# and the JSON reporter beside the list one, its report at FLAKY_REPORT: a
# test that fails and then passes on its retry is `flaky`, which does not
# fail the run, and scripts/flaky.py reports it with its spec and line. Any
# other command runs as it is: its retries and reporters are its own.
set -euo pipefail

# Whether a suite's command is Playwright's own, alone: flags may follow it.
playwright_own() {
  [[ "$1" =~ ^[[:space:]]*(([A-Z_][A-Z0-9_]*=[^[:space:]]*[[:space:]]+)*)npx[[:space:]]+playwright[[:space:]]+test([[:space:]]|$) ]] && [[ "$1" != *[\;\&\|\`\$\(\)\<\>]* ]] && [[ "$1" != *$'\n'* ]]
}

# The suite's command, $1, with the flags after it ($2...), and one retry
# with the JSON report where FLAKY_REPORT says, when it is Playwright's own.
suite() {
  local run=$1; shift
  if [ -n "${FLAKY_REPORT:-}" ] && playwright_own "$run"; then
    mkdir -p "$(dirname "$FLAKY_REPORT")"
    PLAYWRIGHT_JSON_OUTPUT_NAME=$FLAKY_REPORT bash -c "$run $* --retries=1 --reporter=list,json"
  else
    bash -c "$run${*:+ $*}"
  fi
}

run() {
  local run=${RUN:?} plan=${TARGETED:-} site=${SITE:-single} central=${CENTRAL:-.dx-central} level=${LEVEL:-}
  local tests=() repro=()
  if [ "$level" = pr ]; then
    mapfile -t tests < <(jq -r '((.tests // []) + (.smoke // [])) | unique[]' <<<"${plan:-{\}}" 2>/dev/null || true)
    mapfile -t repro < <(jq -r '(.repro // [])[]' <<<"${plan:-{\}}" 2>/dev/null || true)
    echo "Pull request level (#479): ${tests[*]:-no mapped or smoke tests}; ${repro[*]:-no reproduction tests}. The merge queue runs every suite."
  elif [ -z "$plan" ] || [ "$(jq -r '.targeted // false' <<<"$plan" 2>/dev/null)" != true ]; then
    suite "$run"; return
  else
    mapfile -t tests < <(jq -r '.tests[]' <<<"$plan")
    mapfile -t repro < <(jq -r '.repro[]' <<<"$plan")
    echo "Targeted (#352): ${tests[*]:-no mapped tests}; ${repro[*]:-no reproduction tests}."
  fi
  if [ "${#tests[@]}" -gt 0 ]; then
    if playwright_own "$run"; then
      suite "$run" --pass-with-no-tests "$(printf '%q ' "${tests[@]}")"
    else
      echo "The suite's command is not Playwright's own, so it runs whole: $run"
      suite "$run"
    fi
  fi
  if [ "${#repro[@]}" -gt 0 ] && [ "$site" = single ]; then
    cp "$central/kinds/wordpress-plugin/playwright.dx-repro.config.ts" playwright.dx-repro.config.ts
    npx playwright test -c playwright.dx-repro.config.ts --project=chromium "${repro[@]}"
  fi
}

self_test() {
  local d fail=0 log
  d=$(mktemp -d)
  log="$d/log"
  mkdir -p "$d/bin" "$d/central/kinds/wordpress-plugin"
  : > "$d/central/kinds/wordpress-plugin/playwright.dx-repro.config.ts"
  printf '#!/bin/sh\necho "npx $*" >> %s\n' "$log" > "$d/bin/npx"
  printf '#!/bin/sh\necho "npm $*" >> %s\n' "$log" > "$d/bin/npm"
  chmod +x "$d/bin/npx" "$d/bin/npm"
  t() {
    local name=$1 want=$2 nowant=${3:-}
    : > "$log"
    (cd "$d" && PATH="$d/bin:$PATH" CENTRAL="$d/central" run >/dev/null 2>&1) || true
    if { [ "$want" = EMPTY ] && [ ! -s "$log" ]; } || { grep -qE -- "$want" "$log" && { [ -z "$nowant" ] || ! grep -qE -- "$nowant" "$log"; }; }; then echo "ok   $name"; else echo "FAIL $name"; cat "$log"; fail=1; fi
  }
  plan='{"targeted":true,"tests":["tests/e2e/specs/layout.spec.ts"],"repro":["tests/e2e/repro/issue-69.spec.ts"]}'
  RUN="npx playwright test" TARGETED="" t "no plan runs the whole suite" "^npx playwright test$"
  RUN="npx playwright test" TARGETED='{"targeted":false}' t "a plan that is not targeted runs the whole suite" "^npx playwright test$"
  RUN="npx playwright test" TARGETED=$plan SITE=single t "C5 the mapped tests through the suite's command" "playwright test --pass-with-no-tests tests/e2e/specs/layout.spec.ts"
  RUN="npx playwright test" TARGETED=$plan SITE=single t "C5 and the reproduction test, in chromium" "-c playwright.dx-repro.config.ts --project=chromium tests/e2e/repro/issue-69.spec.ts"
  RUN="npx playwright test -c playwright.network.config.ts" TARGETED=$plan SITE=network t "C5 the network suite runs the mapped tests, not the reproduction" "network.config.ts --pass-with-no-tests" "dx-repro"
  RUN="DU_SNAPSHOTS=1 npx playwright test --project=visual" TARGETED=$plan SITE=single t "a command with variables first is still Playwright's" "--project=visual --pass-with-no-tests"
  RUN="npm run test:e2e" TARGETED=$plan SITE=single t "an npm script runs whole, its arguments untouched" "^npm run test:e2e$" "npm run test:e2e --pass"
  RUN=$'npx playwright test\nnpm run report' TARGETED=$plan SITE=single t "a command on several lines runs whole" "^npx playwright test$" "pass-with-no-tests"
  RUN="npx playwright test && npm run report" TARGETED=$plan SITE=single t "a compound command runs whole, the flags on no part of it" "^npx playwright test$" "pass-with-no-tests"
  # #479 C3: a pull request where the queue runs every suite.
  local pr_plan='{"targeted":false,"tests":["tests/e2e/specs/layout.spec.ts"],"repro":[],"smoke":["tests/e2e/specs/smoke.spec.ts","tests/e2e/specs/layout.spec.ts"]}'
  RUN="npx playwright test" TARGETED=$pr_plan LEVEL=pr t "C3 a queue's pull request runs the mapped specs and the smoke set, each once, even untargeted" \
    "playwright test --pass-with-no-tests tests/e2e/specs/layout.spec.ts tests/e2e/specs/smoke.spec.ts" "^npx playwright test$"
  RUN="npx playwright test" TARGETED='{"targeted":false,"tests":[],"repro":[],"smoke":[]}' LEVEL=pr t "C3 nothing mapped and no smoke set runs nothing, never the whole suite" EMPTY
  RUN="npx playwright test" TARGETED='' LEVEL=pr t "C3 no plan at the pull request level runs nothing" EMPTY
  RUN="npx playwright test" TARGETED=$pr_plan t "C3 without the level, an untargeted plan still runs the whole suite (the queue's group, a push)" "^npx playwright test$" "pass-with-no-tests"
  # #479 C4: one retry and the JSON report, for Playwright's own command.
  printf '#!/bin/sh\necho "npx $* json=$PLAYWRIGHT_JSON_OUTPUT_NAME" >> %s\n' "$log" > "$d/bin/npx"
  RUN="npx playwright test" TARGETED='' FLAKY_REPORT=build/dx-e2e.json t "C4 a whole run retries once, the JSON report beside the list one" \
    "^npx playwright test --retries=1 --reporter=list,json json=build/dx-e2e.json$"
  RUN="npx playwright test" TARGETED=$plan SITE=network FLAKY_REPORT=build/dx-e2e.json t "C4 a targeted run too, after its filters" \
    "pass-with-no-tests tests/e2e/specs/layout.spec.ts +--retries=1 --reporter=list,json json=build/dx-e2e.json"
  RUN="npm run test:e2e" TARGETED='' FLAKY_REPORT=build/dx-e2e.json t "C4 another command keeps its own retries and reporters" "^npm run test:e2e$" "retries"
  RUN="npx playwright test" TARGETED='' t "C4 without FLAKY_REPORT, nothing is added" "^npx playwright test json=$" "retries"
  rm -rf "$d"
  if [ "$fail" -eq 0 ]; then echo "all tests passed"; else return 1; fi
}

case "${1:-}" in
  run) run ;;
  --test) self_test ;;
  *) echo "usage: e2e-run.sh run | --test" >&2; exit 2 ;;
esac
