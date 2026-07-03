# BLUETTI 素材生产工作流

网页端一站式素材生产：**批量出脚本 → 剪辑审核 → 分镜 Prompt → 审核 → AI 出片 / 人工剪辑**。

## 同事访问地址

**https://adflow.vidau.ai**（正式） · **https://adflow.vidau.info**（测试）  
需 DNS 解析到服务器并完成 Nginx + HTTPS 配置，见下方。

本地开发：**http://127.0.0.1:8787**

## 快速开始

```bash
cd vidau-workflow
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python scripts/run_batch.py serve
```

## 分支与部署

| 分支 | 环境 |
|------|------|
| `test` | 测试服（vidau.info / 测试机） |
| `main` | 正式服（vidau.ai / 生产机） |

研发流程：`feature` → merge **`test`** → 运维部署测试 → 验证后 merge **`main`** → 部署生产。

测试机更新：

```bash
cd /opt/vidau-workflow && GIT_BRANCH=test bash scripts/jenkins_update.sh
```

测试服关闭出片扣费（全员 SSO 可无限测，见 `config/env.staging.snippet`）：

```bash
cd /opt/vidau-workflow && bash scripts/apply_test_billing_none.sh
python scripts/check_test_billing.py --url https://adflow.vidau.info --strict
# 期望 charge_enabled=false
```

### SSO / 主站环境（测试 vs 正式）

正式服与测试服 **域名、API、SSO App ID 不同**；`SSO_ENV` **留空** 时由 `APP_DOMAIN` 自动识别（`adflow.vidau.info` → 测试，`adflow.vidau.ai` → 正式）。

| 文档 / 模板 | 说明 |
|-------------|------|
| [config/sso_env.md](config/sso_env.md) | 变量对照、自动检测规则、排错 |
| [config/env.staging.snippet](config/env.staging.snippet) | 测试服 `.env` 片段 |
| [config/env.production.snippet](config/env.production.snippet) | 正式服 `.env` 片段 |
| [docs/DEPLOY_ADFLOW.md](docs/DEPLOY_ADFLOW.md) | **统一部署**（与 AdFlow 同后端、域名迁移、UGC 产线） |

部署后自检：

```bash
python scripts/verify_deploy.py --url https://adflow.vidau.info --expect-domain adflow.vidau.info
```

## 域名 adflow.vidau.ai / adflow.vidau.info

### 1. DNS

| 环境 | 主机记录 | 值 |
|------|----------|-----|
| 正式 | `adflow.vidau.ai` | 生产服务器公网 IP |
| 测试 | `adflow.vidau.info` | 测试服务器公网 IP |

### 2. 服务器部署

```bash
cd /opt/vidau-workflow
bash scripts/deploy_server.sh
# 编辑 .env（正式参考 config/env.production.snippet，测试参考 config/env.staging.snippet）
sudo APP_DOMAIN=adflow.vidau.ai bash scripts/setup_nginx_domain.sh   # 正式
# 或 sudo APP_DOMAIN=adflow.vidau.info bash scripts/setup_nginx_domain.sh  # 测试
```

云安全组放行：**80、443**（HTTPS）；8787 仅本机 Nginx 反代，可不对外开放。

### 3. 验证

```bash
curl -I https://adflow.vidau.ai/api/meta
# 测试：curl -I https://adflow.vidau.info/api/meta
```

## 项目结构

```
frontend/          # 网页前端
src/app.py         # FastAPI + API
config/nginx/      # adflow.vidau.ai / adflow.vidau.info 反代配置
data/              # SQLite、成片（不进 Git）
```

## Workflow Blueprint（UGC 产线）

- 参考视频拆解 / 多案例风格学习 → 生成可确认的生产蓝图 → 批次出片
- API：`/api/workflows/reference/*`、`/api/workflows/blueprints/*`
- 配置样例：`config/workflows/`、`config/creative/`
- MCP 工具：`mcp_server/server.py`（Hermes 驱动同一后端）

## To C AdFlow 规划落地

- `docs/toc_adflow/mvp_ux_blueprint.md`：MVP 页面蓝图与关键状态
- `docs/toc_adflow/quick_generate_api.md`：To C 语义化 API 契约
- `docs/toc_adflow/billing_funnel.md`：计费拦截点与转化路径
- `docs/toc_adflow/metrics_gray_release.md`：埋点指标与灰度方案
- 前端入口：`/` 为新版快速生成首页；原专业面板保留在 `/pro`
