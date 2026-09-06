"""限流契约 — 租户+IP 双维 Redis 滑动窗口(wayfinder 002)。

覆盖:窗口滑动(合成时钟直打 Lua 判定)、双维独立计数、超限 429 形状与
Retry-After、SPI 独立配额、限流先于路由鉴权生效、非限流路径不受影响。
"""

import uuid

import pytest
from fastapi import Request

from gateway_py.rate_limit import _allow, _client_ip


@pytest.fixture(autouse=True)
def _isolated_key_prefix(monkeypatch):
    """每测独立键前缀:共享 Redis 下避免上一测的计数残留毒化本测阈值。"""
    prefix = f"rltest:{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("RATE_LIMIT_KEY_PREFIX", prefix)
    return prefix


class TestSlidingWindowAlgorithm:
    async def test_window_slides_with_synthetic_clock(self):
        # 限额 2 / 窗口 1000ms:窗口内第 3 次拒绝,最早一次滑出窗口后恢复放行
        assert await _allow(["sw:k"], [2], now_ms=0, window_ms=1000) == (True, 0)
        assert await _allow(["sw:k"], [2], now_ms=100, window_ms=1000) == (True, 0)
        blocked, retry = await _allow(["sw:k"], [2], now_ms=200, window_ms=1000)
        assert blocked is False
        assert retry >= 1  # 最早记录 t=0 滑出窗口还需 800ms → 向上取整 1s

        ok, _ = await _allow(["sw:k"], [2], now_ms=1001, window_ms=1000)
        assert ok is True  # t=0 已滑出,窗口内仅剩 t=100

    async def test_two_keys_count_independently(self):
        # 维度独立计数:一键耗尽配额,另一键仍享有完整窗口配额
        assert (await _allow(["sw:dim-a"], [1], now_ms=0, window_ms=1000))[0] is True
        assert (await _allow(["sw:dim-a"], [1], now_ms=1, window_ms=1000))[0] is False
        assert (await _allow(["sw:dim-b"], [1], now_ms=1, window_ms=1000))[0] is True

    async def test_multi_dimension_all_or_nothing(self):
        # 双维原子:租户维放行但 IP 维拒绝时,租户维不得计数(拒绝不进窗口)
        assert (await _allow(["ao:tenant", "ao:ip"], [2, 1], now_ms=0, window_ms=1000))[0] is True
        blocked, _ = await _allow(["ao:tenant", "ao:ip"], [2, 1], now_ms=1, window_ms=1000)
        assert blocked is False  # IP 维(限额 1)已满

        # 若非原子,租户维此刻已被计入 2 次;all-or-nothing 下应为 1 次 → 仍放行
        ok, _ = await _allow(["ao:tenant"], [2], now_ms=2, window_ms=1000)
        assert ok is True


class TestClientIpExtraction:
    """IP 采信规则:不可信直连不看 XFF;可信反代采信最右非可信跳。"""

    @staticmethod
    def _request(peer: str, xff: str | None) -> Request:
        headers = [(b"x-forwarded-for", xff.encode())] if xff else []
        return Request(scope={"type": "http", "client": (peer, 1234), "headers": headers})

    def test_untrusted_peer_ignores_forged_xff(self):
        # 直连 peer 不在可信代理名单 → 伪造 XFF 无效,用真实 peer
        req = self._request("203.0.113.9", "1.1.1.1, 2.2.2.2")
        assert _client_ip(req) == "203.0.113.9"

    def test_trusted_proxy_takes_rightmost_untrusted_hop(self):
        # 本方反代(127.0.0.1)追加真实客户端 → 取最右非可信跳,左侧伪造段失效
        req = self._request("127.0.0.1", "fake-attacker-hop, 198.51.100.7, 127.0.0.1")
        assert _client_ip(req) == "198.51.100.7"


