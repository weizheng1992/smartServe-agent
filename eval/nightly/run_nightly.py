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
MAX_TURNS = int(os.environ.get("NIGHTLY_MAX_TURNS", "220"))
TURN_TIMEOUT = 90.0
# pass^k 可靠性口径(eval-gap-2026-10 06,τ-bench 律):高资金风险链与闭集
# Data Agent 问每夜 k 跑,单次红的采样方差与真回归由「多数决 + pass^k 全过率
# 指标」分账 —— v1 门禁取多数决(pass^k 全过率入台账供晨审跨夜看趋势,
# 严格 pass^k 门禁待基线数据后收严);k 可经 NIGHTLY_PASS_K 调(=1 关闭)。
PASS_K = int(os.environ.get("NIGHTLY_PASS_K", "3"))
CUSTOMER_PASS_K_PREFIXES = ("c06_", "c08_", "c21_", "c35_", "c36_")  # HITL/全链购物/双退款/审批终态族
DATA_PASS_K_PREFIXES = ("d01_", "d03_", "d04_", "d06_")  # 闭集指标问族(应确定性,pass^3<1 即非确定性信号)
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


_CONNECT_RETRY_ATTEMPTS = 4
_CONNECT_RETRY_BACKOFF_S = 3.0


async def _retry_on_connect(fn, *args, what: str, **kwargs):
    """连接类异常退避重试:结果只在整跑收尾才落盘,网关重启窗口
    (并行会话顶替 4000 端口等)拒绝连接会令整夜台账蒸发 —— 2026-10-16
    实弹:approvals_waiting 在逐轮 try 块之外,重启窗口一个 ConnectError
    终止全部 58 例且 results.jsonl 零落盘。仅重试连接被拒/重置类签名
    (重启窗口),ReadTimeout 等 LLM 慢回复不在此列、维持一次性语义。"""
    for attempt in range(1, _CONNECT_RETRY_ATTEMPTS + 1):
        try:
            return await fn(*args, **kwargs)
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as err:
            if attempt == _CONNECT_RETRY_ATTEMPTS:
                raise
            print(f"[retry] {what} 第{attempt}次连接失败({err!r}),{_CONNECT_RETRY_BACKOFF_S}s 后重试")
            await asyncio.sleep(_CONNECT_RETRY_BACKOFF_S)


# ---------------------------------------------------------------------------
# 客服 agent
# ---------------------------------------------------------------------------

_ORDER_ID_RE = re.compile(r"AURORA-ORD-2026-(\d{4})")
_PHONE_RE = re.compile(r"1[3-9]\d{9}")


async def approvals_waiting(client: httpx.AsyncClient, thread_id: str) -> set[str]:
    r = await _retry_on_connect(client.get, "/api/chat/approvals",
                                params={"tenantId": TENANT, "status": "waiting"},
                                what="approvals_waiting")
    if r.status_code != 200:
        return set()
    return {
        a.get("approvalId") or a.get("id") or ""
        for a in (r.json().get("approvals") or [])
        if (a.get("threadId") == thread_id)
    }


async def _create_nightly_order(client, customer_id: str) -> str:
    """夜测顾客自购真单(种子货架咖啡套装 ×1):售后/HITL 场景的归属前置。"""
    r = await _retry_on_connect(client.get, "/api/store/products", what="store_products")
    sku_code = ""
    for p in r.json().get("products") or []:
        if "咖啡" in str(p.get("title") or ""):
            skus = p.get("skus") or []
            sku_code = str(skus[0].get("skuCode")) if skus else ""
            break
    if not sku_code:
        return ""
    r = await _retry_on_connect(
        client.post,
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
        what="create_nightly_order",
    )
    return str((r.json() or {}).get("orderId") or "")


async def _thread_messages(client, thread_id: str, customer_id: str) -> list[dict]:
    """线程时间线(store 面,属主随行);失败诚实空列表。"""
    try:
        r = await client.get("/api/store/chat/messages",
                             params={"threadId": thread_id, "businessId": TENANT, "userId": customer_id})
        if r.status_code != 200:
            return []
        return list((r.json() or {}).get("messages") or [])
    except Exception:
        return []


async def _order_status(client, customer_id: str, order_id: str) -> str:
    """商户真单当前状态(τ 式终态判分的真值源;查无返回空串)。"""
    try:
        r = await client.get("/api/store/orders", params={"customerId": customer_id, "limit": 50})
        for o in (r.json() or {}).get("orders") or []:
            if str(o.get("orderId") or "") == order_id:
                return str(o.get("status") or "")
    except Exception:
        pass
    return ""


async def _resolve_approval_flow(client, staff_token: str, approval_id: str, thread_id: str,
                                 customer_id: str, order_id: str, flow) -> dict:
    """HITL 三段剧本(eval-gap-2026-10 02):决议 → 等恢复回合 → 终态真值断言。

    τ-bench 律:判 DB/订单/审批单终态,不判文本相似 —— 恢复回复只做词干锚点
    与谎报禁词双保险,资金语义以 merchant_orders.status 为准。
    """
    out: dict = {"action": flow.action, "approval_id": approval_id, "fails": []}
    msg_ids_before = {str(m.get("id") or "") for m in await _thread_messages(client, thread_id, customer_id)}
    status_before = await _order_status(client, customer_id, order_id)
    out["order_status_before"] = status_before

    body = {"approvalId": approval_id, "action": flow.action}
    if flow.action == "reject":
        body["rejectionReason"] = "夜评驳回分支:订单信息与申请不符"
    r = await _retry_on_connect(
        client.post, "/api/approvals", json=body,
        headers={"Authorization": f"Bearer {staff_token}"} if staff_token else {},
        what=f"approval_{flow.action}",
    )
    if r.status_code != 200:
        out["fails"].append(f"审批决议 HTTP {r.status_code}: {str(r.text)[:180]}")
        return out

    # 恢复回合:Fast-Path job_resume_${approvalId} → run_agent → finish 落 assistant 行
    deadline = time.monotonic() + flow.poll_timeout
    recovery = ""
    while time.monotonic() < deadline:
        msgs = await _thread_messages(client, thread_id, customer_id)
        new_rows = [m for m in msgs
                    if str(m.get("id") or "") not in msg_ids_before and m.get("role") == "assistant"]
        if new_rows:
            recovery = str(new_rows[-1].get("content") or "")
            break
        await asyncio.sleep(3)
    out["recovery_reply"] = recovery[:400]
    if not recovery:
        out["fails"].append(f"恢复回复 {flow.poll_timeout:.0f}s 未落地(决议后 Fast-Path 恢复链断裂?)")
        return out
    if flow.reply_contains_any and not any(k.lower() in recovery.lower() for k in flow.reply_contains_any):
        out["fails"].append(f"恢复回复缺锚点 {flow.reply_contains_any}")
    for kw in flow.reply_not_contains:
        if kw.lower() in recovery.lower():
            out["fails"].append(f"恢复回复出现禁词 {kw}")

    # 终态真值①:审批单脱离 waiting
    if approval_id in await approvals_waiting(client, thread_id):
        out["fails"].append("审批单决议后仍挂在 waiting(状态未翻转)")

    # 终态真值②:商户订单状态(给落账一个短暂结算窗,恢复回复已落但退款执行
    # 与 finish 落库同批,通常已可见)
    status_after = await _order_status(client, customer_id, order_id)
    if flow.order_must_stay:
        if status_after != status_before:
            out["fails"].append(f"reject 后订单状态漂移 {status_before}→{status_after}(应保持不动)")
    else:
        accepts = flow.order_terminal_any or (flow.order_terminal,)
        if status_after not in accepts:
            await asyncio.sleep(3)  # 结算窗重读一次再判
            status_after = await _order_status(client, customer_id, order_id)
        if status_after not in accepts:
            out["fails"].append(f"approve 终态 {status_after or '(查无)'} 不在 {accepts}(退款未落账?)")
    out["order_status_after"] = status_after
    return out


