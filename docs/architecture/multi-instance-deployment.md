# 多实例部署指南 (Multi-Instance Deployment)

> 状态:**设计文档,未实施**。当前部署模式为单实例(gateway ×1,周期任务随 lifespan;ADR-0007 后无独立 worker 进程)。
> 本文盘点存量单实例假设、给出迁移方案与开关顺序,供真正横向扩容时立项使用。
> 挂账来源:CLAUDE.md 核心架构不变量 #3、`engine_py/scheduler.py` 模块文档字符串。

## 1. 为什么现在不能直接多实例

两个**硬缺口**会在第二个实例上线的那一刻静默断裂,另有一个**软缺口**(数据陈旧化,不致失联),其余组件要么天然安全、要么幂等空转:

| # | 缺口 | 位置 | 断裂表现 |
|---|------|------|----------|
| 1 | 周期任务调度单实例假设 | `engine_py/scheduler.py`(随 gateway lifespan 启动,ADR-0007) | 每个实例都跑 outbox 对账(30s)+ 坏例池摘要(6h);对账因行锁不重复派发,但摘要/保留期任务重复空转,日志与摘要统计失真 |
| 2 | socket.io 房间为进程内存态 | `gateway_py/realtime.py:25`(`AsyncServer` 未配 `client_manager`) | 坐席连实例 A、顾客连实例 B 时同处 `thread:{id}` 房间却互不可见——`peer_joined`/`typing`/`new_message` 不跨实例广播,**人工接管双端失联** |
| 3 | 购物车 L1 进程缓存无跨实例失效 | `engine_py/tools_registry/mall_domain.py`(`_cart_storage` 读缓存 + Redis 写穿透,2026-09-08 起) | 实例 A 缓存某用户车后,实例 B 的写入只落 Redis 不清 A 的缓存:A 侧播报陈旧车况;更糟是**丢失更新**——A 基于陈旧快照追加后整表覆盖 Redis,B 在窗口内的累量被冲掉 |

## 2. 已就绪组件盘点(无需改动)

- **SSE 事件流**(`gateway_py/routers/chat.py`):裸 `XREAD`(无消费组)对 Redis Streams 非破坏性尾读,每条 SSE 连接独立续读(`Last-Event-ID`),Redis 本身即扇出点。任意实例持有连接均能看到全量事件。
- **outbox 对账补偿**(`engine_py/approvals/outbox_worker.py`):`FOR UPDATE SKIP LOCKED` 行级互斥,多实例并发扫描不会重复捞取同一事件;`processing` 停滞 >5min 重入队机制在实例崩溃场景仍成立。
- **审批防重复派发**(`engine_py/approvals/gatekeeper.py`):`lock:approval:{id}` Redis SETNX(5s TTL)跨实例互斥 + `waiting` 状态机守卫(已处理工单二次提交返回 400)。注意:进程内 `_local_locks` 仅是 Redis 不可用时的降级,多实例下该降级不跨进程——**多实例部署要求 Redis 必须在线**。
- **本地 embedding 串行护栏**(`engine_py/llm/chat.py` `_SerializedEmbeddings`):进程内锁按设计生效——段错误来自同进程两线程同时 encode,跨进程 torch 运行时相互独立。多实例反而降低单进程并发压力,无需任何改动。
- **Fast-Path 恢复派发**:审批动作发生在处理 admin HTTP 请求的那个 gateway 实例上,`run_agent` 就地执行、事件走 Redis Streams 广播——任意实例处理等价。
- **确定性 JobId** `job_resume_${approvalId}`:跨实例幂等锚点不变。
- **购物车持久性**(`engine_py/tools_registry/mall_domain.py`,2026-09-08 起):真实状态写穿透 Redis(`agent:cart:{userId}`),进程缓存仅一级读缓存、Redis 故障静默降级纯内存。**单实例重启不失忆**已由 `tests/test_cart_persistence_regression.py` 钉死;跨实例陈旧读见上表缺口 #3(多实例前须给缓存加短 TTL 或直读)。

## 3. 迁移方案

### 3.1 缺口 #1:scheduler 单例化(两选一,推荐 B)

> 2026-09-30 改判(ADR-0007):Temporal 执行路线退役,原方案 C(Temporal Schedule)随路线一并退场;若未来重引入 Temporal 须新立 ADR,届时可重启该方案。

| 方案 | 做法 | 适用 |
|------|------|------|
| A. 环境变量阉割 | 其余实例 `ENGINE_SCHEDULER_ENABLED=0`,仅一个实例保留 | **day-1 停损方案**,零代码;缺点是"哪个实例开着"成为部署拓扑隐知识,该实例挂了兜底也挂 |
| B. Redis 分布式锁(推荐) | 每个 tick 前抢 `SET scheduler:{task} NX PX{interval}`,抢到才执行 | 改动小(~20 行);锁过期/脑裂语义要谨慎;多实例部署本就要求 Redis 硬依赖(§3.3.1),锁设施是现成的 |

