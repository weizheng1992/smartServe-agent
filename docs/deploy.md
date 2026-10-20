# 生产部署方案（Docker Compose · 场景 A 全栈 / 场景 B 只部署商户面）

> **按规模选方案**：本篇是基础单机版（已实测），适用内部/几十并发。更大规模见
> [deploy-scaling.md](deploy-scaling.md)——单机压榨（§1）/ 中型生产·监控·蓝绿（§2）/
> 多机水平扩展（§3）/ K8s（§4），每档含架构与操作步骤（设计稿，采用前需目标环境验证）。
>
> 一套 `deploy/` 目录 = 服务器完整上线能力：四个前端（nginx 一体镜像）、
> gateway（FastAPI，周期任务随 lifespan）、Redis（PG 复用同机 adkg PG18）。
> 训练产物（SFT adapter）的部署另见 [sft-deploy-eval.md](sft-deploy-eval.md)。

## 一、架构总览

```text
                    ┌────────────────────── 服务器 (Docker 24+, 2C8G+, 40GB 盘) ─────────────────────┐
浏览器 ──HTTP──▶ web :3000/:3001/:3005/:3006   nginx 四站点静态 + SPA 回退
                    │      └── /api/* 反代 ──▶  gateway :4000  FastAPI(双 Agent/数据分析/客服)
                    │                              ├── PostgreSQL 18 (adkg-postgres 容器, shared-infra 网络直连,
                    │                              │   agent_platform/agent_merchant 两库, 归 ad-kg 侧编排)
                    │                              ├── Redis 7     (redis_data 卷, 不暴露宿主)
                    │                              ├── uploads 卷 (/data/uploads 聊天附件)
                    │                              └── hf_cache 卷 (bge 本地 embedding 模型)
                    └── LLM: AI_BASE_URL 指向服务器可达的 OpenAI 兼容端点(外置)
```

要点：

- 前端全部走**相对路径 `/api/...`**，nginx 同源反代到 gateway——无 CORS 问题，
  SSE（`/api/chat/*/stream`）与 socket.io 升级头已按长连接调优
- gateway 镜像含 torch/sentence-transformers（本地 embedding），体积 GB 级属预期
- 数据全部落在 named volume；`redis` 默认**不向宿主机暴露端口**；PG 由 ad-kg 侧
  compose 管理（宿主 :5433），上线五步前先按其 README 起 PG 并跑
  `bash scripts/init_external_pg.sh`

## 二、服务器要求

| 项 | 最低 | 推荐 |
|---|---|---|
| CPU/内存 | 2C 4G | 4C 8G（gateway 首启要跑 embedding 模型） |
| 磁盘 | 40GB | 60GB（gateway 镜像 GB 级 + PG 数据 + 15GB 全精度基座仅自测时需要） |
| 软件 | Docker 24+ / Compose v2 | 同左（无需装 bun/uv/python，构建全在容器内） |
| 网络 | 可达 LLM 端点 + 镜像源 | 国内配 docker 镜像加速与 HF_ENDPOINT |

## 三、上线五步

```bash
# 0) 服务器装 Docker(官方脚本) 后,克隆仓库
git clone git@github.com:weizheng1992/smartServe-agent.git && cd smartServe-agent

# 0.5) 先起 ad-kg 侧 PG18(本编排不自带 PG;同机模式在本机、两机模式在 A 机执行)
docker network create shared-infra   # 两机模式下 B 机也须建(prod.yml/merchant.yml 以 external 引用此网,缺了 up 直接报错)
cd <ad-kg 仓库根目录> && docker compose up -d && cd -   # 克隆 ad-kg 后进入其根目录,见其 docs/deployment.md
bash scripts/init_external_pg.sh    # 共享 PG 建 agent_user 角色 + 两库(幂等,一次性;跨机模式见脚本头注)

# 1) 环境变量:复制模板并改密(LLM 端点/PG/Redis 凭据必改;PG 主机名固定 adkg-postgres)
cp deploy/.env.prod.example deploy/.env.prod
vim deploy/.env.prod

# 2) 起基础设施(Redis 先就绪;PG 已由上一步就绪)
# ⚠️ compose 文件内 ${REDIS_PASSWORD} 插值只认 --env-file 传入的 .env.prod,
#    env_file: 只注入容器内——漏了 --env-file Redis 会回落缺省口令,与 gateway 错配
docker compose --env-file deploy/.env.prod -f deploy/docker-compose.prod.yml up -d redis

# 3) 构建应用镜像(首次 5~15 分钟;uv/bun 都走锁文件,可复现)
docker compose --env-file deploy/.env.prod -f deploy/docker-compose.prod.yml build gateway web

# 4) 数据库迁移(migrate 服务跑完自动退出,gateway 等它成功才启动)
docker compose --env-file deploy/.env.prod -f deploy/docker-compose.prod.yml up -d gateway

# 5) 起前端 + 验证
docker compose --env-file deploy/.env.prod -f deploy/docker-compose.prod.yml up -d web
curl -s http://127.0.0.1:4000/api/health     # {"status":...} 即网关就绪
curl -s http://127.0.0.1:3000/healthz        # ok
```

