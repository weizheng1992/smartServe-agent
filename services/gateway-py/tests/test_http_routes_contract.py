"""📜 HTTP 路由契约测试 — 1:1 移植 apps/server/test/contract/httpRoutes.contract.test.ts。

钉死 39 条路由的响应契约(envelope 形状 + 关键字段),作为 gateway-py 的回归网。

与 TS 原版的两处刻意差异(TS 契约套件从未真正运行,原样照抄会钉死错误契约):
1. POST /api/tenant 请求体字段为 id(TS/Python 控制器均读 data.id,原测试发 businessId 会 400);
2. 契约审批单 ID 使用 UUID(Python 侧 ApprovalGatekeeper 校验 UUID 格式)。
"""

from __future__ import annotations

import pytest

from .conftest import _TS, CONTRACT_APPROVAL, CONTRACT_THREAD

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

    async def test_list_contains_seeded_tenants(self, client, contract_fixtures):
        res = await client.get("/api/tenant/list")
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert isinstance(body["tenants"], list)
        ids = [t["id"] for t in body["tenants"]]
        assert "nike" in ids
        assert "adidas" in ids

    async def test_create_list_delete_roundtrip(self, client, contract_fixtures):
        ct_id = f"ct_{_TS}"
        create_res = await client.post("/api/tenant", json={"id": ct_id, "name": "契约测试租户"})
        assert create_res.status_code in (200, 201)
        assert create_res.json()["success"] is True

        list_after_create = await client.get("/api/tenant/list")
        created = next((t for t in list_after_create.json()["tenants"] if t["id"] == ct_id), None)
        assert created is not None

        del_res = await client.delete(f"/api/tenant/{created['id']}")
        assert del_res.status_code == 200
        assert del_res.json()["success"] is True

    async def test_update_tenant_roundtrip(self, client, contract_fixtures):
        ut_id = f"ut_{_TS}"
        create_res = await client.post(
            "/api/tenant",
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
        list_res = await client.get("/api/tenant/list")
        updated = next((t for t in list_res.json()["tenants"] if t["id"] == ut_id), None)
        assert updated is not None
        assert updated["name"] == "契约测试租户V2"
        assert updated["refundLimit"] == 500
        assert updated["industry"] == "跨境母婴"

        ghost_res = await client.put(f"/api/tenant/ghost_{_TS}", json={"name": "幽灵租户"})
        assert ghost_res.status_code == 404

        await client.delete(f"/api/tenant/{ut_id}")


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

    async def test_admin_conversations_rejects_unregistered_tenant(self, client, contract_fixtures):
        res = await client.get("/api/admin/conversations", params={"tenantId": f"ghost_{_TS}"})
        assert res.status_code == 403
        assert res.json()["success"] is False

    async def test_admin_conversations_all_aggregate_view_passes(self, client, contract_fixtures):
        # "all" 为聚合视图参数,非单租户扮演,不受门禁拦截
        res = await client.get("/api/admin/conversations", params={"tenantId": "all"})
        assert res.status_code == 200
        assert res.json()["success"] is True


class TestStoreOrdersStrictScoping:
    """商户订单列表严格归属(2026-09-05):/api/store/orders 不得再 OR CUST-8801
    混入演示用户订单。背景 bug:任何 customerId 查询都会带出张伟(CUST-8801)
    的订单,与聊天侧视图永久不一致且跨用户泄漏。"""

    async def test_store_orders_scoped_to_requested_customer(self, client, contract_fixtures):
        import json as _json

        from sqlalchemy import text

        from gateway_py.merchant_db import ensure_merchant_tables, merchant_engine

        await ensure_merchant_tables()
        async with merchant_engine().begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, "
                    "shipping_address) VALUES (:oid, :cid, 'PAID', 100, CAST(:addr AS jsonb)) "
                    "ON CONFLICT (order_id) DO NOTHING"
                ).bindparams(
                    oid="CT-ORD-SCOPE-A",
                    cid="CUST-CT-SCOPE-A",
                    addr=_json.dumps({"fullAddress": "契约测试地址"}),
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, "
                    "shipping_address) VALUES (:oid, :cid, 'PAID', 200, CAST(:addr AS jsonb)) "
                    "ON CONFLICT (order_id) DO NOTHING"
                ).bindparams(
                    oid="CT-ORD-SCOPE-8801",
                    cid="CUST-8801",
                    addr=_json.dumps({"fullAddress": "契约测试地址"}),
                )
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


