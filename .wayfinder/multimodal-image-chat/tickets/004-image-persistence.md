---
id: "004"
title: 图片持久化与会话还原
map: multimodal-image-chat
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: ""
status: open
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
