#!/usr/bin/env bash
# 测试服启用 Seedance 直连出片（覆盖 .env 里 VIDEO_PROVIDER=platform）
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/vidau-workflow}"
SERVICE_NAME="${SERVICE_NAME:-bluetti-workflow}"
ENV_FILE="${APP_DIR}/.env"
SNIPPET="${APP_DIR}/config/env.seedance.snippet"
PORT="${WEBHOOK_PORT:-8787}"
cd "$APP_DIR"
touch "$ENV_FILE"
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ "$line" =~ ^[[:space:]]*# ]] && continue
  [[ -z "${line// }" ]] && continue
  key="${line%%=*}"
  [[ -z "$key" ]] && continue
  if ! grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    echo "$line" >>"$ENV_FILE"
  fi
done <"$SNIPPET"
if grep -q '^VIDEO_PROVIDER=' "$ENV_FILE"; then
  sed -i.bak 's/^VIDEO_PROVIDER=.*/VIDEO_PROVIDER=seedance/' "$ENV_FILE"
else
  echo 'VIDEO_PROVIDER=seedance' >>"$ENV_FILE"
fi
if grep -q '^SEEDANCE_API_KEY=$' "$ENV_FILE" 2>/dev/null || ! grep -q '^SEEDANCE_API_KEY=' "$ENV_FILE"; then
  key="$(grep '^SEEDANCE_API_KEY=' "$SNIPPET" | cut -d= -f2-)"
  if grep -q '^SEEDANCE_API_KEY=' "$ENV_FILE"; then
    sed -i.bak "s|^SEEDANCE_API_KEY=.*|SEEDANCE_API_KEY=${key}|" "$ENV_FILE"
  else
    echo "SEEDANCE_API_KEY=${key}" >>"$ENV_FILE"
  fi
fi
echo "==> VIDEO_PROVIDER / SEEDANCE"
grep -E '^(VIDEO_PROVIDER|SEEDANCE_API_KEY)=' "$ENV_FILE" | sed 's/SEEDANCE_API_KEY=.*/SEEDANCE_API_KEY=***/'
sudo systemctl restart "$SERVICE_NAME"
sleep 2
curl -fsS "http://127.0.0.1:${PORT}/api/meta" | head -c 300 || true
echo ""
echo "完成。排队视频可执行: python scripts/retry_batch_videos.py --batch-id <id>"
