# 分场景部署指南（按用户规模选型）

> 基础单机方案（已实测）见 [deploy.md](deploy.md)；本文按**用户规模与负载**给出四档进阶
> 场景，每档含架构变化、具体配置与操作步骤。
>
> **实测状态标注**：场景 A 基础版已在本机全链实测；B/C/D/E 的配置为设计稿，
> **未经部署验证**，采用前请在目标环境按文档自行验证。

## 选型速查

| 场景 | 适用规模 | 硬件 | 核心动作 | 文档章节 |
|---|---|---|---|---|
| A 单机全家桶 | 内部/几十并发 | 2C4G | 基础 compose 上线 | [deploy.md](deploy.md) |
| B 单机压榨 | 数百并发 / 数千日活 | 4C16G | workers/日志轮转/持久化/资源上限 | 本文 §1 |
| C 中型生产 | 数千日活 | 8C32G | 监控栈 + 蓝绿零停机 + 备份强化 | 本文 §2 |
| D 多机水平扩展 | 5000+ 日活 | 多机 + 云件 | LB 多副本 + 云 RDS/Redis + embedding 独立 | 本文 §3 |
| E K8s | 万级 / 团队化 | 集群 | 编排整体迁移 | 本文 §4 |

**先说结论**：业务代码三个特性让扩容不需要动业务层——gateway 无状态（会话在
PG/Redis）、限流挂 Redis、LLM 调用有熔断重试。扩容全部发生在部署层。

---

## §1 场景 B：单机压榨版

**症状驱动**：用户变多后响应变慢 / `pool exhausted` / 磁盘被日志吃满。

### 1.1 四个改动

**① gateway 多 worker**（`deploy/Dockerfile.gateway` 的 CMD）：

```dockerfile
CMD ["uv", "run", "--no-sync", "uvicorn", "gateway_py.main:app", \
     "--host", "0.0.0.0", "--port", "4000", "--workers", "4"]
```

⚠️ 代价：每个 worker 各加载一份 bge 模型（内存 +~300MB/个）。内存紧张时改
`AI_EMBEDDING_PROVIDER=openai`（走 LLM 端点的 /embeddings），进程不再载模型。

**② 日志轮转**（现在 json 日志无上限，会吃满磁盘——优先级最高）：
compose 每个长驻服务加：

```yaml
    logging:
      driver: json-file
      options: { max-size: "50m", max-file: "3" }
```

**③ Redis AOF 持久化**（现重启丢限流窗口与缓存）：

```yaml
  redis:
    command: ["redis-server", "--requirepass", "${REDIS_PASSWORD}", \
              "--appendonly", "yes", "--appendfsync", "everysec"]
```

**④ 资源上限**（防单服务拖垮整机）：gateway/worker 加
`deploy.resources.limits.memory: 8g`，postgres 加 `4g`。

### 1.2 用法（覆盖文件已提供：`deploy/docker-compose.scale.yml`）

```bash
docker compose -f deploy/docker-compose.prod.yml \
               -f deploy/docker-compose.scale.yml \
               --env-file deploy/.env.prod up -d
```

### 1.3 预期与验证

并发容量约 ×3~4；验证：压测 `POST /api/chat`（如 `hey`/`wrk`）看 P95，
监控 `docker stats` 内存是否触顶、PG 活跃连接数。

---

## §2 场景 C：中型生产（监控 + 零停机 + 备份强化）

### 2.1 监控栈（配置已提供：`deploy/docker-compose.monitoring.yml` + `deploy/monitoring/prometheus.yml`）

```bash
docker compose -f deploy/docker-compose.prod.yml \
               -f deploy/docker-compose.monitoring.yml \
               --env-file deploy/.env.prod up -d prometheus grafana cadvisor
# Grafana: http://服务器:3300(首登改密);Prometheus 控制台: :9090
```

关键指标：`/api/health` 拨测（黑盒）、容器内存/CPU（cadvisor）、PG 活跃连接、
LLM 熔断器状态（应用日志关键字 `circuit` 告警）。告警走 Grafana Alerting
（webhook 到飞书/钉钉）。

### 2.2 零停机蓝绿发版

compose 单项目 `up -d` 会重建容器（秒级中断）。中型规模改为双项目：

```bash
# 项目名即颜色;两套 .env 仅数据库/Redis 地址相同、端口错开
docker compose -p smartserve-blue -f deploy/docker-compose.prod.yml up -d --build
# 切流:宿主 nginx(或云 SLB)把 upstream 从 blue 组切到 green 组
docker compose -p smartserve-green -f deploy/docker-compose.prod.yml up -d --build
```

切流前用 `curl` 对新项目端口跑一遍冒烟（health + 一条真实问句）；旧项目保留
10 分钟作回滚，`down` 掉即回滚完成。

### 2.3 备份强化

