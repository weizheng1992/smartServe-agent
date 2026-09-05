"""双层画像租户隔离回归(memory/long_memory.py,钉死 .claude/rules/agent-engine.md §1.4)。

读侧(``search_relevant_facts`` 的 _tenant_visible 过滤):
- scope=global(或空)全商户放行——客观生理事实(脚长/过敏)跨商户通用;
- scope=tenant 仅归属商户可见:竞品不可见、平台默认上下文(ecommerce/无)也不可见;
- 平台默认上下文只放行"无主/自营"画像,不放行任何具名租户画像;
- 跨用户隔离(user_id SQL 过滤)与 pending 状态不参与召回。

写侧(``extract_and_store_facts`` 正则容灾路径的 scope 判定链):
显式声明 > 生理特征正则(global)> 商户上下文(非 ecommerce 即 tenant)。

检索走 ``precomputed_embedding`` 注入、写入打桩 embedding 模型,全程零 LLM/零向量模型。
"""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager

import pytest
from sqlalchemy import text

from engine_py.db import LongMemoryFact
from engine_py.memory.long_memory import LongMemory

_EMB = json.dumps([1.0, 0.0])  # 与查询侧 precomputed [1,0] 余弦=1,必过 0.55 阈值
_ORTHOGONAL_EMB = json.dumps([0.0, 1.0])  # 余弦=0,用于阈值下限用例


@pytest.fixture()
def clean_facts(pg_factory):
    asyncio.run(_clean(pg_factory))
    return pg_factory


@contextmanager
def _fake_embedding_model():
    """extract_and_store_fact 的写侧向量化打桩(检索侧用 precomputed_embedding 不经过此)。"""
    from engine_py.memory import long_memory as lm

    class _StubModel:
        async def aembed_query(self, _text: str) -> list[float]:
            return [1.0, 0.0]

    original = lm.get_embedding_model
    lm.get_embedding_model = lambda: _StubModel()
    try:
        yield
    finally:
        lm.get_embedding_model = original


async def _clean(factory) -> None:
    async with factory() as session:
        await session.execute(text("DELETE FROM long_memory_facts"))
        await session.commit()


def _mk_fact(
    *,
    user: str = "CUST-P1",
    scope: str = "global",
    business: str | None = None,
    fact: str = "用户脚长 270mm",
    status: str = "approved",
    embedding: str = _EMB,
) -> LongMemoryFact:
    return LongMemoryFact(
        user_id=user,
        business_id=business,
        scope=scope,
        fact=fact,
        embedding=embedding,
        type="preference",
        confidence=0.9,
        status=status,
        source="test",
    )


async def _insert(factory, *facts: LongMemoryFact) -> None:
    async with factory() as session:
        for f in facts:
            session.add(f)
        await session.commit()


def _facts_of(result: list[dict]) -> set[str]:
    return {item["fact"] for item in result}


async def _search(mem: LongMemory, query: str = "脚长 偏好") -> list[dict]:
    return await mem.search_relevant_facts(query, precomputed_embedding=[1.0, 0.0])


# ---------- 读侧:作用域可见性 ----------


def test_global画像跨租户可见(clean_facts):
    """客观生理事实(scope=global)对所有商户上下文放行。"""
    factory = clean_facts
    asyncio.run(_insert(factory, _mk_fact(scope="global", business=None, fact="用户脚长 270mm")))

    for ctx in ("nike", "adidas", "ecommerce", None):
        mem = LongMemory("CUST-P1", ctx)
        result = asyncio.run(_search(mem))
        assert "用户脚长 270mm" in _facts_of(result), f"global 画像在上下文 {ctx} 不可见"


def test_tenant画像竞品与平台均不可见(clean_facts):
    """scope=tenant 画像:归属商户可见,竞品与平台默认上下文均不可见(防跨租户泄漏)。"""
    factory = clean_facts
    asyncio.run(
        _insert(
            factory,
            _mk_fact(scope="tenant", business="nike", fact="偏好 Nike Flyknit 系列跑鞋"),
            _mk_fact(scope="tenant", business="adidas", fact="偏好 Adidas 椰子鞋"),
        )
    )

    # 归属商户各见其位
    nike_view = _facts_of(asyncio.run(_search(LongMemory("CUST-P1", "nike"))))
    assert "偏好 Nike Flyknit 系列跑鞋" in nike_view
    assert "偏好 Adidas 椰子鞋" not in nike_view

    adidas_view = _facts_of(asyncio.run(_search(LongMemory("CUST-P1", "adidas"))))
    assert "偏好 Adidas 椰子鞋" in adidas_view
    assert "偏好 Nike Flyknit 系列跑鞋" not in adidas_view

    # 平台默认上下文(ecommerce / 无)一双租户画像都看不到
    for ctx in ("ecommerce", None):
        platform_view = _facts_of(asyncio.run(_search(LongMemory("CUST-P1", ctx))))
        assert platform_view == set(), f"平台上下文 {ctx} 泄漏了具名租户画像"


