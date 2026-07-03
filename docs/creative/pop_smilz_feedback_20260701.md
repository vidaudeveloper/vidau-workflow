# PopSmilz 客户反馈整理（秋 · 2026-07-01）

来源：微信群（刘雨琪 ↔ 秋）

## 投放策略

| 项 | 要求 |
|----|------|
| 时长 A/B | **一半 >30s，一半 15s**，对比流量与花费是否值得 |
| 本批数量 | 先发 **4 条** 看效果 |

## 画面与合规

- **禁止出现 TikTok / TK 平台标志**（画面、贴纸、水印）
- **粉末质感**以实拍为准：淡粉白微胶囊粉末；与「爆米花」类文案/画面**无关**
- 产品材质前后一致，勿 AI 乱改粉质

## 文案问题（需避免）

- AI 味重、不自然
- 卖点与场景脱节
- 不要用爆米花式比喻

## 推荐叙事（自然种草）

```
重口/尴尬食物或场景口气
  → 同伴委婉指出异味（可选）
  → 自然拿出自用产品，讲全卖点
  → 食用后口气完全消失
  → 近距离自信交谈
```

结合**具体场景**，不要空泛堆砌卖点。

## 优质案例（秋提供 · 可作方向 1–3）

### 方向 1 · 戴口罩通勤
金发欧美女主长时间戴口罩，口腔闷热异味；摘口罩后使用 NC PopSmilz。

口播参考（Subject）：
1. Wearing a mask all day makes my mouth stuffy and smelly. I use NC PopSmilz daily for commute days.
2. Three clinical probiotic strains target bacteria under masks and keep oral balance.
3. Sugar-free crispy strawberry texture, no weird chemical aftertaste.
4. Finally breathe fresh after long mask hours.
5. Commuters, must-buy for daily trip.

### 方向 2 · 社交聚会紧张
温柔金发女主聚会紧张口干口臭，不敢近距离聊；悄悄用条包。

### 方向 3 · 长途车程出差
干练金发女主密闭车程口干厚重异味，到站前快速清新。

### 方向 4 · 重口食物尴尬（模板）
食用重口食物口气尴尬 → 同伴委婉指出 → 自然讲全卖点 → 口气消失 → 自信交谈。

## 产线配置对应

| 配置 | 路径 |
|------|------|
| 脚本 Prompt | `config/prompts/script_system_pop_smilz.txt` |
| 方向 1–4 | `config/creative/pop_smilz_15_directions.json`（已更新前 4 条） |
| Seedance 禁 TK 标 | `src/pipeline/video.py` negative prompt |
| 批次说明 | 补充指令注明 `15s` 或 `30s dual` |

## 下一批建议

```text
产品: PopSmilz Oral Probiotics
数量: 4
变体 1-4 对应秋的方向 1-4
变体 1-2: VIDEO_SEGMENT_STRATEGY=single, 15s
变体 3-4: dual 或 30s（按 A/B 测）
补充: 自然种草；禁止 TK 标志；粉末微胶囊；禁止 popcorn 文案
```
