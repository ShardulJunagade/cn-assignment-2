#!/bin/bash
set -euo pipefail # Exit on error, undefined variable, or failed pipe

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PYTHON_BIN=${PYTHON_BIN:-python3}

usage() {
  cat <<'EOF'
Usage: sudo ./run_assignment.sh <command> [options]

Commands:
  setup                         Create results/ and logs/ folders
  system-baseline [args...]     Run Task B using the host system resolver
  custom-iterative [args...]    Run Task D (iterative custom resolver)
  custom-recursive [args...]    Run Task E (recursive custom resolver)
  custom-iterative-nocache      Run Task F comparison with cache disabled
  clean                         Remove stale Mininet state (mn -c)

All commands except 'setup' and 'clean' accept the same optional arguments
as src/main.py (e.g. --with-nat, --gateway-ip, --timeout).
EOF
}

require_root() {
  if [[ $(id -u) -ne 0 ]]; then
    echo "This command must be run as root. Try: sudo ./run_assignment.sh $1" >&2
    exit 1
  fi
}

run_phase() {
  local phase=$1
  shift || true
  require_root "$phase"
  ${PYTHON_BIN} "${ROOT_DIR}/src/main.py" "${phase}" "$@"
}

cmd=${1:-}
if [[ -z "$cmd" ]]; then
  usage
  exit 1
fi
shift || true

case "$cmd" in
  setup)
    mkdir -p "${ROOT_DIR}/results" "${ROOT_DIR}/logs"
    echo "Folders results/ and logs/ are ready."
    ;;
  system-baseline)
    run_phase "system-baseline" --with-nat "$@"
    ;;
  custom-iterative)
    run_phase "custom-iterative" --with-nat "$@"
    ;;
  custom-recursive)
    run_phase "custom-recursive" --with-nat "$@"
    ;;
  custom-iterative-nocache)
    run_phase "custom-iterative" --with-nat --no-cache "$@"
    ;;
  clean)
    require_root "clean"
    mn -c || true
    ;;
  *)
    usage
    exit 1
    ;;
esac