浏览器打开 `http://服务器IP:3000|3001|3005|3006` 即四个终端；商城测试账号
`test@example.com`（种子数据见下）。

**种子数据**（演示/测试环境；生产评估后自行决定）：

```bash
cd deploy
docker compose --env-file .env.prod -f docker-compose.prod.yml run --rm gateway \
  sh -c 'cd engine-py && uv run --no-sync python -m engine_py.db.seed && \
                        uv run --no-sync python -m engine_py.db.seed_third_party'
docker compose --env-file .env.prod -f docker-compose.prod.yml run --rm gateway \
  sh -c 'cd gateway-py && uv run --no-sync python -m gateway_py.merchant_seed'
```

**周期任务**（HITL 对账/超时扫描/坏例摘要）随 gateway lifespan 自动在场，无需单独启用。

## 三·五、自动发布（push main 即发，2026-10-20 起）

`.github/workflows/ci.yml` 四棒接力：`frontend + python 测试 → build-push（runner 上构建 gateway/web 镜像推 GHCR，sha+latest 双 tag）→ deploy（SSH 到 B 机 pull + up + 健康断言）`。PR 只跑前两棒；push main 全链路。构建在 runner（4C16G）——prod 面（场景 A）服务器零构建；场景 B 的 `merchant-web` 仍走本机构建（CI 流水线未覆盖该 Dockerfile，见 §九）。

- **Secrets 三枚**：`DEPLOY_HOST` / `DEPLOY_USER` / `DEPLOY_SSH_KEY`（部署专用用户：git deploy key + docker 组，无 sudo）
- **GHCR 首次**：push 成功后到 Packages 页把 `smartserve-gateway` / `smartserve-web` 设 **public**（默认 private，B 机匿名 pull 会 401）；国内直连拉不动走 daocloud 代理 retag
- **回滚**：镜像带 sha tag，compose 的 `image:` 指回上一个 sha 再 `up -d`，一条命令
- **两机拓扑**：本机（B 机）只跑 smartServe 全栈；PG 在 A 机（ad-kg 仓库，`DATABASE_URL` 填 A 机内网 IP:5433，安全组只对 B 机放行）——见 ad-kg 仓库 `docs/deployment.md`。B 机首次部署前置：`docker network create shared-infra`（prod.yml/merchant.yml 以 `external: true` 引用，缺网 `up` 直接报错；该网仅满足 compose 声明，gateway 实际走 A 机内网 IP 连 PG）；A 机侧建网 + 起 ad-kg PG 见 §二 0.5 步

## 四、镜像说明

| 镜像 | Dockerfile | 内容 | 预期体积 |
|---|---|---|---|
| gateway | `deploy/Dockerfile.gateway` | uv workspace 安装 engine-py+gateway-py（含 torch/bge），CMD uvicorn | 4~6GB |
| web | `deploy/Dockerfile.web` | bun 1.4 构建四个 Vite 应用 → nginx:1.27 四站点静态 | ~200MB |
| redis | 官方镜像 `redis:7-alpine` | 缓存/事件主干 | 官方体积 |

> PG 不在本编排内：已外置 ad-kg 侧 PG18（`scripts/init_external_pg.sh` 初始化），无对应镜像。

设计细节：

- **依赖层缓存**：gateway 先拷 `pyproject/uv.lock` 再同步依赖，改源码不重装依赖；
  web 先 `bun install --frozen` 再构建
- **根 `.dockerignore`**：`node_modules`/`training_data`（154MB adapter）/测试报告/
  `.env` 全部不进构建上下文
- **前端零构建参数**：代码走相对 `/api`，不需要 VITE_* 注入域名，换域名重新 build 即可

## 五、运维

**日志**：`docker compose -f deploy/docker-compose.prod.yml logs -f gateway`（其余同理）

**备份**（每日 cron，示例；PG 在 A 机，走一次性 psql 客户端容器）：

```bash
PW=$(grep ^POSTGRES_PASSWORD deploy/.env.prod | cut -d= -f2-)
docker run --rm -e PGPASSWORD="$PW" docker.m.daocloud.io/library/postgres:18-alpine \
  pg_dump -h <A机内网IP> -p 5433 -U agent_user agent_platform | gzip > /backup/agent_$(date +%F).sql.gz
# 商户库同理：库名换 agent_merchant
```

