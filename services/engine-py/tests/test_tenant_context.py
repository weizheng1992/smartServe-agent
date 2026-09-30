"""引擎侧租户上下文契约(A7 收口)。

此前 engine 进程没有租户上下文 —— 深层模块各自 ``or "ecommerce"`` 静默兜底,
显式租户断供时错绑主站且不留痕。收口后:入口(run_agent)注入,深层解析 =
显式参数 > 上下文 > 平台默认(响亮告警)。
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from engine_py.tenant import tenant_of_state
from engine_py.tenant_context import (
    PLATFORM_DEFAULT_BUSINESS_ID,
    current_business_id,
    reset_business_context,
    resolve_business_id,
    set_business_context,
)


@pytest.fixture(autouse=True)
def _clean_context():
    """每个用例独享干净上下文(测试同事件循环,防相互串染)。"""
    token = set_business_context(None)
    yield
    reset_business_context(token)


class TestResolver:
    def test_explicit_wins_over_context(self):
        set_business_context("nike")
        assert resolve_business_id("adidas") == "adidas"

    def test_context_used_when_no_explicit(self):
        set_business_context("nike")
        assert resolve_business_id(None) == "nike"
        assert resolve_business_id("") == "nike"
        assert resolve_business_id("  ") == "nike", "空白串视同未传"

    def test_platform_default_with_loud_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="engine_py.tenant_context"):
            resolved = resolve_business_id(None)
        assert resolved == PLATFORM_DEFAULT_BUSINESS_ID == "ecommerce"
        assert any("tenant-context" in r.getMessage() for r in caplog.records), "兜底必须响亮留痕"

    def test_explicit_ecommerce_is_not_flagged(self, caplog):
        """显式传主站是调用方的明确决定,不走兜底告警分支。"""
        with caplog.at_level(logging.WARNING, logger="engine_py.tenant_context"):
            assert resolve_business_id("ecommerce") == "ecommerce"
        assert not caplog.records

    def test_reset_restores_previous(self):
        outer = set_business_context("nike")
        inner = set_business_context("adidas")
        assert current_business_id() == "adidas"
        reset_business_context(inner)
        assert current_business_id() == "nike"
        reset_business_context(outer)
        assert current_business_id() is None


class TestPropagation:
    def test_child_task_inherits_context(self):
        """深层消费机制:run_agent 在协程内 set,asyncio 子任务继承副本。"""
        seen: dict = {}

        async def deep_site():
            seen["biz"] = current_business_id()

        async def entry():
            set_business_context("nike")
            await asyncio.create_task(deep_site())

        asyncio.run(entry())
        assert seen["biz"] == "nike"

    def test_sibling_task_not_polluted(self):
        """set 只影响本任务上下文副本 —— 不跨作业泄漏(契约钉死)。"""
        seen: dict = {}

        async def job_a():
            set_business_context("nike")

        async def job_b():
            seen["biz"] = current_business_id()

        async def both():
            await asyncio.gather(asyncio.create_task(job_a()), asyncio.create_task(job_b()))

        asyncio.run(both())
        assert seen["biz"] is None, "job_a 的注入不得泄漏进 job_b"


class TestDeepSites:
    def test_tenant_of_state_falls_back_to_context(self):
        set_business_context("nike")
        # 状态缺租户字段(手工构造状态/图中间节点直调)时吃入口真值
        assert tenant_of_state({"input": "你好"}) == "nike"

    def test_tenant_of_state_state_still_authority(self):
        set_business_context("nike")
        assert tenant_of_state({"business_id": "adidas"}) == "adidas"
        assert tenant_of_state({"business_config": {"businessId": "aurora"}}) == "aurora"

    def test_cold_start_no_raise(self):
        """不变量 #4:无状态无上下文也不抛,回平台默认。"""
        assert tenant_of_state({}) == "ecommerce"
        assert current_business_id() is None
