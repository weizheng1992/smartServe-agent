"""商城领域服务 — 镜像 tools/src/mallDomainService.ts(984 LOC,全量移植,含种子兜底)。

商品检索例外(2026-09-11 L3/L2):search_products 不再吃 TS 基线的 MOCK 种子兜底
—— 主目录换 agent_merchant 商户真货架,检索链 = 商户货架(词元 ILIKE → 语义
余弦补位)→ engine 本地 products 表 → 诚实空;compare_products 同步只吃真实
检索结果,假货不混入、话术不点名。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
import re
import time

from sqlalchemy import text

from ..config import settings
from ..db import get_session
from ..llm.chat import get_chat_model, get_embedding_model
from . import order_domain
from .cache import tool_cache
from .order_domain import OrderDomainService


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度(与 rag/contextual_rag.py 同源实现,零范数防御)。"""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


class MallDomainService:
    # 导购 wrapper 词表:剥掉无商品语义的导购措辞,剩余才是检索词元。与
    # slot_extractor SHOPPING_GUIDE 规则、ShoppingGuideSkill._FALLBACK_RE
    # 两处意图词表同族维护(2026-09-07 同源补词);含商品语义的词条
    # (选鞋/选衣服/跑步鞋/卫衣/夹克)严禁入列 —— 剥掉即毁掉检索词。
    _GUIDE_WRAPPER_TERMS = (
        "有什么好看",
        "推荐几款",
        "推荐几件",
        "推荐一款",
        "介绍一下",
        "什么牌子",
        "买什么",
        "有没有",
        "挑一款",
        "选一款",
        "找一找",
        "哪款好",
        "看商品",
        "好看",
        "款式",
        "热门",
        "爆款",
        "热销",
        "热卖",
        "畅销",
        "上新",
        "新品",
        "推荐",
        "导购",
        "最近",
        "商品",
        "东西",
        "我想",
        "帮我",
        "买",
        "请",
        # 2026-09-11 L1 补:评价/热度修饰词族。注意「的」是分隔符但「好/高」不是——
        # 「比较好的帐篷」剥「比较」会残留『好』词元(OR 匹配拉入无关商品),故修饰
        # 词族一律收短语形(比较好/人气高/性价比高/最好卖…);长序替换内建,
        # 「性价比高」先于「性价比」消费。
        "有什么",
        "一下",
        "我要",
        "卖得好",
        "卖的好",
        "比较好",
        "比较",
        "不错",
        "性价比高",
        "性价比",
        "值得",
        "人气高",
        "人气",
        "受欢迎",
        "最受欢迎",
        "口碑",
        "评价好",
        "评价",
        "最好",
        "最好卖",
    )

    # 口语词元 → 货架词素别名(2026-09-12,_expand_stem_aliases 消费):口语统称
    # 「裤子/鞋子」与货架命名「工装裤/慢跑裤/老爹鞋」差一个名词后缀,ILIKE 子串
    # 永远擦肩(症状:「卖的好的裤子」货架明明有裤子却诚实空——语义档余弦
    # 0.51-0.53 又卡在 0.55 阈值下,词干路径才是确定性修法)。刻意显式小词表
    # 而非通用剥「子」规则 —— 电子/种子类词剥后语义漂移,别名只在核实过货架
    # 词素后收录。
    _TERM_STEM_ALIASES: dict[str, tuple[str, ...]] = {
        "裤子": ("裤",),
        "鞋子": ("鞋",),
    }
    # 词元清洗(ADR 检索链 L1):数量前缀逐块剥、「衬衫都」尾缀语气字仅剥
    # 长块(len>2,「成都」两字不动);⚠️ 分隔符连词只收「和/与」,「跟」
    # 严禁入列(高跟鞋/跟妆会被劈开)。
    _QUANTITY_PREFIX_RE = re.compile(r"^(?:几[件条双款个]|[两三四五六七八九十]+[件条双款个]|\d+[件条双款个])")
    _TRAILING_PARTICLE_RE = re.compile(r"(?:都要|都|吧|呢|啊|呀)$")

    # 购物车存储(2026-09-08 重构):_cart_storage 降级为进程一级读缓存,真实
    # 状态写穿透 Redis(agent:cart:{userId})。此前纯进程内存,网关重启即失忆,
    # 与浏览器 localStorage 购物车分裂 —— 引擎对已遗忘的车重新播报「已成功
    # 加入」,前端按 skuCode 合并发现条目都在,quantity 原值覆盖原值,计数
    # 纹丝不动(用户症状:「说成功了但没加入」)。Redis 不可用时降级纯内存。
    _cart_storage: dict[str, list[dict]] = {}
    _CART_REDIS_PREFIX = "agent:cart:"

    # L2 语义召回缓存:spu_code → (嵌入文本 sha256 前 16 位, 向量)。进程内
    # 缓存足够 —— 重嵌只是几毫秒级 bge 推理,跨进程共享(pgvector)是目录
    # 到千级 SPU 后的事,现在引入是过度设计。
    _spu_embedding_cache: dict[str, tuple[str, list[float]]] = {}

    @staticmethod
    async def _load_cart(cart_key: str) -> list[dict] | None:
        """读购物车:进程缓存命中优先,否则回源 Redis。None 表示两处皆无。"""
        if cart_key in MallDomainService._cart_storage:
            return MallDomainService._cart_storage[cart_key]
        try:
            from ..event_bus import get_client

            raw = await (await get_client()).get(f"{MallDomainService._CART_REDIS_PREFIX}{cart_key}")
            if raw is None:
                return None
            items = json.loads(raw)
            MallDomainService._cart_storage[cart_key] = items
            return items
        except Exception as err:
            print(f"[MallDomain] Cart Redis load degraded to memory view: {err}")
            return None

    @staticmethod
    async def _save_cart(cart_key: str, items: list[dict]) -> None:
        """写购物车:进程缓存与 Redis 同步写穿透;Redis 故障静默降级纯内存。"""
        MallDomainService._cart_storage[cart_key] = items
        try:
            from ..event_bus import get_client

            await (await get_client()).set(
                f"{MallDomainService._CART_REDIS_PREFIX}{cart_key}", json.dumps(items, ensure_ascii=False)
            )
        except Exception as err:
            print(f"[MallDomain] Cart Redis persist degraded to memory only: {err}")

    @staticmethod
    async def get_user_addresses(
        user_id: str | None = None, business_id: str | None = None, thread_id: str | None = None
    ) -> dict:
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
                                or f"{r['province']}{r['city']}{r['district']}{r['detailAddress']}",
                                "tag": r["tag"] or "home",
                                "isDefault": bool(r["isDefault"]),
                            }
                            for r in rows
                        ],
                    }
        except Exception as err:
            print(f"[MallDomainService.getUserAddresses] Database query error: {err}")

        # 终点诚实空(2026-09-12):旧「张先生/中关村」高保真假地址兜底退役 ——
        # 查无/库不可达是合法真实态,严禁虚构地址顶替(real-data-only/01)。
        return {"total": 0, "userId": effective_user_id or "current_user", "addresses": []}

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
        full_address = f"{params['province']}{params['city']}{params['district']}{params['detailAddress']}"

        try:
            async with get_session() as session:
                if params.get("isDefault"):
                    await session.execute(
                        text(
                            "UPDATE user_addresses SET is_default = false WHERE user_id = :uid AND business_id = :bid"
                        ).bindparams(uid=effective_user_id, bid=effective_biz_id)
                    )
                inserted = (
                    (
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
                    )
                    .mappings()
                    .first()
                )
                await session.commit()

                return {
                    "success": True,
                    "message": "收货地址保存成功",
                    "addressId": str(inserted["id"]) if inserted else f"addr_{int(time.time() * 1000)}",
                    "fullAddress": full_address,
                    "tag": params.get("tag") or "home",
                    "isDefault": bool(params.get("isDefault")),
                }
        except Exception as err:
            # 写库失败如实失败(2026-09-12):旧兜底假成功 + addr_mock_ 假 ID ——
            # 用户以为保存成功实际未落库,比假数据更糟(real-data-only/01)。
            print(f"[MallDomainService.saveUserAddress] Database insert failed: {err}")
            return {
                "success": False,
                "message": "收货地址保存失败，请稍后重试或联系人工客服。",
                "addressId": None,
                "fullAddress": full_address,
                "tag": params.get("tag") or "home",
                "isDefault": bool(params.get("isDefault")),
            }

    @staticmethod
    async def query_product_skus(params: dict) -> dict:
        """2. 查询商品多规格 SKU 与物理库存。

        降级链(2026-09-12,real-data-only/01):商户真货架(merchant_skus×
        merchant_spus)优先 → engine 本地 product_skus → 诚实空。商户库可达
        但查无必须诚实空,严禁假 SKU 目录顶替(旧 AJ1 三件套已拆)。
        """
        business_id = params.get("businessId")
        if not business_id and params.get("threadId"):
            ctx = await OrderDomainService.get_thread_session_context(params["threadId"])
            if ctx["businessId"]:
                business_id = ctx["businessId"]

        product_id = params.get("productId")
        sku_code = params.get("skuCode")

        # 1) 商户真货架:spu_code 精确命中或 title 子串解析(导购候选名直达规格)
        if product_id or sku_code:
            try:
                async with order_domain._merchant_reader_engine().connect() as mconn:
                    rows = (
                        (
                            await mconn.execute(
                                text(
                                    'SELECT sk.id, sk.sku_code AS "skuCode", sp.title AS "productName", '
                                    "sk.spec_attributes AS \"specAttributes\", sk.price, sk.stock, "
                                    'COALESCE(sk.image_url, sp.main_image) AS "imageUrl", sp.status '
                                    "FROM merchant_skus sk JOIN merchant_spus sp ON sk.spu_id = sp.id "
                                    "WHERE sp.status = 'ON_SALE' AND ("
                                    "(CAST(:pid AS TEXT) IS NOT NULL AND (sp.spu_code = :pid OR sp.title ILIKE CAST(:ptitle AS TEXT))) "
                                    "OR (CAST(:sku AS TEXT) IS NOT NULL AND sk.sku_code = :sku)) "
                                    "AND (CAST(:in_stock_only AS INT) = 0 OR sk.stock > 0) "
                                    "ORDER BY sk.price ASC LIMIT 20"
                                ).bindparams(
                                    pid=product_id,
                                    ptitle=f"%{product_id}%" if product_id else None,
                                    sku=sku_code,
                                    in_stock_only=1 if params.get("inStockOnly") else 0,
                                )
                            )
                        )
                        .mappings()
                        .all()
                    )
                if rows:
                    return MallDomainService._sku_rows_to_payload([dict(r) for r in rows], product_id, params)
                # 商户库可达但查无 → 诚实空,不落本地演示目录
                return {"total": 0, "productId": product_id, "skus": []}
            except Exception as err:
                print(f"[MallDomainService.queryProductSkus] Merchant shelf unavailable, degrading: {err}")

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

                if rows:
                    return MallDomainService._sku_rows_to_payload(rows, params.get("productId"), params)
        except Exception as err:
            print(f"[MallDomainService.queryProductSkus] Error querying SKUs: {err}")

        # 终点诚实空(2026-09-12):旧 AJ1 假 SKU 目录整体退役 —— 查无/库不可达
        # 是合法真实态,严禁硬编码目录顶替(real-data-only/01)。
        return {"total": 0, "productId": params.get("productId"), "skus": []}

    @staticmethod
    def _sku_rows_to_payload(rows: list[dict], product_id: str | None, params: dict) -> dict:
        """SKU 行 → 出参载荷(商户/本地两路共用,契约键零漂移)。

        skuId 取值:商户路径为 sku_code(与导购候选 id=spu_code、网关加购
        同一业务标识);本地回退路径为行 UUID(历史形态)。键名两路一致。"""
        if params.get("color") or params.get("size"):

            def _matches(r: dict) -> bool:
                spec = r.get("specAttributes") or {}
                match = True
                if params.get("color") and spec.get("color"):
                    match = match and (params["color"] in spec["color"] or spec["color"] in params["color"])
                if params.get("size") and spec.get("size"):
                    match = match and (params["size"] in str(spec["size"]) or str(spec["size"]) in params["size"])
                return match

            rows = [r for r in rows if _matches(r)]
        return {
            "total": len(rows),
            "productId": product_id,
            "skus": [
                {
                    "skuId": str(r.get("skuCode") or r["id"]),
                    "skuCode": r["skuCode"],
                    "productName": r.get("productName"),
                    "specs": r.get("specAttributes"),
                    "price": f"¥{float(r['price']):.2f}",
                    "stock": r["stock"],
                    "inStock": (r["stock"] or 0) > 0,
                    "status": r.get("status"),
                    "imageUrl": r.get("imageUrl"),
                }
                for r in rows
            ],
        }

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
        except Exception as err:
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

        order = await OrderDomainService.find_order_by_id(
            params["orderId"], effective_user_id, effective_biz_id
        )
        if not order:
            return {"error": f"⚠️ 售后申请失败：订单 {params['orderId']} 不属于您名下或不存在。"}

        ticket_id = f"AS-{int(time.time()):X}-{random.randint(100, 999)}"
        refund_amount = params.get("refundAmount") or float(order.get("totalAmount") or 0) or 100.0
        # ADR-0002 Q1/Q2:本轮上传的瑕疵凭证落票(上限与引擎视觉上限一致);
        # 不传 = 空数组,旧行为零破坏。executor 层程序化注入,严禁指望 LLM 抄 URL。
        from ..vision.analyzer import MAX_IMAGES_PER_MESSAGE

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
                        oid=params["orderId"],
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

        await tool_cache.delete(f"cache:order_status:{params['orderId']}")

        return {
            "success": True,
            "ticketId": ticket_id,
            "orderId": params["orderId"],
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

    @staticmethod
    def _extract_query_terms(query: str | None) -> list[str]:
        """原始 NL 输入 → 检索词元:剥导购 wrapper 词,按分隔符切分。

        整句子串匹配对 NL 措辞永远空手而归(2026-09-11「推荐背包热销」给了
        跑鞋);剥词后按词元 OR 匹配。剩余为空 = 纯浏览形输入,无关键词,
        由调用方走浏览语义(不加 query 过滤)。替换按词长降序,防「推荐」
        先吃掉「推荐几款」留下裸「几款」。
        """
        if not query:
            return []
        rest = query
        for term in sorted(MallDomainService._GUIDE_WRAPPER_TERMS, key=len, reverse=True):
            rest = rest.replace(term, " ")
        chunks = re.split(r"[\s,，、。.!！?？:；;的和与]+", rest)
        cleaned = []
        for chunk in chunks:
            chunk = MallDomainService._QUANTITY_PREFIX_RE.sub("", chunk.strip()).strip()
            # 尾缀语气字仅剥长块(len>2):「衬衫都」→「衬衫」;「成都」两字不动
            if len(chunk) > 2:
                chunk = MallDomainService._TRAILING_PARTICLE_RE.sub("", chunk).strip()
            if chunk and chunk not in cleaned:
                cleaned.append(chunk)
        return cleaned

    @staticmethod
    def _expand_stem_aliases(terms: list[str]) -> list[str]:
        """词元 → 词元 + 货架词素别名(扩充 ILIKE OR 匹配面,保持原词元在前)。

        词干是子串超集(「%裤%」⊇「%裤子%」),追加不改原词元语义;别名见
        _TERM_STEM_ALIASES 注释。空表进空表出 —— 浏览形判定不受影响。"""
        expanded: list[str] = []
        for term in terms:
            if term not in expanded:
                expanded.append(term)
            for stem in MallDomainService._TERM_STEM_ALIASES.get(term, ()):
                if stem not in expanded:
                    expanded.append(stem)
        return expanded

    @staticmethod
    async def _fetch_merchant_catalog(
        terms: list[str] | None, category: str | None, max_price, limit: int
    ) -> list[dict] | None:
        """商户真货架 SQL 检索层(agent_merchant.merchant_spus/skus)。

        None=库不可达(调用方降级 engine 本地表);[]=可达查无(诚实空,
        严禁跨目录补货)。terms 非空时词元 OR ILIKE 四列(title/subtitle/
        category/description,对齐网关搜索先例 —— category 列必须参与:SPU
        title 是「双肩包」不含「背包」,品类列「背包收纳」才是命中面);terms
        为 None 是 L2 语义召回的候选池形态(硬过滤全量,无词元条件)。展示价=
        MIN(sku.price)、库存=SUM(sku.stock),与网关 _spu_to_product 同语义;
        排序 min_price ASC 与 engine 分支 price ASC 契约一致。热销排序不做:
        merchant 库无销量列(全仓亦无 sales_volume),无数据源 —— 已文档化
        限制,不合成假热度。无 SKU 的 SPU 展示价 NULL,经 HAVING 排除
        (不可售,且 float(None) 会炸)。
        """
        conditions = ["s.status = 'ON_SALE'"]
        params: dict = {}
        if terms:
            like_clauses = []
            for idx, term in enumerate(terms):
                key = f"q{idx}"
                params[key] = f"%{term}%"
                like_clauses.append(
                    f"(s.title ILIKE :{key} OR s.subtitle ILIKE :{key} "
                    f"OR s.category ILIKE :{key} OR s.description ILIKE :{key})"
                )
            conditions.append("(" + " OR ".join(like_clauses) + ")")
        if category:
            conditions.append("s.category = :cat")
            params["cat"] = category
        having_clauses = ["MIN(k.price) IS NOT NULL"]
        if max_price:
            having_clauses.append("MIN(k.price) <= :pmax")
            params["pmax"] = max_price
        params["lim"] = limit
        try:
            # 运行时经 order_domain 模块属性取 reader,严禁 from-import 导入期
            # 绑定:测试以整体替换 order_domain._merchant_reader_engine 的方式
            # 注入密封容器引擎,绑定会让 patch 失明。
            async with order_domain._merchant_reader_engine().connect() as conn:
                rows = (
                    (
                        await conn.execute(
                            text(
                                "SELECT s.spu_code, s.title, s.subtitle, s.description, s.category, "
                                "s.main_image, s.specs, "
                                "MIN(k.price) AS min_price, COALESCE(SUM(k.stock), 0) AS total_stock "
                                "FROM merchant_spus s LEFT JOIN merchant_skus k ON k.spu_id = s.id "
                                f"WHERE {' AND '.join(conditions)} "
                                "GROUP BY s.id "
                                f"HAVING {' AND '.join(having_clauses)} "
                                "ORDER BY min_price ASC LIMIT :lim"
                            ).bindparams(**params)
                        )
                    )
                    .mappings()
                    .all()
                )
        except Exception as err:
            print(f"[MallDomain] 商户真货架库不可达,商品检索降级 engine 本地表: {err}")
            return None
        return [
            {
                "id": r["spu_code"],
                "name": r["title"],
                "price": float(r["min_price"]),
                "stock": int(r["total_stock"] or 0),
                # 卡片 💡 行吃卖点短句,长文案只作回落(唯一消费方是
                # ShoppingGuideSkill._format_candidate 的单行渲染)
                "description": r["subtitle"] or r["description"],
                "category": r["category"],
                "specs": r["specs"] if isinstance(r["specs"], dict) else {},
                "imageUrl": r["main_image"],
            }
            for r in rows
        ]

    @staticmethod
    async def _embed_texts(texts: list[str]) -> list[list[float]]:
        """批量文本嵌入(独立静态方法是为了给测试留桩点)。"""
        return await get_embedding_model().aembed_documents(texts)

    @staticmethod
    async def _embed_query(query: str) -> list[float]:
        """查询嵌入(独立静态方法是为了给测试留桩点)。"""
        return await get_embedding_model().aembed_query(query)

    @staticmethod
    async def _ensure_spu_embeddings(products: list[dict]) -> list[list[float]]:
        """候选 SPU 嵌入向量:进程内缓存按嵌入文本 sha256 失效(商户改标题/
        卖点,下轮查询自动重嵌,无需通知 engine)。miss 批量一次
        aembed_documents —— 本地 bge 经 _SerializedEmbeddings 进程级串行
        护栏(2026-09-05 双线程 SIGSEGV 事故,见 llm/chat.py)。"""
        texts = [f"{p['name']} {p['description'] or ''} {p['category'] or ''}" for p in products]
        vectors: list[list[float] | None] = []
        need_idx: list[int] = []
        for idx, embed_text in enumerate(texts):
            digest = hashlib.sha256(embed_text.encode("utf-8")).hexdigest()[:16]
            cached = MallDomainService._spu_embedding_cache.get(products[idx]["id"])
            if cached and cached[0] == digest:
                vectors.append(cached[1])
            else:
                vectors.append(None)
                need_idx.append(idx)
        if need_idx:
            embedded = await MallDomainService._embed_texts([texts[i] for i in need_idx])
            for idx, vector in zip(need_idx, embedded, strict=True):
                digest = hashlib.sha256(texts[idx].encode("utf-8")).hexdigest()[:16]
                MallDomainService._spu_embedding_cache[products[idx]["id"]] = (digest, list(vector))
                vectors[idx] = list(vector)
        assert all(v is not None for v in vectors), "补齐 miss 后不应残留 None"
        return vectors  # type: ignore[return-value]

    @staticmethod
    async def _semantic_recall_merchant_catalog(
        query: str, category: str | None, max_price, limit: int
    ) -> list[dict] | None:
        """L2 语义召回补位(2026-09-11):词元 ILIKE 查空时 bge 余弦 top-k。

        返回契约与 _fetch_merchant_catalog 一致(None=能力不可用,[]=无命中)。
        候选池吃满硬过滤(status/category/maxPrice)但不吃词元条件;命中按
        相似度 DESC 输出 —— 语义档的价值就是相关性排序(min_price ASC 只属
        词元/浏览路径)。嵌入异常降级 None → 调用方落诚实空,绝不阻断检索。
        """
        candidates = await MallDomainService._fetch_merchant_catalog(None, category, max_price, 200)
        if candidates is None or not candidates:
            return candidates
        try:
            query_vector = await MallDomainService._embed_query(query)
            candidate_vectors = await MallDomainService._ensure_spu_embeddings(candidates)
            scored: list[tuple[float, dict]] = []
            for product, vector in zip(candidates, candidate_vectors, strict=True):
                similarity = _cosine_similarity(query_vector, vector)
                if similarity >= settings.mall_semantic_min_similarity:
                    scored.append((similarity, product))
            scored.sort(key=lambda pair: pair[0], reverse=True)
            return [product for _, product in scored[:limit]]
        except Exception as err:
            print(f"[MallDomain] 语义召回嵌入不可用,降级诚实空: {err}")
            return None

    @staticmethod
    async def get_shelf_overview() -> list[dict]:
        """店内品类盘点(2026-09-12):在售 SPU 按品类聚合计数,供诚实空回复
        引导(「暂时没有背心,店里有 背包收纳(2款)、潮流鞋靴(2款)…」)。

        库不可达返回 [](调用方优雅省略盘点段),不降级 engine 本地表 ——
        盘点描述的是「商户店内」货架,跨目录拼数会误导。"""
        try:
            async with order_domain._merchant_reader_engine().connect() as conn:
                rows = (
                    (
                        await conn.execute(
                            text(
                                "SELECT s.category, COUNT(*) AS spu_count "
                                "FROM merchant_spus s WHERE s.status = 'ON_SALE' "
                                "GROUP BY s.category ORDER BY spu_count DESC, s.category ASC"
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
        except Exception as err:
            print(f"[MallDomain] 品类盘点不可达,诚实空回复省略盘点段: {err}")
            return []
        return [{"category": r["category"], "spuCount": int(r["spu_count"])} for r in rows]

    @staticmethod
    async def _invoke_rewrite_llm(prompt: str) -> str:
        """改写档 LLM 调用(独立静态方法 = 测试桩点);超时由调用方统一收口。"""
        response = await get_chat_model().ainvoke(prompt)
        return response.content if hasattr(response, "content") else str(response)

    @staticmethod
    async def _rewrite_query_terms(query: str, categories: list[str]) -> list[str]:
        """L4 同义词改写(2026-09-12):词元+语义双空后,以货架品类词表为锚,
        让 LLM 把口语措辞映射成货架检索词元再试一次。

        设计约束:①词表锚定 —— 改写只允许产出词表内品类词或其近义商品叫法,
        防 LLM 自由发挥跨目录补货(与「诚实空不跨目录」同一红线);②短超时
        (默认 2s)+ 任何异常降级空表,检索链终点始终是诚实空;③解析容错
        围栏/脏 JSON,产出经长度与数量钳制。"""
        if not categories:
            return []
        vocab_line = "、".join(categories)
        prompt = (
            f"用户在商店搜索：\"{query}\"\n"
            f"店内货架在售品类词表：{vocab_line}\n"
            "任务：判断用户想买的商品是否属于词表中某品类或其常见叫法（同义词/口语别称）。\n"
            '只输出 JSON 对体：{"terms": ["检索词", ...]}\n'
            "规则：\n"
            "1. terms 只放能在词表品类名或常见商品叫法上命中该需求的中文短词（2-6 字）；\n"
            "2. 最多 3 个，按可能性从高到低；\n"
            "3. 词表与该需求商品语义无关时输出 {\"terms\": []}，不要勉强关联；\n"
            "4. 不要输出任何解释文字。"
        )
        try:
            raw = await asyncio.wait_for(
                MallDomainService._invoke_rewrite_llm(prompt),
                timeout=settings.mall_query_rewrite_timeout_seconds,
            )
        except Exception as err:
            print(f"[MallDomain] 查询改写档降级空表(query={query!r}): {err}")
            return []
        clean = str(raw).strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```[a-zA-Z]*\s*", "", clean)
            clean = re.sub(r"\s*```$", "", clean).strip()
        try:
            parsed = json.loads(clean)
        except Exception:
            print(f"[MallDomain] 查询改写档输出不可解析,降级空表: {clean[:120]!r}")
            return []
        terms = parsed.get("terms") if isinstance(parsed, dict) else None
        if not isinstance(terms, list):
            return []
        cleaned: list[str] = []
        for term in terms[:3]:
            text_term = str(term).strip()
            if 1 < len(text_term) <= 6 and text_term not in cleaned:
                cleaned.append(text_term)
        return cleaned

    @staticmethod
    async def search_products(params: dict) -> dict:
        """6. 商品检索与导购选品。"""
        query = params.get("query")
        category = params.get("category")
        max_price = params.get("maxPrice")
        limit = params.get("limit") or 4
        effective_biz_id = params.get("businessId") or "ecommerce"
        # 词干别名展开(2026-09-12):口语统称「裤子/鞋子」→ 追加货架词素「裤/鞋」
        # 作 OR 词元 —— 商户货架与 engine 兜底两条词元路径共享;语义档仍嵌原始
        # query(0.55 阈值按原始查询定标,换表示会毁定标)。
        base_terms = MallDomainService._extract_query_terms(query)
        terms = MallDomainService._expand_stem_aliases(base_terms)

        if params.get("threadId") and effective_biz_id == "ecommerce":
            ctx = await OrderDomainService.get_thread_session_context(params["threadId"])
            if ctx["businessId"]:
                effective_biz_id = ctx["businessId"]

        # L3/L2(2026-09-11):聊天检索主目录换商户真货架(单商户现实,全租户含
        # ecommerce 统一路由;merchant 分支不吃 businessId —— 商户表无租户列)。
        # None=不可达降级 engine 本地 products 表;[]=可达查无 → 诚实空,
        # 严禁跨目录补货。词元查空且原始 NL 非空时,先经语义召回补位(L2,
        # 「户外过夜的装备」这类词元命中不了的口语措辞);浏览形输入(terms 空
        # 但 fetch 全量非空)不走语义。语义 None/[] 都落诚实空。
        # 多品类连词请求(词元 ≥2,如「裤子和衬衫」)按词元轮转配额:
        # 每个词元各取 top-limit 后交错合并去重——价格单序会让贵品类在
        # 小 limit 下全灭(实报症状第二层)。单品类/浏览形不进此路。
        merchant_products = None
        merchant_unreachable = False
        if len(base_terms) >= 2 and not category:
            per_term_lists: list[list[dict]] = []
            for term in base_terms:
                rows = await MallDomainService._fetch_merchant_catalog(
                    MallDomainService._expand_stem_aliases([term]), category, max_price, limit
                )
                if rows is None:
                    # 库不可达:立即中断,跳过词元单查,交给既有降级链
                    # (语义/L4 本就各自处理不可达),严禁 N 词元 N 次失败连接
                    per_term_lists = []
                    merchant_unreachable = True
                    break
                if rows:
                    per_term_lists.append(rows)
            if per_term_lists:
                merged: list[dict] = []
                seen_ids: set[str] = set()
                exhausted = False
                for rank in range(max(len(lst) for lst in per_term_lists)):
                    for lst in per_term_lists:
                        if rank < len(lst) and lst[rank]["id"] not in seen_ids:
                            seen_ids.add(lst[rank]["id"])
                            merged.append(lst[rank])
                            if len(merged) >= limit:
                                exhausted = True
                                break
                    if exhausted:
                        break
                merchant_products = merged
        if merchant_products is None and not merchant_unreachable:
            merchant_products = await MallDomainService._fetch_merchant_catalog(
                terms, category, max_price, limit
            )
        if merchant_products is not None:
            if not merchant_products and query and settings.mall_semantic_enabled:
                merchant_products = (
                    await MallDomainService._semantic_recall_merchant_catalog(
                        query, category, max_price, limit
                    )
                    or []
                )
            # L4(2026-09-12):词元+语义双空后的同义词改写重试 —— 口语统称与
            # 货架命名既无词元交集、余弦又卡阈值下时(「背心」症状:0.51-0.53
            # vs 0.55),LLM 以货架品类词表为锚改写一次。词表锚定 + 短超时降级,
            # 重试空即诚实空,不跨目录补货。
            if not merchant_products and query and settings.mall_query_rewrite_enabled:
                rewritten = await MallDomainService._rewrite_query_terms(
                    query, [o["category"] for o in await MallDomainService.get_shelf_overview()]
                )
                if rewritten:
                    merchant_products = (
                        await MallDomainService._fetch_merchant_catalog(
                            MallDomainService._expand_stem_aliases(rewritten), category, max_price, limit
                        )
                        or []
                    )
            return {"total": len(merchant_products), "products": merchant_products}

        try:
            conditions: list[str] = []
            query_params: dict = {}
            if effective_biz_id and effective_biz_id != "ecommerce":
                conditions.append("business_id = :bid")
                query_params["bid"] = effective_biz_id
            if terms:
                like_clauses = []
                for idx, term in enumerate(terms):
                    key = f"q{idx}"
                    query_params[key] = f"%{term}%"
                    like_clauses.append(f"(name ILIKE :{key} OR description ILIKE :{key})")
                conditions.append("(" + " OR ".join(like_clauses) + ")")
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
        except Exception as err:
            print(f"[MallDomainService.searchProducts] Database query error, degrade to honest empty: {err}")

        # 查无结果诚实返回空(2026-09-11):旧 `filtered or MOCK_PRODUCTS` 把整个
        # 目录冒充「推荐」全量返回(要背包给跑鞋)的欺骗性兜底已拆除,B 档先改
        # 诚实过滤、L3 起 MOCK_PRODUCTS 本体也删 —— 降级链终点只剩诚实空。纯
        # 浏览形输入由 terms 为空走无关键词全量路径,浏览语义不受影响。
        return {"total": 0, "products": []}

    @staticmethod
    async def compare_products(params: dict) -> dict:
        """7. 商品多维参数对比。"""
        product_ids = params["productIds"]
        # 对比池仅来自 search_products 真实结果(商户真货架优先链,2026-09-11):
        # 硬编码 Nike 拼接与点名 Pegasus/Invincible 的文案已拆除 —— 假货不得
        # 混入对比,话术不得点名检索结果里不存在的商品。
        search_res = await MallDomainService.search_products({**params, "limit": 10})
        matched = [
            p
            for p in (search_res.get("products") or [])
            if p.get("id") in product_ids or any(pid in (p.get("name") or "") for pid in product_ids)
        ]
        summary = (
            f"已为您对比 {len(matched)} 款商品的核心参数，如需逐项深挖某一维度请告诉我。"
            if matched
            else "未找到可对比的商品，请确认商品名称或编号后重试。"
        )
        return {
            "success": True,
            "comparedCount": len(matched),
            "products": matched,
            "summary": summary,
        }

    @staticmethod
    async def add_to_cart(params: dict) -> dict:
        """8. 购物车添加与管理。"""
        sku_id = params["skuId"]
        quantity = params.get("quantity") or 1
        title = params.get("title") or "精选商品"
        # 无价不入车(2026-09-12):旧兜底 899.0 恰为已拆除的 Pegasus 假商品价 ——
        # 编造价格会污染购物车总额,缺参必须如实拒绝(real-data-only/01)。
        if params.get("price") is None:
            return {
                "success": False,
                "message": "未能确定该商品的价格，无法加入购物车。请重新选择商品后再试。",
                "lastModifiedItemId": None,
            }
        price = params.get("price")
        cart_key = params.get("userId") or params.get("threadId") or "default_user"

        items = (await MallDomainService._load_cart(cart_key)) or []
        existing = next((i for i in items if i["skuId"] == sku_id), None)
        if existing:
            existing["quantity"] += quantity
        else:
            items.append(
                {
                    "skuId": sku_id,
                    "quantity": quantity,
                    "title": title,
                    "price": price,
                    "spec": params.get("spec"),
                }
            )
        await MallDomainService._save_cart(cart_key, items)

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
    async def has_cart(params: dict) -> bool:
        """购物车是否真实存在(storage 有键且非空)。

        get_cart_summary 对缺失键返回演示默认车(AJ1),调用方不可据其判空,
        否则会对空车播报幻影移除/改量(2026-09-06 修复)。
        """
        cart_key = params.get("userId") or params.get("threadId") or "default_user"
        return bool(await MallDomainService._load_cart(cart_key))

    @staticmethod
    async def get_cart_summary(params: dict) -> dict:
        cart_key = params.get("userId") or params.get("threadId") or "default_user"
        # 空车诚实空(2026-09-12):旧 `or [AJ1 演示车]` 兜底有两层欺骗 —— 空车是
        # 合法真实态被顶替,且 [] 是 falsy,清空购物车后查看必现幻影 AJ1
        # (real-data-only/01 实测 100% 复现)。
        items = (await MallDomainService._load_cart(cart_key)) or []
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
        items = (await MallDomainService._load_cart(cart_key)) or []

        if quantity <= 0:
            items = [i for i in items if i["skuId"] != sku_id]
        else:
            target = next((i for i in items if i["skuId"] == sku_id), None)
            if target:
                target["quantity"] = quantity

        await MallDomainService._save_cart(cart_key, items)
        total_amount = sum(i["price"] * i["quantity"] for i in items)
        return {
            "success": True,
            "message": "商品已从购物车移除" if quantity <= 0 else f"商品数量已更新为 {quantity} 件",
            # totalQuantity 与 add_to_cart 对齐:删除/改量后技能侧据此播报件数,
            # 缺键时 `or 0` 回退曾致"0 件商品,总金额 ¥2198"自相矛盾(2026-09-06)
            "cart": {
                "itemCount": len(items),
                "totalQuantity": sum(i["quantity"] for i in items),
                "totalAmount": total_amount,
                "items": items,
            },
        }
