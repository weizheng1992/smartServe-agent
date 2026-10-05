"""夜间 agent 评测跑批器(每晚 23:00 durable cron;真实 LLM 会话)。

用法::

    cd services/gateway-py && uv run python ../../eval/nightly/run_nightly.py [--base http://localhost:4000]

前置:网关 4000 在跑(docker + seed + gateway --env-file);栈不可用退出码 2
(防假红 —— 环境问题与 agent 退化严格分账)。

判分 = 场景信号(scenarios.py)+ 全局编造检查(回答中的商户单号必须属于
种子集 ∪ 本夜新建)+ HITL 观察(waiting 审批单按线程计数差)+ 延迟记录。
advisory 场景只记录不断言(措辞开放,转晨审)。

失败喂飞轮:客服侧失败入坏例池(record_badcase_signal,静默降级不阻断);
Data Agent 未命中由管线自身落 agent_unanswered。结果落
eval/nightly/results/<时间戳>/{report.html, results.jsonl, 清单见 HTML}。

成本护栏:总轮次上限 ``MAX_TURNS``(超限跳过剩余场景并如实标注 skipped),
每轮 HTTP 超时 90s,失败不重试(LLM 会话重试必烧双份配额)。
数据隔离:顾客/线程一律 ``NIGHTLY_`` 前缀,收尾清理订单+回补库存+删线程
(审计类记录按仓库约定保留)。
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import html
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

BASE = os.environ.get("NIGHTLY_BASE_URL", "http://localhost:4000")
TENANT = "aurora"
STAFF_EMAIL = os.environ.get("NIGHTLY_STAFF_EMAIL", "test@example.com")
STAFF_PASSWORD = os.environ.get("NIGHTLY_STAFF_PASSWORD", "agent-all-dev")
MAX_TURNS = 130
TURN_TIMEOUT = 90.0
NIGHT = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
CUST_PREFIX = "NIGHTLY"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scenarios import CUSTOMER_CASES, DATA_CASES, MENU_CASES  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent / "results" / NIGHT


def _load_env() -> None:
    """services/.env 装载(setdefault 不覆盖)——engine/gateway 模块 import 时读 env。"""
    for cand in (ROOT / "services" / ".env", ROOT / ".env"):
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip('"'))
                    if k.strip() == "DATABASE_URL":
                        os.environ.setdefault("MERCHANT_DATABASE_URL", "")
            if os.environ.get("DATABASE_URL") and not os.environ.get("MERCHANT_DATABASE_URL"):
                import re as _re

                os.environ["MERCHANT_DATABASE_URL"] = _re.sub(
                    r"/[^/]+$", "/agent_merchant", os.environ["DATABASE_URL"]
                )
            return


async def health_check(client: httpx.AsyncClient) -> bool:
    try:
        r = await client.get("/api/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 客服 agent
# ---------------------------------------------------------------------------

_ORDER_ID_RE = re.compile(r"AURORA-ORD-2026-(\d{4})")
_PHONE_RE = re.compile(r"1[3-9]\d{9}")


async def approvals_waiting(client: httpx.AsyncClient, thread_id: str) -> set[str]:
    r = await client.get("/api/chat/approvals", params={"tenantId": TENANT, "status": "waiting"})
    if r.status_code != 200:
        return set()
    return {
        a.get("approvalId") or a.get("id") or ""
        for a in (r.json().get("approvals") or [])
        if (a.get("threadId") == thread_id)
    }


async def _create_nightly_order(client, customer_id: str) -> str:
    """夜测顾客自购真单(种子货架咖啡套装 ×1):售后/HITL 场景的归属前置。"""
    r = await client.get("/api/store/products")
    sku_code = ""
    for p in r.json().get("products") or []:
        if "咖啡" in str(p.get("title") or ""):
            skus = p.get("skus") or []
            sku_code = str(skus[0].get("skuCode")) if skus else ""
            break
    if not sku_code:
        return ""
    r = await client.post(
        "/api/store/orders",
        json={
            "customerId": customer_id,
            "skuCode": sku_code,
            "quantity": 1,
            "recipientName": "夜测",
            "recipientPhone": "13800001111",
            "shippingAddress": "北京市海淀区夜测路 1 号",
        },
        timeout=60,
    )
    return str((r.json() or {}).get("orderId") or "")


async def run_customer_case(client, case, seeded_ids: set[str], created_ids: set[str], budget: dict) -> dict:
    """跑一个客服场景(多轮连续 threadId);返回逐轮结果与裁决。"""
    thread_id = f"nightly_{case.case_id}_{int(time.time())}"
    # 顾客 id 带每夜唯一后缀:引擎侧购物车按 userId 挂账(Redis),case_id 恒定
    # 会跨跑残留(首夜实弹:上次失败跑的瑜伽垫混进本次结算)
    customer_id = f"{CUST_PREFIX}_{case.case_id}_{NIGHT}"
    order_id = ""
    if case.setup == "order":
        order_id = await _create_nightly_order(client, customer_id)
        if order_id:
            created_ids.add(order_id)
    turns_out = []
    verdict_fail = []
    prior_approvals = await approvals_waiting(client, thread_id)
    customer_order_ids: set[str] = set()
    ok = True
    for i, turn in enumerate(case.turns, 1):
        if budget["turns"] >= MAX_TURNS:
            turns_out.append({"turn": i, "skipped": True, "message": turn.message})
            continue
        budget["turns"] += 1
        t0 = time.monotonic()
        message = turn.message.replace("{order_id}", order_id) if order_id else turn.message.replace("{order_id}", "AURORA-ORD-2026-0000")
        try:
            images = [budget.get("image_map", {}).get(u, u) for u in turn.image_urls]
            r = await client.post(
                "/api/store/chat",
                json={"message": message, "businessId": TENANT, "userId": customer_id, "threadId": thread_id,
                      **({"imageUrls": images} if images else {})},
                timeout=TURN_TIMEOUT,
            )
            latency = round(time.monotonic() - t0, 1)
            body = r.json() if r.status_code == 200 else {}
            output = str(body.get("output") or body.get("result") or "")
        except Exception as err:
            latency = round(time.monotonic() - t0, 1)
            output, r = "", None
            turns_out.append({"turn": i, "error": repr(err), "latency_s": latency})
            if not turn.advisory:
                ok = False
                verdict_fail.append(f"轮{i} 请求异常 {err!r}")
            continue

        row = {"turn": i, "message": message[:200], "output": output[:1200], "latency_s": latency}
        fails = []
        # 传输层契约断言(空消息 400 等):不走 LLM 判分
        if turn.expect_http is not None:
            if r.status_code != turn.expect_http:
                fails.append(f"HTTP {r.status_code} ≠ 期望 {turn.expect_http}")
            row["http"] = r.status_code
            if fails and not turn.advisory:
                ok = False
                verdict_fail.extend(f"轮{i}: {f}" for f in fails)
            row["fails"] = fails
            turns_out.append(row)
            prior_approvals = await approvals_waiting(client, thread_id)
            continue
        # 场景信号
        if turn.contains_any:
            if not any(kw.lower() in output.lower() for kw in turn.contains_any):
                fails.append(f"缺锚点 {turn.contains_any}")
        for kw in turn.not_contains:
            if kw.startswith("1[3-9]"):  # 手机号正则特例
                if _PHONE_RE.search(output):
                    fails.append("泄漏手机号形态")
            elif kw.lower() in output.lower():
                fails.append(f"出现禁词 {kw}")
        if not output.strip():
            fails.append("空回复")
        # HITL 观察
        now_waiting = await approvals_waiting(client, thread_id)
        new = now_waiting - prior_approvals
        row["new_approvals"] = len(new)
        if turn.expect_new_approval and not new:
            fails.append("应挂起 HITL 未挂起")
        if turn.expect_no_new_approval and new:
            fails.append("不应挂起却新建了审批单")
        prior_approvals = now_waiting
        # 全局编造检查:回答中的商户单号必须在种子集 ∪ 本夜新建 ∪ 本顾客真实订单;
        # 用户自己报出的单号被诚实回显(「未查询到订单 X」)不算编造 —— 编造 =
        # 无中生有,不是回声。聊天结算当轮生成的单号不在任何预登记集里 →
        # 未知名号先查本顾客订单刷新(存在即真实),查无才判编造
        for frag in _ORDER_ID_RE.findall(output):
            oid = f"AURORA-ORD-2026-{frag}"
            if oid in seeded_ids | created_ids | customer_order_ids or oid in turn.message:
                continue
            try:
                r2 = await client.get("/api/store/orders",
                                      params={"customerId": customer_id, "limit": 50})
                for o in (r2.json() or {}).get("orders") or []:
                    created_ids.add(str(o.get("orderId") or ""))
                    customer_order_ids.add(str(o.get("orderId") or ""))
            except Exception:
                pass
            if oid not in created_ids and oid not in turn.message:
                fails.append(f"编造单号 {oid}")
        # 转人工排队:线程真源须翻 human_takeover(engine takeover.mark_takeover_requested)
        if turn.expect_takeover:
            tr = await client.get("/api/store/chat/messages",
                                  params={"threadId": thread_id, "businessId": TENANT})
            tstatus = str(((tr.json() or {}).get("thread") or {}).get("status") or "")
            row["thread_status"] = tstatus
            if tstatus != "human_takeover":
                fails.append(f"转人工未接管: thread.status={tstatus or '未知'}")
        if fails and not turn.advisory:
            ok = False
            verdict_fail.extend(f"轮{i}: {f}" for f in fails)
        elif fails:
            row["advisory_notes"] = fails
        row["fails"] = fails
        turns_out.append(row)

    # 收尾:删线程(审计记录按仓库约定保留)
    try:
        await client.request(
            "DELETE", "/api/chat/threads", params={"threadId": thread_id, "userId": customer_id}
        )
    except Exception:
        pass
    return {
        "kind": "customer",
        "case_id": case.case_id,
        "dimension": case.dimension,
        "ok": ok,
        "thread_id": thread_id,
        "turns": turns_out,
        "fails": verdict_fail,
    }


# ---------------------------------------------------------------------------
# Data Agent
# ---------------------------------------------------------------------------


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    frames = []
    for block in text.split("\n\n"):
        ev, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                ev = line[7:].strip()
            elif line.startswith("data: "):
                data = line[6:]
        if ev is not None:
            try:
                frames.append((ev, json.loads(data) if data else {}))
            except Exception:
                frames.append((ev, {"raw": data}))
    return frames


async def run_data_case(client, tokens: dict[str, str], case, budget: dict) -> dict:
    if budget["turns"] >= MAX_TURNS:
        return {"kind": "data", "case_id": case.case_id, "dimension": case.dimension,
                "ok": True, "skipped": True, "fails": []}
    token = tokens.get(case.staff_email) or ""
    if not token:
        return {"kind": "data", "case_id": case.case_id, "dimension": case.dimension,
                "ok": False, "fails": [f"员工 {case.staff_email} 无 token"], "advisory": case.advisory}
    budget["turns"] += len(case.turns) if case.turns else 1
    t0 = time.monotonic()
    fails: list[str] = []
    questions = case.turns or [case.question]
    session_id = f"nightly_{case.case_id}"
    qa_rows: list[dict] = []
    frames: list[tuple[str, dict]] = []
    status_code = 0
    for qi, q in enumerate(questions, 1):
        try:
            body = {"question": q}
            if case.turns:
                body["pageContext"] = {"sessionId": session_id}
            r = await client.post(
                "/api/admin/analytics/ask",
                headers={"x-tenant-id": TENANT, "Authorization": f"Bearer {token}"},
                json=body,
                timeout=TURN_TIMEOUT,
            )
            status_code = r.status_code
            frames = _parse_sse(r.text) if r.status_code == 200 else []
        except Exception as err:
            return {"kind": "data", "case_id": case.case_id, "dimension": case.dimension,
                    "ok": False, "error": repr(err), "fails": [f"请求异常 {err!r}"],
                    "latency_s": round(time.monotonic() - t0, 1)}
        qa_rows.append({"q": q, "frames": [ev for ev, _ in frames if ev != "heartbeat"],
                        "payloads": [{"event": ev, "data": d} for ev, d in frames if ev != "heartbeat"]})
    latency = round(time.monotonic() - t0, 1)
    typed = [(ev, data) for ev, data in frames if ev != "heartbeat"]
    types = [ev for ev, _ in typed]
    has_result = "result" in types
    if case.expect_frame == "result" and not has_result:
        fails.append(f"未出结果帧,实际 {types}")
    if case.expect_frame == "not_result" and has_result:
        fails.append(f"越权出结果帧 {types}(应 unsupported/error/clarify)")
    if case.expect_frame == "clarify_metric":
        cl = next((d for ev, d in typed if ev == "clarify"), {})
        if "clarify" not in types or str((cl or {}).get("clarifyKind")) != "metric":
            fails.append(f"指标歧义须出 metric clarify,实际 {types} {str(cl)[:160]}")
    if r.status_code != 200:
        fails.append(f"HTTP {r.status_code}")
    ok = not fails or case.advisory
    return {"kind": "data", "case_id": case.case_id, "dimension": case.dimension,
            "question": case.question, "frames": types, "qa": qa_rows,
            "frame_payloads": [{"event": ev, "data": d} for ev, d in typed],
            "ok": ok, "fails": fails,
            "advisory": case.advisory, "latency_s": latency, "staff": case.staff_email}


async def _owner_perms(client, tokens: dict[str, str]) -> set[str]:
    r = await client.get("/api/admin/analytics/menus",
                         headers={"x-tenant-id": TENANT, "Authorization": f"Bearer {tokens.get(STAFF_EMAIL, '')}"})
    return set((r.json() or {}).get("perms") or []) if r.status_code == 200 else set()


async def run_menu_case(client, owner_perms: set[str], case, tokens: dict[str, str]) -> dict:
    """商户端菜单/按钮可见性矩阵(0013 RBAC):登录各角色 → GET /menus,
    断言 role 回显、菜单/按钮非空、按钮闭集 ⊆ 老板全量;受限角色严格小于老板。"""
    email = case.staff_email
    token = tokens.get(email) or ""
    if not token:
        return {"kind": "menu", "case_id": case.case_id, "dimension": case.dimension,
                "ok": False, "fails": [f"员工 {email} 无 token"], "advisory": False}
    r = await client.get("/api/admin/analytics/menus",
                         headers={"x-tenant-id": TENANT, "Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        return {"kind": "menu", "case_id": case.case_id, "dimension": case.dimension,
                "ok": False, "fails": [f"HTTP {r.status_code}"], "advisory": False}
    body = r.json()
    role = str(body.get("role") or "")
    perms = set(body.get("perms") or [])
    menus = body.get("menus") or []
    fails = []
    if not menus:
        fails.append("菜单树为空")
    if not perms:
        fails.append("按钮权限闭集为空")
    if not perms <= owner_perms:
        fails.append(f"按钮集越过老板全量 {sorted(perms - owner_perms)}")
    if case.expect == "owner_baseline" and role != "finance_owner":
        fails.append(f"角色回显 {role} ≠ finance_owner")
    if case.expect == "subset" and len(perms) >= len(owner_perms):
        fails.append(f"受限角色按钮数 {len(perms)} 未小于老板 {len(owner_perms)}")
    # subset_nonstrict:admin 全量与老板相等是文档口径(0013),只断 ⊆ 与非空
    return {"kind": "menu", "case_id": case.case_id, "dimension": case.dimension,
            "ok": not fails, "fails": fails, "role": role,
            "menus_count": len(menus), "perms_count": len(perms), "perms": sorted(perms)}


# ---------------------------------------------------------------------------
# 清理与报告
# ---------------------------------------------------------------------------


async def run_isolation_case(client) -> dict:
    """会话隔离(确定性,零 LLM 断言):顾客 X 的线程绝不出现在顾客 Y 的列表。"""
    x_user, y_user = f"{CUST_PREFIX}_iso_x", f"{CUST_PREFIX}_iso_y"
    thread_id = f"nightly_iso_{int(time.time())}"
    r = await client.post("/api/store/chat", json={
        "message": "在吗", "businessId": TENANT, "userId": x_user, "threadId": thread_id,
    }, timeout=TURN_TIMEOUT)
    if r.status_code != 200:
        return {"kind": "perf", "case_id": "c23_会话隔离", "dimension": "多场景·会话",
                "ok": False, "fails": [f"X 建线程 HTTP {r.status_code}"]}
    ry = await client.get("/api/store/chat/messages",
                          params={"userId": y_user, "businessId": TENANT})
    y_threads = (ry.json() or {}).get("userThreads") or []
    leak = [t for t in y_threads if t.get("threadId") == thread_id]
    rx = await client.get("/api/store/chat/messages",
                          params={"userId": x_user, "businessId": TENANT, "threadId": thread_id})
    x_sees = (rx.json() or {}).get("threadId") == thread_id
    await client.request("DELETE", "/api/chat/threads",
                         params={"threadId": thread_id, "userId": x_user})
    fails = []
    if leak:
        fails.append("X 的线程泄漏进 Y 的会话列表")
    if not x_sees:
        fails.append("X 自己反而看不到自己的线程")
    return {"kind": "perf", "case_id": "c23_会话隔离", "dimension": "多场景·会话",
            "ok": not fails, "fails": fails}


async def run_concurrency(client) -> dict:
    """5 路并发真实会话:不 500、不串话、并发延迟记录(优化预算数据源)。"""
    async def one(i: int):
        t0 = time.monotonic()
        try:
            r = await client.post("/api/store/chat", json={
                "message": "推荐一款背包", "businessId": TENANT,
                "userId": f"{CUST_PREFIX}_conc_{i}", "threadId": f"nightly_conc_{i}",
            }, timeout=120)
            ok = r.status_code == 200 and (r.json() or {}).get("success") is True
            return r.status_code, round(time.monotonic() - t0, 1), ok
        except Exception as err:
            return 0, round(time.monotonic() - t0, 1), repr(err)[:80]

    rs = await asyncio.gather(*(one(i) for i in range(5)))
    fails = [f"并发路{i}: HTTP {s} / {err if isinstance(err, str) else ''}"
             for i, (s, _, ok) in enumerate(rs) if s != 200 or ok is not True]
    for i in range(5):
        await client.request("DELETE", "/api/chat/threads",
                             params={"threadId": f"nightly_conc_{i}", "userId": f"{CUST_PREFIX}_conc_{i}"})
    return {"kind": "perf", "case_id": "p01_并发5路", "dimension": "优化·并发",
            "ok": not fails, "fails": fails, "latencies": [l for _, l, _ in rs]}


async def run_sse_bridge(client) -> dict:
    """顾客侧 SSE 桥存活:订阅 store 流后 AI 回复须在 35s 内以 message 帧送达。"""
    thread_id = f"nightly_sse_{int(time.time())}"
    got = {"message": False}
    stop = {"stop": False}

    # 属主闸前置:store 流订阅要求线程已存在(查无 404 掐流是正确行为)——
    # 先显式建线程,再开流,再发消息(首夜实弹:流先开订阅即 404 空收)
    await client.post("/api/chat/threads", json={
        "threadId": thread_id, "businessId": TENANT, "userId": f"{CUST_PREFIX}_sse",
    }, timeout=30)

    async def listen():
        async with client.stream("GET", "/api/store/chat/stream",
                                 params={"threadId": thread_id, "businessId": TENANT},
                                 timeout=45) as resp:
            async for chunk in resp.aiter_text():
                if "event: message" in chunk:
                    got["message"] = True
                    return
                if stop["stop"]:
                    return

    task = asyncio.create_task(listen())
    await asyncio.sleep(1.5)
    await client.post("/api/store/chat", json={
        "message": "在吗,推荐一款背包", "businessId": TENANT,
        "userId": f"{CUST_PREFIX}_sse", "threadId": thread_id,
    }, timeout=TURN_TIMEOUT)
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=35)
    except asyncio.TimeoutError:
        stop["stop"] = True
    await client.request("DELETE", "/api/chat/threads",
                         params={"threadId": thread_id, "userId": f"{CUST_PREFIX}_sse"})
    return {"kind": "perf", "case_id": "p02_SSE桥存活", "dimension": "优化·实时",
            "ok": got["message"], "fails": [] if got["message"] else ["35s 内未收到顾客侧 message 帧"]}


async def cleanup() -> dict:
    """NIGHTLY_ 前缀数据回收:订单/行项目删除 + 库存回补 + 演示客户不触碰。"""
    from gateway_py.merchant_db import ensure_merchant_tables, merchant_engine
    from sqlalchemy import text as _t

    await ensure_merchant_tables()
    restored: dict[str, int] = {}
    deleted_orders = 0
    async with merchant_engine().begin() as conn:
        rows = (
            await conn.execute(
                _t("SELECT order_id, customer_id FROM merchant_orders WHERE customer_id LIKE :p"),
                {"p": f"{CUST_PREFIX}%"},
            )
        ).mappings().all()
        if rows:
            ids = [r["order_id"] for r in rows]
            item_rows = (
                await conn.execute(
                    _t("SELECT sku_code, quantity FROM merchant_order_items WHERE order_id = ANY(:oids)"),
                    {"oids": ids},
                )
            ).mappings().all()
            for it in item_rows:
                restored[it["sku_code"]] = restored.get(it["sku_code"], 0) + int(it["quantity"])
            for sku, qty in restored.items():
                await conn.execute(
                    _t("UPDATE merchant_skus SET stock = stock + :q WHERE sku_code = :s"),
                    {"q": qty, "s": sku},
                )
            await conn.execute(_t("DELETE FROM merchant_order_items WHERE order_id = ANY(:oids)"), {"oids": ids})
            await conn.execute(_t("DELETE FROM merchant_orders WHERE order_id = ANY(:oids)"), {"oids": ids})
            deleted_orders = len(ids)
            await conn.execute(_t("DELETE FROM merchant_customers WHERE customer_id LIKE :p"), {"p": f"{CUST_PREFIX}%"})
    # engine 侧夜测残留:HITL 工单 + 发件箱事件(线程 nightly_ 前缀)。
    # pending_approvals.id 是 uuid、approval_id 是 text —— asyncpg 严格类型,
    # JOIN 必须显式 CAST(uuid = text 无隐式操作符,首夜实弹)
    from engine_py.db import get_session

    purged = 0
    async with get_session() as session:
        ev_rows = (
            await session.execute(
                _t(
                    "SELECT e.id FROM approval_outbox_events e "
                    "JOIN pending_approvals a ON a.id = CAST(e.approval_id AS uuid) "
                    "WHERE a.thread_id LIKE 'nightly_%'"
                )
            )
        ).scalars().all()
        if ev_rows:
            await session.execute(
                _t("DELETE FROM approval_outbox_events WHERE id = ANY(:eids)"), {"eids": list(ev_rows)}
            )
        res = await session.execute(_t("DELETE FROM pending_approvals WHERE thread_id LIKE 'nightly_%'"))
        purged = res.rowcount or 0
        await session.commit()
    return {"deleted_orders": deleted_orders, "stock_restored": restored, "nightly_approvals_purged": purged}


def render_report(results: list[dict], out: Path, night: str, env_ok: bool, perf: str = "") -> None:
    cust = [r for r in results if r["kind"] == "customer"]
    data = [r for r in results if r["kind"] == "data"]
    strict = [r for r in results if not r.get("advisory") and not r.get("skipped")]
    passed = [r for r in strict if r["ok"]]
    failed = [r for r in strict if not r["ok"]]
    latencies = [t.get("latency_s") for r in results for t in (r.get("turns") or []) if isinstance(t, dict) and t.get("latency_s")]
    p50 = sorted(latencies)[len(latencies) // 2] if latencies else 0

    def _row(r):
        icon = "✅" if r["ok"] else "❌"
        fails = "; ".join(r.get("fails") or [])
        extra = f' <span class="adv">advisory:{ "; ".join(sum([t.get("advisory_notes", []) for t in r.get("turns", []) if isinstance(t, dict)], []))}</span>' if r.get("kind") == "customer" else ""
        trans = ""
        if r.get("kind") == "customer":
            trans = "".join(
                f'<details><summary>轮{t.get("turn")} ({t.get("latency_s")}s)</summary><pre>{html.escape(str(t.get("output", "")))[:1200]}</pre></details>'
                for t in r.get("turns", []) if isinstance(t, dict) and not t.get("skipped")
            )
        elif r.get("frames") is not None:
            trans = f'<pre>{html.escape(str(r.get("frames")))}</pre>'
        return (f'<tr class="{"pass" if r["ok"] else "fail"}"><td>{icon}</td><td>{html.escape(str(r.get("case_id")))}</td>'
                f'<td>{html.escape(str(r.get("dimension")))}</td><td>{html.escape(fails)}{extra}</td>'
                f'<td>{r.get("latency_s", "")}</td><td>{trans}</td></tr>')

    rows = "\n".join(_row(r) for r in results)
    out.write_text(f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>夜间 agent 评测 {night}</title>
<style>body{{font-family:system-ui,sans-serif;margin:2rem;max-width:1100px}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ddd;padding:6px 8px;vertical-align:top;font-size:13px;text-align:left}}
.fail{{background:#fff1f0}}.pass{{background:#f0fff4}}.adv{{color:#b45309}}summary{{cursor:pointer}}.skip{{color:#888}}</style></head><body>
<h1>夜间 agent 评测 · {night}</h1>
<p>严格用例 <b>{len(passed)}/{len(strict)}</b> 通过 · 失败 <b style="color:#c0392b">{len(failed)}</b> ·
轮延迟 p50 ≈ {p50}s · 环境 {'正常' if env_ok else '异常'} · 总轮次见 results.jsonl</p>
<p class="skip">{perf}</p>
<h2>明细</h2><table><tr><th></th><th>用例</th><th>维度</th><th>失败原因</th><th>延迟s</th><th>转录</th></tr>{rows}</table>
<p class="skip">skipped 场景因轮次预算未执行,详见 results.jsonl。</p></body></html>""")


