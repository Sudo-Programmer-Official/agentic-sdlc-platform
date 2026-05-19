#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT_DIR/apps/api"
ENV_FILE="$API_DIR/.env"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <fast|strict>"
  exit 1
fi

MODE="$1"
PROFILE_FILE="$API_DIR/.env.$MODE"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE"
  exit 1
fi

if [[ ! -f "$PROFILE_FILE" ]]; then
  echo "Missing profile file: $PROFILE_FILE"
  exit 1
fi

set_key() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i.bak "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    printf "\n%s=%s\n" "$key" "$value" >> "$ENV_FILE"
  fi
}

while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  [[ "$line" =~ ^# ]] && continue
  key="${line%%=*}"
  value="${line#*=}"
  set_key "$key" "$value"
done < "$PROFILE_FILE"

rm -f "$ENV_FILE.bak"

echo "Applied runtime mode '$MODE' from $(basename "$PROFILE_FILE")"
echo "Restart API/scheduler/worker to pick up new settings."
