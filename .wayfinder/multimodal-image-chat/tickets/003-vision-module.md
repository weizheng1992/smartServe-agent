---
id: "003"
title: engine vision 模块(移植+改良)
map: multimodal-image-chat
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: "weizheng"
status: closed
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

完成(2026-09-08,TDD 红绿,`engine vision 模块(移植+改良)`):

- **模块**:`engine_py/vision/analyzer.py`(考古基准 f71f7fa / b75fb78^)。继承 TS:OCR 正则(ORD-/SF/YTO/ZTO/EMS/TRACK)、三级定责(negligible/minor/severe)、启发式兜底(confidence 0.88)、PII 脱敏(复用 `scrub_pii_string`,比 TS 多覆盖邮箱)、prompt 任务定义。出参 camelCase 字典镜像 TS VisionAnalysisResult;`damageAssessment` 五字段冻结。
- **改良 TS 缺陷**:①手写 ```json 围栏剥离 → `with_structured_output(method="function_calling")`(001 裁决,Pydantic schema `VisionAnalysis`/`DamageAssessment`);②1500ms 硬超时 → `AI_VISION_TIMEOUT_SECONDS`(默认 15s,模型级 request_timeout + max_retries=0 失败即降级);③TS 传公网 CDN URL,Python 侧本地图 `/api/uploads/` 引用 → base64 Data URL 直传(bigmodel 拉不到 localhost,亦免出网暴露),单图不可读跳过、全不可读直走启发式。
- **接线**:triage Step 0.5 TODO 位落地(`intent_triage_engine.py`):📷 状态播报 + `analyze_images` + try/except 保险带(视觉失败绝不炸分流),`damageAssessment or 既有值` 镜像 TS;后续全部 return 路径与 `state.damage_assessment` 槽位、`card_synthesizer` 消费端原样复用,零额外管线改动。
- **统一入口**:`get_vision_model()` 落 `llm/chat.py`(lru_cache 单例,`AI_VISION_MODEL` 默认 glm-4.6v);刻意不入 `_ResilientChatOpenAI` 韧性层 —— 视觉失败域独立、自带兜底,不污染全局熔断与遥测(agent-engine.md 准则 2 已补例外注记)。
- **测试**:`tests/test_vision_analyzer.py` 七用例(空图不触模型 / LLM 失败降级启发式 / 运单正则 / 无破损词不出定责 / LLM 成功结构化+PII 脱敏+imageUrl 服务端强制回填 / 本地图转 Data URL / 坏图降级不异常),伪模型注入 seam。
- **验证**:engine 全量 162 passed、gateway 契约 95 passed 无回归、ruff 双服务干净。`test:prompt:compare` 未跑 —— 文本路径 prompt 零改动(带图分支才触发 vision),基线不可能漂移;真实带图 E2E 与卡片渲染验收按图归 005。
