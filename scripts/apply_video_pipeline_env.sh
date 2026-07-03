#!/usr/bin/env bash
# 写入 TikTok UGC 出片相关 .env（15s 单段 · Seedance 原生音 · 无 TTS 后期）
# 在服务器 /opt/vidau-workflow 执行：
#   bash scripts/apply_video_pipeline_env.sh

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/vidau-workflow}"
ENV_FILE="${APP_DIR}/.env"
SERVICE_NAME="${SERVICE_NAME:-bluetti-workflow}"

declare -A KV=(
  [VIDEO_DEFAULT_DURATION_SEC]=15
  [VIDEO_SEGMENT_STRATEGY]=single
  [SEEDANCE_UGC_STYLE]=true
  [TTS_MUTE_SEEDANCE_AUDIO]=false
  [TTS_POST_ENABLED]=false
  [TTS_FIT_TO_VIDEO_SEC]=15
)

cd "$APP_DIR"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "错误: 未找到 ${ENV_FILE}"
  exit 1
fi

for key in "${!KV[@]}"; do
  val="${KV[$key]}"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i.bak "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    echo "${key}=${val}" >>"$ENV_FILE"
  fi
  echo "  ${key}=${val}"
done

# 按当前域名补全参考素材公网前缀（可选）
domain="$(grep '^APP_DOMAIN=' "$ENV_FILE" | tail -1 | cut -d= -f2-)"
if [[ -n "$domain" ]] && ! grep -q '^SEEDANCE_ASSET_PUBLIC_BASE_URL=.' "$ENV_FILE"; then
  echo "SEEDANCE_ASSET_PUBLIC_BASE_URL=https://${domain}/uploads" >>"$ENV_FILE"
  echo "  SEEDANCE_ASSET_PUBLIC_BASE_URL=https://${domain}/uploads"
fi

echo "==> 重启 ${SERVICE_NAME}"
sudo systemctl restart "$SERVICE_NAME"
sleep 2
echo "完成。"
