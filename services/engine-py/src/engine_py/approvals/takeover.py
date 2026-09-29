"""接管状态机真源(threads.status + assigned_operator_id)— live-desk-rework P1。

spec: docs/architecture/live-desk-rework.md §2.1。复合语义:
``status = 'human_takeover'`` 且 ``assigned_operator_id IS NULL`` = 呼叫中/排队;
非空 = 接管中。HTTP 链(gatekeeper)与 socket 链(realtime)经本模块同写一源。

掉线释放的**权威路径** = ``threads.metadata.takeover_release_at``(DB deadline)+
scheduler 幂等扫描(``release_expired_takeovers``)—— 进程内计时器仅可作 UX
提示,不可作唯一路径(多实例约束,spec §6)。
"""

from __future__ import annotations

from sqlalchemy import text

from ..db import get_session


async def mark_takeover_requested(thread_id: str) -> None:
    """进入/保持接管态(坐席空 = 呼叫中)。同一接管期只记首次 requested_at
    (排队时长取最早呼叫时刻);释放后再次进入则起新期。"""
    async with get_session() as session:
        await session.execute(
            text(
                "UPDATE threads SET status = 'human_takeover', updated_at = NOW(), "
                "metadata = CASE WHEN status = 'human_takeover' THEN metadata "
                "ELSE jsonb_set(COALESCE(metadata, '{}'::jsonb), '{takeover_requested_at}', to_jsonb(NOW())) "
                "END "
                "WHERE id = :tid"
            ).bindparams(tid=thread_id)
        )
        await session.commit()


async def assign_operator(thread_id: str, operator_email: str, business_id: str | None = None) -> bool:
    """坐席认领/发言 → 接管中 + 认领坐席;清掉线释放 deadline(认领即活人在线)。

    P2 认领池原子守卫(spec §2.3):``WHERE assigned_operator_id IS NULL OR = :op``
    —— 两坐席同抢只成一人,败者得 False 收「已被认领」;本坐席重复认领幂等成真。
    抢单防线不依赖进程内存(多实例天然安全)。

    ``business_id`` 提供时收租户 WHERE(socket 链传入,与 update_conversation_status
    同口径);gatekeeper 内部路径线程归属已由路由层校验,不传。
    """
    sql = (
        "UPDATE threads SET status = 'human_takeover', assigned_operator_id = :op, "
        "updated_at = NOW(), metadata = COALESCE(metadata, '{}'::jsonb) - 'takeover_release_at' "
        "WHERE id = :tid AND (assigned_operator_id IS NULL OR assigned_operator_id = :op)"
    )
    params: dict = {"op": operator_email, "tid": thread_id}
    if business_id:
        sql += " AND business_id = :biz"
        params["biz"] = business_id
    sql += " RETURNING id"
    async with get_session() as session:
        claimed = (await session.execute(text(sql).bindparams(**params))).scalar() is not None
        await session.commit()
    return claimed


async def thread_state(thread_id: str) -> dict:
    """threads 真源形状(live-desk-rework §4:conversation_state_changed 统一
    载荷 status/assignedOperatorId/unreadCount)。线程不存在回空态。"""
    async with get_session() as session:
        row = (
            await session.execute(
                text("SELECT status, assigned_operator_id, COALESCE(unread_count, 0) FROM threads WHERE id = :tid").bindparams(
                    tid=thread_id
                )
            )
        ).first()
    if row is None:
        return {"status": "active", "assignedOperatorId": None, "unreadCount": 0}
    return {"status": row[0] or "active", "assignedOperatorId": row[1], "unreadCount": int(row[2] or 0)}


async def reset_unread(thread_id: str, business_id: str | None = None) -> bool:
    """坐席打开时间线 → 未读清零(P2 激活存量死列;仅坐席台展示,顾客端不同步)。
    幂等;``business_id`` 提供时收租户 WHERE。"""
    sql = "UPDATE threads SET unread_count = 0 WHERE id = :tid AND COALESCE(unread_count, 0) <> 0"
    params: dict = {"tid": thread_id}
    if business_id:
        sql += " AND business_id = :biz"
        params["biz"] = business_id
    async with get_session() as session:
        result = await session.execute(text(sql).bindparams(**params))
        await session.commit()
    return (result.rowcount or 0) > 0


async def release_takeover(thread_id: str, business_id: str | None = None) -> bool:
    """释放接管 → active,AI 暂停闸随状态自然解除。

    条件 UPDATE(status 必须正处接管态)保证幂等:重复释放 0 行,调用方据此
    不重复落系统消息。``business_id`` 提供时强校验租户边界(员工通道/socket
    通道传入,严防跨租户释放)。
    """
    sql = (
        "UPDATE threads SET status = 'active', assigned_operator_id = NULL, "
        "updated_at = NOW(), metadata = COALESCE(metadata, '{}'::jsonb) "
        "    - 'takeover_release_at' - 'takeover_requested_at' "
        "WHERE id = :tid AND status = 'human_takeover'"
    )
    params: dict = {"tid": thread_id}
    if business_id:
        sql += " AND business_id = :biz"
        params["biz"] = business_id
    sql += " RETURNING id"
    async with get_session() as session:
        released = (await session.execute(text(sql).bindparams(**params))).scalar() is not None
        await session.commit()
    return released


