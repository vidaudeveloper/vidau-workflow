#!/usr/bin/env bash
# 将服务器 .env 从旧域名 workflow.vidau.* 迁移到 adflow.vidau.*
# 在服务器执行：
#   cd /opt/vidau-workflow
#   sudo APP_DOMAIN=adflow.vidau.info bash scripts/apply_adflow_domain.sh   # 测试
#   sudo APP_DOMAIN=adflow.vidau.ai bash scripts/apply_adflow_domain.sh     # 正式

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/vidau-workflow}"
ENV_FILE="${APP_DIR}/.env"
SERVICE_NAME="${SERVICE_NAME:-bluetti-workflow}"

if [[ -z "${APP_DOMAIN:-}" ]]; then
  echo "用法: APP_DOMAIN=adflow.vidau.info bash scripts/apply_adflow_domain.sh"
  exit 1
fi

if [[ "$APP_DOMAIN" == *".vidau.info" ]]; then
  PUBLIC_BASE_URL="https://adflow.vidau.info"
elif [[ "$APP_DOMAIN" == *".vidau.ai" ]]; then
  PUBLIC_BASE_URL="https://adflow.vidau.ai"
else
  PUBLIC_BASE_URL="https://${APP_DOMAIN}"
fi

cd "$APP_DIR"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "错误: 未找到 ${ENV_FILE}"
  exit 1
fi

_set_kv() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i.bak "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    echo "${key}=${val}" >>"$ENV_FILE"
  fi
}

_set_kv APP_DOMAIN "$APP_DOMAIN"
_set_kv PUBLIC_BASE_URL "$PUBLIC_BASE_URL"

# 旧 workflow 域名残留替换
sed -i.bak \
  -e 's|workflow\.vidau\.info|adflow.vidau.info|g' \
  -e 's|workflow\.vidau\.ai|adflow.vidau.ai|g' \
  "$ENV_FILE" || true

echo "==> APP_DOMAIN=$(grep '^APP_DOMAIN=' "$ENV_FILE" | tail -1)"
echo "==> PUBLIC_BASE_URL=$(grep '^PUBLIC_BASE_URL=' "$ENV_FILE" | tail -1)"

echo "==> 安装 Nginx 反代（若尚未配置）"
sudo APP_DOMAIN="$APP_DOMAIN" bash scripts/setup_nginx_domain.sh || true

echo "==> 重启 ${SERVICE_NAME}"
sudo systemctl restart "$SERVICE_NAME"
sleep 2

echo "==> 健康检查"
curl -fsS "http://127.0.0.1:${WEBHOOK_PORT:-8787}/api/meta" | head -c 400
echo ""
