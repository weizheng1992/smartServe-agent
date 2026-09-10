"""带图轮次不得被文本去重拦截器重放(2026-09-10 误退事故)—— 事故回放钉死。

事故(线程 merchant_thread_CUST-8801_aurora_1788076908973,09-10 18:32):
用户重发「坏了」+ 破损投诉图(图内明示外店单号 ORD-77777)。重复提问拦截器
只比较文本(input == user_msgs[-2] 的 content),当前轮的图证与 Step 0.5 刚
算出的 vision_order_id(同文件 28 行之前)被完全无视 → duplicate_bypass 逐字
重放 09-09 修复前(pre-OCR 消费)的旧消歧卡,引导用户挑本店真单
(AURORA-ORD-2026-9081)→ 对真单误起退款审批;图内外店单 ORD-77777 的
幽灵单拦截(§1.6)永远没有机会登场。intent_logs 佐证:
duplicate_bypass(rule) 后一轮即 refund 审批落库。

钉死契约:
- 历史同形对 + 当前轮带图重发 → 拦截器不得触发(输出非重放,OCR 单号照常消费);
- 纯文本真重复(无图)→ 拦截器照旧工作(去重能力不被过度修复抹掉)。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.triage import intent_triage_engine as triage_mod
from engine_py.triage.semantic_cache import SemanticVectorCache

# 实弹记录的真实 vision 输出(glm-4.6v 对事故原图;与 09-09 修复同一采集)
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
        "imageUrl": "/api/uploads/fbb8f3df27ee443685ffa55c351b2176.png",
    },
}

# 09-09 修复前时代产出的旧消歧卡(被重放的靶文本,节选自事故线程 assistant 行)
_STALE_DISAMBIG_CARD_CONTENT = (
    "您好，非常抱歉听到您商品损坏的消息，极光潮品官方旗舰店会为您妥善处理。🛠️\n\n"
    "为了尽快为您办理售后，麻烦您确认一下具体是哪笔订单出现了问题：\n\n"
    "1. **订单号：AURORA-ORD-2026-9081**（状态：已付款）\n"
    "2. **订单号：AURORA-ORD-2026-9082**（状态：已发货）\n\n"
    "请回复对应的订单号，收到后我会立即为您核实处理。"
)

_INCIDENT_IMAGE = "/api/uploads/fbb8f3df27ee443685ffa55c351b2176.png"

# OCR 失效子场景(2026-09-10 事故第二层实测):vision LLM 结构化解析失败降级
# 启发式 —— 破损定责仍在,但 extractedOrderId 为空。历史回填单号若被当已确认,
# 这种轮次会直接对旧卡里的本店真单自动退款。
_VISION_NO_OCR = {
    **_VISION_WITH_OCR,
    "extractedOrderId": None,
    "ocrText": "鞋底开胶断裂 完全不能穿",
}


class _IncidentHistoryShortMemory:
    """网关已写入当前用户行后的真实历史形状:上一轮带图「坏了」→ 旧消歧卡
    → 当前轮「坏了」(user_msgs[-2] 即上一轮用户行,与事故线程逐字段同形)。"""

    def __init__(self, thread_id: str) -> None:
        pass

    async def get_messages(self) -> list:
        return [
            {
                "role": "user",
                "content": "坏了",
                "cards": [],
                "image_urls": ["/api/uploads/fe14c73e756b4f9ebebf024e4fe39e75.png"],
            },
            {"role": "assistant", "content": _STALE_DISAMBIG_CARD_CONTENT, "cards": []},
            {"role": "user", "content": "坏了", "cards": [], "image_urls": [_INCIDENT_IMAGE]},
        ]


class _TextDuplicateShortMemory:
    """纯文本真重复对照:无图参与,拦截器必须照旧重放(防过度修复)。"""

    def __init__(self, thread_id: str) -> None:
        pass

    async def get_messages(self) -> list:
        return [
            {"role": "user", "content": "这个人真好笑", "cards": []},
            {"role": "assistant", "content": "哈哈，确实很有意思呢，还有什么能帮到您的吗？", "cards": []},
            {"role": "user", "content": "这个人真好笑", "cards": []},
        ]


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


def _incident_state(with_image: bool = True) -> dict:
    state = {
        "thread_id": "thread_vdup_image_test",
        "user_id": "CUST-8801",
        "input": "坏了",
        "image_urls": [_INCIDENT_IMAGE] if with_image else None,
        "input_embedding": [0.0, 1.0, 0.0],
        "business_config": {"businessId": "aurora"},
        "rag_documents": [],
    }
    return state


def _patch_common(
    monkeypatch: pytest.MonkeyPatch,
    history_cls,
    vision_result: dict | None = None,
):
    """确定性环境:历史/记忆/落库全桩,vision 固定回放,锚向量定向 refund。"""
    monkeypatch.setattr(triage_mod, "ShortMemory", history_cls)
    monkeypatch.setattr(triage_mod, "TaskMemory", lambda tid: _FakeTaskMemory(tid, None))

    if vision_result is not None:
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


class TestDuplicateBypassSkipsImageTurns:
    """根因钉子:带图轮次的文本去重 = 吞新证据 → 重放过期答复误导用户。"""

    def test_image_resent_not_replayed_and_ocr_consumed(self, monkeypatch):
        _patch_common(monkeypatch, _IncidentHistoryShortMemory, _VISION_WITH_OCR)
        result = asyncio.run(triage_mod.IntentTriageEngine.process(_incident_state()))

        output = result.get("output") or ""
        assert "相同的咨询" not in output, (
            f"带图重发不得被文本去重重放过期消歧卡(事故:重放卡引导挑本店真单误退),"
            f"实际 output={output[:120]!r}"
        )
        entities_order = next(
            (i.get("entities", {}).get("orderId") for i in result.get("intents", [])), None
        )
        ctx_order = (result.get("order_context") or {}).get("targetOrderId")
        assert entities_order == "ORD-77777" or ctx_order == "ORD-77777", (
            f"豁免去重后图内 OCR 单号必须照常消费:entities={entities_order!r} "
            f"order_context={ctx_order!r}"
        )

    def test_ocr_failed_with_history_backfill_must_disambiguate_not_refund(self, monkeypatch):
        """OCR 失效 × 历史回填:vision 没抽出单号时,历史旧卡里的本店单号不得
        冒充已确认上下文触发自动退款 —— 必须落回商品归属消歧(出选择卡问用户),
        这是「缺单号带图售后」的设计安全位。"""
        _patch_common(monkeypatch, _IncidentHistoryShortMemory, _VISION_NO_OCR)

        async def _fake_disambig(vision, user_id, business_id, **kwargs):
            return {
                "status": "ambiguous",
                "candidates": [
                    {"orderId": "AURORA-ORD-2026-9081", "productName": "极光风暴冲锋衣", "quantity": 1},
                    {"orderId": "AURORA-ORD-2026-9082", "productName": "极光工装裤", "quantity": 1},
                ],
            }

        monkeypatch.setattr(triage_mod, "disambiguate_product", _fake_disambig)
        result = asyncio.run(triage_mod.IntentTriageEngine.process(_incident_state()))

        output = result.get("output") or ""
        intents = result.get("intents") or []
        entities_order = next((i.get("entities", {}).get("orderId") for i in intents), None)
        assert "破损的是哪件商品" in output, (
            f"OCR 失效 + 缺可信单号必须出商品选择卡问用户,实际 output={output[:120]!r}"
        )
        assert entities_order != "AURORA-ORD-2026-9081", (
            f"历史回填单号不得成为退款实体:intents={intents!r}"
        )
        assert any(c.get("type") == "quick_replies" for c in (result.get("cards") or [])), (
            f"选择卡缺失:{result.get('cards')!r}"
        )

    def test_plain_text_true_duplicate_still_replays(self, monkeypatch):
        """对照组:无图真重复,拦截器照旧工作 —— 修复不得抹掉去重能力。"""
        _patch_common(monkeypatch, _TextDuplicateShortMemory)
        state = _incident_state(with_image=False)
        state["input"] = "这个人真好笑"
        result = asyncio.run(triage_mod.IntentTriageEngine.process(state))

        output = result.get("output") or ""
        assert "相同的咨询" in output, (
            f"纯文本真重复必须照旧重放上一轮答复,实际 output={output[:120]!r}"
        )
        assert "确实很有意思" in output, "重放内容应是上一轮 assistant 答复本体"


if __name__ == "__main__":
    pytest.main([__file__])
