# ontology CHANGELOG

## 0.2.0 — 2026-10-19(批一:四域全量 + 动作面 + codegen,ADR-0015)

- `domain/{product,trading,crm,shared}.yaml` 补齐:12 实体/9 join/8 维度全量;
  registry 两阶段构建 —— 跨域 join 在 base 侧域文件声明、全域实体表校验,
  表达式维度单冒号守卫。
- `application/actions.yaml`:9 动作(faces/permission/roles/notes)+ 幽灵
  `reply` 登记 + 免签退款限额缺省 50(六处分叉单源,租户覆写通道不变)。
- codegen:`emit_python()` → `engine_py/ontology_generated.py`(自包含零依赖),
  漂移门 `test_codegen_sync`(文件 ≠ 编译输出即红)。
- 引擎接线:gatekeeper 受理集显式化 + 入口未知动作早退 400 + reject 显式
  分支;阈值七处单源(gatekeeper/执行器×2/run_agent×2/state/tenant_config/
  seed,seed ecommerce $100→$50 有意收紧);schema 卡 membership→member_level
  勘正(错卡此前正喂 T2 接地 prompt)。
- 网关接线:approval_actions 四词表改派生再出口(名字/成员/消费点零变化);
  商户台动作白名单 400(实弹①静默驳回收口);新册
  `gateway tests/test_approval_action_registry.py`(400×2 + 受理集 parity +
  rbac 源码级 permission 真实性)。
- 测试:ontology 一致性门 20→40(parity 扩全量 + 动作守卫 + codegen 漂移门 +
  TS 双向对齐);engine 1834 全绿;gateway 458+3skip 全绿;ruff 双服务清。

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
