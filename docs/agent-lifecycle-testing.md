# Agent 全生命周期迭代测试与金丝雀发布规划指南 (Agent Lifecycle Testing & Canary Deployment)

本指南旨在为本智能客服平台(smartServe)提供一套工业级、闭环的 **DevOps + LLMOps 持续集成与发布保障体系**。由于大模型 Agent 具有随机性、提示词敏感性与工具链状态漂移等特征,Agent 的上线迭代必须遵循严格的、数据驱动的渐进式发布流程。

> **修订说明(2026-09-03)**:本文按当前 Python 后端架构(`services/gateway-py` FastAPI + `services/engine-py` LangGraph/SQLAlchemy)修订。全文以 **ℹ️现状** 标注已实现的真实资产、以 **🎯目标态** 标注规划;第五阶段经设计评审全量重写(半自动闭环)。历史版本中引用的 Next.js API route、Drizzle、Langfuse 深度集成、`select-tool`/`is-not-hallucinated` 断言类型、`is_active_new_agent` 配置字段均经代码核实**不存在**,已移除或更正。

---

## 🗺️ 架构全局纵览 (Overview)

```
[ 本地/CI 迭代开发 ] ➔ [ 1. 离线黄金集回归 (Promptfoo + Playwright) ]
                                │ (100% 绿灯通过)
                                ▼
                [ 2. 线上 Shadow 暗网双跑 ] ➔ 对比 Latency/Cost/Intent
                                │ (平稳运行 1-3 天)
                                ▼
                [ 3. 金丝雀渐进式灰度 ] ➔ 先 Puma ➔ 再 Nike/Adidas 按比例灰度
                                │ (观察 session_metrics)
                                ▼
                [ 4. 生产观测 ] ➔ 收集用户真实提问与反馈信号
                                │
                                ▼
                [ 5. Bad-Case 半自动闭环 ] ➔ 实时入候选池 ➔ 人工 Triage ➔ Promptfoo 黄金集
                                │
                                └─── 修复后回到 1 重新排队(黄金集变绿 ≠ 可发布,必须重走 2/3)───┘
```

**关键修正**:五阶段是一条**环**而非一条线。第五阶段的出口接回第一阶段入口——修复(往往改的是提示词/SOP,恰是对线上行为扰动最大的变更类别)必须重新走完离线回归 → Shadow → 金丝雀,不存在"黄金集变绿即发布"的捷径。

---

## 🛑 第一阶段:离线黄金回归测试 (Offline Regression & Golden Dataset)

在任何 Agent 提示词或工具链代码合并进 `main` 主干分支前,必须通过 **双层黄金测试集(Golden Dataset)**,证明其决策与对话质量无退化。

### 1. 语义与意图分类回归 (Promptfoo)

ℹ️现状:评测基建真实可用。主配置 `eval/promptfooconfig.yaml`(自定义 provider `eval/providers/agent_provider.py` 直连 engine_py,挂载 13 个 testCase 文件、约 43 条 case),另有分类/规划分册 `promptfoo.classify.yaml`、`promptfoo.planner.yaml` 与多意图专项;TS→Python 迁移等价性由基线 pin/compare 把关(`bun run test:prompt:pin` / `test:prompt:compare`)。

*   **评测指标**:
    *   **Triage F1 Score**(`eval/scorers/intentF1.scorer.ts`):测试分类意图的精准度,确保不会将 `order_status` 与 `refund` 混淆。
    *   **Answer Quality Score (LLM-as-a-Judge)**(`eval/scorers/answerQuality.scorer.ts`,含幻觉评判维度):对 Agent 总结输出(Finish Node)进行打分。
*   **执行指令**:
    ```bash
    bun run test:prompt
    ```
*   **硬性红线**:意图匹配率必须维持在 **100%**,回答语义均分不低于 **4.5 / 5.0** 分。

### 2. 物理与安全性回归 (Playwright E2E)

