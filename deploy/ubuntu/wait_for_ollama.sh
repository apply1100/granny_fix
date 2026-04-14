#!/usr/bin/env bash

set -euo pipefail

ENV_FILE="${1:-/opt/grannybot/.env}"
OLLAMA_HOST_DEFAULT="http://127.0.0.1:11434"
MAX_ATTEMPTS="${OLLAMA_WAIT_ATTEMPTS:-30}"
SLEEP_SECONDS="${OLLAMA_WAIT_SECONDS:-2}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [[ "${LOCAL_QWEN_BACKEND:-ollama}" != "ollama" ]]; then
  exit 0
fi

OLLAMA_HOST="${LOCAL_QWEN_OLLAMA_HOST:-$OLLAMA_HOST_DEFAULT}"

for ((attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1)); do
  if curl -fsS "${OLLAMA_HOST%/}/api/tags" >/dev/null 2>&1; then
    exit 0
  fi
  sleep "$SLEEP_SECONDS"
done

echo "Ollama API was not ready at ${OLLAMA_HOST%/} after ${MAX_ATTEMPTS} attempts." >&2
exit 1
