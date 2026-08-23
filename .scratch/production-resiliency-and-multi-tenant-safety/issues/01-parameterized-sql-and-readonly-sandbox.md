# 01 — 参数化预编译与只读安全沙箱 (Parameterized Prepared SQL & Read-Only Sandbox)

**What to build:** 彻底消除自然语言转 SQL（NL2SQL）中的字符拼接与注入隐患。重构自然语言指标查询编译器 `NLMetricQueryEngine`，输出结构化参数化查询对象 `{ text: string, values: unknown[] }`；提供数据库级只读事务执行沙箱 `executeReadOnlyAnalyticsQuery`，强制注入 `SET TRANSACTION READ ONLY` 与 3000ms 语句超时保护，确保复杂分析型查询永远不会越权写入数据或阻塞线上交易主库。

**Blocked by:** None — can start immediately.

**Status:** closed

- [x] `NLMetricQueryEngine.compile` 输出强类型 `{ text: string, values: unknown[] }`，所有商户 ID、数值阈值、分类字符串均转为 `$1, $2, $3` 位置占位符
- [x] 动态过滤条件支持操作符白名单校验（`>`, `>=`, `<`, `<=`, `=`, `!=`），非法操作符回退为安全默认值
- [x] 数据库层提供 `executeReadOnlyAnalyticsQuery` 沙箱执行包装器，前置执行只读会话配置与 3 秒硬超时
- [x] 查询结果限制强制执行安全分页截断（`Math.min(limit, 50)`），防止大表全量扫表导致内存溢出
- [x] 编写对抗性 SQL 注入单测（如 `' OR 1=1; DROP TABLE products; --`），验证恶意输入被安全作为字面量值绑定且不破坏语法结构
