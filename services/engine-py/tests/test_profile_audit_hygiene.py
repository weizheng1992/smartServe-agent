"""画像审计写路卫生钉死(wayfinder persona-hardening 13)。

钉三组行为(全程桩 LLM/向量模型,零真实调用,缝与 02 号票同):
- source 钉枚举:审计 Agent 产物落库 source 一律 agent_audit,LLM 自填的
  散文(实弹:「本轮对话-用户主动提及徒步行程」)写时不信 —— 归因查询
  (10 号票 A3 断言 LIKE 'agent_audit%')才有意义;
- prompt 卫生:schema 不再要求 LLM 自填 source + 明令 assistant 转述不算
  用户新陈述(回声环路的源头闸);
- 回声去重:新事实与该用户既有事实(含 pending)高相似(≥0.90)即弃,
  阻断 注入→回复→再抽取 的回声环路;低于阈值照常落库。

审计任务在产线经 fire-and-forget create_task 派生;测试直调
`_run_profile_audit` 取确定性,不追逐后台任务时序。
"""

from __future__ import annotations

import asyncio
import json
import math
from contextlib import contextmanager

import pytest
from sqlalchemy import select, text

from engine_py.db import LongMemoryFact
from engine_py.memory.long_memory import (
    _ECHO_DEDUP_THRESHOLD,
    PROFILE_AUDIT_SYSTEM_PROMPT,
    LongMemory,
)


@pytest.fixture()
def clean_profile_tables(pg_factory):
    def _clean() -> None:
        async def _go() -> None:
            async with pg_factory() as session:
                await session.execute(text("DELETE FROM long_memory_facts"))
                await session.commit()

        asyncio.run(_go())

    _clean()
    return pg_factory


@contextmanager
def _fake_models(audit_payload: str, embed_map: dict[str, list[float]]):
    """桩 chat(固定 audit JSON)+ embedding(文本→向量映射表,未命中给零向量)。"""
    from engine_py.memory import long_memory as lm

    class _Resp:
        content = audit_payload

    class _StubChat:
        async def ainvoke(self, _prompt: str):
            return _Resp()

    class _StubEmbed:
        async def aembed_query(self, value: str) -> list[float]:
            return embed_map.get(value, [0.0, 0.0])

    orig_emb, orig_chat = lm.get_embedding_model, lm.get_chat_model
    lm.get_embedding_model = lambda: _StubEmbed()
    lm.get_chat_model = lambda: _StubChat()
    try:
        yield
    finally:
        lm.get_embedding_model, lm.get_chat_model = orig_emb, orig_chat


def _seed_fact(factory, user: str, fact: str, embedding: list[float], status: str = "approved") -> None:
    async def _go() -> None:
        async with factory() as session:
            session.add(
                LongMemoryFact(
                    user_id=user,
                    scope="global",
                    fact=fact,
                    embedding=json.dumps(embedding),
                    type="preference",
                    confidence=1.0,
                    status=status,
                    source="agent_audit",
                )
            )
            await session.commit()

    asyncio.run(_go())


def _rows_of(factory, user: str) -> list[dict]:
    async def _q() -> list[dict]:
        async with factory() as session:
            rows = (
                (await session.execute(select(LongMemoryFact).where(LongMemoryFact.user_id == user)))
                .scalars()
                .all()
            )
            return [{"fact": r.fact, "source": r.source, "status": r.status} for r in rows]

    return asyncio.run(_q())


def _run_audit(user: str, payload: str, embed_map: dict[str, list[float]]) -> None:
    with _fake_models(payload, embed_map):
        asyncio.run(LongMemory(user, "ecommerce")._run_profile_audit("顾客的提问", "客服的回答"))


# ---------- source 钉枚举 ----------


class TestSourcePinnedToEnum:
    def test_llm_free_text_source_never_stored(self, clean_profile_tables):
        """实弹形状:LLM 把 source 填成中文叙述散文,写时必须无视,一律钉 agent_audit。"""
        payload = json.dumps(
            {
                "hasNewPreference": True,
                "extractedFacts": [
                    {
                        "fact": "用户偏好黑色配色的装备",
                        "scope": "global",
                        "confidence": 0.9,
                        "source": "本轮对话-用户主动提及徒步行程",
                    }
                ],
            },
            ensure_ascii=False,
        )
        _run_audit("t-prof-hygiene-1", payload, {})
        rows = _rows_of(clean_profile_tables, "t-prof-hygiene-1")
        assert len(rows) == 1
        assert rows[0]["source"] == "agent_audit"

    def test_llm_plausible_enum_source_also_pinned(self, clean_profile_tables):
        """LLM 碰巧填了合法枚举值也一样钉 agent_audit —— 写时不信 LLM,不留双轨。"""
        payload = json.dumps(
            {
                "hasNewPreference": True,
                "extractedFacts": [
                    {"fact": "用户偏好顺丰快递", "scope": "global", "confidence": 0.9, "source": "tool_record"}
                ],
            },
            ensure_ascii=False,
        )
        _run_audit("t-prof-hygiene-2", payload, {})
        rows = _rows_of(clean_profile_tables, "t-prof-hygiene-2")
        assert rows[0]["source"] == "agent_audit"


