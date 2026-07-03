#!/usr/bin/env bash
# 绑定域名 adflow.vidau.ai / adflow.vidau.info（需 DNS 已解析到本机）
# 用法：sudo bash scripts/setup_nginx_domain.sh
# 或：  sudo APP_DOMAIN=adflow.vidau.ai bash scripts/setup_nginx_domain.sh

set -euo pipefail

DOMAIN="${APP_DOMAIN:-adflow.vidau.ai}"
APP_PORT="${WEBHOOK_PORT:-8787}"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
NGINX_TEMPLATE="${ROOT_DIR}/config/nginx/${DOMAIN}.conf"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "请使用 sudo 运行"
  exit 1
fi

if [[ ! -f "${NGINX_TEMPLATE}" ]]; then
  echo "错误: 未找到 Nginx 模板 ${NGINX_TEMPLATE}"
  echo "请在 config/nginx/ 下创建 ${DOMAIN}.conf"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y nginx certbot python3-certbot-nginx

if ! curl -fsS "http://127.0.0.1:${APP_PORT}/api/meta" >/dev/null; then
  echo "错误: 本机 ${APP_PORT} 无服务，请先启动 bluetti-workflow"
  exit 1
fi

cp "${NGINX_TEMPLATE}" "/etc/nginx/sites-available/${DOMAIN}.conf"
ln -sf "/etc/nginx/sites-available/${DOMAIN}.conf" "/etc/nginx/sites-enabled/${DOMAIN}.conf"
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl enable nginx
systemctl reload nginx

echo "==> 申请 HTTPS 证书（按提示输入邮箱并同意条款）"
certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos --register-unsafely-without-email || \
  certbot --nginx -d "${DOMAIN}"

echo ""
echo "完成。同事访问: https://${DOMAIN}"
