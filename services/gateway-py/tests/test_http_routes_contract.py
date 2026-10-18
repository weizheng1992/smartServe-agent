"""📜 HTTP 路由契约测试 — 1:1 移植 apps/server/test/contract/httpRoutes.contract.test.ts。

钉死 39 条路由的响应契约(envelope 形状 + 关键字段),作为 gateway-py 的回归网。

与 TS 原版的两处刻意差异(TS 契约套件从未真正运行,原样照抄会钉死错误契约):
1. POST /api/tenant 请求体字段为 id(TS/Python 控制器均读 data.id,原测试发 businessId 会 400);
2. 契约审批单 ID 使用 UUID(Python 侧 ApprovalGatekeeper 校验 UUID 格式)。
"""

from __future__ import annotations

import base64
import importlib
import os
import random
from datetime import UTC
from typing import ClassVar

import pytest

from .conftest import _TS, CONTRACT_APPROVAL, CONTRACT_THREAD, create_thread


@pytest.fixture()
async def platform(client):
    """平台运营者 JWT(platform@aurora;ASGITransport 不触发 lifespan,显式种子)。

    平台面零鉴权收口(2026-10-18,critical):管控台全族(tenant/overview/
    billing/skills/rag/evals/logs/guardrails/personas)须持 platform_admin JWT。"""
    from engine_py.analytics import rbac

    await rbac.ensure_platform_admin()
    password = os.environ.get("E2E_ACCOUNT_PASSWORD", "agent-all-dev")
    r = await client.post("/api/auth/login", json={"email": "platform@aurora", "password": password})
    assert r.status_code == 200, f"平台登录失败: {r.text}"
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


class TestPlatformGate:
    """平台面零鉴权收口负例:匿名 401、普通商户员工 403、平台运营者放行。"""

    async def test_anonymous_platform_reads_401(self, client):
        for path in (
            "/api/tenant/list",
            "/api/overview",
            "/api/guardrails",
            "/api/billing/usages",
            "/api/evals/results",
            "/api/logs",
            "/api/skills/registry",
            "/api/rag/documents",
        ):
            res = await client.get(path)
            assert res.status_code == 401, f"{path}: {res.status_code} {res.text[:120]}"

    async def test_anonymous_platform_writes_401(self, client):
        res = await client.put("/api/billing/quota", json={"businessId": "nike", "monthlyLimitTokens": 1})
        assert res.status_code == 401
        res = await client.post("/api/tenant", json={"id": "x", "name": "x"})
        assert res.status_code == 401
        res = await client.delete("/api/tenant/nike")
        assert res.status_code == 401

    async def test_non_platform_staff_403(self, client, contract_fixtures):
        """JWT 有效但非 platform_admin(普通商户员工)→ 403。"""
        from engine_py.analytics import rbac

        # test@example.com 是 STAFF_SEED_ROSTER 的 aurora 种子员工:登录前幂等补
        # bcrypt 密码(与 conftest staff_auth 同租户,避免跨租户固定 staff id 撞 PK)
        await rbac.ensure_defaults("aurora")
        password = os.environ.get("E2E_ACCOUNT_PASSWORD", "agent-all-dev")
        r = await client.post("/api/auth/login", json={"email": "test@example.com", "password": password})
        assert r.status_code == 200, r.text
        staff_headers = {"Authorization": f"Bearer {r.json()['data']['token']}"}
        res = await client.get("/api/tenant/list", headers=staff_headers)
        assert res.status_code == 403
        assert "platform_admin" in res.json()["detail"]

    async def test_platform_admin_reads_pass(self, client, platform):
        res = await client.get("/api/tenant/list", headers=platform)
        assert res.status_code == 200
        res = await client.get("/api/overview", headers=platform)
        assert res.status_code == 200

pytestmark = pytest.mark.asyncio(loop_scope="session")


class TestHealth:
    async def test_get_api_health(self, client, contract_fixtures):
        res = await client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["success"] is True


class TestTenant:
    async def test_ping_tenant_context_and_config(self, client, contract_fixtures):
        res = await client.get("/api/tenant/ping", headers={"x-tenant-id": "nike"})
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["tenant"]["tenantId"] == "nike"
        assert "config" in body
        assert isinstance(body["timestamp"], str)

    async def test_list_contains_seeded_tenants(self, client, contract_fixtures, platform):
        res = await client.get("/api/tenant/list", headers=platform)
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert isinstance(body["tenants"], list)
        ids = [t["id"] for t in body["tenants"]]
        assert "nike" in ids
        assert "adidas" in ids
        # 注册表行携带 planTier(admin-readiness 02:内置域标记随行下发)
        sample = body["tenants"][0]
        assert isinstance(sample.get("planTier"), str)

    async def test_builtin_tenant_delete_and_disable_protected(self, client, contract_fixtures, platform):
        """内置业务域保护(admin-readiness 02):builtin 行禁删、禁停用,
        名称/行业仍可改 —— nike/adidas/ecommerce 是 nightly 评测与密封契约的依赖基线。"""
        from engine_py.db import get_session
        from sqlalchemy import text

        builtin_id = f"bt_{_TS}"
        async with get_session() as session:
            await session.execute(
                text(
                    "INSERT INTO tenants (business_id, name, plan_tier, status) "
                    "VALUES (:bid, '内置保护契约域', 'builtin', 'active') ON CONFLICT (business_id) DO NOTHING"
                ).bindparams(bid=builtin_id)
            )
            await session.commit()

        # 禁删
        del_res = await client.delete(f"/api/tenant/{builtin_id}", headers=platform)
        assert del_res.status_code == 403
        assert "不可删除" in str(del_res.json())

        # 禁停用
        disable_res = await client.put(
            f"/api/tenant/{builtin_id}",
            headers=platform,
            json={"name": "内置保护契约域", "status": "disabled"},
        )
        assert disable_res.status_code == 403
        assert "不可停用" in str(disable_res.json())

        # 名称/行业仍可改(status 保持 active)
        rename_res = await client.put(
            f"/api/tenant/{builtin_id}",
            headers=platform,
            json={"name": "内置保护契约域-改名", "status": "active", "industry": "契约测试"},
        )
        assert rename_res.status_code == 200

        listing = await client.get("/api/tenant/list", headers=platform)
        row = next(t for t in listing.json()["tenants"] if t["id"] == builtin_id)
        assert row["name"] == "内置保护契约域-改名"
        assert row["status"] == "active"
        assert row["planTier"] == "builtin"

        # 清理:直连 DB(路由层拒删,测试自清理走 SQL)
        async with get_session() as session:
            await session.execute(text("DELETE FROM tenants WHERE business_id = :bid").bindparams(bid=builtin_id))
            await session.commit()

    async def test_create_list_delete_roundtrip(self, client, contract_fixtures, platform):
        ct_id = f"ct_{_TS}"
        create_res = await client.post("/api/tenant", headers=platform, json={"id": ct_id, "name": "契约测试租户"})
        assert create_res.status_code in (200, 201)
        assert create_res.json()["success"] is True

        list_after_create = await client.get("/api/tenant/list", headers=platform)
        created = next((t for t in list_after_create.json()["tenants"] if t["id"] == ct_id), None)
        assert created is not None

        # 未配置 SPI 的租户:密钥/回调地址/退款阈值诚实回 null,
        # 严禁编造默认值(key_x_sec / 300 / localhost:3005 曾是编造重灾区)
        assert created["apiKey"] is None
        assert created["webhookUrl"] is None
        assert created["refundLimit"] is None

        del_res = await client.delete(f"/api/tenant/{created['id']}", headers=platform)
        assert del_res.status_code == 200
        assert del_res.json()["success"] is True

    async def test_configured_secret_is_write_only_never_echoed(self, client, contract_fixtures, platform):
        """已配置租户的 apiSecret 是 write-only(2026-10-15 安全审计 #1):
        GET /api/tenant/list 无鉴权依赖,DB 里存了活体密钥也严禁明文回吐 ——
        密钥真源在网关 env(验签消费),DB 字段仅配置面。"""
        from engine_py.db import get_session
        from sqlalchemy import text

        st_id = f"st_{_TS}"
        async with get_session() as session:
            await session.execute(text("DELETE FROM tenant_configs WHERE business_id = :bid").bindparams(bid=st_id))
            await session.execute(text("DELETE FROM tenants WHERE business_id = :bid").bindparams(bid=st_id))
            await session.execute(
                text(
                    "INSERT INTO tenants (business_id, name, plan_tier, status) "
                    "VALUES (:bid, '密钥write-only契约域', 'builtin', 'active')"
                ).bindparams(bid=st_id)
            )
            await session.execute(
                text(
                    "INSERT INTO tenant_configs (id, business_id, spi_config, status) "
                    "VALUES (gen_random_uuid(), :bid, CAST(:cfg AS jsonb), 'published')"
                ).bindparams(
                    bid=st_id,
                    cfg='{"apiSecret": "live-secret-do-not-echo", "spiBaseUrl": "http://x"}',
                )
            )
            await session.commit()
        try:
            listing = await client.get("/api/tenant/list", headers=platform)
            row = next((t for t in listing.json()["tenants"] if t["id"] == st_id), None)
            assert row is not None
            assert row["apiKey"] is None, "密钥必须 write-only,严禁明文回吐"
            assert "live-secret-do-not-echo" not in listing.text, "响应全文不得含密钥"
        finally:
            async with get_session() as session:
                await session.execute(
                    text("DELETE FROM tenant_configs WHERE business_id = :bid").bindparams(bid=st_id)
                )
                await session.execute(
                    text("DELETE FROM tenants WHERE business_id = :bid").bindparams(bid=st_id)
                )
                await session.commit()

    async def test_update_tenant_roundtrip(self, client, contract_fixtures, platform):
        ut_id = f"ut_{_TS}"
        create_res = await client.post(
            "/api/tenant",
            headers=platform,
            json={
                "id": ut_id,
                "name": "契约测试租户",
                "refundLimit": 300,
                # 前端真实形状:行业/阈值同时以嵌套 config 携带
                "config": {"industry": "美妆个护", "refundLimit": 300, "webhookUrl": "https://hook.example.com"},
            },
        )
        assert create_res.status_code in (200, 201)

        upd_res = await client.put(
            f"/api/tenant/{ut_id}",
            headers=platform,
            json={
                "name": "契约测试租户V2",
                "refundLimit": 500,
                "webhookUrl": "https://spi.example.com/hook",
                "industry": "跨境母婴",
            },
        )
        assert upd_res.status_code == 200
        body = upd_res.json()
        assert body["success"] is True
        assert body["businessId"] == ut_id

        # 名称/退款阈值/行业应反映更新后的真实值(industry 落 tenants 表;refundLimit 从 tenant_configs.skills_config 读取)
        list_res = await client.get("/api/tenant/list", headers=platform)
        updated = next((t for t in list_res.json()["tenants"] if t["id"] == ut_id), None)
        assert updated is not None
        assert updated["name"] == "契约测试租户V2"
        assert updated["refundLimit"] == 500
        assert updated["industry"] == "跨境母婴"

        ghost_res = await client.put(f"/api/tenant/ghost_{_TS}", headers=platform, json={"name": "幽灵租户"})
        assert ghost_res.status_code == 404

        await client.delete(f"/api/tenant/{ut_id}", headers=platform)


class TestTenantOnboardingConfig:
    """租户引导配置编辑面契约(new-user-onboarding E)。

    PUT /api/tenant/{id} 收 onboardingConfig 完整 JSON 文档:服务端 schema 校验
    (engine_py.onboarding.validate_onboarding_config 单一来源)—— JSON 手编错形
    400 诚实失败;合法即整体覆写落 tenant_configs.onboarding_config,未携带
    保留既有(合并式);GET /api/tenant/list 回读供编辑面预填。

    POST /api/tenant 创建流同语义(2026-09-10 补齐「仅编辑态」边界):创建即
    携带即写入,不必先建再编辑;错形 400 且不落租户。"""

    VALID_ONBOARDING: ClassVar[dict] = {
        "welcomeText": "您好！我是契约测试租户的智能客服 🎉",
        "returningGreeting": "欢迎回来！请问这次需要帮您什么？",
        "quickRepliesTitle": "您可以直接选择：",
        "quickReplies": [
            {"label": "查订单", "action": "send_message", "payload": {"text": "帮我查订单物流"}},
            {"label": "🎧 转人工", "action": "send_message", "payload": {"text": "转人工"}},
        ],
    }

    async def test_create_with_onboarding_config_write_and_readback(self, client, contract_fixtures, platform):
        """创建即携带(2026-09-10):POST /api/tenant 带 onboardingConfig → 校验通过
        即随建租户一并落库,列表回读等值;消除「先建后编辑」两步走。"""
        ct_id = f"otc_{_TS}"
        res = await client.post(
            "/api/tenant",
            headers=platform,
            json={"id": ct_id, "name": "创建带引导配置租户", "onboardingConfig": self.VALID_ONBOARDING},
        )
        assert res.status_code in (200, 201)
        assert res.json()["success"] is True

        list_res = await client.get("/api/tenant/list", headers=platform)
        row = next((t for t in list_res.json()["tenants"] if t["id"] == ct_id), None)
        assert row is not None
        assert row["onboardingConfig"] == self.VALID_ONBOARDING

        await client.delete(f"/api/tenant/{ct_id}", headers=platform)

    async def test_create_with_invalid_onboarding_rejected_400(self, client, contract_fixtures, platform):
        """创建流错形与 PUT 同姿态:400 诚实失败,且租户不落库(不留半成品行)。"""
        ct_id = f"otc2_{_TS}"
        bad = {**self.VALID_ONBOARDING, "welcomText": "未知键错形"}
        res = await client.post(
            "/api/tenant",
            headers=platform,
            json={"id": ct_id, "name": "创建错形校验租户", "onboardingConfig": bad},
        )
        assert res.status_code == 400
        assert "onboardingConfig" in res.json()["detail"]

        list_res = await client.get("/api/tenant/list", headers=platform)
        assert next((t for t in list_res.json()["tenants"] if t["id"] == ct_id), None) is None

    async def test_create_without_onboarding_leaves_unconfigured(self, client, contract_fixtures, platform):
        """未携带 = 保持未配置(回读 null,首访走平台默认),与编辑态「未携带保留」同语义。"""
        ct_id = f"otc3_{_TS}"
        res = await client.post("/api/tenant", headers=platform, json={"id": ct_id, "name": "创建不带引导租户"})
        assert res.status_code in (200, 201)

        list_res = await client.get("/api/tenant/list", headers=platform)
        row = next((t for t in list_res.json()["tenants"] if t["id"] == ct_id), None)
        assert row is not None
        assert row["onboardingConfig"] is None

        await client.delete(f"/api/tenant/{ct_id}", headers=platform)

    async def test_valid_onboarding_config_write_and_readback(self, client, contract_fixtures, platform):
        ot_id = f"ot_{_TS}"
        create_res = await client.post(
            "/api/tenant", headers=platform, json={"id": ot_id, "name": "引导配置测试租户"}
        )
        assert create_res.status_code in (200, 201)

        upd_res = await client.put(
            f"/api/tenant/{ot_id}",
            headers=platform,
            json={"name": "引导配置测试租户", "onboardingConfig": self.VALID_ONBOARDING},
        )
        assert upd_res.status_code == 200
        assert upd_res.json()["success"] is True

        # 列表回读:编辑面预填取到的是刚写入的真实配置,非伪造默认
        list_res = await client.get("/api/tenant/list", headers=platform)
        row = next((t for t in list_res.json()["tenants"] if t["id"] == ot_id), None)
        assert row is not None
        assert row["onboardingConfig"] == self.VALID_ONBOARDING

        await client.delete(f"/api/tenant/{ot_id}", headers=platform)

    async def test_unknown_top_level_key_rejected_400(self, client, contract_fixtures, platform):
        ot_id = f"ot2_{_TS}"
        await client.post("/api/tenant", headers=platform, json={"id": ot_id, "name": "引导校验测试租户"})

        bad = {**self.VALID_ONBOARDING, "welcomText": "未知键错形"}
        res = await client.put(
            f"/api/tenant/{ot_id}",
            headers=platform,
            json={"name": "引导校验测试租户", "onboardingConfig": bad},
        )
        assert res.status_code == 400
        # FastAPI HTTPException 序列化为 detail;错误信息须点名具体错形供编辑面展示
        assert "onboardingConfig" in res.json()["detail"]

        await client.delete(f"/api/tenant/{ot_id}", headers=platform)

    async def test_button_shape_error_rejected_400(self, client, contract_fixtures, platform):
        ot_id = f"ot3_{_TS}"
        await client.post("/api/tenant", headers=platform, json={"id": ot_id, "name": "引导按钮校验租户"})

        bad = {**self.VALID_ONBOARDING, "quickReplies": [{"label": "缺 action 与 payload"}]}
        res = await client.put(
            f"/api/tenant/{ot_id}",
            headers=platform,
            json={"name": "引导按钮校验租户", "onboardingConfig": bad},
        )
        assert res.status_code == 400
        assert "quickReplies" in res.json()["detail"]

        await client.delete(f"/api/tenant/{ot_id}", headers=platform)

    async def test_update_without_onboarding_preserves_existing(self, client, contract_fixtures, platform):
        """合并式语义:不带 onboardingConfig 的常规更新(改名/阈值)不得清空既有引导配置。"""
        ot_id = f"ot4_{_TS}"
        await client.post("/api/tenant", headers=platform, json={"id": ot_id, "name": "引导保留测试租户"})
        await client.put(
            f"/api/tenant/{ot_id}",
            headers=platform,
            json={"name": "引导保留测试租户", "onboardingConfig": self.VALID_ONBOARDING},
        )

        plain_res = await client.put(
            f"/api/tenant/{ot_id}",
            headers=platform,
            json={"name": "引导保留测试租户V2", "refundLimit": 888},
        )
        assert plain_res.status_code == 200

        list_res = await client.get("/api/tenant/list", headers=platform)
        row = next((t for t in list_res.json()["tenants"] if t["id"] == ot_id), None)
        assert row["name"] == "引导保留测试租户V2"
        assert row["refundLimit"] == 888
        assert row["onboardingConfig"] == self.VALID_ONBOARDING  # 未携带 → 保留

        await client.delete(f"/api/tenant/{ot_id}", headers=platform)