# ---------- prompt 卫生 ----------


class TestPromptHygiene:
    def test_prompt_schema_no_longer_asks_llm_for_source(self):
        """schema 里的 "source": string 行必须移除 —— 要求了就必然有散文回流。"""
        assert '"source"' not in PROFILE_AUDIT_SYSTEM_PROMPT

    def test_prompt_carries_echo_guard(self):
        """回声源头闸:assistant 转述已注入画像不算用户新陈述,必须明令。"""
        assert "转述" in PROFILE_AUDIT_SYSTEM_PROMPT


# ---------- 回声再吸收去重 ----------


class TestEchoDedup:
    def test_high_similarity_echo_of_existing_fact_dropped(self, clean_profile_tables):
        """注入→回复→再抽取回声:与既有 approved 事实近重复(≥阈值)即弃,零落库。"""
        _seed_fact(clean_profile_tables, "t-prof-hygiene-3", "买包只买黑色的包", [1.0, 0.0])
        payload = json.dumps(
            {
                "hasNewPreference": True,
                "extractedFacts": [
                    {"fact": "用户偏好黑色配色的包", "scope": "global", "confidence": 0.6}
                ],
            },
            ensure_ascii=False,
        )
        # 桩向量与既有事实同向 → 余弦 1.0 ≥ 阈值
        _run_audit("t-prof-hygiene-3", payload, {"用户偏好黑色配色的包": [1.0, 0.0]})
        rows = _rows_of(clean_profile_tables, "t-prof-hygiene-3")
        assert [r["fact"] for r in rows] == ["买包只买黑色的包"]

    def test_echo_of_pending_fact_also_dropped(self, clean_profile_tables):
        """pending 事实同属回声源 —— 否则待审队列照样被重复污染。"""
        _seed_fact(clean_profile_tables, "t-prof-hygiene-4", "用户喜欢徒步", [1.0, 0.0], status="pending")
        payload = json.dumps(
            {
                "hasNewPreference": True,
                "extractedFacts": [
                    {"fact": "用户喜欢徒步", "scope": "global", "confidence": 0.6}
                ],
            },
            ensure_ascii=False,
        )
        _run_audit("t-prof-hygiene-4", payload, {"用户喜欢徒步": [1.0, 0.0]})
        rows = _rows_of(clean_profile_tables, "t-prof-hygiene-4")
        assert len(rows) == 1 and rows[0]["status"] == "pending"

    def test_below_threshold_new_fact_still_stored(self, clean_profile_tables):
        """低于阈值(余弦 0.866 < 0.90)是真新事实,照常落库。"""
        _seed_fact(clean_profile_tables, "t-prof-hygiene-5", "用户偏好黑色", [1.0, 0.0])
        payload = json.dumps(
            {
                "hasNewPreference": True,
                "extractedFacts": [
                    {"fact": "用户偏好徒步背包", "scope": "global", "confidence": 0.9}
                ],
            },
            ensure_ascii=False,
        )
        angle = math.acos(0.866)
        vec = [math.cos(angle), math.sin(angle)]
        _run_audit("t-prof-hygiene-5", payload, {"用户偏好徒步背包": vec})
        rows = _rows_of(clean_profile_tables, "t-prof-hygiene-5")
        assert {r["fact"] for r in rows} == {"用户偏好黑色", "用户偏好徒步背包"}

    def test_orthogonal_fact_stored(self, clean_profile_tables):
        _seed_fact(clean_profile_tables, "t-prof-hygiene-6", "用户脚长270mm", [1.0, 0.0])
        payload = json.dumps(
            {
                "hasNewPreference": True,
                "extractedFacts": [
                    {"fact": "用户对羊毛过敏", "scope": "global", "confidence": 0.9}
                ],
            },
            ensure_ascii=False,
        )
        _run_audit("t-prof-hygiene-6", payload, {"用户对羊毛过敏": [0.0, 1.0]})
        rows = _rows_of(clean_profile_tables, "t-prof-hygiene-6")
        assert len(rows) == 2

    def test_dedup_threshold_is_strict(self):
        """阈值语义:≥ 即弃,取 0.90(与范例回放近重复线同档)。"""
        assert _ECHO_DEDUP_THRESHOLD >= 0.9
