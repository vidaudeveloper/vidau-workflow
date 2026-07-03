# To C 快速生成 API 语义层

目标：在不破坏现有 `/api/batches/*` 内部流程的前提下，提供 To C 友好的语义化接口。

## 已落地端点

## 1) 获取 To C 入口配置

- `GET /api/toc/config`
- 用途：前端决定是否展示 To C 向导入口

响应示例：

```json
{
  "enabled": false,
  "default_language": "英语",
  "metrics_enabled": true,
  "journey": "brief_or_url_to_first_ad",
  "cta": "创建第一条广告"
}
```

## 2) 生成前积分估算

- `POST /api/toc/quick-generate/estimate`
- 优先调用主站 `getTaskCost`，失败时降级返回经验区间

请求示例：

```json
{
  "brief": "做一条便携储能产品15秒广告",
  "duration_sec": 15,
  "ratio": "9:16",
  "resolution": "1080p",
  "model_name": "happyhorse_1.0"
}
```

响应示例：

```json
{
  "currency": "credits",
  "estimated_credits": 305.0,
  "range": [305.0, 305.0],
  "provider": "platform",
  "fallback": false
}
```

降级示例：

```json
{
  "currency": "credits",
  "estimated_credits": null,
  "range": [300, 650],
  "provider": "seedance",
  "fallback": true
}
```

## 3) 一句话快速生成（语义化入口）

- `POST /api/toc/quick-generate`
- 语义：`brief/url -> 自动创建批次 -> autopilot 跑通脚本/分镜/视频`
- 底层复用：`prepare_batch + run_full_autopilot`

请求示例：

```json
{
  "brief": "为便携储能电源生成一条户外露营广告，风格真实自然",
  "source_url": "https://example.com/product",
  "product": "",
  "direction": "",
  "language": "英语",
  "count": 1,
  "use_first_frame": true
}
```

响应示例：

```json
{
  "batch_id": "a1b2c3d4",
  "queued": true,
  "autopilot": true,
  "next": {
    "batches": "/api/batches",
    "scripts": "/api/scripts?batch_id=a1b2c3d4",
    "videos": "/api/videos"
  }
}
```

## 4) To C 最近项目摘要

- `GET /api/toc/projects?limit=20`
- 语义：聚合批次、脚本、分镜、视频完成度，用于工作区卡片展示

响应示例：

```json
{
  "items": [
    {
      "batch_id": "a1b2c3d4",
      "title": "Elite 300 · ⑤功能解说型",
      "status": "生成中",
      "created_at": "2026-06-24T03:00:00+00:00",
      "script_total": 1,
      "prompt_passed": 1,
      "video_done": 0
    }
  ]
}
```

## 5) To C 埋点入口（灰度版）

- `POST /api/toc/metrics/events`
- `GET /api/toc/metrics/events?limit=100`
- 当前仅日志与进程内缓冲，后续可无缝迁移到外部埋点平台。

## 字段映射（To C -> 现有内部管线）

- `brief` -> `extra_instruction`
- `source_url` -> `extra_instruction` 附加上下文
- `product/direction`（可空）-> 自动兜底到首个配置项
- `count`（默认 1）-> batch 数量
- `use_first_frame` -> 一致透传

## 兼容策略

- 不改已有内部 API 契约，新增 `/api/toc/*` 路由作为语义层。
- 前端可以渐进切换：新用户走 `/api/toc/*`，高级用户仍用原面板 API。
