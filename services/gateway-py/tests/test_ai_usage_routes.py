"""AI 用量路由契约(docs/ai-usage-panel.md P0-2;/api/admin/ai-usage/*)。

覆盖:JWT 闸(无 token 401)、平台 all 视角显式 400(无单一配额口径)、summary
自然月窗与归因数学(上月行不计入 / 跨租户 llm 行不计入 —— 快照→造数→快照的
delta 断言,抗同库他例污染)、turns 列表与线程过滤、calls 下钻(异租 job 一律
404 不泄露存在性 / 零 LLM 轮诚实空列表)。
"""

from __future__ import annotations

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from gateway_py.main import app

TENANT = {"x-tenant-id": "aurora"}
DEV_PASSWORD = os.environ.get("E2E_ACCOUNT_PASSWORD", "agent-all-dev")


@pytest.fixture()
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.fixture()
async def auth(client):
    """真实登录换 Bearer token(email → staff_members 角色;与 analytics 契约同链路)。"""
    from engine_py.analytics import rbac

    await rbac.ensure_defaults("aurora")

    async def _login(email: str = "test@example.com", password: str = DEV_PASSWORD) -> dict[str, str]:
        r = await client.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, f"登录失败 {email}: {r.text}"
        return {**TENANT, "Authorization": f"Bearer {r.json()['data']['token']}"}

    return _login


async def _seed_threads(session, tids: list[str]) -> None:
    for tid in tids:
        await session.execute(
            text(
                'INSERT INTO threads (id, "user_id", business_id, status) '
                "VALUES (:t, 'u_usage_probe', 'aurora', 'active') ON CONFLICT (id) DO NOTHING"
            ).bindparams(t=tid)
        )


