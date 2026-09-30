"""画像 Agent 审计路由与工具写路现状钉死(wayfinder persona-hardening 02)。

钉四组行为(全程桩 LLM/向量模型,零真实调用):
- 置信度红线路由(`_run_profile_audit`):<0.60 丢弃 / >=0.85 approved / 其余 pending,含 0.60/0.85 边界;
- 审计侧 scope 判定链:显式声明 > LLM 判定 > 生理特征正则 global > 商户上下文(非 ecommerce 即 tenant);
- JSON 解析容错:markdown 围栏剥壳可解析;非法 JSON 吞异常零落库;
- recordUserPreference 工具写路**现状钉死**:thread 上下文明明解析出 businessId,
  工具却整体丢弃 —— 落 DB 默认 scope=global + business_id NULL + source=regex_fallback
  (租户偏好误升全局画像、归因失真)。此为缺陷曝光用例,persona-hardening 04
  修复后翻转断言,勿当契约真值。

审计任务在产线经 extract_and_store_fact 的 fire-and-forget create_task 派生;
测试直调 `_run_profile_audit` 取确定性,不追逐后台任务时序。
"""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager

import pytest
from sqlalchemy import select, text

from engine_py.db import LongMemoryFact
from engine_py.memory.long_memory import LongMemory
from engine_py.tools_registry.order_domain import OrderDomainService


@pytest.fixture()
def clean_profile_tables(pg_factory):
    def _clean() -> None:
        async def _go() -> None:
            async with pg_factory() as session:
                await session.execute(text("DELETE FROM long_memory_facts"))
                await session.execute(text("DELETE FROM threads WHERE id LIKE 't-prof-%'"))
                await session.commit()

        asyncio.run(_go())

    _clean()
    return pg_factory


@contextmanager
def _fake_models(audit_payload: str | None = None):
    """桩 chat(audit JSON)+ embedding。audit_payload 为 None 时不桩 chat。"""
    from engine_py.memory import long_memory as lm
    from engine_py.tools_registry import order_domain as od

    class _StubEmbed:
        async def aembed_query(self, _text: str) -> list[float]:
            return [1.0, 0.0]

    class _Resp:
        content = audit_payload or ""

    class _StubChat:
        async def ainvoke(self, _prompt: str):
            return _Resp()

    orig_lm_emb, orig_lm_chat = lm.get_embedding_model, lm.get_chat_model
    orig_od_emb = od.get_embedding_model
    lm.get_embedding_model = lambda: _StubEmbed()
    od.get_embedding_model = lambda: _StubEmbed()
    if audit_payload is not None:
        lm.get_chat_model = lambda: _StubChat()
    try:
        yield
    finally:
        lm.get_embedding_model, lm.get_chat_model = orig_lm_emb, orig_lm_chat
        od.get_embedding_model = orig_od_emb


def _audit_payload(*facts: dict, has_new: bool = True) -> str:
    return json.dumps({"hasNewPreference": has_new, "extractedFacts": list(facts)}, ensure_ascii=False)


def _run_audit(user: str, business: str | None, **kwargs) -> None:
    asyncio.run(LongMemory(user, business)._run_profile_audit("顾客的提问", "客服的回答", **kwargs))


def _rows_of(factory, user: str) -> list[dict]:
    async def _q() -> list[dict]:
        async with factory() as session:
            rows = (
                (await session.execute(select(LongMemoryFact).where(LongMemoryFact.user_id == user)))
                .scalars()
                .all()
            )
            return [
                {
                    "scope": r.scope,
                    "business_id": r.business_id,
                    "status": r.status,
                    "confidence": r.confidence,
                    "source": r.source,
                    "fact": r.fact,
                    "type": r.type,
                }
                for r in rows
            ]

    return asyncio.run(_q())


# ---------- 置信度红线路由 ----------


def test_审计_置信低于红线丢弃(clean_profile_tables):
    factory = clean_profile_tables
    with _fake_models(_audit_payload({"fact": "偏好速干面料", "scope": "tenant", "confidence": 0.5})):
        _run_audit("CUST-A1", "nike")
    assert _rows_of(factory, "CUST-A1") == []


