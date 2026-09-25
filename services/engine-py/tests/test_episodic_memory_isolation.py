"""情境记忆专项回归(memory/episodic_memory.py,钉死 .claude/rules/agent-engine.md §1.4 双层隔离)。

读侧(``retrieve_events``):
- _tenant_visible 矩阵:scope=global(或空)全商户放行;scope=tenant 归属商户可见,
  竞品与平台默认上下文(ecommerce/无)不放行具名租户事件;未知 scope 一律不可见;
- 混合评分:max(余弦, 关键词×0.95),阈值 0.55 —— 词不命中可被向量补位,向量不命中
  可被关键词补位,双空诚实空;
- 输出 camelCase 事件形(importanceScore 缺省 3 / scope 空缺补 global / timestamp 可空);
- 冷启动诚实空(无 userId / 空表 / DB 失败),写侧失败静默不炸会话。

写侧(``add_event`` 的 scope→business_id 判定链):
显式参数 > 构造上下文 > 平台缺省 ecommerce;global 一律 business_id 落空。

检索走 ``precomputed_embedding`` 注入、写侧打桩 embedding 模型,全程零 LLM/零向量模型。
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime

import pytest
from sqlalchemy import select, text

from engine_py.db import EpisodicEventRow
from engine_py.memory.episodic_memory import EpisodicMemory

_EMB = json.dumps([1.0, 0.0])  # 与查询侧 precomputed [1,0] 余弦=1,必过 0.55 阈值
_ORTHOGONAL_EMB = json.dumps([0.0, 1.0])  # 余弦=0,关键词补位/双空用例专用

_BASE_TS = datetime(2026, 9, 1, 12, 0, 0)  # noqa: DTZ001 — episodic_events.timestamp 是 naive DateTime 列


@pytest.fixture()
def clean_events(pg_factory):
    asyncio.run(_clean(pg_factory))
    return pg_factory


@contextmanager
def _fake_embedding_model():
    """add_event 的写侧向量化打桩(检索侧用 precomputed_embedding 不经过此)。"""
    from engine_py.memory import episodic_memory as em

    class _StubModel:
        async def aembed_query(self, _text: str) -> list[float]:
            return [1.0, 0.0]

    original = em.get_embedding_model
    em.get_embedding_model = lambda: _StubModel()
    try:
        yield
    finally:
        em.get_embedding_model = original


@contextmanager
def _broken_db_session():
    """get_session 打桩成连接即炸,钉死 DB 失败的诚实降级路径。"""
    from engine_py.memory import episodic_memory as em

    @asynccontextmanager
    async def _boom():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    original = em.get_session
    em.get_session = lambda: _boom()
    try:
        yield
    finally:
        em.get_session = original


async def _clean(factory) -> None:
    async with factory() as session:
        await session.execute(text("DELETE FROM episodic_events"))
        await session.commit()


def _mk_event(
    *,
    user: str = "CUST-P1",
    scope: str = "tenant",
    business: str | None = None,
    content: str = "用户咨询了退款进度",
    embedding: str = _EMB,
    importance: int | None = 5,
    ts: datetime = _BASE_TS,
) -> EpisodicEventRow:
    return EpisodicEventRow(
        user_id=user,
        business_id=business,
        scope=scope,
        content=content,
        embedding=embedding,
        importance=importance,
        timestamp=ts,
    )


async def _insert(factory, *events: EpisodicEventRow) -> None:
    async with factory() as session:
        for e in events:
            session.add(e)
        await session.commit()


def _contents_of(result: list[dict]) -> set[str]:
    return {item["event"] for item in result}


async def _retrieve(mem: EpisodicMemory, query: str = "退款 进度", limit: int = 3) -> list[dict]:
    return await mem.retrieve_events(query, limit=limit, precomputed_embedding=[1.0, 0.0])


def _rows_of(factory, user: str) -> list[tuple]:
    async def _q() -> list[tuple]:
        async with factory() as session:
            rows = (
                (await session.execute(select(EpisodicEventRow).where(EpisodicEventRow.user_id == user)))
                .scalars()
                .all()
            )
            return [(r.scope, r.business_id, r.importance, r.content) for r in rows]

    return asyncio.run(_q())


# ---------- 读侧:作用域可见性 ----------


def test_global事件跨租户可见(clean_events):
    """scope=global 事件对所有商户上下文放行。"""
    factory = clean_events
    asyncio.run(_insert(factory, _mk_event(scope="global", business=None, content="用户凌晨申请了全额退款")))

    for ctx in ("nike", "adidas", "ecommerce", None):
        mem = EpisodicMemory("CUST-P1", ctx)
        result = asyncio.run(_retrieve(mem))
        assert "用户凌晨申请了全额退款" in _contents_of(result), f"global 事件在上下文 {ctx} 不可见"


def test_tenant事件竞品与平台均不可见(clean_events):
    """scope=tenant 事件:归属商户可见,竞品与平台默认上下文均不可见(防跨租户泄漏)。"""
    factory = clean_events
    asyncio.run(
        _insert(
            factory,
            _mk_event(scope="tenant", business="nike", content="nike 门店咨询了换货"),
            _mk_event(scope="tenant", business="adidas", content="adidas 门店咨询了换货"),
        )
    )

    nike_view = _contents_of(asyncio.run(_retrieve(EpisodicMemory("CUST-P1", "nike"))))
    assert "nike 门店咨询了换货" in nike_view
    assert "adidas 门店咨询了换货" not in nike_view

    adidas_view = _contents_of(asyncio.run(_retrieve(EpisodicMemory("CUST-P1", "adidas"))))
    assert "adidas 门店咨询了换货" in adidas_view
    assert "nike 门店咨询了换货" not in adidas_view

    # 平台默认上下文(ecommerce / 无)两条具名租户事件都看不到
    for ctx in ("ecommerce", None):
        platform_view = _contents_of(asyncio.run(_retrieve(EpisodicMemory("CUST-P1", ctx))))
        assert platform_view == set(), f"平台上下文 {ctx} 泄漏了具名租户事件"


def test_平台上下文仅见无主与自营事件(clean_events):
    """tenant 事件在平台默认上下文下:business_id 空缺/ecommerce 放行,具名租户拦截。"""
    factory = clean_events
    asyncio.run(
        _insert(
            factory,
            _mk_event(scope="tenant", business=None, content="平台客服协助了退款"),
            _mk_event(scope="tenant", business="ecommerce", content="自营店完成了补发"),
            _mk_event(scope="tenant", business="nike", content="nike 完成了补发"),
        )
    )

    view = _contents_of(asyncio.run(_retrieve(EpisodicMemory("CUST-P1", "ecommerce"))))
    assert view == {"平台客服协助了退款", "自营店完成了补发"}


def test_未知scope事件一律不可见(clean_events):
    """_tenant_visible 的未知 scope 分支:宁可漏收不可错收。"""
    factory = clean_events
    asyncio.run(_insert(factory, _mk_event(scope="archived", business=None, content="历史归档事件")))

    for ctx in ("nike", "ecommerce", None):
        assert asyncio.run(_retrieve(EpisodicMemory("CUST-P1", ctx))) == []


def test_跨用户事件隔离(clean_events):
    """事件按 user_id 物理隔离:他人的 global 事件也不得召回。"""
    factory = clean_events
    asyncio.run(_insert(factory, _mk_event(user="CUST-P2", scope="global", content="他人退款事件")))

    assert asyncio.run(_retrieve(EpisodicMemory("CUST-P1", "nike"))) == []


# ---------- 读侧:混合评分与阈值 ----------


def test_关键词命中补位向量缺位(clean_events):
    """正交向量(余弦=0)+ 全量关键词命中 → 0.95 ≥ 0.55,召回(关键词通道钉死)。"""
    factory = clean_events
    asyncio.run(
        _insert(
            factory,
            _mk_event(scope="global", content="用户咨询了退款进度", embedding=_ORTHOGONAL_EMB),
        )
    )

    view = _contents_of(asyncio.run(_retrieve(EpisodicMemory("CUST-P1", "nike"), query="退款 进度")))
    assert view == {"用户咨询了退款进度"}


def test_部分关键词命中低于阈值不召回(clean_events):
    """两词元仅中一个 → 0.475 < 0.55,且余弦=0,双通道皆不足即诚实空。"""
    factory = clean_events
    asyncio.run(
        _insert(
            factory,
            _mk_event(scope="global", content="用户咨询了退款进度", embedding=_ORTHOGONAL_EMB),
        )
    )

    view = asyncio.run(_retrieve(EpisodicMemory("CUST-P1", "nike"), query="退款 发票"))
    assert view == []


def test_余弦命中补位关键词缺位(clean_events):
    """向量余弦=1 而查询词元零命中 → 1.0 ≥ 0.55,召回(max 合流钉死)。"""
    factory = clean_events
    asyncio.run(_insert(factory, _mk_event(scope="global", content="夜间下单已经成为习惯")))

    view = _contents_of(asyncio.run(_retrieve(EpisodicMemory("CUST-P1", "nike"), query="尺码推荐")))
    assert view == {"夜间下单已经成为习惯"}


def test_双通道双空诚实空(clean_events):
    """正交向量且无关键词命中 → effective_score=0 < 0.55,过滤(阈值行为钉死)。"""
    factory = clean_events
    asyncio.run(_insert(factory, _mk_event(content="用户喜欢凌晨下单", embedding=_ORTHOGONAL_EMB)))

    assert asyncio.run(_retrieve(EpisodicMemory("CUST-P1", "nike"), query="尺码推荐")) == []


def test_limit截取按相似度降序(clean_events):
    """阈值上多事件时按 effective_score 降序取 limit 条(纯余弦 1.0 > 纯关键词 0.95)。"""
    factory = clean_events
    asyncio.run(
        _insert(
            factory,
            _mk_event(scope="global", content="用户咨询了退款进度", embedding=_ORTHOGONAL_EMB),
            _mk_event(scope="global", content="夜间下单已经成为习惯"),
        )
    )

    result = asyncio.run(_retrieve(EpisodicMemory("CUST-P1", "nike"), query="退款", limit=1))
    assert [item["event"] for item in result] == ["夜间下单已经成为习惯"]

    full = asyncio.run(_retrieve(EpisodicMemory("CUST-P1", "nike"), query="退款", limit=5))
    assert [item["event"] for item in full] == ["夜间下单已经成为习惯", "用户咨询了退款进度"]


# ---------- 读侧:输出形与冷启动 ----------


def test_输出camelCase形与缺省补齐(clean_events):
    """事件形钉死:importanceScore 缺省 3 / scope 空缺补 global / timestamp ISO 回读。"""
    factory = clean_events
    asyncio.run(
        _insert(
            factory,
            _mk_event(scope="global", content="缺省字段事件", importance=None),
        )
    )

    result = asyncio.run(_retrieve(EpisodicMemory("CUST-P1", "nike")))
    assert len(result) == 1
    event = result[0]
    assert set(event.keys()) == {"id", "event", "importanceScore", "timestamp", "embedding", "scope", "businessId"}
    assert event["importanceScore"] == 3
    assert event["scope"] == "global"
    assert event["timestamp"] == _BASE_TS.isoformat()
    assert event["businessId"] is None
    assert event["embedding"] == [1.0, 0.0]


def test_importance分级落库与回读(clean_events):
    """重要性 1-10 落库并按原值回读。"""
    factory = clean_events
    asyncio.run(_insert(factory, _mk_event(scope="global", content="重大投诉事件", importance=9)))

    result = asyncio.run(_retrieve(EpisodicMemory("CUST-P1", "nike")))
    assert result[0]["importanceScore"] == 9


def test_冷启动诚实空(clean_events):
    """无 userId 与空表均返回 [],不抛错(无异常冷启动准则)。"""
    assert asyncio.run(EpisodicMemory("").retrieve_events("退款", precomputed_embedding=[1.0, 0.0])) == []

    result = asyncio.run(_retrieve(EpisodicMemory("CUST-NEVER-SEEN", "nike")))
    assert result == []


def test_db失败读侧诚实空写侧静默(clean_events):
    """DB 不可达:读侧 [] / 写侧吞错不炸会话,两者都不 raise。"""
    factory = clean_events
    with _broken_db_session():
        assert asyncio.run(_retrieve(EpisodicMemory("CUST-P1", "nike"))) == []
        with _fake_embedding_model():
            asyncio.run(EpisodicMemory("CUST-P1", "nike").add_event("写入应被吞", 5))
    assert _rows_of(factory, "CUST-P1") == []


def test_写侧无userId不落库(clean_events):
    factory = clean_events
    with _fake_embedding_model():
        asyncio.run(EpisodicMemory("").add_event("无主事件", 5))
    assert _rows_of(factory, "") == []


# ---------- 写侧:scope→business_id 判定链 ----------


def test_写侧_显式business_id优先于上下文(clean_events):
    factory = clean_events
    with _fake_embedding_model():
        asyncio.run(EpisodicMemory("CUST-W1", "nike").add_event("adidas 侧事件", 5, business_id="adidas"))
    assert _rows_of(factory, "CUST-W1") == [("tenant", "adidas", 5, "adidas 侧事件")]


def test_写侧_商户上下文回落(clean_events):
    factory = clean_events
    with _fake_embedding_model():
        asyncio.run(EpisodicMemory("CUST-W2", "nike").add_event("上下文归属事件", 5))
    assert _rows_of(factory, "CUST-W2") == [("tenant", "nike", 5, "上下文归属事件")]


def test_写侧_平台缺省ecommerce(clean_events):
    factory = clean_events
    with _fake_embedding_model():
        asyncio.run(EpisodicMemory("CUST-W3", None).add_event("无上下文事件", 5))
    assert _rows_of(factory, "CUST-W3") == [("tenant", "ecommerce", 5, "无上下文事件")]


def test_写侧_global事件business_id一律落空(clean_events):
    """scope=global 时即便显式携带 business_id 也落 NULL(跨商户通用语义)。"""
    factory = clean_events
    with _fake_embedding_model():
        asyncio.run(EpisodicMemory("CUST-W4", "nike").add_event("生理性事件", 5, scope="global", business_id="nike"))
    assert _rows_of(factory, "CUST-W4") == [("global", None, 5, "生理性事件")]