ℹ️现状(诚实标注):`apps/web/e2e/` 仅 5 条测试。Anti-IDOR 有覆盖但断言较弱(仅 UI 文本断言);名为 HITL 的 `chat-hitl.e2e.ts` 实际只测登录重定向与布局渲染。**下方三项验证要点中,目前只有第一项部分成立**,HITL 审批挂起→核签流程与熔断器 E2E 为待补技术债(见附录)。另:E2E 的 webServer 只拉起前端,后端/DB 需手工就绪;登录依赖的 `/api/auth/login` 路由在 gateway-py 中不存在(靠 localStorage 兜底)。

*   **验证要点(目标态)**:
    *   **安全拦截(Anti-IDOR)**:验证用户只能查到或修改属于自己 `userId` 归属下的订单。
    *   **审批拦截(HITL)**:验证大额退款正确被系统挂起(Status: pending)并生成审批单。
    *   **熔断器(Circuit Breaker)**:验证自旋熔断阈值(10 步/3 次错误)生效。
*   **执行指令**:
    ```bash
    bun run test:e2e
    ```

---

## 🌐 第二阶段:暗网双跑模式 (Shadow Mode / Parallel Run)

真实生产环境的用户输入具有无限可能性,因此在完全切流前,必须进行 **Shadow Mode(暗网双跑)**,验证新 Agent 在海量生产请求下的并发吞吐与稳定性。

ℹ️现状:线上暗网双跑**未实现**。现存资产是离线 shadow 回放器(`engine_py/shadow/replay.py` + `shadow/diff.py`),与 `eval/pinBaselines.ts` / `compareBaselines.ts` 配合,用作 TS→Python 迁移的等价性门禁。历史版本的 Next.js `/api/chat` 双跑伪代码对应的 `apps/web/app/api/chat/route.ts` **从未存在**(apps/web 为 Vite 6 SPA),已移除。

🎯目标态:线上双跑的挂点在 FastAPI gateway 的 chat 路由(`services/gateway-py/src/gateway_py/routers/chat.py`,`POST /api/chat`):

```python
# 🎯目标态伪代码(未实现)
@router.post("")
async def chat(req: ChatRequest):
    async def _shadow():
        try:
            r = await run_agent(req, variant="shadow")
            # 静默记录 shadow 的决策流、耗时、Token 到 eval 对比表
            await log_shadow_metrics(req.thread_id, r)
        except Exception:
            logger.exception("[Shadow Agent] 暗网执行失败,不影响用户")

    if await shadow_enabled_for(req.tenant_id):
        asyncio.create_task(_shadow())   # 异步非阻塞,隐藏其返回

    return await run_agent(req)          # 生产 Agent 决定用户可见输出
```

### 对比审计指标 (Shadow Auditing Metrics)

*   **耗时(Latency)**:对比新老 Agent 全图决策平均耗时,验证其是否发生明显卡顿。
*   **财务成本(Cost)**:由于提示词改变、RAG 数量微调,必须在 APM 中对比两者的 Token 消耗量。
*   **工具调起差异率**:审计新 Agent 规划的 Tools 与老 Agent 调用工具的重合度,防止误调无关高危接口。

---

## 🚦 第三阶段:金丝雀渐进式灰度发布 (Canary & Ring Deployment)

当 Shadow 模式下连续 48 小时指标正常,开始通过渐进灰度将新 Agent 真实投产。

ℹ️注:原文所称配置字段 `is_active_new_agent` 经核实**不存在**,按租户灰度目前是纸面规划。落地时应作为租户配置 registry 的灰度字段(例如 `canary_new_agent_ratio`)实现,走配置热更新,并在 Admin 提供开关面。

### 1. 按租户商户灰度 (Ring 1)
智能客服平台为多商户(Nike、Adidas、Puma、主站)提供多租户隔离服务。
*   **策略**:选择一两家咨询体量小、业务容错度高、合作紧密的种子商户(例如 Puma)作为灰度第一环(Ring 1)。
*   **实施**:修改种子商户的灰度配置后,该商户会话自动由新 Agent 接管,其他主站商户保持不变。

