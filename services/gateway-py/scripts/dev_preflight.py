"""dev 启动前置自检(2026-10-15 夜评台账 #3/#9 收口)。

三闸串联,任一失败响亮退出拒绝拉网关:
1. 深模块真导入 —— uvicorn --reload 只监视 gateway_py 树,engine_py 深链的
   语法错误/半成品提交不会触发 reload,网关带旧代码继续跑(09-17/09-18/
   09-20 三轮「过期进程」事故);
2. PG 存活 —— Docker Desktop 停运后网关带病起,依赖路由全 500(10-10 实锤);
3. Redis 存活 —— SSE 事件主干/限流/nonce 同生共死。

dev:server 脚本已串联本闸(--env-file 同源)。
"""

from __future__ import annotations

import asyncio
import os
import sys

CHECKS = ("engine_py.run_agent", "gateway_py.main")


def _check_imports() -> list[tuple[str, BaseException]]:
    failures: list[tuple[str, BaseException]] = []
    for mod in CHECKS:
        try:
            __import__(mod)
            print(f"[Preflight] ✓ {mod}")
        except BaseException as err:  # 自检闸连 SystemExit 都要抓来报错
            failures.append((mod, err))
            print(f"[Preflight] ✗ {mod}: {err!r}")
    return failures


async def _check_infra() -> list[str]:
    """PG/Redis 存活探测(3s 超时);URL 取自环境,与网关同源。"""
    problems: list[str] = []

    dsn = os.environ.get("DATABASE_URL", "")
    if dsn:
        try:
            import asyncpg

            def _pg_dsn(url: str) -> str:
                # TS 遗留 postgres:// 方言转 asyncpg 可用(engine config 同款归一)
                return url.replace("postgres://", "postgresql://", 1)

            conn = await asyncio.wait_for(asyncpg.connect(_pg_dsn(dsn)), timeout=3)
            await conn.close()
            print("[Preflight] ✓ postgres 存活")
        except Exception as err:
            problems.append(f"postgres 不可达({dsn.rsplit('@', 1)[-1]}): {err!r:.80}")
    else:
        problems.append("DATABASE_URL 未注入(漏带 --env-file?)")

    redis_url = os.environ.get("REDIS_URL", "")
    if redis_url:
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(redis_url, socket_connect_timeout=3, socket_timeout=3)
            try:
                await client.ping()
                print("[Preflight] ✓ redis 存活")
            finally:
                await client.aclose()
        except Exception as err:
            problems.append(f"redis 不可达({redis_url.rsplit('@', 1)[-1]}): {err!r:.80}")
    else:
        problems.append("REDIS_URL 未注入(漏带 --env-file?)")
    return problems


def main() -> int:
    failures = _check_imports()
    infra_problems = asyncio.run(_check_infra())
    for problem in infra_problems:
        print(f"[Preflight] ✗ {problem}")
    if failures:
        print(
            f"[Preflight] 🚨 {len(failures)} 个深模块导入失败,拒绝启动网关 —— "
            "先修复再起(过期/半成品进程是三轮巡检事故的直接根因)"
        )
        return 1
    if infra_problems:
        print(
            "[Preflight] 🚨 基础设施不可达,拒绝启动网关 —— 先 `bun run docker:up` "
            "起 PG/Redis(带病网关=依赖路由全 500,10-10 实锤)"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