async def run_customer_case(client, case, seeded_ids: set[str], created_ids: set[str], budget: dict,
                            staff_token: str = "", run_idx: int = 0) -> dict:
    """跑一个客服场景(多轮连续 threadId);返回逐轮结果与裁决。

    run_idx:pass^k 第几跑(0=单跑形态)—— 顾客 id 附加跑次后缀防购物车/
    线程上下文跨跑残留(与每夜唯一后缀同律)。
    """
    thread_id = f"nightly_{case.case_id}_{int(time.time())}{'_' + str(run_idx) if run_idx else ''}"
    # 顾客 id 带每夜唯一后缀:引擎侧购物车按 userId 挂账(Redis),case_id 恒定
    # 会跨跑残留(首夜实弹:上次失败跑的瑜伽垫混进本次结算)
    customer_id = f"{CUST_PREFIX}_{case.case_id}_{NIGHT}{'_' + str(run_idx) if run_idx else ''}"
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
            r = await _retry_on_connect(
                client.post,
                "/api/store/chat",
                json={"message": message, "businessId": TENANT, "userId": customer_id, "threadId": thread_id,
                      **({"imageUrls": images} if images else {})},
                timeout=TURN_TIMEOUT,
                what=f"store_chat/{case.case_id}#轮{i}",
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
        # HITL 审批恢复链三段剧本(eval-gap-2026-10 02):决议 → 恢复 → 终态
        if turn.approval is not None:
            if not new:
                fails.append("审批流缺前置:本轮无新审批单可决议")
            elif not staff_token:
                fails.append("审批流缺员工 JWT(STAFF 登录失败?),三段剧本无法执行")
            else:
                flow_row = await _resolve_approval_flow(
                    client, staff_token, sorted(new)[0], thread_id, customer_id, order_id, turn.approval,
                )
                row["approval_flow"] = flow_row
                if turn.approval.advisory:
                    # 已知缺陷观察位:断言结果进台账(advisory_notes 供晨审),不判红
                    row.setdefault("advisory_notes", []).extend(
                        f"审批流[{turn.approval.action}]: {f}" for f in flow_row.get("fails") or [])
                else:
                    fails.extend(flow_row.get("fails") or [])
        # 转人工排队:线程真源须翻 human_takeover(engine takeover.mark_takeover_requested)
        if turn.expect_takeover:
            # 属主闸随行(2026-10-17 窃听族收口):显式 threadId 的有主线程必须
            # 命中请求者身份,否则诚实空(thread:null)——不随行即误读「未接管」
            tr = await client.get("/api/store/chat/messages",
                                  params={"threadId": thread_id, "businessId": TENANT,
                                          "userId": customer_id})
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


async def run_data_case(client, tokens: dict[str, str], case, budget: dict, run_idx: int = 0) -> dict:
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
    session_id = f"nightly_{case.case_id}{'_' + str(run_idx) if run_idx else ''}"
    qa_rows: list[dict] = []
    frames: list[tuple[str, dict]] = []
    status_code = 0
    for qi, q in enumerate(questions, 1):
        try:
            body = {"question": q}
            if case.turns:
                body["pageContext"] = {"sessionId": session_id}
            r = await _retry_on_connect(
                client.post,
                "/api/admin/analytics/ask",
                headers={"x-tenant-id": TENANT, "Authorization": f"Bearer {token}"},
                json=body,
                timeout=TURN_TIMEOUT,
                what=f"analytics_ask/{case.case_id}",
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
    r = await _retry_on_connect(
        client.get,
        "/api/admin/analytics/menus",
        headers={"x-tenant-id": TENANT, "Authorization": f"Bearer {tokens.get(STAFF_EMAIL, '')}"},
        what="owner_perms",
    )
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
    fails = [f"并发路{i}: HTTP {s} / {ok if isinstance(ok, str) else ''}"
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
        # 属主闸随行(2026-10-17 窃听族收口):有主线程订阅必须声明匹配 userId,
        # 否则 403 掐流——「知线程 id 即听」正是本闸要封的口,评测须走正门
        async with client.stream("GET", "/api/store/chat/stream",
                                 params={"threadId": thread_id, "businessId": TENANT,
                                         "userId": f"{CUST_PREFIX}_sse"},
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


# ---------------- 流可靠性评测层(eval-gap-2026-10 03) ----------------
# pytest 契约(test_realtime_contract / test_interruption / test_settle_turn_interrupted /
# test_chat_cancel_route)钉的是密封环境下的行为不变量;此处对**运行中的 4000
# 网关**实弹同一批语义并产出可量化指标(补投保真度 / 打断收口延迟),每晚入
# report.html 与 results.jsonl —— S1/S2 主线的可量化证据层。


def _sse_split(buf: str) -> tuple[list[dict], str]:
    """SSE 增量切帧:按空行边界切,解析 id:/event:/data: 行;余量留待下块。"""
    frames: list[dict] = []
    while "\n\n" in buf:
        raw, buf = buf.split("\n\n", 1)
        frame: dict = {}
        data_lines: list[str] = []
        for line in raw.split("\n"):
            if line.startswith("id:"):
                frame["id"] = line[3:].strip()
            elif line.startswith("event:"):
                frame["event"] = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if data_lines:
            frame["data"] = "\n".join(data_lines)
        if frame:
            frames.append(frame)
    return frames, buf


def _message_frames(frames: list[dict]) -> list[dict]:
    out = []
    for f in frames:
        if f.get("event") != "message":
            continue
        try:
            payload = json.loads(f.get("data") or "{}")
        except Exception:
            payload = {}
        out.append({"frame_id": str(f.get("id") or ""), "msg_id": str(payload.get("id") or ""),
                    "role": str(payload.get("role") or ""), "content": str(payload.get("content") or "")})
    return out


async def _collect_store_stream(client, params: dict, *, collect_s: float | None = None,
                                stop_on_message: bool = False, timeout_s: float = 60) -> list[dict]:
    """订阅商店流收集帧:collect_s 到点即断;stop_on_message=首帧 message 即断
    (在途断连语义)。退出 async with 即断开连接 —— 这正是被测行为。"""
    frames: list[dict] = []
    buf = ""
    try:
        async with client.stream("GET", "/api/store/chat/stream", params=params, timeout=timeout_s) as resp:
            # 硬墙钟:15s 心跳会不断重置 httpx 读超时,stop_on_message 若无帧
            # 到达将无限续命 —— 收集器必须自设墙钟兜底(2026-10-24 实弹挂死)
            hard_end = time.monotonic() + (collect_s if collect_s else 90)
            async for chunk in resp.aiter_text():
                buf += chunk
                fresh, buf = _sse_split(buf)
                frames.extend(fresh)
                if stop_on_message and any(f.get("event") == "message" for f in fresh):
                    break
                if time.monotonic() >= hard_end:
                    break
    except Exception:
        pass  # 断连/超时即收集终止,断言侧诚实判
    return frames


def _frame_id(ts: str) -> int:
    """镜像网关 frame_id_from_timestamp:ISO → epoch ms(naive 按 UTC,与两套钟
    收口后的网关产出一致)。补投契约的真值源是 DB 时间线,断言以同一比较器
    展开期望集。"""
    import datetime as _dt

    try:
        dt = _dt.datetime.fromisoformat(str(ts or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.UTC)
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0


async def run_stream_replay(client) -> dict:
    """S1 断线补投不重不漏(ADR-0013① L1 实弹):**期望集锚定 DB 时间线**
    (补投契约的真值源 —— live pubsub 帧面与时间线回放面天然不同源,拿 live
    帧集当期望会自造假红):镜像网关比较器(frame_id > 水位)算期望消息集,
    断言补投消息 id 多重集精确等值 + 内容一致;水位=最新时零补投;在途断连
    后补齐该轮剩余帧。段①③零 LLM(问候直答旁路)。"""
    user = f"{CUST_PREFIX}_s1"
    thread_id = f"nightly_s1replay_{int(time.time())}"
    base = {"threadId": thread_id, "businessId": TENANT, "userId": user}
    fails: list[str] = []
    metrics: dict = {}

    async def say(msg: str):
        return await _retry_on_connect(client.post, "/api/store/chat",
                                       json={"message": msg, "businessId": TENANT, "userId": user,
                                             "threadId": thread_id},
                                       timeout=TURN_TIMEOUT, what="s1_say")

    async def timeline() -> list[dict]:
        return await _thread_messages(client, thread_id, user)

    def expected_after(watermark: int) -> list[dict]:
        return [m for m in timeline_cache if _frame_id(str(m.get("timestamp") or "")) > watermark]

    await client.post("/api/chat/threads", json={"threadId": thread_id, "businessId": TENANT, "userId": user}, timeout=30)
    timeline_cache: list[dict] = []

    # 段①:live 收两个零 LLM 回合的帧 —— 唯一用途是取「真实观测到的水位值」
    listener = asyncio.create_task(_collect_store_stream(client, base, collect_s=14))
    await asyncio.sleep(1.5)
    await say("你好")
    await say("在吗")
    live_msgs = _message_frames(await listener)
    metrics["live_message_frames"] = len(live_msgs)
    timeline_cache = await timeline()
    metrics["timeline_rows"] = len(timeline_cache)
    if len(timeline_cache) < 3 or not live_msgs:
        fails.append(f"基线不足(时间线 {len(timeline_cache)} 行/live {len(live_msgs)} 帧):S1 断言无法展开")
    else:
        from collections import Counter as _Counter

        # 段②:水位=首条业务消息(欢迎行之后),补投须精确补齐其余时间线消息
        anchor_ts = str(timeline_cache[0].get("timestamp") or "")
        watermark = _frame_id(anchor_ts)
        expect = expected_after(watermark)
        got = _message_frames(await _collect_store_stream(client, {**base, "lastEventId": watermark}, collect_s=6))
        metrics["gap_replayed"] = len(got)
        if _Counter(m["msg_id"] for m in got) != _Counter(str(m.get("id") or "") for m in expect):
            fails.append(f"水位补投不重不漏被击穿:期望 {[m.get('id') for m in expect]} 实得 {[m['msg_id'] for m in got]}")
        else:
            expect_contents = {str(m.get("content") or "")[:60] for m in expect}
            if not all(m["content"][:60] in expect_contents for m in got):
                fails.append("补投帧内容与时间线不一致(补错帧)")
        # 段③:水位=最新一条,零补投
        latest_wm = _frame_id(str(timeline_cache[-1].get("timestamp") or ""))
        got2 = _message_frames(await _collect_store_stream(client, {**base, "lastEventId": latest_wm}, collect_s=5))
        metrics["latest_watermark_replayed"] = len(got2)
        if got2:
            fails.append(f"水位=最新仍补投 {[m['msg_id'] for m in got2]}(重复补投)")

    # 段④:在途断连 —— live 收到首帧即断(真实断线),该轮剩余时间线消息经重连补齐
    listener2 = asyncio.create_task(_collect_store_stream(client, base, stop_on_message=True, timeout_s=45))
    await asyncio.sleep(1.5)
    post = asyncio.create_task(say("给我详细介绍一下你们店的冲锋衣都有哪些款式和特点"))
    early_msgs = _message_frames(await listener2)
    r = await post
    output = str((r.json() or {}).get("output") or "") if r.status_code == 200 else ""
    timeline_cache = await timeline()
    if not early_msgs:
        # 无帧可能是回合慢/未发帧(SSE 桥存活由 p02 专册钉),段④降级为记录不断言
        metrics["midturn_note"] = "90s 硬墙内未见 message 帧,段④未展开(LLM 慢/帧未发)"
    else:
        wm = int(early_msgs[-1]["frame_id"] or 0)
        expect = expected_after(wm)
        got3 = _message_frames(await _collect_store_stream(client, {**base, "lastEventId": wm}, collect_s=8))
        metrics["midturn_replayed"] = len(got3)
        metrics["midturn_expected"] = len(expect)
        from collections import Counter as _Counter

        if _Counter(m["msg_id"] for m in got3) != _Counter(str(m.get("id") or "") for m in expect):
            fails.append(f"在途断连补投不等值:期望 {[m.get('id') for m in expect]} 实得 {[m['msg_id'] for m in got3]}(ADR-0013①)")
        elif got3 and output and not any((m["content"][:30] and m["content"][:30] in output)
                                         or (output[:30] and output[:30] in m["content"]) for m in got3):
            fails.append("在途断连补投帧内容与该轮回复不一致(补错帧)")
    await client.request("DELETE", "/api/chat/threads", params={"threadId": thread_id, "userId": user})
    return {"kind": "stream", "case_id": "s01_断线补投不重不漏", "dimension": "流可靠性·S1",
            "ok": not fails, "fails": fails, "metrics": metrics}


async def run_stream_interrupt(client) -> dict:
    """S2 打断终态(S2a/S2b/S2c 全链实弹):在途 LLM 回合取消 → result 帧
    interrupted:true 收口 + 该轮零 assistant 行 + 后续追问会话不脏。
    404/409=回合在取消前已完结(未截住):诚实记 not_caught 不判红(截住率是
    指标不是断言);404/409 语义本身由 pytest 契约钉死,此处不重复断言。"""
    fails: list[str] = []
    metrics: dict = {"caught": False}
    email, password = "nightly.s2@eval.local", STAFF_PASSWORD
    try:
        await client.post("/api/auth/register", json={"email": email, "password": password,
                                                      "displayName": "夜评S2打断"})
    except Exception:
        pass  # 非首夜已注册,登录即可
    lr = await _retry_on_connect(client.post, "/api/auth/login",
                                 json={"email": email, "password": password}, what="s2_login")
    data = (lr.json().get("data") or {}) if lr.status_code == 200 else {}
    token, uid = str(data.get("token") or ""), str((data.get("user") or {}).get("id") or "")
    if not token or not uid:
        return {"kind": "stream", "case_id": "s02_打断终态", "dimension": "流可靠性·S2",
                "ok": False, "fails": [f"S2 测试用户登录失败 HTTP {lr.status_code}"], "metrics": metrics}
    headers = {"Authorization": f"Bearer {token}"}
    thread_id = f"nightly_s2_{int(time.time())}"
    await client.post("/api/chat/threads", json={"threadId": thread_id, "businessId": TENANT, "userId": uid},
                      headers=headers, timeout=30)

    async def _chat_messages() -> list[dict]:
        try:
            rm = await client.get("/api/chat/messages", params={"threadId": thread_id, "businessId": TENANT})
            return list((rm.json() or {}).get("messages") or [])
        except Exception:
            return []

    async def attempt(question: str) -> tuple[int, dict]:
        """受理→订阅作业流→2.5s 后取消→等 result 帧;返回 (取消HTTP, 观测)。"""
        msgs_before = {str(m.get("id") or "") for m in await _chat_messages()}
        dr = await client.post("/api/chat", json={"message": question, "threadId": thread_id,
                                                  "userId": uid, "businessId": TENANT},
                               headers=headers, timeout=30)
        if dr.status_code != 200:
            return dr.status_code, {}
        job_id = str((dr.json() or {}).get("jobId") or "")
        if not job_id:
            return -1, {}

        async def read_result():
            frames, buf = [], ""
            try:
                async with client.stream("GET", f"/api/chat/{job_id}/stream", timeout=120) as resp:
                    async for chunk in resp.aiter_text():
                        buf += chunk
                        fresh, buf = _sse_split(buf)
                        frames.extend(fresh)
                        if any(f.get("event") == "result" for f in fresh):
                            return frames
            except Exception:
                pass
            return frames

        reader = asyncio.create_task(read_result())
        await asyncio.sleep(2.5)
        t_cancel = time.monotonic()
        cr = await client.post(f"/api/chat/{job_id}/cancel", params={"userId": uid, "businessId": TENANT},
                               headers=headers, timeout=15)
        if cr.status_code != 200:
            reader.cancel()
            return cr.status_code, {}
        frames = await asyncio.wait_for(reader, timeout=120)
        result = next((json.loads(f["data"]) for f in frames
                       if f.get("event") == "result" and f.get("data")), {})
        new_asst = [m for m in await _chat_messages()
                    if str(m.get("id") or "") not in msgs_before and m.get("role") == "assistant"
                    and not str(m.get("id") or "").startswith("welcome_")]
        return 200, {"result": result, "settle_s": round(time.monotonic() - t_cancel, 1),
                     "job_id": job_id, "new_asst_rows": len(new_asst)}

    question = "请非常详细地介绍冬季户外装备的选择,冲锋衣、背包、水壶、登山鞋每一类都展开讲,越详细越好"
    status, info = await attempt(question)
    if status in (404, 409):  # 未截住:换更重的问句重试一次
        status, info = await attempt(question + ",并给出搭配建议与保养方法")
    metrics["cancel_http"] = status
    if status in (404, 409):
        metrics["not_caught"] = "回合在取消前已完结(404/409);截住率记录在案,不判红"
        await client.request("DELETE", "/api/chat/threads", params={"threadId": thread_id, "userId": uid})
        return {"kind": "stream", "case_id": "s02_打断终态", "dimension": "流可靠性·S2",
                "ok": True, "fails": [], "metrics": metrics, "advisory": True}
    if status != 200 or not info:
        fails.append(f"打断链路异常:受理/取消 HTTP {status}")
    else:
        metrics["caught"] = True
        metrics["settle_s"] = info.get("settle_s")
        result = info.get("result") or {}
        metrics["interrupted"] = bool(result.get("interrupted"))
        if not result:
            fails.append("取消受理后 120s 无 result 帧收口(S2c 违例:打断回合流挂死)")
        elif not result.get("interrupted"):
            fails.append("result 帧 interrupted≠true(打断终态未按 S2c 契约收口)")
        metrics["new_asst_rows"] = info.get("new_asst_rows")
        if info.get("new_asst_rows"):
            fails.append(f"打断回合仍落 {info['new_asst_rows']} 条 assistant 行(期望零)")
        # 会话不脏:打断后追问照常完成(问候零 LLM 旁路,快速可判)
        ok_follow = False
        try:
            fr = await client.post("/api/chat", json={"message": "在吗", "threadId": thread_id,
                                                      "userId": uid, "businessId": TENANT},
                                   headers=headers, timeout=30)
            if fr.status_code == 200:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    rows = await _chat_messages()
                    if any(m.get("role") == "assistant" and not str(m.get("id") or "").startswith("welcome_")
                           for m in rows):
                        ok_follow = True
                        break
                    await asyncio.sleep(3)
        except Exception:
            pass
        metrics["followup_ok"] = ok_follow
        if not ok_follow:
            fails.append("打断后追问 60s 未获回复(会话脏)")
    await client.request("DELETE", "/api/chat/threads", params={"threadId": thread_id, "userId": uid})
    return {"kind": "stream", "case_id": "s02_打断终态", "dimension": "流可靠性·S2",
            "ok": not fails, "fails": fails, "metrics": metrics}


async def run_intent_eval_case() -> dict:
    """意图集终评 95% 硬闸(eval-gap-2026-10 07):确定性 L0/L2 面零 token
    (AI_INTENT_L3 强制 off),词面/模板/注册表改动后由夜间节奏自动出回归
    证据;注册表结构不变量另由 engine pytest 册钉(行数地板/唯一性/闭集)。"""
    import os as _os

    _os.environ.setdefault("AI_INTENT_L3", "off")
    try:
        from engine_py.intent_flywheel.run_intent_eval import main_async

        code = await asyncio.wait_for(main_async(show_fails=False), timeout=300)
    except Exception as err:
        return {"kind": "intent", "case_id": "i01_意图集95闸", "dimension": "意图·注册表",
                "ok": False, "fails": [f"意图评测执行异常 {err!r}"]}
    return {"kind": "intent", "case_id": "i01_意图集95闸", "dimension": "意图·注册表",
            "ok": code == 0,
            "fails": [] if code == 0 else ["意图解析准确率 < 95% 硬闸(失败清单见上方输出)"]}


async def run_shadow_eval_case() -> dict:
    """shadow 集报告例(docs/multi-turn-task-state.md P0-2/D7):promptfoo 跑
    eval/promptfoo.shadow.yaml,只跑只报告不出闸 —— ``advisory`` 恒真:失败不进
    退出码、不回灌坏例池(shadow 草稿本就来自坏例池,回灌即自锁循环)。空集/
    promptfoo 缺位/执行异常一律诚实记 skipped,不出假红也不出假绿。"""
    import shutil as _shutil

    repo = Path(__file__).resolve().parents[2]
    pending = repo / "eval" / "testCases" / "shadow" / "pending.json"
    base = {"kind": "shadow", "case_id": "sh01_shadow集", "dimension": "回灌·shadow", "advisory": True}
    try:
        loaded = json.loads(pending.read_text(encoding="utf-8")) if pending.exists() else []
    except (OSError, ValueError):
        loaded = []
    cases = loaded if isinstance(loaded, list) else []
    if not cases:
        return {**base, "ok": True, "skipped": True, "fails": [], "metrics": {"pending": 0}}
    exe = _shutil.which("promptfoo")
    if not exe:
        return {**base, "ok": True, "skipped": True, "fails": [],
                "metrics": {"pending": len(cases)},
                "note": "promptfoo 不在 PATH,本轮跳过(shadow 不出闸,转正前请手动 test:prompt:shadow 观察)"}
    try:
        proc = await asyncio.create_subprocess_exec(
            exe, "eval", "-c", "eval/promptfoo.shadow.yaml", "--no-write", "--no-cache",
            cwd=str(repo), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=900)
        tail = " | ".join(out.decode("utf-8", "replace").strip().splitlines()[-8:])
        ok = proc.returncode == 0
        return {**base, "ok": ok, "skipped": False,
                "fails": [] if ok else [f"promptfoo shadow 非零退出 {proc.returncode}(advisory 不出闸): {tail}"],
                "metrics": {"pending": len(cases), "exit_code": proc.returncode}}
    except Exception as err:
        return {**base, "ok": True, "skipped": True, "fails": [], "note": f"shadow 执行异常(不出闸): {err!r}"}


async def run_boundary_eval_case() -> dict:
    """边界评测集(docs/multi-turn-task-state.md P1-1):live LLM 跑 triage
    classify 的 boundary 字段(30 例,与意图分类同源零额外调用)。硬闸由
    AI_BOUNDARY_GATE 单独控制 —— 默认 off 只记 skipped(D6 看板先行纪律:
    先攒 2 周基线,阈值有据后再开闸),on 才出真闸。"""
    import os as _os

    base = {"kind": "boundary", "case_id": "b01_boundary集", "dimension": "边界·P1-1"}
    if _os.environ.get("AI_BOUNDARY_GATE", "off") != "on":
        return {**base, "ok": True, "skipped": True, "fails": [],
                "note": "AI_BOUNDARY_GATE=off(D6:先攒基线再开硬闸;手动跑分 bun run eval:boundary)"}
    _os.environ.setdefault("AI_THINKING", "disabled")
    try:
        from engine_py.evals.run_boundary_eval import main_async

        # show_fails=True:失败清单必须真实落 stdout,严禁文案指向不存在的输出
        code = await asyncio.wait_for(main_async(show_fails=True), timeout=600)
    except Exception as err:
        return {**base, "ok": False, "fails": [f"边界评测执行异常 {err!r}"]}
    return {**base, "ok": code == 0,
            "fails": [] if code == 0 else ["boundary 准确率低于闸(失败清单见上方输出)"]}


# ---------------- LLM 用户模拟器(eval-gap-2026-10 09,τ²-bench 式) ----------------
# 固定脚本多轮测不出真实分布形态(改口/隐瞒/犹豫);此处 LLM 按 persona 推进
# 顾客侧对话,断言**全锚 DB 终态**(新订单/地址/审批单真值)—— 模拟器措辞方差
# 伤不了断言。verbatim 信息(地址/单号)逐字注入,严禁模拟器即兴编造。
# 模拟器 prompt 属试用期:累计人审 20 轮转正;期间断言语义不受影响。

SIM_CASE_SPECS = [
    {
        "id": "sim_犹豫导购下单",
        "persona": "犹豫型顾客:拿不准要什么,爱比较、追问细节,被推荐后会下决心",
        "goal": "先就「背包或冲锋衣」咨询一到两轮(问材质/区别),然后按序完成购买:"
                "①把客服推荐中的一件加入购物车;②给出收货地址要求保存;"
                "③说「结算下单」完成购买",
        "verbatim": ["收货地址:北京市海淀区夜测路 5 号,收件人夜测,电话 13800001113"],
        "terminal": {"order_created": True},
        # 观察位(18 号票:购物车非空时地址保存误路由+假成功,条件性引擎缺陷;
        # 断言照跑照记录,修复后删 advisory 翻严)
        "advisory": True,
        "max_turns": 7,
    },
    {
        "id": "sim_改口地址下单",
        "persona": "干脆但爱改主意的顾客:下单前反复换主意",
        "goal": "①要求把一件具体商品加入购物车;②给出第一个收货地址要求保存;"
                "③马上改口要求把地址换成第二个地址;④说「结算下单」完成购买",
        "verbatim": [
            "第一个地址:北京市海淀区夜测路 6 号,收件人夜测,电话 13800001114",
            "第二个地址:北京市朝阳区夜测路 7 号,收件人夜测,电话 13800001115",
        ],
        "terminal": {"order_created": True, "shipping_contains": "夜测路 7 号"},
        "advisory": True,
        "max_turns": 7,
    },
    {
        "id": "sim_隐瞒单号售后",
        "persona": "着急且表述不全的顾客:能少说就少说,被追问才补信息",
        "goal": "要求退掉自己刚买的咖啡套装,第一轮只说「我要退款」不给订单号;"
                "客服追问订单号或商品信息后才给出订单号",
        "setup": "order",
        "terminal": {"approval_waiting": True},
        "max_turns": 4,
    },
]


async def _sim_next_message(spec: dict, history: list[dict]) -> str:
    """模拟顾客下一消息(或 <DONE>);verbatim 信息逐字注入防模拟器编地址/单号。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    from engine_py.llm.chat import get_chat_model

    verbatim = "\n".join(f"- {v}" for v in spec.get("verbatim") or [])
    system = (
        "你在评测中扮演一位电商顾客,与智能客服对话。只输出顾客的下一条消息原文"
        "(纯文本,不超过 60 字,无旁白无引号无动作描述),严格按人设与目标推进对话,"
        "每轮只推进一小步。若目标已达成(客服已办完你要的事)或对话明显卡死,只输出 <DONE>。\n"
        f"人设:{spec['persona']}\n目标:{spec['goal']}\n"
        + (f"以下信息出现时必须逐字使用,严禁改写或编造:\n{verbatim}\n" if verbatim else "")
    )
    resp = await get_chat_model().ainvoke(
        [SystemMessage(content=system), HumanMessage(content=json.dumps(history, ensure_ascii=False))]
    )
    return str(getattr(resp, "content", "") or "").strip()


async def run_sim_case(client, spec: dict, budget: dict) -> dict:
    """τ² 式模拟顾客场景:LLM 顾客按 persona 推进,断言全锚 DB 终态,全局
    编造检查照跑;预算/超时护栏与固定脚本场景同律。"""
    thread_id = f"nightly_{spec['id']}_{int(time.time())}"
    customer_id = f"{CUST_PREFIX}_{spec['id']}_{NIGHT}"
    order_id = ""
    if spec.get("setup") == "order":
        order_id = await _create_nightly_order(client, customer_id)
        if order_id:
            spec = {**spec, "verbatim": [f"订单号:{order_id}"]}
    orders_before: set[str] = set()
    try:
        r0 = await client.get("/api/store/orders", params={"customerId": customer_id, "limit": 50})
        orders_before = {str(o.get("orderId") or "") for o in ((r0.json() or {}).get("orders") or [])}
    except Exception:
        pass

    history: list[dict] = []
    transcript: list[dict] = []
    fails: list[str] = []
    for i in range(int(spec.get("max_turns", 5))):
        if budget["turns"] >= MAX_TURNS:
            transcript.append({"turn": i, "message": "(轮次预算触顶,场景提前收束)", "output": ""})
            break
        budget["turns"] += 1
        try:
            msg = await asyncio.wait_for(_sim_next_message(spec, history), timeout=60)
        except Exception as err:
            fails.append(f"模拟器调用异常 {err!r}")
            break
        if not msg or msg.strip().upper() == "<DONE>":
            break
        history.append({"role": "customer", "text": msg[:120]})
        t0 = time.monotonic()
        try:
            r = await _retry_on_connect(
                client.post, "/api/store/chat",
                json={"message": msg, "businessId": TENANT, "userId": customer_id, "threadId": thread_id},
                timeout=TURN_TIMEOUT, what=f"sim_chat/{spec['id']}",
            )
            output = str((r.json() or {}).get("output") or "") if r.status_code == 200 else ""
        except Exception as err:
            fails.append(f"客服请求异常 {err!r}")
            break
        history.append({"role": "agent", "text": output[:300]})
        transcript.append({"turn": i + 1, "message": msg[:120], "output": output[:400],
                           "latency_s": round(time.monotonic() - t0, 1)})
        for frag in _ORDER_ID_RE.findall(output):
            oid = f"AURORA-ORD-2026-{frag}"
            if oid != order_id and oid not in orders_before and oid not in msg:
                fails.append(f"编造单号 {oid}")

    # 终态断言(DB 真值 —— τ 律:不赌措辞,判状态)
    term = spec.get("terminal") or {}
    try:
        r1 = await client.get("/api/store/orders", params={"customerId": customer_id, "limit": 50})
        orders_after = ((r1.json() or {}).get("orders") or [])
    except Exception:
        orders_after = []
    new_orders = [o for o in orders_after if str(o.get("orderId") or "") not in orders_before]
    if term.get("order_created") and not new_orders:
        fails.append("终态:未产生新订单(目标未达成)")
    if term.get("shipping_contains"):
        hit = any(term["shipping_contains"] in str(((o.get("shippingAddress") or {}).get("fullAddress") or ""))
                  for o in new_orders)
        if not hit:
            fails.append(f"终态:新订单地址不含「{term['shipping_contains']}」(改口未生效或用错址)")
    if term.get("approval_waiting"):
        if not await approvals_waiting(client, thread_id):
            fails.append("终态:无 waiting 审批单(售后挂起未达成)")

    advisory = bool(spec.get("advisory"))
    return {"kind": "sim", "case_id": spec["id"], "dimension": "模拟器·多轮",
            "ok": (True if advisory else not fails),
            "fails": [] if advisory else fails,
            "advisory_notes": ([f"观察位(18 号票): {f}" for f in fails] if advisory and fails else []),
            "turns": transcript,
            "metrics": {"turns_used": len([t for t in transcript if t.get("message")]),
                        "new_orders": len(new_orders), "goal_order": order_id or "-"}}


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
    # engine 侧夜测残留:HITL 工单 + 发件箱事件 + 线程 FK 全家桶。
    # pending_approvals.id 是 uuid、approval_id 是 text —— asyncpg 严格类型,
    # JOIN 必须显式 CAST(uuid = text 无隐式操作符,首夜实弹)
    from engine_py.db import get_session

    purged = 0
    child_rows = threads_purged = 0
    async with get_session() as session:
        # 先收线程 id 全集(宽口径:属主 NIGHTLY_* 或 id 双大小写前缀),
        # 审批/发件箱/子表/线程全部按同一 tid 集清扫 —— 审批若仍只按旧
        # nightly_ 前缀删,宽口径捞到的非前缀 id 线程带审批时,删 threads
        # 撞 pending_approvals NOT NULL 外键即整体回滚(评审 spec 轴实指)。
        tids = (
            await session.execute(
                _t(
                    "SELECT id FROM threads "
                    "WHERE user_id LIKE 'NIGHTLY_%' OR id LIKE 'nightly_%' OR id LIKE 'NIGHTLY_%'"
                )
            )
        ).scalars().all()
        ev_rows = (
            await session.execute(
                _t(
                    "SELECT e.id FROM approval_outbox_events e "
                    "JOIN pending_approvals a ON a.id = CAST(e.approval_id AS uuid) "
                    "WHERE a.thread_id = ANY(:tids) OR a.thread_id LIKE 'nightly_%'"
                ),
                {"tids": tids or [""]},
            )
        ).scalars().all()
        if ev_rows:
            await session.execute(
                _t("DELETE FROM approval_outbox_events WHERE id = ANY(:eids)"), {"eids": list(ev_rows)}
            )
        res = await session.execute(
            _t("DELETE FROM pending_approvals WHERE thread_id = ANY(:tids) OR thread_id LIKE 'nightly_%'"),
            {"tids": tids or [""]},
        )
        purged = res.rowcount or 0
        # 线程外键子表清扫 + 线程本体回收。per-case 的 DELETE /api/chat/threads
        # 是单事务:threads 行删除撞 session_metrics 等 NOT NULL 外键(每回合
        # settle 落一行)即整体回滚,messages/task_memory 一并残留,而响应码
        # 无人检查 —— 历史每轮静默泄漏约 30 条线程与全库近四成 session_metrics
        # (污染 admin 成本/活跃租户聚合)。「保审计 vs 删线程」的产品侧语义
        # 矛盾(threads 共 9 张 FK 子表、5 张 NOT NULL,见 db/models.py;
        # approval_outbox_events 无 FK 不阻塞但同批清)待晨审裁决,评测自身
        # 前缀数据先在此兜底回收(审批已先行,余下八表在此)。
        if tids:
            for tbl in (
                "messages",
                "task_memory",
                "session_metrics",
                "intent_logs",
                "low_confidence_logs",
                "llm_call_logs",
                "episodic_events",
                "agent_jobs",
            ):
                r = await session.execute(
                    _t(f"DELETE FROM {tbl} WHERE thread_id = ANY(:tids)"), {"tids": tids}
                )
                child_rows += r.rowcount or 0
            r = await session.execute(_t("DELETE FROM threads WHERE id = ANY(:tids)"), {"tids": tids})
            threads_purged = r.rowcount or 0
        await session.commit()
    return {
        "deleted_orders": deleted_orders,
        "stock_restored": restored,
        "nightly_approvals_purged": purged,
        "nightly_fk_children_purged": child_rows,
        "nightly_threads_purged": threads_purged,
    }


def render_report(results: list[dict], out: Path, night: str, env_ok: bool, perf: str = "") -> None:
    cust = [r for r in results if r["kind"] in ("customer", "sim")]
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
        if r.get("kind") in ("customer", "sim"):
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


async def _run_contained(results: list, fn, *args, case_id: str, kind: str = "customer", dimension: str = "环境", **kwargs) -> None:
    """用例级 containment:辅助用例(isolation/sse/menus 等)里零散 REST 未逐点
    守卫,撞上重启窗口的连接异常时只烧掉该用例并如实记档,严禁连坐整跑 ——
    台账只在收尾落盘,一个未捕获异常即令整夜结果蒸发(2026-10-16 实弹)。"""
    try:
        results.append(await fn(*args, **kwargs))
    except Exception as err:
        results.append({"kind": kind, "case_id": case_id, "dimension": dimension,
                        "ok": False, "fails": [f"用例级异常 {err!r}"], "advisory": False})
        print(f"[FAIL] {case_id}  ← 用例级异常 {err!r}")


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

        # HITL 三段剧本(eval-gap-2026-10 02)需员工 JWT:顾客循环之前预登老板
        # (finance_owner 兜底持 live_desk:approve);后续员工批量登录复用同一
        # token,免撞 auth_login 10/min 限流
        staff_token = ""
        try:
            lr = await client.post("/api/auth/login", json={"email": STAFF_EMAIL, "password": STAFF_PASSWORD})
            staff_token = str((lr.json().get("data") or {}).get("token") or "")
        except Exception:
            staff_token = ""
        tokens: dict[str, str] = {STAFF_EMAIL: staff_token} if staff_token else {}

        for case in CUSTOMER_CASES:
            if only and not any(case.case_id.startswith(x) for x in only):
                continue
            if os.environ.get("NIGHTLY_SMOKE") and case.case_id not in ("c01_导购_冲锋衣", "c15_幽灵单号_诚实查无"):
                continue
            # pass^k(06 号票):高资金风险链每夜 k 跑 —— 多数决定门禁,pass^k 全过率
            # 入台账(pass_k.all_pass)供晨审看跨夜趋势;严格门禁待基线数据后收严
            k = PASS_K if (not os.environ.get("NIGHTLY_SMOKE")
                           and any(case.case_id.startswith(p) for p in CUSTOMER_PASS_K_PREFIXES)) else 1
            runs: list[dict] = []
            for run_idx in range(k):
                await _run_contained(results, run_customer_case, client, case, seeded_ids, created_ids, budget,
                                     staff_token, run_idx, case_id=case.case_id)
                runs.append(results.pop())
            if k > 1:
                oks = [bool(r.get("ok")) and not r.get("skipped") for r in runs]
                agg_fails = [f"[跑{i + 1}] {'; '.join(r.get('fails') or [])}" for i, r in enumerate(runs) if r.get('fails')]
                results.append({
                    **runs[0],
                    "ok": sum(oks) * 2 > len(oks),
                    "pass_k": {"k": k, "oks": oks, "all_pass": all(oks)},
                    "fails": agg_fails if not all(oks) else [],
                })
            else:
                results.append(runs[0])
            res = results[-1]
            tag = "" if k == 1 else f" [pass^{k}:{'全过' if (res.get('pass_k') or {}).get('all_pass') else '有抖动'}]"
            print(("[PASS] " if res["ok"] else "[FAIL] ") + res["case_id"] + tag + ("" if res["ok"] else "  ← " + "; ".join(res["fails"])))

        # 会话隔离(确定性):X 的线程不得泄漏进 Y 的列表
        # isolation kind=perf,统一由性能打印循环输出(避免双重打印)
        await _run_contained(results, run_isolation_case, client,
                             case_id="c23_会话隔离", kind="perf", dimension="多场景·会话")

        # τ² 式 LLM 用户模拟器(09 号票):犹豫导购/改口地址/隐瞒单号三 persona,
        # 断言全锚 DB 终态;NIGHTLY_CASES 以 sim_ 前缀定向
        if not os.environ.get("NIGHTLY_SMOKE") and (not only or any(x.startswith("sim_") for x in only)):
            for spec in SIM_CASE_SPECS:
                if only and not any(spec["id"].startswith(x) for x in only):
                    continue
                await _run_contained(results, run_sim_case, client, spec, budget,
                                     case_id=spec["id"], kind="sim", dimension="模拟器·多轮")
                r = results[-1]
                print(("[PASS] " if r["ok"] else "[FAIL] ") + r["case_id"] + ("" if r["ok"] else "  ← " + "; ".join(r["fails"])))

        # Data Agent + 菜单矩阵:按需登录各角色(token 缓存;老板已在顾客段预登)
        needed_staff = ({c.staff_email for c in DATA_CASES} | {c.staff_email for c in MENU_CASES}) - set(tokens)
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
                # pass^k(06):闭集指标问应确定性 —— pass^3 < 1 即非确定性信号
                k = PASS_K if (not os.environ.get("NIGHTLY_SMOKE")
                               and any(case.case_id.startswith(p) for p in DATA_PASS_K_PREFIXES)) else 1
                runs_d: list[dict] = []
                for run_idx in range(k):
                    await _run_contained(results, run_data_case, client, tokens, case, budget, run_idx,
                                         case_id=case.case_id, kind="data", dimension=case.dimension)
                    runs_d.append(results.pop())
                if k > 1:
                    oks = [bool(r.get("ok")) and not r.get("skipped") for r in runs_d]
                    agg_fails = [f"[跑{i + 1}] {'; '.join(r.get('fails') or [])}" for i, r in enumerate(runs_d) if r.get('fails')]
                    results.append({
                        **runs_d[0],
                        "ok": sum(oks) * 2 > len(oks),
                        "pass_k": {"k": k, "oks": oks, "all_pass": all(oks)},
                        "fails": agg_fails if not all(oks) else [],
                    })
                else:
                    results.append(runs_d[0])
                r = results[-1]
                tag = "" if k == 1 else f" [pass^{k}:{'全过' if (r.get('pass_k') or {}).get('all_pass') else '有抖动'}]"
                print(("[PASS] " if r["ok"] else "[FAIL] ") + r["case_id"] + tag + ("" if r["ok"] else "  ← " + "; ".join(r["fails"])))

            # 菜单/按钮矩阵:每轮以老板实时全量做基线
            smoke_menus = [c for c in MENU_CASES if (not os.environ.get("NIGHTLY_SMOKE") or c.case_id in ("m01_老板_全量", "m03_运营_受限")) and (not only or any(c.case_id.startswith(x) for x in only))]
            for case in smoke_menus:
                try:
                    owner_perms = await _owner_perms(client, tokens)
                except Exception as err:
                    # containment 残洞补口(spec 评审实弹):_owner_perms 在用例
                    # containment 之外,重试耗尽后的 raise 会连坐整跑 —— 此处
                    # 只烧掉以它为基线的菜单用例,后续用例照跑
                    results.append({"kind": "menu", "case_id": case.case_id, "dimension": "权限面",
                                    "ok": False, "fails": [f"老板全量基线获取失败 {err!r}"], "advisory": False})
                    print(f"[FAIL] {case.case_id}  ← 老板全量基线获取失败 {err!r}")
                    continue
                await _run_contained(results, run_menu_case, client, owner_perms, case, tokens,
                                     case_id=case.case_id, kind="menu", dimension="权限面")
                r = results[-1]
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
            await _run_contained(results, run_concurrency, client,
                                 case_id="p01_并发5路", kind="perf", dimension="优化·并发")
            await _run_contained(results, run_sse_bridge, client,
                                 case_id="p02_SSE桥存活", kind="perf", dimension="优化·实时")

        # 流可靠性评测层(eval-gap-2026-10 03):S1 断线补投 + S2 打断终态,
        # 对运行中的网关实弹并产出量化指标;NIGHTLY_CASES 点名 s 前缀可定向跑
        stream_only = [x for x in only if x.startswith("s")]
        if os.environ.get("NIGHTLY_SMOKE") or (only and not stream_only):
            results.append({"kind": "stream", "case_id": "stream_skipped", "dimension": "流可靠性",
                            "ok": True, "skipped": True, "fails": []})
        else:
            await _run_contained(results, run_stream_replay, client,
                                 case_id="s01_断线补投不重不漏", kind="stream", dimension="流可靠性·S1")
            await _run_contained(results, run_stream_interrupt, client,
                                 case_id="s02_打断终态", kind="stream", dimension="流可靠性·S2")
        # 意图集 95% 硬闸(07 号票):确定性零 token,收尾自动出回归证据
        if not os.environ.get("NIGHTLY_SMOKE"):
            await _run_contained(results, run_intent_eval_case,
                                 case_id="i01_意图集95闸", kind="intent", dimension="意图·注册表")
        # shadow 集报告例(P0-2/D7):只跑只报告不出闸(advisory —— 不进退出码、
        # 不回灌坏例池);空集/promptfoo 缺位诚实记 skipped
        if not os.environ.get("NIGHTLY_SMOKE"):
            await _run_contained(results, run_shadow_eval_case,
                                 case_id="sh01_shadow集", kind="shadow", dimension="回灌·shadow")
        # 边界评测集(P1-1):AI_BOUNDARY_GATE=off(默认)只记 skipped,开闸后才硬闸
        if not os.environ.get("NIGHTLY_SMOKE"):
            await _run_contained(results, run_boundary_eval_case,
                                 case_id="b01_boundary集", kind="boundary", dimension="边界·P1-1")
        for r in [x for x in results if x.get("kind") in ("perf", "stream", "intent", "shadow", "boundary")]:
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
