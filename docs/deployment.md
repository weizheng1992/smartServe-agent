# 启动与部署指南(dev Temporal 与线上)

> 覆盖两件事:**开发环境启动流程**(含 Temporal dev 集群)与**线上部署流程**。
> 多实例横向扩容另见 `docs/architecture/multi-instance-deployment.md`。
> 最后核对:2026-09-05(2.3.5,commit c3d14f8 后的代码事实)。

## 0. 先讲清拓扑真相(避免被历史文档误导)

README 与早期文档有"优先连 Temporal、离线回退本地仿真"的表述,那是 TS 时代语义(TS 网关会 `start_workflow`)。**Python 迁移后的现实**:

```text
请求执行路径(生产真路径):
  前端 SPA → gateway-py /api/chat → asyncio.create_task(run_agent(job))   ← chat.py:68
                                       └─ 进程内 LangGraph 直跑(triage→planner→…→finish)

Temporal 的现实角色:
  worker 进程(bun run worker)同时干两件事:
    ① scheduler 载体:outbox 对账(30s)+ 坏例池摘要(6h)   ← 有真实流量,必启
    ② 注册 AgentWorkflow 于队列 agent-tasks-py             ← 全仓无 start_workflow
                                                            调用方,工作流休眠待命
```

结论:**Temporal Server 当前不在请求关键路径上**。dev 可以完全不启 Temporal(对账/摘要照常,worker 退化为纯周期任务进程);线上最小形态甚至可以不部署 Temporal 集群,只跑 worker 进程。§3 给出未来把执行迁回 Temporal 的启用步骤。

## 1. 开发环境启动流程

### 1.1 前置

- Node/bun、uv(python 3.12+,共享 venv `services/.venv`)、Docker Desktop
- 根目录 `.env`(从 `.env.example` 复制;`dev:server`/`worker`/`db:push`/`db:seed` 经 `uv run --env-file ../../.env` 自动注入,`config.py` 只读 `os.environ`)
- LLM 必须:`AI_*` 系列缺省值指向无效地址,缺失时所有 LLM 节点以 `Connection error` 失败(见 README 环境变量说明)

### 1.2 基础设施(docker compose)

| 命令 | 起什么 | 说明 |
|------|--------|------|
| `bun run docker:up` | PostgreSQL 15(5432,库 agent_platform/agent_merchant)+ Redis 7(6379,带密码) | **必启**;两者是网关与引擎的硬依赖 |
| `bun run docker:temporal` | Temporal dev 集群(profile `temporal`) | **可选**;详见 1.4 |

Temporal 服务定义(`docker-compose.yml`):镜像 `temporalio/dev-server:latest`,容器内 frontend 7233 映射宿主机 **7239**、UI **8233**(`http://localhost:8233`)。单进程 dev server(SQLite 持久化于容器内),**仅供开发,不可生产**。

### 1.3 启动顺序与依赖矩阵

```bash
bun run docker:up        # ① PG + Redis(一切的前置)
bun run db:push          # ② Alembic 迁移(engine-py 内执行)
bun run db:seed          # ③ 播种(engine + 三方 + 商户,按需)
bun run dev:server       # ④ gateway :4000(前端 web/admin 的 API 依赖)
bun run worker           # ⑤ scheduler 载体(对账/摘要;dev 常忘,见下)
bun run dev:web / dev:admin / dev:merchant   # ⑥ 前端 3000/3001/3005
```

**dev 常踩坑清单**:

