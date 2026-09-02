"""商城领域服务 — 镜像 tools/src/mallDomainService.ts(984 LOC,全量移植,含种子兜底)。"""

from __future__ import annotations

import datetime as _dt
import random
import time

from sqlalchemy import text

from ..db import get_session
from .cache import tool_cache
from .order_domain import OrderDomainService


class MallDomainService:
    # 购物车进程内存态(与 TS cartStorage 一致,单实例假设)
    _cart_storage: dict[str, list[dict]] = {}

    @staticmethod
    async def get_user_addresses(user_id: str | None = None, business_id: str | None = None, thread_id: str | None = None) -> dict:
        """1. 查询用户收货地址簿。"""
        effective_user_id = user_id
        effective_biz_id = business_id or "ecommerce"
        if (not effective_user_id or effective_biz_id == "ecommerce") and thread_id:
            ctx = await OrderDomainService.get_thread_session_context(thread_id)
            effective_user_id = effective_user_id or ctx["userId"]
            if ctx["businessId"]:
                effective_biz_id = ctx["businessId"]

        try:
            conditions: list[str] = []
            params: dict = {}
            if effective_biz_id and effective_biz_id != "ecommerce":
                conditions.append("business_id = :bid")
                params["bid"] = effective_biz_id
            if effective_user_id:
                conditions.append("user_id = :uid")
                params["uid"] = effective_user_id
            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            async with get_session() as session:
                rows = (
                    (
                        await session.execute(
                            text(
                                'SELECT id, business_id AS "businessId", user_id AS "userId", '
                                'receiver_name AS "receiverName", receiver_phone AS "receiverPhone", '
                                'province, city, district, detail_address AS "detailAddress", '
                                'full_address AS "fullAddress", tag, is_default AS "isDefault", '
                                'created_at AS "createdAt" FROM user_addresses '
                                f"{where_clause} ORDER BY is_default DESC, created_at DESC LIMIT 10"
                            ).bindparams(**params)
                        )
                    )
                    .mappings()
                    .all()
                )
                if rows:
                    return {
                        "total": len(rows),
                        "userId": effective_user_id or "current_user",
                        "addresses": [
                            {
                                "id": str(r["id"]),
                                "receiverName": r["receiverName"],
                                "receiverPhone": r["receiverPhone"],
                                "fullAddress": r["fullAddress"]
                                or f'{r["province"]}{r["city"]}{r["district"]}{r["detailAddress"]}',
                                "tag": r["tag"] or "home",
                                "isDefault": bool(r["isDefault"]),
                            }
                            for r in rows
                        ],
                    }
        except Exception as err:  # noqa: BLE001
            print(f"[MallDomainService.getUserAddresses] Database query error: {err}")

        # 默认高保真种子数据兜底
        return {
            "total": 2,
            "userId": effective_user_id or "current_user",
            "addresses": [
                {
                    "id": "addr_default_home_01",
                    "receiverName": "张先生",
                    "receiverPhone": "138****8899",
                    "fullAddress": "北京市海淀区中关村南大街1号院3号楼802室",
                    "tag": "home",
                    "isDefault": True,
                },
                {
                    "id": "addr_company_office_02",
                    "receiverName": "张先生 (公司)",
                    "receiverPhone": "138****8899",
                    "fullAddress": "北京市朝阳区酒仙桥路恒通商务园B8栋5层",
                    "tag": "company",
                    "isDefault": False,
                },
            ],
        }

    @staticmethod
    async def save_user_address(params: dict) -> dict:
        """保存或新增用户收货地址。"""
        user_id = params.get("userId")
        business_id = params.get("businessId")
        if (not user_id or not business_id) and params.get("threadId"):
            ctx = await OrderDomainService.get_thread_session_context(params["threadId"])
            user_id = user_id or ctx["userId"]
            business_id = business_id or ctx["businessId"]

        effective_user_id = user_id or "anonymous_user"
        effective_biz_id = business_id or "ecommerce"
        full_address = f'{params["province"]}{params["city"]}{params["district"]}{params["detailAddress"]}'

        try:
            async with get_session() as session:
                if params.get("isDefault"):
                    await session.execute(
                        text(
                            "UPDATE user_addresses SET is_default = false WHERE user_id = :uid AND business_id = :bid"
                        ).bindparams(uid=effective_user_id, bid=effective_biz_id)
                    )
                inserted = (
                    await session.execute(
                        text(
                            "INSERT INTO user_addresses ("
                            "business_id, user_id, receiver_name, receiver_phone, "
                            "province, city, district, detail_address, full_address, tag, is_default, created_at, updated_at"
                            ") VALUES (:bid, :uid, :rn, :rp, :prov, :city, :dist, :detail, :full, :tag, :is_def, NOW(), NOW()) "
                            'RETURNING id, full_address AS "fullAddress", is_default AS "isDefault"'
                        ).bindparams(
                            bid=effective_biz_id,
                            uid=effective_user_id,
                            rn=params["receiverName"],
                            rp=params["receiverPhone"],
                            prov=params["province"],
                            city=params["city"],
                            dist=params["district"],
                            detail=params["detailAddress"],
                            full=full_address,
                            tag=params.get("tag") or "home",
                            is_def=bool(params.get("isDefault")),
                        )
                    )
                ).mappings().first()
                await session.commit()

                return {
                    "success": True,
                    "message": "收货地址保存成功",
                    "addressId": str(inserted["id"]) if inserted else f"addr_{int(time.time() * 1000)}",
                    "fullAddress": full_address,
                    "tag": params.get("tag") or "home",
                    "isDefault": bool(params.get("isDefault")),
                }
        except Exception as err:  # noqa: BLE001
            print(f"[MallDomainService.saveUserAddress] Database insert fallback: {err}")
            return {
                "success": True,
                "message": "收货地址已登记",
                "addressId": f"addr_mock_{int(time.time() * 1000)}",
                "fullAddress": full_address,
                "tag": params.get("tag") or "home",
                "isDefault": bool(params.get("isDefault")),
            }

    @staticmethod
    async def query_product_skus(params: dict) -> dict:
        """2. 查询商品多规格 SKU 与物理库存。"""
        business_id = params.get("businessId")
        if not business_id and params.get("threadId"):
            ctx = await OrderDomainService.get_thread_session_context(params["threadId"])
            if ctx["businessId"]:
                business_id = ctx["businessId"]

        try:
            conditions: list[str] = []
            query_params: dict = {}
            if params.get("productId"):
                conditions.append("s.product_id = :pid")
                query_params["pid"] = params["productId"]
            if params.get("skuCode"):
                conditions.append("s.sku_code = :sku")
                query_params["sku"] = params["skuCode"]
            if business_id and business_id != "ecommerce":
                conditions.append("s.business_id = :bid")
                query_params["bid"] = business_id
            if params.get("inStockOnly"):
                conditions.append("s.stock > 0")
            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            async with get_session() as session:
                rows = (
                    (
                        await session.execute(
                            text(
                                'SELECT s.id, s.product_id AS "productId", p.name AS "productName", '
                                's.sku_code AS "skuCode", s.spec_attributes AS "specAttributes", s.price, '
                                's.cost_price AS "costPrice", s.stock, s.image_url AS "imageUrl", s.status '
                                "FROM product_skus s LEFT JOIN products p ON s.product_id = p.id "
                                f"{where_clause} ORDER BY s.price ASC LIMIT 20"
                            ).bindparams(**query_params)
                        )
                    )
                    .mappings()
                    .all()
                )

                rows = [dict(r) for r in rows]
                if params.get("color") or params.get("size"):
                    def _matches(r: dict) -> bool:
                        spec = r.get("specAttributes") or {}
                        match = True
                        if params.get("color") and spec.get("color"):
                            match = match and (
                                params["color"] in spec["color"] or spec["color"] in params["color"]
                            )
                        if params.get("size") and spec.get("size"):
                            match = match and (
                                params["size"] in str(spec["size"]) or str(spec["size"]) in params["size"]
                            )
                        return match

                    rows = [r for r in rows if _matches(r)]

                if rows:
                    return {
                        "total": len(rows),
                        "productId": params.get("productId"),
                        "skus": [
                            {
                                "skuId": str(r["id"]),
                                "skuCode": r["skuCode"],
                                "productName": r.get("productName"),
                                "specs": r.get("specAttributes"),
                                "price": f"¥{float(r['price']):.2f}",
                                "stock": r["stock"],
                                "inStock": (r["stock"] or 0) > 0,
                                "status": r["status"],
                                "imageUrl": r.get("imageUrl"),
                            }
                            for r in rows
                        ],
                    }
        except Exception as err:  # noqa: BLE001
            print(f"[MallDomainService.queryProductSkus] Error querying SKUs: {err}")

        mock_skus = [
            {
                "skuId": "sku_nike_aj1_blk_42",
                "skuCode": "NK-AJ1-001-42",
                "productName": "Air Jordan 1 Retro High OG",
                "specs": {"color": "黑白芝加哥", "size": "42", "version": "高帮经典款"},
                "price": "¥1299.00",
                "stock": 15,
                "inStock": True,
                "status": "active",
                "imageUrl": "/products/aj1_black.png",
            },
            {
                "skuId": "sku_nike_aj1_blk_425",
                "skuCode": "NK-AJ1-001-425",
                "productName": "Air Jordan 1 Retro High OG",
                "specs": {"color": "黑白芝加哥", "size": "42.5", "version": "高帮经典款"},
                "price": "¥1299.00",
                "stock": 8,
                "inStock": True,
                "status": "active",
                "imageUrl": "/products/aj1_black.png",
            },
            {
                "skuId": "sku_nike_aj1_red_43",
                "skuCode": "NK-AJ1-002-43",
                "productName": "Air Jordan 1 Retro High OG",
                "specs": {"color": "公牛红", "size": "43", "version": "高帮经典款"},
                "price": "¥1399.00",
                "stock": 0,
                "inStock": False,
                "status": "out_of_stock",
                "imageUrl": "/products/aj1_red.png",
            },
        ]
        return {"total": len(mock_skus), "productId": params.get("productId") or "prod_nike_air_jordan_1", "skus": mock_skus}

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
                        await session.execute(
                            text(
                                'SELECT id, business_id AS "businessId", order_id AS "orderId", carrier, '
                                'carrier_code AS "carrierCode", tracking_number AS "trackingNumber", status, '
                                'current_location AS "currentLocation", courier_name AS "courierName", '
                                'courier_phone AS "courierPhone", estimated_delivery AS "estimatedDelivery" '
                                "FROM logistics_packages WHERE tracking_number = :tn LIMIT 1"
                            ).bindparams(tn=tracking_number)
                        )
                    ).mappings().first()
                elif order_id:
                    pkg_row = (
                        await session.execute(
                            text(
                                'SELECT id, business_id AS "businessId", order_id AS "orderId", carrier, '
                                'carrier_code AS "carrierCode", tracking_number AS "trackingNumber", status, '
                                'current_location AS "currentLocation", courier_name AS "courierName", '
                                'courier_phone AS "courierPhone", estimated_delivery AS "estimatedDelivery" '
                                "FROM logistics_packages WHERE order_id = :oid ORDER BY created_at DESC LIMIT 1"
                            ).bindparams(oid=order_id)
                        )
                    ).mappings().first()

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
        except Exception as err:  # noqa: BLE001
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
    async def query_product_reviews(params: dict) -> dict:
        """4. 查询商品评价与口碑画像。"""
        limit = params.get("limit") or 5
        try:
            conditions: list[str] = []
            query_params: dict = {}
            if params.get("productId"):
                conditions.append("r.product_id = :pid")
                query_params["pid"] = params["productId"]
            if params.get("fitFeedback"):
                conditions.append("r.fit_feedback = :fit")
                query_params["fit"] = params["fitFeedback"]
            if params.get("sentiment"):
                conditions.append("r.sentiment = :sent")
                query_params["sent"] = params["sentiment"]
            if params.get("ratingMin"):
                conditions.append("r.rating >= :rmin")
                query_params["rmin"] = params["ratingMin"]
            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            async with get_session() as session:
                rows = (
                    (
                        await session.execute(
                            text(
                                'SELECT r.id, r.product_id AS "productId", r.user_name AS "userName", r.rating, '
                                'r.content, r.fit_feedback AS "fitFeedback", r.sentiment, '
                                'r.merchant_reply AS "merchantReply", r.created_at AS "createdAt" '
                                f"FROM product_reviews r {where_clause} "
                                "ORDER BY r.rating DESC, r.created_at DESC "
                                f"LIMIT {int(limit)}"
                            ).bindparams(**query_params)
                        )
                    )
                    .mappings()
                    .all()
                )

                if rows:
                    avg_rating = sum(int(r["rating"] or 0) for r in rows) / len(rows)
                    fit_labels = {
                        "true_to_size": "尺码偏好: 正码合脚",
                        "runs_small": "尺码偏好: 偏小半码，建议拍大",
                    }
                    return {
                        "totalReviews": len(rows),
                        "avgRating": f"{avg_rating:.1f} / 5.0",
                        "sentimentSummary": {
                            "positiveRate": "92%",
                            "fitConsensus": "86% 用户反馈尺码标准（正码），鞋楦包裹性适中",
                        },
                        "reviews": [
                            {
                                "userName": r.get("userName") or "匿名用户",
                                "rating": f"{r['rating']} ⭐",
                                "content": r["content"],
                                "fitFeedback": fit_labels.get(r.get("fitFeedback"), "尺码偏好: 偏大"),
                                "merchantReply": r.get("merchantReply"),
                            }
                            for r in rows
                        ],
                    }
        except Exception as err:  # noqa: BLE001
            print(f"[MallDomainService.queryProductReviews] Database error: {err}")

        return {
            "totalReviews": 128,
            "avgRating": "4.8 / 5.0",
            "sentimentSummary": {
                "positiveRate": "94.5%",
                "fitConsensus": "88% 用户反馈按日常运动鞋正码选购即可，前掌包裹感舒适",
            },
            "reviews": [
                {
                    "userName": "晨***跑",
                    "rating": "5 ⭐",
                    "content": "脚感很棒，包裹性强，日常穿42码这款拍42码刚刚好，非常透气！",
                    "fitFeedback": "尺码偏好: 正码合脚",
                    "merchantReply": "感谢您的认可！祝您跑出好成绩！",
                },
                {
                    "userName": "k***8",
                    "rating": "5 ⭐",
                    "content": "颜值在线，做工走线工整，顺丰第二天就到了，五星好评。",
                    "fitFeedback": "尺码偏好: 正码合脚",
                    "merchantReply": None,
                },
                {
                    "userName": "路***人",
                    "rating": "4 ⭐",
                    "content": "鞋底略硬需要踩开两三天，脚背偏高的朋友建议选大半码。",
                    "fitFeedback": "尺码偏好: 脚背高建议大半码",
                    "merchantReply": "收到反馈，高脚背鞋友可适当松开鞋带前两组穿孔哦~",
                },
            ],
        }

    @staticmethod
    async def apply_after_sale(params: dict) -> dict:
        """5. 提交售后退款/退货退款/换货工单。"""
        thread_id = params.get("threadId")
        effective_user_id = ""
        effective_biz_id = "ecommerce"
        if thread_id:
            ctx = await OrderDomainService.get_thread_session_context(thread_id)
            effective_user_id = ctx["userId"]
            effective_biz_id = ctx["businessId"]

        order = await OrderDomainService.find_order_by_id(params["orderId"], effective_user_id, effective_biz_id)
        if not order:
            return {"error": f"⚠️ 售后申请失败：订单 {params['orderId']} 不属于您名下或不存在。"}

        ticket_id = f"AS-{int(time.time()):X}-{random.randint(100, 999)}"
        refund_amount = params.get("refundAmount") or float(order.get("totalAmount") or 0) or 100.0

        try:
            async with get_session() as session:
                await session.execute(
                    text(
                        "INSERT INTO after_sale_tickets ("
                        "id, business_id, order_id, order_item_id, user_id, "
                        "type, reason, reason_description, refund_amount, status, created_at, updated_at"
                        ") VALUES ("
                        ":tid, :bid, :oid, :oiid, :uid, :type, :reason, :rdesc, :amount, 'pending_review', NOW(), NOW())"
                    ).bindparams(
                        tid=ticket_id,
                        bid=effective_biz_id,
                        oid=params["orderId"],
                        oiid=params.get("orderItemId"),
                        uid=effective_user_id or order.get("userId") or "user_001",
                        type=params["type"],
                        reason=params["reason"],
                        rdesc=params.get("reasonDescription") or "用户通过智能客服提交售后申请",
                        amount=refund_amount,
                    )
                )
                await session.execute(
                    text(
                        "INSERT INTO after_sale_logs (ticket_id, action, operator, note, created_at) "
                        "VALUES (:tid, 'created', 'agent_autopilot', :note, NOW())"
                    ).bindparams(tid=ticket_id, note=f"用户申请【{params['type']}】，原因: {params['reason']}")
                )
                await session.commit()
        except Exception as err:  # noqa: BLE001
            print(f"[MallDomainService.applyAfterSale] Database insert failed, returning fallback ticket: {err}")

        await tool_cache.delete(f"cache:order_status:{params['orderId']}")

        return {
            "success": True,
            "ticketId": ticket_id,
            "orderId": params["orderId"],
            "type": params["type"],
            "reason": params["reason"],
            "refundAmount": f"¥{refund_amount:.2f}",
            "status": "pending_review",
            "instruction": (
                "仅退款申请已提交，系统预计将在 1-2 小时内原路返还款项。"
                if params["type"] == "refund_only"
                else "退货退款申请已受理，请等待商家审核通过后获取回寄地址与退货运单单号。"
            ),
        }

    MOCK_PRODUCTS = [
        {
            "id": "prod_nike_air_pegasus_41",
            "name": "Nike Air Zoom Pegasus 41 极速轻量透气跑鞋",
            "price": 899.0,
            "stock": 58,
            "description": "双重 Zoom Air 缓震气垫，工程网眼鞋面透气亲肤，全天候舒适缓震。",
            "category": "running_shoes",
            "specs": {"适用人群": "男女同款", "场景": "日常慢跑/马拉松训练", "材质": "透气织物+气垫"},
            "imageUrl": "/products/pegasus_41.png",
        },
        {
            "id": "prod_nike_invincible_3",
            "name": "Nike ZoomX Invincible Run 3 旗舰缓震跑鞋",
            "price": 1299.0,
            "stock": 22,
            "description": "厚底 ZoomX 超强回弹泡棉，高阶护膝缓震，长距离奔跑首选。",
            "category": "running_shoes",
            "specs": {"适用人群": "男女同款", "场景": "长距离慢跑/大体重护膝", "材质": "Flyknit 编织+ZoomX"},
            "imageUrl": "/products/invincible_3.png",
        },
        {
            "id": "prod_nike_windrunner_jacket",
            "name": "Nike Windrunner 连帽运动风行者夹克外套",
            "price": 599.0,
            "stock": 45,
            "description": "经典 V 字拼接设计，防风轻防泼水面料，内里网眼透气舒适。",
            "category": "apparel",
            "specs": {"适用人群": "男女同款", "版型": "标准休闲宽松", "面料": "聚酯纤维防风层"},
            "imageUrl": "/products/windrunner.png",
        },
    ]

    @staticmethod
    async def search_products(params: dict) -> dict:
        """6. 商品检索与导购选品。"""
        query = params.get("query")
        category = params.get("category")
        max_price = params.get("maxPrice")
        limit = params.get("limit") or 4
        effective_biz_id = params.get("businessId") or "ecommerce"

        if params.get("threadId") and effective_biz_id == "ecommerce":
            ctx = await OrderDomainService.get_thread_session_context(params["threadId"])
            if ctx["businessId"]:
                effective_biz_id = ctx["businessId"]

        try:
            conditions: list[str] = []
            query_params: dict = {}
            if effective_biz_id and effective_biz_id != "ecommerce":
                conditions.append("business_id = :bid")
                query_params["bid"] = effective_biz_id
            if query:
                conditions.append("(name ILIKE :q OR description ILIKE :q)")
                query_params["q"] = f"%{query}%"
            if category:
                conditions.append("category = :cat")
                query_params["cat"] = category
            if max_price:
                conditions.append("price <= :pmax")
                query_params["pmax"] = max_price
            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            async with get_session() as session:
                rows = (
                    (
                        await session.execute(
                            text(
                                'SELECT id, business_id AS "businessId", name, price, stock, description, category '
                                f"FROM products {where_clause} ORDER BY price ASC LIMIT :lim"
                            ).bindparams(**query_params, lim=limit)
                        )
                    )
                    .mappings()
                    .all()
                )
                if rows:
                    return {
                        "total": len(rows),
                        "products": [
                            {
                                "id": str(r["id"]),
                                "name": r["name"],
                                "price": float(r["price"]),
                                "stock": int(r["stock"]),
                                "description": r["description"],
                                "category": r["category"],
                                "specs": {"品类": r["category"] or "精选"},
                                "imageUrl": "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=400",
                            }
                            for r in rows
                        ],
                    }
        except Exception as err:  # noqa: BLE001
            print(f"[MallDomainService.searchProducts] Database query fallback: {err}")

        def _matches(p: dict) -> bool:
            if query and query not in p["name"] and query not in p["description"] and query not in p["category"]:
                return False
            if max_price and p["price"] > max_price:
                return False
            return True

        filtered = [p for p in MallDomainService.MOCK_PRODUCTS if _matches(p)]
        result_list = filtered or MallDomainService.MOCK_PRODUCTS
        return {"total": len(result_list), "products": result_list[:limit]}

    @staticmethod
    async def compare_products(params: dict) -> dict:
        """7. 商品多维参数对比。"""
        product_ids = params["productIds"]
        search_res = await MallDomainService.search_products({**params, "limit": 10})
        all_products = list(search_res.get("products") or []) + [
            {
                "id": "prod_nike_air_pegasus_41",
                "name": "Nike Pegasus 41",
                "price": 899.0,
                "specs": {"缓震度": "中等均衡", "重量": "260g (42码)", "推荐场景": "5-10km 日常慢跑", "性价比": "高"},
            },
            {
                "id": "prod_nike_invincible_3",
                "name": "Nike Invincible 3",
                "price": 1299.0,
                "specs": {"缓震度": "超强顶级", "重量": "298g (42码)", "推荐场景": "半马/大体重缓震护膝", "性价比": "旗舰体验"},
            },
        ]

        matched = [
            p for p in all_products if p.get("id") in product_ids or any(pid in (p.get("name") or "") for pid in product_ids)
        ]
        return {
            "success": True,
            "comparedCount": len(matched),
            "products": matched,
            "summary": (
                f"已为您对比 {len(matched)} 款商品的核心参数：Pegasus 41 性价比高、更轻巧；"
                "Invincible 3 缓震回弹更澎湃、适合长时间运动。"
            ),
        }

    @staticmethod
    async def add_to_cart(params: dict) -> dict:
        """8. 购物车添加与管理。"""
        sku_id = params["skuId"]
        quantity = params.get("quantity") or 1
        title = params.get("title") or "精选商品"
        price = params.get("price") if params.get("price") is not None else 899.0
        cart_key = params.get("userId") or params.get("threadId") or "default_user"

        items = MallDomainService._cart_storage.get(cart_key, [])
        existing = next((i for i in items if i["skuId"] == sku_id), None)
        if existing:
            existing["quantity"] += quantity
        else:
            items.append({"skuId": sku_id, "quantity": quantity, "title": title, "price": price, "spec": params.get("spec")})
        MallDomainService._cart_storage[cart_key] = items

        total_amount = sum(i["price"] * i["quantity"] for i in items)
        return {
            "success": True,
            "message": f"已成功将 {quantity} 件商品加入购物车！",
            "lastModifiedItemId": sku_id,
            "cart": {
                "itemCount": len(items),
                "totalQuantity": sum(i["quantity"] for i in items),
                "totalAmount": total_amount,
                "items": items,
            },
        }

    @staticmethod
    async def get_cart_summary(params: dict) -> dict:
        cart_key = params.get("userId") or params.get("threadId") or "default_user"
        items = MallDomainService._cart_storage.get(cart_key) or [
            {
                "skuId": "sku_nike_aj1_blk_425",
                "title": "Air Jordan 1 Retro High OG (42.5码 / 黑白芝加哥)",
                "price": 1299.0,
                "quantity": 1,
                "spec": "颜色: 黑白芝加哥 | 尺码: 42.5",
            }
        ]
        total_amount = sum(i["price"] * i["quantity"] for i in items)
        estimated_discount = 100 if total_amount >= 1000 else 0
        return {
            "success": True,
            "cart": {
                "itemCount": len(items),
                "totalQuantity": sum(i["quantity"] for i in items),
                "totalAmount": total_amount,
                "discount": estimated_discount,
                "payableAmount": total_amount - estimated_discount,
                "items": items,
            },
        }

    @staticmethod
    async def update_cart_item(params: dict) -> dict:
        sku_id = params["skuId"]
        quantity = params["quantity"]
        cart_key = params.get("userId") or params.get("threadId") or "default_user"
        items = MallDomainService._cart_storage.get(cart_key, [])

        if quantity <= 0:
            items = [i for i in items if i["skuId"] != sku_id]
        else:
            target = next((i for i in items if i["skuId"] == sku_id), None)
            if target:
                target["quantity"] = quantity

        MallDomainService._cart_storage[cart_key] = items
        total_amount = sum(i["price"] * i["quantity"] for i in items)
        return {
            "success": True,
            "message": "商品已从购物车移除" if quantity <= 0 else f"商品数量已更新为 {quantity} 件",
            "cart": {"itemCount": len(items), "totalAmount": total_amount, "items": items},
        }
