# gateway-py — NestJS 网关的 Python 参考重写(Phase 2)

`apps/server`(NestJS,39 路由)的参考式重写。契约冻结:HTTP 路由 + SSE 线格式 +
socket.io 事件与 TS 版 1:1;验收网 = `apps/server/test/contract/` 密封契约测试。

## 架构

- **uv workspace**(`services/pyproject.toml`):gateway-py 依赖 engine-py,
  复用其 DB 投影层、事件总线、技能注册表、审批门禁与 run_agent —— 镜像 TS 中
  server → engine/tools/db 的包依赖结构
- **SSE**:直接消费 Phase 1a Redis Streams 主干(`job:events:{jobId}`),
  `id: N` 整数序号 + Last-Event-ID 重放 + 15s 心跳,与 TS pipeSSEFromStream 同协议
- **socket.io**:python-socketio ASGIApp(namespace `/ws/chat`,path `/socket.io`),
  五事件 join_thread / takeover_conversation / release_takeover / send_message / typing
- **SPI 鉴权**:API-Key 约定式(`key_{tenant}` / `secret_{tenant}` / 平台主键)+
  HMAC-SHA256 签名通道(`METHOD\nPATH\nTIMESTAMP\nNONCE\nSHA256(BODY)`,300s 防重放)
- **SQL 沙箱**:sqlglot AST 只读校验(比 TS 正则黑名单更强:语法树级阻断 +
  系统表穿透防护)+ 只读事务 + 3s 超时
- **租户上下文**:contextvars 中间件(x-tenant-id / x-business-id / query / body
  四级回退 + admin 默认 all),guard 缺租户 403

## 运行

```bash
cd services && uv sync
uvicorn gateway_py.main:app --port 4000
# 或:cd gateway-py && uv run uvicorn gateway_py.main:app --port 4000
```

## 已知简化(对照 TS)

- evals 指标为随机生成(与 TS 现状一致)
- ws:events Redis 通道保持"只发不收"现状(消费方后续接入)
- 视图:admin CRUD 响应字段以契约测试断言为准做了 1:1 对齐
