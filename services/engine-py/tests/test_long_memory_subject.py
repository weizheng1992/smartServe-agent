"""长记忆主体归属册(2026-10-24 画像归属票)。

钉面:①可变数字维度同维度异值覆盖(实弹「体重70/75 并存」修复)+同值真回声
弃;②体重 斤→kg 归一(140斤=70kg 不再并存);③回声目标为 pending 时再现
升级(补 pending 永无人审的闭环);④subject 分组:第三人事实与本人互不为
回声、互不覆盖;⑤正则回退路的第三人归属。经 pg_factory 密封 PG,嵌入用
parity 假向量(同文本同向量=回声,异文本近正交=不误伤,不触真 bge)。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select

from engine_py.db import LongMemoryFact, get_session
from engine_py.memory import long_memory as lm_module
from engine_py.memory.long_memory import (
    LongMemory,
    fact_dimension_value,
    normalize_subject,
)

pytestmark = pytest.mark.usefixtures("pg_factory")


def _biz() -> str:
    return f"mem_{uuid.uuid4().hex[:10]}"


def _fake_embed(text: str) -> list[float]:
    """parity 假向量:同文本同向量(cos=1 必判回声),异文本正交(不误伤)。"""
    return [1.0, 0.0] if sum(ord(c) for c in text) % 2 else [0.0, 1.0]


@pytest.fixture(autouse=True)
def _fake_embedding(monkeypatch):
    """测试不触真 bge:嵌入按文本 parity 生成。"""

    async def fake_embed(self_or_text, *args, **kwargs):
        text = self_or_text if isinstance(self_or_text, str) else str(self_or_text)
        return _fake_embed(text)

    monkeypatch.setattr(lm_module, "get_embedding_model", lambda: type("E", (), {"aembed_query": staticmethod(fake_embed)}))


def _rows(user_id: str) -> list[LongMemoryFact]:
    async def run():
        async with get_session() as session:
            return (
                (
                    await session.execute(
                        select(LongMemoryFact)
                        .where(LongMemoryFact.user_id == user_id)
                        .order_by(LongMemoryFact.created_at, LongMemoryFact.id)
                    )
                )
                .scalars()
                .all()
            )

    return asyncio.run(run())


def _ingest(mem: LongMemory, fact: str, *, subject: str = "self", confidence: float = 0.95, status: str = "approved"):
    return asyncio.run(
        mem._ingest_fact(
            fact_text=fact,
            embedding=_fake_embed(fact),
            scope="global",
            business_id=None,
            confidence=confidence,
            status=status,
            source="agent_audit",
            subject=subject,
        )
    )


# ---- 纯函数:维度提取与主体归一 ----


def test_fact_dimension_value_normalization():
    assert fact_dimension_value("用户身高175cm") == ("身高", "175")
    assert fact_dimension_value("体重140斤") == ("体重", "70")  # 斤→kg 归一
    assert fact_dimension_value("现在体重75了") == ("体重", "75")
    assert fact_dimension_value("脚长270mm") == ("脚长", "270")
    assert fact_dimension_value("尺码：XL") == ("尺码", "XL")
    assert fact_dimension_value("喜欢宽松版型") is None
    assert fact_dimension_value(None) is None


def test_normalize_subject():
    assert normalize_subject(None) == "self"
    assert normalize_subject("self") == "self"
    assert normalize_subject("本人") == "self"
    assert normalize_subject("妻子") == "妻子"
    assert normalize_subject("x" * 50) == "x" * 12  # 防散文截断


# ---- 密封 PG:写侧三分与主体分组 ----


def test_dimension_new_value_supersedes_old():
    user = f"mem_{uuid.uuid4().hex[:8]}"
    mem = LongMemory(user, None)
    _ingest(mem, "用户身高175cm")
    _ingest(mem, "用户身高178cm")

    rows = _rows(user)
    by_fact = {r.fact: r.status for r in rows}
    assert by_fact["用户身高175cm"] == "superseded"
    assert by_fact["用户身高178cm"] == "approved"

    # 读侧 approved-only:只召回新值
    recalled = asyncio.run(mem.search_relevant_facts("身高"))
    assert [f["fact"] for f in recalled] == ["用户身高178cm"]
    assert recalled[0]["subject"] == "self"


def test_dimension_same_value_is_true_echo():
    user = f"mem_{uuid.uuid4().hex[:8]}"
    mem = LongMemory(user, None)
    _ingest(mem, "用户身高178cm")
    _ingest(mem, "用户身高178cm")  # 同值同维度:真回声弃落

    rows = _rows(user)
    assert len(rows) == 1
    assert rows[0].status == "approved"


def test_weight_unit_normalization_prevents_coexistence():
    user = f"mem_{uuid.uuid4().hex[:8]}"
    mem = LongMemory(user, None)
    _ingest(mem, "用户体重140斤")
    _ingest(mem, "用户体重70kg")  # 归一后同值:回声弃落,不再 70/140 并存

    rows = _rows(user)
    assert len(rows) == 1
    assert rows[0].fact == "用户体重140斤"


def test_pending_echo_promotes_on_reoccurrence():
    user = f"mem_{uuid.uuid4().hex[:8]}"
    mem = LongMemory(user, None)
    _ingest(mem, "用户偏好亚麻面料", confidence=0.8, status="pending")
    _ingest(mem, "用户偏好亚麻面料", confidence=0.8, status="pending")  # 再现=群众复核

    rows = _rows(user)
    assert len(rows) == 1  # 不新增重复行
    assert rows[0].status == "approved"
    assert (rows[0].confidence or 0) >= 0.85


def test_subject_grouping_no_cross_conflict():
    user = f"mem_{uuid.uuid4().hex[:8]}"
    mem = LongMemory(user, None)
    _ingest(mem, "用户的妻子身高约160cm", subject="妻子")
    _ingest(mem, "用户身高175cm")
    _ingest(mem, "用户身高178cm")  # 只覆盖本人的 175,妻子的 160 不动

    rows = _rows(user)
    by_fact = {(r.fact, r.subject): r.status for r in rows}
    assert by_fact[("用户身高175cm", "self")] == "superseded"
    assert by_fact[("用户身高178cm", "self")] == "approved"
    assert by_fact[("用户的妻子身高约160cm", "妻子")] == "approved"

    # 第三人与本人的事实互不为回声(同文本异主体各自成行)
    _ingest(mem, "用户偏好亚麻面料")
    _ingest(mem, "用户偏好亚麻面料", subject="妻子")
    rows = _rows(user)
    linen = [r for r in rows if r.fact == "用户偏好亚麻面料"]
    assert {r.subject for r in linen} == {"self", "妻子"}


def test_regex_fallback_third_person_subject():
    user = f"mem_{uuid.uuid4().hex[:8]}"
    mem = LongMemory(user, None)
    asyncio.run(mem.extract_and_store_fact("fact: 妻子喜欢亚麻连衣裙", user_query=None))

    rows = _rows(user)
    assert len(rows) == 1
    assert rows[0].subject == "妻子"
    assert rows[0].source == "regex_fallback"
