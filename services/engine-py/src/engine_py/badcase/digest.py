"""候选池周度摘要与保留期执行。

保留策略(2026-09-03 评审):``candidate`` 90 天、``dismissed`` 30 天;
``converted`` 完结留痕不清理。摘要供周度 triage 评审使用。
"""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import delete, func, select, update

from ..db import BadcaseCandidate, get_session

CANDIDATE_TTL_DAYS = 90
DISMISSED_TTL_DAYS = 30


async def run_badcase_digest() -> dict:
    """输出池分布摘要,并执行保留期:过期 candidate 自动转 dismissed、过期 dismissed 清除。"""
    now = _dt.datetime.now()
    summary: dict = {"distribution": {}, "expired": 0, "purged": 0}
    try:
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(BadcaseCandidate.signal_source, BadcaseCandidate.status, func.count())
                    .group_by(BadcaseCandidate.signal_source, BadcaseCandidate.status)
                    .order_by(BadcaseCandidate.signal_source)
                )
            ).all()
            for source, status, count in rows:
                summary["distribution"].setdefault(source, {})[status] = int(count)

            expired = await session.execute(
                update(BadcaseCandidate)
                .where(
                    BadcaseCandidate.status == "candidate",
                    BadcaseCandidate.created_at <= now - _dt.timedelta(days=CANDIDATE_TTL_DAYS),
                )
                .values(
                    status="dismissed",
                    note=func.coalesce(BadcaseCandidate.note, "") + "; auto-expired(90d)",
                    updated_at=now,
                )
            )
            summary["expired"] = int(expired.rowcount or 0)

            purged = await session.execute(
                delete(BadcaseCandidate).where(
                    BadcaseCandidate.status == "dismissed",
                    BadcaseCandidate.updated_at <= now - _dt.timedelta(days=DISMISSED_TTL_DAYS),
                )
            )
            summary["purged"] = int(purged.rowcount or 0)
            await session.commit()
        print(f"[BadcaseDigest] 池分布={summary['distribution']} 过期转dismissed={summary['expired']} 清理={summary['purged']}")
    except Exception as err:  # noqa: BLE001 — 摘要失败不影响调度框架
        print(f"[BadcaseDigest] 摘要/保留期执行异常: {err}")
    return summary