- pg_dump 每日 cron（基础版已有）+ **上传异地对象存储**（OSS/COS，`ossutil cp`）
- 每月一次**恢复演练**：备份文件灌进临时库，跑一遍 seed 对账
- 卷快照：云盘快照策略（若云服务器）覆盖 `pg_data`

---

## §3 场景 D：多机水平扩展

### 3.1 目标架构

```text
用户 ──▶ 云 LB/SLB(TLS 终结)
          ├── 节点1..N: gateway 容器(--workers 4)      ← 无状态,随便加
          ├── 静态: 四前端 dist 上 CDN(或独立 nginx 机)
          ├── PostgreSQL → 云 RDS 主备(自动备份/只读副本)
          ├── Redis → 云 Redis(主备)
          ├── embedding → 独立推理服务(TEI 或 LLM 网关聚合 /embeddings)
          └── LLM → 多渠道池化(单端点限流会成为新瓶颈)
```

### 3.2 迁移要点（按依赖顺序；配置已提供）

| 组件 | 配置文件 |
|---|---|
| 入口 LB（自托管 nginx 版，TLS+轮询+被动探活） | `deploy/lb/nginx-lb.conf`（云 SLB 参数照抄） |
| 应用节点（只跑 gateway 的单机 compose） | `deploy/docker-compose.gateway-node.yml` |
| 独立 embedding（TEI + bge，OpenAI 兼容） | `deploy/embedding/docker-compose.tei.yml` |


1. **PG 先行**：pg_dump 迁云 RDS，`DATABASE_URL` 换 RDS 连接串（带
   `?sslmode=require`）；低峰窗口切，应用无感知
2. **embedding 解耦**：引擎走 `AI_EMBEDDING_PROVIDER=openai`，读的是
   `AI_BASE_URL` 的 `/embeddings`——让 LLM 网关聚合该路由（后端可以是 TEI：
   `docker run ghcr.io/huggingface/text-embeddings-inference --model-id BAAI/bge-small-zh-v1.5`）。
   gateway 不再载 torch 模型，镜像可瘦身为纯 CPU 轻量版
3. **gateway 多机**：每台 `docker compose up -d gateway`，注册进 SLB 后端组；
   无会话粘性需求（SSE 是单连接语义，任意副本可服务）。限流的
   `RATE_LIMIT_TRUSTED_PROXIES` 加入 SLB 网段，否则限流按 LB IP 计
4. **静态上 CDN**：四前端构建产物上传 OSS+CDN，源站只留 `/api`
5. **Temporal**：迁自托管 Temporal 集群或云版，Worker 与 gateway 同机部署即可

### 3.3 容量参考

单 gateway 副本（4 worker）≈ 数十 QPS API + 数百并发 SSE（取决于 LLM 端点吞吐，
**LLM 端点的并发上限先于应用到达**）；PG 建议连接数 = 副本数 × 池大小（默认
~15/副本），RDS 规格按此选。

---

## §4 场景 E：K8s

**触发条件**（满足任一再上，否则是过度设计）：多机运维成本失控、需要弹性伸缩
（促销波峰）、团队已有 K8s 平台。

**全套 manifest 已提供：`deploy/k8s/`**（namespace/secret/configmap/gateway
Deployment+Service+HPA/web/worker/TEI/migrate Job/Ingress + README 含 apply
顺序与镜像推送步骤；镜像占位 `registry.example.com/smartserve/*` 需替换）。

**compose → K8s 映射表**：

| compose 概念 | K8s 对应 |
|---|---|
| `deploy/docker-compose.prod.yml` 的 service | Deployment（无状态：gateway/web/worker）+ Service + Ingress |
| `volumes:` | PVC（pg_data → 云盘 StorageClass）/ Secret 挂载 |
| `deploy/.env.prod` | Secret（AI key/JWT/DB 密码）+ ConfigMap（开关类） |
| `migrate` 一次性服务 | Job（pre-install hook 或独立 Job，滚动前跑） |
| `--profile temporal` | 独立 Helm release（temporal 官方 chart） |
| 副本数手工 | HPA（CPU 60% 目标，min 2 max 10） |

健康检查沿用：`/api/health` 作 liveness+readiness probe；`start_period: 180s`
对应 `initialDelaySeconds`。镜像不变（同一份 Dockerfile 直接用）。

建议顺序：先在测试集群跑通 gateway+web+RDS 外置的最小集，PG/Redis 仍用云件，
**不要**一上来把有状态件搬进集群。

---

## 附：各场景共用的纪律（从基础版继承，不随扩容改变）

1. 评测集永不入训；接入切 `AI_BASE_URL` 一行，回滚同行
2. 权重/密钥/训练产物不进镜像与 git
3. `deploy/.env.prod` 三密钥改强随机；`.env.prod` 永不入库
4. 备份没有恢复演练 = 没有备份
