"""限流中间件 — 租户+IP 双维 Redis 滑动窗口(wayfinder 002)。

TS 规格 docs/specs/server-gateway-hardening-and-scaling.md Solution 3:对话入口
60 req/min、商户 SPI 300 req/min,基于 Redis 记录访问频次。Python 侧落地:

- **双维独立计数**:租户维度(同租户聚合防刷,护 LLM Token 账单)+ IP 维度
  (防同 IP 轮换租户绕过),任一超限即 429。
- **原子全有或全无**:双维判定在单个 Lua 脚本内完成,任一维度超限则所有
  维度都不计数 —— 严格兑现"拒绝的请求不进窗口(只数放行)"。
- **ZSET 滑动窗口**:Lua 原子完成 裁剪→计数→放量→续期;Retry-After 取被拒
  维度窗口内最早一条滑出所需时间。键过期随窗口自然消亡,无残留。
- **IP 采信规则**:仅当直连 peer 属 :code:`RATE_LIMIT_TRUSTED_PROXIES`(默认
  ``127.0.0.1,::1``)才解析 X-Forwarded-For,且取**最右非可信跳**(由最近
  可信代理追加);不可信直连一律用真实 peer —— 伪造 XFF 旋转不了 IP 桶。
- **挂载顺序**:须注册在 TenantContextMiddleware 之前(内层),复用其解析好的
  ``request.state.tenant``,与 guard 同一租户口径;admin 聚合态 ``tenantId="all"``
  非真实租户,不设租户桶(仅 IP 维兜底)。只挂 /api/chat 与 /api/v1/spi 高频
  入口,39 条冻结路由形状不变(仅超载请求收到 429)。
- **fail-open**:Redis 故障时打印错误放行 —— Redis 与网关 SSE/事件主干同生共死,
  它挂时业务本身已不可用,限流组件不额外阻断(打印错误上下文,严禁空 except)。
- **阈值 env**::code:`RATE_LIMIT_WINDOW_SECONDS`(60)、
  :code:`RATE_LIMIT_{CHAT,SPI}_{TENANT,IP}_MAX`(默认 60/120 与 300/600,IP 维
  为规格租户数 ×2 的运营冗余)、:code:`RATE_LIMIT_KEY_PREFIX`(键前缀,共享
  Redis 隔离环境用)、:code:`RATE_LIMIT_TRUSTED_PROXIES`(逗号分隔)。
- **已知取舍(v1)**:SPI 租户维度键取自**未经 HMAC 验证**的 ``x-tenant-id``,且限流
  先于鉴权生效 —— 攻击者可伪造 header 耗尽受害租户的 SPI 窗口(IP 维可兜底节流
  单源攻击)。单实例运营期接受此取舍;硬化路线为 SPI 路由 ``_authenticate`` 通过
  之后再补记租户维度计数。
"""

from __future__ import annotations

import logging
import os
import time
import uuid

from engine_py.event_bus import get_client as get_redis
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# (路径前缀, 作用域) —— 精确匹配前缀或其子路径;仅这两组高频入口限流
_RATE_SCOPES = (("/api/chat", "chat"), ("/api/v1/spi", "spi"))

_DEFAULT_LIMITS = {"chat": {"tenant": 60, "ip": 120}, "spi": {"tenant": 300, "ip": 600}}

# KEYS=各维度窗口键;ARGV=[now_ms, window_ms, limit_1..N, member_1..N]
# 任一维度超限 → 全部维度不计数(all-or-nothing);返回 {1|0放行, retry_after秒}
_SLIDING_WINDOW_LUA = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local n = #KEYS
local allowed = 1
local retry_ms = 1
for i = 1, n do
  redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', now - window)
  if redis.call('ZCARD', KEYS[i]) >= tonumber(ARGV[2 + i]) then
    allowed = 0
    local oldest = redis.call('ZRANGE', KEYS[i], 0, 0, 'WITHSCORES')
    if oldest[2] then
      retry_ms = math.max(retry_ms, oldest[2] + window - now)
    end
  end
