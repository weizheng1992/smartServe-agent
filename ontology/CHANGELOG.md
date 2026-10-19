# ontology CHANGELOG

## 0.3.0 — 2026-10-19(批二+批三:映射接管 + TS/docs 生成 + CI 门,ADR-0015)

- schema 卡投影化:`analytics/schema_cards.py` 手抄列卡退役,由
  `registry.card_projection()` 派发(分组规则与表序冻结校验;客户表 PII 列
  以 `analysis_columns` 裁剪,不进 T2 接地 prompt);codegen 扩
  `ONTOLOGY_ENTITIES`/`CARD_MAIN_ORDER`/`CARD_SPECIAL_ORDER`/两张卡表。
- 列级漂移闸:`semantic_compiler._assert_model_matches_card` 升列级
  (卡列 ⊆ semantic_model 列);gateway manifest 册增本体对拍断言
  (本体 merchant_db 实体列 ⊆ manifest 真实列,纯数据零 DB)。
- `emit_typescript()` → `generated/ts/ontology-actions.ts`(typed const,
  同步门);前端接线(packages/contracts)按零消费方纪律推迟(ADR 留痕)。
- `emit_docs()` → `docs/ontology.md` 知识地图(词汇闭集/四域实体表/
  Mermaid ER/动作面表/资金闸缺省)+ 同步门;`--write-all` 三路统一入口。
- CI 三步入册(ci.yml python job):ontology ruff(同口径 pyproject)+
  再生成漂移门(`--write-all` 后 `git diff --exit-code`)+ 一致性门。
- 落律:`.claude/rules/tools-registry.md` §1.5 本体知识层节;ADR-0015 批二/批三
  记录与偏差留痕(DDL 单源化与 packages/contracts 推迟及理由);
  README v5 专节状态改「已全部落地」。
- 已知推迟(ADR-0015 批二留痕):`_MERCHANT_DDL` 由声明生成(回归面
  458 契约套件跑真 DDL,成本>收益,列级断言已捕获同类漂移);
  user_coupons 卡注记删「商城券包;」前缀(语义不变)。

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