def test_审计_高置信含边界直批approved(clean_profile_tables):
    """>=0.85 approved;0.85 恰在批线上。"""
    factory = clean_profile_tables
    payload = _audit_payload(
        {"fact": "偏好 Nike Flyknit", "scope": "tenant", "confidence": 0.9},
        {"fact": "偏好 Alder 鞋垫", "scope": "tenant", "confidence": 0.85},
    )
    with _fake_models(payload):
        _run_audit("CUST-A2", "nike")
    rows = sorted(_rows_of(factory, "CUST-A2"), key=lambda r: r["confidence"])
    assert [(r["status"], r["confidence"]) for r in rows] == [("approved", 0.85), ("approved", 0.9)]


def test_审计_中置信含边界落pending(clean_profile_tables):
    """[0.60, 0.85) pending;0.60 恰在线内不入弃件。"""
    factory = clean_profile_tables
    payload = _audit_payload(
        {"fact": "疑似偏好轻量鞋面", "scope": "tenant", "confidence": 0.7},
        {"fact": "疑似偏好周末晨跑", "scope": "tenant", "confidence": 0.6},
    )
    with _fake_models(payload):
        _run_audit("CUST-A3", "nike")
    rows = sorted(_rows_of(factory, "CUST-A3"), key=lambda r: r["confidence"])
    assert [(r["status"], r["confidence"]) for r in rows] == [("pending", 0.6), ("pending", 0.7)]


def test_审计_无新偏好零写入(clean_profile_tables):
    factory = clean_profile_tables
    with _fake_models(_audit_payload(has_new=False)):
        _run_audit("CUST-A4", "nike")
    assert _rows_of(factory, "CUST-A4") == []


def test_审计_legacy字符串项容错(clean_profile_tables):
    """extractedFacts 退化为纯字符串数组:confidence 补 1.0、source 记 agent_audit_legacy。"""
    factory = clean_profile_tables
    payload = json.dumps({"hasNewPreference": True, "extractedFacts": ["偏好亚麻材质"]}, ensure_ascii=False)
    with _fake_models(payload):
        _run_audit("CUST-A5", "nike")
    rows = _rows_of(factory, "CUST-A5")
    assert len(rows) == 1
    row = rows[0]
    assert row["fact"] == "偏好亚麻材质"
    assert row["status"] == "approved" and row["confidence"] == 1.0
    assert row["source"] == "agent_audit_legacy"


# ---------- 审计侧 scope 判定链 ----------


def test_审计_scope_LLM判定生效(clean_profile_tables):
    factory = clean_profile_tables
    payload = _audit_payload({"fact": "偏好 Air Jordan 复刻", "scope": "tenant", "confidence": 0.9})
    with _fake_models(payload):
        _run_audit("CUST-S1", "nike")
    assert [(r["scope"], r["business_id"]) for r in _rows_of(factory, "CUST-S1")] == [("tenant", "nike")]


def test_审计_scope_显式声明压过LLM判定(clean_profile_tables):
    factory = clean_profile_tables
    payload = _audit_payload({"fact": "偏好某品牌联名款", "scope": "tenant", "confidence": 0.9})
    with _fake_models(payload):
        _run_audit("CUST-S2", "adidas", explicit_scope="global")
    assert [(r["scope"], r["business_id"]) for r in _rows_of(factory, "CUST-S2")] == [("global", None)]


def test_审计_scope_生理特征正则兜global(clean_profile_tables):
    """LLM 漏判 scope 时,生理特征(脚长)凭正则兜回 global —— 即便在 nike 会话。"""
    factory = clean_profile_tables
    payload = _audit_payload({"fact": "用户脚长 270mm", "confidence": 0.9})
    with _fake_models(payload):
        _run_audit("CUST-S3", "nike")
    assert [(r["scope"], r["business_id"]) for r in _rows_of(factory, "CUST-S3")] == [("global", None)]


def test_审计_scope_非电商商户缺scope落tenant(clean_profile_tables):
    factory = clean_profile_tables
    payload = _audit_payload({"fact": "偏好椰子鞋配色", "confidence": 0.9})
    with _fake_models(payload):
        _run_audit("CUST-S4", "adidas")
    assert [(r["scope"], r["business_id"]) for r in _rows_of(factory, "CUST-S4")] == [("tenant", "adidas")]


