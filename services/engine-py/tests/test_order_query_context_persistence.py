"""查单轮 targetOrderId 跨轮持久化回归(2026-09-15 用户实报「为什么没有关联」)。

事故链:用户上一轮刚查过订单 AURORA-ORD-2026-9094(助手已展示完整订单详情),
下一轮「我想申请退款」却被反问「请提供您的【订单编号】」—— 查单轮解析出的
订单没有随回合收口落进 TaskMemory.orderContext,退款严格抽取器
(extract_explicit_order_id 只认当前输入与已确认 orderContext,2026-09-05
双退款事故防线)读不到已确认单号,只能冷启动追问。

机制:ORDER_QUERY 带显式单号走 Step 1.5 单意图齐备终局 —— 全引擎唯一不带
with_order_context=True 的终局出口,``_set_target_order_id`` 的原地注入不进
LangGraph 通道;run_agent 回合收口「orderContext: result.order_context or
saved」两者皆空,中途 save 被空值覆盖。对照:embedding 判定 1/2/3 与 Step 3
终局均带 with_order_context=True,同场景不断链。

钉死契约:
- 查单(单意图齐备)终局必须透传 order_context(与其余终局同口径);
- 两轮回放:查单 → 「我想申请退款」必须关联已查订单,不得冷启动追问;
- 退款严格抽取器对「当前输入/已确认 orderContext」双通道的信任边界保持
  (防双退款事故回归:历史盲回填仍被禁止)。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.triage import intent_triage_engine as triage_mod
from engine_py.triage.semantic_cache import SemanticVectorCache
from engine_py.triage.slot_extractor import SlotExtractor

QUERY_ORDER = "AURORA-ORD-2026-9094"
TURN_QUERY = f"帮我查一下订单 {QUERY_ORDER} 到哪了"
TURN_REFUND = "我想申请退款"


class _FakeShortMemory:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_messages(self) -> list:
        return []


class _StoreTaskMemory:
    """TaskMemory 桩:全线程共享一份存储(真实实现为整条覆盖式 upsert)。"""

    store: dict = {}

    def __init__(self, thread_id: str) -> None:
        pass

    async def get_task_state(self) -> dict | None:
        return _StoreTaskMemory.store.get("state")

    async def save_task_state(self, payload: dict) -> None:
        _StoreTaskMemory.store["state"] = payload


async def _fake_exemplars(*args, **kwargs) -> list:
    return []


async def _noop_log(*args, **kwargs) -> None:
    return None


def _no_matching_skill(*args, **kwargs):
    return None


def _patch_common(monkeypatch: pytest.MonkeyPatch) -> None:
    """确定性环境:记忆全桩、锚向量定向、落库静默、技能快轨关闭(只测 triage 路由)。"""
    _StoreTaskMemory.store = {}
    monkeypatch.setattr(triage_mod, "ShortMemory", _FakeShortMemory)
    monkeypatch.setattr(triage_mod, "TaskMemory", _StoreTaskMemory)
    monkeypatch.setattr(triage_mod.IntentTriageEngine, "log_intent_to_db", _noop_log)
    monkeypatch.setattr(triage_mod, "search_relevant_exemplars", _fake_exemplars)
    monkeypatch.setattr(SemanticVectorCache, "_tenant_cache", {})

    async def _fake_embed(text: str) -> list[float]:
        return [0.0, 1.0, 0.0]

    async def _fake_anchors() -> dict:
        orth = [1.0, 0.0, 0.0]
        return {"order_status": [orth], "refund": [[0.0, 1.0, 0.0]], "out_of_scope": [orth]}

    monkeypatch.setattr(SemanticVectorCache, "get_embedding_with_cache", _fake_embed)
    monkeypatch.setattr(SemanticVectorCache, "get_anchor_vectors", _fake_anchors)

    from engine_py.skills import SkillRegistry

    monkeypatch.setattr(SkillRegistry, "find_matching_skill", staticmethod(_no_matching_skill))


def _run_turn(input_text: str) -> dict:
    """单回合 = run_agent 回合初快照(run_agent.py:292-300)→ triage.process →
    收口覆盖式落库(run_agent.py:520-528,orderContext 取「结果值 or 回合初快照」)。
    回合中 triage 的中途 save 对收口不可见 —— 生产断链机制正源于此。"""
    saved = _StoreTaskMemory.store.get("state") or {}
    saved_order = saved.get("orderContext")
    state = {
        "thread_id": "thread_order_assoc_repro",
        "user_id": "CUST-REPRO-ASSOC",
        "job_id": None,
        "input": input_text,
        "input_embedding": [0.0, 1.0, 0.0],
        "business_config": {"businessId": "aurora"},
        "rag_documents": [],
    }
    if saved_order is not None:
        state["order_context"] = saved_order
    result = asyncio.run(triage_mod.IntentTriageEngine.process(state))
    _StoreTaskMemory.store["state"] = {
        **(result.get("task_plan") or {}),
        "guideContext": result.get("guide_context") or saved.get("guideContext"),
        "cartContext": result.get("cart_context") or saved.get("cartContext"),
        "orderContext": result.get("order_context") or saved_order,
    }
    return result


def test_order_query_turn_persists_target_order_id(monkeypatch):
    """契约 1:查单单意图齐备终局必须透传 order_context(现状红:键缺失)。"""
    _patch_common(monkeypatch)
    result = _run_turn(TURN_QUERY)

    carried = (result.get("order_context") or {}).get("targetOrderId")
    assert carried == QUERY_ORDER, (
        f"查单轮终局必须携带已解析订单上下文,实际 order_context={result.get('order_context')!r}"
    )
    # 收口后 TaskMemory 必须持有该单号(下一轮退款关联的数据源)
    persisted = (_StoreTaskMemory.store.get("state") or {}).get("orderContext") or {}
    assert persisted.get("targetOrderId") == QUERY_ORDER, (
        f"回合收口必须把已查订单落进 TaskMemory.orderContext,实际 {persisted!r}"
    )


def test_refund_after_order_query_associates_queried_order(monkeypatch):
    """契约 2(用户实报症状):查单 → 「我想申请退款」必须关联已查订单。

    现状红:查单轮 order_context 未持久化,退款轮冷启动追问「请提供您的
    【订单编号】」。修复后:退款轮 slots/orders 携带已查订单号,追问消失。
    """
    _patch_common(monkeypatch)

    _run_turn(TURN_QUERY)
    turn2 = _run_turn(TURN_REFUND)

    output = str(turn2.get("output") or "")
    assert "请提供您的【订单编号】" not in output, (
        f"已查订单后申请退款不得冷启动追问,实际回复: {output!r}"
    )
    associated = next(
        (
            i.get("taskSpec", {}).get("slots", {}).get("orderId") or i.get("entities", {}).get("orderId")
            for i in turn2.get("intents", [])
        ),
        None,
    )
    assert associated == QUERY_ORDER, (
        f"退款意图必须关联上一轮已查订单 {QUERY_ORDER},实际 intents={turn2.get('intents')!r}"
    )
    # 关联后的订单上下文须继续向后传递(续聊不再次断链)
    carried = (turn2.get("order_context") or {}).get("targetOrderId")
    assert carried == QUERY_ORDER, f"退款轮必须继续透传订单上下文,实际 order_context={turn2.get('order_context')!r}"


def test_refund_strict_extractor_keeps_trusted_context_channel():
    """契约 3(双退款防线不回退):严格抽取器认「当前输入/已确认 orderContext」
    双通道 —— 持久化修复正落在补齐已确认通道的数据源,抽取器语义不变。"""
    spec = SlotExtractor.extract(
        TURN_REFUND, None, None, {"orderContext": {"targetOrderId": QUERY_ORDER}}
    )
    assert spec["slots"].get("orderId") == QUERY_ORDER
    assert spec["missingSlots"] == []

    # 历史盲回填依旧禁止(2026-09-05 双退款事故防线):无 orderContext 时,
    # 历史消息里的单号不得进入退款槽位
    spec_hist = SlotExtractor.extract(
        TURN_REFUND,
        None,
        None,
        {"historyMsgs": [{"role": "assistant", "content": f"订单 {QUERY_ORDER} 已支付,正在备货。"}]},
    )
    assert not spec_hist["slots"].get("orderId"), "历史盲回填必须保持禁止"
    assert "orderId" in spec_hist["missingSlots"]
