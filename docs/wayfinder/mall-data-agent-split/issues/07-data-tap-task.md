# 07: 最小数据水龙头落码（intent 数据导出）

Type: task
Status: resolved

## Question

把意图数据的「水龙头」拧开——这是本图唯一落码票（图谱期决议：数据积累靠日历时间，方案再好晚启动就晚有数据）：

1. 盘点 `intent_logs` 与 `low_confidence_logs` 的实际落库现状：谁在写（哪个 Stage/节点）、字段、写入条件、清理/TTL 策略；
2. 打通最小导出 CLI（`scripts/` 下，如 `export_intent_data.py`）：按时间窗导出 JSONL（至少含 query / intent / confidence / source_stage / 时间戳），uv 生态、ruff 干净、带最小 pytest；
3. `badcase_candidates` 池（`badcase/pool.py`）同规则可导出；
4. **不建**标注界面、**不建**训练管线。只读现状优先；若导出必需字段缺记，做最小增量补齐（带测试）并在 Answer 中说明，不自行扩表改语义。

完成标准：CLI 可跑通真实导出；Answer 里记录「实际记了什么/缺什么/量级怎么看」的事实（06 号票直接依赖）。遵守仓库工程规范（uv + pytest + ruff）。

## Answer

### 做了什么

1. **新增只读导出 CLI** `services/engine-py/scripts/export_intent_data.py`：按时间窗把三张表导出为 JSONL，不改任何写入语义、不建标注界面、不建训练管线。参数：`--source intent|low_confidence|badcase`、`--since/--until`（ISO 日期或日期时间，含端点；带时区视为 UTC 后取整为 naive，对齐表内 DB 服务器 `now()` 的 naive 时间）、`--out`（缺省或 `-` 打 stdout；摘要走 stderr，stdout 始终纯 JSONL）。输出按 `created_at` 升序。
2. **新增测试** `services/engine-py/tests/test_export_intent_data.py`（15 个用例，全绿）：内存 sqlite 建三张目标表造数，不依赖真实 postgres/Docker；JSONB 的 DDL 在 sqlite 方言下经测试内 `compiles` 钩子降级为 JSON，异步路径用只实现 `execute` 的同步会话门面；覆盖字段映射、winner 缺失回落、时间窗过滤/排序、JSONL 写文件/stdout、时区归一、CLI 全链路（换 `get_session` 指向 sqlite）。
3. **工程规范**：`uv run ruff check scripts/export_intent_data.py tests/test_export_intent_data.py` All checks passed；`uv run pytest tests/test_export_intent_data.py` 15 passed。
4. **真实导出已跑通**（dev 库，2026-09-17 实测）：intent 1966 行 / low_confidence 4 行 / badcase 547 行均成功导出；`--since 2026-09-10 --until 2026-09-11` 窗口导出 273 行。

**CLI 用法示例**（在 `services/engine-py` 下执行，自动加载仓库根 `.env` 的 `DATABASE_URL`）：

```bash
uv run python scripts/export_intent_data.py --source intent \
    --since 2026-09-01 --until 2026-09-17T23:59:59 --out /tmp/intent.jsonl
uv run python scripts/export_intent_data.py --source low_confidence --out /tmp/lc.jsonl
uv run python scripts/export_intent_data.py --source badcase --out -   # stdout
```

每行字段口径（三个源统一至少含 `query/intent/confidence/source_stage/created_at` + `source/id`）：
- `intent`：query=input_text，intent=winner（缺则回落 predicted_intents[0]），confidence=confidence 列，source_stage=method；附 predicted_intents/candidates/arbitration_reason/actual_outcome/thread_id；
- `low_confidence`：表内无 intent/confidence/method 列——intent 与 confidence **从 candidates[0]（写入方传入的终局 intents 列表）推导**，source_stage 恒为 null；附 reviewed/thread_id；
- `badcase`：候选池只存信号引用不存原文（零原始数据红线），query/intent/confidence 恒为 null，source_stage=signal_source，附 conversation_ref/business_id/status/suggested_class/note。

### 事实盘点：实际记了什么 / 缺什么 / 量级怎么看

