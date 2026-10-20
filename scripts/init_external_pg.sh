#!/usr/bin/env bash
# 一次性初始化共享 PG18（adkg-postgres）：建 agent_user 角色 + agent_platform / agent_merchant 两库。
#
# 背景（2026-10-20）：本仓库 PG15 实例（shared-postgres）退役，统一复用同机 ad-kg 的
# PG18（pgvector/pgvector:pg18，容器名 adkg-postgres，宿主端口 :5433）。本脚本即切换的
# 前置步骤，与 ad-kg scripts/init_db.py 同风格：幂等，重复执行结果不变。
#
# 做什么：
#   1. 角色 agent_user（LOGIN + CREATEDB）。CREATEDB 是商户库自愈建库的依赖
#      （gateway_py/merchant_db.py 在 3D000 时 CREATE DATABASE agent_merchant）。
#   2. 两库 agent_platform / agent_merchant，owner = agent_user（库内 DDL/扩展无需再授权；
#      uuid-ossp 自 PG13 起 trusted，owner 可装）。
#   3. ALTER ROLE 每次执行，把口令刷成 .env 当前值（改密后重跑即同步）。
#
# 用法：
#   bun run db:init-external        # 等价 bash scripts/init_external_pg.sh
#   前置：ad-kg 仓库 docker compose up -d（PG18 在跑）
#
# 凭据来源：根 .env 的 POSTGRES_USER / POSTGRES_PASSWORD（即 agent_user 的凭据，
# 自 compose 剥离 PG 后这两个变量不再喂 docker，语义收窄为初始化凭据）。
# 两种执行位置：
#   同机/A 机/本地（有 adkg-postgres 容器）：直接跑，走 docker exec
#   B 机跨机（没有该容器）：ADKG_PG_HOST=<A机IP> ADKG_PG_ADMIN_PASSWORD=<A机.adkg的PG口令>
#     bash scripts/init_external_pg.sh —— 走一次性 psql 客户端容器打 A 机 :5433
# 覆写项：ADKG_PG_CONTAINER（缺省 adkg-postgres）、ADKG_PG_ADMIN（缺省 adkg）、
#         ADKG_PG_HOST/ADKG_PG_PORT（跨机 TCP 模式）。

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$ROOT/.env" ]; then
  set -a; . "$ROOT/.env"; set +a
fi
: "${POSTGRES_USER:?根 .env 需设 POSTGRES_USER（agent_user）}"
: "${POSTGRES_PASSWORD:?根 .env 需设 POSTGRES_PASSWORD}"
ADMIN_USER="${ADKG_PG_ADMIN:-adkg}"

run_psql() {
  if [ -n "${ADKG_PG_HOST:-}" ]; then
    : "${ADKG_PG_ADMIN_PASSWORD:?跨机模式需 ADKG_PG_ADMIN_PASSWORD（A 机 .env 的 POSTGRES_PASSWORD）}"
    PGPASSWORD="$ADKG_PG_ADMIN_PASSWORD" docker run --rm -i \
      -e PGPASSWORD="$ADKG_PG_ADMIN_PASSWORD" \
      docker.m.daocloud.io/library/postgres:18-alpine \
      psql -h "$ADKG_PG_HOST" -p "${ADKG_PG_PORT:-5433}" -U "$ADMIN_USER" -d postgres \
      -v role="$POSTGRES_USER" -v pwd="$POSTGRES_PASSWORD"
  else
    docker exec -i "${ADKG_PG_CONTAINER:-adkg-postgres}" \
      psql -U "$ADMIN_USER" -d postgres \
      -v role="$POSTGRES_USER" -v pwd="$POSTGRES_PASSWORD"
  fi
}

echo "== 初始化共享 PG18：目标=${ADKG_PG_HOST:-adkg-postgres(容器)} 管理员=$ADMIN_USER 角色=$POSTGRES_USER"
run_psql <<'SQL'
-- 角色不存在则建（CREATE ROLE 不支持 IF NOT EXISTS，走 \gexec 生成语句）
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L CREATEDB', :'role', :'pwd')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'role') \gexec
-- 口令/CREATEDB 每次刷新（幂等；改密重跑即同步）；角色名是标识符用 :"role"
ALTER ROLE :"role" WITH LOGIN PASSWORD :'pwd' CREATEDB;
-- 两库不存在则建，owner 归 agent_user
SELECT format('CREATE DATABASE %I OWNER %I', d.name, :'role')
FROM (VALUES ('agent_platform'), ('agent_merchant')) AS d(name)
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = d.name) \gexec

SELECT rolname || '：CREATEDB=' || rolcreatedb FROM pg_roles WHERE rolname = :'role';
SELECT '库 ' || datname || '：owner=' || pg_get_userbyid(datdba)
FROM pg_database WHERE datname IN ('agent_platform', 'agent_merchant') ORDER BY datname;
SQL
echo "== 完成（幂等，可重跑）"
