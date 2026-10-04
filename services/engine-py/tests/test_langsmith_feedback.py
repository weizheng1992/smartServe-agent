"""LangSmith 语义反馈遥测契约(P11,2026-10-03):httpx 客户端进程级复用。

旧实现每回合 `async with httpx.AsyncClient()` 新建连接池 + TLS 握手;
现 _get_langsmith_client 懒建单例(与 llm/chat lru_cache 单例同纪律)。
全程 MockTransport,不触网;fire-and-forget 纪律(上报失败静默)同册钉死。
"""

from __future__ import annotations

import importlib

import httpx
import pytest

run_agent_module = importlib.import_module("engine_py.run_agent")  # 包 __init__ 把 run_agent 重绑成函数,须取模块本体


@pytest.fixture()
def _reset_client():
    run_agent_module._langsmith_client = None
    yield
    run_agent_module._langsmith_client = None


@pytest.fixture()
def _api_key(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_API_KEY", "test-key")
    monkeypatch.setenv("LANGCHAIN_ENDPOINT", "https://smith.test")


def test_client_reused_across_calls(_reset_client, _api_key):
    """同进程两次上报复用同一客户端(1 个连接池,2×2 请求)。"""
    posts: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        posts.append(f"{request.url}@{id(request.headers.get('x-api-key'))}")
        return httpx.Response(200)

    transport = httpx.MockTransport(_handler)
    real_init = httpx.AsyncClient.__init__
    creations = {"n": 0}

    def _counting_init(self, *args, **kwargs):
        creations["n"] += 1
        kwargs.pop("transport", None)
        real_init(self, *args, transport=transport, **kwargs)

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(httpx.AsyncClient, "__init__", _counting_init)
        import asyncio

        asyncio.run(run_agent_module._report_langsmith_feedback(True, "ok"))
        asyncio.run(run_agent_module._report_langsmith_feedback(False, "bad"))
    finally:
        monkeypatch.undo()

    assert creations["n"] == 1, f"两次上报应复用一个客户端,实建 {creations['n']} 个"
    assert len(posts) == 4  # correctness + success × 2 回合


def test_no_api_key_skips_entirely(_reset_client, monkeypatch):
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    import asyncio

    asyncio.run(run_agent_module._report_langsmith_feedback(True, "ok"))
    assert run_agent_module._langsmith_client is None, "未配 key 不得创建客户端"


def test_report_failure_is_swallowed(_reset_client, _api_key):
    """fire-and-forget:上报异常静默(观测面不反噬回合收口)。"""

    def _handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("smith down")

    run_agent_module._langsmith_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    import asyncio

    asyncio.run(run_agent_module._report_langsmith_feedback(True, "ok"))  # 不抛即过
