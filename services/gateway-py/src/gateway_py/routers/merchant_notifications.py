"""商户站内消息推送(/api/admin/notifications*、/api/store/notifications*)
—— mall-notifications(spec .scratch/mall-notifications,2026-10-31):员工→
顾客单向公告。数据面:agent_merchant.merchant_notifications +
merchant_notification_reads(merchant_db.py 幂等 DDL);广播不 fan-out
(target_type='all'),未读 = anti-join reads;recipient_count 发送时快照,
历史列表直读免实时 COUNT。

实时面(03 票):信号帧非数据帧 —— 定向 publish notify:user/{customerId}、
广播 publish notify:business/{businessId},SSE 端订阅转发;数据真源恒为本
文件的查询端点(pubsub 无回放,断线补齐靠进页拉取)。发布失败只打日志不回滚
已落库消息(publish_thread_message 同纪律)。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..tenant_scope import StaffContext, staff_context

router = APIRouter()

# 单员工单日广播上限(spec D12:gateway 常量起步,防误触不防恶意;单发不限)
BROADCAST_DAILY_LIMIT = 20


def _iso_utc(value: datetime) -> str:
    """库侧 naive UTC → aware ISO(server-gateway.md 两套钟律:naive 串会被
    前端按本地解析,实弹下单时间早 8 小时)。"""
    return value.replace(tzinfo=UTC).isoformat()


class NotificationSendIn(BaseModel):
    targetType: str = "all"
    customerId: str | None = None
    title: str
    body: str


async def _publish_signal(business_id: str, target_type: str, customer_id: str | None) -> None:
    """通知信号帧发布单点:单频道 notify:business:{businessId}(03 裁决 ——
    tail_pubsub 只支持单频道订阅,不为双频道改公共泵语义;帧零内容只当信号,
    定向帧带 targetUserId 由连接侧过滤)。发布失败只打日志,不回滚已落库
    真消息(publish_thread_message 同纪律)。"""
    try:
        import json as _json

        from engine_py.event_bus import get_client

        client = await get_client()
        if client is None:
            return
        payload: dict[str, Any] = {"type": "notification"}
        if target_type == "customer" and customer_id:
            payload["targetUserId"] = customer_id
        await client.publish(f"notify:business:{business_id}", _json.dumps(payload))
    except Exception as err:  # 实时增强失败不回滚落库真消息
        print(f"[Notify] signal publish 失败(不影响落库): {err!r}")


# ---------------- 员工侧(merchant-admin,staff JWT + perm 闸) ----------------


@router.post("/api/admin/notifications")
async def admin_send_notification(
    request: Request, body: NotificationSendIn, ctx: StaffContext = Depends(staff_context)
):
    """发送站内消息(广播 / 单客定向;perm 闸 notify:send,与 promotions 同款)。

    频控是防误触闸不是安全闸(D12):超限业务错误 success=False 400,前端按
    errMsgOf 呈现,不 throw。"""
    if "notify:send" not in ctx["perms"]:
        return JSONResponse(status_code=403, content={"success": False, "message": "无消息推送权限"})
    title = body.title.strip()
    body_text = body.body.strip()
    if not title or len(title) > 50:
        return JSONResponse(status_code=400, content={"success": False, "message": "标题必填且不超过 50 字"})
    # 正文可留空(spec D2 只钉标题必填;F3「无正文场景『—』」预设空正文合法),
    # 仅闸长度上限
    if len(body_text) > 500:
        return JSONResponse(status_code=400, content={"success": False, "message": "正文不超过 500 字"})
    target_type = body.targetType
    if target_type not in ("all", "customer"):
        return JSONResponse(status_code=400, content={"success": False, "message": "targetType 仅支持 all | customer"})
    customer_id = (body.customerId or "").strip()
    if target_type == "customer" and not customer_id:
        return JSONResponse(status_code=400, content={"success": False, "message": "定向发送必须指定 customerId"})

    from engine_py.tools_registry.order_domain import merchant_writer_engine
    from sqlalchemy import text

    from gateway_py.merchant_db import ensure_merchant_tables

    await ensure_merchant_tables()
    business_id = ctx["business_id"]
    created_by = str(ctx["staff_id"])
    async with merchant_writer_engine().begin() as conn:
        if target_type == "customer":
            exists = (
                await conn.execute(
                    text("SELECT 1 FROM merchant_customers WHERE customer_id = :cid").bindparams(cid=customer_id)
                )
            ).first()
            if not exists:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": f"顾客 {customer_id} 不存在"},
                )
            recipient_count = 1
        else:
            today_start = datetime.now(UTC).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
            sent_today = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM merchant_notifications "
                        "WHERE business_id = :b AND target_type = 'all' "
                        "AND created_by = :by AND created_at >= :since"
                    ).bindparams(b=business_id, by=created_by, since=today_start)
                )
            ).scalar_one()
            if sent_today >= BROADCAST_DAILY_LIMIT:
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "message": f"今日广播已达上限({BROADCAST_DAILY_LIMIT} 条),请明日再试",
                    },
                )
            recipient_count = (await conn.execute(text("SELECT COUNT(*) FROM merchant_customers"))).scalar_one()
        row = (
            await conn.execute(
                text(
                    "INSERT INTO merchant_notifications "
                    "(business_id, target_type, customer_id, title, body, msg_type, recipient_count, created_by) "
                    "VALUES (:b, :tt, :cid, :title, :body, 'announcement', :rc, :by) "
                    "RETURNING id, created_at"
                ).bindparams(
                    b=business_id, tt=target_type, cid=customer_id or None, title=title,
                    body=body_text, rc=recipient_count, by=created_by,
                )
            )
        ).mappings().one()
    await _publish_signal(business_id, target_type, customer_id or None)
    return {
        "success": True,
        "data": {
            "id": str(row["id"]),
            "targetType": target_type,
            "recipientCount": recipient_count,
            "createdAt": _iso_utc(row["created_at"]),
        },
    }


@router.get("/api/admin/notifications")
async def admin_list_notifications(
    ctx: StaffContext = Depends(staff_context),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
):
    """已发历史(只读审计,spec F2):时间倒序,定向行 JOIN 出顾客名;
    **无已读回执字段**(D6 —— 商户不见回执)。"""
    if "notify:send" not in ctx["perms"]:
        return JSONResponse(status_code=403, content={"success": False, "message": "无消息推送权限"})

    from engine_py.tools_registry.order_domain import merchant_writer_engine
    from sqlalchemy import text

    from gateway_py.merchant_db import ensure_merchant_tables

    await ensure_merchant_tables()
    offset = (page - 1) * pageSize
    async with merchant_writer_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT n.id, n.target_type, n.customer_id, c.name AS customer_name, "
                    "n.title, n.body, n.msg_type, n.recipient_count, n.created_by, n.created_at "
                    "FROM merchant_notifications n "
                    "LEFT JOIN merchant_customers c ON c.customer_id = n.customer_id "
                    "WHERE n.business_id = :b ORDER BY n.created_at DESC LIMIT :l OFFSET :o"
                ).bindparams(b=ctx["business_id"], l=pageSize, o=offset)
            )
        ).mappings().all()
        total = (
            await conn.execute(
                text("SELECT COUNT(*) FROM merchant_notifications WHERE business_id = :b").bindparams(
                    b=ctx["business_id"]
                )
            )
        ).scalar_one()
    items: list[dict[str, Any]] = [
        {
            "id": str(r["id"]),
            "targetType": r["target_type"],
            "customerId": r["customer_id"],
            "customerName": r["customer_name"],
            "title": r["title"],
            "body": r["body"],
            "msgType": r["msg_type"],
            "recipientCount": r["recipient_count"],
            "createdBy": r["created_by"],
            "createdAt": _iso_utc(r["created_at"]),
        }
        for r in rows
    ]
    return {"success": True, "data": {"notifications": items, "total": total, "page": page, "pageSize": pageSize}}


# ---------------- 顾客侧(store 面,自报身份;/api/store 聊天同律) ----------------


def _bad_request(message: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"success": False, "message": message})


def _is_customer(user_id: str) -> bool:
    """顾客身份闸单点(spec F3 原文:接口按**非 CUST-*** 返回空且不入库 reads
    —— 不只挡 guest- 前缀,任意非顾客身份一律诚实空;推送对象域就是顾客)。"""
    return user_id.startswith("CUST-")


def _visible_and_unread(*, unread_only: bool = False) -> str:
    """本人可见集(广播 ∪ 发给我的,:b 租户 / :uid 顾客)与未读判定的 SQL
    片段单点 —— 顾客属主语义只此一处,严禁调用方手工重复拼接(窃听族收口
    同纪律)。"""
    cond = "n.business_id = :b AND (n.target_type = 'all' OR n.customer_id = :uid)"
    if unread_only:
        cond += (" AND NOT EXISTS (SELECT 1 FROM merchant_notification_reads r "
                 "WHERE r.notification_id = n.id AND r.customer_id = :uid)")
    return cond


@router.get("/api/store/notifications")
async def store_list_notifications(
    userId: str | None = Query(None),
    businessId: str = Query("aurora"),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
):
    """我的消息分页(时间倒序,含已读态)。非 CUST-* 身份诚实空(U2 律零接入,
    不查库不落 reads)。userId 必报走手写 400(store/chat 先例,非 Pydantic 422)。"""
    user_id = (userId or "").strip()
    if not user_id:
        return _bad_request("userId 必传")
    if not _is_customer(user_id):
        return {"success": True, "data": {"notifications": [], "total": 0, "page": page, "pageSize": pageSize}}

    from engine_py.tools_registry.order_domain import merchant_writer_engine
    from sqlalchemy import text

    from gateway_py.merchant_db import ensure_merchant_tables

    await ensure_merchant_tables()
    offset = (page - 1) * pageSize
    async with merchant_writer_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT n.id, n.title, n.body, n.msg_type, n.customer_id, n.created_at, "
                    "EXISTS(SELECT 1 FROM merchant_notification_reads r "
                    "       WHERE r.notification_id = n.id AND r.customer_id = :uid) AS is_read "
                    "FROM merchant_notifications n "
                    f"WHERE {_visible_and_unread()}"
                    "ORDER BY n.created_at DESC LIMIT :l OFFSET :o"
                ).bindparams(b=businessId, uid=user_id, l=pageSize, o=offset)
            )
        ).mappings().all()
        total = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM merchant_notifications n "
                    f"WHERE {_visible_and_unread()}"
                ).bindparams(b=businessId, uid=user_id)
            )
        ).scalar_one()
    return {
        "success": True,
        "data": {
            "notifications": [
                {
                    "id": str(r["id"]),
                    "title": r["title"],
                    "body": r["body"],
                    "msgType": r["msg_type"],
                    "isRead": bool(r["is_read"]),
                    "createdAt": _iso_utc(r["created_at"]),
                }
                for r in rows
            ],
            "total": total,
            "page": page,
            "pageSize": pageSize,
        },
    }


@router.get("/api/store/notifications/unread-count")
async def store_unread_count(userId: str | None = Query(None), businessId: str = Query("aurora")):
    """未读数(铃铛徽标真源;anti-join reads)。非 CUST-* 恒 0。"""
    user_id = (userId or "").strip()
    if not user_id:
        return _bad_request("userId 必传")
    if not _is_customer(user_id):
        return {"success": True, "data": {"unread": 0}}

    from engine_py.tools_registry.order_domain import merchant_writer_engine
    from sqlalchemy import text

    from gateway_py.merchant_db import ensure_merchant_tables

    await ensure_merchant_tables()
    async with merchant_writer_engine().connect() as conn:
        unread = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM merchant_notifications n "
                    f"WHERE {_visible_and_unread(unread_only=True)}"
                ).bindparams(b=businessId, uid=user_id)
            )
        ).scalar_one()
    return {"success": True, "data": {"unread": unread}}


class NotificationReadIn(BaseModel):
    userId: str
    businessId: str = "aurora"
    ids: list[str] | None = None
    all: bool = False


@router.post("/api/store/notifications/read")
async def store_mark_read(body: NotificationReadIn):
    """标已读(单/批/全部;幂等 ON CONFLICT DO NOTHING)。

    可见性闸:INSERT...SELECT 带本人可见集条件 —— 看不到的消息标不了已读
    (跨客定向 id 混入是静默 no-op,不报错不越权)。非 CUST-* 成功空操作。"""
    user_id = body.userId.strip()
    if not user_id:
        return _bad_request("userId 必传")
    if not _is_customer(user_id):
        return {"success": True, "data": {"marked": 0}}

    from engine_py.tools_registry.order_domain import merchant_writer_engine
    from sqlalchemy import text

    from gateway_py.merchant_db import ensure_merchant_tables

    await ensure_merchant_tables()
    async with merchant_writer_engine().begin() as conn:
        if body.all:
            stmt = text(
                "INSERT INTO merchant_notification_reads (notification_id, customer_id) "
                "SELECT n.id, :uid FROM merchant_notifications n "
                f"WHERE {_visible_and_unread()} "
                "ON CONFLICT DO NOTHING"
            ).bindparams(uid=user_id, b=body.businessId)
        else:
            ids = [i for i in (body.ids or []) if str(i).strip()]
            if not ids:
                return _bad_request("ids 与 all 至少提供其一")
            stmt = text(
                "INSERT INTO merchant_notification_reads (notification_id, customer_id) "
                "SELECT n.id, :uid FROM merchant_notifications n "
                f"WHERE {_visible_and_unread()} "
                "AND n.id::text = ANY(:ids) "
                "ON CONFLICT DO NOTHING"
            ).bindparams(uid=user_id, b=body.businessId, ids=ids)
        marked = (await conn.execute(stmt)).rowcount
    return {"success": True, "data": {"marked": marked}}


@router.get("/api/store/notifications/stream")
async def store_notifications_stream(
    request: Request,
    userId: str | None = Query(None),
    businessId: str = Query("aurora"),
):
    """用户级实时信号流(store 面第 5 条 SSE;复用 tail_pubsub 泵)。

    闸:userId 必报(手写 400,列表端点同律);游客 400 拒连 —— 无消息入口的
    匿名身份不养连接(U2 律)。

    频道拓扑(03 裁决,见 _publish_signal):单频道 fan-in,定向帧带
    targetUserId、连接侧过滤 —— 服务端不做 per-connection 过滤(那需要复制
    tail_pubsub 泵或改其公共语义,两者都不值);帧零消息内容,与 store chat
    stream 的自报身份信任模型一致。无回放(ADR-0013 补投是 DB 时间线回放,
    通知无时间线源):断线窗口的信号丢失不丢数据,数据真源恒为列表/未读数
    端点,前端重连成功即重拉。"""
    user_id = (userId or "").strip()
    if not user_id:
        return _bad_request("userId 必传")
    if not _is_customer(user_id):
        return _bad_request("仅注册顾客可订阅消息流(U2 律零接入)")

    from fastapi.responses import StreamingResponse

    from ..sse_tail import streaming_headers, tail_pubsub

    return StreamingResponse(
        tail_pubsub(
            f"notify:business:{businessId}",
            connected_payload={"userId": user_id},
            disconnected=request.is_disconnected,
        ),
        media_type="text/event-stream",
        headers=streaming_headers(),
    )