**升级发版**：

```bash
git pull
docker compose --env-file deploy/.env.prod -f deploy/docker-compose.prod.yml build gateway web
docker compose --env-file deploy/.env.prod -f deploy/docker-compose.prod.yml up -d     # migrate 自动执行
```

**回滚**：`git checkout <上一个tag/commit>` 后重复升级命令；镜像层缓存让回滚重建很快。

**健康检查**：`/api/health`（gateway）、`/healthz`（四个前端站点）；compose 已带
healthcheck + 依赖编排（gateway 等 migrate 成功、web 等 gateway 健康）。

## 六、安全清单

- [ ] `deploy/.env.prod` 三个 `change-me` 全改强密码；该文件已在 gitignore，永不入库
- [ ] 6379 未暴露（默认未开）；如需外部访问走 SSH 隧道。PG 共享同机 adkg PG18（5433
      由 ad-kg 侧管理暴露面，smartServe 经 shared-infra 内网直连，不经宿主端口）
- [ ] 对外暴露仅 3000/3001/3005/3006/4000；云安全组按此收敛
- [ ] 域名 + TLS：前面加一层宿主 nginx/Caddy 或云 SLB 反代这五个端口，
      websocket/SSE 头照抄 `deploy/nginx.conf` 的 proxy 段
- [ ] LLM API Key 只放 `deploy/.env.prod`，不进代码与日志

## 七、裸机替代方案（不用 Docker 时）

```bash
# 前提: python3.14 + uv、bun 1.4、PostgreSQL 18(自装或指向 adkg 外置实例,建 agent_user 角色与两库)、Redis7 装好(uv 读 services/.python-version 自动装对版本;夜审 B2:与 CI/本地 venv 对齐,旧文 3.12 与实际运行时漂移)
uv sync --directory services                       # Python 依赖
bun install                                        # 前端依赖
bun run build                                      # 四前端 dist
# 各服务用 systemd 跑:
#   gateway:  cd services && uv run uvicorn gateway_py.main:app --port 4000
#   四前端:   任一 nginx 静态服务 apps/*/dist(配置抄 deploy/nginx.conf)
```

数据库迁移/种子命令与 Docker 相同（`alembic upgrade head` 等）。

## 八、验证清单

- [ ] `curl :4000/api/health` 返回 JSON
- [ ] 四端口站点能打开，客服发消息有 SSE 流式回复（LLM 端点已配）
- [ ] merchant 真实登录/注册可用（种子已导入）
- [ ] merchant-admin 数据分析六页出真数（连接的是种子库）
- [ ] 重启服务器后 `docker compose --env-file deploy/.env.prod -f deploy/docker-compose.prod.yml up -d` 一键恢复（卷持久化）

## 九、场景 B：只部署商户面（merchant / merchant-admin）

只要商户门户（3005）与商户后台（3006）时用这套编排——`web`（3000）/`admin`（3001）不构建、不暴露：

| 文件 | 作用 |
|---|---|
| `deploy/docker-compose.merchant.yml` | 编排：Redis + migrate + gateway + `merchant-web`（仅 3005/3006；PG 复用 A 机） |
| `deploy/Dockerfile.web.merchant` | 只构建 `merchant` + `merchant-admin` 两个 dist（turbo filter 带上 ui/types） |
| `deploy/nginx.merchant.conf` | 只留 3005/3006 两个 server 块，代理参数与全量 nginx.conf 逐字一致 |

```bash
# 1) 环境变量与场景 A 共用同一份模板/文件
cp deploy/.env.prod.example deploy/.env.prod && vim deploy/.env.prod

# 2) 一键起（镜像构建 + 迁移 + 启动）
docker compose --env-file deploy/.env.prod -f deploy/docker-compose.merchant.yml up -d --build
```

- **网关不裁剪**：商户两面前端的后端 = 同一 gateway（engine/PG/Redis 也是同一套）；web/admin 专属路由闲置无害，代码级裁端点不划算也不做。4000 端口仍暴露，便于直连调试与 SPI 回调。
- **数据隔离**：project name 是 `smartserve-merchant`，卷名带前缀，与全量版（`smartserve-prod`）的库数据互不串；同一台机器二选一跑，或并存（内存够 8G 才建议并存）。
- **验证清单**（替换第八节对应项）：`curl :3005/healthz` / `:3006/healthz` 返回 ok；3005 商城可登录加购；3006 登录后悬浮助手提问出真数；`docker compose --env-file deploy/.env.prod -f deploy/docker-compose.merchant.yml up -d` 一键恢复。
