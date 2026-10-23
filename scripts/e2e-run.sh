#!/usr/bin/env bash
# Runs one end-to-end suite of plugin-tests-wp.yml: whole, or only what a
# pull request touches (#352, scripts/repro-ways.py affected).
#
#   e2e-run.sh run     RUN (the suite's command), TARGETED (the plan JSON, or
#                      empty), SITE (single or network), CENTRAL (the
#                      organisation's checkout)
#   e2e-run.sh --test  self-test, with a stand-in for npx
#
# Targeted: the mapped tests through the suite's own command, when that
# command is Playwright's own (`npx playwright test ...`, which takes file
# filters and --pass-with-no-tests, so a suite they are not part of runs
# none), alone: any other command (an npm script, a wrapper, a list of
# commands) runs whole, as the filters could land on the wrong part. The reproduction tests run on the single site, in
# chromium, through the kind's playwright.dx-repro.config.ts.
set -euo pipefail

run() {
  local run=${RUN:?} plan=${TARGETED:-} site=${SITE:-single} central=${CENTRAL:-.dx-central}
  local tests=() repro=()
  if [ -z "$plan" ] || [ "$(jq -r '.targeted // false' <<<"$plan" 2>/dev/null)" != true ]; then
    bash -c "$run"; return
  fi
  mapfile -t tests < <(jq -r '.tests[]' <<<"$plan")
  mapfile -t repro < <(jq -r '.repro[]' <<<"$plan")
  echo "Targeted (#352): ${tests[*]:-no mapped tests}; ${repro[*]:-no reproduction tests}."
  if [ "${#tests[@]}" -gt 0 ]; then
    if [[ "$run" =~ ^[[:space:]]*(([A-Z_][A-Z0-9_]*=[^[:space:]]*[[:space:]]+)*)npx[[:space:]]+playwright[[:space:]]+test([[:space:]]|$) ]] && [[ "$run" != *[\;\&\|\`\$\(\)\<\>]* ]] && [[ "$run" != *$'\n'* ]]; then
      bash -c "$run --pass-with-no-tests $(printf '%q ' "${tests[@]}")"
    else
      echo "The suite's command is not Playwright's own, so it runs whole: $run"
      bash -c "$run"
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
    if grep -qE -- "$want" "$log" && { [ -z "$nowant" ] || ! grep -qE -- "$nowant" "$log"; }; then echo "ok   $name"; else echo "FAIL $name"; cat "$log"; fail=1; fi
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
  rm -rf "$d"
  if [ "$fail" -eq 0 ]; then echo "all tests passed"; else return 1; fi
}

case "${1:-}" in
  run) run ;;
  --test) self_test ;;
  *) echo "usage: e2e-run.sh run | --test" >&2; exit 2 ;;
esac