class TestMerchantTenantGate:
    """商户注册门禁(A档,2026-09-04):客户端自报 businessId/tenantId 必须在 tenants
    注册表登记且 active 方可使用商户服务路径。此前任意自报租户可获全套引擎服务
    并收到品牌扮演回复(实测 ghost 租户 200 + "X 官方商城"角色扮演 + 线程落库)。"""

    async def test_store_chat_rejects_unregistered_tenant(self, client, contract_fixtures):
        res = await client.post(
            "/api/store/chat",
            json={"message": "你们支持哪些支付方式", "businessId": f"ghost_{_TS}", "userId": "CUST-CONTRACT-GHOST"},
        )
        assert res.status_code == 403
        assert res.json()["success"] is False

    async def test_store_chat_messages_rejects_unregistered_tenant(self, client, contract_fixtures):
        res = await client.get("/api/store/chat/messages", params={"businessId": f"ghost_{_TS}", "userId": "u_ghost"})
        assert res.status_code == 403
        assert res.json()["success"] is False

    async def test_store_chat_messages_allows_registered_tenant(self, client, contract_fixtures):
        # nike 为 conftest seed_tenants 落库的 active 注册租户;过闸后走纯 DB 会话读取(无 LLM)
        res = await client.get("/api/store/chat/messages", params={"businessId": "nike", "userId": "u_contract"})
        assert res.status_code == 200
        assert res.json()["success"] is True

    async def test_admin_conversations_rejects_cross_tenant(self, client, contract_fixtures, staff_auth):
        # A4 收口(2026-09-26 夜审):员工面租户边界 —— 参数租户 ≠ 员工真租户
        # 一律 403,幽灵租户同罪;此前该路由匿名可读任意租户会话
        res = await client.get(
            "/api/admin/conversations", params={"tenantId": f"ghost_{_TS}"}, headers=staff_auth
        )
        assert res.status_code == 403
        # 身份/租户闸走 HTTPException 形(detail),业务错才走 success 形
        assert "租户" in res.json()["detail"]

    async def test_admin_conversations_rejects_anonymous(self, client, contract_fixtures):
        # A4 收口:无凭证 401(此前裸奔)
        res = await client.get("/api/admin/conversations", params={"tenantId": "aurora"})
        assert res.status_code == 401

    async def test_admin_conversations_all_aggregate_rejected_for_staff(self, client, contract_fixtures, staff_auth):
        # A4 收口:「all」跨租户聚合是匿名时代遗产,员工可见面不得越过其租户行
        # (不变量 #1); aurora 员工查自己租户仍 200
        res_all = await client.get("/api/admin/conversations", params={"tenantId": "all"}, headers=staff_auth)
        assert res_all.status_code == 403
        res_own = await client.get("/api/admin/conversations", params={"tenantId": "aurora"}, headers=staff_auth)
        assert res_own.status_code == 200
        assert res_own.json()["success"] is True


class TestStoreChatMultimodal:
    """商户聊天多模态(2026-09-09):store_chat 接收 imageUrls 透传引擎并以用户行
    落库(005 治理后引擎零写用户行,store_chat 漏写会导致 merchant 用户消息不落库)。"""

    async def test_store_chat_with_images_persists_and_restores(self, client, contract_fixtures, monkeypatch):
        # 拦截 run_agent(受理脊单点 chat_turn,A3 后 run_agent 只在此被调用):
        # 必须补丁 router 命名空间的引用;且 store_chat 会解引用 final_state,桩须返回 dict
        async def _fake_run_agent(job):
            return {"output": "已收到您的图片(测试桩)", "cards": []}

        monkeypatch.setattr("gateway_py.chat_turn.run_agent", _fake_run_agent)

        thread_id = f"merchant_thread_img_{random.randint(10**6, 10**7)}"
        image_urls = ["/api/uploads/contract_store_a.png", "/api/uploads/contract_store_b.png"]
        res = await client.post(
            "/api/store/chat",
            json={
                "message": "请查看我上传的图片",
                "threadId": thread_id,
                "userId": "CUST-STORE-IMG",
                "businessId": "nike",
                "imageUrls": image_urls,
            },
        )
        assert res.status_code == 200
        assert res.json()["success"] is True

        # 刷新还原语义:GET /api/store/chat/messages 带回 imageUrls
        res2 = await client.get(
            "/api/store/chat/messages", params={"businessId": "nike", "threadId": thread_id, "userId": "CUST-STORE-IMG"}
        )
        assert res2.status_code == 200
        body = res2.json()
        user_msgs = [m for m in body["messages"] if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0]["imageUrls"] == image_urls

    async def test_store_chat_plain_message_persists_single_user_row(self, client, contract_fixtures, monkeypatch):
        # 纯文本(无图)也须落库且仅一行用户行——钉死 005 治理后的回归修复
        async def _fake_run_agent(job):
            return {"output": "已收到您的咨询(测试桩)", "cards": []}

        monkeypatch.setattr("gateway_py.chat_turn.run_agent", _fake_run_agent)

        thread_id = f"merchant_thread_plain_{random.randint(10**6, 10**7)}"
        res = await client.post(
            "/api/store/chat",
            json={"message": "你们支持哪些支付方式", "threadId": thread_id, "userId": "CUST-STORE-PLAIN", "businessId": "nike"},
        )
        assert res.status_code == 200
        assert res.json()["success"] is True

        res2 = await client.get(
            "/api/store/chat/messages",
            params={"businessId": "nike", "threadId": thread_id, "userId": "CUST-STORE-PLAIN"},
        )
        user_msgs = [m for m in res2.json()["messages"] if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0]["imageUrls"] is None

    async def test_store_chat_rejects_empty_message_without_images(self, client, contract_fixtures):
        res = await client.post(
            "/api/store/chat",
            json={"message": "   ", "businessId": "nike", "userId": "CUST-STORE-EMPTY"},
        )
        assert res.status_code == 400
        assert res.json()["success"] is False


class TestConversationTimelineChronologicalOrder:
    """时间线排序锚(2026-09-10):messages.timestamp 是 TEXT 列,网关写 naive 本地
    墙钟(append_message datetime.now()),引擎写 UTC 带偏移(short_memory 模拟时钟,
    与真实落库时刻可有分钟级偏差)—— 两格式字符串比较无意义,曾致最近一轮
    「用户问 → 客服答」在时间线里倒置显示(答在问上)。排序锚改 created_at
    (DB 单一时钟、DEFAULT now()),与 list_conversations / list_user_threads 的
    LATERAL 末消息选取(ORDER BY created_at DESC)同锚。"""

    async def test_store_chat_messages_orders_by_created_at_not_text_timestamp(self, client, contract_fixtures):
        import datetime as dt

        from engine_py.db import get_session
        from sqlalchemy import text

        base = dt.datetime.now(dt.UTC)
        t_user_real = base - dt.timedelta(minutes=4)
        t_asst_real = base - dt.timedelta(minutes=2)
        # 镜像生产数据形状:用户行=网关 naive 北京墙钟;客服行=引擎 UTC(+00:00)
        naive_user_text = (t_user_real + dt.timedelta(hours=8)).replace(tzinfo=None).isoformat()
        utc_asst_text = t_asst_real.isoformat()

        thread_id = "thread_timeline_order_tz"
        async with get_session() as session:
            await session.execute(
                text(
                    'INSERT INTO threads (id, "user_id", "business_id", status, "created_at", "updated_at") '
                    "VALUES (:tid, 'CUST-TZ-ORDER', 'nike', 'active', NOW(), NOW()) ON CONFLICT (id) DO NOTHING"
                ).bindparams(tid=thread_id)
            )
            for mid, role, content, ts_text, created_at in [
                ("tzorder_user", "user", "坏了", naive_user_text, t_user_real),
                ("tzorder_asst", "assistant", "收到您的照片,请选择破损商品", utc_asst_text, t_asst_real),
            ]:
                await session.execute(
                    text(
                        "INSERT INTO messages (id, thread_id, business_id, role, content, timestamp, created_at) "
                        "VALUES (:mid, :tid, 'nike', :role, :content, :ts, :ca) ON CONFLICT (id) DO NOTHING"
                    ).bindparams(
                        mid=mid, tid=thread_id, role=role, content=content, ts=ts_text, ca=created_at.replace(tzinfo=None)
                    )
                )
            await session.commit()

        res = await client.get(
            "/api/store/chat/messages",
            params={"businessId": "nike", "threadId": thread_id, "userId": "CUST-TZ-ORDER"},
        )
        assert res.status_code == 200
        roles = [m["role"] for m in res.json()["messages"]]
        # 真实时序:用户问(早 2 分钟)在前、客服答在后;文本字符串序会倒置这对
        assert roles == ["user", "assistant"]

    async def test_append_message_writes_utc_aware_timestamp(self, contract_fixtures):
        """写入格式收口(2026-09-25):网关行 TEXT 列 timestamp 统一 UTC 带偏移,
        与引擎行同格式 —— 混排 naive 本地曾致字符串序「答在问上」(排序锚虽已
        改 created_at,展示/导出消费仍吃本列,格式统一免得下一处比较重蹈)。"""
        import datetime as dt

        from engine_py.db import get_session
        from sqlalchemy import text

        from gateway_py.conversation_repo import append_message

        thread_id = "thread_append_ts_format"
        await append_message(
            {
                "threadId": thread_id,
                "businessId": "nike",
                "userId": "CUST-TS-FORMAT",
                "role": "user",
                "content": "格式收口探针",
            }
        )
        await append_message(
            {
                "threadId": thread_id,
                "businessId": "nike",
                "userId": "CUST-TS-FORMAT",
                "role": "assistant",
                "content": "naive 传入按本地墙钟换算",
                # 刻意 naive(DTZ001 豁免):被测对象就是 naive 入参的换算
                "timestamp": dt.datetime(2026, 9, 25, 17, 58, 20).isoformat(),  # noqa: DTZ001
            }
        )
        async with get_session() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT role, timestamp FROM messages WHERE thread_id = :tid ORDER BY created_at, id"
                        ).bindparams(tid=thread_id)
                    )
                )
                .mappings()
                .all()
            )
        assert len(rows) == 2
        for row in rows:
            parsed = dt.datetime.fromisoformat(row["timestamp"])
            assert parsed.tzinfo is not None, f"{row['role']} 行仍写 naive 时间戳: {row['timestamp']}"
            assert parsed.utcoffset() == dt.timedelta(0), f"{row['role']} 行须为 UTC: {row['timestamp']}"
        # naive 17:58 本地墙钟 → UTC 换算期望按宿主时区现算(CI 是 UTC runner,
        # 写死 +8 的 09:58 前缀在 UTC 宿主上 17:58 本地即 17:58Z,必炸)
        expected_utc = (
            dt.datetime(2026, 9, 25, 17, 58, 20)
            .astimezone()  # naive 视作宿主本地时区
            .astimezone(dt.UTC)
            .strftime("%Y-%m-%dT%H:%M:%S")
        )
        assert rows[1]["timestamp"].startswith(expected_utc), rows[1]["timestamp"]


class TestStoreCartRead:
    """商城购物车只读端点(2026-09-15 单账本收口):聊天侧入车在引擎账本,
    商城购物车页挂载时经此端点合流展示 —— 此前聊天加购后商城页永远少一件。
    契约:有车返回引擎车行(含点名直配 skuCode/spuId);无车诚实空,严禁
    get_cart_summary 的演示默认车(AJ1)漏出。"""

    async def test_store_cart_returns_engine_rows(self, client, contract_fixtures):
        from engine_py.tools_registry.mall_domain import MallDomainService

        # 内存车直种(_load_cart 内存优先,零 Redis 依赖,确定性)
        MallDomainService._cart_storage["CUST-CT-CART"] = [
            {
                "skuId": "SPU-CT-CART",
                "quantity": 2,
                "title": "契约测试冲锋衣",
                "price": 1299.0,
                "skuCode": "SKU-CT-CART-BLK-M",
                "spuId": "SPU-CT-CART",
                "spec": {"颜色": "曜石黑", "尺码": "M"},
            }
        ]
        try:
            res = await client.get("/api/store/cart", params={"customerId": "CUST-CT-CART"})
            assert res.status_code == 200
            body = res.json()
            assert body["success"] is True
            assert body["totalQuantity"] == 2
            assert body["totalAmount"] == 2598.0
            row = body["items"][0]
            assert row["skuCode"] == "SKU-CT-CART-BLK-M", "点名直配的 skuCode 必须随行透出(商城页结算直取)"
            assert row["spuId"] == "SPU-CT-CART"
            assert row["title"] == "契约测试冲锋衣"
        finally:
            MallDomainService._cart_storage.pop("CUST-CT-CART", None)

    async def test_store_cart_honest_empty_for_unknown_customer(self, client, contract_fixtures):
        """无车顾客必须空车,严禁演示默认车(AJ1)顶替真实态。"""
        res = await client.get("/api/store/cart", params={"customerId": "CUST-CT-NOCART"})
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["items"] == []
        assert body["totalQuantity"] == 0


