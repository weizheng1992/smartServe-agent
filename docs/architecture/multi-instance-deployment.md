# 多实例部署指南 (Multi-Instance Deployment)

> 状态:**设计文档,未实施**。当前部署模式为单实例(gateway ×1 + worker ×1)。
> 本文盘点存量单实例假设、给出迁移方案与开关顺序,供真正横向扩容时立项使用。
> 挂账来源:CLAUDE.md 核心架构不变量 #3、`engine_py/scheduler.py` 模块文档字符串。

## 1. 为什么现在不能直接多实例

两个**硬缺口**会在第二个实例上线的那一刻静默断裂,其余组件要么天然安全、要么幂等空转:

| # | 缺口 | 位置 | 断裂表现 |
|---|------|------|----------|
| 1 | 周期任务调度单实例假设 | `engine_py/scheduler.py`(随 `bun run worker` 入口启动) | 每个实例都跑 outbox 对账(30s)+ 坏例池摘要(6h);对账因行锁不重复派发,但摘要/保留期任务重复空转,日志与摘要统计失真 |
| 2 | socket.io 房间为进程内存态 | `gateway_py/realtime.py:25`(`AsyncServer` 未配 `client_manager`) | 坐席连实例 A、顾客连实例 B 时同处 `thread:{id}` 房间却互不可见——`peer_joined`/`typing`/`new_message` 不跨实例广播,**人工接管双端失联** |

## 2. 已就绪组件盘点(无需改动)

