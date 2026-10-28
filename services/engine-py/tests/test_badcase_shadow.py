"""badcase 回灌 shadow 集单测(docs/multi-turn-task-state.md P0-2,2026-10-24)。

裁决 D7:高置信信号(suspected_defect 先验族)自动起草用例草稿进 shadow 集
—— 夜评对 shadow 只跑只报告、不出闸;人审 `promote` 一键转正进硬闸集。
纪律:自动只到 shadow 为止;起草输入必须过脱敏管道(仓库零原始数据,
cmd_draft 兜底再脱敏同律);入池/起草失败静默降级绝不阻断(观测性规范)。
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select, update

from engine_py.badcase.pool import SOURCE_CLAIM_MISMATCH, SOURCE_INTENT_CONFLICT, SOURCE_PERSONA_FACT_DELETED
from engine_py.badcase.shadow import (
    AUTO_DRAFT_SOURCES,
    build_shadow_case,
    load_pending,
    merge_shadow_case,
    remove_shadow_case,
    save_pending,
)
from engine_py.db import BadcaseCandidate, Message, Thread, get_session

pytestmark = pytest.mark.usefixtures("pg_factory")


class TestPureCaseSurgery:
    def test_build_shape_and_origin(self):
        case = build_shadow_case("12345678-aaaa-bbbb-cccc-dddddddddddd", SOURCE_CLAIM_MISMATCH, "帮我查退款")
        assert case["description"].startswith("[badcase:12345678]")
        assert SOURCE_CLAIM_MISMATCH in case["description"]
        assert case["vars"]["origin"] == "badcase:12345678-aaaa-bbbb-cccc-dddddddddddd"
        assert case["vars"]["input"] == "帮我查退款"
        assert case["assert"] == [], "断言最小化:自动起草不带任何断言(人审 promote 时补)"

    def test_merge_dedupes_by_origin(self):
        c1 = build_shadow_case("id-1", SOURCE_CLAIM_MISMATCH, "输入一")
        c2 = build_shadow_case("id-2", SOURCE_CLAIM_MISMATCH, "输入二")
        merged = merge_shadow_case([c1, c2], build_shadow_case("id-1", SOURCE_CLAIM_MISMATCH, "输入一改"))
        assert len(merged) == 2
        assert merged[-1]["vars"]["input"] == "输入一改"  # 同 origin 替换并沉底

    def test_remove_found_and_missing(self):
        c1 = build_shadow_case("id-1", SOURCE_CLAIM_MISMATCH, "x")
        c2 = build_shadow_case("id-2", SOURCE_CLAIM_MISMATCH, "y")
        case, rest = remove_shadow_case([c1, c2], "badcase:id-1")
        assert case is not None and case["vars"]["origin"] == "badcase:id-1"
        assert rest == [c2]
        case, rest = remove_shadow_case([c1], "badcase:无")
        assert case is None and rest == [c1]

    def test_pending_roundtrip_and_corrupt_fallback(self, tmp_path):
        p = tmp_path / "pending.json"
        assert load_pending(p) == [], "文件缺失 → 空表(首跑即用)"
        save_pending(p, [build_shadow_case("id-1", SOURCE_CLAIM_MISMATCH, "x")])
        assert len(load_pending(p)) == 1
        p.write_text("{坏的", encoding="utf-8")
        assert load_pending(p) == [], "坏 JSON → 空表兜底,不抛"


@pytest.mark.usefixtures("pg_factory")
class TestAutoDraft:
    def _thread(self, thread_id: str) -> None:
        async def _seed() -> None:
            async with get_session() as session:
                session.add(Thread(id=thread_id, business_id="ecommerce"))
                await session.commit()

        asyncio.run(_seed())

    def _message(self, thread_id: str, role: str, content: str, ts: str) -> None:
        async def _seed() -> None:
            async with get_session() as session:
                session.add(
                    Message(
                        id=f"msg_{thread_id}_{ts}",
                        thread_id=thread_id,
                        business_id="ecommerce",
                        role=role,
                        content=content,
                        timestamp=ts,
                    )
                )
                await session.commit()

        asyncio.run(_seed())

    def _candidate(self, source: str, thread_id: str, status: str = "candidate") -> str:
        async def _seed() -> str:
            async with get_session() as session:
                row = BadcaseCandidate(
                    signal_source=source,
                    conversation_ref=f"thread:{thread_id}",
                    business_id="ecommerce",
                    suggested_class="suspected_defect",
                    status=status,
                    note="终稿宣称[已为您发起退款]但审批表无任何记录",
                )
                session.add(row)
                await session.commit()
                return str(row.id)

        return asyncio.run(_seed())

    def _status_of(self, candidate_id: str) -> str | None:
        async def _q() -> str | None:
            async with get_session() as session:
                row = (
                    await session.execute(
                        select(BadcaseCandidate.status).where(BadcaseCandidate.id == candidate_id).limit(1)
                    )
                ).scalar_one_or_none()
                return row

        return asyncio.run(_q())

    def test_claim_mismatch_auto_drafts_redacted_case(self, tmp_path):
        from engine_py.badcase.shadow import auto_draft_shadow_cases

        pending = tmp_path / "pending.json"
        self._thread("thread_shadow_a")
        self._message("thread_shadow_a", "user", "我的订单 A-100 怎么还不退款,联系我 13800138000", "2026-10-24T10:00:00")
        cid = self._candidate(SOURCE_CLAIM_MISMATCH, "thread_shadow_a")

        summary = asyncio.run(auto_draft_shadow_cases(pending_path=pending))
        assert summary["drafted"] == 1 and summary["skipped"] == 0
        cases = load_pending(pending)
        assert len(cases) == 1
        assert cases[0]["vars"]["origin"] == f"badcase:{cid}"
        assert cases[0]["vars"]["input"], "输入取自脱敏管道产物,非空"
        assert self._status_of(cid) == "shadow_draft"

    def test_idempotent_and_status_filter(self, tmp_path):
        from engine_py.badcase.shadow import auto_draft_shadow_cases

        pending = tmp_path / "pending.json"
        self._thread("thread_shadow_b")
        self._message("thread_shadow_b", "user", "已提交的退款什么时候到账", "2026-10-24T10:00:00")
        self._candidate(SOURCE_CLAIM_MISMATCH, "thread_shadow_b")
        asyncio.run(auto_draft_shadow_cases(pending_path=pending))

        summary2 = asyncio.run(auto_draft_shadow_cases(pending_path=pending))
        assert summary2["drafted"] == 0, "已转 shadow_draft 的候选不再重复起草"
        assert len(load_pending(pending)) == 1

    def test_neutral_source_and_non_thread_ref_skipped(self, tmp_path):
        from engine_py.badcase.shadow import auto_draft_shadow_cases

        pending = tmp_path / "pending.json"
        self._thread("thread_shadow_c")
        self._message("thread_shadow_c", "user", "退货政策是什么", "2026-10-24T10:00:00")
        self._candidate(SOURCE_INTENT_CONFLICT, "thread_shadow_c")  # neutral 先验:不自动起草
        cid_no_thread = self._candidate(SOURCE_CLAIM_MISMATCH, "thread_shadow_c")
        # 改写 ref 为非 thread 形(无对话原文可取)→ skip
        asyncio.run(_set_ref(cid_no_thread, "approval:xyz"))

        summary = asyncio.run(auto_draft_shadow_cases(pending_path=pending))
        # 共享 PG 跨测试有既有候选,只断言本测候选的结局,不钉全局计数
        assert summary["drafted"] == 0
        assert all(c["vars"]["origin"] != f"badcase:{cid_no_thread}" for c in load_pending(pending))
        assert self._status_of(cid_no_thread) == "candidate"

    def test_thread_without_user_message_skipped(self, tmp_path):
        from engine_py.badcase.shadow import auto_draft_shadow_cases

        pending = tmp_path / "pending.json"
        self._thread("thread_shadow_d")
        cid = self._candidate(SOURCE_CLAIM_MISMATCH, "thread_shadow_d")

        summary = asyncio.run(auto_draft_shadow_cases(pending_path=pending))
        assert summary["drafted"] == 0
        assert self._status_of(cid) == "candidate", "跳过不改状态(等人工 draft 流程)"
        assert all(c["vars"]["origin"] != f"badcase:{cid}" for c in load_pending(pending))

    def test_test_thread_prefix_never_drafted(self, tmp_path):
        """测试线程前缀闸(2026-10-28 人审实证):e2e/夜评线程是测试流量,
        行为面归 e2e 册与夜评自有门禁,shadow 自动起草只产噪声 —— 高置信
        信号(source=persona_fact_deleted 先验 suspected_defect)+ 完整用户行
        在场也必须 skip,候选保持 candidate 留周度人审面。"""
        from engine_py.badcase.shadow import auto_draft_shadow_cases

        pending = tmp_path / "pending.json"
        self._thread("merchant_thread_e2e_cart_1")
        self._message("merchant_thread_e2e_cart_1", "user", "极光三合一冲锋衣 曜石黑 M码 加入购物车", "2026-10-26T00:19:07")
        self._thread("nightly_sim_犹豫导购下单_1")
        self._message("nightly_sim_犹豫导购下单_1", "user", "帮我看看冲锋衣", "2026-10-26T00:20:00")
        cid_e2e = self._candidate(SOURCE_PERSONA_FACT_DELETED, "merchant_thread_e2e_cart_1")
        cid_nightly = self._candidate(SOURCE_PERSONA_FACT_DELETED, "nightly_sim_犹豫导购下单_1")

        summary = asyncio.run(auto_draft_shadow_cases(pending_path=pending))
        assert summary["drafted"] == 0
        for cid in (cid_e2e, cid_nightly):
            assert self._status_of(cid) == "candidate", "测试线程跳过不改状态(留周度人审面)"
            assert all(c["vars"]["origin"] != f"badcase:{cid}" for c in load_pending(pending))

    def test_promote_moves_case_into_suite_and_converts(self, tmp_path):
        """端到端:shadow 草稿 → promote(选套件+补断言)→ 硬闸套件落例、
        pending 摘除、候选留痕 converted —— D7 人审闸的最后一环。"""
        import argparse
        import json as _json

        from engine_py.badcase import cli as badcase_cli
        from engine_py.badcase.shadow import auto_draft_shadow_cases, load_pending

        pending = tmp_path / "pending.json"
        eval_dir = tmp_path / "eval"
        self._thread("thread_shadow_e")
        self._message("thread_shadow_e", "user", "退款到底什么时候到账", "2026-10-24T11:00:00")
        cid = self._candidate(SOURCE_CLAIM_MISMATCH, "thread_shadow_e")
        asyncio.run(auto_draft_shadow_cases(pending_path=pending))
        origins = [c["vars"]["origin"] for c in load_pending(pending)]
        assert f"badcase:{cid}" in origins

        args = argparse.Namespace(
            id=cid[:8],
            suite="testCases/ecommerce/shadow-promote-test.json",
            input=None,
            description=None,
            expected_tools="listUserOrders",
            intents="order_status",
            not_contains="退款已到账",
            note="回归断言补齐",
        )
        asyncio.run(badcase_cli.cmd_promote(args, pending_path=pending, eval_dir=eval_dir))

        suite = _json.loads((eval_dir / "testCases/ecommerce/shadow-promote-test.json").read_text(encoding="utf-8"))
        assert len(suite) == 1 and suite[0]["vars"]["origin"] == f"badcase:{cid}"
        assert suite[0]["vars"]["expectedTools"] == ["listUserOrders"]
        assert any(a.get("type") == "not-contains" for a in suite[0]["assert"])
        assert all(c["vars"]["origin"] != f"badcase:{cid}" for c in load_pending(pending)), "已转正从 shadow 摘除"
        assert self._status_of(cid) == "converted"

    def test_high_confidence_sources_are_defect_priors(self):
        # D7:自动起草只对 suspected_defect 先验族开闸;neutral(intent_conflict)
        # 与「单独立案聚合」的 circuit_breaker 永不自动起草
        from engine_py.badcase.pool import SOURCE_CIRCUIT_BREAKER, SOURCE_PERSONA_FACT_DELETED

        assert SOURCE_CLAIM_MISMATCH in AUTO_DRAFT_SOURCES
        assert SOURCE_PERSONA_FACT_DELETED in AUTO_DRAFT_SOURCES
        assert SOURCE_INTENT_CONFLICT not in AUTO_DRAFT_SOURCES
        assert SOURCE_CIRCUIT_BREAKER not in AUTO_DRAFT_SOURCES


# ── 测试辅助(放文件尾,避免吃收集器注意力)─────────────────────────


async def _set_ref(candidate_id: str, ref: str) -> None:
    async with get_session() as session:
        await session.execute(
            update(BadcaseCandidate).where(BadcaseCandidate.id == candidate_id).values(conversation_ref=ref)
        )
        await session.commit()


if __name__ == "__main__":
    pytest.main([__file__])
