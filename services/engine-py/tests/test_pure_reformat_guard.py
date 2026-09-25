"""纯排版/指代续聊收编回归(词表缺口确定性预检,2026-09-25)。

实弹:「给一个表格显示」在分类器 10 档词表无归属,structured_llm 就近抓
历史窗口单号判 order_status + 绑 AURORA-ORD-2026-6307,确定性订单快路照办
答出无关订单表(intent_logs f5bd4c40)。本套钉死:

1. 检出器:纯函数判定面 —— 排版形×交付动词命中;订单/购物车/地址话题
   名词、操作动词、显式单号在场一律不命中(严禁误伤真实业务请求);
2. 接线:Step 3 分类器即便误判 order_status + 带单号,纯排版输入收编
   general_query、实体剥除,structured_llm 原判经 reformat_guard 进
   candidates 留痕。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.triage import intent_triage_engine as triage_mod
from engine_py.triage.intent_triage_engine import detect_pure_reformat
from engine_py.triage.semantic_cache import SemanticVectorCache
from engine_py.triage.structured_classifier import IntentNode, StructuredTriageOutput

# ── 检出器单测(纯函数,无 IO)──────────────────────────────────────────


class TestDetectPureReformat:
    def test_reformat_phrases_hit(self) -> None:
        for text in (
            "给一个表格显示",
            "用表格显示一下",
            "把上面的内容做成表格",
            "刚才那个列个清单",
            "换个格式显示",
            "重新整理一下给我看",
            "帮我用列表展示",
        ):
            assert detect_pure_reformat(text), text

    def test_business_requests_do_not_hit(self) -> None:
        for text in (
            "我想申请退款",                       # 操作动词
            "订单什么时候发货",                    # 订单话题名词
            "帮我查一下订单 AURORA-ORD-2026-6307 的物流轨迹",  # 显式单号
            "把订单 AURORA-ORD-2026-6307 做成表格",           # 单号+话题名词:订单域表格诉求
            "订单列表给我看看",                    # 订单话题名词
            "购物车清单发我",                      # 购物车话题名词
            "我的收货地址列表",                    # 地址话题名词
            "店铺信息",
            "有什么热销商品",
            "按利润排一下前5款商品",
            "几个帐篷的特点和价格对比",
            None,
        ):
            assert not detect_pure_reformat(text), text


# ── Step 3 接线测试(fake classify,正交锚点令 Step 2 全跳过)─────────────


async def _fake_exemplars(*args, **kwargs) -> list:
    return []


class _FakeShortMemory:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_messages(self) -> list:
        # 正确时序的历史窗口(修 ShortMemory 排序后的形态):含帐篷问答,
        # 上文另有真实单号在场 —— 分类器即便想就近抓单也抓得到,守门靠收编
        return [
            {"role": "user", "content": "帮我查一下订单 AURORA-ORD-2026-6307 的物流轨迹", "cards": None},
            {"role": "assistant", "content": "该订单配送中。", "cards": None},
            {"role": "user", "content": "几个帐篷的特点和价格对比", "cards": None},
            {"role": "assistant", "content": "店内帐篷信息如下…", "cards": None},
            {"role": "user", "content": "给一个表格显示", "cards": None},
        ]


class _FakeTaskMemory:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_task_state(self) -> dict | None:
        return None

    async def save_task_state(self, state: dict) -> None:
        return None


def _state() -> dict:
    return {
        "thread_id": "thread_reformat_guard_test",
        "user_id": "u_reformat_guard",
        "input": "给一个表格显示",
        "image_urls": [],
        "input_embedding": [1.0, 0.0, 0.0],
        "business_config": {"businessId": "ecommerce"},
    }


class TestReformatGuardWiring:
    def _run_process(self, monkeypatch: pytest.MonkeyPatch, classify_result, log_calls: list) -> dict:
        """实弹复刻:分类器误判 order_status 并绑历史窗口单号 —— 预检必须
        在单号绑定/订单快路之前收编。"""

        async def _fake_classify(input_text, **kwargs):
            return classify_result

        async def _fake_embed(text: str) -> list[float]:
            # 文本→稳定单位向量:同文同向量、异文(近)正交 —— 常量向量会令
            # 语义去重(≥0.98)把任意续聊误判为重复提问,Step 3 根本到不了
            import hashlib

            digest = int(hashlib.sha1(text.encode("utf-8")).hexdigest(), 16)
            vec = [0.0] * 97
            vec[digest % 97] = 1.0
            return vec

        async def _fake_anchors() -> dict:
            orth = [0.0, 1.0, 0.0]
            return {"order_status": [orth], "refund": [orth], "out_of_scope": [orth]}

        async def _fake_log(*args, **kwargs):
            log_calls.append({"args": args, "kwargs": kwargs})

        monkeypatch.setattr(triage_mod, "ShortMemory", _FakeShortMemory)
        monkeypatch.setattr(triage_mod, "TaskMemory", _FakeTaskMemory)
        monkeypatch.setattr(triage_mod, "classify", _fake_classify)
        monkeypatch.setattr(triage_mod, "search_relevant_exemplars", _fake_exemplars)
        monkeypatch.setattr(triage_mod.IntentTriageEngine, "log_intent_to_db", _fake_log)
        monkeypatch.setattr(SemanticVectorCache, "_tenant_cache", {})
        monkeypatch.setattr(SemanticVectorCache, "get_embedding_with_cache", _fake_embed)
        monkeypatch.setattr(SemanticVectorCache, "get_anchor_vectors", _fake_anchors)
        return asyncio.run(triage_mod.IntentTriageEngine.process(_state()))

    def test_misrouted_order_status_is_coerced(self, monkeypatch) -> None:
        """实弹形状:分类器判 order_status + 带历史窗口单号 → 收编 general_query,
        实体剥除,域角色不再落入 order_service(订单快路无从触发)。"""
        log_calls: list = []
        result = self._run_process(
            monkeypatch,
            StructuredTriageOutput(
                intents=[
                    IntentNode(
                        intent="order_status",
                        confidence=0.9,
                        type="primary",
                        entities={"orderId": "AURORA-ORD-2026-6307"},
                    )
                ]
            ),
            log_calls,
        )
        winner = result["intents"][0]
        assert winner["intent"] == "general_query"
        assert not winner["entities"].get("orderId"), "收编后不得残留单号实体"
        assert result["active_domain_role"] != "order_service"
        # 留痕:structured_llm 原判与收编动作都必须可溯
        layers = [(c["layer"], c["intent"]) for c in log_calls[0]["kwargs"]["candidates"]]
        assert ("structured_llm", "order_status") in layers
        assert ("reformat_guard", "order_status") in layers

    def test_general_query_classification_passes_through(self, monkeypatch) -> None:
        """分类器本就判 general_query:预检不得改写(直通形态保持)。"""
        log_calls: list = []
        result = self._run_process(
            monkeypatch,
            StructuredTriageOutput(intents=[IntentNode(intent="general_query", confidence=0.9, type="primary")]),
            log_calls,
        )
        layers = [c["layer"] for c in log_calls[0]["kwargs"]["candidates"]]
        assert "reformat_guard" not in layers
        assert result["intents"][0]["intent"] == "general_query"


if __name__ == "__main__":
    pytest.main([__file__])