### 2. 按流量比例灰度 (Ring 2)
在第一环运行平稳后,针对 Nike / Adidas 等大体量商户开启流量灰度比例划分。
*   **金丝雀发布梯度(Canary Gradients)**:
    $$5\% \longrightarrow 10\% \longrightarrow 30\% \longrightarrow 50\% \longrightarrow 100\%$$
*   **指标观察哨(SQLAlchemy `session_metrics` BI 看板;schema 归 engine-py/Alembic 所有)**:
    *   **Autopilot Success Ratio(自主解决率)**:如果自主解决率突降,证明新 Agent 的提示词可能导致工具无法合理匹配。
    *   **Resolution Ratio(人工核签拦截比)**:若 Pending 比例超限,说明新 Agent 的退款金额格式判断或敏感度变高。
    *   **Circuit Breaker Fuses(硬熔断次数)**:ℹ️现状:熔断状态只活在图内存(`build_graph.py` 中 10 步/3 错常量),`session_metrics.resolution_status` 无 `circuit_breaker` 取值,此看板目前**无数据可查**——落盘在第五阶段 v1 补齐。

---

## 📊 第四阶段:生产环境深度可观测性 (Production Observability)

Agent 发布完成后,必须进行端到端的**分布式链路追踪(Distributed Tracing)**,用真实数据进行系统性能度量。

ℹ️现状(2026-09-03 摸底):
*   **Langfuse 未集成**(仅规则文档提及);**OpenTelemetry 零集成**;gateway-py 零 APM。
*   LangSmith 仅有 `run_agent.py` 内部的成败上报,**无 runId 绑定**、打不到具体 trace,且与用户反馈无关。
*   `session_metrics` 表真实存在并有读写:`calculated_cost_usd`、`resolution_status`、`node_transitions_count`、`avg_latency_ms`。
*   **数据质量债**:`/api/evals/run` 返回本地随机指标(gateway `crud.py` 注释自认"非真实评测");`/api/logs` 的 prompt/completion tokens 为硬编码值——已列为第五阶段**前置清理项**。
*   前端"APM"是本地 DAG 执行监控面板(`APMPanel.tsx`),非外部 APM。

🎯目标态:
1.  **链路追踪(Trace View)**:先补 LangSmith runId 桥接(或在 engine-py 自建轻量 trace 表),才能按节点呈现 Triage 意图识别、Planner 任务规划、Executor 工具调用参数与 Validator 数据核验。
2.  **财务审计(Billing Analytics)**:监控租户端 `session_metrics.calculated_cost_usd`,发现异常超额消耗时进行多租户 TPM/RPM 的 Redis 滑动窗口动态限流。

---

## 🔄 第五阶段:Bad-Case 半自动闭环 (Semi-Automatic Bad-Case Loop)

大模型 Agent 系统持续进化的关键,在于将线上的失败(Bad-cases)无缝转为下一次迭代测试的燃料。

> **定位(2026-09-03 设计评审锁定)**:**半自动闭环**——收集、清洗、用例草案自动化;业务定性、断言编写、修复保持人工。"自愈/自进化"是愿景措辞,不是系统承诺。本环路的出口是**重新排队**(回到第一阶段),而非直接发布。

### 0. 设计原则

1.  **候选池制**:一切信号只进候选池,**永不直接变成回归断言**。坏例只提供"输入 → 错误输出",回归测试需要的"输入 → 正确输出"中那个"正确"必须由人(或经人审核的 LLM 标注)定义——直接自动补签等于把用户情绪固化为规范。
2.  **信号源先验**:不同信号源的可信度不同,预分级时携带默认倾向(见下表),降低 triage 人力。
3.  **熔断单独立案**:熔断触发是设计好的保护动作,按根因聚合上报,不自动进黄金集;仅 triage 确认根因为规划缺陷/工具误调的才转正。
4.  **仓库零原始数据**:黄金集只存"脱敏后的用户话语 + 参数化租户/场景描述";原始会话留在库里,repo 只放指向它的引用。
5.  **断言最小化**:只断与根因相关的字段,禁止整句 golden answer 比对;复用现有 scorer,**不发明新断言类型**。
6.  **放弃 APM score 机制**:候选池表本身是事实源("标 score=0.0"的原设计依赖一个不存在 runId 绑定的 APM,已废弃);LangSmith 上报降级为可选旁路。

