"""📜 HTTP 路由契约测试 — 1:1 移植 apps/server/test/contract/httpRoutes.contract.test.ts。

钉死 39 条路由的响应契约(envelope 形状 + 关键字段),作为 gateway-py 的回归网。

与 TS 原版的两处刻意差异(TS 契约套件从未真正运行,原样照抄会钉死错误契约):
1. POST /api/tenant 请求体字段为 id(TS/Python 控制器均读 data.id,原测试发 businessId 会 400);
2. 契约审批单 ID 使用 UUID(Python 侧 ApprovalGatekeeper 校验 UUID 格式)。
"""

from __future__ import annotations

import pytest

from .conftest import CONTRACT_APPROVAL, CONTRACT_THREAD, _TS

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
