"""技能契约黄金快照(2026-09-15 架构深化②)。

SkillResult.to_dict() 是 triage 快轨/step 执行引擎/SSE/TaskMemory 消费的
线上形状 —— 键形逐字节冻结:改动本文件的期望形状 = 有意打破线上契约,
必须同步两个适配器(triage _try_skill_fast_track、step_execution_engine)
与全部消费方。SkillContext 的字段名即技能层的类型化接口,测试直接构造。"""

from __future__ import annotations

from engine_py.skills.contract import SkillContext, SkillResult

# 完整结果(所有字段就位)的线上形状 —— 键名/嵌套/键序无关,键集精确匹配
GOLDEN_FULL = {
    "success": True,
    "output": "已成功为您办理订单 [AURORA-ORD-2026-9094] 的退款申请。",
    "nextAction": "finish",
    "skillId": "skill_order_refund",
    "cards": [{"type": "refund_confirmation"}],
    "taskPlan": {"goal": "g", "subtasks": [], "currentStepIndex": 0},
    "approvalPayload": {"actionType": "processRefund"},
    "extra": {
        "guideContext": {"candidateProductIds": ["p1"]},
        "cartContext": {"items": [], "addedThisTurn": []},
        "orderContext": {"targetOrderId": "AURORA-ORD-2026-9094"},
    },
}


def test_full_result_golden_shape():
    """全字段结果的线上形状:success/output/nextAction 恒在;其余非 None 才出现;
    领域上下文收入 extra(驼形)。"""
    r = SkillResult(
        output=GOLDEN_FULL["output"],
        skill_id="skill_order_refund",
        cards=GOLDEN_FULL["cards"],
        task_plan=GOLDEN_FULL["taskPlan"],
        approval_payload=GOLDEN_FULL["approvalPayload"],
        guide_context=GOLDEN_FULL["extra"]["guideContext"],
        cart_context=GOLDEN_FULL["extra"]["cartContext"],
        order_context=GOLDEN_FULL["extra"]["orderContext"],
    )
    assert r.to_dict() == GOLDEN_FULL


def test_minimal_result_key_presence_semantics():
    """缺席字段不产键(None 与缺席同义,.get 安全)—— 与历史返回 dict 兼容。"""
    r = SkillResult(output="ok")
    d = r.to_dict()
    assert d == {"success": True, "output": "ok", "nextAction": "finish"}
    assert d.get("cards") is None and "cards" not in d
    assert d.get("extra") is None and "extra" not in d


def test_failure_and_require_approval_shapes():
    fail = SkillResult(success=False, output="请补充订单号。", error="Missing required slot: orderId")
    assert fail.to_dict() == {
        "success": False,
        "output": "请补充订单号。",
        "nextAction": "finish",
        "error": "Missing required slot: orderId",
    }
    hitl = SkillResult(
        output="已提交人工复核。",
        next_action="require_approval",
        approval_payload={"actionType": "processRefund"},
    )
    assert hitl.to_dict()["nextAction"] == "require_approval"
    assert hitl.to_dict()["approvalPayload"] == {"actionType": "processRefund"}


def test_skill_context_fields_are_the_interface():
    """SkillContext 字段即接口:调用方装配一次,技能只读。"""
    ctx = SkillContext(
        thread_id="t1",
        user_id="u1",
        tenant_id="aurora",
        input="我要退款",
        slots={"orderId": "AURORA-ORD-2026-9094"},
        guide_context={"candidateProductIds": ["p1"]},
        is_approved=True,
    )
    assert (ctx.thread_id, ctx.user_id, ctx.tenant_id) == ("t1", "u1", "aurora")
    assert ctx.slots["orderId"] == "AURORA-ORD-2026-9094"
    assert ctx.is_approved is True and ctx.cart_context == {}