### 1. 信号与实时入池

**事件驱动**:动作发生即写候选池(无周期依赖)。"每周"只是 triage 评审节奏,不是数据搬运节奏——安全类坏例不必等一周。

新表 `badcase_candidates`(engine-py SQLAlchemy + Alembic 迁移):

| 字段 | 说明 |
|---|---|
| `signal_source` | `human_takeover` / `persona_fact_deleted` / `approval_rejected` / `thumbs_down`(v3.1)/ `circuit_breaker` |
| `conversation_ref` | 指向会话/审批单/偏好事实的引用 ID,**不复制原文** |
| `tenant_id` | 租户边界(多租户不变量) |
| `suggested_class` | LLM 预分级:`suspected_defect` / `expected_behavior` / `neutral`(携带源先验) |
| `status` | `candidate → confirmed / dismissed / converted` |
| `created_at` | 入池时间 |

**信号源与挂点**(前三个入口已在线,零契约变更):

| 信号源 | 已有挂点 | 默认先验 |
|---|---|---|
| 转人工 | `POST /api/chat/approvals` `action=start_human_takeover` → `gatekeeper.py` | 中性待判 |
| 删除偏好事实 | `DELETE /api/personas/{fact_id}` → gateway `crud.py` | **疑似缺陷**(记忆管道写入了错误事实) |
| 驳回退款 | `POST /api/approvals` `action=reject` → gateway `admin.py` | **设计行为**(HITL 正常运转,除非勾选"审批判错") |
| 踩(v3.1) | 计划新增 feedback 路由 + 前端 UI | 中性待判 |
| 熔断触发 | 图内 10 步/3 错 | 缺陷信号,**单独立案聚合**,不自动入黄金集 |

**熔断可观测化(前置)**:`resolution_status` 增加 `circuit_breaker` 取值,`global_transitions_count` / `tool_errors_count` 计数落盘 `session_metrics`——这是第三/五阶段熔断看板与根因聚合的数据前提。

### 2. 人工 Triage

*   **角色分工**:业务定性("这算不算缺陷")归**客服主管**;断言编写("正确行为是什么")归**开发**。
*   **载体**:Admin 后台新增"坏例池"模块(复用 `useAdminCrud` 套件,随 v3.1 契约修订交付);v1 过渡期用只读查询/CLI。
*   **节奏**:每周一次 triage 评审;**安全类坏例(IDOR、越权、泄密话术)走紧急通道**,不等周会。
*   **保留期**:`candidate` 90 天、`dismissed` 30 天、`converted` 完结留痕。
*   **转化门槛**:triage 界面必须展示"**原文 vs 脱敏后**"对照,人确认后才允许转 case 进仓库。

### 3. 脱敏与转化

*   **已知值替换,不做智能猜测**:脱敏时不猜正则(中文姓名误报率极高,"李宁"是品牌还是人名?),而是从 `users` / `user_addresses` 取该用户真实姓名/地址做**精确字符串替换**;不引入 NER 模型。现有 `tools_registry/scrubber.py`(手机号/证件/邮箱/银行卡)的输出直接复用。
*   **落盘**:`eval/testCases/badcase/<主题>.json`,复用现有断言机制(`javascript` scorer + `expectedTools`/`expectedIntents` 变量 + `contains`/`not-contains`),每条 case 携带 `origin` 标签。顺手将存在但未挂载的 `multi-tenant.json` 接入主配置。
*   **真实格式示例**(注意:历史文档示例中的 `select-tool` / `is-not-hallucinated` 断言类型从未存在):

```json
[
  {
    "description": "badcase-2026-09-03-记忆写入缺陷:讨论尺码后查发货被误引导向退款",
    "vars": {
      "input": "刚才我们讨论过尺码,现在告诉我为什么我的订单迟迟不发货?",
      "tenantFixture": "puma-like",
      "expectedTools": ["getOrderStatus"],
      "origin": "badcase-2026-09-03-memory-write-defect"
    },
    "assert": [
      { "type": "javascript", "value": "file://scorers/toolAccuracy.scorer.ts" },
      { "type": "not-contains", "value": "猜您想要退款" }
    ]
  }
]
```

