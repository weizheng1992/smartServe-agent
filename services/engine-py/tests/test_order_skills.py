"""订单技能层回归:退款 SOP 与极速改地址 SOP 的编排契约。

SPI 适配器以桩注入 —— 本套钉技能层分支(槽位校验/查单/HITL 阈值门禁/
履约状态拦截/执行与失败话术/卡片);DB 侧行为由
test_order_domain_views 与 test_double_refund_replay 另行钉死。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.skills.contract import SkillContext
from engine_py.skills.order_skills import OrderAddressModificationSkill, OrderRefundSkill

_ORDER = {
    "orderId": "AURORA-ORD-2026-9081",
    "status": "PAID",
    "totalAmount": 200.0,
    "items": [{"title": "Nike Air Zoom Pegasus 41", "quantity": 1, "price": 899.0}],
    "isAddressModifiable": True,
}


class _FakeSpi:
    def __init__(self, order: dict | None = _ORDER, action_result: dict | None = None):
        self.order = order
        self.action_result = action_result or {"success": True, "message": "ok"}
        self.calls: list[tuple[str, dict]] = []

    async def get_order_detail(self, params: dict) -> dict | None:
        self.calls.append(("get_order_detail", params))
        return self.order

    async def execute_order_action(self, params: dict) -> dict:
        self.calls.append(("execute_order_action", params))
        return self.action_result


def _wire(monkeypatch: pytest.MonkeyPatch, spi: _FakeSpi, threshold: float = 50.0, skill_cls=OrderRefundSkill) -> None:
    async def fake_client(self, tenant_id: str) -> _FakeSpi:
        return spi

    async def fake_threshold(self, tenant_id: str) -> float:
        return threshold

    monkeypatch.setattr(skill_cls, "get_spi_client", fake_client)
    monkeypatch.setattr(skill_cls, "get_effective_approval_threshold", fake_threshold)


def _ctx(slots: dict, extra: dict | None = None) -> SkillContext:
    extra = extra or {}
    return SkillContext(
        thread_id="t_order_skill",
        tenant_id="aurora",
        user_id="CUST-8802",
        input="我要退款",
        slots=slots,
        is_approved=bool(extra.get("isApproved")),
    )


# ---------------------------------------------------------------- 退款 SOP

def test_refund_missing_order_id_asks_for_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    spi = _FakeSpi()
    _wire(monkeypatch, spi)
    res = asyncio.run(OrderRefundSkill().execute(_ctx({})))
    assert res.success is False
    assert "订单号" in res.output
    assert spi.calls == [], "缺槽位时不得发起任何 SPI 调用"


def test_refund_order_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    spi = _FakeSpi(order=None)
    _wire(monkeypatch, spi)
    res = asyncio.run(OrderRefundSkill().execute(_ctx({"orderId": "NOPE-1"})))
    assert res.success is False
    assert "未查询到" in res.output


def test_refund_over_threshold_routes_to_hitl(monkeypatch: pytest.MonkeyPatch) -> None:
    """超阈值(¥200 > ¥50)且未经审批 → 挂起 HITL,不得执行退款。"""
    spi = _FakeSpi()
    _wire(monkeypatch, spi, threshold=50.0)
    res = asyncio.run(OrderRefundSkill().execute(_ctx({"orderId": _ORDER["orderId"]})))
    assert res.next_action == "require_approval"
    assert res.approval_payload["actionType"] == "processRefund"
    assert res.approval_payload["amount"] == 200.0
    assert [c[0] for c in spi.calls] == ["get_order_detail"], "门禁拦截时严禁 execute_order_action"
    assert "人工" in res.output


def test_refund_over_threshold_with_approval_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    """审批通过(isApproved)后放行执行。"""
    spi = _FakeSpi()
    _wire(monkeypatch, spi, threshold=50.0)
    res = asyncio.run(OrderRefundSkill().execute(_ctx({"orderId": _ORDER["orderId"]}, extra={"isApproved": True})))
    assert res.success is True
    assert res.cards[0]["type"] == "refund_confirmation"
    assert [c[0] for c in spi.calls] == ["get_order_detail", "execute_order_action"]
    # threadId 必须透传:process_refund 靠它解析归属用户(SPI 上下文修复回归)
    exec_params = spi.calls[1][1]
    assert exec_params["threadId"] == "t_order_skill"
    assert exec_params["userId"] == "CUST-8802"


def test_refund_below_threshold_auto_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    """小额(¥30 ≤ ¥50)免审直退。"""
    spi = _FakeSpi(order={**_ORDER, "totalAmount": 30.0})
    _wire(monkeypatch, spi, threshold=50.0)
    res = asyncio.run(OrderRefundSkill().execute(_ctx({"orderId": _ORDER["orderId"]})))
    assert res.success is True
    assert res.next_action == "finish"
    assert "原路退回" in res.output


def test_refund_action_failure_surfaces_message(monkeypatch: pytest.MonkeyPatch) -> None:
    spi = _FakeSpi(order={**_ORDER, "totalAmount": 30.0}, action_result={"success": False, "message": "库存锁定中"})
    _wire(monkeypatch, spi, threshold=50.0)
    res = asyncio.run(OrderRefundSkill().execute(_ctx({"orderId": _ORDER["orderId"]})))
    assert res.success is False
    assert "退款申请失败" in res.output and "库存锁定中" in res.output


def test_refund_fallback_regex_can_handle() -> None:
    skill = OrderRefundSkill()
    assert skill.can_handle(SkillContext(input="这个鞋子有瑕疵")) is True
    assert skill.can_handle(SkillContext(input="今天天气不错")) is False


# ---------------------------------------------------------------- 改地址 SOP

def test_address_missing_slots_asks(monkeypatch: pytest.MonkeyPatch) -> None:
    spi = _FakeSpi()
    _wire(monkeypatch, spi, skill_cls=OrderAddressModificationSkill)
    res = asyncio.run(OrderAddressModificationSkill().execute(_ctx({"orderId": "X"})))
    assert res.success is False
    assert "订单编号和新的收货地址" in res.output
    assert spi.calls == []


def test_address_order_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    spi = _FakeSpi(order=None)
    _wire(monkeypatch, spi, skill_cls=OrderAddressModificationSkill)
    res = asyncio.run(OrderAddressModificationSkill().execute(_ctx({"orderId": "NOPE-1", "newAddress": "北京市朝阳区"})))
    assert res.success is False
    assert "未查询到" in res.output


@pytest.mark.parametrize("status", ["SHIPPED", "DELIVERED", "CANCELLED"])
def test_address_fulfilled_order_is_refused(monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    """已发货/已送达/已取消:拦截改址,不发起执行。"""
    spi = _FakeSpi(order={**_ORDER, "status": status})
    _wire(monkeypatch, spi, skill_cls=OrderAddressModificationSkill)
    res = asyncio.run(OrderAddressModificationSkill().execute(_ctx({"orderId": _ORDER["orderId"], "newAddress": "上海市浦东新区"})))
    assert res.success is False
    assert "无法直接拦截修改" in res.output
    assert [c[0] for c in spi.calls] == ["get_order_detail"], "拦截时严禁 execute_order_action"


def test_address_not_modifiable_flag_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    spi = _FakeSpi(order={**_ORDER, "isAddressModifiable": False})
    _wire(monkeypatch, spi, skill_cls=OrderAddressModificationSkill)
    res = asyncio.run(OrderAddressModificationSkill().execute(_ctx({"orderId": _ORDER["orderId"], "newAddress": "上海市浦东新区"})))
    assert res.success is False
    assert [c[0] for c in spi.calls] == ["get_order_detail"]


def test_address_high_value_gates_to_hitl(monkeypatch: pytest.MonkeyPatch) -> None:
    """高价值(¥200>100)改址:技能路径必须过 HITL 门(2026-09-12 merchant 验收
    07 修复 —— 旧契约直改是审批红线旁路,新契约建审批工单并如实告知)。"""
    created: list[dict] = []

    class _FakeGate:
        @staticmethod
        async def create_pending_approval_ticket(params: dict) -> dict:
            created.append(params)
            return {"approvalId": "fake-approval-1", "nextPlan": {"subtasks": [{}]}}

    import engine_py.approvals.gatekeeper as gatekeeper_mod

    monkeypatch.setattr(gatekeeper_mod.ApprovalPolicyEngine, "create_pending_approval_ticket", _FakeGate.create_pending_approval_ticket)
    spi = _FakeSpi()
    _wire(monkeypatch, spi, skill_cls=OrderAddressModificationSkill)
    res = asyncio.run(
        OrderAddressModificationSkill().execute(_ctx({"orderId": _ORDER["orderId"], "newAddress": "上海市浦东新区张江路 5 号"}))
    )
    assert res.success is True
    assert "人工审核" in res.output
    assert [c[0] for c in spi.calls] == ["get_order_detail"], "高价值改址等待审批,严禁直接执行"
    assert created[0]["actionType"] == "changeShippingAddress"
    assert created[0]["actionPayload"]["args"]["newAddress"] == "上海市浦东新区张江路 5 号"


def test_address_low_value_order_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    """低价值(¥30≤100)改址:不受审批门拦截,直接执行(threadId 透传)。"""
    spi = _FakeSpi(order={**_ORDER, "totalAmount": 30.0})
    _wire(monkeypatch, spi, skill_cls=OrderAddressModificationSkill)
    res = asyncio.run(
        OrderAddressModificationSkill().execute(_ctx({"orderId": _ORDER["orderId"], "newAddress": "上海市浦东新区张江路 5 号"}))
    )
    assert res.success is True
    assert "上海市浦东新区张江路 5 号" in res.output
    assert res.cards[0]["type"] == "order_card"
    exec_params = spi.calls[1][1]
    assert exec_params["actionType"] == "MODIFY_ADDRESS"
    assert exec_params["newAddress"] == "上海市浦东新区张江路 5 号"
    assert exec_params["threadId"] == "t_order_skill", "threadId 透传(归属解析)"


def test_address_fallback_regex_can_handle() -> None:
    skill = OrderAddressModificationSkill()
    assert skill.can_handle(SkillContext(input="帮我改地址")) is True
    assert skill.can_handle(SkillContext(input="推荐几双跑鞋")) is False
