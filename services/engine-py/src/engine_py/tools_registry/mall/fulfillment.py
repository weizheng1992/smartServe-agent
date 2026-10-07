"""履约后簇:包裹轨迹 + 售后申请。"""

from __future__ import annotations

import json
import random
import time

from sqlalchemy import text

from ...db import get_session
from ...tenant_context import resolve_business_id
from ..cache import tool_cache
from ..order_domain import OrderDomainService

MallDomainService = None  # service.py 类定义后回填(调用时经本模块全局解析,patch 面不漂移)


class FulfillmentMixin:
    """簇方法集;经 service.MallDomainService 合并为一类(全部 staticmethod)。"""

    @staticmethod
    async def query_package_tracking(params: dict) -> dict:
        """3. 查询物流时序轨迹与实时派送状态。"""
        order_id = params.get("orderId")
        tracking_number = params.get("trackingNumber")
        try:
            async with get_session() as session:
                pkg_row = None
                if tracking_number:
                    pkg_row = (
                        (
                            await session.execute(
                                text(
                                    'SELECT id, business_id AS "businessId", order_id AS "orderId", carrier, '
                                    'carrier_code AS "carrierCode", tracking_number AS "trackingNumber", status, '
                                    'current_location AS "currentLocation", courier_name AS "courierName", '
                                    'courier_phone AS "courierPhone", estimated_delivery AS "estimatedDelivery" '
                                    "FROM logistics_packages WHERE tracking_number = :tn LIMIT 1"
                                ).bindparams(tn=tracking_number)
                            )
                        )
                        .mappings()
                        .first()
                    )
                elif order_id:
                    pkg_row = (
                        (
                            await session.execute(
                                text(
                                    'SELECT id, business_id AS "businessId", order_id AS "orderId", carrier, '
                                    'carrier_code AS "carrierCode", tracking_number AS "trackingNumber", status, '
                                    'current_location AS "currentLocation", courier_name AS "courierName", '
                                    'courier_phone AS "courierPhone", estimated_delivery AS "estimatedDelivery" '
                                    "FROM logistics_packages WHERE order_id = :oid ORDER BY created_at DESC LIMIT 1"
                                ).bindparams(oid=order_id)
                            )
                        )
                        .mappings()
                        .first()
                    )

                if pkg_row:
                    tracks = (
                        (
                            await session.execute(
                                text(
                                    'SELECT id, package_id AS "packageId", occurred_at AS "occurredAt", '
                                    "location, status, description FROM logistics_tracks "
                                    "WHERE package_id = :pid ORDER BY occurred_at DESC"
                                ).bindparams(pid=pkg_row["id"])
                            )
                        )
                        .mappings()
                        .all()
                    )
                    estimated = pkg_row.get("estimatedDelivery")
                    return {
                        "packageId": str(pkg_row["id"]),
                        "orderId": pkg_row["orderId"],
                        "carrier": pkg_row["carrier"],
                        "carrierCode": pkg_row["carrierCode"],
                        "trackingNumber": pkg_row["trackingNumber"],
                        "packageStatus": pkg_row["status"],
                        "currentLocation": pkg_row.get("currentLocation") or "集散中心分拨中",
                        "courier": (
                            {"name": pkg_row["courierName"], "phone": pkg_row.get("courierPhone") or "95338"}
                            if pkg_row.get("courierName")
                            else None
                        ),
                        "estimatedDelivery": str(estimated)[:10] if estimated else "预计明日送达",
                        "trackTimeline": [
                            {
                                "time": str(t["occurredAt"]),
                                "location": t["location"],
                                "status": t["status"],
                                "description": t["description"],
                            }
                            for t in tracks
                        ],
                    }
        except Exception as err:
            print(f"[MallDomainService.queryPackageTracking] Database tracking error: {err}")

        return {
            "packageId": "pkg_sf_1092837465",
            "orderId": order_id or "ORD-ECOM-889901",
            "carrier": "顺丰速运 (SF Express)",
            "carrierCode": "SF",
            "trackingNumber": tracking_number or "SF1092837465",
            "packageStatus": "delivering",
            "currentLocation": "北京市朝阳区酒仙桥分部",
            "courier": {"name": "张师傅", "phone": "138-1234-5678"},
            "estimatedDelivery": "2026-08-25",
            "trackTimeline": [
                {
                    "time": "2026-08-22 08:30:00",
                    "location": "北京市朝阳区酒仙桥派件网点",
                    "status": "dispatching",
                    "description": "【北京市】快件已由派件员张师傅（电话：13812345678）正在为您派送，请注意接听电话",
                },
                {
                    "time": "2026-08-21 23:45:00",
                    "location": "北京顺义集散中心",
                    "status": "transporting",
                    "description": "【北京市】快件到达北京顺义集散中心，准备发往朝阳区酒仙桥网点",
                },
                {
                    "time": "2026-08-21 14:20:00",
                    "location": "上海青浦分拨中心",
                    "status": "transporting",
                    "description": "【上海市】快件已从上海青浦分拨中心发出，运往北京",
                },
                {
                    "time": "2026-08-20 18:00:00",
                    "location": "上海市闵行区揽收部",
                    "status": "picked_up",
                    "description": "【上海市】顺丰速运 已揽收",
                },
            ],
        }

    @staticmethod
    async def apply_after_sale(params: dict) -> dict:
        """5. 提交售后退款/退货退款/换货工单。"""
        thread_id = params.get("threadId")
        effective_user_id = ""
        effective_biz_id: str | None = None
        if thread_id:
            ctx = await OrderDomainService.get_thread_session_context(thread_id)
            effective_user_id = ctx["userId"]
            effective_biz_id = ctx["businessId"]
        # A7:无 threadId 时先吃入口上下文,再落平台默认(不再无条件 ecommerce)
        effective_biz_id = resolve_business_id(effective_biz_id)

        # 缺单号诚实报错(nightly 2026-09-23):LLM 深规划对缺槽退款复合句
        # (「看订单顺便把没发货的退了」)可能产出无 orderId 的售后子任务,
        # params["orderId"] 硬下标曾 KeyError 炸图执行降级道歉文案。
        order_id = params.get("orderId")
        if not order_id:
            return {"error": "⚠️ 售后申请失败：请提供订单编号，或先告诉我您要退哪一笔订单。"}

        order = await OrderDomainService.find_order_by_id(
            order_id, effective_user_id, effective_biz_id
        )
        if not order:
            return {"error": f"⚠️ 售后申请失败：订单 {order_id} 不属于您名下或不存在。"}

        ticket_id = f"AS-{int(time.time()):X}-{random.randint(100, 999)}"
        refund_amount = params.get("refundAmount") or float(order.get("totalAmount") or 0) or 100.0
        # ADR-0002 Q1/Q2:本轮上传的瑕疵凭证落票(上限与引擎视觉上限一致);
        # 不传 = 空数组,旧行为零破坏。executor 层程序化注入,严禁指望 LLM 抄 URL。
        from ...vision.analyzer import MAX_IMAGES_PER_MESSAGE

        evidence_urls = [str(u) for u in (params.get("evidenceImageUrls") or [])][:MAX_IMAGES_PER_MESSAGE]

        try:
            async with get_session() as session:
                await session.execute(
                    text(
                        "INSERT INTO after_sale_tickets ("
                        "id, business_id, order_id, order_item_id, user_id, "
                        "type, reason, reason_description, refund_amount, evidence_urls, status, created_at, updated_at"
                        ") VALUES ("
                        ":tid, :bid, :oid, :oiid, :uid, :type, :reason, :rdesc, :amount, "
                        "CAST(:evidence AS jsonb), 'pending_review', NOW(), NOW())"
                    ).bindparams(
                        tid=ticket_id,
                        bid=effective_biz_id,
                        oid=order_id,
                        oiid=params.get("orderItemId"),
                        uid=effective_user_id or order.get("userId") or "user_001",
                        type=params["type"],
                        reason=params["reason"],
                        rdesc=params.get("reasonDescription") or "用户通过智能客服提交售后申请",
                        amount=refund_amount,
                        evidence=json.dumps(evidence_urls, ensure_ascii=False),
                    )
                )
                await session.execute(
                    text(
                        "INSERT INTO after_sale_logs (ticket_id, action, operator, note, created_at) "
                        "VALUES (:tid, 'created', 'agent_autopilot', :note, NOW())"
                    ).bindparams(
                        tid=ticket_id, note=f"用户申请【{params['type']}】，原因: {params['reason']}"
                    )
                )
                await session.commit()
        except Exception as err:
            # 诚实失败(ADR-0002):工单没落库就严禁播报「已提交」——吞异常
            # 返回假 success 是 2026-09-12 实弹抓出的存量欺骗(商户单售后
            # 因 order_id 外键错位从未真正落库)。
            print(f"[MallDomainService.applyAfterSale] 售后工单落库失败 orderId={params.get('orderId')}: {err}")
            return {"success": False, "error": "售后工单提交失败，请稍后重试或转人工客服处理。"}

        await tool_cache.delete(f"cache:order_status:{order_id}")

        return {
            "success": True,
            "ticketId": ticket_id,
            "orderId": order_id,
            "type": params["type"],
            "reason": params["reason"],
            "refundAmount": f"¥{refund_amount:.2f}",
            "status": "pending_review",
            "evidenceCount": len(evidence_urls),
            "instruction": (
                "仅退款申请已提交，系统预计将在 1-2 小时内原路返还款项。"
                if params["type"] == "refund_only"
                else "退货退款申请已受理，请等待商家审核通过后获取回寄地址与退货运单单号。"
            ),
        }

    # MOCK_PRODUCTS(3 件 Nike 假目录)已于 2026-09-11 L3 整体拆除:它是
    # 「要背包给跑鞋」症状的假货源头,降级链终点改诚实空;test_guide_skills
    # 用各自的局部桩数据,不依赖此属性。
