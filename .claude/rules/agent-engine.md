---
description: LangGraph 状态机决策图、Temporal 工作流编排、双层记忆隔离、多模态视觉感知与发件箱引擎规范
paths: ["packages/engine/**/*"]
---

# 智能体核心决策引擎规范 (Agent Engine)

本工作区是整个平台的核心中枢，负责 LangGraph DAG 状态图调度、四象限记忆体系、双层客户画像隔离、多模态视觉定责、Contextual RAG 检索、审批门禁与 Temporal 分布式工作流。

## 1. 核心架构与拓扑流程

### 1.1 状态转移拓扑 (Graph Topology)

- **状态总线**：基于 `packages/engine/src/graph/state.ts` 中的 `AgentStateAnnotation` 承载全局状态（`threadId`、`intents`、`taskPlan`、`shortMemory`、`longMemoryFacts`、`output`、`cards` 等）。
- **DAG 状态转移图**：
  - 起点 ➔ `triage`（意图分流与多模态感知）
  - 分流分支：日常寒暄/简单单意图走**极速直达旁路**直接路由至 `finish`；复杂多意图路由至 `planner`。
  - 核心执行环：`planner` ➔ `merge` ➔ 循环 [`executor` ⇄ `validator`] ➔ 校验通过进入 `finish`；未通过或需回溯时退回 `executor`。
- **双模运行引擎**：优先连接 Temporal 工作流（端口 `7239`）编译执行 `agentWorkflow`；当 Temporal 离线时平滑回退至本地 LangGraph 仿真模拟器。

### 1.2 分流与意图消歧 (Triage & Disambiguation)

- **第一道防线（语义去重旁路）**：计算与前序查询的余弦相似度（$\ge 0.98$），直接命中缓存返回。
- **低置信度归档与槽位消歧**：分类置信度不足时，自动写入 `low_confidence_logs` 表，并触发 `slotDisambiguationEngine.ts` 引导用户补充缺失关键槽位。
- **多模态视觉定责流水线 (`visionAnalyzerService.ts`)**：
  - 视觉 LLM 与启发式规则双通道并发判断。
  - 快递面单/包装条形码 OCR 实体提取（如 `ORD-XXXXX`、`SFXXX`），并提取至后续工具执行。
  - 商品成色与破损智能定责评级（`negligible` / `minor` / `severe`）。
  - 内置 1500ms `Promise.race` 容灾超时机制，超时自动降级。

### 1.3 四象限记忆与双层画像隔离 (Quad-Memory & Dual-Tier Persona)

- **短期记忆 (`ShortMemory`)**：基于 `messages` 物理表读取最近 10 轮对话，内存为空时触发自愈补全。
- **长期偏好记忆 (`LongMemory`)**：大模型提取用户习惯，向量化存储至 `long_memory_facts`，检索时基于余弦相似度（硬阈值 $\ge 0.65$）召回 Top-5。
- **情境记忆 (`EpisodicMemory`)**：关键业务事件按重要性（1-10分）向量化落盘。
- **任务记忆 (`TaskMemory`)**：持久化保存挂起和未完成的任务规划步骤。
- **双层画像物理隔离 (`AgentMemoryEngine` & `contextAssemblyPipeline.ts`)**：
  - 严格区分 `scope: 'global'`（客观生理属性，如脚长/过敏史）与 `scope: 'tenant'`（品牌专属偏好/会员积分）。
  - 上下文装配召回时严格限定：`WHERE user_id = $1 AND (scope = 'global' OR business_id = $2)`，严禁跨租户泄漏画像。

### 1.4 Contextual RAG 知识检索 (`contextualRag.ts`)

- **上下文增强切片**：文档入库时通过 `chunker.ts` 切片，并由大模型为每个切片前缀生成包含全局文档背景的 Contextual Summary。
- **租户物理隔离检索**：向量检索与 SQL 过滤强制附带 `WHERE business_id = :tenantId`，物理阻断跨租户政策混淆。

### 1.5 审批门禁与事务发件箱 (`approvalGatekeeper.ts` & `approvalOutboxWorker.ts`)

- **HITL 安全挂起**：退款、改地址等高危动作触发挂起，记录写入 `pending_approvals`。
- **事务发件箱（Transactional Outbox）**：审批动作与 `approval_outbox_events` 事件在同一数据库事务中原子提交。
- **确定性去重恢复**：恢复任务采用确定性标识 `job_resume_${approvalId}`，结合 `approvalOutboxWorker` 轮询重试机制，彻底杜绝丢单与重复退款。

---

## 2. 编码与维护准则

1. **确定性拓扑**：修改 `planner.node.ts` 时必须严格声明 `dependencies` 依赖数组，供 `stepExecutionEngine.ts` 调度 `Promise.allSettled` 并行执行。
2. **统一调用入口**：所有 LLM 与向量 Embedding 调用必须统一走 `packages/engine/src/llm/callLLMWithRetry.ts`，内置重试、超时与 Token 统计。
3. **中文本地化日志**：Temporal Activity 与执行节点产生的所有用户态进度事件必须使用标准中文本地化文本。
4. **无异常冷启动**：记忆检索、租户配置加载等底层逻辑必须兼容空数据与冷启动，严禁未捕获抛错阻断状态机。
