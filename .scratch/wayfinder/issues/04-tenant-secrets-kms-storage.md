# TICKET-04: 商户专属 API 凭据安全加密存储（AES-256-GCM / KMS）方案

**Label:** `wayfinder:research` (AFK)  
**Parent Map:** [Wayfinder Map](../map.md)  
**Assignee:** Subagent (Completed)  
**Status:** Closed

---

## Question

商户接入自定义 API 或大模型提供商（如商户自备的 OpenAI/Anthropic Key、私有 ERP Bearer Token、Basic Auth 账密、自定义 Request Headers）时，系统如何进行高强度加密落盘与运行时安全注入？

---

## Resolution Findings

1. **AES-256-GCM 对称加密规范**:
   - 采用 12 字节随机 `iv` + 16 字节 `authTag` + 加密密文；
   - 存储格式采用 `iv:authTag:ciphertext`（统一 Hex 编码），通过 Node.js 原生 `crypto.createCipheriv` / `createDecipheriv` 编解码。

2. **基于 HKDF 的租户级密钥派生**:
   - 主密钥 `ENCRYPTION_MASTER_KEY` 作为 IKM，结合 `tenantId` 作为 Salt 与 `"tenant-api-secrets-v1"` 作为 Info，通过 `crypto.hkdfSync` 派生 32 字节独立密钥。

3. **运行时 JIT 注入与脱敏 (Redaction)**:
   - 凭据仅在发起 HTTP 请求前瞬间解密装配，不在 State/内存长期驻留；
   - Pino 日志、Langfuse Span 及前端 SSE 事件流统一屏蔽与脱敏凭据字段。
