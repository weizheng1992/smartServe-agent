"""锚点 oos 终局权收编(intent-arbitration 06,2026-09-10)—— 判定 4 降为提议者。

现状钉子:「买个东西怎么买」购买流程咨询,oos 锚句余弦 1.000(实测 bge-small-zh),
旧路径 29 锚句 ×0.86 硬阈值判死后直接关会话,零 LLM 确认 —— 用户拿到「超出
服务范围」罐头回复;结构化精判对同输入判 shopping_guide(实测)。本套钉死:

1. 锚点 oos 高分不再独自收尾:fallthrough Step 3 结构化精判;
2. 精判确认出范畴 → llm_out_of_scope 照旧收尾,行为不变;
3. 确认/改判决策进 01 的仲裁留痕(candidates 含 embedding→structured_llm 链)。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.triage import intent_triage_engine as triage_mod
from engine_py.triage.semantic_cache import SemanticVectorCache
from engine_py.triage.structured_classifier import IntentNode, StructuredTriageOutput


async def _fake_exemplars(*args, **kwargs) -> list:
    return []


class _FakeShortMemory:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_messages(self) -> list:
        return []


class _FakeTaskMemory:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_task_state(self) -> dict | None:
        return None

    async def save_task_state(self, state: dict) -> None:
        return None


def _state() -> dict:
    return {
        "thread_id": "thread_anchor_oos_test",
        "user_id": "u_anchor_oos",
        "input": "买个东西怎么买",  # 实测:oos 锚句余弦 1.000,槽位层判 chat
        "image_urls": [],
        "input_embedding": [1.0, 0.0, 0.0],
        "business_config": {"businessId": "ecommerce"},
    }


class TestAnchorOosArbitration:
    def _run_process(
        self,
        monkeypatch: pytest.MonkeyPatch,
        classify_result: StructuredTriageOutput,
        log_calls: list,
    ) -> dict:
        """锚点向量摆位:输入向量 [1,0,0] 仅与 oos 锚 [1,0,0] 平行(相似 1.0),
        与 order/refund 锚 [0,1,0] 正交 —— 判定 4 必命中且余量充足。"""

        async def _fake_classify(input_text, **kwargs):
            return classify_result

        async def _fake_embed(text: str) -> list[float]:
            return [1.0, 0.0, 0.0]

        async def _fake_anchors() -> dict:
            orth = [0.0, 1.0, 0.0]
            return {"order_status": [orth], "refund": [orth], "out_of_scope": [[1.0, 0.0, 0.0]]}

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

    def test_anchor_oos_rejudged_action_not_canned_close(self, monkeypatch):
        """锚点 oos 满分 × 精判改判动作意图 → 走动作管道结果,不得罐头关会话。
        06 之前:判定 4 直接返回 general_query + 「超出服务范围」罐头回复。"""
        result = self._run_process(
            monkeypatch,
            StructuredTriageOutput(intents=[IntentNode(intent="shopping_guide", confidence=0.85)]),
            [],
        )
        assert result["intents"][0]["intent"] == "shopping_guide", (
            "锚点误吞的购买流程咨询必须按精判走动作管道,而非罐头兜底"
        )
        assert "output" not in result or "超出" not in str(result.get("output", "")), (
            "不得以 oos 罐头回复关闭业务内会话"
        )

    def test_anchor_oos_llm_confirmed_keeps_oos_close_with_trace(self, monkeypatch):
        """精判确认真 oos → 照旧收尾(行为不变),且留痕呈现
        embedding(out_of_scope)→ structured_llm(out_of_scope) 确认链。"""
        log_calls: list = []
        result = self._run_process(
            monkeypatch,
            StructuredTriageOutput(
                intents=[IntentNode(intent="out_of_scope", confidence=0.9)],
                isOutOfScope=True,
            ),
            log_calls,
        )
        assert result["intents"][0]["intent"] == "general_query"
        assert "超出了我的服务范围" in str(result.get("output", ""))
        assert "llm_out_of_scope" in str(result["task_plan"]["subtasks"][0]["description"])
        # 单点落库(01):一条终局行,candidates 携带锚点提议与 LLM 确认
        assert len(log_calls) == 1
        candidates = log_calls[0]["kwargs"]["candidates"]
        layers = [(c["layer"], c["intent"]) for c in candidates]
        assert ("embedding", "out_of_scope") in layers, "锚点提议必须进终局留痕"
        assert ("structured_llm", "out_of_scope") in layers, "LLM 确认必须紧随其后留痕"
        assert layers.index(("embedding", "out_of_scope")) < layers.index(
            ("structured_llm", "out_of_scope")
        )
        assert log_calls[0]["kwargs"]["arbitration_reason"] == "llm_out_of_scope"

    def test_rejudge_trace_carries_anchor_proposal_into_terminal_row(self, monkeypatch):
        """改判路径同样留痕:终局行 candidates 含锚点 oos 提议与精判胜出提议。"""
        log_calls: list = []
        self._run_process(
            monkeypatch,
            StructuredTriageOutput(intents=[IntentNode(intent="shopping_guide", confidence=0.85)]),
            log_calls,
        )
        assert len(log_calls) == 1
        layers = [(c["layer"], c["intent"]) for c in log_calls[0]["kwargs"]["candidates"]]
        assert ("embedding", "out_of_scope") in layers
        assert ("structured_llm", "shopping_guide") in layers
        assert log_calls[0]["kwargs"]["arbitration_reason"] == "structured_llm_terminal"


if __name__ == "__main__":
    pytest.main([__file__])