1. **只跑 `dev:all` 不跑 `worker`** → 发件箱对账兜底不在场,审批 Fast-Path 失败时无补偿(2.3.3 事故的放大因素之一)。依赖审批链路调试时**必须**另开终端跑 `bun run worker`。
2. **改 engine-py 后网关不热重载**:uvicorn `--reload` 不监视 engine-py 目录,改完需 `touch services/gateway-py/src/gateway_py/main.py` 触发重载。
3. **worker 依赖安装**:`temporalio` 在 engine-py 的 `worker` extra 里。注意 uv workspace 共享 venv——在单个成员里执行精确 `uv sync --extra worker` 会剥掉另一成员(gateway-py)的包;补装后到 `services/gateway-py` 里跑一次非精确 `uv run python -c "import uvloop"` 之类即可恢复。temporalio 解析到 ≥1.32 时 API 已变(`Connection` 并入 `Client.connect`),worker.py 已适配,勿回退。
4. **端口错位**:配置默认 `TEMPORAL_ADDRESS=127.0.0.1:7239`(宿主机映射端口),不是 Temporal 惯例的 7233。自建集群或 CLI 时对准 7239,或改 env。

### 1.4 两种 dev 模式

| 模式 | 操作 | 适用 |
|------|------|------|
| 无 Temporal(默认) | 不跑 `docker:temporal` | 全部业务功能可用;worker 启动时打印"无法建立 Temporal 连接"告警后继续,周期任务照常(设计内降级,非故障) |
| 带 Temporal | `bun run docker:temporal` + `bun run worker` | 验证 workflow/activity 注册、UI 里观察队列 `agent-tasks-py`、为 §3 启用做开发 |

## 2. 线上部署流程

### 2.1 部署形态与进程清单

| 组件 | 产物 | 进程 | 副本 |
|------|------|------|------|
| web / admin / merchant | `bun run build` 静态产物(Vite SPA) | 静态托管/CDN,Nginx 反代 `/api`、`/spi` 到网关 | 任意 |
| gateway-py | uv sync 后的 `gateway_py.main:app` | `uvicorn gateway_py.main:app --host 0.0.0.0 --port 4000 --workers N`(**无 --reload**) | ≥1(多实例见 §2.7) |
| engine worker | 同一 uv 环境 | `python -m engine_py.temporal.worker`(生产常驻;承载 scheduler) | **恰好 1**(多实例需先读 §2.7) |
| PostgreSQL | 版本 ≥15,两库 agent_platform + agent_merchant | 托管/自建 | HA |
| Redis | ≥7 | 托管/自建 | **HA(硬依赖)**:SSE 事件源、审批跨实例锁、发件箱对账竞争回避全在其上 |
| Temporal | 见 2.2 三选一 | — | 按路线 |

### 2.2 Temporal 线上路线(三选一)

| 路线 | 做法 | 适用 |
|------|------|------|
| A. 暂不部署(最小形态) | 不部署任何 Temporal;worker 进程照跑(启动告警后降级为纯周期任务) | **当前功能集下的合法选择**——请求路径不走 Temporal(§0),worker 的 scheduler 职责不依赖 Temporal 在线 |
| B. Temporal Cloud | env 指向云地址 + mTLS/API key;`TEMPORAL_NAMESPACE` 按分配填写 | 推荐的"要 Temporal"路线,零运维 |
| C. 自托管集群 | 官方 docker-compose / Helm(temporalio/auto-setup + 独立 PG/Cassandra 可选 ES);frontend 地址填进 `TEMPORAL_ADDRESS` | 有平台运维能力时;**dev-server 镜像禁止生产** |

### 2.3 发布步骤(按序)

```bash
# ① 依赖与构建
cd services && uv sync                     # workspace 两成员齐装
cd .. && bun install && bun run build      # 前端三产物
bun run lint && bun run biome:check        # 门禁(按 CI 配置)

# ② 数据库(对新环境;滚动发布只跑迁移)
bun run docker:up                          # 或指向既有 PG
bun run db:push                            # alembic upgrade head
bun run db:seed                            # 仅首次/演示环境;生产按需

# ③ 起服务(顺序:基础设施 → 网关 → worker → 前端流量切入)
uvicorn gateway_py.main:app --host 0.0.0.0 --port 4000 --workers 2   # gateway
python -m engine_py.temporal.worker                                  # worker(恰好1)
# 前端产物上线,Nginx /api、/spi 反代至 :4000
```

