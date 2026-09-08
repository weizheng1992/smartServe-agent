---
id: "003"
title: engine vision 模块(移植+改良)
map: multimodal-image-chat
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: ""
status: open
blocked-by: ["001"]
blocks: ["005"]
created: 2026-09-08
---

## Question

把 TS 的 `visionAnalyzerService`(commit `f71f7fa`,树 `b75fb78^`,`packages/engine/src/vision/visionAnalyzerService.ts`)移植为 `engine_py/vision/`,挂进 triage Step 0.5(TODO 位:`triage/intent_triage_engine.py:219-224`),产出 `state.damage_assessment`(消费方 `cards/card_synthesizer.py:79-83` 已就位)。

**继承 TS 设计**:OCR 单号正则(ORD-/SF/YTO/ZTO/EMS/TRACK)、破损 3 级定责(negligible/minor/severe)、启发式正则快速通道作 LLM 失败兜底(纯函数,易移植)、PII 脱敏切面(复用 `tools_registry/scrubber.py` 口径)、prompt 任务定义与 `suggestedAction` 枚举。

**改良 TS 缺陷**(考古裁决):

- 手写 ```json 围栏剥离 → Pydantic `with_structured_output`(**method="function_calling"**;001 裁决:`response_format` 仅文本模型/GLM-5.3-Flash 支持,GLM-4.6V 走 tools 取参)。
- 1500ms reject 超时(真实多模态必降级)→ 可配置超时(默认放宽到秒级)+ 失败保留启发式部分结果。
- `DamageAssessmentData` 字段名**不动**(契约钉死,见地图 Notes)。
- 视觉模型按 001 结论接入(独立模型配置,不复用文本 `get_chat_model()` 的模型名)。

**验收**:单测双分支(LLM 成功出结构化结果 / 超时降级启发式);带图会话出现 damage_assessment 卡;`bun run test:eval` 不回归;引擎行为变更时跑 `test:prompt:compare`。

## Resolution
