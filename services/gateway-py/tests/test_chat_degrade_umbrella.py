"""chat 受理降级伞契约(夜评 2026-10-07 #2):dispatch 两臂 sync/async 同伞 ——
受理脊(chat_turn.accept_chat_turn:用户行 append/暂停闸/建作业)任何残余异常
都以 200 + 诚实道歉信封降级,严禁 HTTP 500 裸堆栈(上游 429 实测教训)。
8b72a08 上收受理脊时 async 臂漏伞,本册钉死两臂同形。"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from gateway_py.main import app

TENANT = {"x-tenant-id": "ecommerce"}
APOLOGY_FRAGMENT = "上游模型波动"


@pytest.fixture()
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.fixture()
def raise_accept(monkeypatch):
    """桩受理脊:无论何参一律炸(append/闸/建作业任一环残余异常的最坏形态)。"""

    def _patch(exc: Exception) -> None:
        async def _boom(*args, **kwargs):
            raise exc

        monkeypatch.setattr("gateway_py.chat_turn.accept_chat_turn", _boom)

    return _patch


async def _post(client: AsyncClient, body: dict):
    return await client.post("/api/chat", headers=TENANT, json=body)


async def test_sync_arm_degrades_with_apology(client, raise_accept):
    raise_accept(RuntimeError("db down"))
    res = await _post(client, {"message": "在吗", "sync": True})
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["jobId"] == ""
    assert APOLOGY_FRAGMENT in body["output"]


async def test_async_arm_degrades_with_apology(client, raise_accept):
    """async 臂同伞(8b72a08 漏伞补齐):受理脊炸也 200 + 道歉,不裸 500。"""
    raise_accept(RuntimeError("db down"))
    res = await _post(client, {"message": "在吗", "sync": False})
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["jobId"] == ""
    assert APOLOGY_FRAGMENT in body["output"]
    assert APOLOGY_FRAGMENT in body["result"]
