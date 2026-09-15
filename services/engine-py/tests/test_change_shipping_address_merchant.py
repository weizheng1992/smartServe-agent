"""merchant 验收 07 红灯回路(2026-09-12 真实操作验收发现)。

实弹症状:「把订单AURORA-ORD-2026-9091的收货地址改成上海…」回复「处理失败」,
merchant_orders.shipping_address 未变。根因两层:
①change_shipping_address 的 UPDATE 写的是不存在的 `address` 列(orders 表真实
  列名 shipping_address)—— 任何来源的订单都炸,被 catch 吞成通用失败;
  merchant 真单根本不在 engine orders 表里,这次写穿本身就不该发生;
②技能快轨(OrderAddressModificationSkill)对高价值订单直接 execute_order_action
  (is_approved=True),完全绕过步进引擎的 HITL 审批门 —— ¥100 红线形同虚设。
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from engine_py.skills.contract import SkillContext
from engine_py.skills.order_skills import OrderAddressModificationSkill
from engine_py.skills.spi_client import LocalDbSpiAdapter
from engine_py.tools_registry.order_domain import OrderDomainService

TID = "accept_addr_fix_thread"
UID = "CUST-8801"
NEW_ADDR = "上海市浦东新区世纪大道100号"


def test_refund_keywords_include_bare_colloquial_forms():
    """06 病灶:「退了订单…」被判定 2 锚点/关键词分支路由成查单 —— 裸口语
    退款形必须进退款词表(资金动作一票优先的词面基础)。"""
    from engine_py.triage.intent_triage_engine import REFUND_KEYWORDS_RE

    for text_val in ("退了订单AURORA-ORD-2026-9094", "把这单退掉", "退还押金", "我想退款"):
        assert REFUND_KEYWORDS_RE.search(text_val), text_val


def test_engine_order_address_persisted(pg_factory):
    """engine 单:改址必须真实落库到 shipping_address 列(现状红:UPDATE 写
    不存在的 address 列,任何单都炸)。"""

    async def scenario():
        engine = pg_factory.kw["bind"]
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO threads (id, user_id, business_id, status, created_at, updated_at) "
                    "VALUES (:t, :u, 'ecommerce', 'active', now(), now()) "
                    "ON CONFLICT (id) DO UPDATE SET user_id = EXCLUDED.user_id"
                ).bindparams(t=TID, u=UID)
            )
            await conn.execute(
                text(
                    "INSERT INTO orders (order_id, status, carrier, tracking_number, estimated_delivery, "
                    "user_id, business_id, total_amount) VALUES ('TEST-ORD-1', 'paid', 'SF', 'SF001', "
                    "now() + interval '3 days', :u, 'ecommerce', 617)"
                ).bindparams(u=UID)
            )
        return await OrderDomainService.change_shipping_address(
            "TEST-ORD-1", NEW_ADDR, thread_id=TID, is_approved=True
        )

    result = asyncio.run(scenario())
    assert not result.get("error"), f"改址不应失败: {result}"

    async def check():
        engine = pg_factory.kw["bind"]
        async with engine.connect() as conn:
            return (
                await conn.execute(
                    text("SELECT shipping_address FROM orders WHERE order_id='TEST-ORD-1'")
                )
            ).scalar()

    assert asyncio.run(check()) == NEW_ADDR


def test_merchant_order_skips_engine_write_updates_mirror(pg_factory, monkeypatch):
    """merchant 真单:engine orders 表里根本没有该行,UPDATE 引擎表毫无意义且
    必炸 —— 必须跳过引擎写、直接商户镜像写穿。"""

    merchant_order = {
        "orderId": "AURORA-ORD-2026-9091",
        "status": "PAID",
        "totalAmount": 617.0,
        "userId": UID,
        "source": "merchant",
        "isAddressModifiable": True,
        "shippingAddress": {"recipientName": "张伟", "phone": "13800138000", "fullAddress": "北京市朝阳区旧地址"},
    }
    mirror_calls: list[dict] = []

    async def _fake_find(order_id, user_id=None, business_id=None):
        return dict(merchant_order)

    async def _fake_update(order_id, *, status=None, shipping_address=None):
        mirror_calls.append({"orderId": order_id, "shipping_address": shipping_address})

    import engine_py.tools_registry.order_domain as order_domain_mod
    monkeypatch.setattr(OrderDomainService, "find_order_by_id", staticmethod(_fake_find))
    monkeypatch.setattr(order_domain_mod, "_update_merchant_order", _fake_update)

    async def scenario():
        return await OrderDomainService.change_shipping_address(
            "AURORA-ORD-2026-9091", NEW_ADDR, thread_id=TID, is_approved=True
        )

    result = asyncio.run(scenario())
    assert not result.get("error"), f"merchant 真单改址不应失败: {result}"
    assert mirror_calls and mirror_calls[0]["shipping_address"]["fullAddress"] == NEW_ADDR


class _FakeSpi:
    """SPI 桩:get_order_detail 返回 merchant 形订单,execute_order_action 记录调用。"""

    def __init__(self, order: dict, calls: list):
        self._order = order
        self._calls = calls

    async def get_order_detail(self, params: dict) -> dict | None:
        return dict(self._order)

    async def execute_order_action(self, req: dict) -> dict:
        self._calls.append(req)
        return {"success": True, "actionType": req.get("actionType"), "message": "ok"}


def _skill_ctx(order: dict) -> SkillContext:
    return SkillContext(
        thread_id=TID,
        tenant_id="ecommerce",
        user_id=UID,
        input="把订单的收货地址改成上海市浦东新区世纪大道100号",
        slots={"orderId": order["orderId"], "newAddress": NEW_ADDR, "activeIntent": "order_modify_address"},
    )


def test_skill_high_value_creates_hitl_ticket(pg_factory, monkeypatch):
    """高价值(¥617>100)改址:技能路径必须过 HITL —— 建审批工单并如实告知
    等待审核,严禁直接 execute_order_action(现状红:完全绕过审批门)。"""

    async def scenario():
        engine = pg_factory.kw["bind"]
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO threads (id, user_id, business_id, status, created_at, updated_at) "
                    "VALUES (:t, :u, 'ecommerce', 'active', now(), now()) "
                    "ON CONFLICT (id) DO UPDATE SET user_id = EXCLUDED.user_id"
                ).bindparams(t=TID, u=UID)
            )
        calls: list = []
        order = {
            "orderId": "AURORA-ORD-2026-9091",
            "status": "PAID",
            "totalAmount": 617.0,
            "isAddressModifiable": True,
            "items": [],
        }
        async def _fake_spi(self, tenant):
            return _FakeSpi(order, calls)

        monkeypatch.setattr(OrderAddressModificationSkill, "get_spi_client", _fake_spi)
        result = (await OrderAddressModificationSkill().execute(_skill_ctx(order))).to_dict()
        async with engine.connect() as conn:
            tickets = (
                await conn.execute(
                    text(
                        "SELECT action_type, status FROM pending_approvals "
                        "WHERE thread_id=:t AND action_type='changeShippingAddress'"
                    ),
                    {"t": TID},
                )
            ).mappings().all()
        return result, calls, tickets

    result, calls, tickets = asyncio.run(scenario())
    assert not calls, "高价值改址不得直接执行"
    assert tickets, "必须生成 changeShippingAddress 审批工单"
    assert tickets[0]["status"] == "waiting"
    assert "审核" in (result.get("output") or ""), "必须如实告知等待人工审核"
    # 恢复计划必须随结果带回(run_agent 回合收口以 result.task_plan 覆盖
    # TaskMemory;不随行则挂起计划被 bypass 空计划冲掉,审批通过后 resume
    # 无计划可恢复 —— 2026-09-12 实弹:approve 成功而地址未变)
    saved_plan = result.get("taskPlan") or {}
    subtasks = saved_plan.get("subtasks") or []
    step = subtasks[0] if subtasks else {}
    assert "changeShippingAddress" in (step.get("description") or ""), "恢复计划必须含改址步骤"
    assert (step.get("result") or {}).get("waitingForApproval") is True
    assert (step.get("result") or {}).get("approvalId")


def test_skill_low_value_executes_directly(pg_factory, monkeypatch):
    """低价值(¥99≤100)改址:不受审批门拦截,直接执行。"""

    async def scenario():
        calls: list = []
        order = {
            "orderId": "TEST-ORD-2",
            "status": "PAID",
            "totalAmount": 99.0,
            "isAddressModifiable": True,
            "items": [],
        }
        async def _fake_spi(self, tenant):
            return _FakeSpi(order, calls)

        monkeypatch.setattr(OrderAddressModificationSkill, "get_spi_client", _fake_spi)
        result = (await OrderAddressModificationSkill().execute(_skill_ctx(order))).to_dict()
        return result, calls

    result, calls = asyncio.run(scenario())
    assert len(calls) == 1, "低价值改址应直接执行"
    assert result.get("success") is True


def test_skill_adapter_class_present():
    """防呆:SPI 适配器类名漂移防护。"""
    assert LocalDbSpiAdapter is not None


if __name__ == "__main__":
    pytest.main([__file__])
