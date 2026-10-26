"""序数指代混同守卫(20 号票,judge 校准飞轮产出)。

「顺便把上一笔订单申请退款」曾把同句查物流的 ORD-98712 错挂为退款对象
(实弹:审批单 waiting 于 98712)—— 序数指代词在场时资金动作必须反问确认。
双守卫面:技能 fast-track(OrderRefundSkill.execute)与 routing 谓词。
"""

from __future__ import annotations

import asyncio

from engine_py.skills.contract import SkillContext
from engine_py.skills.order_skills import OrderRefundSkill


def _ctx(message: str, order_id: str = "ORD-98712") -> SkillContext:
    return SkillContext(
        thread_id="th_test_prev_ref",
        tenant_id="ecommerce",
        user_id="test@example.com",
        input=message,
        slots={"orderId": order_id, "activeIntent": "order_return"},
    )


def test_prev_referent_guard_blocks_refund_and_asks():
    """指代词在场:不执行退款、输出反问确认(严禁默认当前单号)。"""

    async def _run():
        return await OrderRefundSkill().execute(_ctx("我想看看我买的跑鞋 ORD-98712 到了没，顺便我想把上一笔订单申请退款了"))

    res = asyncio.run(_run())
    assert res.next_action != "require_approval", "指代未消解严禁挂 HITL 审批"
    assert "确认" in res.output or "哪一笔" in res.output or "订单号" in res.output


def test_prev_referent_variants_all_guarded():
    from engine_py.skills.routing import is_previous_order_referent

    for msg in ("把上一笔订单退了", "上一单退款", "前一单申请退款", "上次那单不想要了"):
        assert is_previous_order_referent(msg), msg
    for msg in ("ORD-98712 退款", "把我刚买的跑鞋退了", "推荐一款背包"):
        assert not is_previous_order_referent(msg), msg


def test_explicit_order_id_refund_unguarded():
    """显式单号无指代词:正常走 SOP 路径(不触发守卫分支)。

    用「订单不存在」输出证明流程穿透守卫进入订单查询(而非守卫反问)。
    """

    async def _run():
        return await OrderRefundSkill().execute(_ctx("订单 ORD-99999 帮我退款", order_id="ORD-99999"))

    res = asyncio.run(_run())
    assert "未查询到订单" in res.output or res.next_action in (None, "require_approval")
