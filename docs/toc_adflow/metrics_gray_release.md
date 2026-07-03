# To C 指标体系与灰度发布方案

## 北极星指标

- `D1 首条广告生成完成率`
  - 定义：新用户注册/首次访问后 24h 内，至少完成 1 条视频生成。

## 漏斗指标

1. `create_view`
2. `brief_submitted`
3. `estimate_success`
4. `quick_generate_started`
5. `script_generated`
6. `prompt_generated`
7. `video_generated`
8. `export_clicked`
9. `export_success`
10. `purchase_clicked`
11. `purchase_success`

## 质量指标

- `video_success_rate`（视频成功率）
- `retry_rate`（重试率）
- `insufficient_credits_rate`（余额不足阻断率）
- `mean_time_to_first_preview`（首预览耗时）

## 性能指标

- `TTFV`：提交到首个可见结果（脚本）时间
- `TTVP`：提交到首个视频可播放时间
- `p50/p90/p99`：分步骤耗时（脚本、分镜、视频）

## 已落地埋点接口

- `POST /api/toc/metrics/events`
- `GET /api/toc/metrics/events?limit=100`

当前行为：
- 打印结构化日志 `[ToCMetric] {...}`
- 进程内保留最近 500 条（调试用途）

## 事件命名约定

- 统一前缀：`toc_`
- 动作态：过去式（`_started`、`_viewed`、`_done`、`_failed`）
- 示例：
  - `toc_config_viewed`
  - `toc_quick_estimate`
  - `toc_quick_generate_started`
  - `toc_projects_viewed`

## 灰度发布策略

## 阶段 1（10%）

- 条件：`toc_mode_enabled=true` + 小流量入口
- 目标：验证创建链路可用性与首条完成率
- 门槛：
  - `video_success_rate >= 85%`
  - `D1 首条完成率 >= 25%`

## 阶段 2（30%）

- 优化失败提示、余额拦截文案
- 观察购买转化与留存变化

## 阶段 3（100%）

- 入口默认切到 To C 向导
- 内部面板保留为“专业模式”

## 回滚条件

- 连续 30 分钟 `video_success_rate < 70%`
- 购买页错误率 > 10%
- API p95 延迟较基线上升 > 50%

## 数据治理注意事项

- 不上传 token、密码、邮箱等敏感字段
- 事件属性统一白名单
- 仅记录产品行为，不记录可逆个人隐私