class TestStoreOrdersStrictScoping:
    """商户订单列表严格归属(2026-09-05):/api/store/orders 不得再 OR CUST-8801
    混入演示用户订单。背景 bug:任何 customerId 查询都会带出张伟(CUST-8801)
    的订单,与聊天侧视图永久不一致且跨用户泄漏。"""

    async def test_store_orders_scoped_to_requested_customer(self, client, contract_fixtures):

        from gateway_py.merchant_db import ensure_merchant_tables, merchant_engine
        from tests.merchant_seed_helpers import seed_merchant_order

        await ensure_merchant_tables()
        async with merchant_engine().begin() as conn:
            await seed_merchant_order(
                conn,
                order_id="CT-ORD-SCOPE-A",
                customer_id="CUST-CT-SCOPE-A",
                total_amount=100,
                shipping_address={"fullAddress": "契约测试地址"},
            )
            await seed_merchant_order(
                conn,
                order_id="CT-ORD-SCOPE-8801",
                customer_id="CUST-8801",
                total_amount=200,
                shipping_address={"fullAddress": "契约测试地址"},
            )

        res = await client.get("/api/store/orders", params={"customerId": "CUST-CT-SCOPE-A"})
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        order_ids = [o["orderId"] for o in body["orders"]]
        assert order_ids == ["CT-ORD-SCOPE-A"], (
            f"严格归属被破坏:查询 CUST-CT-SCOPE-A 却返回 {order_ids}(不应混入 CUST-8801 演示单)"
        )

    async def test_store_orders_default_user_returns_own_orders(self, client, contract_fixtures):
        res = await client.get("/api/store/orders")
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert all(o["userId"] == "CUST-8801" for o in body["orders"])


class TestStoreCouponLifecycle:
    """领券→核销全生命周期(2026-09-21 bug 闭环):核销后的券必须仍出现在
    /api/store/coupons(带 status)——修前只回 claimed 态,商品页 claimedIds
    丢失记录,领券按钮复现,用户再点即 400「已领取过该券」。"""

    async def test_used_coupon_stays_listed_with_status(self, client, contract_fixtures):
        import uuid as _uuid

        from sqlalchemy import text

        from gateway_py.merchant_db import ensure_merchant_tables, merchant_engine

        await ensure_merchant_tables()
        uid = "CUST-CT-COUPON-1"
        async with merchant_engine().begin() as conn:
            row = (await conn.execute(text(
                "SELECT id FROM promotions WHERE promo_type='coupon' AND status='active' LIMIT 1"
            ))).mappings().first()
            if row is None:
                pid = str(_uuid.uuid4())
                await conn.execute(text(
                    "INSERT INTO promotions (id, name, promo_type, status, "
                    "discount_value, scope_type) VALUES (CAST(:i AS uuid), '契约测试券', "
                    "'coupon', 'active', 50, 'all')"
                ).bindparams(i=pid))
            else:
                pid = str(row["id"])

        # ① 首领成功
        r = await client.post("/api/store/coupons/claim", json={"promoId": pid, "userId": uid})
        assert r.status_code == 200, r.text
        # ② 列表含该券,status=claimed
        listed = (await client.get("/api/store/coupons", params={"userId": uid})).json()["coupons"]
        assert [(c["promotionId"], c["status"]) for c in listed] == [(pid, "claimed")]
        # ③ 结算核销(mark_coupon_used 同语义)
        async with merchant_engine().begin() as conn:
            await conn.execute(
                text("UPDATE user_coupons SET status='used' WHERE user_id=:u").bindparams(u=uid)
            )
        # ④ 核销后仍在列表,status=used(修前整条消失 → 前端按钮复现)
        listed2 = (await client.get("/api/store/coupons", params={"userId": uid})).json()["coupons"]
        assert [(c["promotionId"], c["status"]) for c in listed2] == [(pid, "used")]
        # ⑤ API 层重复领仍诚实拒绝(业务语义不变)
        r2 = await client.post("/api/store/coupons/claim", json={"promoId": pid, "userId": uid})
        assert r2.status_code == 400

        # 清理
        async with merchant_engine().begin() as conn:
            await conn.execute(text("DELETE FROM user_coupons WHERE user_id=:u").bindparams(u=uid))


