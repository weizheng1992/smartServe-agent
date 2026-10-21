"""用量配额闸契约(2026-10-21,spec .scratch/agent-usage-quota,票 02/03)。

钉面:游客终身上限 / IP 日顶(all-or-nothing,拒绝不占名额)/ 用户日顶 /
商户池耗尽 / kill switch / Redis fail-open / 拒轮不落用户行 / web 面强制
JWT(401/403)。闸在密封套件缺省关(conftest AI_QUOTA_GATE=0),本册逐测
monkeypatch 开启并以唯一键前缀自隔离。
"""

from __future__ import annotations

import os
import uuid

import pytest
from engine_py.credits import get_balance
from engine_py.event_bus import get_client as get_redis

from gateway_py import quota

from .conftest import user_auth

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _biz() -> str:
    return f"qgate_{uuid.uuid4().hex[:10]}"


async def _seed_tenant(business_id: str) -> None:
    from engine_py.db import get_session
    from sqlalchemy import text

    async with get_session() as session:
        await session.execute(
            text(
                "INSERT INTO tenants (id, business_id, name, plan_tier, status) "
                "VALUES (gen_random_uuid(), :bid, :name, 'free', 'active') "
                "ON CONFLICT (business_id) DO NOTHING"
            ).bindparams(bid=business_id, name=f"配额测试 {business_id}")
        )
        await session.commit()


@pytest.fixture()
def stub_run_agent(monkeypatch):
    """桩引擎:闸测试只关心受理脊语义,LLM 全链(含降级)与本册无关。"""

    async def _fake(job):
        return {"output": "好的", "cards": [], "task_plan": {}}

    monkeypatch.setattr("gateway_py.chat_turn.run_agent", _fake)


@pytest.fixture()
def gate_on(monkeypatch):
    """逐测开闸 + 唯一键前缀(测试间零串扰,与既有测试零串扰)。"""
    monkeypatch.setenv("AI_QUOTA_GATE", "1")
    monkeypatch.setenv("AI_QUOTA_KEY_PREFIX", f"qgate_{uuid.uuid4().hex[:10]}")


async def _store_chat(client, *, user_id: str, business_id: str, message: str = "在吗"):
    return await client.post(
        "/api/store/chat",
        json={
            "message": message,
            "userId": user_id,
            "businessId": business_id,
            "threadId": f"qgate_{user_id}_{business_id}",
        },
    )


class TestStoreFaceGate:
    async def test_missing_user_id_rejected_400(self, client):
        """身份必报(评审修复):缺省回落 CUST-8801 会拿种子真客的登录日顶
        (嫁祸面)——与 cancel 闸同律,计费动作严禁落缺省身份。"""
        res = await client.post(
            "/api/store/chat",
            json={"message": "在吗", "businessId": "nike"},
        )
        assert res.status_code == 400
        assert res.json()["success"] is False

    async def test_guest_lifetime_limit(self, client, monkeypatch, gate_on, stub_run_agent):
        """第 11 次拒 QUOTA_GUEST_LIMIT;池恰好扣 10(拒轮不扣池)。"""
        biz = _biz()
        await _seed_tenant(biz)
        guest = f"guest-{biz}"
        for _ in range(10):
            res = await _store_chat(client, user_id=guest, business_id=biz)
            assert res.status_code == 200 and res.json()["success"] is True, res.text
        res = await _store_chat(client, user_id=guest, business_id=biz)
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is False
        assert body["quotaCode"] == quota.QUOTA_GUEST_LIMIT
        initial = int(os.environ.get("AI_MERCHANT_INITIAL_CREDITS", "1000"))
        assert await get_balance(biz) == initial - 10

    async def test_pool_exhaustion(self, client, monkeypatch, gate_on, stub_run_agent):
        """懒初始化赠 AI_MERCHANT_INITIAL_CREDITS;扣尽即 QUOTA_MERCHANT_EXHAUSTED。"""
        monkeypatch.setenv("AI_MERCHANT_INITIAL_CREDITS", "2")
        biz = _biz()
        await _seed_tenant(biz)
        for _ in range(2):
            res = await _store_chat(client, user_id=f"guest-{biz}", business_id=biz)
            assert res.json()["success"] is True
        res = await _store_chat(client, user_id=f"guest-{biz}", business_id=biz)
        body = res.json()
        assert body["success"] is False
        assert body["quotaCode"] == quota.QUOTA_MERCHANT_EXHAUSTED
        assert await get_balance(biz) == 0

    async def test_rejected_turn_persists_no_user_row(self, client, monkeypatch, gate_on, stub_run_agent):
        """D9:被拒问询不在消息历史里凭空出现(用户行 10,不含被拒轮)。"""
        monkeypatch.setenv("AI_GUEST_QUOTA", "2")
        biz = _biz()
        await _seed_tenant(biz)
        guest = f"guest-{biz}"
        thread_id = f"qgate_{guest}_{biz}"
        for _ in range(3):
            await _store_chat(client, user_id=guest, business_id=biz)
        from engine_py.db import get_session
        from sqlalchemy import text

        async with get_session() as session:
            count = (
                await session.execute(
                    text("SELECT COUNT(*) FROM messages WHERE thread_id = :t AND role = 'user'").bindparams(
                        t=thread_id
                    )
                )
            ).scalar()
        assert count == 2

    async def test_kill_switch_off_no_deduction(self, client, monkeypatch, stub_run_agent):
        """AI_QUOTA_GATE=0:整体关断,连账户行都不建(懒初始化不触达)。"""
        monkeypatch.setenv("AI_QUOTA_GATE", "0")
        biz = _biz()
        await _seed_tenant(biz)
        res = await _store_chat(client, user_id=f"guest-{biz}", business_id=biz)
        assert res.json()["success"] is True
        assert await get_balance(biz) is None


