# 15: data agent 内部执行编排

Type: grilling
Status: resolved
Blocked by: 09

## Question

data agent 的多步分析任务怎么编排（09 号管对外缝，本票管对内执行架构）：

- 复用现有 step 执行体系（LangGraph planner 快轨 + StepExecutionEngine + task plan + ApprovalPolicyEngine）vs 轻量单轮工具循环（一次语义解析 → 一次模板执行 → 卡片）——首版复杂度选哪档；
- 多步场景（「对比上月」「先总量再看 top5 明细」）首版是否支持，支持则计划态放哪（复用 task_memory？）；
- HITL 挂起/审批缝对只读分析是否完全不接（08 已定首版只读，理论无资金闸需求，但要确认无长任务挂起场景）；
- 演化缝：Python 沙箱深度分析（spring-ai-alibaba/DataAgent 模式：任务级容器跑生成的分析代码、资源限制、自动清理）是否列为二期评估项——与首版「只读 SQL、LLM 永不写 SQL」的边界要写清。

参照 map Notes 的 DataAgent 链接（其规划阶段带人工干预机制可借鉴）。

## Answer

决议日期 2026-09-17，用户全盘采纳推荐（Q1–Q4）。

### D1 执行骨架 = 轻量单轮小图

- data agent 图：`intake（含 PageContext/session_ctx）→ resolve（L0–L3）→ [ClarificationRequest 反问分支 | compile → execute] → 卡片组装 → SSE 流式回复`。
- **不接** StepExecutionEngine / ApprovalPolicyEngine / planner 快轨——只读分析用不上多步计划与资金闸，接入即过度工程；商城 agent 的 step 体系一行不动。
- 落点：`engine_py/analytics/` 内自建小图（09-D3），与商城图并行。

### D2 多步场景 = v1 不支持、不建计划态

- 对比类 10-D5 已排除；「先总量再 top5 明细」类引导靠反问与胶囊，不建计划态；task_memory 不接。
- 演化缝：将来需要时建 data agent 专属轻计划态，**不是**接商城 step 引擎。

### D3 HITL = 零接入

只读、单轮秒级、无长任务挂起场景。09-D3 预留的执行引擎插入位保持不动即完成预留。

### D4 Python 沙箱深度分析 = 二期评估项（边界写死）

- 它打破「LLM 永不产出执行代码」的一期铁律，必须独立评估：容器隔离、资源限制、只读数据快照、结果标注「非核验口径」。
- 触发条件：「整理计算」类长尾需求经真实问句分布（10 号场景运营数据）验证成规模。
