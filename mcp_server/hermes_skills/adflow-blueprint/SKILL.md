---
name: adflow-blueprint
description: >-
  Drive AdFlow production via Workflow Blueprint — ONE human gate then autopilot.
  Use when the user specifies duration, native audio vs TTS, subtitles, UGC
  viral format, narrative beats, or any per-campaign SOP. Default review_mode
  is autopilot (no script/prompt human gates after confirm).
metadata:
  hermes:
    tags: [adflow, blueprint, workflow, production, intent, 产线, 蓝图]
    related_skills: [adflow-workflow, adflow-copy, adflow-canvas, adflow-intake]
---

# AdFlow — Workflow Blueprint（一次确认 → 全自动）

**核心原则：ONE human gate → autopilot to completion.**

用户在对话里的每一条要求映射到 `Workflow Blueprint` 字段，经 `patch_workflow_blueprint` 写入。
展示确认单 **一次**；用户说 确认/OK/开始/批准 后，**立即**调用 `confirm_and_run_production`，
**禁止**再次询问或插入脚本/分镜人工闸门（除非用户事先明确要求 manual review）。

---

## Phase A — Draft（无 MCP 写入，除 upsert blueprint）

1. **Intake** — `analyze_intake` / `decompose_reference_video`（有参考时）
2. **建草案** — `create_workflow_blueprint` + `patch_workflow_blueprint`（可多次 patch）
3. **展示确认单一次** — `get_workflow_confirmation`（含 review_mode、时长、音频、字幕）

用户未说清 **时长 / 单双段 / 音频 / 字幕** 时 → 先问，再 patch，再展示确认单。
**禁止**用 CSV/四段结构长文塞进 `extra_instruction` 替代 Blueprint 字段。

---

## Phase B — Single gate（唯一人工闸门）

用户说 **确认 / OK / 开始 / 批准**（任意肯定词）→ **同一轮**立即调用：

```
confirm_and_run_production(
  workflow_id=...,
  product=...,
  direction="UGC Campaign",   # 勿填 ⑤功能解说型
  count=...,
  language=...,
)
```

**不要**先 `confirm_workflow_blueprint` 再问「可以开始吗?」。
**不要**拆成 `create_batch` + 手动 `review_script` / `review_prompt`。

---

## 确认后 FORBIDDEN（硬性禁止）

| 禁止行为 | 原因 |
|---------|------|
| 「可以开始吗?」 | 用户已确认 |
| 「脚本审核 — 可以批准吗?」 | review_mode=autopilot 自动过审 |
| 「Prompt 批准?」 | 同上 |
| 连续「稍等」轮询 | 调一次 `get_production_board` 即可 |
| `create_batch` 不带 `workflow_id` | MCP 会拒绝 |
| `direction=⑤功能解说型` + direction_library | 会生成 30s 功能片而非 UGC |
| 长 CSV extra_instruction 替代 Blueprint | 时长/策略必须在 patch 里 |

---

## review_mode（默认 autopilot）

| 模式 | patch | 行为 |
|------|-------|------|
| **autopilot**（默认） | `production.review_mode: "autopilot"` | 脚本/Prompt/视频自动批准，`run_autopilot` 跑完全链 |
| **manual** | `production.review_mode: "manual"` | 仅当用户说「我要审脚本」时在 confirm **之前** patch |

确认单会显示 `审核模式` 与说明：autopilot = 无脚本/分镜人工闸门。

---

## 验证失败（autopilot 内）

- 后端 `run_autopilot` 自动批准脚本与 Prompt；预算违规时 orchestrator 会 **自动 regenerate 一次**（15s 单段）。
- 通过 Blueprint + 口播预算 fix，首次生成应尽量正确：
  - **15s single** → 38–52 英文词，0–15s 单段，无 Part A/B
  - **30s dual** → 55–72 英文词，Part A/B 结构

若 autopilot 仍失败 → 报告 `get_production_board` 一次，请用户决定是否改 Blueprint 重跑。

