# AdFlow MCP + Skill 安装指南

适用于 **Hermes Desktop** 或 **Hermes CLI**，连接 VidAU 测试环境体验 AdFlow 广告视频产线（Blueprint 驱动、一次确认 → 全自动出片）。

| 环境 | 地址 |
|------|------|
| 测试服 API / 网页 | https://adflow.vidau.info |
| 正式服 | https://adflow.vidau.ai |
| Skill 远程安装清单 | https://adflow.vidau.info/.well-known/skills/index.json |
| 远程 MCP（推荐） | https://adflow.vidau.info/mcp |
| 代码仓库（GitLab，部署用） | https://gt.superads.cn/vidau/vidau-workflow |
| 代码仓库（GitHub，对外镜像） | https://github.com/vidaudeveloper/vidau-workflow |

---

## 一、配置 MCP（adflow）

AdFlow 提供 **远程 MCP**（与 Creative Agent 相同，Hermes 填 URL 即可，**无需 clone 仓库**）。

### 1.1 在 Hermes 里添加 MCP Server（推荐）

1. 打开 Hermes **右上角设置** → **MCP** → **Add server**
2. **Name** 填：`adflow`
3. JSON 配置如下：

```json
{
  "url": "https://adflow.vidau.info/mcp",
  "enabled": true,
  "connect_timeout": 60,
  "timeout": 300,
  "tools": {
    "prompts": false,
    "resources": false
  }
}
```

4. 点击 **Save server** → **Reload MCP** → 等待 reload 完成 → 关闭配置弹窗

### 1.2 说明

- 测试服 `auth_enabled=false`，**无需 Bearer Token / Cookie**。
- MCP 与网页 API 共用同一后端；业务逻辑在服务器，Hermes 只连 `https://adflow.vidau.info/mcp`。
- 正式服将 URL 改为 `https://adflow.vidau.ai/mcp`（若已部署）。

### 1.3 本地 stdio MCP（可选，开发调试）

仅在本机跑后端、或远程 MCP 不可用时使用：

```powershell
git clone -b test https://github.com/vidaudeveloper/vidau-workflow.git D:\bluetti-material-workflow
cd D:\bluetti-material-workflow\mcp_server
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

Hermes MCP 类型选 **stdio**，`command` 指向 `mcp_server\.venv\Scripts\python.exe`，`args` 为 `server.py`，`env.ADFLOW_BASE_URL` 设为 `https://adflow.vidau.info` 或 `http://127.0.0.1:8787`。

---

## 二、安装 Skill

Skill 告诉 Agent **如何按产线 SOP 调用 MCP 工具**（Blueprint、一次确认、UGC 台词、画布预览等）。

### 2.1 一键安装（推荐）

在 Hermes **新对话**的聊天框发送：

```
https://adflow.vidau.info/.well-known/skills/index.json 查看这个站点的所有 skill 并安装
```

Agent 会拉取清单并安装各 Skill 的 `SKILL.md`。安装完成后建议 **新开一个对话**，确保 Skill 已加载。

### 2.2 手动复制（备选）

```powershell
$src = "D:\bluetti-material-workflow\mcp_server\hermes_skills"
$dst = "$env:LOCALAPPDATA\hermes\skills"
Copy-Item "$src\adflow-blueprint" "$dst\adflow-blueprint" -Recurse -Force
Copy-Item "$src\adflow-copy"     "$dst\adflow-copy"     -Recurse -Force
Copy-Item "$src\adflow-canvas"   "$dst\adflow-canvas"   -Recurse -Force
```

---

## 三、验收测试

### 3.1 MCP 连通

在 Hermes 对话中发送：

```
帮我查一下 AdFlow 健康状态和产品列表
```

Agent 应调用 `health_check`、`list_products` 等工具并正常返回。

### 3.2 一次确认 → 全自动出片（推荐流程）

```
用 PopSmilz 口腔益生菌做一条 15 秒英语 UGC 测试视频：
- 单段 15s、9:16
- Seedance 原生口播，不要后期 TTS
- 字幕 skip
- 痛点快节奏钩子
确认单我看过后说「确认」，请直接跑完全流程，不要再问我「可以开始吗」
```

**预期行为：**

1. `patch_workflow_blueprint` → `get_workflow_confirmation`（**只展示一次**）
2. 用户说 **确认** 后 → `confirm_and_run_production`（锁定 Blueprint + autopilot）
3. **不再**插入脚本 / Prompt 人工审核闸门（默认 `review_mode=autopilot`）
4. 终态汇报 `batch_id` 与成片状态

### 3.3 画布预览（可选）

```
打开 AdFlow 工作流画布，看一下当前批次进度
```

Agent 应调用 `show_workflow_canvas`，并在浏览器预览打开：

`https://adflow.vidau.info/hermes/canvas?batch_id=B...`

### 3.4 命令行自检（运维 / 开发）

