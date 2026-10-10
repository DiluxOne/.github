#!/usr/bin/env bash
# One runner slot on the organisation's VM: an endless loop of one-job
# runners. Each turn it asks GitHub for a just-in-time runner configuration
# (the dilux-runner App, whose only permission is the organisation's
# self-hosted runners), starts a fresh container of ghcr.io/diluxone/runner
# with it, waits for that one job to end, and cleans what the job left on the
# VM before the next turn. Nothing a job installs survives it.
#
#   dx-runner-slot.sh <slot>     run slot <slot> (1, 2, …); systemd's
#                                dx-runner@<slot>.service does this
#   dx-runner-slot.sh --test     self-test
#
# Reads /etc/dx-runner/app.env (CLIENT_ID, INSTALLATION_ID, ORG) and the App's
# key /etc/dx-runner/app.pem, both root-only. Each slot keeps its own ports
# (wp-env suites side by side never share one) and its own folders under
# $DX_BASE/d<slot>, mounted into the container at the same path, because the
# jobs start wp-env containers on the VM's own Docker, which resolves paths on
# the VM.
set -euo pipefail

DX_BASE=${DX_BASE:-/data/runners-dx}
DX_IMAGE=${DX_IMAGE:-ghcr.io/diluxone/runner:stable}
DX_GROUP_ID=${DX_GROUP_ID:-3}                  # runner group private-repos-vm
DX_LABELS=${DX_LABELS:-self-hosted,linux,x64,diluxone}
DX_PORT_BASE=${DX_PORT_BASE:-9000}
DX_STATE=${DX_STATE:-/var/lib/dx-runner}
DX_CONF=${DX_CONF:-/etc/dx-runner}
API=https://api.github.com

# Ports of a slot: the development site and the tests site.
slot_ports() { echo "$((DX_PORT_BASE + 20 * $1)) $((DX_PORT_BASE + 20 * $1 + 1))"; }

# The runner's name: the slot plus a random suffix, since every job registers
# a new runner and GitHub wants names unique.
runner_name() { printf 'diluxone-chile-%s-%s' "$1" "$2"; }

# The body of POST /orgs/{org}/actions/runners/generate-jitconfig.
jit_payload() { # name slot
  jq -nc --arg name "$1" --argjson group "$DX_GROUP_ID" --arg labels "$DX_LABELS" \
    --arg work "$DX_BASE/d$2/_work" \
    '{name: $name, runner_group_id: $group, labels: ($labels | split(",")), work_folder: $work}'
}

# From `docker ps -a --format '{{.ID}} {{.Label "com.docker.compose.project.working_dir"}}'`
# lines, the containers this slot's wp-env started (its compose projects live
# under the slot's wp-env home).
slot_containers() { # slot < lines
  awk -v home="$DX_BASE/d$1/wp-env/" 'index($2, home) == 1 {print $1}'
}

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

app_token() {
  local now h p sig
  now=$(date +%s)
  h=$(printf '{"alg":"RS256","typ":"JWT"}' | b64url)
  p=$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' $((now - 60)) $((now + 540)) "$CLIENT_ID" | b64url)
  sig=$(printf '%s.%s' "$h" "$p" | openssl dgst -sha256 -sign "$DX_CONF/app.pem" | b64url)
  curl -fsS -X POST -H "Authorization: Bearer $h.$p.$sig" -H "Accept: application/vnd.github+json" \
    "$API/app/installations/$INSTALLATION_ID/access_tokens" | jq -r .token
}

# Removes what the last job left: its wp-env containers and its checkout
# (the tool cache stays: jobs in one slot run one after another).
clean_slot() {
  local slot=$1 ids
  ids=$(docker ps -a --format '{{.ID}} {{.Label "com.docker.compose.project.working_dir"}}' | slot_containers "$slot")
  # shellcheck disable=SC2086 # one ID per word
  [ -z "$ids" ] || docker rm -f $ids >/dev/null
  docker volume prune -f >/dev/null || true
  mkdir -p "$DX_BASE/d$slot/_work" "$DX_BASE/d$slot/wp-env"
  find "$DX_BASE/d$slot/_work" -mindepth 1 -maxdepth 1 ! -name _tool -exec rm -rf {} +
  rm -rf "${DX_BASE:?}/d$slot/wp-env/"*
  chown -R "$RUNNER_UID" "$DX_BASE/d$slot"
}

