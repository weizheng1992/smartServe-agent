---
id: multimodal-image-chat
title: 多模态图片客服
type: map
labels: [wayfinder:map]
status: open
created: 2026-09-08
---

## Destination

用户在 web 聊天发图(物流面单、破损商品、商品图),平台真实"看图办事":上传存储 → 引擎视觉理解(OCR 提单号、破损 3 级定责)→ 意图分流注入 → damage_assessment 等卡片回复 → 会话刷新可还原。回收 Phase 1b 移植池中"多模态 vision"一项,补齐 TS 退役时(2026-09)留下的四个断点。**本图为执行图(override)**:ticket 直接实现并关闭;全部子票关闭即到达。

## Notes

- **执行图 override**:ticket 是工作单元,领取后直接实现、验证、关闭。
- **验收总纲**:相关 pytest 契约/单测绿;`bun run test:eval` 不回归;动到引擎生成行为时 `bun run test:prompt:compare` 基线不回归;`uv run ruff check .` 干净。
- **契约冻结例外**(CLAUDE.md 不变量 #6):新增路由(如 `/api/chat/upload`)必须同批补 pytest 契约测试,路由计数 41→N 同步 `.claude/rules/server-gateway.md` 与 CLAUDE.md。
- **提交纪律**:一票一组 commit,中文 commit 风格,weizheng1992 身份,无尾注。
- **建议技能**:实现类票用 `tdd`;受阻塞时 `diagnosing-bugs`。research 技能未安装,001 由 web 调研代理完成。
- **TS 考古基准**(勿照抄,择善继承):vision 引入于 commit `f71f7fa`,最后完整 TS 树 `b75fb78^`,核心 `packages/engine/src/vision/visionAnalyzerService.ts`(~145 行);设计文档 `docs/architecture/multimodal-and-rich-cards.md`(与实况有出入,以代码考古为准)。
- **契约钉死**:`DamageAssessmentData` 字段名不动(`packages/types/src/card.ts:179` 与 `DamageAssessmentCard` 组件在用);前端消息结构 `Message.imageUrls` 不改形。
- **已知断点地图**(现状盘点):① 上传端点 404 + 零存储方案;② triage 视觉解析 TODO(`intent_triage_engine.py:220`);③ 全链路无 image_url content parts 构造、无视觉模型配置;④ messages 表无 imageUrls、历史不还原图。
- **Tracker 约定**:见 [.wayfinder/README.md](../README.md)。

## Decisions so far

- [视觉模型选型与接入形状(research)](tickets/001-research-vision-model.md): 主力 **GLM-4.6V**(1/3 元/M token、128K 上下文、原生工具调用、base64 Data URL 直传、≤50 图/请求),免费兜底 GLM-4.6V-Flash,严格 schema 切 GLM-5.3-Flash;新增 `AI_VISION_MODEL` env 复用现有 `AI_*`;结构化输出只能 function_calling 式(`response_format` 仅文本模型支持)。
- [gateway 上传端点 + 本地存储](tickets/002-upload-endpoint.md): `POST /api/chat/upload` 落地(MIME 白名单、10MB 读流实测、UUID 落盘 `public/uploads`、`/api/uploads` StaticFiles 回读),新增 `python-multipart` 依赖;契约三用例入册,路由计数 41→42 三处文档同步;uploads 公开读=UUID capability URL,单实例运营期接受。
- [engine vision 模块(移植+改良)](tickets/003-vision-module.md): `engine_py/vision/analyzer.py` 落地并挂 triage Step 0.5 —— 结构化输出走 function_calling、超时可配(默认 15s)、本地图转 base64 Data URL 直传、LLM 失败降级启发式;`get_vision_model()` 入 `llm/chat.py` 统一入口(`AI_VISION_MODEL` 默认 glm-4.6v);七用例 + engine 162 / gateway 95 全绿。

## Not yet specified

- **粘贴/拖拽上传**:前端输入增强(现仅文件选择器),等基本链路打通后视手感立票。
- **severe 定责 → HITL 审批**:TS 文档承诺但从未实现(suggestedAction 只是数据字段);等定责链路真实跑起来、看过真实分布再决定是否兑现。
- **商户端图片输入**:`apps/merchant` 聊天浮窗无 imageUrls 入口,等 web 端验证价值后再议。
- **通用看图对话**(非 OCR/定责场景,视觉摘要直接进 planner 上下文):TS 亦无,超出回收范围,雾里观望。

## Out of scope

- **OSS/对象存储上云**:单实例本地盘够用,部署演进另行立项。
- **图片向量化进 RAG/四象限记忆**:TS 亦无,属能力扩展非回收。
- **takeScreenshot、nlQuery 六件套、SPI 远程连接器、KMS 等其余 Phase 1b 项**:继续留回收池,无真实调用方不动。
