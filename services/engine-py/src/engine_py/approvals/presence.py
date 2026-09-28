"""坐席在线态(live-desk-rework §2.3):连接态即在线 + 手动免打扰。

存储 = Redis 共享存储(多实例不封死,零迁移 —— 瞬态不入库):

- 在线 **ZSET** ``live_desk:presence:{tenant}``:member=email,score=last_seen
  unix 秒。TTL 心跳语义 = score 距今不超过 ttl;读取侧比较 + 顺手
  ZREMRANGEBYSCORE 修剪,不依赖 Redis 键过期(单键 O(log n),无 KEYS 扫描)。
- 免打扰 **SET** ``live_desk:dnd:{tenant}``:member=email。手动开关,无 TTL
  (自拨状态,不随心跳消失)。

分层纪律:在线态是「人的能力态」,与接管态(threads 列,会话级)严格分层;
**仅展示,不作分配闸**(自选认领不依赖调度)。Redis 不可用时如实报空
(presence 是纯展示增强,绝不阻断宿主流程)。
"""

from __future__ import annotations

import datetime as _dt

_PRESENCE_TTL_SECONDS = 60.0


def _presence_key(tenant_id: str) -> str:
    return f"live_desk:presence:{tenant_id}"


def _dnd_key(tenant_id: str) -> str:
    return f"live_desk:dnd:{tenant_id}"


async def heartbeat(tenant_id: str, email: str, ttl_seconds: float = _PRESENCE_TTL_SECONDS) -> None:
    """心跳续期(socket 连接/加入房间/presence_ping 时调用)。"""
    from ..event_bus import get_client

    client = await get_client()
    now = _dt.datetime.now().timestamp()
    await client.zadd(_presence_key(tenant_id), {email: now})
    await client.zremrangebyscore(_presence_key(tenant_id), 0, now - ttl_seconds)


async def drop(tenant_id: str, email: str) -> None:
    """socket 断开即离线(单连接假设;多连接残余由 TTL 兜底过期)。"""
    from ..event_bus import get_client

    client = await get_client()
    await client.zrem(_presence_key(tenant_id), email)


async def set_dnd(tenant_id: str, email: str, enabled: bool) -> None:
    """手动免打扰开关(工作台头部自拨)。"""
    from ..event_bus import get_client

    client = await get_client()
    if enabled:
        await client.sadd(_dnd_key(tenant_id), email)
    else:
        await client.srem(_dnd_key(tenant_id), email)


async def presence_map(tenant_id: str, ttl_seconds: float = _PRESENCE_TTL_SECONDS) -> dict[str, dict]:
    """email → {online, dnd, lastSeenAt}(全租户坐席在线态汇总;Redis 不可用
    回空 dict,展示降级不报错)。"""
    try:
        from ..event_bus import get_client

        client = await get_client()
        now = _dt.datetime.now().timestamp()
        await client.zremrangebyscore(_presence_key(tenant_id), 0, now - ttl_seconds)
        raw = await client.zrange(_presence_key(tenant_id), 0, -1, withscores=True)
        dnd = await client.smembers(_dnd_key(tenant_id))
    except Exception as err:  # Redis 离线:纯展示面,如实空态
        print(f"[Presence] 在线态读取失败(按全离线呈现): {err}")
        return {}
    result: dict[str, dict] = {}
    for email, score in raw or []:
        result[str(email)] = {
            "online": (now - float(score)) <= ttl_seconds,
            "dnd": str(email) in (dnd or set()),
            "lastSeenAt": _dt.datetime.fromtimestamp(float(score), tz=_dt.UTC).astimezone().isoformat(),
        }
    # 免打扰但离线的坐席也要在汇总里(dnd 是自拨状态,不随心跳消失;
    # 只迭代在线 ZSET 会把「免打扰且离线」的人整个丢掉)
    for email in dnd or set():
        result.setdefault(str(email), {"online": False, "dnd": True, "lastSeenAt": None})
    return result