### 2.4 就绪与验收检查

| 检查 | 命令/位置 | 期望 |
|------|-----------|------|
| 网关存活 | `GET /api/health` | `{"success": true}` |
| worker scheduler 在线 | worker 日志 | `[Scheduler] 周期任务就绪: outbox_reconcile(间隔 30s)` |
| 审批闭环 E2E | `scripts/debug/refund-approval-e2e.sh` | GREEN(店铺订单 REFUNDED + outbox completed) |
| Temporal(路线 B/C) | UI :8233 或 Cloud 页面 | 队列 `agent-tasks-py` 有 worker 注册 |
| 契约套件 | `bun run test:eval` | 全绿(密封 testcontainers,裸机可跑) |

### 2.5 环境变量矩阵(Temporal/编排相关)

| 变量 | 默认 | 说明 |
|------|------|------|
| `TEMPORAL_ADDRESS` | `127.0.0.1:7239` | dev 为宿主机映射端口;路线 B/C 改为集群/云地址 |
| `TEMPORAL_NAMESPACE` | `default` | Temporal Cloud 下按分配填 |
| `TEMPORAL_TASK_QUEUE` | `agent-tasks-py` | Python worker 专属队列(与 TS 基线 `agent-tasks` 物理隔离) |
| `ENGINE_SCHEDULER_ENABLED` | `1` | 多实例下单实例保留、其余置 0(方案 A 止损) |
| `AI_*` 系列 | 无有效缺省 | LLM/Embedding 必填;embedding 默认本地 bge-small-zh(进程内 torch,注意冷启动与内存预算) |

### 2.6 发布后观测与排障入口

- **审批"批了没反应"**:先查 `SELECT status, error_message FROM approval_outbox_events ORDER BY created_at DESC LIMIT 3;`,再看 worker 是否在线(对账兜底)。
- **worker 日志关键字**:`[Scheduler:outbox_reconcile] 对账扫描`(每 30s 有事件才打印,安静≠挂了;进程存活看 pid)、`[Temporal Worker Warn]`(Server 不在线,设计内降级)。
- **SSE 断流类**:Redis 可达性与 `socket_timeout=20` 不变量(阻塞命令 BLOCK 时长必须小于它)。

### 2.7 多实例

worker(因其 scheduler 职责)与 socket.io 房间是两个硬缺口,方案与前置清单整体见 `docs/architecture/multi-instance-deployment.md`,不在本页重复。**单实例网关 + 恰好一个 worker 是当前架构的安全形态**。

## 3. Temporal 执行路线的启用(未来演进,当前未启用)

若未来要把执行从"网关进程内 run_agent"迁回 Temporal 编排(获得持久化、重放、跨进程吞吐):

1. **补 submitter**:gateway-py 侧新建 temporal client,`client.start_workflow(AgentWorkflow, args=..., id=f"agent_{jobId}", task_queue=settings.temporal_task_queue)`;`chat.py:68` 的直跑改为按开关分流(env 如 `AGENT_EXEC_MODE=temporal|local`,保留 local 回退)。
2. **恢复语义对齐**:`job_resume_${approvalId}` 派发改走 `start_workflow`(同 id 幂等续跑)或 `signal_with_start`,Fast-Path 与对账 worker 各自适配。
3. **SSE 桥接**:workflow 的 `currentStatus/currentPlan/chatHistory` Query 已注册(与 TS 同名),网关侧恢复轮询推送(TS 基线 1.9.0 的 300ms 桥接模式)。
4. **scheduler 迁移**:顺势把周期任务改 Temporal Schedule(`overlap_policy=SKIP`),多实例硬缺口 #1 消解。
5. **验收**:契约套件 + `scripts/debug/refund-approval-e2e.sh` 在 temporal 模式下全绿,再切流。

启用前该路线保持现状即可——休眠的 workflow 注册没有成本,删除反而丢失 §3 的演进底座。
