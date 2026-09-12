"""回归:售后凭证落库(ADR-0002 Q1/Q2,spec .scratch/aftersale-evidence-real-sales)。

症状根源:用户上传瑕疵照片后凭证「消失」——applyAfterSale 工具 schema 无
图片参数,after_sale_tickets 表无附件列,人工审批员处理工单时看不到图,
售后闭环断在最后一环。

契约:
- 工单表 evidence_urls JSONB 列;工具 schema 加 evidenceImageUrls 数组参数;
- 本轮上传图(≤3 张,与引擎 vision 上限一致)程序化落票,严禁指望 LLM 抄 URL;
- 不传凭证 = 旧行为零破坏(照常开单,列为空数组);
- executor 层对 applyAfterSale/processRefund 程序化补注:前者落票,后者经
  HITL 审批载荷让人工审批员看到凭证(⚠️ 事实修正:OrderRefundSkill 走
  SPI process_refund,不写工单表——技能路径无票可落,审批可见性由
  审批载荷自动携带,见 spec Comments)。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from engine_py.tools_registry import get_tool
from engine_py.tools_registry.mall_domain import MallDomainService
from engine_py.tools_registry.order_domain import OrderDomainService


class _CapturingSession:
    """记录每条语句的 SQL 与绑定参数,不触达真实数据库。"""

    def __init__(self):
        self.statements: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        self.statements.append({"sql": str(stmt), "params": stmt.compile().params})

    async def commit(self):
        pass


@pytest.fixture()
def stubbed_order(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ctx(thread_id):
        return {"userId": "CUST-8801", "businessId": "ecommerce"}

    async def fake_find(order_id, uid, bid):
        return {"orderId": order_id, "totalAmount": 1299.0, "userId": uid}

    monkeypatch.setattr(OrderDomainService, "get_thread_session_context", staticmethod(fake_ctx))
    monkeypatch.setattr(OrderDomainService, "find_order_by_id", staticmethod(fake_find))


def _run_apply(params: dict, monkeypatch: pytest.MonkeyPatch) -> tuple[dict, _CapturingSession]:
    session = _CapturingSession()
    monkeypatch.setattr(
        "engine_py.tools_registry.mall_domain.get_session", lambda: session
    )
    result = asyncio.run(MallDomainService.apply_after_sale({"threadId": "t1", **params}))
    return result, session


def test_evidence_urls_persisted_on_ticket(monkeypatch: pytest.MonkeyPatch, stubbed_order) -> None:
    result, session = _run_apply(
        {
            "orderId": "AURORA-ORD-2026-9083",
            "type": "return_and_refund",
            "reason": "quality_issue",
            "evidenceImageUrls": ["/api/uploads/a.jpg", "/api/uploads/b.jpg"],
        },
        monkeypatch,
    )

    assert result["success"] is True
    insert = next(s for s in session.statements if "after_sale_tickets" in s["sql"])
    assert "evidence_urls" in insert["sql"], "工单 INSERT 必须写凭证列"
    assert json.loads(insert["params"]["evidence"]) == ["/api/uploads/a.jpg", "/api/uploads/b.jpg"]
    assert result["evidenceCount"] == 2, "出参回填凭证数,供回复诚实播报"


def test_no_evidence_keeps_legacy_flow(monkeypatch: pytest.MonkeyPatch, stubbed_order) -> None:
    """不传凭证 = 旧行为零破坏:照常开单,列为空数组。"""
    result, session = _run_apply(
        {"orderId": "AURORA-ORD-2026-9083", "type": "refund_only", "reason": "no_reason_7d"},
        monkeypatch,
    )

    assert result["success"] is True
    insert = next(s for s in session.statements if "after_sale_tickets" in s["sql"])
    assert json.loads(insert["params"]["evidence"]) == []


def test_evidence_capped_at_three(monkeypatch: pytest.MonkeyPatch, stubbed_order) -> None:
    """引擎视觉分析上限 3 张,凭证同口径,超出截断。"""
    result, session = _run_apply(
        {
            "orderId": "AURORA-ORD-2026-9083",
            "type": "return_and_refund",
            "reason": "quality_issue",
            "evidenceImageUrls": [f"/api/uploads/{i}.jpg" for i in range(5)],
        },
        monkeypatch,
    )

    assert result["evidenceCount"] == 3
    insert = next(s for s in session.statements if "after_sale_tickets" in s["sql"])
    assert len(json.loads(insert["params"]["evidence"])) == 3


def test_tool_schema_has_evidence_param() -> None:
    tool = get_tool("applyAfterSale")
    assert tool is not None
    props = (tool.schema or {}).get("properties") or {}
    assert props.get("evidenceImageUrls", {}).get("type") == "array", "工具 schema 必须声明凭证数组参数"


# ── executor 层程序化注入(唯一可信的凭证来源,严禁指望 LLM 抄 URL)────────


def test_executor_injects_evidence_for_aftersale_tools() -> None:
    from engine_py.graph.nodes.step_execution_engine import maybe_inject_aftersale_evidence

    args = asyncio.run(
        maybe_inject_aftersale_evidence(
            "applyAfterSale",
            {"orderId": "O1", "type": "return_and_refund", "reason": "quality_issue"},
            {"image_urls": ["/api/uploads/a.jpg", "/api/uploads/b.jpg"], "thread_id": "t1"},
        )
    )
    assert args["evidenceImageUrls"] == ["/api/uploads/a.jpg", "/api/uploads/b.jpg"]

    # processRefund 不落工单表,但凭证随审批载荷让人工审批员可见
    refund_args = asyncio.run(
        maybe_inject_aftersale_evidence(
            "processRefund", {"orderId": "O1", "reason": "破损"},
            {"image_urls": ["/api/uploads/a.jpg"], "thread_id": "t1"},
        )
    )
    assert refund_args["evidenceImageUrls"] == ["/api/uploads/a.jpg"]


def test_executor_injection_noop_cases() -> None:
    from engine_py.graph.nodes.step_execution_engine import maybe_inject_aftersale_evidence

    # 非售后工具不注入
    state = {"image_urls": ["/a.jpg"], "thread_id": "t1"}
    assert asyncio.run(maybe_inject_aftersale_evidence("getOrderStatus", {"orderId": "O1"}, state)) == {"orderId": "O1"}
    # 已有凭证(LLM 或上游已给)不覆盖
    with_evidence = {"orderId": "O1", "evidenceImageUrls": ["/x.jpg"]}
    assert asyncio.run(maybe_inject_aftersale_evidence("applyAfterSale", with_evidence, state)) is with_evidence


def test_db_failure_errors_honestly(monkeypatch: pytest.MonkeyPatch, stubbed_order) -> None:
    """落库失败严禁吞异常后假 success:True——「已提交」必须是真话。

    2026-09-12 实弹抓出的存量缺陷:商户真单售后因 order_id 外键错位插不进
    本地表,异常被吞后照样播报「已提交」。外键已随 0010 迁移移除,此处钉死
    「失败必须诚实报错」的语义。"""
    from engine_py.tools_registry.mall_domain import MallDomainService as _svc

    class _BrokenSession(_CapturingSession):
        async def execute(self, stmt):
            raise RuntimeError("db down")

    monkeypatch.setattr("engine_py.tools_registry.mall_domain.get_session", lambda: _BrokenSession())
    result = asyncio.run(
        _svc.apply_after_sale({"threadId": "t1", "orderId": "X", "type": "refund_only", "reason": "no_reason_7d"})
    )
    assert "error" in result, "落库失败必须诚实报错"
    assert result.get("success") is not True, "严禁假成功"
