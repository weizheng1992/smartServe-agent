---
description: LangGraph 状态机决策图、Skills 技能开放架构、Temporal 工作流编排、四象限记忆与双层画像隔离规范
paths: ["services/engine-py/**/*"]
---

# 智能体核心决策引擎规范 (Agent Engine)

本服务是整个平台的核心中枢（`services/engine-py/src/engine_py/`），负责 LangGraph DAG 状态图调度、Skills 技能分发、四象限记忆体系、双层客户画像隔离、多模态视觉定责、Contextual RAG 检索、审批门禁与 Temporal 分布式工作流。行为规格以退役的 TS 实现为基线，由影子双跑（`shadow/`）与 pytest 契约测试钉死。

## 1. 核心架构与拓扑流程

### 1.1 状态转移拓扑 (Graph Topology)

- **状态总线**：基于 `graph/state.py` 的 `AgentState` 承载全局状态（`thread_id`、`intents`、`task_plan`、`short_memory`、`long_memory_facts`、`output`、`cards` 等；Python 侧 snake_case，但 `task_plan` 内部键与 SSE 载荷保持 camelCase 冻结契约）。
- **DAG 状态转移图**：
  - 起点 ➔ `triage`（意图分流与多模态感知）
  - 分流分支：日常寒暄/简单单意图走**极速直达旁路**（`executor_fast_path.py`）直接路由至 `finish`；复杂多意图路由至 `planner`。
  - 核心执行环：`planner` ➔ `merge` ➔ 循环 [`executor` ⇄ `validator`] ➔ 校验通过进入 `finish`；未通过或需回溯时退回 `executor`。
- **双模运行引擎**：优先连接 Temporal 工作流（端口 `7239`，队列 `agent-tasks-py`）编译执行 `temporal/workflows.py`；当 Temporal 离线时平滑回退至本地 LangGraph 仿真模拟器。
- **事件主干**：用户态进度事件经 `event_bus.py` 写入 Redis Streams（INCR 序号 + XADD maxlen），网关 SSE 直接以该流为事件源。

### 1.2 Skills 技能分发与开放集成架构 (Skills Pipeline)

- **技能基类 (`skills/base_skill.py`)**：所有业务技能（如 `OrderRefundSkill`）必须继承 `BaseSkill`，提供统一的元数据、依赖工具声明、SOP 策略以及多阶段执行管道（`validate` ➔ `pre_execute` ➔ `execute` ➔ `post_execute`）。
- **执行器调度 (`graph/nodes/step_execution_engine.py`)**：
  - 优先通过 Skills 注册表检索匹配的 Skill 实例执行业务逻辑；
  - 若无特定 Skill，则回退至标准 Tool 工具分发执行（`asyncio.gather` 并行调度依赖无关节点）。
- **租户级技能配置重载 (Tenant Skill Config Overrides)**：
  - 支持多租户在 `TenantBusinessConfig` 中动态覆写技能参数（启用/禁用、退款限额阈值 `maxAutoRefundAmount`、退款有效窗口 `maxRefundDays`、强制人工审核开关 `requireApproval`、自定义通知 Webhook 等）。

### 1.3 分流与意图消歧 (Triage & Disambiguation)

- **第一道防线（语义去重旁路）**：`triage/semantic_cache.py` 计算与前序查询的余弦相似度（≥ 0.98），直接命中缓存返回。
- **低置信度归档与槽位消歧**：分类置信度不足时，自动写入 `low_confidence_logs` 表，并触发 `triage/slot_extractor.py` 引导用户补充缺失关键槽位。
- **多模态视觉定责**：视觉 LLM 与启发式规则双通道并发判断；快递面单/包装条形码 OCR 实体提取（如 `ORD-XXXXX`、`SFXXX`），商品成色与破损智能定责评级（`negligible` / `minor` / `severe`），内置 1500ms 容灾超时自动降级。

### 1.4 四象限记忆与双层画像隔离 (Quad-Memory & Dual-Tier Persona)

- **短期记忆 (`memory/short_memory.py`)**：基于 `messages` 物理表读取最近 10 轮对话，内存为空时触发自愈补全。
- **长期偏好记忆 (`memory/long_memory.py`)**：大模型提取用户习惯，向量化存储至 `long_memory_facts`，检索时基于余弦相似度（硬阈值 ≥ 0.65）召回 Top-5。
- **情境记忆 (`memory/episodic_memory.py`)**：关键业务事件按重要性（1-10分）向量化落盘。
- **任务记忆 (`memory/task_memory.py`)**：持久化保存挂起和未完成的任务规划步骤。
- **双层画像物理隔离**：
  - 严格区分 `scope: 'global'`（客观生理属性，如脚长/过敏史）与 `scope: 'tenant'`（品牌专属偏好/会员积分）。
  - 上下文装配召回时严格限定：`WHERE user_id = :1 AND (scope = 'global' OR business_id = :2)`，严禁跨租户泄漏画像。

