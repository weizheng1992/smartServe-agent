"""商户 data agent(wayfinder 09-D3:独立轻管线,落点本包)。

模块面:
- engine       MetricQueryEngine 深模块(resolve/compile/execute)
- resolver     L0 同义词归一(词表/反向词/时间窗/LIMIT),未命中 unsupported
- sql_guard    sqlglot AST 白名单校验(单语句 SELECT/表白名单/租户谓词断言)
- schema_cards 编译期 schema 卡片(代码事实源;漂移断言见 17 号票决议)

铁律:LLM 永不写 SQL(08-D1);用户输入永不进 SQL 文本;business_id 服务端
强制注入;未命中响亮失败,严禁静默兜底(08-P1)。
"""
