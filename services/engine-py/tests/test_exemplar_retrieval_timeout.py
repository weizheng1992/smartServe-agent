"""exemplar 检索超时容灾与确定性排序(triage-review-remediation 工单05,2026-09-11)。

样本召回挂在 triage 主链上,LLM 例句服务拖慢时不能陪挂 —— 超时与异常同降级
空列表;检索查询带 created_at+id 双键确定性排序。本套钉死容灾行为(排序由
SQL 层保证,查询构造在 _search_relevant_exemplars_impl 内单测无 DB 不可行,
靠语句形状断言兜底)。
"""

from __future__ import annotations

import asyncio

from engine_py.triage import exemplar_service as svc


def test_timeout_degrades_to_empty_list(monkeypatch):
    """内层实现超过 EXEMPLAR_RETRIEVAL_TIMEOUT_SECONDS(默认 0.2s)→ 外层
    快速返回空列表,不陪挂。"""

    async def _slow_impl(*args, **kwargs):
        await asyncio.sleep(5.0)
        return [{"should": "not reach"}]

    monkeypatch.setattr(svc, "_search_relevant_exemplars_impl", _slow_impl)
    result = asyncio.run(
        asyncio.wait_for(svc.search_relevant_exemplars("ecommerce", "退货政策"), timeout=2.0)
    )
    assert result == []


def test_exception_degrades_to_empty_list(monkeypatch):
    async def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(svc, "_search_relevant_exemplars_impl", _boom)
    assert asyncio.run(svc.search_relevant_exemplars("ecommerce", "退货政策")) == []


def test_impl_query_orders_deterministically():
    """排序形状:实现源码携带 created_at/id 双键 order_by(确定性取最新 50)。"""
    import inspect

    src = inspect.getsource(svc._search_relevant_exemplars_impl)
    assert "created_at.desc()" in src and "id.desc()" in src, (
        "检索必须带 created_at+id 双键确定性排序,无序取 50 会令 prompt 上下文随物理行序抖动"
    )


if __name__ == "__main__":
    import pytest

    pytest.main([__file__])
