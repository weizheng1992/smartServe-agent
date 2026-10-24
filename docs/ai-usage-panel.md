# AI 用量面板（设计基线，2026-10-24 grilling 共识收口）

> 本文是「AI 用量可视化」的实施 spec。15 个决策点经 grilling 三轮定档，全按推荐；
> 实施与 code-review 以此为对照物。P1/P2 段为路线图，本期不实施。

## 背景与结论

项目省 token/延迟的三板斧已落地（零 LLM 快轨群 / 2000 预算+懒摘要 / 语义缓存+L2 范例回放，
关 thinking 为单项最大延迟优化）。**计量基建 95% 已存在**（`llm_call_logs` 逐调用、
`session_metrics` 每轮一行），缺的只是商户后台的呈现面与商城端的 debug 冒泡。
"省了多少"是反事实量，P0 只展示**实际值 + 命中标记 + 路径占比**（省的证据链）。

## P0 范围（本期）

### 1. 写侧增强（引擎，三处小改）

| 改动 | 位置 | 说明 |
|---|---|---|
| `llm_call_logs` 加 `job_id` 列 | `llm/telemetry.py` 行字典（`CallContext.job_id` 现成）| 轮↔调用精确关联的唯一键 |
| `session_metrics` 加 `job_id` + `turn_path` 列 | `db/models.py` + 迁移 0025 | 轮路径一等公民化 |
| 进图前问候旁路补写零 token 行 | `run_agent.py` greeting 分支 | 此前完全不落库，轮数统计缺行 |

`turn_path` 取值闭集（triage 出口映射，单点在 `handle_immediate_bypass` + process() 成功出口）：

| turn_path | route_key 来源 | 语义 |
|---|---|---|
| `greeting` | rule_greeting / 进图前问候 | 零 LLM 罐头问候 |
| `semantic_cache` | super_semantic_cache | 同问语义缓存复放（0 次调用）|
| `duplicate_bypass` | duplicate_bypass | 重复提问拦截（0 次调用）|
| `rag_direct` | rag_consult_direct / _llm | 咨询单次直答（≈1 次调用；快轨内缓存复放与新直答库内不可区分，如实合并）|
| `clarify` | confidence_clarify / slot_clarification_* | 澄清反问（0.5 级联旁路）|
| `bypass_other` | rule_empty/symbols/length_limit/exit、llm_out_of_scope、image_*、技能 HITL | 其余确定性旁路 |
| `deep_path` | process() 成功出口（triage 节点默认）| 非旁路主链。**含** triage 判定后中断/熔断的轮（路径已决、token 已花）与 consult_no_rag 空弱回落轮（走主链 finish 终稿，不经旁路出口）；NULL 仅剩三个降级臂（路径未决即离场）|

### 口径修正（code-review 双轴 2026-10-24）

- **未归因桶**：商户页只展示本租户归因行 + notes 口径注记 —— 跨租户合计数字对
  商户面是隔离反模式（架构不变量 #1）；P1 归因修复后未归因桶转真桶。
- **灰度口径**：首版仅 finance_owner/admin 经 `_GREY_RELEASE_MENUS` 实现，为
  **菜单可见性灰度**（与 m-agent-desk 同律）；接口闸 = 员工 JWT + 租户归属
  （operator_scope 无角色闸，403 结构上不可达），一线角色直敲 API 可见本租户数据。
- **turns threadId 过滤**：网关契约已钉（含线程过滤与排序），页面消费入口列 P1。

### 2. 网关只读端点（`routers/admin.py`，`operator_scope` 员工闸）

- `GET /api/admin/ai-usage/summary` — 自然月窗口（`date_trunc('month', NOW())`，DB 时钟
  单点，规避容器时区漂移）：配额口径（session_metrics SUM + monthly_limit_tokens 对照）、
  按天趋势、路径占比、全量调用口径（llm_call_logs 月窗 SUM，含 data agent/未归因桶）。
- `GET /api/admin/ai-usage/turns?thread_id=&limit=&offset=` — 轮列表（turn_path/tokens/延迟/终态）。
- `GET /api/admin/ai-usage/calls?job_id=` — 轮下钻调用明细（先验轮归属本租户再放行）。

### 3. 商户后台页面（apps/merchant-admin）

- 路由 `/ai-usage`，菜单种子 `m-ai-usage` 挂 `d-ops`；**灰度**：进 `_GREY_RELEASE_MENUS`
  （首版仅 finance_owner/admin 可见，sales_viewer/warehouse/support 不可见）。
- 图表复用自研 LineChart/BarChart，零新依赖。KPI：本月 token vs 限额、积分余额
  （复用 `/api/admin/credits`）、平均轮延迟、零 LLM 命中率（greeting+semantic_cache+
  duplicate_bypass 占比）与快轨占比。**无美元**（成本是平台内部数据）。

### 口径约定

- "面=轮、下钻=调用"：session_metrics 本就每轮一行 INSERT，turn 级聚合零新建表。
- 配额对照与 billing 闸同源（session_metrics）；llm_call_logs 全量为明细口径，
  data agent 行（business_id NULL）独立桶展示，归因修复在 P1。
- 自然月窗口页面自算；`/api/billing/usages` 无时间窗问题**另开票**（计费口径变更，不搭车）。
- 成本常量三处拷贝（$0.15/M）本期不动（商户页无美元）。

## P1（后续票）

- ~~商城端 `?debug=usage` 角标~~ **已交付(2026-10-24)**:SSE 帧 + POST 信封透传
  usage(totalTokens/latencyMs/turnPath,引擎 final_result 携带,greeting 臂与收口臂
  双写),FloatingChatWidget 时间旁小字「⚡ 耗时 · tok · 路径」仅本机渲染、仅当轮,
  历史接口与顾客气泡零改动;浏览器实测双向往返(带参数出角标/无参数零渲染)。
- data agent 归因修复：gateway analytics ask 路径补 `bind_llm_call_context`（绑定点唯一先例 run_agent）。
- 反事实估算"本月快轨+缓存为你省约 X"（基线=全管线历史均值，UI 标注估算）。

## P2

- Prometheus/Grafana 导出（deploy/monitoring 已留 instrumentator 占位注释）。

## 测试接缝（TDD 预定）

1. `turn_path_for_route` 纯函数映射（全 route_key 闭集）。
2. telemetry 行携带 job_id 契约（monkeypatch `_persist` 捕获，不触库）。
3. 问候旁路零 token 行落库（密封 PG，验 turn_path='greeting'、total_tokens=0）。
4. 网关三端点：真实登录鉴权 401/403、summary 月窗数学、turns/calls 过滤与越权。
5. 菜单种子：finance_owner/admin 含 m-ai-usage，sales_viewer 闭集不含（灰度钉）。
6. 前端页面 vitest（诚实空态 + KPI 渲染 + 下钻联动）。
