# 生产部署方案（Docker Compose 全栈）

> 一套 `deploy/` 目录 = 服务器完整上线能力：四个前端（nginx 一体镜像）、
> gateway（FastAPI）、Temporal Worker（可选）、PostgreSQL/Redis/Temporal。
> 训练产物（SFT adapter）的部署另见 [sft-deploy-eval.md](sft-deploy-eval.md)。

## 一、架构总览

```text
                    ┌────────────────────── 服务器 (Docker 24+, 2C8G+, 40GB 盘) ─────────────────────┐
浏览器 ──HTTP──▶ web :3000/:3001/:3005/:3006   nginx 四站点静态 + SPA 回退
                    │      └── /api/* 反代 ──▶  gateway :4000  FastAPI(双 Agent/数据分析/客服)
                    │                              ├── PostgreSQL 15 (pg_data 卷, 不暴露宿主)
                    │                              ├── Redis 7     (redis_data 卷, 不暴露宿主)
                    │                              ├── uploads 卷 (/data/uploads 聊天附件)
                    │                              ├── hf_cache 卷 (bge 本地 embedding 模型)
                    │                              └── Temporal + Worker (--profile temporal 可选)
                    └── LLM: AI_BASE_URL 指向服务器可达的 OpenAI 兼容端点(外置)
```

要点：

- 前端全部走**相对路径 `/api/...`**，nginx 同源反代到 gateway——无 CORS 问题，
  SSE（`/api/chat/*/stream`）与 socket.io 升级头已按长连接调优
- gateway 镜像含 torch/sentence-transformers（本地 embedding），体积 GB 级属预期
- 数据全部落在 named volume；`postgres`/`redis` 默认**不向宿主机暴露端口**

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

# 1) 环境变量:复制模板并改密(LLM 端点/PG/Redis 三个 change-me 必改)
cp deploy/.env.prod.example deploy/.env.prod
vim deploy/.env.prod

# 2) 起基础设施(数据库先就绪)
docker compose -f deploy/docker-compose.prod.yml up -d postgres redis

# 3) 构建应用镜像(首次 5~15 分钟;uv/bun 都走锁文件,可复现)
docker compose -f deploy/docker-compose.prod.yml build gateway web

# 4) 数据库迁移(migrate 服务跑完自动退出,gateway 等它成功才启动)
docker compose -f deploy/docker-compose.prod.yml up -d gateway

# 5) 起前端 + 验证
docker compose -f deploy/docker-compose.prod.yml up -d web
curl -s http://127.0.0.1:4000/api/health     # {"status":...} 即网关就绪
curl -s http://127.0.0.1:3000/healthz        # ok
```

浏览器打开 `http://服务器IP:3000|3001|3005|3006` 即四个终端；商城测试账号
`test@example.com`（种子数据见下）。

**种子数据**（演示/测试环境；生产评估后自行决定）：

```bash
cd deploy
docker compose -f docker-compose.prod.yml run --rm gateway \
  sh -c 'cd engine-py && uv run --no-sync python -m engine_py.db.seed && \
                        uv run --no-sync python -m engine_py.db.seed_third_party'
docker compose -f docker-compose.prod.yml run --rm gateway \
  sh -c 'cd gateway-py && uv run --no-sync python -m gateway_py.merchant_seed'
```

**Temporal 周期任务**（HITL 对账/超时扫描，不需要就不开）：

```bash
docker compose -f deploy/docker-compose.prod.yml --profile temporal up -d
```

## 四、镜像说明

| 镜像 | Dockerfile | 内容 | 预期体积 |
|---|---|---|---|
| gateway（worker 共用） | `deploy/Dockerfile.gateway` | uv workspace 安装 engine-py+gateway-py（含 torch/bge），CMD uvicorn | 4~6GB |
| web | `deploy/Dockerfile.web` | bun 1.4 构建四个 Vite 应用 → nginx:1.27 四站点静态 | ~200MB |
| postgres/redis/temporal | 官方镜像 | 数据与队列 | 官方体积 |

设计细节：

- **依赖层缓存**：gateway 先拷 `pyproject/uv.lock` 再同步依赖，改源码不重装依赖；
  web 先 `bun install --frozen` 再构建
- **根 `.dockerignore`**：`node_modules`/`training_data`（154MB adapter）/测试报告/
  `.env` 全部不进构建上下文
- **前端零构建参数**：代码走相对 `/api`，不需要 VITE_* 注入域名，换域名重新 build 即可

## 五、运维

**日志**：`docker compose -f deploy/docker-compose.prod.yml logs -f gateway`（其余同理）

**备份**（每日 cron，示例）：

```bash
docker compose -f deploy/docker-compose.prod.yml exec -T postgres \
  pg_dump -U agent_user agent_platform | gzip > /backup/agent_$(date +%F).sql.gz
```

**升级发版**：

```bash
git pull
docker compose -f deploy/docker-compose.prod.yml build gateway web
docker compose -f deploy/docker-compose.prod.yml up -d     # migrate 自动执行
```

**回滚**：`git checkout <上一个tag/commit>` 后重复升级命令；镜像层缓存让回滚重建很快。

**健康检查**：`/api/health`（gateway）、`/healthz`（四个前端站点）；compose 已带
healthcheck + 依赖编排（gateway 等 migrate 成功、web 等 gateway 健康）。

## 六、安全清单

- [ ] `deploy/.env.prod` 三个 `change-me` 全改强密码；该文件已在 gitignore，永不入库
- [ ] 5432/6379 未暴露（默认未开）；如需外部访问走 SSH 隧道
- [ ] 对外暴露仅 3000/3001/3005/3006/4000；云安全组按此收敛
- [ ] 域名 + TLS：前面加一层宿主 nginx/Caddy 或云 SLB 反代这五个端口，
      websocket/SSE 头照抄 `deploy/nginx.conf` 的 proxy 段
- [ ] LLM API Key 只放 `deploy/.env.prod`，不进代码与日志

## 七、裸机替代方案（不用 Docker 时）

```bash
# 前提: python3.12 + uv、bun 1.4、PostgreSQL15、Redis7 装好
uv sync --directory services                       # Python 依赖
bun install                                        # 前端依赖
bun run build                                      # 四前端 dist
# 各服务用 systemd 跑:
#   gateway:  cd services && uv run uvicorn gateway_py.main:app --port 4000
#   worker:   cd services/engine-py && uv run python -m engine_py.temporal.worker
#   四前端:   任一 nginx 静态服务 apps/*/dist(配置抄 deploy/nginx.conf)
```

数据库迁移/种子命令与 Docker 相同（`alembic upgrade head` 等）。

## 八、验证清单

- [ ] `curl :4000/api/health` 返回 JSON
- [ ] 四端口站点能打开，客服发消息有 SSE 流式回复（LLM 端点已配）
- [ ] merchant 真实登录/注册可用（种子已导入）
- [ ] merchant-admin 数据分析六页出真数（连接的是种子库）
- [ ] 重启服务器后 `docker compose -f deploy/docker-compose.prod.yml up -d` 一键恢复（卷持久化）
