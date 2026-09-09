"""破损图 OCR 单号消费与消歧闸门时序(2026-09-09)—— 事故回放钉死。

事故(2026-09-09 11:23,线程 merchant_thread_CUST-8801_aurora_1788076908973):
用户「坏了」+ 破损投诉图(图内明示单号 ORD-77777)。vision 实弹输出完全正确
(extractedOrderId=ORD-77777 / ocrText=破损投诉 ORD-77777 / severe 0.95),但:

1. ``vision_analysis["extractedOrderId"]`` 全链零消费 —— 不进 intents.entities、
   不进 order_context、不进槽位,OCR 单号算完即丢;intent_logs 佐证流程直落
   Step 2(method=embedding,refund 0.95,entities 空),之后 planner 深规划
   50s 由 finish 自由发挥"请告知哪笔订单"。
2. Step 1.6 商品归属消歧闸门只认 SlotExtractor 的 intentType(「坏了」→ chat),
   而图驱动的售后意图要到 Step 2 判定 3 才浮现(damage_assessment 令
   has_refund_keywords=True)—— 为"破损图+缺单号"造的消歧对该措辞永不触发。

钉死契约:
- 图内 OCR 单号必须像文本单号一样被消费(entities/order_context 携带);
- 意图浮现点(Step 2 判定 3)缺单号 + 带图也必须过消歧闸(出商品选择卡);
- OCR 单号不得覆盖已确认的 orderContext.targetOrderId;
- 判定 3 返回必须透传 order_context。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.triage import intent_triage_engine as triage_mod
from engine_py.triage.semantic_cache import SemanticVectorCache

# 实弹记录的真实 vision 输出(glm-4.6v 对事故原图,2026-09-09 一次性探针采集)
_VISION_WITH_OCR = {
    "visualSummary": "Image shows a damage complaint form with Chinese text indicating a shoe sole has come apart and is completely unwearable.",
    "detectedObjects": ["shoe", "shoe sole", "complaint form", "text"],
    "extractedOrderId": "ORD-77777",
    "extractedTrackingNumber": None,
    "ocrText": "破损投诉 ORD-77777\n鞋底开胶断裂 完全不能穿",
    "damageAssessment": {
        "damageLevel": "severe",
        "summary": "鞋底开胶断裂，完全不能穿",
        "confidence": 0.95,
        "suggestedAction": "auto_refund",
        "imageUrl": "/api/uploads/fe14c73e756b4f9ebebf024e4fe39e75.png",
    },
}
# 同图但 OCR 无单号(真实破损照片常态:有破损凭证、无面单)
_VISION_NO_OCR = {
    **_VISION_WITH_OCR,
    "extractedOrderId": None,
    "ocrText": "鞋底开胶断裂 完全不能穿",
}
# 带图但既无 OCR 单号也无破损定责:售后意图只能由 Step 3 分类器浮现
_VISION_PLAIN = {
    "visualSummary": "A photo of a clothing item sent by the customer.",
    "detectedObjects": ["clothing"],
    "extractedOrderId": None,
    "extractedTrackingNumber": None,
    "ocrText": "",
    "damageAssessment": None,
}

_INCIDENT_IMAGE = "/api/uploads/fe14c73e756b4f9ebebf024e4fe39e75.png"


class _FakeShortMemory:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_messages(self) -> list:
        return []


class _FakeTaskMemory:
    def __init__(self, thread_id: str, preset: dict | None = None) -> None:
        self._preset = preset

    async def get_task_state(self) -> dict | None:
        return self._preset

    async def save_task_state(self, payload: dict) -> None:
        return None


async def _fake_exemplars(*args, **kwargs) -> list:
    return []


async def _noop_log(*args, **kwargs) -> None:
    return None


def _incident_state() -> dict:
    return {
        "thread_id": "thread_vision_ocr_test",
        "user_id": "CUST-8801",
        "input": "坏了",
        "image_urls": [_INCIDENT_IMAGE],
        "input_embedding": [0.0, 1.0, 0.0],
        "business_config": {"businessId": "aurora"},
        "rag_documents": [],
    }


def _patch_common(
    monkeypatch: pytest.MonkeyPatch,
    vision_result: dict,
    task_preset: dict | None = None,
):
    """确定性环境:vision 固定回放、锚向量定向 refund、记忆/落库全桩。"""
    monkeypatch.setattr(triage_mod, "ShortMemory", _FakeShortMemory)
    monkeypatch.setattr(
        triage_mod, "TaskMemory", lambda tid: _FakeTaskMemory(tid, task_preset)
    )
    async def _fake_analyze(image_urls, prompt, **kwargs):
        return vision_result

    monkeypatch.setattr(triage_mod, "analyze_images", _fake_analyze)

    async def _fake_embed(text: str) -> list[float]:
        return [0.0, 1.0, 0.0]

    async def _fake_anchors() -> dict:
        orth = [1.0, 0.0, 0.0]
        return {"order_status": [orth], "refund": [[0.0, 1.0, 0.0]], "out_of_scope": [orth]}

    monkeypatch.setattr(triage_mod.IntentTriageEngine, "log_intent_to_db", _noop_log)
    monkeypatch.setattr(triage_mod, "search_relevant_exemplars", _fake_exemplars)
    monkeypatch.setattr(SemanticVectorCache, "_tenant_cache", {})
    monkeypatch.setattr(SemanticVectorCache, "get_embedding_with_cache", _fake_embed)
    monkeypatch.setattr(SemanticVectorCache, "get_anchor_vectors", _fake_anchors)


class TestVisionOcrOrderIdConsumption:
    """缺陷 1:OCR 单号算完即丢 —— intents/order_context 必须消费图内单号。"""

    def test_ocr_order_id_must_flow_into_intents_and_context(self, monkeypatch):
        _patch_common(monkeypatch, _VISION_WITH_OCR)
        result = asyncio.run(triage_mod.IntentTriageEngine.process(_incident_state()))

        entities_order = next(
            (i.get("entities", {}).get("orderId") for i in result.get("intents", [])), None
        )
        ctx_order = (result.get("order_context") or {}).get("targetOrderId")
        assert entities_order == "ORD-77777" or ctx_order == "ORD-77777", (
            f"图内 OCR 单号必须被消费:entities={entities_order!r} order_context={ctx_order!r}"
        )

    def test_existing_confirmed_order_not_clobbered_by_ocr(self, monkeypatch):
        preset = {"orderContext": {"targetOrderId": "AURORA-ORD-2026-9081"}}
        _patch_common(monkeypatch, _VISION_WITH_OCR, task_preset=preset)
        result = asyncio.run(triage_mod.IntentTriageEngine.process(_incident_state()))

        ctx = result.get("order_context") or {}
        assert ctx.get("targetOrderId") == "AURORA-ORD-2026-9081", (
            f"已确认订单上下文必须保留并透传(且不得被 OCR 单号覆盖):{ctx!r}"
        )


class TestDisambiguationGateAtIntentEmergence:
    """缺陷 2:模糊损坏词的售后意图在 Step 2 判定 3 才浮现,消歧闸必须在该
    意图浮现点同样生效 —— 否则为本场景造的功能对典型措辞永不触发。"""

    def test_vague_damage_word_with_image_triggers_select_card(self, monkeypatch):
        _patch_common(monkeypatch, _VISION_NO_OCR)
        calls: dict = {}

        async def _fake_disambig(vision, user_id, business_id, **kwargs):
            calls["args"] = (user_id, business_id)
            return {
                "status": "ambiguous",
                "candidates": [
                    {"orderId": "AURORA-ORD-2026-9081", "productName": "极光风暴冲锋衣", "quantity": 1},
                    {"orderId": "AURORA-ORD-2026-9082", "productName": "极光工装裤", "quantity": 1},
                ],
            }

        monkeypatch.setattr(triage_mod, "disambiguate_product", _fake_disambig)
        result = asyncio.run(triage_mod.IntentTriageEngine.process(_incident_state()))

        assert "破损的是哪件商品" in (result.get("output") or ""), (
            f"缺单号带图售后意图必须出商品选择卡,实际 output={ (result.get('output') or '')[:80]!r }"
        )
        cards = result.get("cards") or []
        assert any(c.get("type") == "quick_replies" for c in cards), f"选择卡缺失:{cards!r}"
        assert calls["args"] == ("CUST-8801", "aurora"), "消歧必须拿到真实用户与租户"

    def test_image_with_ocr_order_id_skips_disambiguation(self, monkeypatch):
        """图内已有单号 → 走单号消费(后续查无此单由技能诚实报错),不得进消歧。"""
        _patch_common(monkeypatch, _VISION_WITH_OCR)
        called: list = []

        async def _spy_disambig(*args, **kwargs):
            called.append(args)
            return {"status": "ambiguous", "candidates": [{"orderId": "X", "productName": "Y", "quantity": 1}]}

        monkeypatch.setattr(triage_mod, "disambiguate_product", _spy_disambig)
        result = asyncio.run(triage_mod.IntentTriageEngine.process(_incident_state()))
        assert not called, "图内已有单号时不得触发商品消歧(其前置就是'图内亦无单号')"
        entities_order = next(
            (i.get("entities", {}).get("orderId") for i in result.get("intents", [])), None
        )
        assert entities_order == "ORD-77777", (
            "'跳过消歧'必须是因为单号已被消费,而非链路没接:entities 应携带 ORD-77777"
        )

    def test_step3_classifier_intent_also_disambiguates(self, monkeypatch):
        """Step 3 浮现点:无关键词输入(「请看看这个」)+ 无定责图,售后意图由
        分类器判定才浮现 → 必须同样过消歧出选择卡,而非被注入前的陈旧
        missingSlots 澄清(「请提供订单编号」)劫走。"""
        from types import SimpleNamespace

        _patch_common(monkeypatch, _VISION_PLAIN)

        async def _fake_classify(*args, **kwargs):
            return SimpleNamespace(
                isOutOfScope=False,
                intents=[
                    SimpleNamespace(
                        intent="refund",
                        confidence=0.9,
                        type="primary",
                        entities={},
                        condition=None,
                        missingSlots=["orderId"],
                    )
                ],
                clarificationMessage="请提供订单编号",
            )

        async def _fake_disambig(vision, user_id, business_id, **kwargs):
            return {
                "status": "ambiguous",
                "candidates": [
                    {"orderId": "AURORA-ORD-2026-9081", "productName": "极光风暴冲锋衣", "quantity": 1}
                ],
            }

        monkeypatch.setattr(triage_mod, "classify", _fake_classify)
        monkeypatch.setattr(triage_mod, "disambiguate_product", _fake_disambig)

        state = _incident_state()
        state["input"] = "请看看这个"
        result = asyncio.run(triage_mod.IntentTriageEngine.process(state))

        assert "破损的是哪件商品" in (result.get("output") or ""), (
            f"Step 3 浮现的售后意图必须出商品选择卡,实际 output={ (result.get('output') or '')[:80]!r }"
        )
        assert "订单编号" not in (result.get("output") or "").split("请选择")[0], (
            "消歧已介入时不得再回放注入前的陈旧槽位澄清"
        )
        assert any(c.get("type") == "quick_replies" for c in (result.get("cards") or []))


if __name__ == "__main__":
    pytest.main([__file__])
