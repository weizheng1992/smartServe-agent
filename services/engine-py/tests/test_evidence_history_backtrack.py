"""回归:售后凭证会话历史回溯(ADR-0003 Q3)。

ADR-0002 只带本轮图;「两轮前传过图,这轮才说要退款」的场景凭证丢失。
契约:注入优先级 = 本轮 state.image_urls > 本会话 user 消息历史图
(newest-first 去重);总上限与视觉上限一致;本轮有图严禁重复回溯。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.tools_registry.order_domain import OrderDomainService


class _MsgSession:
    """返回预置 image_urls 行集,记录 SQL;不触达真实数据库。"""

    def __init__(self, row_sets: list[list]):
        self.row_sets = row_sets
        self.executed_sql: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        self.executed_sql.append(str(stmt))
        rows = self.row_sets.pop(0) if self.row_sets else []

        class _R:
            def __init__(self, rows):
                self._rows = rows

            def scalars(self):
                return self

            def all(self):
                return self._rows

        return _R(rows)


def test_history_images_newest_first_deduped(monkeypatch: pytest.MonkeyPatch) -> None:
    """三轮各一张(第一张与第三张重复):去重、newest-first、SQL 锁 user 消息。"""
    session = _MsgSession([[["/c.jpg", "/a.jpg"], ["/a.jpg"], ["/b.jpg"]]])
    monkeypatch.setattr("engine_py.tools_registry.order_domain.get_session", lambda: session)

    urls = asyncio.run(OrderDomainService.get_thread_evidence_images("t1"))

    assert urls == ["/c.jpg", "/a.jpg", "/b.jpg"], "最新消息的图在前,跨消息去重"
    sql = session.executed_sql[0]
    assert "messages" in sql and "role" in sql and "image_urls" in sql
    assert "thread_id" in sql


def test_history_empty_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _MsgSession([[[]], [[]]])
    monkeypatch.setattr("engine_py.tools_registry.order_domain.get_session", lambda: session)
    assert asyncio.run(OrderDomainService.get_thread_evidence_images("t1")) == []


def test_history_capped_at_vision_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from engine_py.vision.analyzer import MAX_IMAGES_PER_MESSAGE

    session = _MsgSession([[[f"/u{i}.jpg" for i in range(9)]]])
    monkeypatch.setattr("engine_py.tools_registry.order_domain.get_session", lambda: session)
    urls = asyncio.run(OrderDomainService.get_thread_evidence_images("t1"))
    assert len(urls) == MAX_IMAGES_PER_MESSAGE, "总上限与引擎视觉上限一致"


# ── 注入升级:state 驱动,本轮优先、历史兜底 ─────────────────────────────


def test_injection_prefers_current_turn_then_history(monkeypatch: pytest.MonkeyPatch) -> None:
    from engine_py.graph.nodes.step_execution_engine import maybe_inject_aftersale_evidence

    # 本轮有图:直接用,严禁查历史
    session = _MsgSession([[["/hist.jpg"]]])
    monkeypatch.setattr("engine_py.tools_registry.order_domain.get_session", lambda: session)
    args = asyncio.run(
        maybe_inject_aftersale_evidence(
            "applyAfterSale", {"orderId": "O1"}, {"image_urls": ["/now.jpg"], "thread_id": "t1"}
        )
    )
    assert args["evidenceImageUrls"] == ["/now.jpg"]
    assert session.executed_sql == [], "本轮有图严禁额外查历史"

    # 本轮无图:回溯会话历史
    session2 = _MsgSession([[["/hist1.jpg", "/hist2.jpg"]]])
    monkeypatch.setattr("engine_py.tools_registry.order_domain.get_session", lambda: session2)
    args2 = asyncio.run(
        maybe_inject_aftersale_evidence(
            "applyAfterSale", {"orderId": "O1"}, {"image_urls": None, "thread_id": "t1"}
        )
    )
    assert args2["evidenceImageUrls"] == ["/hist1.jpg", "/hist2.jpg"]


def test_injection_no_history_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    from engine_py.graph.nodes.step_execution_engine import maybe_inject_aftersale_evidence

    session = _MsgSession([[[]]])
    monkeypatch.setattr("engine_py.tools_registry.order_domain.get_session", lambda: session)
    args = {"orderId": "O1"}
    out = asyncio.run(
        maybe_inject_aftersale_evidence("applyAfterSale", args, {"image_urls": [], "thread_id": "t1"})
    )
    assert out is args, "无图可带时原样返回"
