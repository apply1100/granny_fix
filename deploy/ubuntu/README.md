# Ubuntu deployment

This bot runs directly on an Ubuntu server through systemd.

Recommended layout:

```bash
sudo mkdir -p /opt/grannybot
sudo chown -R "$USER":"$USER" /opt/grannybot
```

Copy the repository into `/opt/grannybot`, then run:

```bash
cd /opt/grannybot
cp deploy/ubuntu/.env.example .env
nano .env
chmod 600 .env
bash deploy/ubuntu/install.sh
sudo cp deploy/ubuntu/grannybot.service /etc/systemd/system/grannybot.service
sudo systemctl daemon-reload
sudo systemctl enable --now grannybot
sudo systemctl status ollama
sudo systemctl status grannybot
sudo journalctl -u grannybot -f
```

What `install.sh` now handles:

- Python venv creation and `requirements.txt` install
- Ollama installation when `LOCAL_QWEN_BACKEND=ollama`
- `LOCAL_QWEN_OLLAMA_MODEL` pull, defaulting to `gemma4:e4b`
- basic runtime directory and `.env` permission hardening

Useful commands:

```bash
sudo systemctl restart ollama
sudo systemctl restart grannybot
sudo systemctl status ollama
sudo systemctl status grannybot
sudo journalctl -u grannybot -n 100 --no-pager
ollama list
```

Updating an existing server:

```bash
sudo systemctl stop grannybot
tar -xzf /tmp/grannybot-deploy.tar.gz -C /opt/grannybot
sudo chown -R ubuntu:ubuntu /opt/grannybot
sudo systemctl start grannybot
```

Extract updates as the service user, or run the `chown` line before restart.
Do not deploy `memory/*.json` or log files from git; they are runtime state and
must stay writable by the `grannybot.service` user.

Important operational notes:

- Run only one polling bot at a time. If your Windows PC is still running `bot.py`, the Ubuntu server can hit Telegram polling conflicts.
- `grannybot.service` waits for the Ollama API before starting the bot when `LOCAL_QWEN_BACKEND=ollama`.
- If you clone into a different directory or run as a different user, update these lines in `deploy/ubuntu/grannybot.service`:
  - `User=ubuntu`
  - `WorkingDirectory=/opt/grannybot`
  - `EnvironmentFile=/opt/grannybot/.env`
  - `ExecStartPre=/usr/bin/bash /opt/grannybot/deploy/ubuntu/wait_for_ollama.sh /opt/grannybot/.env`
  - `ExecStart=/opt/grannybot/.venv-server/bin/python bot.py`