class TestAiUsageSummary:
    async def test_summary_requires_jwt(self, client):
        r = await client.get("/api/admin/ai-usage/summary", headers=TENANT)
        assert r.status_code == 401

    async def test_summary_pins_tenant_against_all_param(self, client, auth):
        """普通员工租户身份推导钉死(operator_scope):自报 tenantId=all 不采信,
        仍按本租户出数 —— 跨租户合计仅 platform_admin 可达(端点内显式 400 防御)。"""
        boss = await auth()
        r = await client.get("/api/admin/ai-usage/summary", params={"tenantId": "all"}, headers=boss)
        assert r.status_code == 200
        assert r.json()["data"]["businessId"] == "aurora"

    async def test_summary_month_window_and_attribution(self, client, auth):
        boss = await auth()
        suffix = uuid.uuid4().hex[:8]
        thread_a, thread_b = f"usage_th_a_{suffix}", f"usage_th_b_{suffix}"
        job_a, job_g, job_old = f"usage_job_a_{suffix}", f"usage_job_g_{suffix}", f"usage_job_o_{suffix}"

        before = (await client.get("/api/admin/ai-usage/summary", headers=boss)).json()["data"]

        from engine_py.db import get_session

        async with get_session() as session:
            await _seed_threads(session, [thread_a, thread_b])
            # 本月两轮(deep_path 1000 tok / greeting 0 tok)+ 上月一轮(9000 tok,不入窗)
            await session.execute(
                text(
                    "INSERT INTO session_metrics (business_id, thread_id, total_tokens, "
                    "calculated_cost_usd, resolution_status, avg_latency_ms, job_id, turn_path, created_at) VALUES "
                    "('aurora', :ta, 1000, 0.00015, 'resolved_auto', 1500, :ja, 'deep_path', NOW()), "
                    "('aurora', :tb, 0, 0, 'resolved_auto', 120, :jg, 'greeting', NOW()), "
                    "('aurora', :ta, 9000, 0.00135, 'resolved_auto', 3000, :jo, 'deep_path', "
                    "date_trunc('month', NOW()) - INTERVAL '1 day')"
                ).bindparams(ta=thread_a, tb=thread_b, ja=job_a, jg=job_g, jo=job_old)
            )
            # 归因两行(planner+finish,job_a)+ 跨租户探针行(business_id NULL,data agent 形态)
            await session.execute(
                text(
                    "INSERT INTO llm_call_logs (thread_id, business_id, job_id, node, model, "
                    "tokens_in, tokens_out, cost_usd, latency_ms) VALUES "
                    "(:ta, 'aurora', :ja, 'planner', 'test-model', 800, 200, 0.00015, 900), "
                    "(:ta, 'aurora', :ja, 'finish', 'test-model', 500, 100, 0.00009, 700), "
                    "(NULL, NULL, NULL, 'unknown', 'test-model', 50000, 5000, 0.00825, 1200)"
                ).bindparams(ta=thread_a, ja=job_a)
            )
            await session.execute(
                text(
                    "INSERT INTO tenant_billing_quotas (business_id, monthly_limit_tokens) "
                    "VALUES ('aurora', 5000000) ON CONFLICT (business_id) DO UPDATE SET monthly_limit_tokens = 5000000"
                )
            )
            await session.commit()

        after = (await client.get("/api/admin/ai-usage/summary", headers=boss)).json()["data"]
        assert after["quota"]["monthlyLimitTokens"] == 5_000_000
        # 自然月窗:上月 9000 tok 不计入,delta 只含本月两轮
        assert after["quota"]["usedTokens"] - before["quota"]["usedTokens"] == 1000
        assert after["turns"]["total"] - before["turns"]["total"] == 2
        assert round((after["turns"]["avgLatencyMs"] * after["turns"]["total"] - before["turns"]["avgLatencyMs"] * before["turns"]["total"]) / 2) == 810
        # 路径闭集落位:deep_path +1 / greeting +1
        def _path_delta(path: str) -> int:
            return next((p["turns"] for p in after["byPath"] if p["path"] == path), 0) - next(
                (p["turns"] for p in before["byPath"] if p["path"] == path), 0
            )

        assert _path_delta("deep_path") == 1
        assert _path_delta("greeting") == 1
        # 调用明细口径只认归因行:business_id NULL 的 55000 tok 不计入
        assert after["calls"]["total"] - before["calls"]["total"] == 2
        assert after["calls"]["totalTokens"] - before["calls"]["totalTokens"] == 1600


