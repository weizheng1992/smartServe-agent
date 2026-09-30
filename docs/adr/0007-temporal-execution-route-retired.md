# ADR-0007: Temporal 执行路线退役 — 回合管线收敛为单一深模块

日期:2026-09-30。状态:已接受。
上位决策:架构审查候选卡①「回合管线 one seam two adapters」拷问定案(2026-09-30)。

## 背景

engine-py 自 TS 移植起保留双模运行引擎:本地 LangGraph 仿真(`run_agent.py` + `graph/build_graph.py`,进程内)与 Temporal 工作流(`temporal/workflows.py` + `activities.py`,队列 `agent-tasks-py`,逐节点 activity)。2026-09-30 架构审查取证:

1. **零启动方**:全仓(`services/`、`apps/`、`scripts/`)检索 `start_workflow` / `execute_workflow` / `AgentWorkflow`,唯一出现点是 `worker.py` 的 **注册**(worker 只执行、从不启动)。gateway 聊天派发是进程内 `asyncio.create_task(run_agent(job))`(chat.py),审批恢复(`job_resume_*`)与影子回放同样进程内。**没有任何代码路径启动过一次 `AgentWorkflow`**——按设计词汇表,"one adapter means a hypothetical seam; two adapters means a real one",这条第二 adapter 是假想缝。
2. **漂移实证**:Temporal 侧是整套手抄复制品而非同一模块的第二 adapter——`workflows.py` 手抄图拓扑(旁路判定、executor⇄validator 环);`activities.py` 手抄收口接线且已漂移:任务记忆只存 `task_plan`(丢 guideContext/cartContext/orderContext),无 session_metrics、无坏例池信号、无 LLM token 聚合、无 Redis 事件发布、无双降级臂;`current_status` 仍产 TS 时代伪造的 `ORD-98712 / FedEx` 假字符串。worker 入口尚有一行重复的 `create_task(start_scheduler())`(孤儿任务)。
3. **部署现状**:Temporal Server 在 dev 与 prod compose 中均为可选 profile,`dev:all` 不启动 worker;唯一真正活着的职责是 worker 进程宿主 scheduler(outbox 对账 / 接管释放 / 坏例摘要),而 scheduler 在连接 Temporal **之前**就已独立启动——宿主身份与 Temporal 毫无耦合。

## 决策

1. **退役删除** Temporal 执行路线:`engine_py/temporal/` 全包(workflows / activities / worker / `__init__`)、pyproject `worker` extra(temporalio)、`TEMPORAL_ADDRESS` / `TEMPORAL_NAMESPACE` / `TEMPORAL_TASK_QUEUE` 配置、根与 prod compose 的 temporal 服务与 `--profile temporal`、`bun run worker` / `bun run docker:temporal` 脚本。
2. **scheduler 宿主迁至 gateway lifespan**:三个周期任务随网关进程运行(开关 `ENGINE_SCHEDULER_ENABLED=0` 照旧);`dev:all` 从此自带 outbox 对账兜底,消除「审批批了没反应、对账无人跑」的开发期陷阱。
3. **回合管线收敛为单一深模块**:`run_agent(job) -> dict` 是一回合的唯一接口(gateway 派发 / 审批恢复 / 影子回放三个调用方共用);图后收口(卡片合成 → 记忆写入 → task 记忆 → 坏例信号 → token 聚合 → assistant 落库)内聚为私有内部缝,公开接口零变化。

## 后果

- 漂移 bug 类被**消灭**而非测试钉死:收口接线只剩一份实现,「双路不同步」在结构上不可能复发。三个调用方、契约测试、坏例池、计费遥测全部只走真实管线。
- 放弃一条**从未启用**的 job 级持久化/重试保险;git 历史(`revert` 本 ADR 对应提交)与本文档即完整考古路径。
- **重引入条款**:任何 resurrect(整回合 activity、逐节点编排、Temporal Schedule 宿主周期任务等任何形态)须重新立项并新立 ADR,不得直接 revert 了事——重引入时必须回答本 ADR 的取证问题:启动方是谁、第二份收口接线如何保证不漂移。
- `docs/architecture/multi-instance-deployment.md` 中「scheduler 单例 → 迁移 Temporal Schedule」的扩容前置项相应改判:多实例化时为周期任务另立分布式锁或编排裁决,不再默认 Temporal。
- 词汇表固化(CONTEXT.md):**回合管线** = `run_agent` 的角色定义(一回合 = 一个深模块;内部:入口预装配 / 图执行 / 收口持久化);**收口** = 图后持久化段,内部缝名。

## 关联

- 架构审查报告(2026-09-30):候选卡①(本 ADR)、卡③审批金额政策、卡④商户 reader 私缝等待探。
- `docs/deployment.md` 的 dev Temporal 启动指南随本 ADR 废止相应章节。