class TestCounterArms:
    """计数臂模块级钉面(真 Redis 密封容器,唯一前缀自隔离)。"""

    async def test_user_daily_cap(self, client, monkeypatch, gate_on):
        monkeypatch.setenv("AI_USER_DAILY", "2")
        for _ in range(2):
            assert (
                await quota._check_counters(user_id="u_d1", business_id="b1", client_ip="9.9.9.9")
            ).allowed is True
        verdict = await quota._check_counters(user_id="u_d1", business_id="b1", client_ip="9.9.9.9")
        assert verdict.allowed is False and verdict.code == quota.QUOTA_USER_DAILY

    async def test_ip_cap_all_or_nothing(self, monkeypatch, gate_on):
        """IP 顶拒时不烧游客终身名额(Lua DECR 自愈):g1 终身键恒 1。"""
        monkeypatch.setenv("AI_GUEST_QUOTA", "100")
        monkeypatch.setenv("AI_GUEST_IP_DAILY", "2")
        for g in ("guest-a", "guest-b"):
            assert (
                await quota._check_counters(user_id=g, business_id="b2", client_ip="9.9.9.9")
            ).allowed is True
        verdict = await quota._check_counters(user_id="guest-c", business_id="b2", client_ip="9.9.9.9")
        assert verdict.allowed is False and verdict.code == quota.QUOTA_IP_LIMIT
        redis = await get_redis()
        prefix = os.environ["AI_QUOTA_KEY_PREFIX"]
        # 事件总线 redis 客户端 decode_responses=True,GET 回 str
        assert await redis.get(f"{prefix}:guest:b2:guest-a") == "1"

    async def test_fail_open_on_redis_error(self, monkeypatch):
        """D7:计数臂故障 fail-open,池扣减仍在(资金路径不陪葬)。"""
        monkeypatch.setenv("AI_QUOTA_GATE", "1")

        async def _boom(*args, **kwargs):
            raise RuntimeError("redis down")

        monkeypatch.setattr("gateway_py.quota.get_redis", _boom)
        biz = _biz()
        verdict = await quota.check_and_consume(
            user_id="guest-x", business_id=biz, client_ip="1.2.3.4", job_id="j_failopen"
        )
        assert verdict.allowed is True
        assert await get_balance(biz) == int(os.environ.get("AI_MERCHANT_INITIAL_CREDITS", "1000")) - 1


class TestWebFaceJwt:
    """Q5b:web 面 /api/chat 强制 JWT(身份取 sub,自报字段仅交叉校验)。"""

    async def test_no_token_401(self, client):
        res = await client.post("/api/chat", json={"message": "在吗"})
        assert res.status_code == 401
        assert res.json()["success"] is False

    async def test_bad_token_401(self, client):
        res = await client.post(
            "/api/chat", headers={"Authorization": "Bearer not-a-jwt"}, json={"message": "在吗"}
        )
        assert res.status_code == 401

    async def test_user_mismatch_403(self, client):
        res = await client.post(
            "/api/chat",
            headers={**user_auth("u_real")},
            json={"message": "在吗", "userId": "CUST-8801"},
        )
        assert res.status_code == 403

    async def test_async_arm_quota_envelope(self, client, monkeypatch, gate_on, stub_run_agent):
        """日顶拒:async 信封带 quotaCode(前端可免开流短路),流上同码终局帧。"""
        monkeypatch.setenv("AI_USER_DAILY", "1")
        biz = _biz()
        await _seed_tenant(biz)
        headers = {**user_auth("u_web_qg"), "x-tenant-id": biz}
        body = {"message": "在吗", "sync": False, "userId": "u_web_qg", "businessId": biz}
        res = await client.post("/api/chat", headers=headers, json=body)
        assert res.status_code == 200
        first = res.json()
        assert first["success"] is True and "quotaCode" not in first
        res = await client.post("/api/chat", headers=headers, json=body)
        assert res.status_code == 200
        second = res.json()
        assert second["quotaCode"] == quota.QUOTA_USER_DAILY
        assert second["jobId"]
        # 流帧载体(Q4 修订):拒轮 result 终局帧带 quotaCode——web 异步臂主渲染
        # 路径消费的就是这个帧,tail 是哑泵(帧形由 realtime 契约册钉),此处钉
        # 事件流内容即可
        from engine_py.event_bus import read_agent_events

        events = await read_agent_events(second["jobId"])
        results = [e for e in events if e["type"] == "result"]
        assert results, "拒轮必须有 result 终局帧(否则流挂死)"
        assert results[-1]["data"].get("quotaCode") == quota.QUOTA_USER_DAILY
        assert results[-1]["data"].get("output")

    async def test_sync_arm_quota_envelope(self, client, monkeypatch, gate_on, stub_run_agent):
        monkeypatch.setenv("AI_USER_DAILY", "1")
        biz = _biz()
        await _seed_tenant(biz)
        headers = {**user_auth("u_web_sync"), "x-tenant-id": biz}
        body = {"message": "在吗", "sync": True, "userId": "u_web_sync", "businessId": biz}
        res = await client.post("/api/chat", headers=headers, json=body)
        assert res.json()["success"] is True
        res = await client.post("/api/chat", headers=headers, json=body)
        body_out = res.json()
        assert body_out["success"] is False
        assert body_out["quotaCode"] == quota.QUOTA_USER_DAILY