class TestAiUsageTurnsAndCalls:
    async def test_turns_thread_filter_and_order(self, client, auth):
        boss = await auth()
        suffix = uuid.uuid4().hex[:8]
        thread_a, thread_b = f"usage_th_c_{suffix}", f"usage_th_d_{suffix}"
        job_a, job_g, job_old = f"usage_job_c_{suffix}", f"usage_job_d_{suffix}", f"usage_job_e_{suffix}"
        from engine_py.db import get_session

        async with get_session() as session:
            await _seed_threads(session, [thread_a, thread_b])
            await session.execute(
                text(
                    "INSERT INTO session_metrics (business_id, thread_id, total_tokens, "
                    "calculated_cost_usd, resolution_status, avg_latency_ms, job_id, turn_path, created_at) VALUES "
                    "('aurora', :ta, 700, 0.0001, 'resolved_auto', 800, :ja, 'deep_path', NOW()), "
                    "('aurora', :tb, 0, 0, 'resolved_auto', 90, :jg, 'semantic_cache', NOW()), "
                    "('aurora', :ta, 400, 0.00006, 'resolved_auto', 2000, :jo, 'deep_path', "
                    "date_trunc('month', NOW()) - INTERVAL '2 days')"
                ).bindparams(ta=thread_a, tb=thread_b, ja=job_a, jg=job_g, jo=job_old)
            )
            await session.commit()

        r = await client.get("/api/admin/ai-usage/turns", params={"threadId": thread_a}, headers=boss)
        assert r.status_code == 200
        turns = r.json()["data"]["turns"]
        mine = [t for t in turns if t["jobId"] in (job_a, job_old)]
        assert [t["jobId"] for t in mine] == [job_a, job_old]  # 新→旧
        assert mine[0]["turnPath"] == "deep_path"
        assert mine[0]["totalTokens"] == 700
        assert mine[0]["latencyMs"] == 800
        # 未过滤列表不串线程
        r_all = await client.get("/api/admin/ai-usage/turns", params={"threadId": thread_b}, headers=boss)
        assert {t["jobId"] for t in r_all.json()["data"]["turns"] if t["jobId"] == job_g} == {job_g}
        assert all(t["threadId"] == thread_b for t in r_all.json()["data"]["turns"])

    async def test_calls_drilldown_and_cross_tenant_404(self, client, auth):
        boss = await auth()
        suffix = uuid.uuid4().hex[:8]
        thread_a = f"usage_th_x_{suffix}"
        job_a, job_g, job_n = f"usage_job_x_{suffix}", f"usage_job_y_{suffix}", f"usage_job_z_{suffix}"
        from engine_py.db import get_session

        async with get_session() as session:
            await _seed_threads(session, [thread_a])
            await session.execute(
                text(
                    'INSERT INTO threads (id, "user_id", business_id, status) '
                    "VALUES (:tn, 'u_usage_probe', 'usage_probe_biz', 'active') ON CONFLICT (id) DO NOTHING"
                ).bindparams(tn=f"usage_th_n_{suffix}")
            )
            await session.execute(
                text(
                    "INSERT INTO session_metrics (business_id, thread_id, total_tokens, "
                    "calculated_cost_usd, resolution_status, avg_latency_ms, job_id, turn_path, created_at) VALUES "
                    "('aurora', :ta, 1000, 0.00015, 'resolved_auto', 1500, :ja, 'deep_path', NOW()), "
                    "('aurora', :ta, 0, 0, 'resolved_auto', 60, :jg, 'greeting', NOW()), "
                    "('usage_probe_biz', :tn, 50, 0, 'resolved_auto', 10, :jn, 'deep_path', NOW())"
                ).bindparams(ta=thread_a, ja=job_a, jg=job_g, jn=job_n, tn=f"usage_th_n_{suffix}")
            )
            await session.execute(
                text(
                    "INSERT INTO llm_call_logs (thread_id, business_id, job_id, node, model, "
                    "tokens_in, tokens_out, cost_usd, latency_ms) VALUES "
                    "(:ta, 'aurora', :ja, 'planner', 'test-model', 800, 200, 0.00015, 900), "
                    "(:ta, 'aurora', :ja, 'finish', 'test-model', 500, 100, 0.00009, 700)"
                ).bindparams(ta=thread_a, ja=job_a)
            )
            await session.commit()

        # 归属先验:本租户轮 → 调用明细按 job_id 精确取出
        r = await client.get("/api/admin/ai-usage/calls", params={"jobId": job_a}, headers=boss)
        assert r.status_code == 200
        calls = r.json()["data"]["calls"]
        assert [c["node"] for c in calls] == ["planner", "finish"]
        assert calls[0]["totalTokens"] == 1000
        assert calls[0]["tokensIn"] == 800 and calls[0]["tokensOut"] == 200
        # 零 LLM 轮(问候旁路)诚实空列表
        r_g = await client.get("/api/admin/ai-usage/calls", params={"jobId": job_g}, headers=boss)
        assert r_g.status_code == 200
        assert r_g.json()["data"]["calls"] == []
        # 异租 job 一律 404(不泄露存在性);未知 job 同型
        r_n = await client.get("/api/admin/ai-usage/calls", params={"jobId": job_n}, headers=boss)
        assert r_n.status_code == 404
        r_u = await client.get("/api/admin/ai-usage/calls", params={"jobId": str(uuid.uuid4())}, headers=boss)
        assert r_u.status_code == 404
