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


async def assign_operator(thread_id: str, operator_email: str, business_id: str | None = None) -> None:
    """坐席认领/发言 → 接管中 + 认领坐席;清掉线释放 deadline(认领即活人在线)。

    ``business_id`` 提供时收租户 WHERE(socket 链传入,与 update_conversation_status
    同口径);gatekeeper 内部路径线程归属已由路由层校验,不传。
    """
    sql = (
        "UPDATE threads SET status = 'human_takeover', assigned_operator_id = :op, "
        "updated_at = NOW(), metadata = COALESCE(metadata, '{}'::jsonb) - 'takeover_release_at' "
        "WHERE id = :tid"
    )
    params: dict = {"op": operator_email, "tid": thread_id}
    if business_id:
        sql += " AND business_id = :biz"
        params["biz"] = business_id
    async with get_session() as session:
        await session.execute(text(sql).bindparams(**params))
        await session.commit()


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
