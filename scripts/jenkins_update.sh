#!/usr/bin/env bash
# 在服务器上执行：日常 pull + 依赖 + 迁移 + 重启
#   cd /opt/vidau-workflow && bash scripts/jenkins_update.sh
# Jenkins 通过 SSH 远程调用此脚本。

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/vidau-workflow}"
GIT_BRANCH="${GIT_BRANCH:-main}"
SERVICE_NAME="${SERVICE_NAME:-bluetti-workflow}"
PORT="${WEBHOOK_PORT:-8787}"

cd "$APP_DIR"

if [[ ! -d .git ]]; then
  echo "错误: ${APP_DIR} 不是 git 仓库，请先运行 scripts/deploy_server.sh 做首次部署"
  exit 1
fi

echo "==> 拉取 origin/${GIT_BRANCH}"
git fetch origin
git checkout "$GIT_BRANCH"
git pull origin "$GIT_BRANCH"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -U pip
pip install -q -r requirements.txt
python scripts/setup_workflow.py init-db

echo "==> 重启 ${SERVICE_NAME}"
sudo systemctl restart "$SERVICE_NAME"
sleep 2

echo "==> 健康检查"
if curl -fsS "http://127.0.0.1:${PORT}/api/meta" | head -c 400; then
  echo ""
  if [[ "${GIT_BRANCH}" == "test" ]]; then
    echo "==> 测试服免扣费检查（AIGC_BILLING_MODE=none）"
    if ! python scripts/check_test_billing.py --env-file "${APP_DIR}/.env" --url "http://127.0.0.1:${PORT}" --strict; then
      echo ""
      echo "提示: 测试服应关闭出片扣费，请执行:"
      echo "  cd ${APP_DIR} && bash scripts/apply_test_billing_none.sh"
      exit 1
    fi
    echo "==> 测试服 Vertex Gemini 检查"
    gemini_ok="$(python3 -c "
import json, urllib.request
d = json.load(urllib.request.urlopen('http://127.0.0.1:${PORT}/api/meta', timeout=10))
print('1' if d.get('gemini_configured') and d.get('gemini_mode') == 'vertex' else '0')
" 2>/dev/null || echo 0)"
    if [[ "$gemini_ok" != "1" ]]; then
      echo "错误: Vertex Gemini 未就绪（gemini_configured 或 gemini_mode 异常）"
      echo "  请执行: cd ${APP_DIR} && git pull origin test && bash scripts/apply_test_gemini_vertex.sh"
      exit 1
    fi
  fi
  echo "Deploy OK"
else
  echo "错误: 服务未响应，查看日志: sudo journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
  exit 1
fi
