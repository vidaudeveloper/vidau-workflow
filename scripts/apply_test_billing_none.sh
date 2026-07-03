#!/usr/bin/env bash
# 测试服关闭主站扣币 — 在服务器 /opt/vidau-workflow 执行：
#   bash scripts/apply_test_billing_none.sh
#
# 将 AIGC_BILLING_MODE 设为 none 并重启服务；出片仍可用，但不走 Agent deduct。

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/vidau-workflow}"
SERVICE_NAME="${SERVICE_NAME:-bluetti-workflow}"
ENV_FILE="${APP_DIR}/.env"

cd "$APP_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "错误: 未找到 ${ENV_FILE}"
  exit 1
fi

if grep -q '^AIGC_BILLING_MODE=' "$ENV_FILE"; then
  sed -i.bak 's/^AIGC_BILLING_MODE=.*/AIGC_BILLING_MODE=none/' "$ENV_FILE"
else
  echo 'AIGC_BILLING_MODE=none' >>"$ENV_FILE"
fi

echo "==> 已设置 AIGC_BILLING_MODE=none"
grep '^AIGC_BILLING_MODE=' "$ENV_FILE" || true

echo "==> 重启 ${SERVICE_NAME}"
sudo systemctl restart "$SERVICE_NAME"
sleep 2

echo "==> 健康检查"
curl -fsS "http://127.0.0.1:${WEBHOOK_PORT:-8787}/api/meta" | head -c 500 || true
echo ""

if [[ -x "${APP_DIR}/.venv/bin/python" ]]; then
  echo "==> 免扣费自检"
  "${APP_DIR}/.venv/bin/python" "${APP_DIR}/scripts/check_test_billing.py" \
    --env-file "$ENV_FILE" \
    --url "http://127.0.0.1:${WEBHOOK_PORT:-8787}" \
    --strict
fi

echo ""
echo "完成。"
echo "  - billing.charge_enabled 应为 false（出片不扣主站积分）"
echo "  - billing.enabled 仍可能为 true（SSO 登录会显示积分/购买入口，属正常）"