**intent_logs（量级：dev 库实测 1966 行，2026-09-02 → 09-16）**
- 写入方（单点）：`IntentTriageEngine.log_intent_to_db`，`services/engine-py/src/engine_py/triage/intent_triage_engine.py:374`（IntentLog 构造，:385 commit）。终局决策单点落库——同一输入只写一次（fast-track 命中时以 bypass 内的写为准，槽位层不再预写，intent-arbitration 01 的决议）。写入异常静默 print 不阻断会话（:392-393）。
- 调用点（Stage/节点 → method 值）：`triage/stages/embedding_anchor.py:100,121,144,173,233`（embedding/rule）、`triage/stages/slot_fusion.py:75,235,284`（slot_extractor/slot_extractor_multi/rule）、`triage/stages/consult_fast_track.py:55`（consult_no_rag）、`triage/stages/llm_refine.py:277,315`（structured_llm/structured_llm_fallback）、`handle_immediate_bypass`（`intent_triage_engine.py:429`，各旁路：skill_fast_track/semantic_cache/vision_disambig/rag_direct 等）。
- 字段：thread_id / input_text / predicted_intents(JSONB) / method / confidence / candidates（仲裁留痕，各判定层提议快照）/ winner / arbitration_reason / actual_outcome / created_at。
- dev 库 method 分布：slot_extractor 560、skill_fast_track 473、structured_llm 276、embedding 259、rag_direct 215、slot_extractor_multi 89、rule 45、consult_no_rag 26、vision_disambig 10、semantic_cache 9、structured_llm_fallback 4。confidence<0.65 共 4 行；candidates 有留痕 1684 行、arbitration_reason 1692 行。
- **缺**：`actual_outcome` 列声明于 `db/models.py:244` 但全仓库无任何写入方，实测 0 行非空——「预测 vs 实际结果」对账维度目前不存在，06 号票引用时须注意。
- TTL/清理：**无**（全库检索无针对该表的 delete/retention），只增不减。

**low_confidence_logs（量级：dev 库实测 4 行，2026-09-04 → 09-14）**
- 写入方：`log_low_confidence_to_db`，`intent_triage_engine.py:400`。写入条件：intent 落库成功后 `confidence < 0.65`（:386-387），即 intent_logs 的子集；实测 4 行与 intent_logs 中 confidence<0.65 的 4 行口径自洽。异常静默降级。
- 字段：thread_id / input_text / candidates（实存终局 intents 列表）/ reviewed / created_at——**无 confidence/intent/method 列**（导出时从 candidates[0] 推导）。
- **缺**：`reviewed` 全 false 且全仓库无更新它的代码（检索无 UPDATE）——人工复核闭环未接线。
- TTL/清理：无。

**badcase_candidates（量级：dev 库实测 547 行，全部 candidate 状态）**
- 写入方：`record_badcase_signal`，`services/engine-py/src/engine_py/badcase/pool.py:68`（支持 dedupe：同 signal_source+conversation_ref+candidate 只入一次）。入池失败静默降级。
- 调用点：`approvals/gatekeeper.py:547`（human_takeover，thread: 引用，仅新建工单时）、`gatekeeper.py:743`（approval_rejected，approval: 引用，驳回时）、`run_agent.py:455`（circuit_breaker，会话收口处，dedupe）、`badcase/intent_signals.py:82`（intent_conflict，挂 log_intent_to_db 落库后 candidates≥2 跨意图族）、`intent_signals.py:120`（claim_mismatch，会话收口宣称 × 审批表零记录）。SOURCE_THUMBS_DOWN / SOURCE_PERSONA_FACT_DELETED 常量已定义但当前 engine-py 无调用点（库里有 1 行 persona_fact_deleted 历史数据）。
- 字段：signal_source / conversation_ref / business_id / suggested_class（先验）/ status / note / created_at / updated_at。只存信号引用不存原文——**导出无 query 文本是设计使然**，定位原文走 conversation_ref（thread:/approval: 前缀）。
- dev 库来源分布：intent_conflict 504、circuit_breaker 28、approval_rejected 12、claim_mismatch 2、persona_fact_deleted 1。
- TTL/清理：**有**——`badcase/digest.py`（candidate 90 天自动转 dismissed 并加备注，dismissed 30 天物理删除；converted 完结留痕不清理），`scheduler.py:38` 每 6 小时周期执行，`engine_py.badcase.cli expire` 可手动触发。三张表中唯一有保留策略的。

**量级怎么看**：直接 `uv run python scripts/export_intent_data.py --source X --out f.jsonl && wc -l f.jsonl`；按时间窗多次导出对比增长；`created_at` 升序保证输出稳定可比。

### 补齐了什么 / 权衡

**零 schema 改动、零写入点改动。** 盘点结论：导出必需字段（query/intent/confidence/source_stage/时间戳）三张表全部可得——intent_logs 直接有列；low_confidence_logs 缺 confidence/intent/method 列，但写入方传入的 candidates（终局 intents 列表）每项自带 intent/confidence，**导出时推导**即可，无需扩表。权衡：加列回填更「显式」，但要动 models + Alembic + 写入语义，违反票面「不自行扩表改语义」的最小增量原则——此处最小增量是零，推导口径已写进 CLI docstring 并有测试锁定（`test_low_confidence_derived_from_candidates`）。

交付物：`services/engine-py/scripts/export_intent_data.py`（新）、`services/engine-py/tests/test_export_intent_data.py`（新）。未触碰 models / 写入点 / 埋点语义。