class TestRateLimitMiddleware:
    async def test_chat_burst_over_limit_returns_429(self, client, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_CHAT_TENANT_MAX", "3")
        monkeypatch.setenv("RATE_LIMIT_CHAT_IP_MAX", "99")
        headers = {"x-tenant-id": "rl-tenant"}
        for _ in range(3):
            res = await client.get("/api/chat/messages", headers=headers)
            assert res.status_code != 429

        blocked = await client.get("/api/chat/messages", headers=headers)
        assert blocked.status_code == 429
        assert blocked.json() == {"success": False, "error": "请求过于频繁，请稍后再试"}
        assert int(blocked.headers["retry-after"]) >= 1

    async def test_tenant_dimension_blocks_without_poisoning_other_tenants(self, client, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_CHAT_TENANT_MAX", "2")
        monkeypatch.setenv("RATE_LIMIT_CHAT_IP_MAX", "99")
        for _ in range(2):
            res = await client.get("/api/chat/messages", headers={"x-tenant-id": "rl-tenant-a"})
            assert res.status_code != 429

        # 租户维度耗尽 → 本租户 429
        assert (
            await client.get("/api/chat/messages", headers={"x-tenant-id": "rl-tenant-a"})
        ).status_code == 429
        # 换租户不受牵连(IP 维 99 未触顶)
        assert (
            await client.get("/api/chat/messages", headers={"x-tenant-id": "rl-tenant-b"})
        ).status_code != 429

    async def test_ip_dimension_blocks_tenant_rotation(self, client, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_CHAT_TENANT_MAX", "99")
        monkeypatch.setenv("RATE_LIMIT_CHAT_IP_MAX", "2")
        for tenant in ("rl-t1", "rl-t2"):
            res = await client.get("/api/chat/messages", headers={"x-tenant-id": tenant})
            assert res.status_code != 429

        # 同 IP 轮换租户绕不过 IP 维
        rotated = await client.get("/api/chat/messages", headers={"x-tenant-id": "rl-t3"})
        assert rotated.status_code == 429

    async def test_spi_scope_own_quota_and_precedes_auth(self, client, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_SPI_TENANT_MAX", "2")
        monkeypatch.setenv("RATE_LIMIT_SPI_IP_MAX", "99")
        for _ in range(2):
            # 无合法凭证 → 401,但未到限额(证明限流与鉴权各司其职)
            res = await client.post(
                "/api/v1/spi/escalation/thread_rl/close",
                headers={"x-tenant-id": "rl-spi"},
                json={},
            )
            assert res.status_code != 429

        over = await client.post(
            "/api/v1/spi/escalation/thread_rl/close", headers={"x-tenant-id": "rl-spi"}, json={}
        )
        assert over.status_code == 429  # 限流在路由鉴权之前生效

    async def test_non_scoped_route_never_limited(self, client, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_CHAT_TENANT_MAX", "1")
        monkeypatch.setenv("RATE_LIMIT_CHAT_IP_MAX", "1")
        for _ in range(5):
            assert (await client.get("/api/health")).status_code == 200

    async def test_forged_xff_cannot_rotate_ip_buckets(self, client, monkeypatch):
        # httpx ASGI peer 是 127.0.0.1(默认可信)——先清空可信名单模拟不可信直连:
        # 伪造 XFF 不产生新 IP 桶,IP 维照常耗尽
        monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXIES", "10.255.255.1")
        monkeypatch.setenv("RATE_LIMIT_CHAT_TENANT_MAX", "99")
        monkeypatch.setenv("RATE_LIMIT_CHAT_IP_MAX", "2")
        for fake_xff in ("1.1.1.1", "2.2.2.2"):
            res = await client.get(
                "/api/chat/messages", headers={"x-tenant-id": "rl-xff", "x-forwarded-for": fake_xff}
            )
            assert res.status_code != 429

        rotated = await client.get(
            "/api/chat/messages", headers={"x-tenant-id": "rl-xff", "x-forwarded-for": "3.3.3.3"}
        )
        assert rotated.status_code == 429  # 换 XFF 绕不过 IP 维

    async def test_admin_all_scope_skips_tenant_bucket(self, client, monkeypatch):
        # admin 无租户态被 TenantContext 默认为 "all" —— 非真实租户,不设租户桶
        monkeypatch.setenv("RATE_LIMIT_CHAT_TENANT_MAX", "1")
        monkeypatch.setenv("RATE_LIMIT_CHAT_IP_MAX", "99")
        headers = {"x-role": "admin"}
        for _ in range(3):
            res = await client.get("/api/chat/messages", headers=headers)
            assert res.status_code != 429  # 若误入租户桶,限额 1 下第 2 发必 429
