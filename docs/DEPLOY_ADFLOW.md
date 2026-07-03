# AdFlow 后端统一部署指南

本仓库 **即 AdFlow 后端**（FastAPI `8787`），与网页 `adflow.vidau.ai` / `adflow.vidau.info` 共用同一服务，systemd 单元名 `bluetti-workflow`，服务器目录 `/opt/vidau-workflow`。

## 架构

```
浏览器 / Hermes MCP
       ↓ HTTPS
Nginx (adflow.vidau.*) → 127.0.0.1:8787
       ↓
bluetti-workflow (python scripts/run_batch.py serve)
       ↓
SQLite + Seedance / 主站出片 + Gemini
```

MCP 薄封装在 `mcp_server/`（Hermes 通过 HTTP 调本后端，不重复业务逻辑）。

## 分支与环境

| 分支 | 域名 | 服务器 |
|------|------|--------|
| `test` | https://adflow.vidau.info | 测试机 |
| `main` | https://adflow.vidau.ai | 生产 `35.187.225.132` |

## 日常更新（已有部署）

```bash
cd /opt/vidau-workflow
GIT_BRANCH=test bash scripts/jenkins_update.sh    # 测试
# GIT_BRANCH=main bash scripts/jenkins_update.sh  # 正式
```

Jenkins / GitLab CI 等价：SSH 到目标机执行上述脚本。

## 首次部署

```bash
sudo git clone https://gt.superads.cn/vidau/vidau-workflow.git /opt/vidau-workflow
cd /opt/vidau-workflow
bash scripts/deploy_server.sh
# 合并 config/env.staging.snippet 或 config/env.production.snippet 到 .env
nano .env   # GEMINI / SEEDANCE / AGENT_COIN_API_KEY 等
sudo APP_DOMAIN=adflow.vidau.info bash scripts/setup_nginx_domain.sh
```

## 从旧域名 workflow.vidau.* 迁移

若 `/api/meta` 里 `app_domain` 仍为 `workflow.vidau.info`：

```bash
cd /opt/vidau-workflow
sudo APP_DOMAIN=adflow.vidau.info bash scripts/apply_adflow_domain.sh
bash scripts/apply_video_pipeline_env.sh
GIT_BRANCH=test bash scripts/jenkins_update.sh
python scripts/verify_deploy.py --url https://adflow.vidau.info --expect-domain adflow.vidau.info
```

## UGC 产线环境变量

测试/生产片段见 `config/env.staging.snippet`、`config/env.production.snippet`。核心项：

| 变量 | 推荐值 | 说明 |
|------|--------|------|
| `VIDEO_DEFAULT_DURATION_SEC` | `15` | 单条 15 秒 |
| `VIDEO_SEGMENT_STRATEGY` | `single` | 单段出片 |
| `SEEDANCE_UGC_STYLE` | `true` | TikTok 快节奏 UGC |
| `TTS_MUTE_SEEDANCE_AUDIO` | `false` | 保留 Seedance 原生配音 |
| `TTS_POST_ENABLED` | `false` | 不做 Edge TTS 后期 |
| `SEEDANCE_ASSET_PUBLIC_BASE_URL` | `https://adflow.vidau.*/uploads` | 参考视频公网 URL 前缀 |

一键写入：`bash scripts/apply_video_pipeline_env.sh`

## 新增 API（Workflow Blueprint）

部署后应可访问（需 SSO 登录，未登录返回 401 而非 404）：

- `POST /api/workflows/reference/decompose` — 参考视频结构化拆解
- `POST /api/workflows/reference/learn-style` — 多案例 UGC 风格学习
- `POST /api/workflows/blueprints/from-decomposition` — 从拆解生成蓝图
- `GET/PATCH /api/workflows/blueprints/{id}` — 蓝图读写
- `POST /api/workflows/blueprints/{id}/confirm` — 生产确认闸门
- `POST /api/videos/{id}/burn-subtitles` — 后期烧录字幕

自检：

```bash
python scripts/verify_deploy.py --url https://adflow.vidau.info --expect-domain adflow.vidau.info
```

## MCP（Hermes）

**远程（推荐）** — Hermes 配置 URL，无需本机 Python：

```json
{
  "url": "https://adflow.vidau.info/mcp",
  "enabled": true,
  "connect_timeout": 60,
  "timeout": 300
}
```

与 Skill 远程安装（`/.well-known/skills/index.json`）配套使用。Nginx 需对 `/mcp` 关闭 `proxy_buffering`（见 `config/nginx/adflow.vidau.info.conf`）。

**本地 stdio**（开发）：

```bash
cd mcp_server && pip install -r requirements.txt
export ADFLOW_BASE_URL=https://adflow.vidau.info
python server.py
```

### Hermes 里看 Workflow 画布

| 方式 | 说明 |
|------|------|
| MCP 工具 `show_workflow_canvas` | 返回 `preview_url`、Mermaid、SVG 链接 |
| MCP 工具 `get_workflow_canvas` | 返回节点 JSON 状态 |
| 浏览器 | http://127.0.0.1:8787/hermes/canvas?batch_id=批次ID（自动刷新） |
| MCP Resource | `adflow://canvas/{batch_id}` → SVG 快照 |

在 Hermes 对话里让 Agent 调用 `show_workflow_canvas`，然后打开返回的 `preview_url` 即可看到与网页相同的节点流图。

## 测试服免扣费

```bash
bash scripts/apply_test_billing_none.sh
python scripts/check_test_billing.py --url https://adflow.vidau.info --strict
```