class TestSkills:
    async def test_registry(self, client, contract_fixtures):
        res = await client.get("/api/skills/registry")
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert isinstance(body["skills"], list)
        assert len(body["skills"]) >= 5

    async def test_get_config(self, client, contract_fixtures):
        res = await client.get("/api/skills/config", headers={"x-tenant-id": "nike"})
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["tenantId"] == "nike"
        assert isinstance(body["skills"], list)

    async def test_put_config(self, client, contract_fixtures):
        res = await client.put(
            "/api/skills/config",
            headers={"x-tenant-id": "nike"},
            json={"skillId": "skill_order_refund", "approvalThresholdAmount": 260},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["tenantId"] == "nike"
        assert body["skillId"] == "skill_order_refund"
        assert body["config"] is not None

    async def test_tenant_alias_route(self, client, contract_fixtures):
        res = await client.get("/api/skills/tenant", headers={"x-tenant-id": "nike"})
        assert res.status_code == 200
        assert res.json()["tenantId"] == "nike"

    async def test_patch_tenant_skill(self, client, contract_fixtures):
        res = await client.patch(
            "/api/skills/tenant/skill_order_refund",
            headers={"x-tenant-id": "nike"},
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

    async def test_resolve_fixture_approval(self, client, contract_fixtures):
        res = await client.post(
            "/api/approvals",
            headers={"x-tenant-id": "nike"},
            json={"approvalId": CONTRACT_APPROVAL, "action": "approve"},
        )
        assert res.status_code == 200
        body = res.json()
        # process_approval_action 透传结果:status 推进为 approved 或显式 success
        assert body.get("status") == "approved" or body.get("success") is True


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
        res = await client.get(
            "/api/chat/orders", params={"userId": "CUST-8801", "businessId": "ecommerce"}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert isinstance(body["orders"], list)


class TestConversations:
    async def test_list_pagination_contains_fixture(self, client, contract_fixtures):
        res = await client.get(
            "/api/conversations",
            params={"tenantId": "nike", "status": "all", "limit": 20, "offset": 0},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["tenantId"] == "nike"
        assert "total" in body
        items = body.get("conversations") or body.get("data") or []
        ids = [c.get("threadId") or c.get("id") for c in items]
        assert CONTRACT_THREAD in ids

    async def test_detail_timeline(self, client, contract_fixtures):
        res = await client.get(f"/api/conversations/{CONTRACT_THREAD}", headers={"x-tenant-id": "nike"})
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["data"]["thread"]["businessId"] == "nike"
        assert isinstance(body["data"]["messages"], list)

    async def test_update_status(self, client, contract_fixtures):
        res = await client.post(
            f"/api/conversations/{CONTRACT_THREAD}/status",
            headers={"x-tenant-id": "nike"},
            json={"status": "human_takeover", "assignedOperatorId": "op_contract"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["data"] is not None


class TestRagDocuments:
    async def test_crud_roundtrip(self, client, contract_fixtures):
        create_res = await client.post(
            "/api/rag/documents",
            headers={"x-tenant-id": "nike"},
            json={"chunkText": "契约测试:Nike 退换货政策 30 天内可退。"},
        )
        assert create_res.status_code == 201
        assert create_res.json()["success"] is True
        doc_id = create_res.json()["data"]["id"]

        list_res = await client.get("/api/rag/documents", params={"tenantId": "nike"})
        assert list_res.status_code == 200
        body = list_res.json()
        assert body["success"] is True
        assert body["tenantId"] == "nike"
        assert body["total"] >= 1
        assert isinstance(body["data"], list)

        del_res = await client.delete(f"/api/rag/documents/{doc_id}", headers={"x-tenant-id": "nike"})
        assert del_res.status_code == 200
        assert del_res.json()["success"] is True
        assert isinstance(del_res.json()["message"], str)


class TestPersonas:
    async def test_crud_roundtrip(self, client, contract_fixtures):
        create_res = await client.post(
            "/api/personas",
            headers={"x-tenant-id": "nike"},
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

        list_res = await client.get("/api/personas", params={"tenantId": "nike"})
        assert list_res.status_code == 200
        body = list_res.json()
        assert body["success"] is True
        assert body["total"] >= 1
        assert any(f["id"] == fact_id for f in body["data"])

        put_res = await client.put(
            f"/api/personas/{fact_id}", headers={"x-tenant-id": "nike"}, json={"confidence": 0.9}
        )
        assert put_res.status_code == 200
        assert put_res.json()["success"] is True
        assert put_res.json()["data"] is not None

        del_res = await client.delete(f"/api/personas/{fact_id}", headers={"x-tenant-id": "nike"})
        assert del_res.status_code == 200
        assert del_res.json()["success"] is True


class TestGuardrails:
    async def test_crud_roundtrip(self, client, contract_fixtures):
        create_res = await client.post(
            "/api/guardrails",
            headers={"x-tenant-id": "nike"},
            json={"ruleName": "契约-禁词", "ruleType": "keyword", "pattern": "诈骗"},
        )
        assert create_res.status_code == 201
        assert create_res.json()["success"] is True
        rule_id = create_res.json()["data"]["id"]

        list_res = await client.get("/api/guardrails", params={"tenantId": "nike"})
        assert list_res.status_code == 200
        body = list_res.json()
        assert body["success"] is True
        assert body["tenantId"] == "nike"
        assert body["total"] >= 1

        put_res = await client.put(
            f"/api/guardrails/{rule_id}", headers={"x-tenant-id": "nike"}, json={"severity": "high"}
        )
        assert put_res.status_code == 200
        assert put_res.json()["success"] is True

        del_res = await client.delete(f"/api/guardrails/{rule_id}", headers={"x-tenant-id": "nike"})
        assert del_res.status_code == 200
        assert del_res.json()["success"] is True


class TestBilling:
    async def test_usages_returns_array(self, client, contract_fixtures):
        res = await client.get("/api/billing/usages")
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)

    async def test_put_quota(self, client, contract_fixtures):
        res = await client.put(
            "/api/billing/quota", json={"businessId": "nike", "monthlyLimitTokens": 5_000_000}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["data"] is not None


class TestEvals:
    async def test_results_total_and_data(self, client, contract_fixtures):
        res = await client.get("/api/evals/results")
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert isinstance(body["total"], (int, float))
        assert isinstance(body["data"], list)

    async def test_run_local_random_metrics(self, client, contract_fixtures):
        res = await client.post(
            "/api/evals/run", json={"datasetName": "contract_dataset", "runName": f"contract_{_TS}"}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["data"] is not None


class TestLogs:
    async def test_success_envelope(self, client, contract_fixtures):
        res = await client.get("/api/logs", params={"tenantId": "nike"})
        assert res.status_code == 200
        assert res.json()["success"] is True


class TestMerchantStoreChatStream:
    """SSE 通道 thread:{threadId}:message — 回归钉:stream 路由必须真正以 SSE 流式返回。

    历史缺陷:曾用普通 ``Response(async_generator)`` 返回,Starlette ``render()``
    对非 bytes 内容调用 ``.encode`` → 构造期 AttributeError → 500。

    走 live_server 而非 session 级 ``client``(ASGITransport):SSE 通道不依赖
    种子租户数据,且 in-process 传输下"订阅后 publish"结构性死锁(见用例内注释)。
    """

    async def test_stream_returns_sse_and_relays_pubsub(self, live_server):
        import asyncio
        import json as _json

        import httpx
        from engine_py.event_bus import get_client as get_redis_client

        # SSE 必须走真网络栈:ASGITransport 把 app 跑完才进 stream 上下文,
        # "订阅后 publish、断言转发"在 in-process 传输下结构性死锁。
        thread_id = f"merchant_stream_{_TS}"
        timeout = httpx.Timeout(10.0, read=30.0)

        async with (
            httpx.AsyncClient(base_url=live_server, timeout=timeout) as client,
            client.stream("GET", "/api/store/chat/stream", params={"threadId": thread_id}) as res,
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
                        await redis.publish(
                            f"thread:{thread_id}:message", _json.dumps({"text": "contract-relay"})
                        )
                    buf += chunk
                    if "event: message" in buf:
                        break

                assert "event: connected" in buf
                assert f'"threadId": "{thread_id}"' in buf
                # 订阅建立后,经由 Redis pub/sub 频道发布的消息应被原样转发
                assert "event: message" in buf
                assert '"text": "contract-relay"' in buf
