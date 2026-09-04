"""回归:语义缓存不得写入/命中"动作形"输入(2026-09-04 幻觉加购投毒链加固)。

背景投毒链(生产事故):
  CartManageSkill.execute 抛 AttributeError → triage Step 1.5 异常被吞 → 降级
  general_query → finish LLM 无工具背书,幻觉"已成功加购" → 回填语义缓存
  → 相似请求以 ≥0.96 相似度永久命中缓存,绕过真实技能执行,商城购物车始终为空。

两道闸门:
  ① 写闸(finish 节点): is_action_query(input) 为真 → 不回填;
  ② 读闸(triage Step 2): is_action_query(input) 为真 → 不查缓存。
闸门只拦动作形输入,纯寒暄/FAQ 的缓存本职行为必须有镜像用例钉死,防误伤。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from engine_py.graph.nodes import finish as finish_mod
from engine_py.skills import is_action_query
from engine_py.triage import intent_triage_engine as triage_mod
from engine_py.triage.semantic_cache import SemanticVectorCache

# 事故当日 finish LLM 的幻觉原文,作为投毒载荷最具回归代表性
_POISON_REPLY = "好的，已为您成功将第1件商品【Nike Air Zoom Pegasus 41 极速轻量透气跑鞋】加入购物车！🛒"
_FAQ_REPLY = "我们支持支付宝、微信支付与银行卡支付。"
_TEST_VEC = [1.0, 0.0, 0.0]


# ---------- 嗅探函数 ----------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("把第1件加入购物车", True),  # 事故原句(CartManageSkill)
        ("查看购物车多少钱", True),  # 购物车查看分支
        ("推荐当季热销机能外套", True),  # 导购(ShoppingGuideSkill)
        ("帮我申请退款", True),  # 售后(OrderRefundSkill 兜底正则)
        ("修改收货地址为北京市朝阳区", True),  # 改地址(OrderAddressModificationSkill 兜底正则)
        ("你们支持哪些支付方式", False),  # 纯 FAQ
        ("今天天气怎么样", False),  # 超纲闲聊
        ("你好", False),  # 寒暄
    ],
)
def test_is_action_query(text: str, expected: bool) -> None:
    assert is_action_query(text) is expected


# ---------- 写闸:finish 节点回填 ----------


class _FakeChatModel:
    def __init__(self, content: str) -> None:
        self._content = content

    async def ainvoke(self, prompt: str) -> SimpleNamespace:
        return SimpleNamespace(content=self._content)


class _FakeShortMemory:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_messages(self) -> list[dict]:
        return []


def _run_finish(monkeypatch: pytest.MonkeyPatch, *, user_input: str, llm_reply: str) -> dict:
    async def _fake_resolve_tenant(state: dict) -> str:
        return "ecommerce"

    monkeypatch.setattr(finish_mod, "_resolve_tenant_id", _fake_resolve_tenant)
    monkeypatch.setattr(finish_mod, "ShortMemory", _FakeShortMemory)
    monkeypatch.setattr(finish_mod, "get_chat_model", lambda: _FakeChatModel(llm_reply))
    monkeypatch.setattr(SemanticVectorCache, "_tenant_cache", {})

    # intents 模拟 structured_llm_fallback 降级态(事故链第 3 环)
    state = {
        "thread_id": "thread_cache_poison_write",
        "input": user_input,
        "input_embedding": list(_TEST_VEC),
        "intents": [{"intent": "general_query", "confidence": 0.5}],
        "short_memory": [],
        "task_plan": {"subtasks": []},
        "global_transitions_count": 0,
        "tool_errors_count": 0,
    }
    return asyncio.run(finish_mod.finish_node(state))


def _cached_queries() -> list[str]:
    return [e["query"] for e in SemanticVectorCache._tenant_cache.get("ecommerce", [])]


def test_finish_write_gate_blocks_action_input(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _run_finish(monkeypatch, user_input="把第1件加入购物车", llm_reply=_POISON_REPLY)
    # LLM 幻觉文本原样透出(闸门管缓存写入,不改终稿行为)
    assert "加入购物车" in result["output"]
    assert "把第1件加入购物车" not in _cached_queries(), "动作形输入的幻觉回复不得回填语义缓存"


def test_finish_write_gate_keeps_faq_caching(monkeypatch: pytest.MonkeyPatch) -> None:
    _run_finish(monkeypatch, user_input="你们支持哪些支付方式", llm_reply=_FAQ_REPLY)
    assert "你们支持哪些支付方式" in _cached_queries(), "纯 FAQ 回复仍应正常回填(闸门不得误伤缓存本职)"


# ---------- 读闸:triage Step 2 缓存命中 ----------


class _FakeShortMemoryTriage:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_messages(self) -> list[dict]:
        return []


class _FakeTaskMemory:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_task_state(self) -> dict:
        return {}

    async def save_task_state(self, state: dict) -> None:
        return None


class _ExplodingSlotExtractor:
    """模拟技能/槽位层故障(事故链第 1 环:fast-track 异常被吞后跌落 Step 2)。"""

    @staticmethod
    def extract_all(*args: object, **kwargs: object) -> list[dict]:
        raise RuntimeError("simulated slot/skill layer failure (original bug class)")

    @staticmethod
    def extract(*args: object, **kwargs: object) -> dict:
        raise RuntimeError("unreachable")


class _ChatOnlySlotExtractor:
    """chat 意图低置信度 → Step 1.5 不拦截,自然跌落 Step 2(FAQ 的真实路径)。"""

    @staticmethod
    def extract_all(*args: object, **kwargs: object) -> list[dict]:
        return [
            {
                "intentType": "chat",
                "confidence": 0.3,
                "slots": {},
                "missingSlots": [],
                "clarificationMessage": "",
            }
        ]

    @staticmethod
    def extract(*args: object, **kwargs: object) -> dict:
        return {
            "intentType": "chat",
            "confidence": 0.3,
            "slots": {},
            "missingSlots": [],
            "clarificationMessage": "",
        }


async def _fake_classify(text: str, **kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(
        isOutOfScope=False,
        clarificationMessage=None,
        intents=[
            SimpleNamespace(
                intent="cart_manage",
                confidence=0.95,
                type="primary",
                entities={},
                missingSlots=[],
                condition=None,
            )
        ],
    )


async def _fake_exemplars(*args: object, **kwargs: object) -> list:
    return []


async def _noop_log(*args: object, **kwargs: object) -> None:
    return None


async def _fake_embed(text: str) -> list[float]:
    return list(_TEST_VEC)


async def _fake_anchors() -> dict[str, list[list[float]]]:
    # 与 _TEST_VEC 正交 → 锚点三判定全部 0 分,不拦截、直达缓存检查
    orthogonal = [0.0, 1.0, 0.0]
    return {"order_status": [orthogonal], "refund": [orthogonal], "out_of_scope": [orthogonal]}


def _run_triage(
    monkeypatch: pytest.MonkeyPatch,
    *,
    user_input: str,
    slot_extractor: type,
    seed_cache: dict | None,
) -> dict:
    monkeypatch.setattr(triage_mod, "ShortMemory", _FakeShortMemoryTriage)
    monkeypatch.setattr(triage_mod, "TaskMemory", _FakeTaskMemory)
    monkeypatch.setattr(triage_mod, "SlotExtractor", slot_extractor)
    monkeypatch.setattr(triage_mod, "classify", _fake_classify)
    monkeypatch.setattr(triage_mod, "search_relevant_exemplars", _fake_exemplars)
    monkeypatch.setattr(triage_mod.IntentTriageEngine, "log_intent_to_db", _noop_log)
    monkeypatch.setattr(SemanticVectorCache, "_tenant_cache", {})
    monkeypatch.setattr(SemanticVectorCache, "get_embedding_with_cache", _fake_embed)
    monkeypatch.setattr(SemanticVectorCache, "get_anchor_vectors", _fake_anchors)
    if seed_cache is not None:
        SemanticVectorCache._tenant_cache["ecommerce"] = [seed_cache]

    state = {
        "thread_id": "thread_cache_poison_read",
        "user_id": "u_poison_test",
        "input": user_input,
        "image_urls": [],
        "input_embedding": list(_TEST_VEC),
        "short_memory": [],
    }
    return asyncio.run(triage_mod.IntentTriageEngine.process(state))


def test_triage_read_gate_rejects_poisoned_cache_for_action_input(monkeypatch: pytest.MonkeyPatch) -> None:
    # 预置投毒缓存:与输入向量完全一致(相似度 1.0,无读闸必命中)
    result = _run_triage(
        monkeypatch,
        user_input="把第1件加入购物车",
        slot_extractor=_ExplodingSlotExtractor,
        seed_cache={"query": "把第1件加入购物车", "reply": _POISON_REPLY, "vector": list(_TEST_VEC)},
    )
    # 🔴 无读闸时:命中 super_semantic_cache 旁路,intents=general_query、
    # output=幻觉原文,永远绕过 CartManageSkill 真实执行
    assert result["intents"][0]["intent"] == "cart_manage", "动作形输入必须落到真实分类/执行,不得被缓存旁路"
    assert "已成功" not in (result.get("output") or ""), "投毒缓存回复不得透出"


def test_triage_read_gate_keeps_faq_cache_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _run_triage(
        monkeypatch,
        user_input="你们支持哪些支付方式",
        slot_extractor=_ChatOnlySlotExtractor,
        seed_cache={"query": "你们支持哪些支付方式", "reply": _FAQ_REPLY, "vector": list(_TEST_VEC)},
    )
    assert "支付宝" in (result.get("output") or ""), "纯 FAQ 仍应命中缓存秒回(闸门不得误伤缓存本职)"
    assert result["intents"][0]["intent"] == "general_query"
