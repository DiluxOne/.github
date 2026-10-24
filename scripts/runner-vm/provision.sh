#!/usr/bin/env bash
# Brings the organisation's VM to the state this repository describes, on
# every boot, before its runner slots start. dx-provision.service fetches this
# script from this repository's main branch and runs it, so a merged change
# reaches the VM on its next start; nobody changes the VM by hand.
#
#   provision.sh            apply (as root, on the VM)
#   provision.sh --install  first time on a new VM: install dx-provision.service
#                           and run it (needs /etc/dx-runner/app.env and app.pem,
#                           the dilux-runner App's, put there by an administrator)
#   provision.sh --test     self-test
#
# What it guarantees, idempotently:
#   - Docker's images live on the data disk: containerd's root is /data/containerd
#     (Docker 29 stores images through containerd, which data-root does not move).
#   - The scripts and units of the runner slots, from this repository.
#   - The runner image, pulled fresh (:stable).
#   - The old long-lived runner services of DiluxOne disabled; the slots enabled.
#   - What jobs leave behind and nothing references any more, removed.
set -euo pipefail

DX_REF=${DX_REF:-main}
DX_RAW=${DX_RAW:-https://raw.githubusercontent.com/DiluxOne/.github/$DX_REF/scripts/runner-vm}
DX_LIB=${DX_LIB:-/usr/local/lib/dx-runner}
# Three slots per two cores unless DX_SLOTS says otherwise (#138, #379): with
# one per core the 8 slots kept the data disk at its IOPS cap while CPU
# stayed at 20 to 28% and most memory was free, so a job waits on the disk
# more than on a core; 12 slots on the VM's 8 cores and 32 GB, each port
# pair (9000 + 20 x slot) still free of any other.
slot_count() { # [DX_SLOTS] [cores]
  local want=${1:-} cores=${2:-$(nproc)}
  if [[ "$want" =~ ^[1-9][0-9]*$ ]]; then echo "$want"; else echo $(( (cores * 3 + 1) / 2 )); fi
}
DX_SLOTS=$(slot_count "${DX_SLOTS:-}")
DX_IMAGE=${DX_IMAGE:-ghcr.io/diluxone/runner:stable}
CONTAINERD_ROOT=${CONTAINERD_ROOT:-/data/containerd}

# The containerd config with its root on the data disk: the root line first
# (a top-level key must precede any table), every other line kept.
containerd_config() { # < current config
  local root=$1
  printf 'root = "%s"\n' "$root"
  grep -v '^[[:space:]]*root[[:space:]]*=' || true
}

# The dx-runner@N units numbered above $1, among the unit names in $2 (one
# per line): what a smaller count leaves behind.
extra_slots() { # count names
  local n
  for n in $(printf '%s\n' "$2" | sed -n 's/^dx-runner@\([0-9]\+\)\.service$/\1/p'); do
    [ "$n" -gt "$1" ] && echo "dx-runner@$n.service"
  done
  return 0
}

slot_unit() {
  cat <<EOF
[Unit]
Description=DiluxOne runner slot %i (one job per container)
After=docker.service dx-provision.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
ExecStart=$DX_LIB/dx-runner-slot.sh %i
Restart=always
RestartSec=10
TimeoutStopSec=60
KillMode=mixed

[Install]
WantedBy=multi-user.target
EOF
}

provision_unit() {
  cat <<EOF
[Unit]
Description=Bring the DiluxOne runner VM to the state DiluxOne/.github describes
After=network-online.target docker.service
Wants=network-online.target
Before=dx-runner@.service

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'curl -fsSL $DX_RAW/provision.sh -o $DX_LIB/provision.sh.new && mv $DX_LIB/provision.sh.new $DX_LIB/provision.sh; exec bash $DX_LIB/provision.sh'
TimeoutStartSec=1800

[Install]
WantedBy=multi-user.target
EOF
}

apply() {
  mkdir -p "$DX_LIB" /var/lib/dx-runner
  if ! command -v jq >/dev/null || ! command -v openssl >/dev/null || ! command -v curl >/dev/null; then
    apt-get update -qq && apt-get install -y -qq jq openssl curl >/dev/null
  fi
  # containerd on the data disk. On a VM that has no images yet it is set
  # here; moving images already on the system disk stays a one-off by hand.
  if [ -f /etc/containerd/config.toml ] && ! grep -q "^root = \"$CONTAINERD_ROOT\"" /etc/containerd/config.toml; then
    if [ -z "$(ls -A /var/lib/containerd/io.containerd.content.v1.content/blobs 2>/dev/null)" ]; then
      containerd_config "$CONTAINERD_ROOT" < /etc/containerd/config.toml > /etc/containerd/config.toml.new
      mv /etc/containerd/config.toml.new /etc/containerd/config.toml
      systemctl restart containerd docker
    else
      echo "provision: containerd keeps images in /var/lib/containerd; move them to $CONTAINERD_ROOT by hand" >&2
    fi
  fi
  curl -fsSL "$DX_RAW/dx-runner-slot.sh" -o "$DX_LIB/dx-runner-slot.sh.new"
  bash "$DX_LIB/dx-runner-slot.sh.new" --test >/dev/null
  mv "$DX_LIB/dx-runner-slot.sh.new" "$DX_LIB/dx-runner-slot.sh"; chmod 755 "$DX_LIB/dx-runner-slot.sh"
  slot_unit > /etc/systemd/system/dx-runner@.service
  provision_unit > /etc/systemd/system/dx-provision.service
  # A failed pull keeps the image already here; the slots still start.
  docker pull -q "$DX_IMAGE" >/dev/null || echo "provision: could not pull $DX_IMAGE; using the one on the VM" >&2
  local unit
  for unit in $(systemctl list-unit-files --no-legend 'actions.runner.DiluxOne.*' | awk '{print $1}'); do
    systemctl disable --now "$unit" >/dev/null 2>&1 || true
  done
  systemctl daemon-reload
  systemctl enable dx-provision.service >/dev/null
  local n
  for n in $(seq 1 "$DX_SLOTS"); do systemctl enable "dx-runner@$n.service" >/dev/null; done
  # A bigger count before (a larger machine, or DX_SLOTS by hand) leaves
  # units above the count: they are stopped and disabled, never left to run.
  local u
  for u in $(extra_slots "$DX_SLOTS" "$(systemctl list-units 'dx-runner@*.service' --all --no-legend --plain 2>/dev/null | awk '{print $1}'; systemctl list-unit-files 'dx-runner@*.service' --no-legend 2>/dev/null | awk '{print $1}')"); do
    systemctl disable --now "$u" >/dev/null 2>&1 || true
  done
  docker container prune -f >/dev/null; docker image prune -f >/dev/null
  docker builder prune -f --filter until=168h >/dev/null || true
  echo "provision: done ($DX_SLOTS slots, $DX_IMAGE)"
}

install() {
  [ -f /etc/dx-runner/app.env ] && [ -f /etc/dx-runner/app.pem ] || { echo "provision: /etc/dx-runner/app.env and app.pem first" >&2; exit 1; }
  mkdir -p "$DX_LIB"
  provision_unit > /etc/systemd/system/dx-provision.service
  systemctl daemon-reload
  systemctl enable --now dx-provision.service
  local n
  for n in $(seq 1 "$DX_SLOTS"); do systemctl start "dx-runner@$n.service"; done
}

self_test() {
  local fail=0
  check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: got [$2], want [$3]"; fail=1; fi; }
  check "containerd root added first" "$(printf 'disabled_plugins = ["cri"]\n' | containerd_config /data/containerd)" \
    "$(printf 'root = "/data/containerd"\ndisabled_plugins = ["cri"]')"
  check "containerd root replaced" "$(printf 'root = "/var/lib/containerd"\nversion = 2\n' | containerd_config /data/containerd)" \
    "$(printf 'root = "/data/containerd"\nversion = 2')"
  check "slot unit runs the slot" "$(slot_unit | grep ExecStart)" "ExecStart=$DX_LIB/dx-runner-slot.sh %i"
  check "provision unit fetches from main" "$(provision_unit | grep -c 'raw.githubusercontent.com/DiluxOne/.github/main/scripts/runner-vm/provision.sh')" "1"
  # #138, #379: three slots per two cores, DX_SLOTS overriding; a smaller count trims the extra units.
  check "#379: the default count is three slots per two cores, 12 on the VM's 8" "$(slot_count '' 8)" "12"
  check "#379: an odd core count rounds up, never to zero" "$(slot_count '' 1) $(slot_count '' 3)" "2 5"
  check "C2 (#138): DX_SLOTS overrides the cores" "$(slot_count 6 8)" "6"
  check "C2 (#138): a DX_SLOTS that is not a count (empty, 0, text) falls back to the default" "$(slot_count 0 8) $(slot_count abc 8) $(slot_count '' 8)" "12 12 12"
  check "C1 (#138): units above the count are the extra ones, in order, each once" "$(extra_slots 4 "$(printf 'dx-runner@1.service\ndx-runner@6.service\ndx-runner@4.service\ndx-runner@8.service\ndx-runner@.service\ndx-runner@6.service\n')" | sort -u | tr '\n' ' ')" "dx-runner@6.service dx-runner@8.service "
  check "C1 (#138): nothing above the count, nothing to trim" "$(extra_slots 8 "$(printf 'dx-runner@1.service\ndx-runner@8.service\n')")" ""
  [ "$fail" = 0 ] && echo "all tests passed"
  return "$fail"
}

case "${1:-}" in
  --test) self_test ;;
  --install) install ;;
  '') apply ;;
  *) echo "usage: $0 [--install | --test]" >&2; exit 64 ;;
esac
