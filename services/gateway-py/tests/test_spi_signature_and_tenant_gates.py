"""SPI HMAC 强制 + 多租户属主闸回归(2026-10-02 gateway-py 全量 code-review,
.scratch/gateway-py-review-2026-10/issues 01-05)。

钉死五面:
① /spi/v1 四条 GET 此前 require_signature=False 免签名放行(商户订单/用户
   PII 裸奔,违背 tools-registry §1.2、对不上 merchant-onboarding-guide 已
   宣称的验签防护)—— 现强制 HMAC:未签名 401/坏签 401/过期戳 401/签名放行;
② nonce 防重放:同一 nonce+签名 300s 窗口内第二次必须 401(此前收而不查重);
③ /api/store/chat/stream 属主闸:此前仅凭 threadId 即订阅 pub/sub 听他会话
   实时流 —— 未注册租户 403/查无线程 404/他租线程 403/属主 200 首帧 connected;
④ get_conversation_timeline 自愈收口:「ecommerce 图章/租户名是 threadId
   子串即改判归属」两条夺权路径封死 —— 跨租户一律隔离为空且不落 UPDATE
   (threads.business_id NOT NULL,「无主认领」本无从发生);
⑤ guardrail PUT/DELETE 租户所有权闸 + /api/v1/spi escalation 缺 x-tenant-id 400。
"""

from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import text

from .conftest import create_thread

pytestmark = pytest.mark.usefixtures("seeded")

_SPI_SECRET = "test-spi-secret-2026"
_API_KEY = "test_spi_key"  # SPI_API_KEYS 缺省静态集(spi.py)

_SPI_GET_PATHS = (
    "/spi/v1/products/search",
    "/spi/v1/user/info",
    "/spi/v1/orders/list",
    "/spi/v1/orders/detail",
)


def _signed_headers(method: str, path: str, secret: str = _SPI_SECRET, nonce: str | None = None, ts: str | None = None) -> dict:
    from gateway_py.hmac_signer import sign

    ts = ts or str(int(time.time() * 1000))
    nonce = nonce or uuid.uuid4().hex
    return {
        "x-signature": sign(secret, method, path, ts, nonce, ""),
        "x-timestamp": ts,
        "x-nonce": nonce,
    }


class TestSpiSignatureEnforcement:
    @pytest.mark.parametrize("path", _SPI_GET_PATHS)
    async def test_unsigned_get_rejected_401(self, client, monkeypatch, path: str):
        monkeypatch.setenv("MERCHANT_API_SECRET", _SPI_SECRET)
        res = await client.get(path)
        assert res.status_code == 401
        body = res.json()
        assert body["success"] is False
        assert "signature" in body["message"]

    async def test_signed_products_search_passes(self, client, monkeypatch):
        monkeypatch.setenv("MERCHANT_API_SECRET", _SPI_SECRET)
        res = await client.get("/spi/v1/products/search", headers=_signed_headers("GET", "/spi/v1/products/search"))
        assert res.status_code == 200
        assert res.json()["success"] is True

    async def test_wrong_secret_rejected_401(self, client, monkeypatch):
        monkeypatch.setenv("MERCHANT_API_SECRET", _SPI_SECRET)
        headers = _signed_headers("GET", "/spi/v1/products/search", secret="attacker-secret")
        res = await client.get("/spi/v1/products/search", headers=headers)
        assert res.status_code == 401
        assert "Invalid HMAC" in res.json()["message"]

    async def test_stale_timestamp_beyond_300s_rejected(self, client, monkeypatch):
        monkeypatch.setenv("MERCHANT_API_SECRET", _SPI_SECRET)
        stale_ts = str(int(time.time() * 1000) - 301_000)
        headers = _signed_headers("GET", "/spi/v1/orders/detail", ts=stale_ts)
        res = await client.get("/spi/v1/orders/detail", params={"orderId": "X"}, headers=headers)
        assert res.status_code == 401
        assert "expired" in res.json()["message"]

    async def test_replayed_nonce_rejected_within_window(self, client, monkeypatch):
        """签名有效但 nonce 已消费 → 401(防重放:此前同签名 300s 内可无限重放)。"""
        monkeypatch.setenv("MERCHANT_API_SECRET", _SPI_SECRET)
        path = "/spi/v1/orders/detail"
        headers = _signed_headers("GET", path, nonce="replay-fixed-nonce-0001")
        first = await client.get(path, params={"orderId": "REPLAY-1"}, headers=headers)
        assert first.status_code != 401, "首刷必须过验签(业务 404 可)"
        second = await client.get(path, params={"orderId": "REPLAY-1"}, headers=headers)
        assert second.status_code == 401
        assert "Replayed" in second.json()["message"]


