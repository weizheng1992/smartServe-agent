# 启动与部署指南(dev 与线上)

> 覆盖两件事:**开发环境启动流程**与**线上部署流程**。
> 多实例横向扩容另见 `docs/architecture/multi-instance-deployment.md`。
> 最后核对:2026-09-30(ADR-0007 后的代码事实)。

## 0. 先讲清拓扑真相

```text
请求执行路径(唯一路径):
  前端 SPA → gateway-py /api/chat → asyncio.create_task(run_agent(job))
                                       └─ 进程内 LangGraph 直跑(triage→planner→…→finish)

周期任务(随网关进程,ADR-0007):
  gateway lifespan 内 start_scheduler():
    outbox 对账(30s)+ 接管释放(30s)+ 坏例池摘要(6h)
```

Temporal 执行路线已于 2026-09-30 退役删除(ADR-0007:全仓零 `start_workflow` 调用方,Temporal 侧收口接线已漂移)。gateway 是回合管线(`run_agent`)与周期任务(`scheduler`)的唯一宿主;重引入持久化执行须新立 ADR(见 ADR-0007 重引入条款)。

## 1. 开发环境启动流程

### 1.1 前置

- Node/bun、uv(python 3.12+,共享 venv `services/.venv`)、Docker Desktop
- 根目录 `.env`(从 `.env.example` 复制;`dev:server`/`db:push`/`db:seed` 经 `uv run --env-file ../../.env` 自动注入,`config.py` 只读 `os.environ`)
- LLM 必须:`AI_*` 系列缺省值指向无效地址,缺失时所有 LLM 节点以 `Connection error` 失败(见 README 环境变量说明)

### 1.2 基础设施(docker compose)

| 命令 | 起什么 | 说明 |
|------|--------|------|
| `bun run docker:up` | PostgreSQL 15(5432,库 agent_platform/agent_merchant)+ Redis 7(6379,带密码) | **必启**;两者是网关与引擎的硬依赖 |

### 1.3 启动顺序与依赖矩阵

```bash
bun run docker:up        # ① PG + Redis(一切的前置)
bun run db:push          # ② Alembic 迁移(engine-py 内执行)
bun run db:seed          # ③ 播种(engine + 三方 + 商户,按需)
bun run dev:server       # ④ gateway :4000(周期任务随 lifespan 自动在场)
bun run dev:web / dev:admin / dev:merchant   # ⑤ 前端 3000/3001/3005
```

**dev 常踩坑清单**:

1. **改 engine-py 后网关不热重载**:uvicorn `--reload` 不监视 engine-py 目录,改完需 `touch services/gateway-py/src/gateway_py/main.py` 触发重载。
2. **环境变量没进进程**:`dev:server` 必须带 `--env-file ../../.env`(脚本已带;手拉 uvicorn 时易漏)。漏了 `AI_*` 会在 lifespan 的 `ensure_llm_config` 即死并点名缺失变量;DB/Redis 默认值碰巧能连,症状像管线 bug 实为 env 缺失。
3. **scheduler 关闭排障**:`ENGINE_SCHEDULER_ENABLED=0` 会整体关掉周期任务(outbox 对账/接管释放/坏例摘要);审批链路调试时确认没设它。

> 历史坑位存档:旧架构下 `dev:all` 不起 worker 进程 → 发件箱对账兜底不在场(2.3.3 事故放大因素)。ADR-0007 后 scheduler 随网关宿主,该坑已消灭。

## 2. 线上部署流程

### 2.1 部署形态与进程清单

| 组件 | 产物 | 进程 | 副本 |
|------|------|------|------|
| web / admin / merchant | `bun run build` 静态产物(Vite SPA) | 静态托管/CDN,Nginx 反代 `/api`、`/spi` 到网关 | 任意 |
| gateway-py | uv sync 后的 `gateway_py.main:app` | `uvicorn gateway_py.main:app --host 0.0.0.0 --port 4000 --workers N`(**无 --reload**;lifespan 自带周期任务) | **1**(多实例见 §2.5) |
| PostgreSQL | 版本 ≥15,两库 agent_platform + agent_merchant | 托管/自建 | HA |
| Redis | ≥7 | 托管/自建 | **HA(硬依赖)**:SSE 事件源、审批跨实例锁、发件箱对账竞争回避全在其上 |

