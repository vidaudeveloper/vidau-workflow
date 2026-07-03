# VidAU SSO / 主站环境对照

Flow 素材工作流（Python/FastAPI）与 Next.js Agent 项目**变量名不同**，但对接同一套 SSO 与主站 API。部署时按 **测试 / 正式** 两套配置，勿混用。

## 环境一览

| 项目 | 测试服 | 正式服 |
|------|--------|--------|
| Git 分支 | `test` | `main` |
| 站点域名 | `adflow.vidau.info` | `adflow.vidau.ai` |
| SSO App ID | `ad-flow-agent-test`（Ad Flow Agent Test） | `ad-flow-agent`（Ad Flow Agent） |
| SSO 环境 | `development`（自动） | `production`（自动） |
| SSO 服务 | `https://sso.vidau.info` | `https://sso.vidau.ai` |
| 主站 API | `https://app-api.vidau.info/api` | `https://app-api.vidau.ai/api` |
| 购买页 | `https://www.vidau.ai/agent-price?agent_code=vidau_flow` | 同左 |

**`SSO_ENV` 默认留空**，由 `APP_DOMAIN` / `PUBLIC_BASE_URL` 自动识别；仅特殊场景（本地 hosts 模拟等）才手动写 `SSO_ENV=production|development`。

## 本仓库 .env 模板

- 测试：`config/env.staging.snippet`
- 正式：`config/env.production.snippet`

合并到服务器 `/opt/vidau-workflow/.env` 后执行：

```bash
sudo systemctl restart bluetti-workflow
curl -s http://127.0.0.1:8787/api/auth/sso/config
```

应看到 `"env":"development"` 或 `"env":"production"`，且 `sdk_url` 指向对应 SSO 域名。

## 与同事 Next.js 配置对照

同事 Agent（Next.js）示例：

```env
NEXT_PUBLIC_VIDAU_SSO_APP_ID=ad-flow-agent
VIDAU_SSO_VERIFY_URL=https://sso.vidau.ai/api/sso/verify-token
VIDAU_APP_API_BASE_URL=https://app-api.vidau.ai
VIDAU_COIN_API_BASE_URL=https://app-api.vidau.ai
VIDAU_COIN_API_KEY=sk-agent-...
BILLING_ENABLED=true
```

本仓库（Python）等价配置：

| Next.js / 同事 | 本仓库 `.env` |
|----------------|---------------|
| `NEXT_PUBLIC_VIDAU_SSO_APP_ID` | `SSO_APP_ID` |
| SSO 域名（从 `VIDAU_SSO_VERIFY_URL` 提取） | `SSO_ENV` 留空 + `APP_DOMAIN=adflow.vidau.ai`，或 `SSO_BASE_URL=https://sso.vidau.ai` |
| `VIDAU_APP_API_BASE_URL` | `PLATFORM_API_URL=https://app-api.vidau.ai/api`（**须带 `/api` 后缀**） |
| `VIDAU_COIN_API_KEY` | `AGENT_COIN_API_KEY` |
| `BILLING_ENABLED=true` | `AIGC_BILLING_MODE=platform` |

### 校验接口差异

- Next 项目常用：`POST {sso}/api/sso/verify-token`
- **本仓库服务端**：`POST {sso}/api/sso/user-info`（Header 带 Token，与 SSO SDK 一致）

两者同属 SSO 服务，本仓库已固定 `user-info`，无需配置 `VIDAU_SSO_VERIFY_URL`。

## 自动检测规则（`SSO_ENV` 留空时，默认推荐）

1. `.env` 中 **`SSO_ENV` 留空**（或注释掉），按 `APP_DOMAIN` / `PUBLIC_BASE_URL` 主机名：
   - 含 `vidau.info`（如 `adflow.vidau.info`）→ `development` → `https://sso.vidau.info`
   - 含 `vidau.ai`（如 `adflow.vidau.ai`）→ `production` → `https://sso.vidau.ai`
2. 若写了 `SSO_ENV=production|development`（或 `prod` / `dev`），**以显式值为准**。

## 常见问题

**`/api/auth/sso/config` 返回 `enabled:false`**

- 运行 `python scripts/check_sso_config.py` 查看 `disabled_reason`
- 常见原因：`.env` 里 `AUTH_MODE=local`（覆盖了 internal.env），或未配置 `SSO_APP_ID`
- 正式服 `.env` 必须含 `AUTH_MODE=platform` + `SSO_APP_ID=ad-flow-agent`（见 `config/env.production.snippet`）

**登录弹窗连错环境（生产站连到 sso.vidau.info）**

- 检查 `APP_DOMAIN` 是否误配为 `adflow.vidau.info`（测试域名）。
- 或 `.env` 是否仍写 `SSO_ENV=development`；删掉该行留空即可（生产域名会自动走 production）。

**`/api/auth/sso/callback` 401**

- 确认 `SSO_APP_ID` 与当前 SSO 环境一致（测试/生产 UUID 可能不同）。
- 确认 `PLATFORM_API_URL` 与 SSO 同属测试或生产，勿 `.info` API + `.ai` SSO 混配。

**购买页 agent 不存在**

- 确认 `AGENT_CODE=vidau_flow`，并联系 @彭悠 在主站上架对应 agent 套餐。