class TestStoreStreamTenantGate:
    async def _mk(self, business_id: str) -> str:
        tid = f"stream_gate_{uuid.uuid4().hex[:8]}"
        await create_thread(tid, "u_stream_gate", business_id)
        return tid

    async def test_unregistered_tenant_rejected_403(self, client):
        res = await client.get(
            "/api/store/chat/stream", params={"threadId": "whatever", "businessId": "ghost-mall"}
        )
        assert res.status_code == 403
        assert "未入驻" in res.json()["error"]

    async def test_foreign_tenant_stream_rejected_403(self, client):
        tid = await self._mk("nike")
        res = await client.get("/api/store/chat/stream", params={"threadId": tid, "businessId": "adidas"})
        assert res.status_code == 403
        assert "不属于" in res.json()["error"]

    async def test_default_tenant_no_longer_anonymous(self, client):
        """缺省(aurora)不再是匿名通行证:nike 线程必 403 —— 无论 aurora 此时
        是否已注册(注册闸或属主闸,两道都该拦)。"""
        tid = await self._mk("nike")
        res = await client.get("/api/store/chat/stream", params={"threadId": tid})
        assert res.status_code == 403

    async def test_missing_thread_404(self, client):
        res = await client.get(
            "/api/store/chat/stream", params={"threadId": "no_such_thread_xyz", "businessId": "adidas"}
        )
        assert res.status_code == 404

    async def test_owner_stream_connects_with_connected_frame(self, live_server):
        """属主订阅放行:首帧 event: connected。走 live_server 真网络栈 ——
        httpx ASGITransport 会缓冲完整响应体,无限 SSE 流永远不吐字节
        (SSE 测试必须 live_server,gateway-py 测试基建既知坑位)。"""
        import httpx

        tid = await self._mk("adidas")
        async with (
            httpx.AsyncClient(timeout=10.0) as hc,
            hc.stream(
                "GET", f"{live_server}/api/store/chat/stream", params={"threadId": tid, "businessId": "adidas"}
            ) as res,
        ):
                assert res.status_code == 200
                assert res.headers["content-type"].startswith("text/event-stream")
                first = b""
                async for chunk in res.aiter_bytes():
                    first += chunk
                    if b"event: connected" in first:
                        break
                assert b"event: connected" in first


class TestTimelineSelfHeal:
    async def _business_id_of(self, tid: str) -> str | None:
        from engine_py.db import get_session

        async with get_session() as session:
            return (
                await session.execute(text("SELECT business_id FROM threads WHERE id = :t").bindparams(t=tid))
            ).scalar()

    async def test_cross_tenant_read_isolated_and_never_rewritten(self):
        """id 含 'aurora' 子串的 nike 线程 × aurora 请求:必须隔离为空且库内
        属主原封不动(旧子串启发式会把线程改判给 aurora 并整段读出)。"""
        from gateway_py import conversation_repo

        tid = f"iso_aurora_bait_{uuid.uuid4().hex[:8]}"
        await create_thread(tid, "u_iso", "nike")
        assert await conversation_repo.get_conversation_timeline(tid, "aurora") is None
        assert await self._business_id_of(tid) == "nike"

    async def test_explicit_ecommerce_stamp_not_claimable(self):
        """显式 ecommerce 图章(web 聊天线程)不再可被他租认领。"""
        from gateway_py import conversation_repo

        tid = f"iso_ecom_{uuid.uuid4().hex[:8]}"
        await create_thread(tid, "u_iso", "ecommerce")
        assert await conversation_repo.get_conversation_timeline(tid, "adidas") is None
        assert await self._business_id_of(tid) == "ecommerce"

    async def test_same_tenant_read_unchanged(self):
        """阳性对照:属主等值请求照常整段读出(收口只杀跨租户,不动正常路径)。"""
        from gateway_py import conversation_repo

        tid = f"iso_own_{uuid.uuid4().hex[:8]}"
        await create_thread(tid, "u_iso", "adidas")
        timeline = await conversation_repo.get_conversation_timeline(tid, "adidas")
        assert timeline is not None
        assert timeline["thread"]["threadId"] == tid


class TestGuardrailTenantScope:
    async def test_cross_tenant_write_delete_rejected_404(self, client):
        create = await client.post(
            "/api/guardrails",
            headers={"x-tenant-id": "nike"},
            json={"ruleName": "隔离闸-禁词", "ruleType": "keyword", "pattern": "越权"},
        )
        assert create.status_code == 201
        rule_id = create.json()["data"]["id"]

        put_foreign = await client.put(
            f"/api/guardrails/{rule_id}", headers={"x-tenant-id": "adidas"}, json={"severity": "low"}
        )
        assert put_foreign.status_code == 404
        del_foreign = await client.delete(f"/api/guardrails/{rule_id}", headers={"x-tenant-id": "adidas"})
        assert del_foreign.status_code == 404

        put_own = await client.put(
            f"/api/guardrails/{rule_id}", headers={"x-tenant-id": "nike"}, json={"severity": "low"}
        )
        assert put_own.status_code == 200
        del_own = await client.delete(f"/api/guardrails/{rule_id}", headers={"x-tenant-id": "nike"})
        assert del_own.status_code == 200


class TestSpiEscalationTenantHeader:
    async def test_close_without_tenant_header_400(self, client):
        res = await client.post(
            "/api/v1/spi/escalation/no_such_thread/close", headers={"x-api-key": _API_KEY}, json={}
        )
        assert res.status_code == 400
        assert "x-tenant-id" in res.json()["detail"]

    async def test_reply_without_tenant_header_400(self, client):
        res = await client.post(
            "/api/v1/spi/escalation/no_such_thread/reply",
            headers={"x-api-key": _API_KEY},
            json={"message": "hi"},
        )
        assert res.status_code == 400

    async def test_close_with_owner_tenant_resolves(self, client):
        tid = f"spi_close_{uuid.uuid4().hex[:8]}"
        await create_thread(tid, "u_spi", "adidas")
        res = await client.post(
            f"/api/v1/spi/escalation/{tid}/close",
            headers={"x-api-key": _API_KEY, "x-tenant-id": "adidas"},
            json={},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "resolved"

    async def test_close_foreign_tenant_404(self, client):
        tid = f"spi_cross_{uuid.uuid4().hex[:8]}"
        await create_thread(tid, "u_spi", "adidas")
        res = await client.post(
            f"/api/v1/spi/escalation/{tid}/close",
            headers={"x-api-key": _API_KEY, "x-tenant-id": "nike"},
            json={},
        )
        assert res.status_code == 404
