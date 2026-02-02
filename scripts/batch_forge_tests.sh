#!/usr/bin/env bash
# Batch-run forge tests for exploit PoCs with optional month/protocol filters.

set -uo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/batch_forge_tests.sh (--filter YYYY-MM | --protocol ProtocolName[_exp][.sol])

Examples:
  scripts/batch_forge_tests.sh --filter 2024-01
  scripts/batch_forge_tests.sh --protocol BarleyFinance
  scripts/batch_forge_tests.sh --protocol BarleyFinance_exp
  scripts/batch_forge_tests.sh --protocol BarleyFinance_exp.sol

The script always runs:
  forge test --mp <file> --mt '^test' -vvvv --skip Corkprotocol_exp.sol --skip proxy_b7e1_exp.sol
  Logs are written to <Protocol>_exp.txt in the repo root.
EOF
}

FILTER=""
PROTOCOL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --filter)
      FILTER="${2-}"
      shift 2
      ;;
    --protocol)
      PROTOCOL="${2-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$FILTER" && -z "$PROTOCOL" ]]; then
  echo "Provide --filter or --protocol" >&2
  usage
  exit 1
fi

SEARCH_ROOT="src/test"
if [[ -n "$FILTER" ]]; then
  SEARCH_ROOT="${SEARCH_ROOT}/${FILTER}"
  if [[ ! -d "$SEARCH_ROOT" ]]; then
    echo "No such directory: ${SEARCH_ROOT}" >&2
    exit 1
  fi
fi

mapfile -t MATCHES < <(find "$SEARCH_ROOT" -type f -name "*_exp.sol" | sort)

if [[ -n "$PROTOCOL" ]]; then
  PROTOCOL_BASE="${PROTOCOL%.sol}"
  PROTOCOL_BASE="${PROTOCOL_BASE%_exp}"
  if [[ -z "$PROTOCOL_BASE" ]]; then
    echo "Invalid --protocol value: ${PROTOCOL}" >&2
    exit 1
  fi
  FILTERED=()
  for FILE in "${MATCHES[@]}"; do
    if [[ "$(basename "$FILE")" == "${PROTOCOL_BASE}_exp.sol" ]]; then
      FILTERED+=("$FILE")
    fi
  done
  MATCHES=("${FILTERED[@]}")
fi

if [[ ${#MATCHES[@]} -eq 0 ]]; then
  echo "No matching *_exp.sol files found for the provided filters." >&2
  exit 1
fi

SKIP_ARGS=(--skip Corkprotocol_exp.sol --skip proxy_b7e1_exp.sol)
FAILURES=()

for FILE in "${MATCHES[@]}"; do
  PROTOCOL_NAME="$(basename "$FILE")"
  PROTOCOL_NAME="${PROTOCOL_NAME%_exp.sol}"
  LOG_FILE="${PROTOCOL_NAME}_exp.txt"

  echo "Running forge test for ${FILE} (log: ${LOG_FILE})"
  if forge test --mp "$FILE" --mt '^test' -vvvv "${SKIP_ARGS[@]}" | tee "$LOG_FILE"; then
    echo "Completed ${PROTOCOL_NAME}"
  else
    echo "forge test failed for ${FILE}, see ${LOG_FILE}"
    FAILURES+=("$FILE")
  fi
done

if [[ ${#FAILURES[@]} -gt 0 ]]; then
  echo "The following runs failed:"
  for FILE in "${FAILURES[@]}"; do
    echo "  - ${FILE}"
  done
  exit 1
fi
