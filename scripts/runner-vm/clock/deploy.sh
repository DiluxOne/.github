#!/usr/bin/env bash
# Deploys the VM's clock (clock.py, function_app.py) to its Function App in
# Azure: diluxone-runner-cl-prod-func, on the dilux-cl-prod-linux-plan App
# Service plan, Python 3.14. The packages are built here for Linux x86_64 and
# shipped in the zip (.python_packages): no build runs on the App.
#
#   deploy.sh          build and deploy (needs az logged in, and uv)
#   deploy.sh --test   self-test: the package holds what the App loads
#
# The App's settings (the dilux-bot key among them) are set once by an
# administrator, never from here: see clock.py. Nothing deploys on merge:
# whoever merges a change to this directory runs this script after it, and
# says so on the pull request.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
RG=${RG:-dilux-hosting-cl-rg}
APP=${APP:-diluxone-runner-cl-prod-func}
PY=${PY:-3.14}
FILES=(function_app.py clock.py requirements.txt host.json)

package() { # <dir> <zip> [skip-deps]
  local dir=$1 zip=$2
  cp "${FILES[@]/#/$HERE/}" "$dir/"
  if [ -z "${3:-}" ]; then
    uv pip install -q --target "$dir/.python_packages/lib/site-packages" \
      --python-platform x86_64-manylinux_2_28 --python-version "$PY" \
      --only-binary :all: -r "$dir/requirements.txt"
  fi
  (cd "$dir" && zip -qr "$zip" .)
}

if [ "${1:-}" = --test ]; then
  fails=0
  check() { # <name> <status>
    if [ "$2" -eq 0 ]; then echo "ok    $1"; else echo "FAIL  $1"; fails=$((fails + 1)); fi
  }
  t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
  mkdir "$t/pkg"
  package "$t/pkg" "$t/clock.zip" skip-deps
  listing=$(unzip -Z1 "$t/clock.zip")
  for f in "${FILES[@]}"; do
    check "package: $f at the root" "$(grep -qx "$f" <<<"$listing"; echo $?)"
  done
  req="$HERE/requirements.txt"
  check "requirements: azure-functions, PyJWT with crypto, cryptography, pinned" \
    "$(grep -qx 'azure-functions==[0-9.]*' "$req" && grep -qx 'PyJWT\[crypto\]==[0-9.]*' "$req" && grep -qx 'cryptography==[0-9.]*' "$req"; echo $?)"
  check "host.json: valid JSON with an extension bundle" \
    "$(python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1]))["extensionBundle"]["id"] else 1)' "$HERE/host.json"; echo $?)"
  check "function_app.py: compiles" "$(python3 -m py_compile "$HERE/function_app.py" 2>/dev/null; echo $?)"
  check "clock: its own self-test passes" "$(python3 "$HERE/clock.py" --test >/dev/null; echo $?)"
  if [ "$fails" -ne 0 ]; then echo "$fails failed"; exit 1; fi
  echo "all passed"
  exit 0
fi

t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
mkdir "$t/pkg"
package "$t/pkg" "$t/clock.zip"
az functionapp deployment source config-zip -g "$RG" -n "$APP" --src "$t/clock.zip" -o none
echo "Deployed to $APP."
