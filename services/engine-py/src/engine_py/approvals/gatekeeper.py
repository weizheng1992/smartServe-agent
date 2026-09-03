"""ApprovalGatekeeper — 镜像 approval/approvalGatekeeper.ts(892 LOC,全量移植)。

统一封装:资金红线检测、免签限额、高价值地址红线、挂起工单生命周期与超时熔断、
Redis SETNX 分布式锁 + 内存后备锁、决议状态机、事务发件箱与断点续跑。

与 TS 的两处等价实现差异(均已在行内注明):
- ``thread:{id}:message`` 事件在 TS 走进程内 emitter(仅 WS 网关消费);Python 侧
  发布到同一事件总线,由 gateway-py 消费;
- 断点续跑为 fire-and-forget(等价 TS mock 模式下 dispatchJob 的异步语义)。
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import re
import uuid

from sqlalchemy import desc, select, text

from ..config import settings
from ..badcase.pool import SOURCE_APPROVAL_REJECTED, SOURCE_HUMAN_TAKEOVER, record_badcase_signal
from ..db import ApprovalOutboxEvent, Message, PendingApproval, get_session
from ..event_bus import emit_status, get_client, publish_agent_event
from ..memory.short_memory import _FALLBACK_USER_ID

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE
)
_AMOUNT_STRIP_RE = re.compile(r"[^0-9.]")

_local_locks: set[str] = set()


async def _ensure_thread_exists(thread_id: str, user_id: str | None = None) -> None:
    async with get_session() as session:
        await session.execute(
            text(
                'INSERT INTO threads (id, "user_id", "business_id", status, "created_at", "updated_at") '
                "VALUES (:tid, :uid, 'ecommerce', 'active', NOW(), NOW()) "
                'ON CONFLICT (id) DO UPDATE SET "updated_at" = NOW()'
            ).bindparams(tid=thread_id, uid=user_id or _FALLBACK_USER_ID)
        )
        await session.commit()


async def _add_system_message(thread_id: str, role: str, content: str) -> str:
    msg_id = str(uuid.uuid4())
    now = _dt.datetime.now().isoformat()
    async with get_session() as session:
        session.add(Message(id=msg_id, thread_id=thread_id, role=role, content=content, timestamp=now))
        await session.commit()
    # TS 侧经进程内 emitter 广播 thread:message;Python 侧发布到事件总线供 gateway-py 消费
    await publish_agent_event(
        f"thread:{thread_id}", "message", {"id": msg_id, "role": role, "content": content, "timestamp": now}
    )
    return msg_id


class ApprovalGatekeeper:
    @staticmethod
    async def check_double_refund(order_id: str) -> dict:
        try:
            async with get_session() as session:
                row = (
                    await session.execute(
                        text('SELECT total_amount AS "totalAmount", status FROM orders WHERE order_id = :oid').bindparams(
                            oid=order_id
                        )
                    )
                ).mappings().first()
                if row:
                    if row["status"] == "refunded":
                        return {"isDoubleRefund": True, "status": row["status"]}
                    return {"isDoubleRefund": False, "status": row["status"]}
        except Exception as err:  # noqa: BLE001
            print(f"[ApprovalGatekeeper] Double refund check DB error: {err}")
        return {"isDoubleRefund": False}

    @staticmethod
    async def evaluate_refund_auto_approval(
        order_id: str | None = None, refund_amount_arg=None, auto_approval_limit: float = 100
    ) -> dict:
        refund_amount = 999999.99
        amount_str = str(refund_amount_arg) if refund_amount_arg is not None else None

        if amount_str:
            try:
                refund_amount = float(_AMOUNT_STRIP_RE.sub("", amount_str)) or 999999.99
            except ValueError:
                refund_amount = 999999.99

        if order_id and not amount_str:
            try:
                async with get_session() as session:
                    row = (
                        await session.execute(
                            text('SELECT total_amount AS "totalAmount" FROM orders WHERE order_id = :oid').bindparams(
                                oid=order_id
                            )
                        )
                    ).mappings().first()
                    if row and row["totalAmount"] is not None:
                        try:
                            refund_amount = float(_AMOUNT_STRIP_RE.sub("", str(row["totalAmount"]))) or 999999.99
                        except ValueError:
                            pass
            except Exception as err:  # noqa: BLE001
                print(f"[ApprovalGatekeeper] Grounding order amount error: {err}")

        return {
            "shouldAutoApprove": refund_amount <= auto_approval_limit,
            "groundedAmount": refund_amount,
        }

    @staticmethod
    async def evaluate_address_change_policy(order_id: str | None = None) -> dict:
        if not order_id:
            return {"isHighValue": False, "totalAmount": 0}
        try:
            async with get_session() as session:
                row = (
                    await session.execute(
                        text('SELECT total_amount AS "totalAmount", status FROM orders WHERE order_id = :oid').bindparams(
                            oid=order_id
                        )
                    )
                ).mappings().first()
                if row:
                    total_amount = float(row["totalAmount"] or 0)
                    status = row["status"] or ""
                    if status not in ("shipped", "delivered") and total_amount > 100.0:
                        return {"isHighValue": True, "totalAmount": total_amount}
        except Exception as err:  # noqa: BLE001
            print(f"[ApprovalGatekeeper] Address policy DB error: {err}")
        return {"isHighValue": False, "totalAmount": 0}

    @staticmethod
    async def find_approval_by_id(approval_id: str) -> dict | None:
        try:
            async with get_session() as session:
                row = (
                    await session.execute(
                        select(PendingApproval).where(PendingApproval.id == approval_id).limit(1)
                    )
                ).scalar_one_or_none()
                if row:
                    payload = row.action_payload or {}
                    return {
                        "id": str(row.id),
                        "threadId": row.thread_id,
                        "actionType": row.action_type,
                        "actionPayload": payload,
                        "status": row.status,
                        "reason": payload.get("rejectionReason") or payload.get("reason"),
                        "deadline": row.deadline,
                        "createdAt": row.created_at,
                    }
        except Exception as err:  # noqa: BLE001
            print(f"[ApprovalGatekeeper] findApprovalById DB error: {err}")
        return None

    @staticmethod
    async def find_latest_approval_by_thread_id(thread_id: str) -> dict | None:
        try:
            async with get_session() as session:
                row = (
                    await session.execute(
                        select(PendingApproval)
                        .where(PendingApproval.thread_id == thread_id)
                        .order_by(desc(PendingApproval.created_at))
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if row:
                    payload = row.action_payload or {}
                    return {
                        "id": str(row.id),
                        "threadId": row.thread_id,
                        "actionType": row.action_type,
                        "actionPayload": payload,
                        "status": row.status,
                        "reason": payload.get("rejectionReason") or payload.get("reason"),
                        "deadline": row.deadline,
                        "createdAt": row.created_at,
                    }
        except Exception as err:  # noqa: BLE001
            print(f"[ApprovalGatekeeper] findLatestApprovalByThreadId DB error: {err}")
        return None

    @staticmethod
    async def evaluate_pending_approval_state(opts: dict) -> dict:
        latest_approval: PendingApproval | None = None
        try:
            async with get_session() as session:
                if opts.get("existingApprovalId"):
                    latest_approval = (
                        await session.execute(
                            select(PendingApproval)
                            .where(PendingApproval.id == opts["existingApprovalId"])
                            .limit(1)
                        )
                    ).scalar_one_or_none()

                if latest_approval is None:
                    approvals = (
                        (
                            await session.execute(
                                select(PendingApproval)
                                .where(PendingApproval.thread_id == opts["threadId"])
                                .order_by(desc(PendingApproval.created_at))
                            )
                        )
                        .scalars()
                        .all()
                    )
                    current_args = opts.get("args") or {}
                    for approval in approvals:
                        payload_args = (approval.action_payload or {}).get("args") or {}
                        if approval.action_type != opts.get("toolName"):
                            continue
                        if current_args.get("orderId") and payload_args.get("orderId"):
                            if str(current_args["orderId"]).strip().lower() == str(payload_args["orderId"]).strip().lower():
                                latest_approval = approval
                                break
                        elif json.dumps(payload_args, sort_keys=True, default=str) == json.dumps(
                            current_args, sort_keys=True, default=str
                        ):
                            latest_approval = approval
                            break

                # 1. 超时解挂检测
                if latest_approval and latest_approval.status == "waiting":
                    now = _dt.datetime.now(latest_approval.deadline.tzinfo) if latest_approval.deadline and latest_approval.deadline.tzinfo else _dt.datetime.now()
                    is_expired = bool(latest_approval.deadline and now > latest_approval.deadline)
                    if is_expired:
                        await session.execute(
                            text(
                                "UPDATE pending_approvals SET status = 'expired' WHERE id = CAST(:aid AS uuid)"
                            ).bindparams(aid=latest_approval.id)
                        )
                        await session.commit()
                        is_refund = opts.get("toolName") == "processRefund"
                        date_str = str(latest_approval.deadline)
                        return {
                            "state": "expired",
                            "approvalId": str(latest_approval.id),
                            "error": (
                                "人工审批已超时。大额资金退款未获得授权，暂未办理。"
                                if is_refund
                                else "人工审批已超时。高价值订单地址修改申请未获得授权，暂未办理。"
                            ),
                            "message": (
                                f"⚠️ 安全核发超时：人工审核申请 (ID: {latest_approval.id}) 已超过截止审批时间 "
                                f"({date_str}) 仍未获得核准，系统已自动实施超时安全解挂熔断。退款暂未执行，请联系客服转人工处理。"
                                if is_refund
                                else f"⚠️ 安全核发超时：订单地址修改人工审核申请 (ID: {latest_approval.id}) 已超过截止审批时间 "
                                f"({date_str}) 仍未获得授权，系统已自动实施超时安全解挂熔断。修改暂未生效。"
                            ),
                        }

                # 2. 无历史工单 → 创建新工单挂起
                if latest_approval is None:
                    new_approval_id = str(uuid.uuid4())
                    deadline = _dt.datetime.now() + _dt.timedelta(hours=24)
                    session.add(
                        PendingApproval(
                            id=new_approval_id,
                            thread_id=opts["threadId"],
                            action_type=opts["toolName"],
                            action_payload={
                                "description": opts.get("stepDescription"),
                                "args": opts.get("args") or {},
                                "stepIndex": opts.get("stepIndex"),
                            },
                            status="waiting",
                            deadline=deadline,
                        )
                    )
                    await session.commit()
                    args = opts.get("args") or {}
                    return {
                        "state": "waiting",
                        "approvalId": new_approval_id,
                        "message": (
                            f"⚠️ 安全拦截：系统检测到敏感支付操作 [退款金额: {args.get('refundAmount') or '100% 原路退回'}]。"
                            f"已物理拦截并自动生成人工审批工单 (ID: {new_approval_id})。"
                            "后台执行处于无阻塞安全挂起中，请管理员点击页面右上角【人工授权模拟面板】进行核发或驳回。"
                            if opts.get("toolName") == "processRefund"
                            else f"⚠️ 安全拦截：检测到高价值订单修改敏感操作 [申请更新配送地址为: {args.get('newAddress') or '新地址'}]。"
                            f"已物理拦截并自动生成人工审批工单 (ID: {new_approval_id})。"
                            "后台执行处于无阻塞安全挂起中，请管理员点击页面右上角【人工授权模拟面板】进行核发或驳回。"
                        ),
                    }

                # 3-6. 状态机迁移
                if latest_approval.status == "waiting":
                    return {"state": "waiting", "approvalId": str(latest_approval.id), "message": "审批工单审核中，任务保持挂起。"}
                if latest_approval.status == "cancelled":
                    return {
                        "state": "cancelled",
                        "approvalId": str(latest_approval.id),
                        "error": "用户已取消此项操作。",
                        "message": "⚠️ 您已主动取消了此笔审批。相关操作已被物理终止。",
                    }
                if latest_approval.status == "rejected":
                    payload = latest_approval.action_payload or {}
                    reason = payload.get("rejectionReason") or "申请不符合政策要求。"
                    return {
                        "state": "rejected",
                        "approvalId": str(latest_approval.id),
                        "rejectionReason": reason,
                        "message": f"❌ 人工审核拒绝：管理员驳回了本次申请，理由: [{reason}]。决策引擎即将启动回溯重规划。",
                    }
                return {"state": "approved", "approvalId": str(latest_approval.id), "isApproved": True}
        except Exception as err:  # noqa: BLE001
            print(f"[ApprovalGatekeeper] evaluatePendingApprovalState error: {err}")
            return {"state": "approved", "isApproved": False}

    @staticmethod
    async def list_pending_approvals(filter_opts: dict | None = None) -> list[dict]:
        filter_opts = filter_opts or {}
        target_tenant = (filter_opts.get("tenantId") or filter_opts.get("businessId") or "").lower().strip()
        async with get_session() as session:
            sql = (
                'SELECT pa.id, pa.thread_id AS "threadId", t.user_id AS "userId", u.email AS "userEmail", '
                'pa.action_type AS "actionType", pa.action_payload AS "actionPayload", pa.status, '
                'pa.deadline, pa.created_at AS "createdAt", t.business_id AS "businessId" '
                "FROM pending_approvals pa "
                "LEFT JOIN threads t ON pa.thread_id = t.id "
                "LEFT JOIN users u ON t.user_id = u.id::text"
            )
            conditions = []
            params = {}
            if target_tenant and target_tenant not in ("all", "admin"):
                conditions.append('t.business_id = :tenant')
                params["tenant"] = target_tenant
            if filter_opts.get("status") and filter_opts["status"] != "all":
                conditions.append("pa.status = :status")
                params["status"] = filter_opts["status"]
            if filter_opts.get("actionType") and filter_opts["actionType"] != "all":
                conditions.append("pa.action_type = :action_type")
                params["action_type"] = filter_opts["actionType"]
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY pa.created_at DESC"
            rows = (await session.execute(text(sql).bindparams(**params))).mappings().all()
            return [
                {
                    "id": str(row["id"]),
                    "threadId": row["threadId"],
                    "userId": row["userId"],
                    "userEmail": row["userEmail"],
                    "actionType": row["actionType"],
                    "actionPayload": row["actionPayload"],
                    "status": row["status"],
                    "deadline": row["deadline"].isoformat() if row["deadline"] else None,
                    "createdAt": row["createdAt"].isoformat() if row["createdAt"] else None,
                    "businessId": row["businessId"],
                }
                for row in rows
            ]

    @staticmethod
    async def create_pending_approval_ticket(params: dict) -> dict:
        thread_id = params["threadId"]
        try:
            await _ensure_thread_exists(thread_id, params.get("userId"))
        except Exception as t_err:  # noqa: BLE001
            print(f"[ApprovalGatekeeper] Thread ensure warning: {t_err}")

        async with get_session() as session:
            existing = (
                await session.execute(
                    select(PendingApproval).where(
                        PendingApproval.thread_id == thread_id, PendingApproval.status == "waiting"
                    )
                )
            ).scalars().first()

            if existing:
                approval_id = str(existing.id)
            else:
                approval_id = str(uuid.uuid4())
                session.add(
                    PendingApproval(
                        id=approval_id,
                        thread_id=thread_id,
                        action_type=params["actionType"],
                        action_payload=params["actionPayload"],
                        status="waiting",
                        deadline=_dt.datetime.now() + _dt.timedelta(hours=24),
                    )
                )
                await session.commit()

        step_to_run = dict(params["stepToRun"])
        current_plan = params["currentPlan"]
        current_index = params["currentIndex"]
        action_type = params["actionType"]

        updated_step = {
            **step_to_run,
            "status": "completed",
            "result": {
                "waitingForApproval": True,
                "approvalId": approval_id,
                "actionType": action_type,
                "message": (
                    "已成功创建人工客服接管工单，请等待客服主管接管回应。"
                    if action_type == "human_escalation"
                    else "安全红线拦截：当前属于资金或敏感高危操作，必须等待管理员人工核准放行。"
                ),
            },
        }
        updated_subtasks = list(current_plan.get("subtasks") or [])
        updated_subtasks[current_index] = updated_step
        next_plan = {**current_plan, "subtasks": updated_subtasks, "currentStepIndex": current_index + 1}

        if params.get("jobId"):
            await emit_status(
                params["jobId"],
                f"🚨 人工介入接管：已成功建立工单号 [{approval_id}] 的转人工待接管工单，已暂停自动决策流程！"
                if action_type == "human_escalation"
                else f"🛡️ 人工审核拦截：已生成审批工单 [{approval_id}]，暂停自动决策流。",
                node="executor",
                plan=next_plan,
            )

        return {"approvalId": approval_id, "nextPlan": next_plan}

    @staticmethod
    async def start_human_takeover(thread_id: str = "default_thread", default_user_id: str = _FALLBACK_USER_ID) -> dict:
        await _ensure_thread_exists(thread_id, default_user_id)

        async with get_session() as session:
            existing = (
                await session.execute(
                    select(PendingApproval)
                    .where(PendingApproval.thread_id == thread_id)
                    .order_by(desc(PendingApproval.created_at))
                    .limit(1)
                )
            ).scalar_one_or_none()

            thread_row = (
                await session.execute(
                    text(
                        'SELECT t.business_id AS "businessId", t.user_id AS "userId", u.email AS "userEmail" '
                        "FROM threads t LEFT JOIN users u ON t.user_id = u.id::text WHERE t.id = :tid LIMIT 1"
                    ).bindparams(tid=thread_id)
                )
            ).mappings().first()
            business_id = (thread_row["businessId"] if thread_row else None) or "ecommerce"
            thread_user_id = thread_row["userId"] if thread_row else None
            thread_user_email = thread_row["userEmail"] if thread_row else None

            if existing:
                return {
                    "success": True,
                    "approvalId": str(existing.id),
                    "approval": {
                        "id": str(existing.id),
                        "threadId": existing.thread_id,
                        "actionType": existing.action_type,
                        "actionPayload": existing.action_payload,
                        "status": existing.status,
                        "deadline": existing.deadline.isoformat() if existing.deadline else None,
                        "businessId": business_id,
                        "userId": thread_user_id,
                        "userEmail": thread_user_email,
                    },
                }

            new_id = str(uuid.uuid4())
            deadline = _dt.datetime.now() + _dt.timedelta(minutes=30)
            payload = {"userInput": "客服随时主动接管实时对话", "reason": "客服主动发起 IM 实时接管"}
            session.add(
                PendingApproval(
                    id=new_id,
                    thread_id=thread_id,
                    action_type="human_escalation",
                    action_payload=payload,
                    status="resolved_by_human",
                    deadline=deadline,
                )
            )
            await session.commit()

        # 📥 Bad-Case 信号入池:转人工(中性先验,仅新建工单时记录,重复呼叫不重复入池)
        await record_badcase_signal(
            SOURCE_HUMAN_TAKEOVER,
            conversation_ref=f"thread:{thread_id}",
            business_id=business_id,
            note="实时人工接管被发起",
        )

        await _add_system_message(
            thread_id, "system", "【系统提示】人工客服已主动接入当前会话，您可以向客服发送消息进行实时沟通。"
        )
        return {
            "success": True,
            "approvalId": new_id,
            "approval": {
                "id": new_id,
                "threadId": thread_id,
                "businessId": business_id,
                "userId": thread_user_id,
                "userEmail": thread_user_email,
                "actionType": "human_escalation",
                "actionPayload": payload,
                "status": "resolved_by_human",
                "deadline": deadline.isoformat(),
                "createdAt": _dt.datetime.now().isoformat(),
            },
        }

    @staticmethod
    async def process_approval_action(options: dict) -> dict:
        approval_id = options.get("approvalId")
        thread_id = options.get("threadId")
        action = options.get("action")
        rejection_reason = options.get("rejectionReason")
        human_reply = options.get("humanReply")
        is_finish = options.get("isFinish")

        if action == "start_human_takeover":
            return await ApprovalGatekeeper.start_human_takeover(thread_id or "default_thread")

        if not approval_id or not action:
            return {"error": "approvalId and action are required", "statusCode": 400}
        if not _UUID_RE.match(approval_id):
            return {"error": f"Approval工单 {approval_id} 格式无效或未找到", "statusCode": 404}

        lock_key = f"lock:approval:{approval_id}"
        lock_acquired = False
        fallback_acquired = False

        try:
            client = await get_client()
        except Exception:  # noqa: BLE001 — Redis 不可用时回退内存锁
            client = None
        if client is not None:
            try:
                result = await client.set(lock_key, "locked", px=5000, nx=True)
                lock_acquired = result is not None and str(result).upper() == "OK"
            except Exception as err:  # noqa: BLE001
                print(f"[ApprovalGatekeeper Lock] Redis SETNX failed, falling back to memory lock: {err}")

        if not lock_acquired:
            if lock_key in _local_locks:
                return {"error": "请勿重复提交，审批正在处理中...", "statusCode": 409}
            _local_locks.add(lock_key)
            fallback_acquired = True

        try:
            async with get_session() as session:
                record = (
                    await session.execute(
                        select(PendingApproval).where(PendingApproval.id == approval_id).limit(1)
                    )
                ).scalar_one_or_none()
                if record is None:
                    return {"error": f"Approval工单 {approval_id} 未找到", "statusCode": 404}

                if action in ("human_message",) or (action == "human_reply" and is_finish is False):
                    if human_reply and human_reply.strip():
                        await _add_system_message(record.thread_id, "assistant", f"[人工客服] {human_reply.strip()}")
                    return {"success": True, "isHumanActive": True, "threadId": record.thread_id}

                if record.status != "waiting":
                    return {
                        "error": f"工单 {approval_id} 已经处理过，当前状态为: {record.status}",
                        "statusCode": 400,
                    }

                next_status = "rejected"
                if action == "approve":
                    if record.action_type == "human_escalation":
                        next_status = "resolved_by_human"
                        reply = (human_reply and human_reply.strip()) or "您好！人工客服专员已接入当前会话为您服务。请问有什么可以帮您？"
                        await _add_system_message(record.thread_id, "assistant", f"[人工客服] {reply}")
                    else:
                        next_status = "approved"
                elif action == "cancel":
                    next_status = "cancelled"
                elif action in ("human_finish", "human_reply") or record.action_type == "human_escalation":
                    next_status = "resolved_by_human"
                    if human_reply and human_reply.strip():
                        await _add_system_message(record.thread_id, "assistant", f"[人工客服] {human_reply.strip()}")
                    await _add_system_message(
                        record.thread_id, "system", "【系统提示】人工客服服务已结束，已成功为您切回 AI 智能助手。"
                    )

                updated_payload = {
                    **(record.action_payload or {}),
                    "rejectionReason": rejection_reason or "",
                    "humanReply": human_reply or "",
                }

                # 🎯 确定性 Job ID:job_resume_${approvalId},物理防重幂等
                deterministic_job_id = f"job_resume_{approval_id}"
                outbox_event_id = str(uuid.uuid4())

                if next_status == "approved":
                    system_prompt_text = "System: Human approval granted. Please execute the requested action."
                elif next_status == "cancelled":
                    system_prompt_text = (
                        "System: Human approval cancelled by the user. Please stop the requested action, "
                        "abort any tool calls for this refund, and explain to the user that the action has "
                        "been successfully cancelled per their request."
                    )
                else:
                    system_prompt_text = (
                        f"System: Human approval rejected. Reason: {rejection_reason or 'Not policy compliant'}. "
                        "Please replan alternative path."
                    )

                thread_user_id = _FALLBACK_USER_ID
                thread_row = (
                    await session.execute(
                        text('SELECT user_id AS "userId" FROM threads WHERE id = :tid LIMIT 1').bindparams(
                            tid=record.thread_id
                        )
                    )
                ).mappings().first()
                if thread_row and thread_row["userId"]:
                    thread_user_id = thread_row["userId"]

                event_type = (
                    "resume_execution"
                    if next_status == "approved"
                    else "cancel_execution"
                    if next_status == "cancelled"
                    else "reject_execution"
                )
                outbox_payload = {
                    "jobId": deterministic_job_id,
                    "threadId": record.thread_id,
                    "userId": thread_user_id,
                    "businessId": record.business_id,
                    "systemPromptText": system_prompt_text,
                    "nextStatus": next_status,
                }

                # 🔒 事务发件箱:工单状态更新与事件插入同一事务原子提交
                async with session.begin_nested():
                    record.status = next_status
                    record.action_payload = updated_payload
                    if next_status != "resolved_by_human":
                        session.add(
                            ApprovalOutboxEvent(
                                id=outbox_event_id,
                                approval_id=approval_id,
                                thread_id=record.thread_id,
                                event_type=event_type,
                                payload=outbox_payload,
                                status="pending",
                                retry_count=0,
                            )
                        )
                await session.commit()

            # 📥 Bad-Case 信号入池:驳回退款(默认设计行为先验;Fast-Path 派发与信号互不影响)
            if next_status == "rejected":
                await record_badcase_signal(
                    SOURCE_APPROVAL_REJECTED,
                    conversation_ref=f"approval:{approval_id}",
                    business_id=str(getattr(record, "business_id", None) or "ecommerce"),
                    note=f"审批驳回,原因: {rejection_reason or '未填写'}",
                )

            if next_status == "resolved_by_human":
                return {"success": True, "threadId": thread_id or record.thread_id, "status": next_status}

            # ⚡ Fast-Path 同步派发:成功标 completed,失败留 pending 由对账 Worker 重试
            try:
                from ..run_agent import AgentJobInput, run_agent

                asyncio.create_task(
                    run_agent(
                        AgentJobInput(
                            jobId=deterministic_job_id,
                            threadId=record.thread_id,
                            userId=thread_user_id,
                            businessId=record.business_id,
                            message=system_prompt_text,
                        )
                    )
                )
                async with get_session() as session:
                    await session.execute(
                        text(
                            "UPDATE approval_outbox_events SET status = 'completed', updated_at = NOW() "
                            "WHERE id = CAST(:eid AS uuid)"
                        ).bindparams(eid=outbox_event_id)
                    )
                    await session.commit()
            except Exception as dispatch_err:  # noqa: BLE001
                async with get_session() as session:
                    await session.execute(
                        text(
                            "UPDATE approval_outbox_events SET status = 'pending', error_message = :err, "
                            "updated_at = NOW() WHERE id = CAST(:eid AS uuid)"
                        ).bindparams(err=str(dispatch_err), eid=outbox_event_id)
                    )
                    await session.commit()

            return {
                "success": True,
                "jobId": deterministic_job_id,
                "threadId": record.thread_id,
                "status": next_status,
            }
        except Exception as err:  # noqa: BLE001
            print(f"[ApprovalGatekeeper] Approval processing error: {err}")
            return {"error": f"审批执行失败: {err}", "statusCode": 500}
        finally:
            if lock_acquired and client is not None:
                try:
                    await client.delete(lock_key)
                except Exception as err:  # noqa: BLE001
                    print(f"[ApprovalGatekeeper Lock] Redis DEL failed: {err}")
            if fallback_acquired:
                _local_locks.discard(lock_key)


ApprovalPolicyEngine = ApprovalGatekeeper
