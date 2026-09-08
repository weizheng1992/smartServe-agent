---
id: "001"
title: 视觉模型选型与接入形状(research)
map: multimodal-image-chat
type: ticket
labels: [wayfinder:research]
mode: AFK
assignee: "weizheng"
status: closed
blocked-by: []
blocks: ["003"]
created: 2026-09-08
---

## Question

为 Python 侧 vision 选定视觉模型并定接入形状。现状:`engine_py/llm/chat.py:112` `get_chat_model()` = LangChain ChatOpenAI(OpenAI 兼容,`AI_BASE_URL`/`AI_MODEL` env,.env 已配智谱),全链路零 `image_url` content parts 构造。

要回答:

1. **型号**:智谱(bigmodel.cn)当前视觉模型(GLM-4V 系 / GLM-4.5V 等)哪个适合客服 OCR+定责场景,规格(上下文/分辨率)。
2. **API 形状**:OpenAI 兼容端点是否支持 `image_url` content block;base64 data URL 与公网 URL 两种传法是否都行;单请求图片数量/大小/分辨率限制。
3. **计费**:每千 token 或每图价格,与现用文本模型成本量级对比。
4. **接入**:独立 `AI_VISION_MODEL`(可复用同 base_url)由 vision 模块单独构造,还是别的形状;与 `with_structured_output`(Pydantic)配合是否可用。

产出写进 Resolution,003 据此直接开工。

## Resolution

调研完成(2026-09-08,web 调研代理;证据:bigmodel.cn 模型概览 / 定价页 / 对话补全 API 参考 / 结构化输出文档):

1. **型号**:主力 **GLM-4.6V**(128K 上下文 / 32K 输出,**1/3 元每百万 token**,官方推荐场景直接命中「图片 OCR 信息提取 / 表单录入」,且是 5.3-Flash 之外唯一支持工具调用的视觉模型);免费兜底 **GLM-4.6V-Flash**(同代架构,完全免费);严格 server-side schema 需求切 **GLM-5.3-Flash**(0.4/1.4 元,唯一支持图像 + `response_format=json_object` 同请求,代价是思考不可关、输出 token 偏高)。GLM-4V 系已退市,勿选。
2. **API 形状**:OpenAI 兼容 `/chat/completions`,`image_url` content block 与 OpenAI vision 完全同形;base64 Data URL 与公网 URL 均可,LangChain 路线统一用 `data:image/jpeg;base64,...` Data URL(本地文件直传,免出网暴露)。单请求 ≤50 图;单图 ≤5MB、≤6000×6000、jpg/png/jpeg —— 网关 10MB/张与 ≤3 图/条治理均在此限制之内,无冲突。
3. **计费**:按输入 token 计价,无「每图」价;一张 1024×1024 图约数百至 1K+ 输入 token,单次面单 OCR + 破损定责请求约 0.001~0.005 元,客服量级成本可忽略。
4. **接入**:新增独立 env `AI_VISION_MODEL`(默认 `glm-4.6v`,开发期可切 `glm-4.6v-flash` 零成本),`AI_BASE_URL` / `AI_API_KEY` 复用现有 `AI_*` 配置,LangChain `ChatOpenAI` 单独构造。**关键约束**:`response_format` 仅文本模型支持(vision 请求 schema 无此字段),GLM-4.6V 拿结构化 JSON 必须走 `with_structured_output(method="function_calling")`(4.6V 支持 tools,tool_choice=auto)或 prompt 钉 schema + 宽容解析;`method="json_mode"` 只有 GLM-5.3-Flash 稳 —— 003 票已按此修正。
