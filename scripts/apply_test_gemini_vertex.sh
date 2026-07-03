#!/usr/bin/env bash
# 测试服 Vertex Gemini — 在服务器 /opt/vidau-workflow 执行：
#   git pull origin test && bash scripts/apply_test_gemini_vertex.sh
#
# 合并 config/env.vertex.snippet，校验 config/gemini-vertex-sa.json 存在并重启。

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/vidau-workflow}"
SERVICE_NAME="${SERVICE_NAME:-bluetti-workflow}"
ENV_FILE="${APP_DIR}/.env"
SNIPPET="${APP_DIR}/config/env.vertex.snippet"
SA_PATH="${APP_DIR}/config/gemini-vertex-sa.json"
PORT="${WEBHOOK_PORT:-8787}"

cd "$APP_DIR"

if [[ ! -f "$SNIPPET" ]]; then
  echo "错误: 未找到 ${SNIPPET}，请先 git pull origin test"
  exit 1
fi

if [[ ! -f "$SA_PATH" ]]; then
  echo "错误: 未找到 Vertex 服务账号 JSON："
  echo "  ${SA_PATH}"
  echo "请先 git pull origin test（凭据随仓库部署）"
  exit 1
fi

touch "$ENV_FILE"

while IFS= read -r line || [[ -n "$line" ]]; do
  [[ "$line" =~ ^[[:space:]]*# ]] && continue
  [[ -z "${line// }" ]] && continue
  key="${line%%=*}"
  [[ -z "$key" ]] && continue
  if ! grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    echo "$line" >>"$ENV_FILE"
    echo "  + ${key}"
  fi
done <"$SNIPPET"

echo "Vertex SA: ${SA_PATH}"

echo "==> 重启 ${SERVICE_NAME}"
sudo systemctl restart "$SERVICE_NAME"
sleep 2

echo "==> Gemini 自检"
meta="$(curl -fsS "http://127.0.0.1:${PORT}/api/meta")"
echo "$meta" | head -c 800
echo ""

configured="$(echo "$meta" | python3 -c "import sys,json; print(json.load(sys.stdin).get('gemini_configured',False))" 2>/dev/null || true)"
mode="$(echo "$meta" | python3 -c "import sys,json; print(json.load(sys.stdin).get('gemini_mode',''))" 2>/dev/null || true)"
if [[ "$configured" != "True" || "$mode" != "vertex" ]]; then
  echo "错误: gemini_configured=${configured} gemini_mode=${mode}"
  exit 1
fi

echo "完成：Vertex Gemini 已就绪。"