def test_平台上下文仅见无主与自营画像(clean_facts):
    """tenant 画像在平台默认上下文下:business_id 空缺/ecommerce 放行,具名租户拦截。"""
    factory = clean_facts
    asyncio.run(
        _insert(
            factory,
            _mk_fact(scope="tenant", business=None, fact="偏好顺丰快递"),
            _mk_fact(scope="tenant", business="ecommerce", fact="偏好平台自营次日达"),
            _mk_fact(scope="tenant", business="nike", fact="偏好 Nike 会员积分兑换"),
        )
    )

    view = _facts_of(asyncio.run(_search(LongMemory("CUST-P1", "ecommerce"))))
    assert view == {"偏好顺丰快递", "偏好平台自营次日达"}


def test_跨用户画像隔离(clean_facts):
    """画像按 user_id 物理隔离:他人的 global 画像也不得召回。"""
    factory = clean_facts
    asyncio.run(_insert(factory, _mk_fact(user="CUST-P1", scope="global", fact="用户脚长 270mm")))

    other_view = _facts_of(asyncio.run(_search(LongMemory("CUST-P2", "nike"))))
    assert other_view == set()


def test_pending画像不参与召回(clean_facts):
    factory = clean_facts
    asyncio.run(_insert(factory, _mk_fact(status="pending", fact="待审画像")))

    view = _facts_of(asyncio.run(_search(LongMemory("CUST-P1", "nike"))))
    assert view == set()


def test_相似度低于阈值不召回(clean_facts):
    """正交向量且无关键词命中 → effective_score=0 < 0.55,过滤(阈值行为钉死)。"""
    factory = clean_facts
    asyncio.run(_insert(factory, _mk_fact(fact="用户喜欢凌晨下单", embedding=_ORTHOGONAL_EMB)))

    view = _facts_of(asyncio.run(_search(LongMemory("CUST-P1", "nike"), query="尺码推荐")))
    assert view == set()


# ---------- 写侧:scope 判定链 ----------


def _rows_of(factory, user: str) -> list[LongMemoryFact]:
    async def _q() -> list[LongMemoryFact]:
        from sqlalchemy import select

        async with factory() as session:
            rows = (
                (await session.execute(select(LongMemoryFact).where(LongMemoryFact.user_id == user)))
                .scalars()
                .all()
            )
            return [(r.scope, r.business_id) for r in rows]

    return asyncio.run(_q())


def test_写侧_商户上下文非生理特征落tenant(clean_facts):
    factory = clean_facts
    with _fake_embedding_model():
        asyncio.run(LongMemory("CUST-W1", "nike").extract_and_store_fact("user prefers Nike Flyknit"))
    assert _rows_of(factory, "CUST-W1") == [("tenant", "nike")]


def test_写侧_生理特征在商户上下文仍落global(clean_facts):
    """脚长/过敏等客观事实跨商户通用,即便在 nike 会话中也归 global(business_id 空)。"""
    factory = clean_facts
    with _fake_embedding_model():
        asyncio.run(LongMemory("CUST-W2", "nike").extract_and_store_fact("fact: 用户脚长 270mm"))
    assert _rows_of(factory, "CUST-W2") == [("global", None)]


def test_写侧_显式声明优先于推断(clean_facts):
    factory = clean_facts
    with _fake_embedding_model():
        asyncio.run(
            LongMemory("CUST-W3", "ecommerce").extract_and_store_fact(
                "user prefers 会员积分兑换",
                explicit_scope="tenant",
                explicit_business_id="adidas",
            )
        )
    assert _rows_of(factory, "CUST-W3") == [("tenant", "adidas")]


def test_写侧_平台默认上下文非生理特征落global(clean_facts):
    factory = clean_facts
    with _fake_embedding_model():
        asyncio.run(LongMemory("CUST-W4", "ecommerce").extract_and_store_fact("user prefers 顺丰快递"))
    assert _rows_of(factory, "CUST-W4") == [("global", None)]
