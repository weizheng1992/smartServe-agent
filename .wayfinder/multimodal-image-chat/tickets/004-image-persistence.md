---
id: "004"
title: 图片持久化与会话还原
map: multimodal-image-chat
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: "weizheng"
status: closed
blocked-by: ["002"]
blocks: ["005"]
created: 2026-09-08
---

## Question

补第四个断点:图片不落库、刷新即失忆。现状:dispatch 落库只存 content(`gateway_py/routers/chat.py:55-63`),`messages` 表无 imageUrls 列(`engine_py/db/models.py:60-72`),web `loadHistory`(`useChatMessages.ts:39-80`)不还原图。

**范围**:

- `messages` 表迁移:存 imageUrls **引用**(JSON 列,不存 blob;DB 所有权在 engine,Alembic 迁移)。
- gateway `append_message` 透传 imageUrls(用户消息侧);SSE/历史读取路径带出。
- web `loadHistory` 还原:带图消息渲染缩略图(消息结构 `Message.imageUrls` 已有字段,前端只差渲染与回填)。

**验收**:发图→刷新页面→图与对话俱在;契约/eval 不回归;迁移幂等(沿用既有 inspection 护栏风格)。

## Resolution

完成(2026-09-08,TDD 红绿,`messages 落库 imageUrls 引用 + 历史还原`):

- **DB 层(engine 所有权)**:Alembic `0006_messages_images` 增列 `image_urls`(JSONB 数组、可空、只存 `/api/uploads/...` 引用不存 blob),沿用 0005 的 inspection 幂等守卫(0001 create_all 已含列时守卫空转);`db/models.py` Message 增 `image_urls` 字段。dev 库 `db:push` 已应用。
- **gateway 写入**:`conversation_repo.append_message` INSERT 增 `CAST(:imgurls AS jsonb)` 列与 `imageUrls` payload 键,返回值同步带出(其余 4 个调用点——realtime×3、spi——不带图,`payload.get` 缺省 None 落 NULL,零改动兼容);`routers/chat.py` dispatch 用户消息落库透传 `body.imageUrls`(此前 AgentJobInput 带图但落库丢弃,即"播报有图、库里没图"断点本体)。
- **gateway 读出**:`get_conversation_timeline` SELECT 增 `image_urls`,parsed_messages 映射 camelCase `imageUrls`(非 list 容错 None)。GET /api/chat/messages、admin 会话时间线共用此函数,一处修两处得。
- **web 还原**:**零前端改动**——`Message.imageUrls` 字段与 ChatArea 缩略图渲染(002 已落)俱在,loadHistory 原样回灌 `data.messages`,后端带回即渲染;`m.imageUrls &&` 守卫使旧消息(None)自然跳过。
- **测试**:`TestChatImagePersistence` 两用例(dispatch 带图拦截 run_agent → GET messages 原样带回;无图消息 imageUrls 为 None),与既有 resume-dispatch 同一 patch 位。
- **验证**:gateway 97 passed(95+2)、engine 162 passed 无回归、ruff 双服务干净。`test:prompt:compare` 未跑——纯持久化透传,文本路径 prompt 零改动。真实发图→刷新 E2E 验收按图归 005。
