"""坏例审结回填回归(P2 通道②,2026-09-23):review_badcase.py 的人审定性
把真实意图写回线程最近待回填 intent_logs 行,坏例状态 candidate→labeled;
dismiss 不动标签;已审结拒绝重复定性。

走真实 get_session(容器 DB);脚本函数以模块导入方式复用(sys.path 注入
与 export_intent_data 同款)。
"""

from __future__ import annotations

import asyncio
import sys
import uuid as _uuid
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from review_badcase import dismiss_badcase, label_badcase, list_pending

from engine_py.db import get_session

_TID = "thread-review-badcase-test"


async def _seed_badcase(note: str = "跨意图族冲突: slot_extractor=refund@0.95 vs structured_llm=consult@0.4") -> str:
    async with get_session() as session:
        await session.execute(
            text("INSERT INTO threads (id, business_id) VALUES (:t, 'aurora') "
                 "ON CONFLICT (id) DO NOTHING").bindparams(t=_TID)
        )
        await session.execute(
            text("DELETE FROM intent_logs WHERE thread_id = :t").bindparams(t=_TID)
        )
        # 该线程一条待回填的终局行(winner 判了 refund,人工将定性为 consult)
        await session.execute(
            text(
                "INSERT INTO intent_logs (thread_id, input_text, predicted_intents, method, "
                "confidence, winner, candidates) VALUES "
                "(:t, '退货政策是什么', '[{\"intent\": \"refund\"}]'::jsonb, "
                "'structured_llm', 0.42, 'refund', '[]'::jsonb)"
            ).bindparams(t=_TID)
        )
        bid = str(_uuid.uuid4())
        await session.execute(
            text(
                "INSERT INTO badcase_candidates (id, signal_source, conversation_ref, business_id, "
                "status, note) VALUES (CAST(:i AS uuid), 'intent_conflict', :ref, 'aurora', 'candidate', :n)"
            ).bindparams(i=bid, ref=f"thread:{_TID}", n=note)
        )
        await session.commit()
        return bid


async def _outcome() -> str | None:
    async with get_session() as session:
        return (
            await session.execute(
                text("SELECT actual_outcome FROM intent_logs WHERE thread_id = :t").bindparams(t=_TID)
            )
        ).scalar()


async def _badcase_status(bid: str) -> str:
    async with get_session() as session:
        return (
            await session.execute(
                text("SELECT status FROM badcase_candidates WHERE id = CAST(:i AS uuid)").bindparams(i=bid)
            )
        ).scalar()


def test_label_backfills_outcome_and_closes_badcase(pg_factory):
    async def scenario():
        bid = await _seed_badcase()
        out = await label_badcase(bid, "consult")
        return out, await _outcome(), await _badcase_status(bid), bid

    out, outcome, status, _ = asyncio.run(scenario())
    assert "error" not in out, out
    assert out["backfilled_rows"] == 1, f"必须回写一条: {out}"
    assert outcome == "consult", "人审定性是 ground truth,覆写待回填行"
    assert status == "labeled"


def test_double_label_rejected(pg_factory):
    async def scenario():
        bid = await _seed_badcase()
        first = await label_badcase(bid, "consult")
        second = await label_badcase(bid, "refund")
        return first, second, await _outcome()

    first, second, outcome = asyncio.run(scenario())
    assert "error" not in first
    assert "error" in second, "已审结坏例必须拒绝重复定性"
    assert outcome == "consult", "拒绝的第二次定性不得改标签"


def test_dismiss_leaves_labels_untouched(pg_factory):
    async def scenario():
        bid = await _seed_badcase()
        out = await dismiss_badcase(bid)
        return out, await _outcome(), await _badcase_status(bid)

    out, outcome, status = asyncio.run(scenario())
    assert "error" not in out
    assert outcome is None, "dismiss 不写标签"
    assert status == "dismissed"


def test_list_pending_shows_last_decision(pg_factory):
    async def scenario():
        await _seed_badcase()
        return await list_pending(limit=50)

    items = asyncio.run(scenario())
    mine = [i for i in items if i["thread_id"] == _TID]
    assert mine, "种子的坏例必须出现在待审列表"
    assert mine[0]["last_decision"]["winner"] == "refund"
    assert mine[0]["last_decision"]["input_text"] == "退货政策是什么"