end
if allowed == 1 then
  for i = 1, n do
    redis.call('ZADD', KEYS[i], now, now .. '-' .. ARGV[2 + n + i])
    redis.call('PEXPIRE', KEYS[i], window)
  end
  return {1, 0}
end
return {0, math.ceil(retry_ms / 1000)}
"""


def _scope_for(path: str) -> str | None:
    for prefix, scope in _RATE_SCOPES:
        if path == prefix or path.startswith(prefix + "/"):
            return scope
    return None


def _limit(scope: str, dim: str) -> int:
    default = _DEFAULT_LIMITS[scope][dim]
    return int(os.environ.get(f"RATE_LIMIT_{scope.upper()}_{dim.upper()}_MAX", str(default)))


def _window_ms() -> int:
    return int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60")) * 1000


def _key_prefix() -> str:
    return os.environ.get("RATE_LIMIT_KEY_PREFIX", "ratelimit")


def _trusted_proxies() -> frozenset[str]:
    raw = os.environ.get("RATE_LIMIT_TRUSTED_PROXIES", "127.0.0.1,::1")
    return frozenset(hop.strip() for hop in raw.split(",") if hop.strip())


def _client_ip(request: Request) -> str:
    """直连 peer 可信(本方反代)才采信 XFF,取最右非可信跳;否则用真实 peer。"""
    peer = request.client.host if request.client else ""
    trusted = _trusted_proxies()
    if peer in trusted:
        forwarded = request.headers.get("x-forwarded-for")
        for hop in reversed(forwarded.split(",")) if forwarded else ():
            hop = hop.strip()
            if hop and hop not in trusted:
                return hop[:64]
    return (peer or "unknown")[:64]


async def _allow(keys: list[str], limits: list[int], *, now_ms: int, window_ms: int) -> tuple[bool, int]:
    """多维度滑动窗口原子判定;返回 (是否放行, retry_after 秒)。now 由调用方注入便于测试合成时钟。"""
    members = [f"{now_ms}-{uuid.uuid4().hex}" for _ in keys]
    verdict = await (
        await get_redis()
    ).eval(_SLIDING_WINDOW_LUA, len(keys), *keys, now_ms, window_ms, *limits, *members)
    return bool(verdict[0]), int(verdict[1])


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        scope = _scope_for(request.url.path)
        if scope is not None:
            blocked = await self._check(request, scope)
            if blocked is not None:
                return blocked
        return await call_next(request)

    async def _check(self, request: Request, scope: str) -> JSONResponse | None:
        """超限返回 429 响应;放行/故障 fail-open 返回 None。"""
        try:
            tenant_ctx = getattr(request.state, "tenant", None) or {}
            tenant_id = str(tenant_ctx.get("tenantId") or "").strip()[:64]
            ip = _client_ip(request)
            now_ms = int(time.time() * 1000)

            keys: list[str] = []
            limits: list[int] = []
            # admin 聚合态 "all" 非真实租户,不设租户桶(跨操作员会互相挤兑)
            if tenant_id and tenant_id != "all":
                keys.append(f"{_key_prefix()}:{scope}:tenant:{tenant_id}")
                limits.append(_limit(scope, "tenant"))
            keys.append(f"{_key_prefix()}:{scope}:ip:{ip}")
            limits.append(_limit(scope, "ip"))

            allowed, retry_after = await _allow(
                keys, limits, now_ms=now_ms, window_ms=_window_ms()
            )
            if not allowed:
                logging.getLogger(__name__).warning(
                    "[RateLimit] 🚫 %s 入口超限(ip=%s tenant=%s 维度键 %s),Retry-After=%ds",
                    scope,
                    ip,
                    tenant_id or "-",
                    keys,
                    retry_after,
                )
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                    content={"success": False, "error": "请求过于频繁，请稍后再试"},
                )
        except Exception as err:
            # fail-open:限流组件故障不得阻断业务(打印错误上下文,严禁空 except)
            print(f"[RateLimit] Redis 判定故障,fail-open 放行: {err}")
        return None