```bash
python scripts/verify_deploy.py --url https://adflow.vidau.info --expect-domain adflow.vidau.info
```

通过时应看到：`hermes_skills=3 (vidau-adflow-skills)`。

---

## 四、Skill 清单

| Skill | 层级 | 作用 |
|-------|------|------|
| **adflow-blueprint** | L0 | Blueprint 产线 SOP；**一次确认** → `confirm_and_run_production`；禁止二次确认 |
| **adflow-copy** | L1 | UGC 台词去 AI 味（hook / 口播 / CTA） |
| **adflow-canvas** | L1 | 工作流画布可视化（`show_workflow_canvas` + 浏览器预览） |

远程清单字段示例（`index.json`）：

```json
{
  "package": "vidau-adflow-skills",
  "version": "0.2.0",
  "skills": [
    { "name": "adflow-blueprint", "files": ["SKILL.md"] },
    { "name": "adflow-copy", "files": ["SKILL.md"] },
    { "name": "adflow-canvas", "files": ["SKILL.md"] }
  ]
}
```

各 Skill 正文地址：`https://adflow.vidau.info/.well-known/skills/{name}/SKILL.md`

---

## 五、标准产线流程（Agent 应遵守）

```
用户描述需求（时长 / 音频 / 字幕 / 风格 / 条数）
    ↓
analyze_intake / decompose_reference_video（可选）
    ↓
create_workflow_blueprint + patch_workflow_blueprint
    ↓
get_workflow_confirmation  ← 唯一人工闸门（展示确认单一次）
    ↓
用户: 确认 / OK / 开始
    ↓
confirm_and_run_production  ← 同一轮，禁止再问「可以开始吗？」
    ↓
后端 autopilot：脚本 → 分镜 Prompt → Seedance 出片
    ↓
get_production_board（查一次）→ 交付 video_url
```

**默认禁止（除非用户事先说「我要审脚本」并设置 `review_mode: manual`）：**

- 「可以开始吗？」「脚本可以批准吗？」「Prompt 批准？」
- `create_batch` 不带 `workflow_id`
- `direction=⑤功能解说型` + 长 CSV `extra_instruction` 替代 Blueprint

---

## 六、常见问题

### Reload MCP 后没有 adflow 工具？

- 检查 `command` / `args` 路径是否正确
- 确认 `mcp_server\.venv` 已执行 `pip install -r requirements.txt`
- 查看 Hermes MCP 日志中的启动报错

### `workflow_id is required`？

必须先 `patch_workflow_blueprint` + `get_workflow_confirmation`，用户确认后再 `confirm_and_run_production`，不能裸调 `create_batch`。

### 生成了 30s 脚本而非 15s？

确认 Blueprint 中：

- `video_spec.duration_sec: 15`
- `video_spec.segment_strategy: "single"`
- `production.review_mode: "autopilot"`

并确保测试服代码为最新 `test` 分支。

### `/.well-known/skills/index.json` 或 `/mcp` 返回 404？

测试服尚未部署最新代码。在服务器执行：

```bash
cd /opt/vidau-workflow
GIT_BRANCH=test bash scripts/jenkins_update.sh
# 若 nginx 已改过，重载：sudo nginx -t && sudo systemctl reload nginx
```

自检应看到 `remote_mcp=/mcp (HTTP 400)` — 400 表示端点存在（GET 无 MCP 会话时的正常响应）。

### GitHub clone 后 Gemini 不工作？

GitHub 镜像**不含**真实 `config/gemini-vertex-sa.json`（密钥保护）。本地开发请复制 `config/gemini-vertex-sa.json.example` 并填入测试服提供的 SA，或仅连远程 `adflow.vidau.info` 使用 MCP。

---

## 七、运维：测试服更新

```bash
cd /opt/vidau-workflow
GIT_BRANCH=test bash scripts/jenkins_update.sh
```

等价手动步骤：

```bash
cd /opt/vidau-workflow
git fetch origin && git checkout test && git pull origin test
sudo systemctl restart bluetti-workflow
python scripts/verify_deploy.py --url https://adflow.vidau.info --expect-domain adflow.vidau.info
```

GitLab CI：项目 Pipelines → `test` 分支 → Run pipeline → 手动执行 **deploy_test**。

---

## 八、相关文件（仓库内）

| 路径 | 说明 |
|------|------|
| `mcp_server/server.py` | MCP 工具定义（含 `confirm_and_run_production`） |
| `mcp_server/hermes_skills/` | Skill 源文件 |
| `src/hermes_skills_registry.py` | `/.well-known/skills` 端点实现 |
| `docs/DEPLOY_ADFLOW.md` | 后端部署总览 |
| `mcp_server/hermes_skills/adflow-blueprint/SKILL.md` | Agent 产线 SOP 全文 |

---

*文档版本：与 `test` 分支对齐（Hermes Skill 远程安装 + 一次确认 autopilot）。*