---

## 硬性门禁（MCP 会拒绝）

1. **禁止** `create_batch` / `run_autopilot` / `confirm_and_run_production` **不带** `workflow_id`
2. Blueprint 含 `direction_library` 时 **禁止** `direction=⑤功能解说型` / `痛点` 等旧目录名
3. **禁止** 无 workflow_id 建批次（会落到默认 30s 模板）

---

## 意图 → Blueprint 字段

### 成片规格 `video_spec`

| 用户说 | patch 字段 |
|--------|-----------|
| 15s / 30s | `duration_sec` |
| 单段 / 双段拼接 | `segment_strategy`: `single` \| `dual` |
| 9:16 竖屏 | `aspect_ratio` |
| 最多 3 镜 | `max_shots` |

### 音频与字幕 `production`

| 用户说 | patch 字段 |
|--------|-----------|
| 原生口播无字幕 | `tts: false`, `subtitles: "skip"`, `seedance_native_audio: true` |
| 原生 + 烧字幕 | `tts: false`, `subtitles: "burn_in"`, `seedance_native_audio: true` |
| 后期 TTS + 字幕 | `tts: true`, `subtitles: "burn_in"`, `seedance_native_audio: false` |
| 我要审脚本 | `review_mode: "manual"`（confirm 前 patch） |

### 创意 / 批量

见 `creative.*`、`batch.direction_library`、`batch.variant_scripts`。
`create_batch.direction` / `confirm_and_run_production.direction` 仅作批次标签 → 用 **`UGC Campaign`**。

---

## patch 示例（PopSmilz 15s 原生 viral）

```json
{
  "video_spec": {
    "duration_sec": 15,
    "segment_strategy": "single",
    "segment_duration_sec": 15,
    "aspect_ratio": "9:16"
  },
  "production": {
    "tts": false,
    "subtitles": "skip",
    "seedance_native_audio": true,
    "ugc_viral_format": true,
    "prompt_format": "viral_15s_blocks",
    "language": "英语",
    "review_mode": "autopilot"
  },
  "creative": {
    "prompt_profile": "ugc_15s",
    "storyboard_profile": "ugc_viral_15s",
    "product_visual_truth": { "hero_product": "NC PopSmilz sachet" },
    "forbidden": ["TikTok logo", "readable burned subtitles"]
  },
  "batch": {
    "direction_library": "config/creative/pop_smilz_15_directions.json",
    "count_per_direction": 4
  }
}
```

---

## MCP 工具速查

| 工具 | 用途 |
|------|------|
| `patch_workflow_blueprint` | **写入用户意图** |
| `get_workflow_confirmation` | 确认单（**展示一次**） |
| **`confirm_and_run_production`** | **用户确认后唯一入口** — confirm + autopilot 原子调用 |
| `confirm_workflow_blueprint` | 仅手动拆步时使用；默认走上面原子工具 |
| `run_autopilot` | 已 confirm 后的 autopilot；优先用原子工具 |
| `create_batch` | 仅 manual review_mode 或用户要逐步审脚本时用 |
| `get_production_board` | 查进度（**一次**，勿 spam） |

---

## 用户流程图

```
用户描述需求
    ↓
analyze_intake / decompose（可选）
    ↓
create_workflow_blueprint + patch（时长/音频/字幕/review_mode）
    ↓
get_workflow_confirmation  ← 唯一展示确认单
    ↓
用户: 确认 / OK / 开始
    ↓
confirm_and_run_production  ← 同一轮，不再询问
    ↓
run_autopilot 后端全自动（脚本→Prompt→出片）
    ↓
get_production_board（查一次）→ 交付 video_url
```

---

## 与 adflow-copy 分工

- **本 Skill**：产线契约、一次确认、autopilot 闸门
- **adflow-copy**：台词去 AI 味（Blueprint 约束下的 hook/口播润色）

先 Blueprint + confirm，再 copy 润色（仅 manual 模式或用户点名时）。
