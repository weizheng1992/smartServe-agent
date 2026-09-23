"""坏例审结 CLI(P2 通道②,2026-09-23):人审定性 → 回写 silver label。

坏例池 520 条 intent_conflict 候选积压待审;审结动作把人工判定的真实
意图写回该线程最近一条 actual_outcome 为空的 intent_logs 行(P2 蒸馏
标签源②),并把坏例行置为 labeled;非缺陷可 dismiss(置 dismissed,
不动标签)。与通道①(澄清自动回填,log_intent_to_db 内联)互补。

用法(services/engine-py 下)::

    uv run python scripts/review_badcase.py list [--limit 20]
    uv run python scripts/review_badcase.py label <badcase_id> --intent promotion_query
    uv run python scripts/review_badcase.py dismiss <badcase_id>

label 语义:该坏例对应线程的「用户真实意图」是 --intent;找不到可回写的
intent_logs 行时仍标记坏例为 labeled 并在 stderr 提示(标签可能已被通道①
写走,属正常)。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select, text

from engine_py.db import BadcaseCandidate, get_session

STATUS_LABELED = "labeled"
STATUS_DISMISSED = "dismissed"


def _thread_ref(conversation_ref: str) -> str:
    return conversation_ref.removeprefix("thread:") if conversation_ref.startswith("thread:") else conversation_ref


async def list_pending(limit: int = 20) -> list[dict]:
    """待审 intent_conflict 候选,附该线程最近一次终局(winner/method)。"""
    async with get_session() as session:
        rows = (
            await session.execute(
                select(BadcaseCandidate)
                .where(
                    BadcaseCandidate.signal_source == "intent_conflict",
                    BadcaseCandidate.status == "candidate",
                )
                .order_by(BadcaseCandidate.created_at.asc())
                .limit(limit)
            )
        ).scalars().all()
        out: list[dict] = []
        for row in rows:
            thread_id = _thread_ref(row.conversation_ref)
            last = (
                await session.execute(
                    text(
                        "SELECT input_text, winner, method, actual_outcome FROM intent_logs "
                        "WHERE thread_id = :t ORDER BY created_at DESC LIMIT 1"
                    ).bindparams(t=thread_id)
                )
            ).mappings().first()
            out.append(
                {
                    "badcase_id": str(row.id),
                    "thread_id": thread_id,
                    "note": row.note,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "last_decision": dict(last) if last else None,
                }
            )
        return out


async def label_badcase(badcase_id: str, intent: str) -> dict:
    """人审定性:回写线程最近一条待回填 intent_logs 的 actual_outcome,
    坏例置 labeled。返回 {labeled_badcase, backfilled_rows, thread_id}。"""
    async with get_session() as session:
        row = (
            await session.execute(
                select(BadcaseCandidate).where(BadcaseCandidate.id == uuid.UUID(badcase_id))
            )
        ).scalar_one_or_none()
        if row is None:
            return {"error": f"坏例不存在: {badcase_id}"}
        if row.status != "candidate":
            return {"error": f"坏例已审结(status={row.status}),拒绝重复定性"}
        thread_id = _thread_ref(row.conversation_ref)
        result = await session.execute(
            text(
                "UPDATE intent_logs SET actual_outcome = :w "
                "WHERE id = (SELECT id FROM intent_logs WHERE thread_id = :t "
                "  AND actual_outcome IS NULL ORDER BY created_at DESC LIMIT 1)"
            ).bindparams(t=thread_id, w=intent)
        )
        row.status = STATUS_LABELED
        row.note = (row.note or "") + f" | 人审定性: {intent}"
        await session.commit()
        return {
            "labeled_badcase": badcase_id,
            "backfilled_rows": result.rowcount or 0,
            "thread_id": thread_id,
        }


async def dismiss_badcase(badcase_id: str) -> dict:
    """非缺陷/不采:置 dismissed,不动任何标签。"""
    async with get_session() as session:
        row = (
            await session.execute(
                select(BadcaseCandidate).where(BadcaseCandidate.id == uuid.UUID(badcase_id))
            )
        ).scalar_one_or_none()
        if row is None:
            return {"error": f"坏例不存在: {badcase_id}"}
        if row.status != "candidate":
            return {"error": f"坏例已审结(status={row.status})"}
        row.status = STATUS_DISMISSED
        await session.commit()
        return {"dismissed_badcase": badcase_id}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list", help="待审候选(含线程最近终局)")
    p_list.add_argument("--limit", type=int, default=20)
    p_label = sub.add_parser("label", help="人审定性 → 回写 actual_outcome")
    p_label.add_argument("badcase_id")
    p_label.add_argument("--intent", required=True, help="用户真实意图档位名")
    p_dismiss = sub.add_parser("dismiss", help="非缺陷,置 dismissed 不动标签")
    p_dismiss.add_argument("badcase_id")
    args = parser.parse_args()

    if args.cmd == "list":
        for item in asyncio.run(list_pending(args.limit)):
            print(json.dumps(item, ensure_ascii=False))
        return 0
    if args.cmd == "label":
        out = asyncio.run(label_badcase(args.badcase_id, args.intent))
    else:
        out = asyncio.run(dismiss_badcase(args.badcase_id))
    print(json.dumps(out, ensure_ascii=False))
    return 1 if "error" in out else 0


if __name__ == "__main__":
    raise SystemExit(main())