推荐路径:**上线多实例当天先用 A 止损 → 迭代内落 B**。

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
3. **`.env` 环境变量矩阵**:`AI_*` 全量、`ENGINE_SCHEDULER_ENABLED`(方案 A 下按实例区分)。
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
- 2026-09-08:购物车由纯进程内存改为 Redis 写穿透(单实例重启失忆曾致「播报成功但购物车计数不变」——引擎失忆后重加,前端按 skuCode 合并时 quantity 原值覆盖原值);同时登记缺口 #3(L1 缓存跨实例陈旧读)。
- 2026-09-30:ADR-0007(Temporal 执行路线退役)——scheduler 宿主由 worker 进程改挂 gateway lifespan,原方案 C(Temporal Schedule)随退场,目标态改为 B(Redis 分布式锁);缺口清单由三减二(Temporal worker 扩容项消失)。

## 6. live-desk-rework 重构的多实例兼容点清单(2026-09-28,wayfinder 票 15)

客服工作台重构(`docs/architecture/live-desk-rework.md`)引入一批新的实时协作组件。逐项核对结果:**除一项设计约束须在 spec 落地时遵守外,其余要么结构性安全、要么由既有缺口方案管辖**;且「真源归一 DB」的主决策整体**降低**了单实例债(旧链路的接管状态散落在前端进程态,新设计全量落库)。

| # | 项 | 多实例下的失效模式 | 扩容期改造方案 | 本期是否已规避 |
|---|----|--------------------|----------------|----------------|
| 1 | socket.io 房间广播(即存量缺口 #2) | 坐席连 A、顾客连 B,同房间互不可见,双端失联 | `AsyncRedisManager`(§3.2 既有方案,不变) | **未规避,零新增债**:方案既有且本期设计不加深它;坐席面迁 socket 的前提是按 §3.2 配 client manager |
| 2 | `realtime.py` `connected_clients` 进程内存态(sid→身份/房间记录) | **无失效**:该表只按本进程 sid 读写,而 socket.io handler 永远跑在连接属主进程上——`_staff_of`/`_tenant_mismatch` 的跨实例读不存在 | 无需改造。**开发约束**:禁止未来加「跨实例查询该表」的用法(如全局在线坐席列表——在线态一律走 Redis presence,勿用此表) | 已规避(结构性安全) |
| 3 | 掉线超时自动释放(票 04 设计) | 计时器为进程内 asyncio 任务:持计时器的实例崩溃 → 释放永不触发;叠加「AI 暂停闸=接管期不建作业」,该会话 **AI 永久停摆**(比现状更糟——现状至少 AI 还在答) | **权威路径必须是 DB deadline + scheduler 扫描**(与排队超时回落共用扫描回路,票 06 已定档):释放判定=幂等条件 UPDATE(`WHERE status='human_takeover' AND deadline < NOW()`),重复扫描天然无害;进程内计时器只可作 UX 快路径(提前触发),不可作唯一路径 | **未规避 → 设计约束**:spec(票 12)须按「扫描为权威、计时器为提示」落;不另立执行票(未实现期,修正发生在设计层) |
| 4 | 排队超时回落 AI(票 06) | 多实例重复扫描、重复回落 | 扫描动作=幂等条件 UPDATE(WHERE 排队态+超时),重复执行第二遍 0 行影响;任务注册进 `scheduler.default_tasks()`(§4 约定 1),scheduler 本身的单实例假设由缺口 #1 方案 A/C 管辖 | 已规避 |
| 5 | Redis presence TTL 心跳(票 06 在线态) | 无——共享存储,任意实例的心跳写同一 key,读侧天然见全量 | Redis 升硬依赖(§3.3.1 已盘) | 已规避 |
| 6 | 自选认领原子 UPDATE(票 06 防抢单) | 无——`WHERE status='waiting'` 条件更新的行锁跨实例成立,双实例同抢必有一方 0 行 | — | 已规避 |
| 7 | `ws:events` Redis 通道只发不收(遗留) | 发布侧经 Redis pub/sub,**天然跨实例**;风险在未来消费方若误用进程内队列承接 | 顾客面推送(票 09 预留位)接入时以 Redis 订阅消费;pub/sub 掉线窗口由保留的轮询兜底(两步撤梯)覆盖 | 非本期缺口;设计注记入 spec |

**结论**:重构四能力(分配/上下文/可靠性/审批联动)的数据决策(真源 `threads.status+assigned_operator_id`、认领原子 UPDATE、presence TTL、`unread_count` 存量列、`thread_notes` 物理隔离库、`clientMsgId` 幂等)全部落在共享存储,无新增进程内存态单点;唯一须守住的设计约束是 #3 的「扫描权威、计时器提示」。