### 2.2 发布步骤(按序)

```bash
# ① 依赖与构建
cd services && uv sync                     # workspace 两成员齐装
cd .. && bun install && bun run build      # 前端三产物
bun run lint && bun run biome:check        # 门禁(按 CI 配置)

# ② 数据库(对新环境;滚动发布只跑迁移)
bun run docker:up                          # 或指向既有 PG
bun run db:push                            # alembic upgrade head
bun run db:seed                            # 仅首次/演示环境;生产按需

# ③ 起服务(基础设施 → 网关 → 前端流量切入)
uvicorn gateway_py.main:app --host 0.0.0.0 --port 4000 --workers 2   # gateway(唯一后端进程)
# 前端产物上线,Nginx /api、/spi 反代至 :4000
```

### 2.3 就绪与验收检查

| 检查 | 命令/位置 | 期望 |
|------|-----------|------|
| 网关存活 | `GET /api/health` | `{"success": true}` |
| 周期任务在线 | gateway 日志 | `[Scheduler] 周期任务就绪: outbox_reconcile(间隔 30s)` |
| 审批闭环 E2E | `scripts/debug/refund-approval-e2e.sh` | GREEN(店铺订单 REFUNDED + outbox completed) |
| 契约套件 | `bun run test:eval` | 全绿(密封 testcontainers,裸机可跑) |

### 2.4 环境变量矩阵

| 变量 | 默认 | 说明 |
|------|------|------|
| `ENGINE_SCHEDULER_ENABLED` | `1` | 周期任务总闸(随 gateway lifespan 启动;多实例下仅保留一个实例置 1,其余 0) |
| `AI_*` 系列 | 无有效缺省 | LLM/Embedding 必填;embedding 默认本地 bge-small-zh(进程内 torch,注意冷启动与内存预算) |
| `AUTH_JWT_SECRET` | 开发缺省密钥 | **生产必须显式注入**(JWT 签发);缺省仅限本地/E2E,注入后无告警(wayfinder 001) |
| `RATE_LIMIT_WINDOW_SECONDS` / `RATE_LIMIT_{CHAT,SPI}_{TENANT,IP}_MAX` | 60 / 60·120·300·600 | 滑动窗口秒数与租户/IP 双维阈值,只挂 `/api/chat` 与 `/api/v1/spi`(wayfinder 002) |
| `RATE_LIMIT_TRUSTED_PROXIES` / `RATE_LIMIT_KEY_PREFIX` | `127.0.0.1,::1` / `ratelimit` | XFF 采信的可信反代清单(逗号分隔);共享 Redis 隔离环境换键前缀 |
| `LLM_CIRCUIT_MAX_FAILURES` / `LLM_CIRCUIT_COOLDOWN_SECONDS` | 5 / 30 | 上游 LLM 全局熔断阈值与冷却(wayfinder 003);E2E 熔断注入用 1/任意 |
| `LLM_RETRY_MAX_ATTEMPTS` / `LLM_RETRY_INITIAL_DELAY_MS` / `LLM_TIMEOUT_SECONDS` | 3 / 1000 / 120 | 指数退避次数、初始退避与单次尝试超时(`wait_for` 包裹) |

### 2.5 多实例

**单实例网关是当前架构的安全形态**:scheduler(周期任务)与 socket.io 房间两个硬缺口都挂在网关单例假设上,方案与前置清单整体见 `docs/architecture/multi-instance-deployment.md`,不在本页重复。

## 3. 发布后观测与排障入口

- **审批"批了没反应"**:先查 `SELECT status, error_message FROM approval_outbox_events ORDER BY created_at DESC LIMIT 3;`,再确认网关在线(scheduler 随 lifespan,网关在即对账在)。
- **周期任务日志关键字**(gateway 日志):`[Scheduler] 启动自检`(启动期)、`[Scheduler:outbox_reconcile] 对账扫描`(每 30s 有事件才打印,安静≠挂了)。
- **SSE 断流类**:Redis 可达性与 `socket_timeout=20` 不变量(阻塞命令 BLOCK 时长必须小于它)。
