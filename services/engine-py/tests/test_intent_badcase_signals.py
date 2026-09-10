"""坏例池两个新信号源(intent-arbitration 02,2026-09-10)。

- ``intent_conflict``:仲裁候选跨意图族(动作形 × 咨询/兜底形)→ 候选行,
  先验 neutral(快轨合法压制非 LLM 层属设计行为,人审定性);
- ``claim_mismatch``:终稿宣称已退款/审批 × 审批表整会话零记录 → 候选行,
  先验 suspected_defect(无中生有的宣称几乎必是缺陷)。

检测口径与 01 的留痕形状、07 的冲突检测三方一致(同一 _CONSULT_SIDE_INTENTS
语义);入池走 record_badcase_signal 静默降级,本套只测检测与落库正确性。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from engine_py.badcase import intent_signals
from engine_py.badcase.pool import SOURCE_CLAIM_MISMATCH, SOURCE_INTENT_CONFLICT
from engine_py.db import BadcaseCandidate, PendingApproval, Thread, get_session
from engine_py.triage.intent_triage_engine import IntentTriageEngine


def _prop(layer: str, intent: str, confidence: float | None = 0.9) -> dict:
    return {"layer": layer, "intent": intent, "confidence": confidence}


class TestDetectIntentConflict:
    def test_action_vs_consult_conflicts(self):
        """b1 靶场景:槽位判动作形 × 分类器判咨询形(双向都算)。"""
        conflict = intent_signals.detect_intent_conflict(
            [_prop("slot_extractor", "order_return", 0.95), _prop("structured_llm", "consult", 0.9)]
        )
        assert conflict is not None
        assert {conflict["a"]["intent"], conflict["b"]["intent"]} == {"order_return", "consult"}

        assert (
            intent_signals.detect_intent_conflict(
                [_prop("slot_extractor", "chat", 0.4), _prop("structured_llm", "refund", 0.9)]
            )
            is not None
        ), "槽位判 chat × 分类器判动作同样跨族(07 要治的反向样本)"

    def test_same_side_or_same_intent_not_conflict(self):
        assert intent_signals.detect_intent_conflict(None) is None
        assert intent_signals.detect_intent_conflict([_prop("slot_extractor", "refund")]) is None
        # 同族异议:general_query vs out_of_scope,无动作形参与
        assert (
            intent_signals.detect_intent_conflict(
                [_prop("embedding", "out_of_scope", 0.86), _prop("structured_llm", "general_query")]
            )
            is None
        )
        # 同意图双层一致:判定 1 的双 embedding 提议之间、跨层同名均不算
        assert (
            intent_signals.detect_intent_conflict(
                [
                    _prop("slot_extractor", "order_query"),
                    _prop("embedding", "order_status"),
                    _prop("structured_llm", "order_status"),
                ]
            )
            is None
        ), "order_query/order_status 同为动作形订单族,不跨族"


class TestDetectClaim:
    def test_positive_claims(self):
        for text in (
            "已为您发起退款申请,请耐心等待。",
            "退款已经提交成功,预计 1-3 个工作日到账。",
            "已经为您办理退货工单。",
            "审批已通过,正在为您安排退款。",
        ):
            assert intent_signals.detect_claim(text), f"宣称未命中: {text}"

    def test_negative_or_plain_not_claim(self):
        for text in (
            "尚未为您发起退款,请先补充订单号。",
            "未查询到订单 ORD-77777,或该订单不属于当前账户。",
            "退货政策是 7 天无理由。",
            "您好！请问有什么可以帮您？",
        ):
            assert not intent_signals.detect_claim(text), f"非宣称被误命中: {text}"


@pytest.mark.usefixtures("pg_factory")
class TestSignalIngestion:
    """密封 PG:两路信号真实落池 + 挂点接线。"""

    def _thread(self, thread_id: str) -> None:
        async def _seed() -> None:
            async with get_session() as session:
                session.add(Thread(id=thread_id, business_id="ecommerce"))
                await session.commit()

        asyncio.run(_seed())

    def _pool_rows(self, source: str, thread_id: str | None = None) -> list[BadcaseCandidate]:
        """密封 PG 全套件共享,断言按源(或源×会话引用)过滤防跨测试串扰。"""

        async def _q() -> list:
            async with get_session() as session:
                stmt = select(BadcaseCandidate).where(BadcaseCandidate.signal_source == source)
                if thread_id:
                    stmt = stmt.where(BadcaseCandidate.conversation_ref == f"thread:{thread_id}")
                return list((await session.execute(stmt)).scalars().all())

        return asyncio.run(_q())

    def test_intent_conflict_writes_candidate_row(self):
        self._thread("thread_sig_conflict")
        asyncio.run(
            intent_signals.record_intent_conflict_if_any(
                "thread_sig_conflict",
                [_prop("slot_extractor", "order_return", 0.95), _prop("structured_llm", "consult", 0.88)],
            )
        )
        rows = self._pool_rows(SOURCE_INTENT_CONFLICT, "thread_sig_conflict")
        assert len(rows) == 1
        row = rows[0]
        assert row.conversation_ref == "thread:thread_sig_conflict"
        assert row.business_id == "ecommerce", "租户随 thread 归属带出"
        assert row.suggested_class == "neutral"
        assert "slot_extractor=order_return" in (row.note or "")
        assert "structured_llm=consult" in (row.note or "")

    def test_log_intent_to_db_wiring_triggers_conflict_signal(self):
        """挂点接线:log_intent_to_db 落库成功后冲突候选自动入池(01×02 串联)。"""
        self._thread("thread_sig_wiring")
        asyncio.run(
            IntentTriageEngine.log_intent_to_db(
                "thread_sig_wiring",
                "退货政策是什么",
                [{"intent": "consult", "confidence": 0.88}],
                "structured_llm",
                0.88,
                candidates=[
                    _prop("slot_extractor", "order_return", 0.95),
                    _prop("structured_llm", "consult", 0.88),
                ],
                arbitration_reason="structured_llm_terminal",
            )
        )
        assert len(self._pool_rows(SOURCE_INTENT_CONFLICT, "thread_sig_wiring")) == 1

    def test_claim_mismatch_zero_approval_writes_row(self):
        self._thread("thread_sig_claim")
        asyncio.run(
            intent_signals.record_claim_mismatch_if_any(
                "thread_sig_claim", "ecommerce", "已为您发起退款申请,请耐心等待。"
            )
        )
        rows = self._pool_rows(SOURCE_CLAIM_MISMATCH, "thread_sig_claim")
        assert len(rows) == 1
        row = rows[0]
        assert row.suggested_class == "suspected_defect"
        assert "已为您发起退款申请" in (row.note or "")

    def test_claim_with_backing_approval_not_flagged(self):
        self._thread("thread_sig_claim_ok")

        async def _seed_approval() -> None:
            async with get_session() as session:
                session.add(
                    PendingApproval(
                        thread_id="thread_sig_claim_ok",
                        action_type="process_refund",
                        deadline=datetime.now() + timedelta(days=1),
                    )
                )
                await session.commit()

        asyncio.run(_seed_approval())
        asyncio.run(
            intent_signals.record_claim_mismatch_if_any(
                "thread_sig_claim_ok", "ecommerce", "审批已通过,退款已经提交成功。"
            )
        )
        assert self._pool_rows(SOURCE_CLAIM_MISMATCH, "thread_sig_claim_ok") == [], "有审批记录背书的宣称不入池"

    def test_plain_reply_never_flags(self):
        self._thread("thread_sig_plain")
        asyncio.run(
            intent_signals.record_claim_mismatch_if_any(
                "thread_sig_plain", "ecommerce", "您的订单 ORD-10001 已发货,预计明日送达。"
            )
        )
        assert self._pool_rows(SOURCE_CLAIM_MISMATCH, "thread_sig_plain") == []


if __name__ == "__main__":
    pytest.main([__file__])
