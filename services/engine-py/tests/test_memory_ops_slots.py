"""画像审计 op 协议册(2026-10-24 SOTA 对齐 P1#1,docs/memory-sota-upgrade.md)。

钉面:UPDATE 覆盖 target(转 superseded)+ 槽位随新值 upsert;DELETE 转 deleted
并入 badcase 候选池(SOURCE_PERSONA_FACT_DELETED,auto-draft 源);NOOP 零写入;
op 缺失按 ADD 兜底(规则路径);DELETE 目标不存在不落任何东西;prompt 携带
既有事实清单。经 pg_factory 密封 PG,chat/embedding 全桩。
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from sqlalchemy import select

from engine_py.badcase.pool import SOURCE_PERSONA_FACT_DELETED
from engine_py.db import BadcaseCandidate, LongMemoryFact, get_session
from engine_py.memory import long_memory as lm_module
from engine_py.memory.long_memory import LongMemory, read_profile_slots

pytestmark = pytest.mark.usefixtures("pg_factory")


@pytest.fixture()
def fake_models(monkeypatch):
    """桩 chat(固定 audit payload)+ 首现正交向量 embedding(同 routing 册模式)。"""
    holder: dict = {"payload": "", "prompts": []}
    seen_vecs: dict[str, list[float]] = {}

    class _StubEmbed:
        async def aembed_query(self, t: str) -> list[float]:
            if t not in seen_vecs:
                seen_vecs[t] = [1.0, 0.0] if len(seen_vecs) % 2 == 0 else [0.0, 1.0]
            return seen_vecs[t]

    class _StubChat:
        async def ainvoke(self, prompt: str):
            holder["prompts"].append(prompt)
            resp = type("R", (), {})()
            resp.content = holder["payload"]
            return resp

    monkeypatch.setattr(lm_module, "get_embedding_model", lambda: _StubEmbed())
    monkeypatch.setattr(lm_module, "get_chat_model", lambda: _StubChat())
    return holder


def _seed_fact(user: str, fact: str, *, status: str = "approved", subject: str = "self") -> str:
    async def run():
        async with get_session() as session:
            row = LongMemoryFact(
                user_id=user,
                fact=fact,
                embedding=json.dumps([1.0, 0.0]),
                confidence=0.95,
                status=status,
                source="agent_audit",
                subject=subject,
            )
            session.add(row)
            await session.commit()
            return str(row.id)

    return asyncio.run(run())


def _fact_rows(user: str) -> list[LongMemoryFact]:
    async def run():
        async with get_session() as session:
            return (
                (
                    await session.execute(
                        select(LongMemoryFact).where(LongMemoryFact.user_id == user).order_by(LongMemoryFact.created_at)
                    )
                )
                .scalars()
                .all()
            )

    return asyncio.run(run())


def _badcase_count(user: str) -> int:
    async def run():
        async with get_session() as session:
            rows = (
                (
                    await session.execute(
                        select(BadcaseCandidate).where(BadcaseCandidate.conversation_ref.like(f"%{user}%"))
                    )
                )
                .scalars()
                .all()
            )
            return [r for r in rows if r.signal_source == SOURCE_PERSONA_FACT_DELETED]

    return asyncio.run(run())


class TestOpProtocol:
    def test_update_op_supersedes_target_and_upserts_slot(self, fake_models):
        user = f"ops_{uuid.uuid4().hex[:8]}"
        target_id = _seed_fact(user, "用户体重70kg")
        fake_models["payload"] = json.dumps(
            {
                "hasNewPreference": True,
                "extractedFacts": [
                    {"fact": "用户当前体重约75kg", "scope": "global", "confidence": 0.95, "op": "UPDATE", "targetId": target_id}
                ],
            },
            ensure_ascii=False,
        )
        asyncio.run(LongMemory(user, None)._run_profile_audit("我胖了现在75了", "好的已记录"))

        rows = _fact_rows(user)
        by_fact = {r.fact: r.status for r in rows}
        assert by_fact["用户体重70kg"] == "superseded"
        assert by_fact["用户当前体重约75kg"] == "approved"
        slots = asyncio.run(read_profile_slots(user))
        weight = [s for s in slots if s["slot"] == "weight"]
        assert len(weight) == 1 and weight[0]["value"] == "75"

    def test_delete_op_marks_deleted_and_records_badcase(self, fake_models):
        user = f"ops_{uuid.uuid4().hex[:8]}"
        target_id = _seed_fact(user, "用户身高175cm")
        fake_models["payload"] = json.dumps(
            {
                "hasNewPreference": True,
                "extractedFacts": [
                    {"fact": "", "scope": "global", "confidence": 0.95, "op": "DELETE", "targetId": target_id}
                ],
            },
            ensure_ascii=False,
        )
        asyncio.run(LongMemory(user, None)._run_profile_audit("忘掉我的身高吧", "好的已删除"))

        rows = _fact_rows(user)
        assert len(rows) == 1 and rows[0].status == "deleted"
        badcases = _badcase_count(user)
        assert len(badcases) == 1
        # 撤回的事实不再被召回(approved-only)
        assert asyncio.run(LongMemory(user, None).search_relevant_facts("身高")) == []

    def test_noop_zero_write(self, fake_models):
        user = f"ops_{uuid.uuid4().hex[:8]}"
        fake_models["payload"] = json.dumps(
            {
                "hasNewPreference": True,
                "extractedFacts": [
                    {"fact": "用户喜欢黑色", "scope": "global", "confidence": 0.95, "op": "NOOP"}
                ],
            },
            ensure_ascii=False,
        )
        asyncio.run(LongMemory(user, None)._run_profile_audit("还能选黑色吗", "可以"))
        assert _fact_rows(user) == []

    def test_missing_op_defaults_add(self, fake_models):
        user = f"ops_{uuid.uuid4().hex[:8]}"
        fake_models["payload"] = json.dumps(
            {
                "hasNewPreference": True,
                "extractedFacts": [
                    {"fact": "用户喜欢羊毛围巾", "scope": "global", "confidence": 0.95}
                ],
            },
            ensure_ascii=False,
        )
        asyncio.run(LongMemory(user, None)._run_profile_audit("给我推荐羊毛围巾", "好的"))
        rows = _fact_rows(user)
        assert len(rows) == 1 and rows[0].status == "approved"

    def test_delete_missing_target_no_write_no_badcase(self, fake_models):
        user = f"ops_{uuid.uuid4().hex[:8]}"
        fake_models["payload"] = json.dumps(
            {
                "hasNewPreference": True,
                "extractedFacts": [
                    {"fact": "", "scope": "global", "confidence": 0.95, "op": "DELETE", "targetId": str(uuid.uuid4())}
                ],
            },
            ensure_ascii=False,
        )
        asyncio.run(LongMemory(user, None)._run_profile_audit("忘了我的尺码吧", "好的"))
        assert _fact_rows(user) == []
        assert _badcase_count(user) == []

    def test_prompt_carries_existing_facts(self, fake_models):
        user = f"ops_{uuid.uuid4().hex[:8]}"
        _seed_fact(user, "用户身高175cm")
        fake_models["payload"] = json.dumps({"hasNewPreference": False, "extractedFacts": []})
        asyncio.run(LongMemory(user, None)._run_profile_audit("有什么推荐", "暂无"))
        assert fake_models["prompts"], "chat 未被调用"
        assert "Existing Profile Facts" in fake_models["prompts"][-1]
        assert "用户身高175cm" in fake_models["prompts"][-1]