*   **Playwright 不做自动补签(v1)**:E2E 基建(真实登录路由、globalSetup 种子数据)修复前,自动生成 Playwright 用例是空中楼阁。需要物理全链路验证的坏例进**人工 E2E 待办**。

### 4. 回归与再发布

*   **黄金集硬上限**:活跃 case ≤ **300**,进新必淘汰(按"最近未触发失败 + 场景覆盖度"加权,依据 `origin` 标签统计)。没有淘汰机制的自愈集会让 CI 慢到没人愿意跑。
*   **断言降级**:尽量用确定性断言(期望工具调用、期望字段、contains),LLM-as-judge 仅限确认缺陷的语义类 case。
*   **过绿 ≠ 发布**:修复通过黄金集只是第一阶段门槛,必须重走第二阶段 Shadow 与第三阶段金丝雀。

### 5. 环路自身度量(北极星)

没有以下三个数字,第五阶段只是数据搬运管道:

| 指标 | 定义 | 阈值 / 动作 |
|---|---|---|
| **坏例类别复发率** | 同根因类别 badcase 二次出现的比例("自愈"的直接证据) | > **10%** 触发根因复盘(上次没修干净) |
| **发现→入集时延** | 信号入池到 case 合并进黄金集 | **P50 < 7 天**(一个 triage 周期内完成转化) |
| **回归拦截率** | 坏例 case 对回归退化的拦截能力 | 季度**变异测试**抽查:revert 某个修复,对应坏例 case 应变红 |

### 6. 落地批次

| 批次 | 内容 | 契约影响 |
|---|---|---|
| **前置清理** ✅ 已落地(2026-09-03) | `/api/logs` 接 `session_metrics` 真实值(无数据处返回真实 0,不再编造 token/延迟);`/api/evals/run` 响应显式携带 `isMock: true` 并从坏例看板数据源排除 | 无 |
| **v1** ✅ 已落地(2026-09-03) | `badcase_candidates` 表(Alembic `0002`)+ 三信号点挂接入池 + 熔断落盘 `session_metrics` + `scheduler.py` 周期任务框架(outbox 对账修复 + 坏例池摘要/保留期)+ 已知值脱敏 + triage CLI(`python -m engine_py.badcase.cli`) | **零**(不动 39 路由冻结契约) |
| **v3.1** | 踩/赞 UI + feedback 路由 + Admin 坏例池 CRUD 模块 + 补 pytest 契约测试 + 更新 `.claude/rules/server-gateway.md` 路由计数 | 显式契约修订 |
| **二期** | 隐式信号(首位:"答后即转人工",信噪比高于踩)、Playwright 自动补签(待 E2E 基建修复)、周期任务迁移 Temporal Schedule(多实例部署前) | 随批评估 |

---

## 📎 附录:技术债与独立立案(2026-09-03 摸底)

1.  ~~**outbox worker 死代码(不变量级失实,单独立案)**~~ **已修复(2026-09-03,随第五阶段 v1 周期任务框架一并落地)**:原 `outbox_worker` 从未被任何入口启动、且旧实现存在"假完成"缺陷;现重构为 `process_pending_events`(SKIP LOCKED + 10s 年龄阈值 + 停滞重入队),由 `scheduler.py` 每 30s 对账补偿,并同步修正 CLAUDE.md 不变量 #3 与 `.claude/rules/agent-engine.md` §1.6 表述。
2.  **死表**:`eval_runs` / `eval_results` 定义后无任何读写,暂留;实际在用的 `eval_run_records` 数据为随机数(见第四阶段前置清理)。
3.  **E2E 基建**:`/api/auth/login` 路由不存在(测试靠 localStorage 兜底)、无 globalSetup 种子、HITL/熔断零覆盖(见第一阶段)。
4.  **失效测试**:`apps/web/tests/chatDialogueScenario.test.ts` 仍 import 已退役的 `db` / `engine` workspace 包。
