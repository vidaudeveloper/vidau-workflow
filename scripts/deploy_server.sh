#!/usr/bin/env bash
# Linux 服务器一键部署 / 更新 — 在服务器上执行：
#   curl -fsSL https://gt.superads.cn/vidau/vidau-workflow/-/raw/main/scripts/deploy_server.sh | bash
# 或克隆后：
#   cd /opt/vidau-workflow && bash scripts/deploy_server.sh

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/vidau-workflow}"
REPO_URL="${REPO_URL:-https://gt.superads.cn/vidau/vidau-workflow.git}"
SERVICE_NAME="${SERVICE_NAME:-bluetti-workflow}"
PORT="${WEBHOOK_PORT:-8787}"

echo "==> 安装系统依赖 (python3, venv, git, ffmpeg)..."
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y python3 python3-venv python3-pip git ffmpeg
elif command -v yum >/dev/null 2>&1; then
  sudo yum install -y python3 python3-pip git ffmpeg
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "错误: 未找到 ffmpeg，请先安装"
  exit 1
fi

echo "==> 拉取代码 -> ${APP_DIR}"
sudo mkdir -p "$(dirname "$APP_DIR")"
if [[ -d "$APP_DIR/.git" ]]; then
  sudo git -C "$APP_DIR" pull
else
  sudo git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -U pip
pip install -q -r requirements.txt
python scripts/setup_workflow.py init-db

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo ""
  echo "!!! 请先编辑 ${APP_DIR}/.env 填入 GEMINI_API_KEY、SEEDANCE_API_KEY"
  echo "    并设置 WEBHOOK_HOST=0.0.0.0  WEBHOOK_PORT=${PORT}"
  echo "    nano ${APP_DIR}/.env"
  echo ""
fi

echo "==> 写入 systemd 服务 ${SERVICE_NAME}"
sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<EOF
[Unit]
Description=BLUETTI / VidAU Material Workflow
After=network.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
Environment=PATH=${APP_DIR}/.venv/bin
ExecStart=${APP_DIR}/.venv/bin/python scripts/run_batch.py serve --host 0.0.0.0 --port ${PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"
sleep 2
sudo systemctl status "${SERVICE_NAME}" --no-pager || true

echo ""
echo "==> 本机探测 http://127.0.0.1:${PORT}/"
if curl -fsS -o /dev/null -w "HTTP %{http_code}\n" "http://127.0.0.1:${PORT}/api/meta"; then
  echo "服务已启动。配置域名: sudo bash scripts/setup_nginx_domain.sh"
  echo "DNS: adflow.vidau.ai（正式）或 adflow.vidau.info（测试）→ 本机公网 IP"
else
  echo "本机仍无法访问，查看日志: sudo journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
  exit 1
fi
