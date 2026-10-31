# tech_stack —— 技术栈与结构

## 仓库形态

Monorepo:Turborepo + Bun workspaces(前端)+ uv workspace(Python 服务)。历史 TS 后端(NestJS 网关 + packages/engine 等)已于 2026-09 完成 1:1 Python 移植后退役;`packages/types`(zod)作为冻结前端契约保留。

## 前端

- Vite 6 + React 19 SPA ×4(web / admin / merchant / merchant-admin)。
- Tailwind CSS v4 + workspace 包 `ui`(shadcn 项目,无头原子,react 为 peerDependency);禁重型组件库。
- `packages/ui` 组件家族 + SVG 图标;`packages/types` 冻结 DTO。
- 注意 Tailwind v4 @source 坑:v4 自动扫描漏 packages/ui symlink。

## 后端

- `services/gateway-py`:FastAPI,137 条注册端点(analytics 43 / merchant 30 / admin 26 / crud 16 / chat 9 / auth 4 / spi 3 / live_desk 5 + health);SSE(Redis Streams 事件源)+ python-socketio 人工接管房间;HMAC-SHA256 SPI。
- `services/engine-py`:LangGraph DAG(triage → planner → merge → exec ⇄ val 循环);BaseSkill 技能管道;四象限记忆;Contextual RAG(本地 bge-small-zh embedding);HITL gatekeeper(事务发件箱 + Fast-Path 恢复);scheduler 随 gateway lifespan 启动;SQLAlchemy 模型 + Alembic 迁移。
- `ontology/`:领域本体声明(yaml)+ `registry.py` 代码生成器;运行时消费 `engine_py/ontology_generated.py`(自包含零依赖,禁手改)。
- Redis:Streams 事件主干 + 审批发件箱对账;PG18 共享同机 ad-kg 实例(agent_platform + agent_merchant 双库)。

## 质量链

pytest 契约套件(testcontainers PG+Redis,事实标准)/ vitest(与被测文件同目录)/ Playwright e2e(六册 + 熔断独立配置)/ promptfoo 评测(Classify、Planner、pin/compare 门禁)/ ruff(两服务全目录)/ biome(仓库版,pathspec 限定)/ ontology 一致性册 + CI regen diff 门。

## 部署

生产走 Docker Compose(场景 A 四前端 nginx 一体 / 场景 B 只部署商户面);镜像 GHCR;两机拓扑(PG 在 A 机 5433,B 机 2G 内存);compose 必须 `--env-file`;新代理路径必须同批镜像到 `deploy/nginx.conf`(契约 test_deploy_nginx_contract.py)。

## LLM 供给

bigmodel Coding Plan 端点(AI_BASE_URL 须配 /api/coding/paas/v4);env 全部 AI_\* 前缀;embedding 本地 bge-small-zh(免费,并发 encode 会 SIGSEGV,必须走 get_embedding_model 串行护栏)。
