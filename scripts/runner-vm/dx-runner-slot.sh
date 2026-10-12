#!/usr/bin/env bash
# One runner slot on the organisation's VM: an endless loop of one-job
# runners. Each turn it asks GitHub for a just-in-time runner configuration
# (the dilux-runner App, whose only permission is the organisation's
# self-hosted runners), starts a fresh container of ghcr.io/diluxone/runner
# with it, waits for that one job to end, and cleans what the job left on the
# VM before the next turn: its containers, its checkout, and the volumes and
# networks of its wp-env (docker compose keeps them past the containers, and
# the next job of the slot would find the last job's database). Nothing a job
# installs survives it.
#
#   dx-runner-slot.sh <slot>     run slot <slot> (1, 2, …); systemd's
#                                dx-runner@<slot>.service does this
#   dx-runner-slot.sh --test     self-test
#
# Reads /etc/dx-runner/app.env (CLIENT_ID, INSTALLATION_ID, ORG) and the App's
# key /etc/dx-runner/app.pem, both root-only. Every job gets the VM's Docker
# socket (wp-env needs it), which is root on the VM: a job could read that key.
# That is accepted on the same terms as the VM itself (runner-vm.yml's
# header): only the private repositories run here, with pull requests from
# the maintainer, the maintainer's agents and Dependabot alone, and the key can
# do nothing but register runners. Each slot keeps its own ports
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

# The docker compose projects of the slot's last job, one per folder of its
# wp-env home: wp-env writes each project's docker-compose.yml in a folder of
# its own there (`wp-env-<repo>-<hash>`), and docker compose, given no name,
# names the project after that folder (lower-case, nothing but [a-z0-9_-]),
# and its volumes and networks after the project.
slot_projects() { # slot
  local dir
  for dir in "$DX_BASE/d$1/wp-env"/*/; do
    [ -d "$dir" ] && basename "$dir" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_\n-'
  done
  return 0
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

# Deletes a runner registration; one already gone is fine.
drop_runner() {
  [ -n "${1:-}" ] || return 0
  curl -sS -o /dev/null -X DELETE -H "Authorization: Bearer $(app_token)" -H "Accept: application/vnd.github+json" \
    "$API/orgs/$ORG/actions/runners/$1" || true
}

# Removes what the last job left: its wp-env containers, then the volumes
# (the databases among them) and networks of its wp-env projects, which
# docker compose keeps past the containers, then its checkout (the tool cache
# stays: jobs in one slot run one after another).
clean_slot() {
  local slot=$1 ids project
  ids=$(docker ps -a --format '{{.ID}} {{.Label "com.docker.compose.project.working_dir"}}' | slot_containers "$slot")
  # shellcheck disable=SC2086 # one ID per word
  [ -z "$ids" ] || docker rm -f $ids >/dev/null
  mkdir -p "$DX_BASE/d$slot/_work" "$DX_BASE/d$slot/wp-env"
  for project in $(slot_projects "$slot"); do
    ids=$(docker volume ls -q --filter "label=com.docker.compose.project=$project")
    # shellcheck disable=SC2086 # one name per word
    [ -z "$ids" ] || docker volume rm -f $ids >/dev/null || echo "dx-runner $slot: could not remove the volumes of $project" >&2
    ids=$(docker network ls -q --filter "label=com.docker.compose.project=$project")
    # shellcheck disable=SC2086 # one ID per word
    [ -z "$ids" ] || docker network rm $ids >/dev/null || echo "dx-runner $slot: could not remove the networks of $project" >&2
  done
  find "$DX_BASE/d$slot/_work" -mindepth 1 -maxdepth 1 ! -name _tool -exec rm -rf {} +
  rm -rf "${DX_BASE:?}/d$slot/wp-env/"*
  chown -R "$RUNNER_UID" "$DX_BASE/d$slot"
}

run_slot() {
  local slot=$1 name token jit dev tests envfile
  # shellcheck disable=SC1091
  . "$DX_CONF/app.env"
  mkdir -p "$DX_STATE"
  RUNNER_UID=$(docker run --rm --entrypoint id "$DX_IMAGE" -u)
  read -r dev tests <<<"$(slot_ports "$slot")"
  local gid; gid=$(stat -c %g /var/run/docker.sock)
  runner_id=""
  trap 'docker stop -t 30 "dx-runner-$slot" >/dev/null 2>&1 || true; drop_runner "$runner_id"; rm -f "$DX_STATE/jit-$slot.env"; exit 0' TERM INT
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
    # The configuration goes in a root-only file, not on the command line,
    # where ps would show it to any user of the VM; it is deleted as soon as
    # the job ends.
    envfile="$DX_STATE/jit-$slot.env"
    (umask 077; printf 'DX_JIT_CONFIG=%s\n' "$(jq -r .encoded_jit_config <<<"$jit")" > "$envfile")
    docker run --rm --init --name "dx-runner-$slot" --network host --group-add "$gid" \
      -v /var/run/docker.sock:/var/run/docker.sock \
      -v "$DX_BASE/d$slot:$DX_BASE/d$slot" \
      --env-file "$envfile" \
      -e WP_ENV_PORT="$dev" -e WP_ENV_TESTS_PORT="$tests" -e WP_ENV_HOME="$DX_BASE/d$slot/wp-env" \
      "$DX_IMAGE" &
    # A just-in-time runner exits 0 after its job, and GitHub removes it on
    # its own. Anything else (a broken image, Docker down) leaves it
    # registered without a job: delete it and wait, so the slot does not
    # register runner after runner.
    local ok=0; wait $! || ok=$?
    rm -f "$envfile"
    if [ "$ok" = 0 ]; then
      touch "$DX_STATE/last-job"
    else
      echo "dx-runner $slot: the container ended with an error; waiting 60 s" >&2
      drop_runner "$runner_id"
      sleep 60
    fi
    runner_id=""
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
  local home; home=$(mktemp -d); mkdir -p "$home/d1/wp-env/wp-env-Diluxone-Users-a8cf25ac" "$home/d1/wp-env/0f1e2d3c4b5a69788796a5b4c3d2e1f0" "$home/d2/wp-env/wp-env-other-11111111"
  touch "$home/d1/wp-env/a-file"
  check "slot 1 projects: its folders, as compose names them" "$(DX_BASE=$home slot_projects 1 | sort | tr '\n' ' ')" "0f1e2d3c4b5a69788796a5b4c3d2e1f0 wp-env-diluxone-users-a8cf25ac "
  check "slot 3 projects: none" "$(DX_BASE=$home slot_projects 3 | tr '\n' ' ')" ""
  rm -rf "$home"
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
