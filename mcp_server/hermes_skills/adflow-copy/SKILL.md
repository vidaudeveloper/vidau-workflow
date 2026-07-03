---
name: adflow-copy
description: >-
  Write natural, scroll-stopping UGC ad voiceover and hooks — de-AI copy for
  TikTok-style scripts. Use when the user asks for 台词/文案/口播/种草/去AI味,
  when reviewing scripts sound robotic, or before approve/regenerate on UGC
  campaigns. Always read Workflow Blueprint constraints first (adflow-blueprint).
metadata:
  hermes:
    tags: [adflow, copy, script, ugc, 台词, 种草]
    related_skills: [adflow-blueprint, adflow-review, adflow-workflow, adflow-intake]
---

# AdFlow — 自然 UGC 台词（去 AI 味）

你是**真人创作者的第一人称口播**，不是品牌宣传片撰稿人。目标：观众 2 秒内信
「这是真人在分享」，愿意看完并点链接。

**产线规则不写死在本 Skill。** 先用 `get_workflow_blueprint` / 确认单读取：
`creative.narrative_rule`、`product_visual_truth`、`forbidden`、`beat_structure`。
台词必须服从 Blueprint；本 Skill 只负责「像真人」。

## 什么时候用本 Skill

- 写/改脚本口播、`hook`、`cta`、`audio` 字段
- 客户说「AI 味重」「不自然」「要像种草」
- `review_script` 之前做台词自检
- `regenerate` 时写 **可执行的 note**（本 Skill 末尾有模板）

---

## 什么是「AI 味」（出现任一条就要改）

| AI 味 | 自然 UGC |
|-------|----------|
| 开场 "Hey guys!" / "In today's video" | 直接从尴尬瞬间切入 |
| 排比三连 "It's amazing, incredible, life-changing" | 一个具体感受 + 一个具体场景 |
| 堆砌全部卖点（CFU、3 strains、sugar-free、PE0301 一句塞完） | **本场景最相关的 2–3 个卖点** |
| 医学广告腔 "clinically proven to eliminate halitosis" | 口语 "my breath was gross" / "mouth felt stale" |
| 爆米花/糖果类比（popping candy, like popcorn） | micro-encapsulated powder, strawberry crunch |
| 无场景的空洞 CTA "Link in bio don't miss out!!!" | 场景收束 + 一句轻催促 |
| 每句长度一样、韵脚整齐 | 长短句交错，有口语停顿感 |
| 第三人称说明书 "This product features..." | 第一人称 "I keep this in my bag" |

---

## 写作顺序（自然种草节拍）

**先场景，后产品。** 不要先念说明书。

```
1. 我正在哪、发生什么（1 句，具体）
2. 口腔/口气尴尬（可感知：stuffy, dry, stale, embarrassed）
3. （可选）同伴/环境反应 — 委婉，不狗血
4. 我怎么做 — 自然拿出条包，不是硬广转身
5. 边用边讲 2–3 个卖点（和场景强相关）
6. 用后的变化 — 自信近距离说话 / 摘口罩 / 下车见客户
7. 轻 CTA — 像推荐给同类人，不要播音腔
```

**产品动作与禁忌** 从 Blueprint `product_visual_truth` / `forbidden` 读取
（例如 tear_method、appearance_notes），不要假设固定品牌或固定撕包方式。

---

## Subject 口播句式（推荐）

客户认可的格式：每句以 **具体处境** 开头，不是形容词堆砌。

```
Subject: [处境] + [我怎么做] + [一个卖点或感受].
```

**好例子（口罩通勤）：**

```
Wearing a mask all day makes my mouth stuffy and smelly.
I use NC PopSmilz daily on commute days.
Three clinical strains target bacteria that build up under masks.
Sugar-free strawberry taste — no weird chemical aftertaste.
Finally fresh again after hours in a mask.
Commuters — keep a pack in your bag.
```

**好例子（聚会紧张）：**

```
Nervous at parties and my mouth goes dry and stale.
I slip NC PopSmilz — nobody notices the single pack.
PE0301 helps when stress dries my mouth out.
Now I actually enjoy talking up close.
```

---

## 15s 词数预算

- 英文口播合计 **40–55 words**（约 12–15 秒自然语速）
- 每句 **6–14 words**；最多 **5–6 句**
- 超过 60 words ⇒ 必删一句卖点或缩短 CTA

---

## 写完后自检（朗读测试）

大声读一遍。若出现以下情况 ⇒ 重写：

1. 读出来像电视广告，不像发朋友圈
2. 有两句可以删掉而不影响故事
3. 听众不知道发生在什么场景
4. 产品名第一次出现太晚（应在尴尬后 5 秒内）
5. 卖点和场景无关（聚会场景却大讲开车）

---

## 与 MCP 配合

### 生成前

1. 用户确认 Blueprint 后走 `confirm_and_run_production`（见 **adflow-blueprint**）；manual 模式才逐步 `review_script`
2. 台词级补充可写入 `create_batch.extra_instruction` 或
   `patch_workflow_blueprint` → `creative.acceptance_points`

```text
自然种草 UGC 口播；第一人称 Subject 句式；去 AI 味；
场景：[从 Blueprint narrative_rule / 变体方向取]；
遵守 creative.forbidden；
按本 Skill 词数预算。
```

### 审核时

用 **adflow-review** + 本 Skill。若 AI 味 ⇒ `review_script(action=regenerate)`.

### regenerate note 模板（直接粘贴改括号）

```text
Rewrite VO to natural first-person UGC (adflow-copy skill):
- Scene: [具体场景]
- Open with embarrassment: [stale/dry/stuffy breath], not "hey guys"
- 4-5 Subject lines, 40-55 words total
- Only 2-3 selling points relevant to this scene: [列举]
- Product interaction per Blueprint product_visual_truth (NOT generic candy/popcorn analogies)
- End: light CTA for commuters/party people/travelers
- Ban: TikTok logo on screen, medical ad tone, feature list dump
```

---

## 黄金参考（示例 — 应写入 Blueprint 而非代码默认）

客户曾认可的 oral-probiotic UGC 方向可作为 `batch.direction_library` 或
`variant_scripts` 内容，例如口罩通勤 / 聚会紧张 / 车程 / 重口尴尬。
完整 Subject 句可参考 `docs/creative/pop_smilz_feedback_20260701.md`，
**开批前须 patch 进 Blueprint**。

---

## 时长 A/B 提示

- **15s 单段**：上面词数预算，一个场景一个故事
- **30s 双段**：Part A 停在上半悬念（还没完全解决）；Part B 产品演示 + 全卖点 + CTA
- 客户测投放时：一半 15s、一半 30s+，文案结构相同，节拍按时长拉伸

---

## 不要做的事

- 不要只给用户表格总结台词 — 给出 **可直接拍的 Subject 列表**
- 不要在未读 `get_script` 的情况下笼统说「挺好的」
- 不要用 regenerate 而不写具体改哪一句