class TestSkills:
    async def test_registry(self, client, contract_fixtures, platform):
        res = await client.get("/api/skills/registry", headers=platform)
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert isinstance(body["skills"], list)
        assert len(body["skills"]) >= 5

    async def test_get_config(self, client, contract_fixtures, platform):
        res = await client.get("/api/skills/config", headers={**platform, "x-tenant-id": "nike"})
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["tenantId"] == "nike"
        assert isinstance(body["skills"], list)

    async def test_put_config(self, client, contract_fixtures, platform):
        res = await client.put(
            "/api/skills/config",
            headers={**platform, "x-tenant-id": "nike"},
            json={"skillId": "skill_order_refund", "approvalThresholdAmount": 260},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["tenantId"] == "nike"
        assert body["skillId"] == "skill_order_refund"
        assert body["config"] is not None

    async def test_tenant_alias_route(self, client, contract_fixtures, platform):
        res = await client.get("/api/skills/tenant", headers={**platform, "x-tenant-id": "nike"})
        assert res.status_code == 200
        assert res.json()["tenantId"] == "nike"

    async def test_patch_tenant_skill(self, client, contract_fixtures, platform):
        res = await client.patch(
            "/api/skills/tenant/skill_order_refund",
            headers={**platform, "x-tenant-id": "nike"},
            json={"enabled": True},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["skillId"] == "skill_order_refund"
        assert body["config"] is not None


class TestApprovals:
    async def test_list_with_fixture(self, client, contract_fixtures):
        res = await client.get("/api/approvals", params={"tenantId": "nike"})
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert isinstance(body["approvals"], list)
        assert body["total"] == len(body["approvals"])
        assert body["tenantId"] == "nike"
        fixture = next((a for a in body["approvals"] if a["id"] == CONTRACT_APPROVAL), None)
        assert fixture is not None
        assert fixture["businessId"] == "nike"
        assert fixture["actionType"] == "processRefund"
        assert fixture["status"] == "waiting"

    async def test_chat_prefix_alias(self, client, contract_fixtures):
        res = await client.get("/api/chat/approvals", params={"tenantId": "nike"})
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert isinstance(body["approvals"], list)

    async def test_chat_prefix_post_alias(self, client, contract_fixtures):
        """回归钉(wayfinder 004):TS 基线双路径控制器含 POST 别名,Python 移植
        只挂了 GET 致前端核签按钮 405;POST /api/chat/approvals 必须可达。
        02 安全先行:顾客动作须携带会话属主 userId;不可解析的 approvalId 落
        引擎自身「格式无效」语义(路由可达性仍由 200 + 错误体钉死)。"""
        res = await client.post(
            "/api/chat/approvals",
            json={"approvalId": "not-a-uuid", "action": "approve", "userId": "u_contract"},
        )
        assert res.status_code == 200  # 路由可达(405 即回归);错误体透传
        assert "格式无效" in str(res.json())

    async def test_resolve_fixture_approval(self, client, contract_fixtures):
        res = await client.post(
            "/api/approvals",
            headers={"x-tenant-id": "nike", "x-user-id": "u_contract"},
            json={"approvalId": CONTRACT_APPROVAL, "action": "approve"},
        )
        assert res.status_code == 200
        body = res.json()
        # process_approval_action 透传结果:status 推进为 approved 或显式 success
        assert body.get("status") == "approved" or body.get("success") is True

    async def _insert_waiting_ticket(self, ticket_id: str, tenant: str = "nike", thread_id: str = CONTRACT_THREAD) -> None:
        from engine_py.db import get_session
        from sqlalchemy import text

        async with get_session() as session:
            await session.execute(
                text(
                    "INSERT INTO pending_approvals (id, thread_id, business_id, status, action_type, reason, "
                    "action_payload, deadline) VALUES (CAST(:id AS uuid), :tid, :bid, 'waiting', 'processRefund', "
                    "'actor 契约工单', CAST('{}' AS jsonb), NOW() + INTERVAL '24 hours') ON CONFLICT (id) DO NOTHING"
                ).bindparams(id=ticket_id, tid=thread_id, bid=tenant)
            )
            await session.commit()

    async def test_resolve_carries_actor_identity(self, client, contract_fixtures, staff_auth):
        """核准人契约(admin-readiness 01 + 02 安全先行改版):员工面身份来自
        JWT(actor 显式声明/缺省取员工 email),顾客面固定 customer 语义;
        均落 actionPayload.resolvedBy/resolvedByRole 并由列表顶层透出;
        非法 actorRole 归 system。"""
        import uuid as _uuid

        from .conftest import _TS, create_thread

        # 员工面工单须在员工租户(aurora):对象级租户校验与商户面 A4 同口径
        aurora_thread = f"actor_aurora_thread_{_TS}"
        await create_thread(aurora_thread, "u_aurora", "aurora")

        # ① 员工 JWT + 显式 actor(商户面操作员)
        aid = str(_uuid.uuid4())
        await self._insert_waiting_ticket(aid, tenant="aurora", thread_id=aurora_thread)
        res = await client.post(
            "/api/approvals",
            headers={**staff_auth, "x-tenant-id": "aurora"},
            json={"approvalId": aid, "action": "approve", "actor": "op_12(王店长)", "actorRole": "merchant_operator"},
        )
        assert res.status_code == 200
        listing = await client.get("/api/approvals", params={"tenantId": "aurora"})
        row = next(a for a in listing.json()["approvals"] if a["id"] == aid)
        assert row["actionPayload"]["resolvedBy"] == "op_12(王店长)"
        assert row["actionPayload"]["resolvedByRole"] == "merchant_operator"
        assert row["resolvedBy"] == "op_12(王店长)"
        assert row["resolvedByRole"] == "merchant_operator"

        # ② 员工 JWT 缺省 actor → 服务端身份(员工 email)兜底;x-role 自报头退役
        aid2 = str(_uuid.uuid4())
        await self._insert_waiting_ticket(aid2, tenant="aurora", thread_id=aurora_thread)
        res2 = await client.post(
            "/api/approvals",
            headers={**staff_auth, "x-tenant-id": "aurora", "x-role": "admin"},
            json={"approvalId": aid2, "action": "reject", "rejectionReason": "契约驳回"},
        )
        assert res2.status_code == 200
        listing2 = await client.get("/api/approvals", params={"tenantId": "aurora"})
        row2 = next(a for a in listing2.json()["approvals"] if a["id"] == aid2)
        assert row2["status"] == "rejected"
        assert row2["actionPayload"]["resolvedBy"] == "test@example.com"
        assert row2["actionPayload"]["resolvedByRole"] == "merchant_operator"

        # ③ 顾客(无 JWT)凭会话归属核销 → customer 语义,不再伪装运营坐席
        aid3 = str(_uuid.uuid4())
        await self._insert_waiting_ticket(aid3)
        res3 = await client.post(
            "/api/approvals",
            headers={"x-tenant-id": "nike"},
            json={"approvalId": aid3, "action": "approve", "actor": "ghost", "actorRole": "hacker", "userId": "u_contract"},
        )
        assert res3.status_code == 200
        listing3 = await client.get("/api/approvals", params={"tenantId": "nike"})
        row3 = next(a for a in listing3.json()["approvals"] if a["id"] == aid3)
        assert row3["actionPayload"]["resolvedBy"] == "customer"
        assert row3["actionPayload"]["resolvedByRole"] == "customer"


class TestOverview:
    """全局指标大盘(admin-readiness 03):六卡全部库内真算,与直连 SQL 对账;
    README 编造的 94.2% Autopilot 率在此被真实值取代。"""

    async def test_overview_cards_match_sql_ground_truth(self, client, contract_fixtures, platform):
        import asyncio

        from engine_py.db import get_session
        from sqlalchemy import text

        # 对账竞速免疫(债务 #10 实证收口,stream-reliability-push 03):审批
        # Fast-Path 的背景恢复作业 asyncio.create_task 后句柄即弃,其 settle
        # (session_metrics 落库)可能落进「API 读数」与「SQL 真值」之间的窗口
        # —— ainvoke→astream 换用(S2c)曾扰动该窗口落点致两轮全量挂此。指标
        # 是最终一致写入,双方读数一致才判:不一致短暂退避重读,上限 5 轮。
        async def _read_both():
            res = await client.get("/api/overview", headers=platform)
            assert res.status_code == 200
            data = res.json()["data"]
            async with get_session() as session:
                auto, total = (
                    await session.execute(
                        text(
                            "SELECT COUNT(*) FILTER (WHERE resolution_status = 'resolved_auto'), COUNT(*) "
                            "FROM session_metrics"
                        )
                    )
                ).one()
                waiting = (
                    await session.execute(text("SELECT COUNT(*) FROM pending_approvals WHERE status = 'waiting'"))
                ).scalar_one()
                expected_tokens = (
                    await session.execute(text("SELECT COALESCE(SUM(total_tokens), 0) FROM session_metrics"))
                ).scalar_one()
            return data, auto, total, waiting, expected_tokens

        for attempt in range(5):
            data, auto, total, waiting, expected_tokens = await _read_both()
            if (
                data["autopilotRate"] == (round(auto / total, 4) if total else 0)
                and data["sessions"]["total"] == total
                and data["usage"]["tokens"] == expected_tokens
                and data["approvals"]["waiting"] == waiting
            ):
                break
            if attempt < 4:
                await asyncio.sleep(0.5)

        expected_rate = round(auto / total, 4) if total else 0
        assert data["autopilotRate"] == expected_rate
        assert data["approvals"]["waiting"] == waiting
        assert data["usage"]["tokens"] == expected_tokens
        assert data["sessions"]["total"] == total
        # 密封环境 session_metrics 为空表:分布为空 dict,get 需缺省
        assert data["sessions"]["distribution"].get("resolved_auto", 0) == auto

        # 形状:六卡齐活且数值型
        assert isinstance(data["activeTenants"], int)
        assert isinstance(data["threads"]["humanTakeover"], int)
        assert set(data["llm24h"]) == {"calls", "costUsd", "avgLatencyMs"}
        assert 0 <= data["autopilotRate"] <= 1


class TestChatThreads:
    """回归钉(wayfinder 004):POST /api/chat/threads。

    TS 基线服务端从未实现此路由(前端 useChatThreads 发起后静默吞 404,
    「开启新一轮对话」从未真正可用);Python 侧补齐契约 —— 幂等建线程,
    重复调用不报错、不重置既有行。
    """

    async def test_create_thread_roundtrip(self, client, contract_fixtures):
        res = await client.post(
            "/api/chat/threads",
            json={"userId": "CUST-E2E-1", "threadId": "thread_contract_create_1", "businessId": "nike"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["thread"]["id"] == "thread_contract_create_1"
        assert body["thread"]["userId"] == "CUST-E2E-1"
        assert body["thread"]["businessId"] == "nike"
        assert body["thread"]["status"] == "active"

    async def test_create_thread_idempotent_replay(self, client, contract_fixtures):
        payload = {"userId": "CUST-E2E-1", "threadId": "thread_contract_create_2", "businessId": "nike"}
        first = (await client.post("/api/chat/threads", json=payload)).json()
        second = (await client.post("/api/chat/threads", json=payload)).json()
        assert first["success"] is True and second["success"] is True
        assert second["thread"]["id"] == payload["threadId"]

    async def test_create_thread_conflicting_owner_returns_409(self, client, contract_fixtures):
        """同 id 异主冲突:他租户 / 他用户重放同 id,必须 409 且不回显他人元数据。

        回归钉(评审 HARD):修复前 SELECT 不带归属谓词,冲突重放会把
        既有线程的 userId/businessId 原样回显给调用者(跨用户信息泄漏)。
        """
        await client.post(
            "/api/chat/threads",
            json={"userId": "CUST-E2E-OWNER", "threadId": "thread_contract_conflict_1", "businessId": "nike"},
        )
        # 1) 他租户重放同 id
        cross_tenant = await client.post(
            "/api/chat/threads",
            json={"userId": "CUST-E2E-INTRUDER", "threadId": "thread_contract_conflict_1", "businessId": "aurora"},
        )
        assert cross_tenant.status_code == 409
        assert "CUST-E2E-OWNER" not in cross_tenant.text
        # 2) 同租户他用户重放同 id
        cross_user = await client.post(
            "/api/chat/threads",
            json={"userId": "CUST-E2E-INTRUDER", "threadId": "thread_contract_conflict_1", "businessId": "nike"},
        )
        assert cross_user.status_code == 409
        assert "CUST-E2E-OWNER" not in cross_user.text


class TestChatThreadsList:
    """GET /api/chat/threads(new-user-onboarding B,路由计数 42→43)。

    TS 基线无此路由,web 侧栏 fetchThreads 长期吞 404 恒空;同一缺口也
    挡住服务端权威首访判定。契约:必填 userId(严格属主等值过滤)、可选
    businessId 收窄、updated_at DESC、上限 50、形状对齐 web ChatThread。
    """

    async def test_list_returns_user_threads_recent_first(self, client, contract_fixtures):
        uid = "CUST-E2E-LIST-1"
        await client.post("/api/chat/threads", json={"userId": uid, "threadId": "thread_list_a", "businessId": "nike"})
        await client.post("/api/chat/threads", json={"userId": uid, "threadId": "thread_list_b", "businessId": "nike"})
        res = await client.get("/api/chat/threads", params={"userId": uid})
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        ids = [t["id"] for t in body["threads"]]
        assert "thread_list_a" in ids and "thread_list_b" in ids
        assert ids.index("thread_list_b") < ids.index("thread_list_a")  # 最近活跃在前
        item = body["threads"][0]
        assert set(item) >= {"id", "userId", "businessId", "status", "createdAt", "updatedAt"}
        assert item["businessId"] == "nike"
        # 最后一条消息摘要:建线程即落引导 assistant 行,列表可见轻摘要
        assert item["lastMessageRole"] == "assistant"
        assert item["lastMessageSnippet"]
        assert item["lastMessageTime"]

    async def test_list_requires_user_id(self, client, contract_fixtures):
        res = await client.get("/api/chat/threads")
        assert res.status_code == 422  # FastAPI 必填查询参缺省

    async def test_list_owner_scoped_no_cross_user_leak(self, client, contract_fixtures):
        """他人线程绝不出现:严格 user_id 等值,不做 thread-id 模糊兜底。"""
        await client.post(
            "/api/chat/threads",
            json={"userId": "CUST-E2E-LIST-OTHER", "threadId": "thread_list_other", "businessId": "nike"},
        )
        res = await client.get("/api/chat/threads", params={"userId": "CUST-E2E-LIST-2"})
        body = res.json()
        assert body["success"] is True
        assert body["threads"] == []
        assert "thread_list_other" not in res.text

    async def test_list_business_filter_narrows(self, client, contract_fixtures):
        uid = "CUST-E2E-LIST-3"
        await client.post("/api/chat/threads", json={"userId": uid, "threadId": "thread_list_nike", "businessId": "nike"})
        await client.post(
            "/api/chat/threads", json={"userId": uid, "threadId": "thread_list_adidas", "businessId": "adidas"}
        )
        res = await client.get("/api/chat/threads", params={"userId": uid, "businessId": "adidas"})
        ids = [t["id"] for t in res.json()["threads"]]
        assert "thread_list_adidas" in ids
        assert "thread_list_nike" not in ids


class TestThreadOnboardingLifecycle:
    """POST /threads 引导行生命周期(new-user-onboarding C)。

    首线程全量引导(welcomeText + quick_replies 入口卡)、回访新线程一行
    轻问候、幂等重放零重复;welcome 行是网关写入 assistant 行的**特批例外**
    (既有所有权:assistant 行归引擎)—— 特例仅限建线程时引导行,聊天回复
    仍归引擎。
    """

    async def _messages_of(self, client, thread_id: str) -> list[dict]:
        res = await client.get("/api/chat/messages", params={"threadId": thread_id})
        return res.json()["messages"]

    async def test_first_thread_full_onboarding_with_entry_card(self, client, contract_fixtures):
        uid = "CUST-E2E-ONB-1"
        res = await client.post(
            "/api/chat/threads", json={"userId": uid, "threadId": "thread_onb_first", "businessId": "nike"}
        )
        assert res.status_code == 200
        messages = await self._messages_of(client, "thread_onb_first")
        assert len(messages) == 1
        welcome = messages[0]
        assert welcome["role"] == "assistant"
        # 契约夹具无 onboarding_config 行 → 平台默认文案,品牌按 tenants.name 渲染
        assert "Nike 官方旗舰店" in welcome["content"]
        assert "智能客服" in welcome["content"]
        cards = welcome["cards"] or []
        assert cards and cards[0]["type"] == "quick_replies"
        options = cards[0]["data"]["options"]
        assert 3 <= len(options) <= 5  # 调研甜点区
        assert "转人工" in options[-1]["label"]  # 转人工固定末位
        for opt in options:
            assert opt["action"] in {"send_message", "trigger_upload"}

    async def test_idempotent_replay_no_duplicate_welcome(self, client, contract_fixtures):
        payload = {"userId": "CUST-E2E-ONB-2", "threadId": "thread_onb_replay", "businessId": "nike"}
        await client.post("/api/chat/threads", json=payload)
        await client.post("/api/chat/threads", json=payload)
        messages = await self._messages_of(client, "thread_onb_replay")
        assert len(messages) == 1  # 确定性消息 id + created 旗标双保险

    async def test_returning_new_thread_gets_light_greeting_only(self, client, contract_fixtures):
        uid = "CUST-E2E-ONB-3"
        await client.post("/api/chat/threads", json={"userId": uid, "threadId": "thread_onb_r1", "businessId": "nike"})
        await client.post("/api/chat/threads", json={"userId": uid, "threadId": "thread_onb_r2", "businessId": "nike"})
        messages = await self._messages_of(client, "thread_onb_r2")
        assert len(messages) == 1
        greeting = messages[0]
        assert greeting["role"] == "assistant"
        assert "欢迎回来" in greeting["content"]
        assert len(greeting["content"]) < 80  # 一行轻问候,非全量引导
        assert not greeting.get("cards")

    async def test_first_visit_per_tenant_independent(self, client, contract_fixtures):
        """首访判定按 (user, tenant) 组合:用户在 nike 已有线程,换 adidas 开
        新线程仍是该租户首访 → 全量引导。"""
        uid = "CUST-E2E-ONB-4"
        await client.post("/api/chat/threads", json={"userId": uid, "threadId": "thread_onb_t_nike", "businessId": "nike"})
        await client.post(
            "/api/chat/threads", json={"userId": uid, "threadId": "thread_onb_t_adidas", "businessId": "adidas"}
        )
        messages = await self._messages_of(client, "thread_onb_t_adidas")
        assert len(messages) == 1
        cards = messages[0]["cards"] or []
        assert cards and cards[0]["type"] == "quick_replies"  # 全量引导,非轻问候

    async def test_greeting_failure_does_not_block_thread_creation(self, client, contract_fixtures, monkeypatch):
        """引导配置解析炸了也不阻断建线程主契约:线程照建(200),零消息行,
        聊天照常可用(建线程永远成功优先)。"""

        async def _boom(business_id: str = "ecommerce"):
            raise RuntimeError("onboarding config db down")

        monkeypatch.setattr("gateway_py.routers.chat.resolve_onboarding_config", _boom)
        res = await client.post(
            "/api/chat/threads", json={"userId": "CUST-E2E-ONB-5", "threadId": "thread_onb_fail", "businessId": "nike"}
        )
        assert res.status_code == 200
        assert res.json()["success"] is True
        assert await self._messages_of(client, "thread_onb_fail") == []


class TestChatThreadDelete:
    """DELETE /api/chat/threads(2026-09-10 补齐,路由计数 43→44)。

    web 侧栏删线程按钮自 TS 时代就调用此端点,服务端一直 405 —— 存量缺口
    收口。契约:threadId/userId 必填;属主严格等值(无主线程不开放顾客删除,
    顾客列表本就看不到);删除范围 = 线程行 + 全部消息 + task_memory 挂起
    任务态(同 id 重建不得复活旧任务态);审计类记录(审批/意图留痕/遥测)
    刻意保留 —— 平台审计资产不随顾客删线程蒸发。
    """

    async def test_delete_removes_thread_messages_and_task_state(self, client, contract_fixtures):
        from engine_py.db import get_session
        from sqlalchemy import text

        uid = "CUST-E2E-DEL-1"
        await client.post(
            "/api/chat/threads", json={"userId": uid, "threadId": "thread_del_cascade", "businessId": "nike"}
        )
        # 挂起任务态:模拟一轮被 HITL 挂起的任务留下的 task_memory 行
        async with get_session() as session:
            await session.execute(
                text(
                    "INSERT INTO task_memory (id, thread_id, pending_intents) "
                    "VALUES (gen_random_uuid(), :tid, CAST('{}' AS jsonb))"
                ).bindparams(tid="thread_del_cascade")
            )
            await session.commit()

        res = await client.delete("/api/chat/threads", params={"threadId": "thread_del_cascade", "userId": uid})
        assert res.status_code == 200
        assert res.json()["success"] is True

        async with get_session() as session:
            thread = (
                await session.execute(
                    text("SELECT id FROM threads WHERE id = :tid").bindparams(tid="thread_del_cascade")
                )
            ).first()
            msg_count = (
                await session.execute(
                    text("SELECT COUNT(*) FROM messages WHERE thread_id = :tid").bindparams(tid="thread_del_cascade")
                )
            ).scalar()
            task_count = (
                await session.execute(
                    text("SELECT COUNT(*) FROM task_memory WHERE thread_id = :tid").bindparams(tid="thread_del_cascade")
                )
            ).scalar()
        assert thread is None
        assert msg_count == 0  # 建线程引导行随会话一并删除
        assert task_count == 0
        listed = await client.get("/api/chat/threads", params={"userId": uid})
        assert "thread_del_cascade" not in [t["id"] for t in listed.json()["threads"]]

    async def test_delete_requires_both_params(self, client, contract_fixtures):
        no_thread = await client.delete("/api/chat/threads", params={"userId": "CUST-E2E-DEL-2"})
        assert no_thread.status_code == 422
        no_user = await client.delete("/api/chat/threads", params={"threadId": "thread_del_x"})
        assert no_user.status_code == 422

    async def test_delete_rejects_non_owner(self, client, contract_fixtures):
        """跨用户删除 403:与 POST 同 id 异主守卫同姿态,他人线程删不掉。"""
        await client.post(
            "/api/chat/threads",
            json={"userId": "CUST-E2E-DEL-OWNER", "threadId": "thread_del_guard", "businessId": "nike"},
        )
        res = await client.delete(
            "/api/chat/threads", params={"threadId": "thread_del_guard", "userId": "CUST-E2E-DEL-INTRUDER"}
        )
        assert res.status_code == 403
        listed = await client.get("/api/chat/threads", params={"userId": "CUST-E2E-DEL-OWNER"})
        assert "thread_del_guard" in [t["id"] for t in listed.json()["threads"]]

    async def test_delete_unknown_thread_404(self, client, contract_fixtures):
        res = await client.delete(
            "/api/chat/threads", params={"threadId": "thread_del_ghost", "userId": "CUST-E2E-DEL-3"}
        )
        assert res.status_code == 404


class TestChatUpload:
    """POST /api/chat/upload(wayfinder multimodal-image-chat 002,路由计数 41→42)。

    前端 ChatArea.tsx 依赖的响应形状:顶层 {success, url},失败顶层 error
    (alert 展示)。MIME 白名单、10MB 流式限长(不信任 client 声明)、UUID 文件名、
    经 /api/uploads/ 静态服务回读字节。
    """

    # 1x1 透明 PNG
    PNG_1PX = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )

    async def test_upload_png_returns_url_and_serves_bytes(self, client, contract_fixtures):
        res = await client.post(
            "/api/chat/upload", files={"file": ("shot.png", self.PNG_1PX, "image/png")}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["url"].startswith("/api/uploads/")
        assert body["url"].endswith(".png")
        # UUID 文件名,不回显客户端可控的原始文件名
        assert "shot" not in body["url"]

        served = await client.get(body["url"])
        assert served.status_code == 200
        assert served.content == self.PNG_1PX

    async def test_upload_rejects_non_image_mime(self, client, contract_fixtures):
        res = await client.post(
            "/api/chat/upload", files={"file": ("note.txt", b"hello", "text/plain")}
        )
        assert res.status_code == 400
        body = res.json()
        assert body["success"] is False
        assert body["error"]

    async def test_upload_rejects_forged_content_type_magic_mismatch(self, client, contract_fixtures):
        """魔数自证(2026-10-17 视觉加固):声明 image/png 递文本字节 —— 白名单只看
        声明头时任意字节可直通视觉模型,落盘前必须内容与声明一致。"""
        res = await client.post(
            "/api/chat/upload", files={"file": ("fake.png", b"hello world, not an image", "image/png")}
        )
        assert res.status_code == 400
        body = res.json()
        assert body["success"] is False
        assert "不符" in body["error"]

    async def test_upload_rejects_real_image_with_mismatched_declared_mime(self, client, contract_fixtures):
        """严格一致性:真 JPEG 字节配 image/png 声明同样 400 —— 扩展名由声明 MIME
        反推,内容与扩展名背离会让引擎以错误 Data URL 形态直传模型。"""
        jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\0" * 32  # JPEG 魔数头
        res = await client.post(
            "/api/chat/upload", files={"file": ("mislabeled.png", jpeg_bytes, "image/png")}
        )
        assert res.status_code == 400
        assert res.json()["success"] is False

    async def test_upload_rejects_oversize_by_streamed_length(self, client, contract_fixtures):
        # 10MB + 1 字节,MIME 合法 —— 限长必须读流实测,不信任声明
        payload = self.PNG_1PX + b"\0" * (10 * 1024 * 1024)
        res = await client.post(
            "/api/chat/upload", files={"file": ("big.png", payload, "image/png")}
        )
        assert res.status_code == 413
        body = res.json()
        assert body["success"] is False
        assert body["error"]


class TestApprovalResumeDispatch:
    """回归(2026-09-05):商户退款审批通过后店铺无变化。

    根因:工单创建路径不写 pending_approvals.business_id(NULL),审批 Fast-Path 把
    None 显式传入 AgentJobInput(businessId=None) 绕过 pydantic 默认值直接校验崩溃,
    resume 永不派发,outbox 事件滞留 pending。fixture 直插 SQL 带 business_id,
    从未覆盖真实创建分支 —— 本用例走执行器真实路径钉死。
    """

    async def test_ticket_created_with_tenant_and_dispatch_completes(self, contract_fixtures, monkeypatch):
        import asyncio

        from engine_py.approvals.gatekeeper import ApprovalGatekeeper
        from engine_py.db import get_session
        from sqlalchemy import text

        # 1) 执行器真实挂起路径创建工单(修复前 business_id 落 NULL)
        created = await ApprovalGatekeeper.evaluate_pending_approval_state(
            {
                "threadId": CONTRACT_THREAD,
                "toolName": "processRefund",
                "args": {"orderId": "ORD-RESUME-1", "reason": "quality issue"},
                "stepDescription": "Process the refund for the order",
                "stepIndex": 0,
            }
        )
        assert created["state"] == "waiting"
        approval_id = created["approvalId"]

        async with get_session() as session:
            row = (
                await session.execute(
                    text("SELECT business_id FROM pending_approvals WHERE id = CAST(:i AS uuid)").bindparams(
                        i=approval_id
                    )
                )
            ).first()
        assert row is not None
        assert row[0] == "nike"  # 修复前为 None → 派发崩溃的直接根因

        # 2) 拦截 run_agent(AgentJobInput 仍在 gatekeeper 内真实构造,校验语义保留)
        captured: dict = {}

        async def _fake_run_agent(job):
            captured["businessId"] = job.business_id
            return {"output": "resumed"}

        # engine_py/__init__.py re-export 了 run_agent 函数,包属性遮蔽同名子模块,
        # 字符串路径会解析到函数上;须 import_module 取真子模块再 patch
        # (消费方为函数内延迟 from ..run_agent import run_agent,patch 子模块属性即生效)
        monkeypatch.setattr(importlib.import_module("engine_py.run_agent"), "run_agent", _fake_run_agent)

        result = await ApprovalGatekeeper.process_approval_action({"approvalId": approval_id, "action": "approve"})
        assert result.get("status") == "approved"

        await asyncio.sleep(0.1)  # 让 create_task 里的协程让步执行

        # 3) Fast-Path 派发成功 → completed;修复前 pending + "AgentJobInput ... businessId" 校验错误
        async with get_session() as session:
            ev = (
                await session.execute(
                    text(
                        "SELECT status, payload->'businessId' FROM approval_outbox_events "
                        "WHERE approval_id = :i"
                    ).bindparams(i=approval_id)
                )
            ).first()
        assert ev is not None
        assert ev[0] == "completed"
        assert ev[1] == "nike"
        assert captured.get("businessId") == "nike"


class TestChatNonLlm:
    async def test_messages_thread_and_history(self, client, contract_fixtures):
        res = await client.get(
            "/api/chat/messages", params={"threadId": CONTRACT_THREAD, "businessId": "nike"}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["thread"]["businessId"] == "nike"
        assert isinstance(body["messages"], list)
        assert len(body["messages"]) >= 1
        assert "role" in body["messages"][0]
        assert "content" in body["messages"][0]

    async def test_orders_returns_array(self, client, contract_fixtures):
        # 2026-10-02 起路由改调 OrderDomainService.list_user_orders 门面:
        # 商户真单优先、engine 本地表兜底,不再内联裸 SQL 漏商户库。
        res = await client.get(
            "/api/chat/orders", params={"userId": "CUST-8801", "businessId": "ecommerce"}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert isinstance(body["orders"], list)

    async def test_cancel_unknown_job_404_envelope(self, client, contract_fixtures):
        """S2b(stream-reliability-push 03):POST /api/chat/{job_id}/cancel 路由
        存在性与错误信封 —— 未知作业 404(success/error 形);身份参数缺失 400
        (取消是写动作,严禁落到 dispatch 的缺省身份上)。受理/属主/409 语义的
        深钉在 test_chat_cancel_route.py(活跃作业须真派发,live 面不造长跑作业);
        引擎侧 interrupted 终帧归 test_settle_turn_interrupted.py(S2c)。"""
        res = await client.post(
            "/api/chat/job_contract_unknown/cancel",
            params={"userId": "CUST-8801", "businessId": "nike"},
        )
        assert res.status_code == 404
        body = res.json()
        assert body["success"] is False
        assert "error" in body

        res = await client.post("/api/chat/job_contract_unknown/cancel")
        assert res.status_code == 400
        assert res.json()["success"] is False

    async def test_orders_shape_camelcase_contract(self):
        """审批抽屉订单区线格式钉死(_serialize_context_order 纯函数):
        门面两类来源行 —— 商户真单(shippingAddress 为 dict,收货人在地址对象内)
        与 engine 演示单(snake_case 文本列)—— 统一映射为 packages/types
        UserOrderRecord camelCase;金额缺值诚实 None,严禁 or 0 伪造 ¥0.00
        (抽屉侧对非数值渲染「—」)。"""
        from gateway_py.routers.chat import _serialize_context_order

        merchant_row = {
            "orderId": "M-1",
            "status": "PAID",
            "totalAmount": 399.0,
            "currency": "CNY",
            "carrier": "顺丰速运 (SF Express)",
            "trackingNumber": "SF123",
            "businessId": "aurora",
            "createdAt": "2026-09-30T10:00:00",
            "shippingAddress": {
                "recipientName": "李雷",
                "phone": "13800000000",
                "fullAddress": "上海市浦东新区测试路1号",
            },
        }
        out = _serialize_context_order(merchant_row)
        assert out["orderId"] == "M-1"
        assert out["status"] == "PAID"
        assert out["totalAmount"] == 399.0
        assert out["recipientName"] == "李雷"
        assert out["phone"] == "13800000000"
        assert out["shippingAddress"] == "上海市浦东新区测试路1号"
        assert out["createdAt"] == "2026-09-30T10:00:00"

        engine_row = {
            "orderId": "ORD-9001",
            "status": "shipped",
            "totalAmount": None,
            "trackingNumber": None,
            "estimatedDelivery": None,
            "businessId": "ecommerce",
            "shipping_address": "北京市朝阳区测试路2号",
        }
        out2 = _serialize_context_order(engine_row)
        assert out2["totalAmount"] is None
        assert out2["shippingAddress"] == "北京市朝阳区测试路2号"
        assert out2["recipientName"] is None
        assert out2["trackingNumber"] is None


class TestChatImagePersistence:
    """wayfinder multimodal 004:发图消息落库 imageUrls 引用,历史读取原样带回。"""

    async def test_dispatch_with_images_persists_and_restores(self, client, contract_fixtures, monkeypatch):
        # 拦截 run_agent(与 TestApprovalResumeDispatch 同一 patch 位):落库断言不依赖引擎
        async def _fake_run_agent(job):
            return None

        monkeypatch.setattr(importlib.import_module("engine_py.run_agent"), "run_agent", _fake_run_agent)

        thread_id = f"thread_img_{random.randint(10**6, 10**7)}"
        image_urls = ["/api/uploads/contract_img_a.png", "/api/uploads/contract_img_b.png"]
        res = await client.post(
            "/api/chat",
            json={
                "message": "请查看我上传的图片",
                "threadId": thread_id,
                "userId": "CUST-8801",
                "businessId": "nike",
                "imageUrls": image_urls,
            },
        )
        assert res.status_code == 200
        assert res.json()["success"] is True

        # 刷新还原语义:GET /api/chat/messages 带回 imageUrls
        res2 = await client.get("/api/chat/messages", params={"threadId": thread_id, "businessId": "nike"})
        assert res2.status_code == 200
        body = res2.json()
        user_msgs = [m for m in body["messages"] if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0]["imageUrls"] == image_urls

    async def test_history_without_images_has_null_imageurls(self, client, contract_fixtures):
        res = await client.get(
            "/api/chat/messages", params={"threadId": CONTRACT_THREAD, "businessId": "nike"}
        )
        assert res.status_code == 200
        for m in res.json()["messages"]:
            assert m.get("imageUrls") is None


class TestConversations:
    async def test_list_pagination_contains_fixture(self, client, contract_fixtures, platform):
        res = await client.get(
            "/api/conversations",
            params={"tenantId": "nike", "status": "all", "limit": 20, "offset": 0},
            headers=platform,
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["tenantId"] == "nike"
        assert "total" in body
        items = body.get("conversations") or body.get("data") or []
        ids = [c.get("threadId") or c.get("id") for c in items]
        assert CONTRACT_THREAD in ids

    async def test_detail_timeline(self, client, contract_fixtures, platform):
        res = await client.get(
            f"/api/conversations/{CONTRACT_THREAD}", headers={**platform, "x-tenant-id": "nike"}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["data"]["thread"]["businessId"] == "nike"
        assert isinstance(body["data"]["messages"], list)

    async def test_update_status(self, client, contract_fixtures, platform):
        res = await client.post(
            f"/api/conversations/{CONTRACT_THREAD}/status",
            params={"tenantId": "nike"},
            headers={**platform, "x-tenant-id": "nike"},
            json={"status": "human_takeover", "assignedOperatorId": "op_contract"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["data"] is not None

    async def test_list_carries_real_per_thread_telemetry(self, client, contract_fixtures, platform):
        """会话列表的 messageCount/totalTokens/costUsd 必须是库内真算
        (此前前端对缺失字段兜底 850 tokens / $0.0035 / 1 轮等编造值)。"""
        from engine_py.db import get_session
        from sqlalchemy import text

        from gateway_py import conversation_repo

        from .conftest import create_thread

        tid = f"tel_thread_{_TS}"
        await create_thread(tid, "u_tel", "nike")
        await conversation_repo.append_message(
            {"threadId": tid, "businessId": "nike", "role": "user", "content": "遥测契约消息"}
        )
        await conversation_repo.append_message(
            {"threadId": tid, "businessId": "nike", "role": "assistant", "content": "遥测契约回复"}
        )
        async with get_session() as session:
            await session.execute(
                text(
                    "INSERT INTO llm_call_logs (thread_id, business_id, node, model, tokens_in, tokens_out, cost_usd, latency_ms) "
                    "VALUES (:tid, 'nike', 'planner', 'glm-4.7', 100, 30, 0.002, 500), "
                    "(:tid, 'nike', 'executor', 'glm-4.7', 200, 70, 0.004, 1500)"
                ).bindparams(tid=tid)
            )
            await session.commit()

        res = await client.get(
            "/api/conversations",
            params={"tenantId": "nike", "status": "all", "limit": 50, "offset": 0},
            headers=platform,
        )
        assert res.status_code == 200
        items = res.json().get("conversations") or []
        row = next((c for c in items if c.get("threadId") == tid), None)
        assert row is not None
        assert row["messageCount"] == 2
        assert row["totalTokens"] == 400
        assert abs(row["costUsd"] - 0.006) < 1e-9
        assert row["llmCalls"] == 2

    async def test_telemetry_endpoint_aggregates_real_llm_logs(self, client, contract_fixtures, platform):
        """会话遥测端点:节点级真算聚合;无记录线程诚实空(严禁假节点/假耗时)。"""
        from engine_py.db import get_session
        from sqlalchemy import text

        from .conftest import create_thread

        tid = f"tel_node_{_TS}"
        await create_thread(tid, "u_tel", "nike")
        async with get_session() as session:
            await session.execute(
                text(
                    "INSERT INTO llm_call_logs (thread_id, business_id, node, model, tokens_in, tokens_out, cost_usd, latency_ms) "
                    "VALUES (:tid, 'nike', 'planner', 'glm-4.7', 100, 30, 0.002, 500), "
                    "(:tid, 'nike', 'planner', 'glm-4.7', 10, 20, 0.001, 700), "
                    "(:tid, 'nike', 'executor', 'glm-4.7', 200, 70, 0.004, 1500)"
                ).bindparams(tid=tid)
            )
            await session.commit()

        res = await client.get(
            f"/api/conversations/{tid}/telemetry", headers={**platform, "x-tenant-id": "nike"}
        )
        assert res.status_code == 200
        data = res.json()["data"]
        nodes = {n["node"]: n for n in data["nodes"]}
        assert set(nodes) == {"planner", "executor"}
        assert nodes["planner"]["calls"] == 2
        assert nodes["planner"]["tokens"] == 160
        assert nodes["planner"]["avgLatencyMs"] == 600
        assert nodes["executor"]["calls"] == 1
        totals = data["totals"]
        assert totals["calls"] == 3
        assert totals["tokens"] == 430
        assert abs(totals["costUsd"] - 0.007) < 1e-9

        # 无遥测线程:诚实空(此前该场景由前端假节点链顶替)
        empty_tid = f"tel_empty_{_TS}"
        await create_thread(empty_tid, "u_tel", "nike")
        empty = await client.get(
            f"/api/conversations/{empty_tid}/telemetry", headers={**platform, "x-tenant-id": "nike"}
        )
        assert empty.status_code == 200
        empty_data = empty.json()["data"]
        assert empty_data["nodes"] == []
        assert empty_data["totals"]["calls"] == 0
        assert empty_data["totals"]["tokens"] == 0


class TestRagDocumentUpload:
    """POST /api/rag/documents/upload + GET /api/rag/documents/upload/jobs/{id}
    (2026-10-17 文档 RAG;2026-10-18 异步作业化 201→202 + 平台闸)。

    平台闸与手写切片写同律(require_platform_admin;20MB docling+VLM 重管线
    严禁匿名触达);闸门(魔数自证/20MB 读流限长/具名租户强制)同步快败;落盘后
    202 派后台任务,状态写 Redis(TTL 1h),轮询端点读终态(jobId 即能力令牌,
    刻意不校验身份)。docling 摄取在本套件打桩(密封套件严禁拉解析模型);
    摄取管线真实行为由 engine 侧 test_document_rag 与真弹冒烟钉死。
    """

    async def test_upload_anonymous_401(self, client, contract_fixtures, monkeypatch, tmp_path):
        """平台闸负例:匿名上传(20MB 重管线最贵写面)必须 401 先于一切闸门。"""
        monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
        res = await client.post(
            "/api/rag/documents/upload",
            files={"file": ("doc.docx", self.DOCX_MAGIC, "application/octet-stream")},
            data={"businessId": "nike"},
        )
        assert res.status_code == 401
        assert not list((tmp_path / "uploads" / "rag" / "docs").glob("*")), "401 分支不得落盘"

    async def _await_job(self, client, job_id: str, timeout_seconds: float = 10.0) -> dict:
        """轮询作业至终态(打桩摄取为内存级,亚秒完成;超时即失败)。"""
        import asyncio

        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            res = await client.get(f"/api/rag/documents/upload/jobs/{job_id}")
            assert res.status_code == 200
            payload = res.json()["data"]
            if payload.get("status") in ("completed", "failed", "skipped"):
                return payload
            await asyncio.sleep(0.2)
        raise AssertionError(f"作业 {job_id} 超时未达终态")

    DOCX_MAGIC = b"PK\x03\x04" + b"\x14\x00\x00\x00"  # zip 容器头(docx 前缀)
    DOC_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # OLE2 复合文档头(老式 .doc)

    async def _stub_ingest(self, monkeypatch, status="ingested", reason=None):
        from engine_py.rag.document_ingest import DocumentIngestResult

        from gateway_py.routers import admin as admin_router

        calls: dict = {}

        async def _fake(path, business_id, *, category, caption_images, source_url):
            calls.update(path=path, business_id=business_id, category=category, source_url=source_url)
            return DocumentIngestResult(
                file=path.name,
                status=status,
                chunks=3,
                tables=1,
                images=1,
                captioned=1,
                doc_title="契约文档",
                reason=reason,
            )

        monkeypatch.setattr(admin_router, "ingest_document_file", _fake)
        return calls

    async def test_upload_docx_ingests_with_named_tenant(self, client, contract_fixtures, platform, monkeypatch, tmp_path):
        monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
        calls = await self._stub_ingest(monkeypatch)
        res = await client.post(
            "/api/rag/documents/upload",
            files={"file": ("会员章程.docx", self.DOCX_MAGIC, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"businessId": "nike"},
            headers=platform,
        )
        assert res.status_code == 202, "异步作业化:受理即 202,摄取在后台"
        body = res.json()
        assert body["success"] is True
        job_id = body["data"]["jobId"]
        assert job_id and body["data"]["sourceUrl"] == "会员章程.docx"
        assert body["data"]["status"] == "processing"

        job = await self._await_job(client, job_id)
        assert job["status"] == "completed"
        assert job["chunks"] == 3 and job["tables"] == 1
        assert calls["business_id"] == "nike"
        assert calls["source_url"] == "会员章程.docx"
        saved = list((tmp_path / "uploads" / "rag" / "docs").glob("*.docx"))
        assert len(saved) == 1, "成功摄取的文档本体保留在 uploads/rag/docs"

    async def test_upload_job_unknown_404(self, client, contract_fixtures):
        res = await client.get("/api/rag/documents/upload/jobs/nonexistent-job-id")
        assert res.status_code == 404
        assert "TTL" in res.json()["detail"]

    async def test_upload_rejects_god_view_and_missing_tenant(self, client, contract_fixtures, platform, monkeypatch, tmp_path):
        monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
        await self._stub_ingest(monkeypatch)
        for form in ({"businessId": "all"}, {}):
            res = await client.post(
                "/api/rag/documents/upload",
                files={"file": ("doc.docx", self.DOCX_MAGIC, "application/octet-stream")},
                data=form,
                headers=platform,
            )
            assert res.status_code == 400, f"form={form} 应拒绝上帝视角/缺省租户"
            assert "具名租户" in res.json()["detail"]

    async def test_upload_rejects_unknown_magic(self, client, contract_fixtures, platform, monkeypatch, tmp_path):
        monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
        res = await client.post(
            "/api/rag/documents/upload",
            files={"file": ("fake.docx", b"hello world, not a document", "application/octet-stream")},
            data={"businessId": "nike"},
            headers=platform,
        )
        assert res.status_code == 400
        assert "不支持的文档类型" in res.json()["detail"]
        assert not list((tmp_path / "uploads" / "rag" / "docs").glob("*")), "拒绝分支不得残留落盘文件"

    async def test_upload_rejects_legacy_doc_with_honest_message(self, client, contract_fixtures, platform, monkeypatch, tmp_path):
        monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
        res = await client.post(
            "/api/rag/documents/upload",
            files={"file": ("legacy.doc", self.DOC_MAGIC + b"\0" * 32, "application/msword")},
            data={"businessId": "nike"},
            headers=platform,
        )
        assert res.status_code == 422
        assert "另存为" in res.json()["detail"]
        assert not list((tmp_path / "uploads" / "rag" / "docs").glob("*"))

    async def test_upload_rejects_oversize_by_streamed_length(self, client, contract_fixtures, platform, monkeypatch, tmp_path):
        monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
        payload = self.DOCX_MAGIC + b"\0" * (20 * 1024 * 1024)  # 20MB + 8 字节
        res = await client.post(
            "/api/rag/documents/upload",
            files={"file": ("big.docx", payload, "application/octet-stream")},
            data={"businessId": "nike"},
            headers=platform,
        )
        assert res.status_code == 413
        assert "20MB" in res.json()["detail"]
        assert not list((tmp_path / "uploads" / "rag" / "docs").glob("*")), "超限分支不得残留半截文件"

    async def test_upload_ingest_failure_polls_failed_and_cleans_file(self, client, contract_fixtures, platform, monkeypatch, tmp_path):
        monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
        await self._stub_ingest(monkeypatch, status="failed", reason="文档转换失败(status=error): 测试桩")
        res = await client.post(
            "/api/rag/documents/upload",
            files={"file": ("broken.docx", self.DOCX_MAGIC, "application/octet-stream")},
            data={"businessId": "nike"},
            headers=platform,
        )
        assert res.status_code == 202
        job = await self._await_job(client, res.json()["data"]["jobId"])
        assert job["status"] == "failed"
        assert "文档转换失败" in job["error"]
        assert not list((tmp_path / "uploads" / "rag" / "docs").glob("*")), "失败分支必须清理落盘文件"

    async def test_upload_accepts_tenant_via_header_and_forwards_category(self, client, contract_fixtures, platform, monkeypatch, tmp_path):
        """x-tenant-id 头臂(server-gateway.md §1.3 承诺的合法入租方式)+ category
        透传与缺省:对抗审查(2026-10-17)实证六例全走表单臂,头臂零覆盖时删掉
        头解析代码套件照常全绿。"""
        monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
        calls = await self._stub_ingest(monkeypatch)
        res = await client.post(
            "/api/rag/documents/upload",
            files={"file": ("章程.docx", self.DOCX_MAGIC, "application/octet-stream")},
            data={"category": "prd"},
            headers={"x-tenant-id": "nike", **platform},
        )
        assert res.status_code == 202, res.json()
        job = await self._await_job(client, res.json()["data"]["jobId"])
        assert job["status"] == "completed"
        assert calls["business_id"] == "nike"
        assert calls["category"] == "prd"

        default_calls = await self._stub_ingest(monkeypatch)
        default_res = await client.post(
            "/api/rag/documents/upload",
            files={"file": ("默认分类.docx", self.DOCX_MAGIC, "application/octet-stream")},
            headers={"x-tenant-id": "nike", **platform},
        )
        assert default_res.status_code == 202
        await self._await_job(client, default_res.json()["data"]["jobId"])
        assert default_calls["category"] == "document", "category 缺省必须落 document"


class TestRagDocuments:
    async def test_crud_roundtrip(self, client, contract_fixtures, platform):
        create_res = await client.post(
            "/api/rag/documents",
            headers={**platform, "x-tenant-id": "nike"},
            json={"chunkText": "契约测试:Nike 退换货政策 30 天内可退。"},
        )
        assert create_res.status_code == 201
        assert create_res.json()["success"] is True
        doc_id = create_res.json()["data"]["id"]

        list_res = await client.get("/api/rag/documents", params={"tenantId": "nike"}, headers=platform)
        assert list_res.status_code == 200
        body = list_res.json()
        assert body["success"] is True
        assert body["tenantId"] == "nike"
        assert body["total"] >= 1
        assert isinstance(body["data"], list)

        del_res = await client.delete(
            f"/api/rag/documents/{doc_id}", headers={**platform, "x-tenant-id": "nike"}
        )
        assert del_res.status_code == 200
        assert del_res.json()["success"] is True
        assert isinstance(del_res.json()["message"], str)

    async def test_create_persists_user_title_and_category(self, client, contract_fixtures, platform):
        """管理台新建切片:自拟标题/分类必须落库(此前被硬编码「知识文档」覆盖),content 别名可用,空正文 422。"""
        titled = f"契约自拟标题 {_TS}"
        create_res = await client.post(
            "/api/rag/documents",
            headers={**platform, "x-tenant-id": "nike"},
            json={"chunkText": f"契约测试:自拟标题切片 {_TS}", "title": titled, "category": "product_knowledge"},
        )
        assert create_res.status_code == 201
        data = create_res.json()["data"]
        assert data["docTitle"] == titled
        assert data["category"] == "product_knowledge"

        alias_res = await client.post(
            "/api/rag/documents",
            headers={**platform, "x-tenant-id": "nike"},
            json={"content": f"契约测试 content 别名切片 {_TS}"},
        )
        assert alias_res.status_code == 201

        empty_res = await client.post(
            "/api/rag/documents", headers={**platform, "x-tenant-id": "nike"}, json={}
        )
        assert empty_res.status_code == 422

        await client.delete(
            f"/api/rag/documents/{data['id']}", headers={**platform, "x-tenant-id": "nike"}
        )
        await client.delete(
            f"/api/rag/documents/{alias_res.json()['data']['id']}", headers={**platform, "x-tenant-id": "nike"}
        )

    async def test_write_faces_require_named_tenant(self, client, contract_fixtures, platform):
        """写/删具名租户强制(2026-10-17 窃听族收口 sec-2):缺省/'all' 一律 400 ——
        此前 add 缺省兜底 ecommerce 静默落演示租户、delete 空头免 WHERE 全库可删。"""
        # add:双头皆缺 → 400(HTTPException 形 {"detail": …})
        no_tenant = await client.post("/api/rag/documents", headers=platform, json={"chunkText": "x"})
        assert no_tenant.status_code == 400
        assert "具名" in no_tenant.json()["detail"]
        # add:'all' → 400(上帝视角严禁直入语料)
        all_view = await client.post(
            "/api/rag/documents", headers={**platform, "x-tenant-id": "all"}, json={"chunkText": "x"}
        )
        assert all_view.status_code == 400

        # delete:空头/'all' → 400 且文档仍在;具名删除放行
        created = await client.post(
            "/api/rag/documents",
            headers={**platform, "x-tenant-id": "nike"},
            json={"chunkText": f"具名闸锚点 {_TS}"},
        )
        assert created.status_code == 201
        doc_id = created.json()["data"]["id"]
        bare_del = await client.delete(f"/api/rag/documents/{doc_id}", headers=platform)
        assert bare_del.status_code == 400
        assert "具名" in bare_del.json()["detail"]
        all_del = await client.delete(
            f"/api/rag/documents/{doc_id}", headers={**platform, "x-tenant-id": "all"}
        )
        assert all_del.status_code == 400

        still = await client.get("/api/rag/documents", params={"tenantId": "nike"}, headers=platform)
        assert any(d["id"] == doc_id for d in still.json()["data"]), "空头/'all' 删除必须不生效"
        named_del = await client.delete(
            f"/api/rag/documents/{doc_id}", headers={**platform, "x-tenant-id": "nike"}
        )
        assert named_del.status_code == 200

    async def test_query_returns_honest_empty_without_fake_scores(self, client, contract_fixtures, platform):
        """拆除「前 N 条文档 + 硬编码 0.75」假召回兜底:无命中时必须诚实空。"""
        res = await client.post(
            "/api/rag/query",
            headers=platform,
            json={"query": "zzz_qq_无任何语义关联乱串_xyzzy", "tenantId": "nike"},
        )
        assert res.status_code == 200
        body = res.json()["data"]
        assert isinstance(body["matches"], list)
        for match in body["matches"]:
            assert abs(match["score"] - 0.75) > 1e-9

    async def test_query_tenant_all_does_not_crash_and_stays_honest(self, client, contract_fixtures, platform):
        """上帝视角 tenantId=all:不再被硬编码降级成 ecommerce;响应契约与单租户一致。"""
        res = await client.post("/api/rag/query", headers=platform, json={"query": "退换货政策", "tenantId": "all"})
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["data"]["tenantId"] == "all"
        assert isinstance(body["data"]["matches"], list)


class TestPersonas:
    async def test_crud_roundtrip(self, client, contract_fixtures, platform):
        create_res = await client.post(
            "/api/personas",
            headers={**platform, "x-tenant-id": "nike"},
            json={
                "userId": "u_contract_persona",
                "fact": "偏好深色跑鞋",
                "businessId": "nike",
                "scope": "tenant",
            },
        )
        assert create_res.status_code == 201
        assert create_res.json()["success"] is True
        fact_id = create_res.json()["data"]["id"]

        list_res = await client.get("/api/personas", params={"tenantId": "nike"}, headers=platform)
        assert list_res.status_code == 200
        body = list_res.json()
        assert body["success"] is True
        assert body["total"] >= 1
        assert any(f["id"] == fact_id for f in body["data"])

        put_res = await client.put(
            f"/api/personas/{fact_id}", headers={**platform, "x-tenant-id": "nike"}, json={"confidence": 0.9}
        )
        assert put_res.status_code == 200
        assert put_res.json()["success"] is True
        assert put_res.json()["data"] is not None

        del_res = await client.delete(
            f"/api/personas/{fact_id}", headers={**platform, "x-tenant-id": "nike"}
        )
        assert del_res.status_code == 200
        assert del_res.json()["success"] is True

    async def test_named_tenant_view_global_readonly_and_ownership_gate(self, client, contract_fixtures, platform):
        """persona-hardening 05:具名租户视图与坐席台同口径 —— global 画像只读
        附带(scope 缺省回填 global 与 DB/召回/坐席台四方同向)、本租户行可见、
        他租户行不可见;变更面由属主闸收紧(读得到改不了,403),平台视角
        (tenantId=all)不受限。"""
        from engine_py.db import LongMemoryFact, get_session
        from sqlalchemy import select

        async with get_session() as session:
            rows = [
                LongMemoryFact(user_id="u_gate_global", fact="全局事实-契约", scope="global", business_id=None),
                LongMemoryFact(user_id="u_gate_aurora", fact="aurora 私有-契约", scope="tenant", business_id="aurora"),
                LongMemoryFact(user_id="u_gate_nike", fact="nike 私有-契约", scope="tenant", business_id="nike"),
            ]
            session.add_all(rows)
            await session.commit()
            seeded_ids = [str(r.id) for r in rows]
        try:
            list_res = await client.get("/api/personas", params={"tenantId": "nike"}, headers=platform)
            assert list_res.status_code == 200
            by_id = {f["id"]: f for f in list_res.json()["data"]}
            assert seeded_ids[0] in by_id and by_id[seeded_ids[0]]["scope"] == "global"
            assert seeded_ids[2] in by_id
            assert seeded_ids[1] not in by_id

            # 具名租户变更面:global 403(读得到改不了)/ 他租户 403 / 本租户 200
            put_global = await client.put(
                f"/api/personas/{seeded_ids[0]}",
                headers={**platform, "x-tenant-id": "nike"},
                json={"confidence": 0.5},
            )
            assert put_global.status_code == 403
            del_global = await client.delete(
                f"/api/personas/{seeded_ids[0]}", headers={**platform, "x-tenant-id": "nike"}
            )
            assert del_global.status_code == 403
            put_foreign = await client.put(
                f"/api/personas/{seeded_ids[1]}",
                headers={**platform, "x-tenant-id": "nike"},
                json={"confidence": 0.5},
            )
            assert put_foreign.status_code == 403
            put_own = await client.put(
                f"/api/personas/{seeded_ids[2]}",
                headers={**platform, "x-tenant-id": "nike"},
                json={"confidence": 0.95},
            )
            assert put_own.status_code == 200
            del_foreign = await client.delete(
                f"/api/personas/{seeded_ids[1]}", headers={**platform, "x-tenant-id": "nike"}
            )
            assert del_foreign.status_code == 403

            # 铸造面同闸(06 补 05 不对称):具名租户不得 POST scope=global 铸平台级事实
            post_global_named = await client.post(
                "/api/personas",
                headers={**platform, "x-tenant-id": "nike"},
                json={"userId": "u_gate_nike", "fact": "越权铸造-契约", "businessId": "nike", "scope": "global"},
            )
            assert post_global_named.status_code == 403

            # 平台视角不受限:all 头可改 global,回填仍是 global;亦可铸造 global
            put_platform_view = await client.put(
                f"/api/personas/{seeded_ids[0]}",
                headers={**platform, "x-tenant-id": "all"},
                json={"confidence": 0.88},
            )
            assert put_platform_view.status_code == 200
            assert put_platform_view.json()["data"]["scope"] == "global"
            post_global_platform = await client.post(
                "/api/personas",
                headers={**platform, "x-tenant-id": "all"},
                json={"userId": "u_gate_platform", "fact": "平台铸造-契约", "scope": "global"},
            )
            assert post_global_platform.status_code == 201
            assert post_global_platform.json()["data"]["scope"] == "global"
            minted_del = await client.delete(
                f"/api/personas/{post_global_platform.json()['data']['id']}",
                headers={**platform, "x-tenant-id": "all"},
            )
            assert minted_del.status_code == 200
        finally:
            async with get_session() as session:
                for fid in seeded_ids:
                    row = (
                        await session.execute(select(LongMemoryFact).where(LongMemoryFact.id == fid))
                    ).scalar_one_or_none()
                    if row:
                        await session.delete(row)
                await session.commit()

    async def test_delete_records_badcase_signal_and_silent_degradation(
        self, client, contract_fixtures, monkeypatch, platform
    ):
        """persona-hardening 06:删除画像 → 坏例池信号入池(persona_fact_deleted,
        suspected_defect 先验,ref=fact:<id>,note 带用户);池写失败静默降级,
        绝不阻断删除响应(标差是旁路,不是主链路)。"""
        from engine_py.db import BadcaseCandidate, LongMemoryFact, get_session
        from sqlalchemy import delete as sa_delete
        from sqlalchemy import select

        fact_ids: list[str] = []

        async def _seed_fact(user_id: str) -> str:
            async with get_session() as session:
                row = LongMemoryFact(user_id=user_id, fact="契约-待删除", scope="tenant", business_id="nike")
                session.add(row)
                await session.commit()
                return str(row.id)

        fact_ids.append(await _seed_fact("u_bc_nike"))
        try:
            del_res = await client.delete(
                f"/api/personas/{fact_ids[0]}", headers={**platform, "x-tenant-id": "nike"}
            )
            assert del_res.status_code == 200

            async with get_session() as session:
                signal = (
                    (
                        await session.execute(
                            select(BadcaseCandidate).where(
                                BadcaseCandidate.conversation_ref == f"fact:{fact_ids[0]}"
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
            assert signal is not None
            assert signal.signal_source == "persona_fact_deleted"
            assert signal.business_id == "nike"
            assert signal.suggested_class == "suspected_defect"  # SOURCE_PRIORS 先验
            assert signal.status == "candidate"
            assert "u_bc_nike" in (signal.note or "")

            # 池写失败静默降级:池侧 get_session 直接炸,删除仍 200 不受染
            def _pool_down(*_args, **_kwargs):
                raise RuntimeError("badcase pool unavailable")

            monkeypatch.setattr("engine_py.badcase.pool.get_session", _pool_down)
            fact_ids.append(await _seed_fact("u_bc_nike2"))
            del_res2 = await client.delete(
                f"/api/personas/{fact_ids[1]}", headers={**platform, "x-tenant-id": "nike"}
            )
            assert del_res2.status_code == 200
            assert del_res2.json()["success"] is True
        finally:
            monkeypatch.undo()
            async with get_session() as session:
                for fid in fact_ids:
                    row = (
                        await session.execute(select(LongMemoryFact).where(LongMemoryFact.id == fid))
                    ).scalar_one_or_none()
                    if row:
                        await session.delete(row)
                await session.execute(
                    sa_delete(BadcaseCandidate).where(
                        BadcaseCandidate.conversation_ref.in_([f"fact:{fid}" for fid in fact_ids])
                    )
                )
                await session.commit()

    async def test_list_tenant_filter_matrix_and_dto_backfill(self, client, contract_fixtures, platform):
        """persona-hardening 06:list 租户过滤矩阵(05 口径)—— 具名租户只见本店 +
        global/NULL 只读附带,tenantId=all 见全部,跨租户不可见;_persona_item
        缺省回填(confidence/source/status/scope/businessId)一并钉死。"""
        from engine_py.db import LongMemoryFact, get_session
        from sqlalchemy import select, update

        async with get_session() as session:
            rows = [
                LongMemoryFact(user_id="u_mtx_nike", fact="nike 私有-矩阵", scope="tenant", business_id="nike"),
                LongMemoryFact(user_id="u_mtx_aurora", fact="aurora 私有-矩阵", scope="tenant", business_id="aurora"),
                LongMemoryFact(user_id="u_mtx_global", fact="global 显式-矩阵", scope="global", business_id=None),
                LongMemoryFact(user_id="u_mtx_null", fact="scope NULL-矩阵", scope=None, business_id=None),
            ]
            session.add_all(rows)
            await session.commit()
            nike_id, aurora_id, global_id, null_id = (str(r.id) for r in rows)
            # DB 列全可空:置 NULL 打 _persona_item 的缺省回填分支
            await session.execute(
                update(LongMemoryFact)
                .where(LongMemoryFact.id == null_id)
                .values(confidence=None, source=None, status=None)
            )
            await session.commit()
        try:
            nike_view = (await client.get("/api/personas", params={"tenantId": "nike"}, headers=platform)).json()
            assert nike_view["tenantId"] == "nike"
            nike_ids = {f["id"] for f in nike_view["data"]}
            assert {nike_id, global_id, null_id} <= nike_ids
            assert aurora_id not in nike_ids

            aurora_ids = {
                f["id"]
                for f in (await client.get("/api/personas", params={"tenantId": "aurora"}, headers=platform)).json()[
                    "data"
                ]
            }
            assert aurora_id in aurora_ids
            assert nike_id not in aurora_ids

            all_ids = {
                f["id"]
                for f in (await client.get("/api/personas", params={"tenantId": "all"}, headers=platform)).json()[
                    "data"
                ]
            }
            assert {nike_id, aurora_id, global_id, null_id} <= all_ids

            by_id = {f["id"]: f for f in nike_view["data"]}
            assert by_id[global_id]["scope"] == "global"
            assert by_id[global_id]["businessId"] == "global"
            assert by_id[null_id]["scope"] == "global"  # NULL scope ≡ global(四方同向)
            assert by_id[null_id]["confidence"] == 1.0
            assert by_id[null_id]["source"] == "chat_dialogue_inference"
            assert by_id[null_id]["status"] == "approved"
        finally:
            async with get_session() as session:
                for fid in (nike_id, aurora_id, global_id, null_id):
                    row = (
                        await session.execute(select(LongMemoryFact).where(LongMemoryFact.id == fid))
                    ).scalar_one_or_none()
                    if row:
                        await session.delete(row)
                await session.commit()


class TestGuardrails:
    async def test_crud_roundtrip(self, client, contract_fixtures, platform):
        create_res = await client.post(
            "/api/guardrails",
            headers={**platform, "x-tenant-id": "nike"},
            json={"ruleName": "契约-禁词", "ruleType": "keyword", "pattern": "诈骗"},
        )
        assert create_res.status_code == 201
        assert create_res.json()["success"] is True
        rule_id = create_res.json()["data"]["id"]

        list_res = await client.get("/api/guardrails", params={"tenantId": "nike"}, headers=platform)
        assert list_res.status_code == 200
        body = list_res.json()
        assert body["success"] is True
        assert body["tenantId"] == "nike"
        assert body["total"] >= 1

        put_res = await client.put(
            f"/api/guardrails/{rule_id}", headers={**platform, "x-tenant-id": "nike"}, json={"severity": "high"}
        )
        assert put_res.status_code == 200
        assert put_res.json()["success"] is True

        del_res = await client.delete(
            f"/api/guardrails/{rule_id}", headers={**platform, "x-tenant-id": "nike"}
        )
        assert del_res.status_code == 200
        assert del_res.json()["success"] is True


class TestBilling:
    async def test_usages_returns_array(self, client, contract_fixtures, platform):
        res = await client.get("/api/billing/usages", headers=platform)
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)

    async def test_put_quota(self, client, contract_fixtures, platform):
        res = await client.put(
            "/api/billing/quota", headers=platform, json={"businessId": "nike", "monthlyLimitTokens": 5_000_000}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["data"] is not None


class TestEvals:
    @pytest.fixture
    def seed_random_eval_rows(self):
        """随机评测行播种器 — 降级自 crud.py 生产随机生成器(wayfinder 005),
        生产路由已 410 退役,生成逻辑留在测试侧供列表/分页类契约测试复用;
        固定种子保证可复现。"""

        rng = random.Random(20260907)

        async def _seed(count: int, dataset: str = "random_suite") -> list[str]:
            from engine_py.db import EvalRunRecordRow, get_session

            ids = [f"contract_eval_rand_{_TS}_{i}" for i in range(count)]
            async with get_session() as session:
                for row_id in ids:
                    session.add(
                        EvalRunRecordRow(
                            id=row_id,
                            run_name=f"promptfoo {dataset} @ rand{rng.randint(0, 999)}",
                            dataset_name=dataset,
                            sample_count=rng.randint(5, 60),
                            tool_accuracy=round(rng.uniform(0.6, 1.0), 4),
                            rag_faithfulness=round(rng.uniform(0.5, 1.0), 4),
                            hitl_trigger_rate=0.0,
                            status="completed",
                        )
                    )
                await session.commit()
            return ids

        return _seed

    async def test_results_lists_real_rows_without_mock_marker(
        self, client, contract_fixtures, seed_random_eval_rows, platform
    ):
        """随机生成器已下线(wayfinder 005):列表来自 promptfoo_import 写入的真实
        汇总行,响应不再携带 isMock;此处播种确定性一行 + 随机多行钉死透传口径。"""
        from engine_py.db import EvalRunRecordRow, get_session

        row_id = f"contract_eval_{_TS}"
        async with get_session() as session:
            session.add(
                EvalRunRecordRow(
                    id=row_id,
                    run_name=f"promptfoo unified @ contract{_TS}",
                    dataset_name="unified",
                    sample_count=47,
                    tool_accuracy=1.0,
                    rag_faithfulness=0.99,
                    hitl_trigger_rate=0.0,
                    status="completed",
                )
            )
            await session.commit()
        random_ids = await seed_random_eval_rows(3)

        res = await client.get("/api/evals/results", headers=platform)
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert isinstance(body["total"], (int, float))
        assert isinstance(body["data"], list)
        listed = {d["id"] for d in body["data"]}
        assert row_id in listed
        assert set(random_ids) <= listed  # 随机播种行同样透传
        mine = [d for d in body["data"] if d["id"] == row_id]
        assert len(mine) == 1
        assert mine[0]["datasetName"] == "unified"
        assert mine[0]["sampleCount"] == 47
        assert mine[0]["toolAccuracy"] == 1.0
        assert "isMock" not in mine[0]  # 假数据标注随真实链路移除

    async def test_run_endpoint_retired(self, client, contract_fixtures, platform):
        """POST /api/evals/run 不再产出随机指标:410 指引真实评测通道。"""
        res = await client.post("/api/evals/run", headers=platform, json={"datasetName": "contract_dataset"})
        assert res.status_code == 410
        assert "test:prompt:record" in res.json()["detail"]

    async def test_result_cases_drilldown_lists_real_rows(self, client, contract_fixtures, platform):
        """评测批次样本下钻(admin-readiness 10):run_record_id 即
        "eval_run_" + eval_runs.id,逐用例 caseName/passed/score/latencyMs/error
        按升序透传,失败样本错误保真。"""
        import uuid as _uuid

        from engine_py.db import EvalResult, EvalRun, get_session

        run_uuid = _uuid.uuid4()
        async with get_session() as session:
            # 两段式提交:FK 依赖(eval_results.run_id → eval_runs.id)先落父行
            session.add(EvalRun(id=run_uuid, business_id="ecommerce", pass_rate=0.5))
            await session.commit()
            session.add(
                EvalResult(
                    run_id=run_uuid,
                    case_name="a_order_query",
                    passed=True,
                    metrics={"score": 0.87, "latencyMs": 1200},
                )
            )
            session.add(
                EvalResult(
                    run_id=run_uuid,
                    case_name="b_refund_flow",
                    passed=False,
                    metrics={"score": 0.2, "latencyMs": 3400, "error": "assert unbacked claim"},
                )
            )
            await session.commit()

        res = await client.get(f"/api/evals/results/eval_run_{run_uuid}/cases", headers=platform)
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["total"] == 2
        first, second = body["data"]  # case_name 升序
        assert first["caseName"] == "a_order_query"
        assert first["passed"] is True
        assert first["score"] == 0.87
        assert first["latencyMs"] == 1200
        assert first["error"] is None
        assert second["caseName"] == "b_refund_flow"
        assert second["passed"] is False
        assert second["error"] == "assert unbacked claim"

    async def test_result_cases_honest_empty_for_garbage_and_unknown(self, client, contract_fixtures, platform):
        """非法 id / 无样本 → 诚实空列表,严禁编造。"""
        import uuid as _uuid

        res = await client.get("/api/evals/results/eval_run_not-a-uuid/cases", headers=platform)
        assert res.status_code == 200
        assert res.json() == {"success": True, "total": 0, "data": []}

        unknown = _uuid.uuid4()
        res2 = await client.get(f"/api/evals/results/eval_run_{unknown}/cases", headers=platform)
        assert res2.status_code == 200
        assert res2.json() == {"success": True, "total": 0, "data": []}


class TestLogs:
    async def test_success_envelope(self, client, contract_fixtures, platform):
        res = await client.get("/api/logs", params={"tenantId": "nike"}, headers=platform)
        assert res.status_code == 200
        assert res.json()["success"] is True

    async def test_llm_call_rows_come_from_llm_call_logs(self, client, contract_fixtures, platform):
        """回归钉:llm_call 类型必须来自真实 llm_call_logs 行(2026-09-05 接线)。

        此前 llm_call 行由 session_metrics 会话汇总拼装(token 记 0、模型名硬编码);
        现在模型名 / tokens / 延迟逐字段透传,租户归因经 business_id 列(缺省回退
        join threads),不造假数。
        """
        import uuid as _uuid

        from engine_py.db import get_session
        from sqlalchemy import text as _text

        llm_thread = f"llm_log_thread_{_TS}"
        await create_thread(llm_thread, "u_llm_log", "nike")
        row_id = _uuid.uuid4()
        async with get_session() as session:
            await session.execute(
                _text(
                    "INSERT INTO llm_call_logs (id, thread_id, business_id, node, model, "
                    "tokens_in, tokens_out, cost_usd, latency_ms) "
                    "VALUES (CAST(:id AS uuid), :tid, :bid, :node, :model, :tin, :tout, :cost, :latency)"
                ).bindparams(
                    id=str(row_id),
                    tid=llm_thread,
                    bid="nike",
                    node="planner",
                    model="glm-4.7",
                    tin=120,
                    tout=35,
                    cost=0.00002325,
                    latency=842,
                )
            )
            await session.commit()

        res = await client.get(
            "/api/logs", params={"tenantId": "nike", "level": "llm_call", "limit": 50}, headers=platform
        )
        assert res.status_code == 200
        rows = res.json()["data"]
        match = next((r for r in rows if r["id"] == f"log_llm_{str(row_id)[:8]}"), None)
        assert match is not None, "种子 llm_call_logs 行未出现在 /api/logs 响应中"
        assert match["logType"] == "llm_call"
        assert match["model"] == "glm-4.7"
        assert match["businessId"] == "nike"
        assert match["promptTokens"] == 120
        assert match["completionTokens"] == 35
        assert match["totalTokens"] == 155
        assert match["latencyMs"] == 842
        assert match["rawDetail"]["node"] == "planner"

    async def test_session_metrics_rows_labeled_session_metric(self, client, contract_fixtures, platform):
        """回归钉:会话遥测汇总不再冒充 llm_call —— logType 必须为 session_metric。"""
        res = await client.get("/api/logs", params={"level": "llm_call", "limit": 50}, headers=platform)
        assert res.status_code == 200
        for row in res.json()["data"]:
            assert row["logType"] == "llm_call"
            assert not row["id"].startswith("log_metric_")


class TestMerchantAdminApprovalsActor:
    """商户控制台 resolve 通道的核准人契约(admin-readiness 04 审计抓获):
    此前直调引擎漏注入 actor,商户面决议落库恒 unknown;P1 真源化后缺省
    取员工 JWT 真身(显式 actor 仍尊重)。"""

    async def test_merchant_resolve_actor缺省取员工JWT真身(self, client, contract_fixtures):
        import uuid as _uuid

        from engine_py.db import StaffMember, get_session
        from sqlalchemy import text

        from gateway_py.routers.auth import issue_token

        # A4 收口:商户面需在职员工身份,且审批单须归属员工真租户(对象级校验)
        nike_email = f"nike-actor-{_TS}@test"
        async with get_session() as session:
            session.add(StaffMember(
                id=f"staff_nike_actor_{_TS}", business_id="nike", email=nike_email,
                display_name="Nike 运营", role="admin", status="enabled", password_hash="x",
            ))
            await session.commit()

        aid = str(_uuid.uuid4())
        async with get_session() as session:
            await session.execute(
                text(
                    "INSERT INTO pending_approvals (id, thread_id, business_id, status, action_type, reason, "
                    "action_payload, deadline) VALUES (CAST(:id AS uuid), :tid, 'nike', 'waiting', 'processRefund', "
                    "'商户通道 actor 契约', CAST('{}' AS jsonb), NOW() + INTERVAL '24 hours') "
                    "ON CONFLICT (id) DO NOTHING"
                ).bindparams(id=aid, tid=CONTRACT_THREAD)
            )
            await session.commit()

        headers = {"Authorization": f"Bearer {issue_token('u_nike_actor', nike_email)}"}
        res = await client.post("/api/admin/approvals", json={"approvalId": aid, "action": "approve"}, headers=headers)
        assert res.status_code == 200

        listing = await client.get("/api/admin/approvals", params={"tenantId": "nike"}, headers=headers)
        row = next(a for a in listing.json()["approvals"] if a["id"] == aid)
        # P1 真源化(live-desk-rework spec §2.2):缺省 actor 取员工 JWT 真身,
        # 不再兜底自报 merchant_operator(审计此前恒匿名伪身份);角色语义保留
        assert row["actionPayload"]["resolvedBy"] == nike_email
        assert row["actionPayload"]["resolvedByRole"] == "merchant_operator"


class TestMerchantStoreChatStream:
    """SSE 通道 thread:{threadId}:message — 回归钉:stream 路由必须真正以 SSE 流式返回。

    历史缺陷:曾用普通 ``Response(async_generator)`` 返回,Starlette ``render()``
    对非 bytes 内容调用 ``.encode`` → 构造期 AttributeError → 500。

    走 live_server 而非 session 级 ``client``(ASGITransport):SSE 通道不依赖
    种子租户数据,且 in-process 传输下"订阅后 publish"结构性死锁(见用例内注释)。

    2026-10-02 属主闸收口:订阅须 threadId 真实存在且 businessId 与属主一致,
    匿名缺省不再通行(此前仅凭 threadId 即可订阅任意他会话实时流)。
    """

    async def test_stream_returns_sse_and_relays_pubsub(self, live_server):
        import asyncio
        import json as _json

        import httpx
        from engine_py.event_bus import get_client as get_redis_client

        # SSE 必须走真网络栈:ASGITransport 把 app 跑完才进 stream 上下文,
        # "订阅后 publish、断言转发"在 in-process 传输下结构性死锁。
        thread_id = f"merchant_stream_{_TS}"
        await create_thread(thread_id, "u_stream_contract", "nike")
        timeout = httpx.Timeout(10.0, read=30.0)

        async with (
            httpx.AsyncClient(base_url=live_server, timeout=timeout) as client,
            client.stream(
                "GET", "/api/store/chat/stream", params={"threadId": thread_id, "businessId": "nike", "userId": "u_stream_contract"}
            ) as res,
        ):
                assert res.status_code == 200
                assert "text/event-stream" in res.headers["content-type"]

                buf = ""
                published = False
                async for chunk in res.aiter_text():
                    # httpx 流式响应只能迭代一次:connected 落地后即可发布,
                    # 继续在同一迭代里等待 pub/sub 转发
                    if not published and "event: connected" in buf:
                        published = True
                        await asyncio.sleep(0.2)  # 等服务端 subscribe 完成
                        redis = await get_redis_client()
                        # L1(ADR-0013):live 帧补 id:(payload.timestamp → epoch ms),
                        # 浏览器重连时以 Last-Event-ID 带回,服务端据此重放缺失消息
                        await redis.publish(
                            f"thread:{thread_id}:message",
                            _json.dumps({"text": "contract-relay", "timestamp": "2026-10-10T01:02:03"}),
                        )
                    buf += chunk
                    if "event: message" in buf:
                        break

                assert "event: connected" in buf
                assert f'"threadId": "{thread_id}"' in buf
                # 订阅建立后,经由 Redis pub/sub 频道发布的消息应被原样转发
                assert "event: message" in buf
                assert '"text": "contract-relay"' in buf
                assert "id: " in buf, f"live message 帧缺 id: 行(ADR-0013):{buf[-300:]!r}"

    async def test_reconnect_replays_timeline_after_last_event_id(self, live_server):
        """L1 重连补投(ADR-0013):带 Last-Event-ID 重连 → 先从 DB 时间线重放
        该时刻之后的缺失消息(带 id: 与完整 payload)再进 live;非数字 id 不重放。
        断线期间的坐席/系统消息从「永久丢失、刷新才回」变「重连即补」。"""
        import uuid as _uuid
        from datetime import datetime, timedelta

        import httpx
        from engine_py.db import get_session
        from sqlalchemy import text as _sql

        thread_id = f"merchant_stream_replay_{_TS}"
        await create_thread(thread_id, "u_stream_replay", "nike")
        now = datetime.now(UTC)
        t1, t2 = now - timedelta(seconds=60), now - timedelta(seconds=30)

        async def _insert(role: str, content: str, ts: datetime) -> None:
            async with get_session() as session:
                await session.execute(
                    _sql(
                        "INSERT INTO messages (id, thread_id, business_id, role, content, timestamp) "
                        "VALUES (:mid, :tid, :bid, :role, :content, :ts)"
                    ).bindparams(
                        mid=str(_uuid.uuid4()), tid=thread_id, bid="nike",
                        role=role, content=content, ts=ts.isoformat(),
                    )
                )
                await session.commit()

        await _insert("assistant", "replay-old-marker", t1)
        await _insert("assistant", "replay-new-marker", t2)
        after_ms = int(t1.timestamp() * 1000)

        timeout = httpx.Timeout(10.0, read=15.0)
        async with httpx.AsyncClient(base_url=live_server, timeout=timeout) as client:
            # 带 Last-Event-ID(= t1 的 epoch ms):t1 被排除,t2 必须重放
            async with client.stream(
                "GET",
                "/api/store/chat/stream",
                params={"threadId": thread_id, "businessId": "nike", "userId": "u_stream_replay"},
                headers={"Last-Event-ID": str(after_ms)},
            ) as res:
                assert res.status_code == 200
                buf = ""
                async for chunk in res.aiter_text():
                    buf += chunk
                    if "replay-new-marker" in buf:
                        break
            assert "event: connected" in buf
            assert "replay-new-marker" in buf, f"缺失消息未重放:{buf[-300:]!r}"
            assert "id: " in buf
            # 水位之前(≤ Last-Event-ID)的消息严禁重放
            assert "replay-old-marker" not in buf, f"水位之前的消息被重放:{buf!r}"

            # 非数字 Last-Event-ID → 不重放(与 chat.py 同款 isdigit 语义)
            async with client.stream(
                "GET",
                "/api/store/chat/stream",
                params={"threadId": thread_id, "businessId": "nike", "userId": "u_stream_replay"},
                headers={"Last-Event-ID": "not-a-number"},
            ) as res:
                buf = ""
                async for chunk in res.aiter_text():
                    buf += chunk
                    if "event: heartbeat" in buf:
                        break
            assert "replay-new-marker" not in buf, f"非数字 id 不应触发重放:{buf!r}"

            # 无 header(首连)→ 不重放:首屏水合仍走 messages 接口(ADR-0013 §1.1)
            async with client.stream(
                "GET",
                "/api/store/chat/stream",
                params={"threadId": thread_id, "businessId": "nike", "userId": "u_stream_replay"},
            ) as res:
                buf = ""
                async for chunk in res.aiter_text():
                    buf += chunk
                    if "event: heartbeat" in buf:
                        break
            assert "event: connected" in buf
            assert "replay-new-marker" not in buf, f"首连不应触发重放:{buf!r}"

    async def test_reconnect_replays_via_query_param(self, live_server):
        """L1 重连补投 query 半边(ADR-0013① 收口):商店前端 P7 退避重建
        (aaa2aba:4xx 重连风暴收口)禁用了原生重连,重建的 EventSource 无法
        带 Last-Event-ID header —— 前端显式以 lastEventId query 带回水位,
        服务端必须与 header 同语义(query_fallback,isdigit 同闸)。"""
        import uuid as _uuid
        from datetime import datetime, timedelta

        import httpx
        from engine_py.db import get_session
        from sqlalchemy import text as _sql

        thread_id = f"merchant_stream_replay_query_{_TS}"
        await create_thread(thread_id, "u_stream_replay_query", "nike")
        now = datetime.now(UTC)
        t1, t2 = now - timedelta(seconds=60), now - timedelta(seconds=30)

        async def _insert(role: str, content: str, ts: datetime) -> None:
            async with get_session() as session:
                await session.execute(
                    _sql(
                        "INSERT INTO messages (id, thread_id, business_id, role, content, timestamp) "
                        "VALUES (:mid, :tid, :bid, :role, :content, :ts)"
                    ).bindparams(
                        mid=str(_uuid.uuid4()), tid=thread_id, bid="nike",
                        role=role, content=content, ts=ts.isoformat(),
                    )
                )
                await session.commit()

        await _insert("assistant", "replay-query-old", t1)
        await _insert("assistant", "replay-query-new", t2)
        after_ms = int(t1.timestamp() * 1000)

        timeout = httpx.Timeout(10.0, read=15.0)
        async with httpx.AsyncClient(base_url=live_server, timeout=timeout) as client:
            # query 带水位(= t1 的 epoch ms):t1 排除,t2 必须重放(header 路径同语义)
            async with client.stream(
                "GET",
                "/api/store/chat/stream",
                params={"threadId": thread_id, "businessId": "nike", "userId": "u_stream_replay_query", "lastEventId": str(after_ms)},
            ) as res:
                assert res.status_code == 200
                buf = ""
                async for chunk in res.aiter_text():
                    buf += chunk
                    if "replay-query-new" in buf:
                        break
            assert "event: connected" in buf
            assert "replay-query-new" in buf, f"query 水位未触发重放:{buf[-300:]!r}"
            assert "id: " in buf
            assert "replay-query-old" not in buf, f"query 水位之前的消息被重放:{buf!r}"

            # 非数字 query id → 不重放(isdigit 语义与 header 同)
            async with client.stream(
                "GET",
                "/api/store/chat/stream",
                params={"threadId": thread_id, "businessId": "nike", "userId": "u_stream_replay_query", "lastEventId": "NaN"},
            ) as res:
                buf = ""
                async for chunk in res.aiter_text():
                    buf += chunk
                    if "event: heartbeat" in buf:
                        break
            assert "replay-query-new" not in buf, f"非数字 query id 不应触发重放:{buf!r}"


class TestAuth:
    """/api/auth/login|logout|me 契约(auth 真实化新增路由,不在 39 条冻结集内)。

    前置:直接落库一个带 bcrypt 凭证的用户(等价 engine seed 的
    E2E_ACCOUNT_PASSWORD 路径,不经 embedding 种子以便密封环境复用)。
    """

    EMAIL = "auth_contract@example.com"
    PASSWORD = "contract-pass-123"

    async def _ensure_user(self) -> None:
        import bcrypt
        from engine_py.db import get_session
        from sqlalchemy import text

        async with get_session() as session:
            await session.execute(
                text(
                    "INSERT INTO users (email, password_hash) VALUES (:email, :pwd) "
                    "ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash"
                ).bindparams(
                    email=self.EMAIL,
                    pwd=bcrypt.hashpw(self.PASSWORD.encode(), bcrypt.gensalt()).decode(),
                )
            )
            await session.commit()

    async def test_login_success_returns_user_and_jwt(self, client, contract_fixtures):
        await self._ensure_user()
        res = await client.post("/api/auth/login", json={"email": self.EMAIL, "password": self.PASSWORD})
        assert res.status_code == 200
        body = res.json()
        # 成功载荷走统一信封 {success, data:{user, token}}
        assert body["success"] is True
        assert body["data"]["user"]["email"] == self.EMAIL
        assert body["data"]["user"]["id"]
        assert body["data"]["token"]

        import jwt as pyjwt

        claims = pyjwt.decode(body["data"]["token"], options={"verify_signature": False})
        assert claims["sub"] == body["data"]["user"]["id"]
        assert claims["email"] == self.EMAIL
        assert claims["jti"]

    async def test_login_wrong_password_401(self, client, contract_fixtures):
        await self._ensure_user()
        res = await client.post("/api/auth/login", json={"email": self.EMAIL, "password": "wrong-pass"})
        assert res.status_code == 401
        assert res.json() == {"success": False, "error": "邮箱或密码错误"}

    async def test_login_unknown_email_same_401_shape(self, client, contract_fixtures):
        res = await client.post(
            "/api/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
        )
        assert res.status_code == 401
        # 与密码错误同文案同形状(防账号枚举)
        assert res.json() == {"success": False, "error": "邮箱或密码错误"}

    async def test_login_user_without_password_cannot_login(self, client, contract_fixtures):
        from engine_py.db import get_session
        from sqlalchemy import text

        async with get_session() as session:
            await session.execute(
                text("INSERT INTO users (email) VALUES ('nopass@example.com') ON CONFLICT (email) DO NOTHING")
            )
            await session.commit()

        res = await client.post(
            "/api/auth/login", json={"email": "nopass@example.com", "password": "anything"}
        )
        assert res.status_code == 401

    async def test_me_roundtrip_and_logout_revocation(self, client, contract_fixtures):
        await self._ensure_user()
        login = (
            await client.post("/api/auth/login", json={"email": self.EMAIL, "password": self.PASSWORD})
        ).json()
        headers = {"Authorization": f"Bearer {login['data']['token']}"}

        me = await client.get("/api/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json() == {
            "success": True,
            "data": {"user": {"id": login["data"]["user"]["id"], "email": self.EMAIL}},
        }

        out = await client.post("/api/auth/logout", headers=headers)
        assert out.status_code == 200
        assert out.json() == {"success": True}

        # 登出后 jti 进黑名单,me 必须拒绝同一 token
        me_after = await client.get("/api/auth/me", headers=headers)
        assert me_after.status_code == 401
        assert me_after.json()["success"] is False

    async def test_me_without_or_garbage_token_401(self, client, contract_fixtures):
        missing = await client.get("/api/auth/me")
        assert missing.status_code == 401
        garbage = await client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
        assert garbage.status_code == 401


class TestRateLimitContract:
    """限流让冻结路由出现 429 新形状 —— 契约套件钉死(CLAUDE.md 不变量 #6)。

    细粒度行为(窗口滑动/维度独立/SPI 配额)见 tests/test_rate_limit.py;
    此处只钉契约事实:正常路径形状不变,超载返回统一 429 + Retry-After。
    """

    async def test_frozen_route_over_limit_returns_unified_429(self, client, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_KEY_PREFIX", "contract-rl")
        monkeypatch.setenv("RATE_LIMIT_CHAT_TENANT_MAX", "1")
        monkeypatch.setenv("RATE_LIMIT_CHAT_IP_MAX", "1")
        headers = {"x-tenant-id": "contract-rl"}

        first = await client.get("/api/chat/messages", headers=headers)
        assert first.status_code != 429  # 未超限时冻结路由形状原样

        second = await client.get("/api/chat/messages", headers=headers)
        assert second.status_code == 429
        assert second.json() == {"success": False, "error": "请求过于频繁，请稍后再试"}
        assert int(second.headers["retry-after"]) >= 1