### 1.5 Contextual RAG 知识检索 (`rag/contextual_rag.py`)

- **上下文增强切片**：文档入库时切片，并由大模型为每个切片前缀生成包含全局文档背景的 Contextual Summary。
- **租户物理隔离检索**：向量检索与 SQL 过滤强制附带 `WHERE business_id = :tenant_id`，物理阻断跨租户政策混淆。

### 1.6 审批门禁与事务发件箱 (`approvals/gatekeeper.py` & `approvals/outbox_worker.py`)

- **HITL 安全挂起**：退款、改地址等高危动作触发挂起，记录写入 `pending_approvals`（ID 必须为 UUID 格式，网关校验）。
- **事务发件箱（Transactional Outbox）**：审批动作与 `approval_outbox_events` 事件在同一数据库事务中原子提交。
- **确定性去重恢复**：恢复任务采用确定性标识 `job_resume_${approvalId}`。恢复由 `process_approval_action` 的同步 Fast-Path 派发（派发失败事件留 `pending`）；`outbox_worker.process_pending_events` 为失败事件的对账补偿（`FOR UPDATE SKIP LOCKED` 防多实例重复、10s 年龄阈值避开与 Fast-Path 竞争、`processing` 停滞 >5min 重入队），由 `scheduler.py` 周期调度（30s 间隔，随 Temporal worker 入口启动，单实例假设，`ENGINE_SCHEDULER_ENABLED=0` 关闭；2026-09-03 修复接入）。

### 1.7 影子双跑与回放 (`shadow/diff.py` & `shadow/replay.py`)

- 迁移验收期工具：对冻结的 TS 基线输出做逐字段 diff 与历史流量回放；基线钉死后仅作回归参考。

### 1.8 坏例候选池与周期任务调度 (`badcase/` & `scheduler.py`,2026-09-03 第五阶段 v1)

- **半自动闭环**：信号收集/用例起草自动化，triage 定夺与入集人工化——信号**永不直接成为回归断言**。
- **信号源与先验**（`badcase/pool.py`）：人工接管 `human_takeover` / 画像事实删除 `persona_fact_deleted`（→ `suspected_defect`）/ 审批驳回 `approval_rejected`（→ `expected_behavior`）+ 熔断（`run_agent` 落盘，暂未入池）。入池接口 `record_badcase_signal` 失败静默降级（print 不吞错），**严禁阻断宿主事务**。
- **脱敏两层管道**（`badcase/redaction.py`）：库内已知值精确替换（地址/收件人/邮箱）➔ `scrubber` 正则兜底；`show` 输出"原文 vs 脱敏对照"，回归用例输入必须取脱敏侧（仓库零原始数据）。
- **triage CLI**：`python -m engine_py.badcase.cli`（list/show/triage/draft/expire）；`draft` 只产 `expectedTools`/`not-contains` 断言（断言最小化，禁整句黄金答案），带 `origin: badcase:{id}` 溯源，人工并入 `eval/testCases/` 后标 `converted`。
- **周期任务**（`scheduler.py`，随 Temporal worker 入口启动，Temporal 离线仍独立运行）：outbox 对账（30s）+ 坏例池摘要/保留期（6h）；**单实例假设**，`ENGINE_SCHEDULER_ENABLED=0` 关闭。

---

## 2. 编码与维护准则

1. **确定性拓扑**：修改 `graph/nodes/planner.py` 时必须严格声明 `dependencies` 依赖数组，供 `step_execution_engine.py` 并行调度。
2. **统一调用入口**：所有 LLM 与向量 Embedding 调用必须统一走 `llm/chat.py`（`get_chat_model` / `get_embedding_model`，lru_cache 单例）；熔断与重试为未完成 TODO。
3. **中文本地化日志**：Temporal Activity 与执行节点产生的所有用户态进度事件必须使用标准中文本地化文本。
4. **无异常冷启动**：记忆检索、租户配置加载等底层逻辑必须兼容空数据与冷启动，严禁未捕获抛错阻断状态机。
5. **环境自读取**：`config.py` 在导入时读取环境变量；任何测试基建必须先注入 `DATABASE_URL` / `REDIS_URL` 再导入 engine_py 模块。
