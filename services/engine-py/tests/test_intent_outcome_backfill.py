"""澄清标签回填回归(P2 前置,2026-09-23):P0 澄清反问后的下一轮终局决策
把 winner 写回澄清行 actual_outcome —— silver label 的第一个积累通道
(盘点:actual_outcome 0/2045,P2 蒸馏的真正瓶颈是标签不是量)。

四轴:①澄清后首轮决策回填;②只回填最新待回填行且不覆写已回填;
③降级兜底行(structured_llm_fallback)不作标签源;④无待回填时静默 no-op。
走真实 log_intent_to_db(容器 DB),不桩 session。
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from engine_py.db import get_session
from engine_py.triage.intent_triage_engine import IntentTriageEngine

_TID = "thread-backfill-test"


async def _clear():
    async with get_session() as session:
        # intent_logs.thread_id 有 threads 外键:先保证线程行存在
        await session.execute(
            text("INSERT INTO threads (id, business_id) VALUES (:t, 'aurora') "
                 "ON CONFLICT (id) DO NOTHING").bindparams(t=_TID)
        )
        await session.execute(text("DELETE FROM intent_logs WHERE thread_id = :t").bindparams(t=_TID))
        await session.commit()


async def _rows():
    async with get_session() as session:
        result = await session.execute(
            text(
                "SELECT method, winner, actual_outcome FROM intent_logs "
                "WHERE thread_id = :t ORDER BY created_at ASC"
            ).bindparams(t=_TID)
        )
        return result.mappings().all()


def test_clarify_row_backfilled_by_next_decision(pg_factory):
    async def scenario():
        await _clear()
        # 澄清轮(method=confidence_cascade,经 handle_immediate_bypass 同款标记)
        await IntentTriageEngine.log_intent_to_db(
            _TID, "帮我搞一下那个东西", [{"intent": "shopping_guide", "confidence": 0.4}],
            "confidence_cascade", 0.4,
        )
        # 下一轮:用户答复后正常终局
        await IntentTriageEngine.log_intent_to_db(
            _TID, "商品推荐", [{"intent": "shopping_guide", "confidence": 0.93}],
            "structured_llm", 0.93,
        )
        return await _rows()

    rows = asyncio.run(scenario())
    assert len(rows) == 2
    clarify = next(r for r in rows if r["method"] == "confidence_cascade")
    assert clarify["actual_outcome"] == "shopping_guide", f"澄清行必须回填真实意图: {dict(clarify)}"
    follow = next(r for r in rows if r["method"] == "structured_llm")
    assert follow["actual_outcome"] is None, "回填只贴澄清行,不污染普通行"


def test_backfill_once_not_overwritten(pg_factory):
    async def scenario():
        await _clear()
        await IntentTriageEngine.log_intent_to_db(
            _TID, "那个啥", [{"intent": "consult", "confidence": 0.35}],
            "confidence_cascade", 0.35,
        )
        await IntentTriageEngine.log_intent_to_db(
            _TID, "退货政策", [{"intent": "consult", "confidence": 0.9}],
            "structured_llm", 0.9,
        )
        # 第三轮:话题已换,不得改写已回填标签
        await IntentTriageEngine.log_intent_to_db(
            _TID, "查订单", [{"intent": "order_query", "confidence": 0.95}],
            "structured_llm", 0.95,
        )
        return await _rows()

    rows = asyncio.run(scenario())
    clarify = next(r for r in rows if r["method"] == "confidence_cascade")
    assert clarify["actual_outcome"] == "consult", "只认澄清后首轮,后续轮不得覆写"


def test_fallback_decision_is_not_label_source(pg_factory):
    async def scenario():
        await _clear()
        await IntentTriageEngine.log_intent_to_db(
            _TID, "嗯嗯那个", [{"intent": "general_query", "confidence": 0.4}],
            "confidence_cascade", 0.4,
        )
        # 下一轮恰逢 LLM 熔断降级 —— 兜底行不配作标签
        await IntentTriageEngine.log_intent_to_db(
            _TID, "算了", [{"intent": "general_query", "confidence": 0.5}],
            "structured_llm_fallback", 0.5,
        )
        return await _rows()

    rows = asyncio.run(scenario())
    clarify = next(r for r in rows if r["method"] == "confidence_cascade")
    assert clarify["actual_outcome"] is None, "降级兜底行严禁作标签源"


def test_no_pending_clarify_is_silent_noop(pg_factory):
    async def scenario():
        await _clear()
        n = await IntentTriageEngine.backfill_clarify_outcome(_TID, "order_query")
        rows = await _rows()
        return n, rows

    n, rows = asyncio.run(scenario())
    assert n == 0 and rows == [], "无待回填行时静默 no-op"