def test_审计_scope_平台上下文缺scope落global(clean_profile_tables):
    factory = clean_profile_tables
    payload = _audit_payload({"fact": "偏好次日达", "confidence": 0.9})
    with _fake_models(payload):
        _run_audit("CUST-S5", "ecommerce")
    assert [(r["scope"], r["business_id"]) for r in _rows_of(factory, "CUST-S5")] == [("global", None)]


# ---------- JSON 解析容错 ----------


def test_审计_markdown围栏剥壳可解析(clean_profile_tables):
    factory = clean_profile_tables
    inner = _audit_payload({"fact": "偏好羊毛混纺", "scope": "tenant", "confidence": 0.88})
    with _fake_models(f"```json\n{inner}\n```"):
        _run_audit("CUST-J1", "nike")
    assert len(_rows_of(factory, "CUST-J1")) == 1


def test_审计_非法JSON吞异常零落库(clean_profile_tables):
    """模型输出散文(围栏剥离后仍非 JSON):异常在函数内吞掉,零落库零上抛。"""
    factory = clean_profile_tables
    with _fake_models("这不是一段 JSON,模型抽风了"):
        _run_audit("CUST-J2", "nike")  # 不抛即过
    assert _rows_of(factory, "CUST-J2") == []


# ---------- 正则容灾路径归因钉死 ----------


def test_正则容灾_归因字段钉死(clean_profile_tables):
    """prefers 前缀行直批入库:source=regex_fallback / confidence=1.0 / approved /
    type=preference;fact 保留整行(仅剥 fact: 前缀,user prefers 前缀不剥)。"""
    factory = clean_profile_tables
    with _fake_models():
        asyncio.run(LongMemory("CUST-R1", "nike").extract_and_store_fact("user prefers 落日橙配色"))
    rows = _rows_of(factory, "CUST-R1")
    assert len(rows) == 1
    row = rows[0]
    assert row["fact"] == "user prefers 落日橙配色"
    assert (row["source"], row["confidence"], row["status"], row["type"]) == ("regex_fallback", 1.0, "approved", "preference")
    assert (row["scope"], row["business_id"]) == ("tenant", "nike")


# ---------- recordUserPreference 工具写路现状(缺陷曝光,04 翻转) ----------


def _seed_thread(factory, thread_id: str, user_id: str | None, business_id: str) -> None:
    async def _go() -> None:
        async with factory() as session:
            await session.execute(
                text(
                    'INSERT INTO threads (id, user_id, business_id) VALUES (:tid, :uid, :bid)'
                ).bindparams(tid=thread_id, uid=user_id, bid=business_id)
            )
            await session.commit()

    asyncio.run(_go())


def test_工具写路_现状_线程租户上下文被整体丢弃(clean_profile_tables):
    """缺陷钉死:thread 会话明明白白解析出 user+businessId(nike),工具写
    LongMemoryFact 却不带 scope/business_id/status/source —— 落 DB 默认
    global+NULL+approved,source 误借 regex_fallback。租户内偏好被误升全局
    画像且归因失真。persona-hardening 04 修复后本断言翻转为
    (tenant, nike, source=tool_record 或同义归因)。"""
    factory = clean_profile_tables
    _seed_thread(factory, "t-prof-ctx", "CUST-T1", "nike")
    with _fake_models():
        res = asyncio.run(OrderDomainService.record_user_preference("color", "黑色", thread_id="t-prof-ctx"))
    assert res.get("success") is True, res
    rows = _rows_of(factory, "CUST-T1")
    assert len(rows) == 1
    row = rows[0]
    assert row["fact"] == "[User color preference]: 黑色"
    # —— 缺陷三连(04 翻转点)——
    assert (row["scope"], row["business_id"]) == ("global", None)
    assert row["source"] == "regex_fallback"


def test_工具写路_缺threadId拒绝(clean_profile_tables):
    res = asyncio.run(OrderDomainService.record_user_preference("color", "黑色", thread_id=None))
    assert "error" in res and "threadId" in res["error"]


def test_工具写路_匿名线程拒绝(clean_profile_tables):
    factory = clean_profile_tables
    _seed_thread(factory, "t-prof-anon", None, "nike")
    res = asyncio.run(OrderDomainService.record_user_preference("color", "黑色", thread_id="t-prof-anon"))
    assert "error" in res and "user context" in res["error"]
    assert _rows_of(factory, "CUST-T2") == []
