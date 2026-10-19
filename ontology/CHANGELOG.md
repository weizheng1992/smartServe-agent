# ontology CHANGELOG

## 0.1.0 — 2026-10-19(批〇试点,ADR-0015)

- `core.yaml`:闭集词汇(domains 五域 / databases 两库 / faces 四面)。
- `domain/marketing.yaml`:三实体(promotions / promotion_redemptions / user_coupons,
  含 table 表列映射锚)+ 两笔域内 join + promotion 维度。
- `registry.py`:pydantic v2 声明模型与加载校验(未知域/库、悬空 join、别名冲突、
  维度缺键、坏版本一律响亮失败)+ semantic_model 同形编译投影。
- `tests/`:一致性门 20 例(parity 5——与 engine semantic_model 逐键相等;
  校验负例 15)全绿。
- ADR-0015 落律;CONTEXT.md 指针;根 README「🧬 v5 规划」专节。
- 已知偏差(留痕于 ADR-0015 §5):未入 uv workspace;跨域 join
  `redemption_of_order` 随 trading.yaml(批一)落位;实体 `table` 键为批二映射预置。
