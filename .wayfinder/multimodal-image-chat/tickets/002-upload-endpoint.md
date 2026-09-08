---
id: "002"
title: gateway 上传端点 + 本地存储
map: multimodal-image-chat
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: "weizheng"
status: closed
blocked-by: []
blocks: ["004", "005"]
created: 2026-09-08
---

## Question

修复前端上传断链:`apps/web/src/components/ChatArea.tsx:74` 仍在 `POST /api/chat/upload`,gateway-py 无此路由(404);`public/uploads/` 空目录,`main.py` 无 StaticFiles 挂载,全仓零图片存储方案。

**范围**(对齐 TS 原版约束并补安全):

- gateway 新增 `POST /api/chat/upload`:MIME 白名单 jpeg/png/webp/gif、10MB 上限、UUID 文件名落盘本地 `uploads/`(单实例本地盘)、返回 `{"url": "/uploads/..."}`。
- StaticFiles 挂载供访问;大小强制(不信任 client header,读流限长);路径穿越防护。
- 同批补 pytest 契约测试,路由计数 41→42,同步 `.claude/rules/server-gateway.md` 与 CLAUDE.md。
- 前端验收:ChatArea 选图上传成功、返回可访问 URL。

**验收**:契约绿;前端手动链路通;`bun run test:eval` 不回归。

## Resolution

完成(2026-09-08,TDD 红绿,`gateway 上传端点 + 本地存储`):

- **路由**:`POST /api/chat/upload`(`routers/chat.py`):MIME 白名单 jpeg/png/webp/gif(服务端从 MIME 反推扩展名,不信任客户端文件名)、UUID hex 文件名落盘(天然免疫路径穿越)、10MB 限长**读流实测**(256KB 分块,不信任 Content-Length;超限即删半成品文件回 413)。错误回 `JSONResponse({success: false, error}, 400/413)`,前端 `alert(data.error)` 精确展示。
- **存储与回读**:目录默认仓库根 `public/uploads`(TS 原版同址,已 gitignore),`UPLOADS_DIR` env 可覆写(测试隔离注入临时目录);`main.py` 挂 `StaticFiles` 于 `/api/uploads` —— URL 前缀选 `/api/` 使其搭 web 既有 Vite 代理直达(裸 `/uploads` 在 3000 端口会 404)。
- **依赖**:新增 `python-multipart`(UploadFile 表单解析必需,原缺)。
- **契约**:`TestChatUpload` 三用例(PNG 往返+静态回读字节一致+UUID 不回显原名 / 非 image MIME 400 / 10MB+1 流式 413),红灯确认 3×404 后转绿;全量 `95 passed` 无回归;路由计数 41→42 已同步 CLAUDE.md、README、`.claude/rules/server-gateway.md`(§1.1 补端点条目);ruff clean。
- **前端验收**:ChatArea.tsx 既有代码即契约(`formData 'file'` 字段、`data.success && data.url`、`alert(data.error)`),零前端改动即通;`/api` 代理已覆盖新前缀。粘贴/拖拽增强留 fog(Not yet specified)。
- **裁决记录**:uploads 访问控制(fog 项「公开读是否可接受」)—— 单实例运营期**接受公开读**:UUID hex 文件名即不可枚举的 capability URL,聊天本就无登录门槛,与现网关安全水位一致;若后续引入鉴权会话再升级。