async def is_human_takeover(thread_id: str) -> bool:
    """AI 暂停闸读真源(网关入队前唯一判据)。线程不存在 → False(AI 照答)。"""
    async with get_session() as session:
        status = (
            await session.execute(text("SELECT status FROM threads WHERE id = :tid").bindparams(tid=thread_id))
        ).scalar()
    return status == "human_takeover"


_PAUSED_CLAIMED_NOTICE = "您的消息已由人工客服接待，请稍候人工坐席回复。"
_PAUSED_QUEUED_NOTICE = "已为您呼叫人工客服，正在排队等待接入，人工客服接入后将在本会话回复您。"


async def paused_reply(thread_id: str) -> str | None:
    """AI 暂停闸的顾客文案(网关各入队入口共用,2026-09-29 诚实化):接管态按
    认领与否分形 —— 排队中不说「已接待」(此前排队也回「已由人工客服接待」,
    坐席根本没接入,与实弹「转人工后人工不能接管」投诉同源的文案失真);
    认领后才承诺坐席回复。未接管回 None(调用方照常跑 AI)。"""
    state = await thread_state(thread_id)
    if state["status"] != "human_takeover":
        return None
    return _PAUSED_CLAIMED_NOTICE if state["assignedOperatorId"] else _PAUSED_QUEUED_NOTICE


async def mark_disconnect_deadlines(operator_email: str, timeout_seconds: float) -> int:
    """坐席掉线 → 其名下接管会话写释放 deadline。仅对尚无 deadline 的会话生效
    (首个 deadline 优先;重连取消后再次掉线才起新计时)。"""
    async with get_session() as session:
        result = await session.execute(
            text(
                "UPDATE threads SET updated_at = NOW(), "
                "metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), '{takeover_release_at}', "
                "to_jsonb(NOW() + make_interval(secs => :secs))) "
                "WHERE status = 'human_takeover' AND assigned_operator_id = :op "
                "AND NOT jsonb_exists(COALESCE(metadata, '{}'::jsonb), 'takeover_release_at')"
            ).bindparams(op=operator_email, secs=timeout_seconds)
        )
        await session.commit()
        return result.rowcount or 0


async def cancel_disconnect_deadlines(operator_email: str) -> int:
    """坐席重连信号(join/认领/发言)→ 取消其名下会话的释放计时。幂等。"""
    async with get_session() as session:
        result = await session.execute(
            text(
                "UPDATE threads SET updated_at = NOW(), "
                "metadata = COALESCE(metadata, '{}'::jsonb) - 'takeover_release_at' "
                "WHERE status = 'human_takeover' AND assigned_operator_id = :op "
                "AND jsonb_exists(COALESCE(metadata, '{}'::jsonb), 'takeover_release_at')"
            ).bindparams(op=operator_email)
        )
        await session.commit()
        return result.rowcount or 0


_RELEASE_NOTICE = "【系统提示】人工客服暂时离线超时，会话已自动释放，已为您切回 AI 智能助手。"
_QUEUE_FALLBACK_NOTICE = "【系统提示】当前人工坐席全忙，已为您切回 AI 智能助手继续服务；如需人工客服请再次呼叫。"


async def release_expired_takeovers() -> list[str]:
    """掉线超时释放扫描(权威路径)。先取过期集再逐线程条件释放:两扫描并发时
    各线程只被释放一次(条件 UPDATE 裁决),幂等 —— 重复扫描 0 行。"""
    async with get_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id FROM threads "
                    "WHERE status = 'human_takeover' AND assigned_operator_id IS NOT NULL "
                    "AND jsonb_exists(COALESCE(metadata, '{}'::jsonb), 'takeover_release_at') "
                    "AND (metadata->>'takeover_release_at')::timestamptz < NOW()"
                )
            )
        ).scalars().all()
    released: list[str] = []
    for thread_id in rows:
        if await release_takeover(str(thread_id)):
            released.append(str(thread_id))
            # 延迟导入:gatekeeper 顶层导入本模块,函数内导入避免回环
            from .gatekeeper import _add_system_message

            await _add_system_message(str(thread_id), "system", _RELEASE_NOTICE)
    return released


_QUEUE_EXPIRED_SQL = (
    "SELECT id FROM threads "
    "WHERE status = 'human_takeover' AND assigned_operator_id IS NULL "
    "AND jsonb_exists(COALESCE(metadata, '{}'::jsonb), 'takeover_requested_at') "
    "AND (metadata->>'takeover_requested_at')::timestamptz < NOW() - make_interval(secs => :secs)"
)


async def release_expired_queue_waits(timeout_seconds: float) -> list[str]:
    """排队超时回落 AI 扫描(live-desk-rework §2.3,默认 ≈5min 可配):呼叫后无人
    认领 → 自动回 ``active`` + system 告知,AI 暂停闸随状态自然解除,顾客可再次
    呼叫。与掉线超时释放(:func:`release_expired_takeovers`)共用 scheduler 扫描
    回路 —— 两个超时一个 worker。幂等:重复扫描 0 行(条件 UPDATE 裁决)。
    """
    async with get_session() as session:
        rows = (
            await session.execute(text(_QUEUE_EXPIRED_SQL).bindparams(secs=timeout_seconds))
        ).scalars().all()
    released: list[str] = []
    for thread_id in rows:
        if await release_takeover(str(thread_id)):
            released.append(str(thread_id))
            from .gatekeeper import _add_system_message

            await _add_system_message(str(thread_id), "system", _QUEUE_FALLBACK_NOTICE)
    return released