run_slot() {
  local slot=$1 name token jit dev tests
  # shellcheck disable=SC1091
  . "$DX_CONF/app.env"
  mkdir -p "$DX_STATE"
  RUNNER_UID=$(docker run --rm --entrypoint id "$DX_IMAGE" -u)
  read -r dev tests <<<"$(slot_ports "$slot")"
  local gid; gid=$(stat -c %g /var/run/docker.sock)
  runner_id=""
  trap 'docker stop -t 30 "dx-runner-$slot" >/dev/null 2>&1 || true; [ -z "$runner_id" ] || curl -fsS -X DELETE -H "Authorization: Bearer $(app_token)" "$API/orgs/$ORG/actions/runners/$runner_id" >/dev/null || true; exit 0' TERM INT
  while :; do
    clean_slot "$slot"
    name=$(runner_name "$slot" "$(openssl rand -hex 3)")
    if ! token=$(app_token) || [ -z "$token" ] || [ "$token" = null ]; then echo "dx-runner $slot: no App token; retrying in 60 s" >&2; sleep 60; continue; fi
    if ! jit=$(curl -fsS -X POST -H "Authorization: Bearer $token" -H "Accept: application/vnd.github+json" \
        "$API/orgs/$ORG/actions/runners/generate-jitconfig" -d "$(jit_payload "$name" "$slot")"); then
      echo "dx-runner $slot: GitHub refused the runner configuration; retrying in 60 s" >&2; sleep 60; continue
    fi
    runner_id=$(jq -r .runner.id <<<"$jit")
    echo "dx-runner $slot: $name (runner $runner_id) waiting for a job"
    docker run --rm --init --name "dx-runner-$slot" --network host --group-add "$gid" \
      -v /var/run/docker.sock:/var/run/docker.sock \
      -v "$DX_BASE/d$slot:$DX_BASE/d$slot" \
      -e DX_JIT_CONFIG="$(jq -r .encoded_jit_config <<<"$jit")" \
      -e WP_ENV_PORT="$dev" -e WP_ENV_TESTS_PORT="$tests" -e WP_ENV_HOME="$DX_BASE/d$slot/wp-env" \
      "$DX_IMAGE" &
    wait $! || echo "dx-runner $slot: the container ended with an error" >&2
    runner_id=""
    touch "$DX_STATE/last-job"
  done
}

self_test() {
  local fail=0
  check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: got [$2], want [$3]"; fail=1; fi; }
  check "slot 1 ports" "$(slot_ports 1)" "9020 9021"
  check "slot 4 ports" "$(slot_ports 4)" "9080 9081"
  check "runner name" "$(runner_name 2 a1b2c3)" "diluxone-chile-2-a1b2c3"
  check "jit payload" "$(jit_payload diluxone-chile-1-x 1)" \
    '{"name":"diluxone-chile-1-x","runner_group_id":3,"labels":["self-hosted","linux","x64","diluxone"],"work_folder":"/data/runners-dx/d1/_work"}'
  check "slot 1 containers only" "$(printf '%s\n' \
    'aaa /data/runners-dx/d1/wp-env/abc123' \
    'bbb /data/runners-dx/d10/wp-env/def456' \
    'ccc /data/runners-dx/d2/wp-env/ghi789' \
    'ddd ' \
    'eee /data/runners/r1/wp-env/x' | slot_containers 1 | tr '\n' ' ')" "aaa "
  [ "$fail" = 0 ] && echo "all tests passed"
  return "$fail"
}

case "${1:-}" in
  --test) self_test ;;
  ''|-*) echo "usage: $0 <slot> | --test" >&2; exit 64 ;;
  *) [[ "$1" =~ ^[0-9]+$ ]] || { echo "dx-runner: slot must be a number" >&2; exit 64; }; run_slot "$1" ;;
esac
