#!/usr/bin/env bash

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/grannybot}"
VENV_DIR="${VENV_DIR:-$APP_DIR/.venv-server}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"
ENV_TEMPLATE="${ENV_TEMPLATE:-$APP_DIR/deploy/ubuntu/.env.example}"
INSTALL_OLLAMA="${INSTALL_OLLAMA:-1}"
PULL_OLLAMA_MODEL="${PULL_OLLAMA_MODEL:-1}"
OLLAMA_DEFAULT_HOST="http://127.0.0.1:11434"
OLLAMA_DEFAULT_MODEL="gemma4:e4b"

if [[ ! -d "$APP_DIR" ]]; then
  echo "APP_DIR does not exist: $APP_DIR" >&2
  echo "Copy this repository to the server first, then rerun." >&2
  exit 1
fi

if [[ -f "$ENV_TEMPLATE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_TEMPLATE"
  set +a
fi

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

LOCAL_QWEN_BACKEND="${LOCAL_QWEN_BACKEND:-ollama}"
LOCAL_QWEN_OLLAMA_HOST="${LOCAL_QWEN_OLLAMA_HOST:-$OLLAMA_DEFAULT_HOST}"
LOCAL_QWEN_OLLAMA_MODEL="${LOCAL_QWEN_OLLAMA_MODEL:-$OLLAMA_DEFAULT_MODEL}"

sudo apt-get update
sudo apt-get install -y python3 python3-venv libgomp1 curl ca-certificates

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
if "$VENV_DIR/bin/python" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('playwright') else 1)"; then
  "$VENV_DIR/bin/python" -m playwright install --with-deps chromium
fi

mkdir -p "$APP_DIR/memory"
mkdir -p "$APP_DIR/model-cache"
chmod 750 "$APP_DIR" "$APP_DIR/memory" "$APP_DIR/model-cache" || true
if [[ -f "$ENV_FILE" ]]; then
  chmod 600 "$ENV_FILE" || true
fi

if [[ "$INSTALL_OLLAMA" == "1" && "$LOCAL_QWEN_BACKEND" == "ollama" ]]; then
  if ! command -v ollama >/dev/null 2>&1; then
    curl -fsSL https://ollama.com/install.sh | sh
  fi

  sudo systemctl enable --now ollama

  if [[ "$PULL_OLLAMA_MODEL" == "1" && -n "$LOCAL_QWEN_OLLAMA_MODEL" ]]; then
    ollama pull "$LOCAL_QWEN_OLLAMA_MODEL"
  fi
fi

cat <<EOF

Install complete.

Runtime summary:
- App dir: $APP_DIR
- Virtualenv: $VENV_DIR
- Backend: $LOCAL_QWEN_BACKEND
- Ollama host: $LOCAL_QWEN_OLLAMA_HOST
- Ollama model: $LOCAL_QWEN_OLLAMA_MODEL

Next steps:
1. Copy deploy/ubuntu/.env.example to $APP_DIR/.env and fill in the real values if you have not already.
2. Run: chmod 600 $APP_DIR/.env
3. Copy deploy/ubuntu/grannybot.service to /etc/systemd/system/grannybot.service.
4. Run:
   sudo systemctl daemon-reload
   sudo systemctl enable --now grannybot
   sudo systemctl status ollama
   sudo systemctl status grannybot
   sudo journalctl -u grannybot -f

Important:
- Stop any local polling bot before starting the Ubuntu service, or Telegram long polling will conflict.
- Set INSTALL_OLLAMA=0 or PULL_OLLAMA_MODEL=0 if you want to manage Ollama manually.

EOF