- **SSE 事件流**(`gateway_py/routers/chat.py`):裸 `XREAD`(无消费组)对 Redis Streams 非破坏性尾读,每条 SSE 连接独立续读(`Last-Event-ID`),Redis 本身即扇出点。任意实例持有连接均能看到全量事件。
- **outbox 对账补偿**(`engine_py/approvals/outbox_worker.py`):`FOR UPDATE SKIP LOCKED` 行级互斥,多实例并发扫描不会重复捞取同一事件;`processing` 停滞 >5min 重入队机制在实例崩溃场景仍成立。
- **审批防重复派发**(`engine_py/approvals/gatekeeper.py`):`lock:approval:{id}` Redis SETNX(5s TTL)跨实例互斥 + `waiting` 状态机守卫(已处理工单二次提交返回 400)。注意:进程内 `_local_locks` 仅是 Redis 不可用时的降级,多实例下该降级不跨进程——**多实例部署要求 Redis 必须在线**。
- **本地 embedding 串行护栏**(`engine_py/llm/chat.py` `_SerializedEmbeddings`):进程内锁按设计生效——段错误来自同进程两线程同时 encode,跨进程 torch 运行时相互独立。多实例反而降低单进程并发压力,无需任何改动。
- **Temporal worker 本体**:同 task queue(`agent-tasks-py`)多 worker 是 Temporal 原生水平扩容模型,活动天然分摊。缺的只是挂在 worker 入口的 scheduler(见缺口 #1)。
- **Fast-Path 恢复派发**:审批动作发生在处理 admin HTTP 请求的那个 gateway 实例上,`run_agent` 就地执行、事件走 Redis Streams 广播——任意实例处理等价。
- **确定性 JobId** `job_resume_${approvalId}`:跨实例幂等锚点不变。

## 3. 迁移方案

### 3.1 缺口 #1:scheduler 单例化(三选一,推荐 C)

| 方案 | 做法 | 适用 |
|------|------|------|
| A. 环境变量阉割 | 其余实例 `ENGINE_SCHEDULER_ENABLED=0`,仅一个实例保留 | **day-1 停损方案**,零代码;缺点是"哪个实例开着"成为部署拓扑隐知识,该实例挂了兜底也挂 |
| B. Redis 分布式锁 | 每个 tick 前抢 `SET scheduler:{task} NX PX{interval}`,抢到才执行 | 改动小(~20 行);锁过期/脑裂语义要谨慎,适合不想动 Temporal 的过渡期 |
| C. Temporal Schedule(推荐) | 把 `process_pending_events` 与 `run_badcase_digest` 注册为 Temporal Schedule(`overlap_policy=SKIP`),scheduler 退场或仅 dev 模式保留 | Temporal 已是编排主干,Schedule 的 exactly-once 启动语义 > 自研锁;dev/影子期(Temporal 离线)仍走本地 scheduler 作回退 |

推荐路径:**上线多实例当天先用 A 止损 → 迭代内落 C**;B 仅在 Temporal 上云遥遥无期时考虑。

### 3.2 缺口 #2:socket.io 跨实例广播

`realtime.py` 的 `AsyncServer` 加 Redis client manager:

```python
sio = socketio.AsyncServer(
    async_mode="asgi",
    client_manager=socketio.AsyncRedisManager(settings.redis_url, channel="socketio_agent_all"),
    cors_allowed_origins="*",
    namespaces=NAMESPACE,
)
```

效果:`emit` 经 Redis pub/sub 复制到所有实例,`thread:{id}` 房间跨实例成立,`joined_room`/`peer_joined`/`typing`/`new_message` 全部恢复双端可达。注意:

- channel 名要显式指定并与旧单实例滚动升级期兼容(同 channel 才互通);
- `AsyncRedisManager` 的 Redis 断连 = 实时通道降级期,需与 SSE 一样有容灾日志,不阻断 HTTP 主链路;
- 契约套件 `test_realtime_contract.py` 跑在单实例下,跨实例广播行为需补一条双 live_server 的集成用例(dev 环境起两个端口)。

### 3.3 配套事项(扩容前置检查清单)

1. **Redis 从"可选依赖"升级为"硬依赖"**(审批跨实例锁、SSE 事件源、socket.io 复制通道、发件箱对账竞争回避全在其上)——上 HA Redis,并把它写进部署 SLA。
2. **PostgreSQL 连接池预算**:每实例独立 engine 池,`max_connections` 按 实例数 × (engine 池 + merchant reader 池 + gateway 池) 估算,预留 pgbouncer 余量。
3. **`.env` 环境变量矩阵**:`AI_*` 全量、`ENGINE_SCHEDULER_ENABLED`(方案 A 下按实例区分)、`TEMPORAL_ADDRESS` 指向集群而非本机。
4. **uvicorn 单 worker 假设**:`dev:server` 为 `--reload` 单进程;生产多进程/多容器时,进程内 `lru_cache` 单例(embedding、chat model、merchant reader engine)按进程各一份,内存与权重加载耗时 ×N,冷启动预算重估。
5. **灰度验证脚本**:现有 `scripts/debug/refund-approval-e2e.sh` 直接复用——多实例下打散到不同实例发起聊天与审批,断言不因实例拓扑变化而变红。

## 4. 开发约定(多实例心智,从现在开始)

新增代码默认遵守,避免继续积累单实例假设:

1. **新周期任务**:一律注册进 `scheduler.default_tasks()` 并保持单次执行幂等(状态迁移/按龄删除类天然满足);写明重复执行的副作用评估。
2. **新实时事件**:socket.io 事件必须走 `sio.emit`(经 client manager 可复制),禁止用进程内 emitter/全局 dict 承载跨请求状态。
3. **新分布式互斥**:优先复用 Redis SETNX + TTL 模式(参照 gatekeeper),锁粒度对齐业务键(如 `lock:approval:{id}`)。
4. **进程内存态**:仅允许作 Redis 故障降级(gatekeeper `_local_locks` 模式),且注释标明"多实例下不互斥"。
5. **JobId 确定性**:跨实例幂等锚点继续遵守 `${业务键}_${确定性ID}` 命名(如 `job_resume_${approvalId}`)。

## 5. 决策记录

- 2026-09-05:盘点成文;方案 A(环境变量单实例)为多实例上线日止损预案,C(Temporal Schedule)为目标态。
- socket.io `AsyncRedisManager` 为缺口 #2 唯一候选方案,无需自研。