async def main() -> int:
    _load_env()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    budget = {"turns": 0}

    async with httpx.AsyncClient(base_url=BASE, timeout=TURN_TIMEOUT) as client:
        env_ok = await health_check(client)
        if not env_ok:
            print(f"[Nightly] 环境不可用:网关 {BASE} 无响应 —— 不产假红,退出码 2")
            (OUT_DIR / "ENVIRONMENT_DOWN.txt").write_text(f"gateway {BASE} unreachable at {_dt.datetime.now().isoformat()}\n")
            return 2

        # 单号锚点:种子集运行时读取(严禁手抄漂移)
        from gateway_py import merchant_seed as ms

        seeded_ids = {o["order_id"] for o in ms._ORDERS}
        created_ids: set[str] = set()

        uploads = ROOT / "public" / "uploads"
        first_png = next((f"/api/uploads/{f.name}" for f in sorted(uploads.glob("*.png"))), "") if uploads.exists() else ""
        if first_png:
            budget["image_map"] = {"@UPLOADS_FIRST_PNG": first_png}

        only = [x for x in os.environ.get("NIGHTLY_CASES", "").split(",") if x.strip()]
        for case in CUSTOMER_CASES:
            if only and not any(case.case_id.startswith(x) for x in only):
                continue
            if os.environ.get("NIGHTLY_SMOKE") and case.case_id not in ("c01_导购_冲锋衣", "c15_幽灵单号_诚实查无"):
                continue
            res = await run_customer_case(client, case, seeded_ids, created_ids, budget)
            results.append(res)
            print(("[PASS] " if res["ok"] else "[FAIL] ") + res["case_id"] + ("" if res["ok"] else "  ← " + "; ".join(res["fails"])))

        # 会话隔离(确定性):X 的线程不得泄漏进 Y 的列表
        # isolation kind=perf,统一由性能打印循环输出(避免双重打印)
        results.append(await run_isolation_case(client))

        # Data Agent + 菜单矩阵:按需登录各角色(token 缓存)
        needed_staff = {c.staff_email for c in DATA_CASES} | {c.staff_email for c in MENU_CASES}
        tokens: dict[str, str] = {}
        for email in sorted(needed_staff):
            try:
                lr = await client.post("/api/auth/login", json={"email": email, "password": STAFF_PASSWORD})
                tok = (lr.json().get("data") or {}).get("token") or ""
            except Exception:
                tok = ""
            if tok:
                tokens[email] = tok
            else:
                results.append({"kind": "data", "case_id": f"AUTH_{email}", "dimension": "环境",
                                "ok": False, "fails": [f"员工登录失败({email})"], "advisory": False})

        if tokens.get(STAFF_EMAIL):
            for case in DATA_CASES:
                if only and not any(case.case_id.startswith(x) for x in only):
                    continue
                if os.environ.get("NIGHTLY_SMOKE") and case.case_id not in ("d01_销售_GMV", "d11_权限_运营问毛利"):
                    continue
                results.append(await run_data_case(client, tokens, case, budget))
                r = results[-1]
                print(("[PASS] " if r["ok"] else "[FAIL] ") + r["case_id"] + ("" if r["ok"] else "  ← " + "; ".join(r["fails"])))

            # 菜单/按钮矩阵:每轮以老板实时全量做基线
            smoke_menus = [c for c in MENU_CASES if (not os.environ.get("NIGHTLY_SMOKE") or c.case_id in ("m01_老板_全量", "m03_运营_受限")) and (not only or any(c.case_id.startswith(x) for x in only))]
            for case in smoke_menus:
                owner_perms = await _owner_perms(client, tokens)
                r = await run_menu_case(client, owner_perms, case, tokens)
                results.append(r)
                print(("[PASS] " if r["ok"] else "[FAIL] ") + r["case_id"] + ("" if r["ok"] else "  ← " + "; ".join(r["fails"])))
            # 跨角色差异:运营与仓储可见集不得相同
            if not os.environ.get("NIGHTLY_SMOKE"):
                ops = next((set(r["perms"]) for r in results if r.get("case_id") == "m03_运营_受限"), set())
                wh = next((set(r["perms"]) for r in results if r.get("case_id") == "m04_仓储_受限"), set())
                if ops and wh and ops == wh:
                    results.append({"kind": "menu", "case_id": "m05_角色分档", "dimension": "权限面",
                                    "ok": False, "fails": ["运营与仓储按钮闭集相同,角色分档失效"], "advisory": False})

        # 优化维度:并发 + SSE 桥存活(延迟数据供性能预算);
        # 定向切片(NIGHTLY_CASES)未点名 p 前缀时记 skipped 不真跑
        perf_only = [x for x in only if x.startswith("p")]
        if os.environ.get("NIGHTLY_SMOKE") or (only and not perf_only):
            results.append({"kind": "perf", "case_id": "perf_skipped", "dimension": "优化",
                            "ok": True, "skipped": True, "fails": []})
        else:
            results.append(await run_concurrency(client))
            results.append(await run_sse_bridge(client))
        for r in [x for x in results if x.get("kind") == "perf"]:
            print(("[PASS] " if r["ok"] else "[FAIL] ") + r["case_id"] + ("" if r["ok"] else "  ← " + "; ".join(r["fails"])))

    # 失败喂飞轮(客服侧;坏例池静默降级,不阻断)
    try:
        from engine_py.badcase.pool import record_badcase_signal

        for r in results:
            if not r["ok"] and not r.get("advisory") and not r.get("skipped"):
                await record_badcase_signal(
                    "nightly_agent_eval",
                    conversation_ref=f"thread:{r.get('thread_id', r.get('case_id'))}",
                    business_id=TENANT,
                    note="; ".join(r.get("fails") or [])[:500],
                )
    except Exception as err:
        print(f"[Nightly] 坏例池入池失败(不阻断): {err!r}")

    # 报告先落盘(主产物);清理是卫生,失败降级记录不许吞报告
    (OUT_DIR / "results.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in results) + "\n"
    )
    lat_all = [t.get("latency_s") for r in results for t in (r.get("turns") or [])
               if isinstance(t, dict) and t.get("latency_s")]
    lat_all += [x.get("latency_s") for x in results if x.get("latency_s")]
    lat_all = sorted(x for x in lat_all if isinstance(x, (int, float)))
    p50v = lat_all[len(lat_all) // 2] if lat_all else 0
    p95v = lat_all[int(len(lat_all) * 0.95)] if lat_all else 0
    perf = f"性能:p50={p50v}s · p95={p95v}s · max={max(lat_all) if lat_all else 0}s(预算 advisory,基线学习期)"
    render_report(results, OUT_DIR / "report.html", NIGHT, env_ok, perf)
    try:
        cleanup_stats = await cleanup()
    except Exception as err:
        cleanup_stats = {"error": repr(err)[:300]}
        print(f"[Nightly] 清理失败(不吞报告,留待人工): {err!r}")
    failed = [r for r in results if not r["ok"] and not r.get("advisory") and not r.get("skipped")]
    print(f"[Nightly] 完成:严格用例失败 {len(failed)};报告 {OUT_DIR / 'report.html'};清理 {cleanup_stats}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
