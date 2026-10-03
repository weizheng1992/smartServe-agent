"""标注水龙头 —— 谁有资格写 ``intent_logs.actual_outcome``,以及怎么写。

silver label 三通道的资格谓词与回写 SQL 的唯一实现,互补关系从「三份注释
互指」收敛为单点(互斥契约由 tests/test_outcome_labeling.py 一册钉死):

- ① 置信级联(``backfill_clarify_outcome``,在线热路径):仅澄清行
  (confidence_cascade)+ 30 分钟窗,单 thread 最近一行;自管事务、静默降级;
- ② 人审定性(``backfill_pending_outcome``,review_badcase):不限 method、
  无时间窗 —— 人审是 ground truth;借用调用方 session,标签回写与坏例
  状态变更必须同一事务提交;
- ③ 规则复判(``backfillable_rows`` + ``write_outcome_by_id``,CLI 批量):
  排除 confidence_cascade(澄清行的标签走通道①用户后续选择,严禁在此
  硬贴),批量扫描逐行贴。

纪律:
- **一次写入**:任何通道对已回填行(actual_outcome 非 NULL)零影响 ——
  资格谓词的 IS NULL 门槛 + ``write_outcome_by_id`` 回写时再验,先到先得;
- **时间资格 Python 侧参数化**(原 ``NOW() - INTERVAL`` 手写 SQL 为
  PG-only 且绑死 DB 服务器时钟),跨方言可测;
- 全 ORM,严禁绕开本 module 手写 actual_outcome 回写 SQL。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update

from ..db import IntentLog, get_session

# 通道①独占(澄清反问行标记);通道③排除同值 —— 互补谓词的唯一事实点
CLARIFY_METHOD = "confidence_cascade"

# 通道①时间资格:用户隔天回来的无关消息不该给昨天的澄清贴标签
CLARIFY_MAX_AGE = timedelta(minutes=30)


def _outcome_cutoff(max_age: timedelta) -> datetime:
    """now(UTC) 去 tz(表内 created_at 为 DB 服务器 naive now(),同形比较)。"""
    return datetime.now(UTC).replace(tzinfo=None) - max_age


def _pending_outcome_criteria(
    stmt,
    *,
    only_method: str | None = None,
    exclude_methods: tuple[str, ...] = (),
    max_age: timedelta | None = None,
):
    """待回填行资格谓词单点:IS NULL 门槛(一次写入)+ 各通道 method/时间资格。"""
    stmt = stmt.where(IntentLog.actual_outcome.is_(None))
    if only_method is not None:
        stmt = stmt.where(IntentLog.method == only_method)
    for excluded in exclude_methods:
        # method IS NULL 的行保留(原 SQL 的 method IS NULL OR <> ALL 语义)
        stmt = stmt.where(IntentLog.method.is_(None) | (IntentLog.method != excluded))
    if max_age is not None:
        stmt = stmt.where(IntentLog.created_at >= _outcome_cutoff(max_age))
    return stmt


async def backfill_clarify_outcome(thread_id: str, winner: str | None) -> int:
    """通道①(在线):澄清后首轮终局 winner 写回该线程最新澄清行。

    资格 = method=confidence_cascade + actual_outcome IS NULL + 30 分钟窗,
    单 thread 最近一行(多轮连续澄清只认最后一次)。自管事务、静默降级,
    返回影响行数(0 = 无待回填/失败)。
    """
    if not thread_id or not winner:
        return 0
    try:
        async with get_session() as session:
            row_id = (
                await session.execute(
                    _pending_outcome_criteria(
                        select(IntentLog.id)
                        .where(IntentLog.thread_id == thread_id)
                        .order_by(IntentLog.created_at.desc())
                        .limit(1),
                        only_method=CLARIFY_METHOD,
                        max_age=CLARIFY_MAX_AGE,
                    )
                )
            ).scalar_one_or_none()
            if row_id is None:
                return 0
            written = await write_outcome_by_id(session, row_id, winner)
            await session.commit()
            return written
    except Exception as err:
        print(f"[Triage] 澄清标签回填失败,已跳过 (threadId={thread_id}): {err}")
        return 0


async def backfill_pending_outcome(session: Any, thread_id: str, winner: str) -> int:
    """通道②核(人审定性):单 thread 最近一条待回填行贴 winner。

    不限 method、无时间窗;借用调用方 session(与坏例状态变更同事务),
    不 commit。返回影响行数(0 = 无可回写行)。
    """
    if not thread_id or not winner:
        return 0
    row_id = (
        await session.execute(
            _pending_outcome_criteria(
                select(IntentLog.id)
                .where(IntentLog.thread_id == thread_id)
                .order_by(IntentLog.created_at.desc())
                .limit(1)
            )
        )
    ).scalar_one_or_none()
    if row_id is None:
        return 0
    return await write_outcome_by_id(session, row_id, winner)


async def backfillable_rows(session: Any, limit: int = 2000) -> list:
    """通道③扫描:规则复判可处理的历史行 (id, input_text, method)。

    资格 = actual_outcome IS NULL + input_text 非空 + 排除 confidence_cascade;
    created_at DESC、受 limit 约束。
    """
    stmt = _pending_outcome_criteria(
        select(IntentLog.id, IntentLog.input_text, IntentLog.method).where(
            func.coalesce(IntentLog.input_text, "") != ""
        ),
        exclude_methods=(CLARIFY_METHOD,),
    ).order_by(IntentLog.created_at.desc()).limit(limit)
    return (await session.execute(stmt)).all()


async def write_outcome_by_id(session: Any, row_id: Any, winner: str) -> int:
    """按 id 贴标签;IS NULL 门槛回写时再验一次(一次写入,先到先得)。"""
    result = await session.execute(
        update(IntentLog)
        .where(IntentLog.id == row_id, IntentLog.actual_outcome.is_(None))
        .values(actual_outcome=winner)
    )
    return result.rowcount or 0
