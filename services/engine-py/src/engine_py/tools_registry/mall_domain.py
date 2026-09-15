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
import secrets
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
        # 包类口语名(2026-09-13):「登山包」子串不在「高山徒步轻量化背包」中,
        # 词素(背包/包)补匹配面
        "登山包": ("背包",),
        "爬山": ("高山", "徒步"),
        "登山": ("高山",),
        "腰包": (),
        "胸包": (),
    }
    # 词元清洗(ADR 检索链 L1):数量前缀逐块剥、「衬衫都」尾缀语气字仅剥
    # 长块(len>2,「成都」两字不动);⚠️ 分隔符连词只收「和/与」,「跟」
    # 严禁入列(高跟鞋/跟妆会被劈开)。
    # 数量词块内定位(2026-09-13;原名 _QUANTITY_PREFIX_RE 名不副实 —— 已非
    # ^ 前缀锚定,code-review 2026-09-14 正名):「推荐两款登山包」块首是
    # 「推荐」,前缀锚定剥不掉致词元全死落语义召回(渔夫帽顶了登山包)——
    # 改块内最小贪婪定位,剥到量词为止
    _QUANTITY_LOCATOR_RE = re.compile(r"^.*?(?:几[件条双款个]|[两三四五六七八九十]+[件条双款个]|\d+[件条双款个])")
    _TRAILING_PARTICLE_RE = re.compile(r"(?:都要|都|吧|呢|啊|呀)$")
    # 价格极值修饰词(2026-09-14 T3 矩阵):「最便宜的背包」曾把「便宜」混入
    # 词元稀释检索(头巾/水壶顶了真背包)—— 极值词是排序语义,剥除后由
    # search sort(price_desc)承接
    _PRICE_SUPERLATIVE_RE = re.compile(r"(?:最便宜|最贵|性价比高|性价比|便宜点|便宜)")
    # 疑问词与口语前缀清洗(2026-09-14 T3 矩阵):「最贵的冲锋衣是哪款」曾整块
    # 成词元「冲锋衣是哪款」ILIKE 必空
    _INTERROGATIVE_TOKEN_RE = re.compile(r"(?:是哪款|哪种|哪个|哪些|什么|怎么样|好吗)")
    _LEADING_FILLER_RE = re.compile(r"^(?:我们|我|你|您|经常|平时|一般|常常|总是|最近|帮忙|帮我|请|打算|想要|想|要|买|找|问|看|挑|选|的)+")

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
        """1. 查询用户收货地址簿(单账本:商户侧 merchant_customers.addresses,
        与商城前端「我的地址」同一存储 —— 双库分裂曾致聊天新增在前端永不可见,
        2026-09-14 用户实报)。"""
        from . import order_domain as _order_domain

        effective_user_id = user_id
        if not effective_user_id and thread_id:
            ctx = await OrderDomainService.get_thread_session_context(thread_id)
            effective_user_id = effective_user_id or ctx["userId"]
        if not effective_user_id:
            return {"total": 0, "userId": "current_user", "addresses": []}

        try:
            async with _order_domain._merchant_reader_engine().connect() as conn:
                raw = (
                    await conn.execute(
                        text("SELECT addresses FROM merchant_customers WHERE customer_id = :uid").bindparams(
                            uid=effective_user_id
                        )
                    )
                ).scalar()
        except Exception as err:
            print(f"[MallDomain] 地址簿查询失败(诚实空): {err}")
            raw = None
        entries = raw if isinstance(raw, list) else []
        addresses = [
            {
                "addressId": e.get("id"),
                "receiverName": e.get("recipientName"),
                "receiverPhone": e.get("phone"),
                "fullAddress": e.get("fullAddress"),
                "isDefault": bool(e.get("isDefault")),
            }
            for e in entries
            if isinstance(e, dict)
        ]
        return {
            "total": len(addresses),
            "userId": effective_user_id,
            "addresses": addresses,
            "message": f"共 {len(addresses)} 个收货地址。" if addresses else "地址列表为空。",
        }

    @staticmethod
    @staticmethod
    async def save_user_address(params: dict) -> dict:
        """保存或新增用户收货地址(单账本:商户侧 merchant_customers.addresses,
        与商城前端同一存储 —— 双库分裂曾致聊天新增在前端永不可见)。"""

        def _mask(phone: str | None) -> str:
            phone = str(phone or "")
            return phone[:3] + "****" + phone[-4:] if len(phone) == 11 else phone

        # 必填字段防线(2026-09-13 M7 实弹):缺参曾直接 KeyError 炸图熔断
        missing_fields = [
            key
            for key in ("province", "city", "district", "detailAddress", "receiverName", "receiverPhone")
            if not params.get(key)
        ]
        if missing_fields:
            return {
                "success": False,
                "missingFields": missing_fields,
                "message": "收货地址信息不完整（缺：" + "、".join(missing_fields) + "），请补充后再保存。",
            }

        from . import order_domain as _order_domain

        user_id = params.get("userId")
        if not user_id and params.get("threadId"):
            ctx = await _order_domain.OrderDomainService.get_thread_session_context(params["threadId"])
            user_id = user_id or ctx["userId"]
        if not user_id:
            return {"success": False, "message": "未能识别您的身份，无法保存地址，请稍后重试。"}

        full_address = (
            f"{params['province']}{params['city']}{params['district']}{params['detailAddress']}"
        )
        entry = {
            "id": params.get("id") or f"ADDR_{int(time.time() * 1000)}_{secrets.token_hex(2)}",
            "recipientName": params["receiverName"],
            "phone": _mask(params["receiverPhone"]),
            "province": params["province"],
            "city": params["city"],
            "district": params["district"],
            "detailAddress": params["detailAddress"],
            "fullAddress": full_address,
            "isDefault": bool(params.get("isDefault")),
        }

        try:
            async with _order_domain._merchant_reader_engine().begin() as conn:
                row = (
                    await conn.execute(
                        text("SELECT addresses FROM merchant_customers WHERE customer_id = :uid").bindparams(
                            uid=user_id
                        )
                    )
                ).mappings().first()
                current = (row.get("addresses") if row else None) or []
                updated = [dict(a) for a in current if isinstance(a, dict)]
                # 首条自动设默认;显式默认时清除其它默认(与商城前端同语义)
                should_default = entry["isDefault"] or not updated
                if should_default:
                    updated = [{**a, "isDefault": False} for a in updated]
                entry["isDefault"] = should_default
                existing = next((i for i, a in enumerate(updated) if a.get("id") == entry["id"]), -1)
                if existing >= 0:
                    updated[existing] = entry
                else:
                    updated.append(entry)
                await conn.execute(
                    text(
                        "INSERT INTO merchant_customers (customer_id, name, phone, addresses) VALUES "
                        "(:uid, :name, :phone, CAST(:a AS jsonb)) ON CONFLICT (customer_id) DO UPDATE "
                        "SET addresses = EXCLUDED.addresses"
                    ).bindparams(
                        uid=user_id, name=entry["recipientName"], phone=entry["phone"],
                        a=json.dumps(updated, ensure_ascii=False),
                    )
                )
        except Exception as err:
            print(f"[MallDomain] saveUserAddress(merchant ledger) failed: {err}")
            return {
                "success": False,
                "message": "收货地址保存失败，请稍后重试或联系人工客服。",
                "addressId": None,
                "fullAddress": full_address,
            }

        return {
            "success": True,
            "message": "收货地址保存成功",
            "addressId": entry["id"],
            "fullAddress": full_address,
            "isDefault": entry["isDefault"],
        }

    @staticmethod
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
        """4. 查询商品评价与口碑画像(2026-09-13 重写:商户真评价表)。

        此前查 engine 本地 product_reviews(products 域,0 行)—— 评价诉求
        全链无数据。现读 merchant_product_reviews,productName 按商品名模糊
        匹配 SPU,返回真实评分/内容;无评价诚实说明,严禁编造。
        """
        from . import order_domain as _order_domain

        product_name = (params.get("productName") or params.get("productId") or "").strip()
        limit = int(params.get("limit") or 5)
        try:
            async with _order_domain._merchant_reader_engine().connect() as conn:
                if product_name:
                    # 词元化匹配(2026-09-13):「三合一冲锋衣」子串不在
                    # 「极光三合一全天候户外硬壳冲锋衣」中,整词死匹配曾查空
                    tokens = [t for t in MallDomainService._extract_query_terms(product_name) if len(t) >= 2][:4]
                    # 整词空则 3/2 字滑窗子词(无分词器;「三合一冲锋衣」→「三合一/冲锋衣」)
                    if tokens:
                        probe = await conn.execute(
                            text(
                                "SELECT 1 FROM merchant_spus s WHERE "
                                + " OR ".join(
                                    f"(s.title ILIKE :kw{i} OR s.subtitle ILIKE :kw{i})"
                                    for i in range(len(tokens))
                                )
                                + " LIMIT 1"
                            ).bindparams(**{f"kw{i}": f"%{t}%" for i, t in enumerate(tokens)})
                        )
                        if probe.scalar() is None:
                            sliding = list({product_name[i:i + n] for n in (3, 2) for i in range(len(product_name) - n + 1)})
                            tokens = [w for w in sliding if len(w) >= 2][:6]
                    or_clauses = " OR ".join(
                        f"(s.title ILIKE :kw{i} OR s.subtitle ILIKE :kw{i})"
                        for i in range(len(tokens))
                    ) or "TRUE"
                    spu_rows = (
                        await conn.execute(
                            text(
                                f"SELECT s.id, s.title FROM merchant_spus s WHERE {or_clauses} LIMIT 5"
                            ).bindparams(**{f"kw{i}": f"%{t}%" for i, t in enumerate(tokens)})
                        )
                    ).mappings().all()
                else:
                    spu_rows = (
                        await conn.execute(text("SELECT s.id, s.title FROM merchant_spus s LIMIT 5"))
                    ).mappings().all()
                if not spu_rows:
                    return {
                        "success": True,
                        "reviews": [],
                        "averageRating": None,
                        "total": 0,
                        "message": f"暂未找到与「{product_name}」相关的在售商品，无法查询评价。",
                    }
                spu_ids = [str(r["id"]) for r in spu_rows]
                rows = (
                    await conn.execute(
                        text(
                            "SELECT r.rating, r.content, r.created_at, s.title AS spu_title "
                            "FROM merchant_product_reviews r JOIN merchant_spus s ON s.id = r.spu_id "
                            "WHERE r.spu_id = ANY(CAST(:ids AS uuid[])) "
                            "ORDER BY r.created_at DESC, r.rating DESC LIMIT :lim"
                        ).bindparams(ids=spu_ids, lim=limit)
                    )
                ).mappings().all()
        except Exception as err:
            print(f"[MallDomain] 商品评价查询失败(诚实空): {err}")
            return {"success": True, "reviews": [], "averageRating": None, "total": 0,
                    "message": "评价数据暂时查询不到，请稍后再试。"}

        reviews = [
            {
                "rating": int(r["rating"]),
                "content": r["content"],
                "product": r["spu_title"],
                "date": r["created_at"].strftime("%Y-%m-%d") if r.get("created_at") else None,
            }
            for r in rows
        ]
        average = round(sum(r["rating"] for r in reviews) / len(reviews), 1) if reviews else None
        message = (
            f"共找到 {len(reviews)} 条真实评价" + (f"，平均 {average} 分。" if average is not None else "")
            if reviews
            else "该商品暂无用户评价。"
        )
        return {
            "success": True,
            "reviews": reviews,
            "averageRating": average,
            "total": len(reviews),
            "message": message,
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
            chunk = MallDomainService._PRICE_SUPERLATIVE_RE.sub("", chunk.strip()).strip()
            chunk = MallDomainService._INTERROGATIVE_TOKEN_RE.sub("", chunk).strip()
            chunk = MallDomainService._QUANTITY_LOCATOR_RE.sub("", chunk.strip()).strip()
            # 口语前缀循环剥(「我经常爬山」→「爬山」)
            while True:
                stripped = MallDomainService._LEADING_FILLER_RE.sub("", chunk).strip()
                if stripped == chunk:
                    break
                chunk = stripped
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
        terms: list[str] | None, category: str | None, max_price, limit: int, sort: str | None = None
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
        title_hit_clause = ""
        if terms:
            like_clauses = []
            title_clauses = []
            for idx, term in enumerate(terms):
                key = f"q{idx}"
                params[key] = f"%{term}%"
                like_clauses.append(
                    f"(s.title ILIKE :{key} OR s.subtitle ILIKE :{key} "
                    f"OR s.category ILIKE :{key} OR s.description ILIKE :{key})"
                )
                title_clauses.append(f"s.title ILIKE :{key}")
            conditions.append("(" + " OR ".join(like_clauses) + ")")
            # 标题命中优先(2026-09-13):description 弱命中(渔夫帽描述含「包」)
            # 曾凭价格优势把 title 强命中的真背包挤出 LIMIT
            title_hit_clause = f"({' OR '.join(title_clauses)})"
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
                                + (
                                    f"ORDER BY (CASE WHEN {title_hit_clause} THEN 0 ELSE 1 END), "
                                    + ("min_price DESC " if sort == "price_desc" else "min_price ASC ")
                                    + "LIMIT :lim"
                                    if title_hit_clause
                                    else (
                                        "ORDER BY min_price DESC LIMIT :lim"
                                        if sort == "price_desc"
                                        else "ORDER BY min_price ASC LIMIT :lim"
                                    )
                                )
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
        """6. 商品检索与导购选品。sort: "price_desc" 按价格降序(「最贵的X」)。"""
        query = params.get("query")
        sort_mode = params.get("sort")
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
                terms, category, max_price, limit, sort=sort_mode
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
            row = {
                "skuId": sku_id,
                "quantity": quantity,
                "title": title,
                "price": price,
                "spec": params.get("spec"),
                # 图片透传(2026-09-15 用户实报):车行缺图曾致前端卡片图不对
                "imageUrl": params.get("imageUrl"),
            }
            # 规格摘要(2026-09-15 用户实报:商城页「规格:」空白):入车即落
            # 可读摘要,卡片 specSummary 与商城页 skuTitle 直接消费
            spec = params.get("spec")
            if isinstance(spec, dict) and spec:
                row["specSummary"] = " / ".join(str(v) for v in spec.values())
            # 可选引用键(2026-09-14 点名直配):skuCode 钉住用户点名的确切规格
            # (结算 sku_code 直配优先,不再被「SPU 最低价」静默换规格);spuId
            # 供前端卡片/商城链接回指 SPU。缺省不落键,旧行形状不变。
            if params.get("skuCode"):
                row["skuCode"] = str(params["skuCode"])
            if params.get("spuId"):
                row["spuId"] = str(params["spuId"])
            items.append(row)
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
    def _shelf_text_tokens(text: str) -> set[str]:
        """货架文本词袋(按名直配评分用):CJK 二元组 + 拉丁/数字词元。"""
        tokens: set[str] = set()
        for run in re.findall(r"[\u4e00-\u9fff]+", text):
            if len(run) == 1:
                tokens.add(run)
            else:
                tokens.update(run[i : i + 2] for i in range(len(run) - 1))
        for run in re.findall(r"[A-Za-z0-9]+", text):
            tokens.add(run.lower())
        return tokens

    @staticmethod
    async def find_shelf_sku_by_description(query: str) -> dict | None:
        """按自然语言描述直配商户货架 SKU(2026-09-14 点名错替收口)。

        症状:用户点名「极光三合一冲锋衣 曜石黑 M码 加入购物车」,加购链从未
        实现按名解析 —— 名字被静默忽略后落 candidate[0],真商品错替与幻影
        同族(此前拆除的是假商品兜底,真商品错替这半一直都在)。

        评分:查询对 (SPU 标题 + SKU 标题 + 规格值) 的字符二元组 F1。判据:
        冠军分 ≥0.35 且领先次名 ≥0.03 才直配;并列/接近并列 = 无法唯一确定,
        返回 None 由调用方诚实反问(同名不同规格、货架无此物都走这条路)。
        货架不可达/空架返回 None,绝不阻断。
        """
        query_tokens = MallDomainService._shelf_text_tokens(query)
        if not query_tokens:
            return None
        try:
            async with order_domain._merchant_reader_engine().connect() as conn:
                rows = (
                    (
                        await conn.execute(
                            text(
                                "SELECT k.sku_code, k.sku_title, k.spec_attributes, k.price, k.stock, "
                                "s.spu_code, s.title AS spu_title, s.main_image "
                                "FROM merchant_skus k JOIN merchant_spus s ON s.id = k.spu_id "
                                "WHERE s.status = 'ON_SALE' AND k.stock > 0 LIMIT 300"
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
        except Exception as err:
            print(f"[MallDomain] 按名直配货架不可达,交回调用方处理: {err}")
            return None
        scored: list[tuple[float, str, dict]] = []
        for r in rows:
            spec = r["spec_attributes"]
            spec_text = " ".join(str(v) for v in spec.values()) if isinstance(spec, dict) else str(spec or "")
            row_tokens = MallDomainService._shelf_text_tokens(f"{r['spu_title']} {r['sku_title'] or ''} {spec_text}")
            if not row_tokens:
                continue
            f1 = 2 * len(query_tokens & row_tokens) / (len(query_tokens) + len(row_tokens))
            scored.append((f1, r["sku_code"], dict(r)))
        if not scored:
            return None
        scored.sort(key=lambda t: (-t[0], t[1]))
        best_f1, best_code, best_row = scored[0]
        if best_f1 < 0.35:
            return None

        def _spec_hits(row: dict) -> int:
            """查询对 SKU 级文本(sku_title+规格值)的命中数 —— 同 SPU 兄弟规格的
            判别器:SPU 标题人人相同,规格词(颜色/尺码)说了才算。"""
            spec = row["spec_attributes"]
            spec_text = " ".join(str(v) for v in spec.values()) if isinstance(spec, dict) else ""
            return len(query_tokens & MallDomainService._shelf_text_tokens(f"{row['sku_title'] or ''} {spec_text}"))

        near = [s for s in scored if s[0] >= best_f1 - 0.03]
        if len(near) > 1:
            # 近并列二分:跨 SPU(两款不同商品都像)→ 诚实反问;同 SPU 兄弟规格
            # → 规格词命中多者胜(「冰川白 M码」vs「曜石黑 L」),命中同数 =
            # 用户没消解规格,反问尺码颜色。
            if any(s[2]["spu_code"] != near[0][2]["spu_code"] for s in near[1:]):
                return None
            hits = [(_spec_hits(s[2]), s) for s in near]
            max_h = max(h for h, _ in hits)
            winners = [s for h, s in hits if h == max_h]
            if len(winners) != 1:
                return None
            best_code, best_row = winners[0][1], winners[0][2]

        best_spec = best_row["spec_attributes"] if isinstance(best_row["spec_attributes"], dict) else {}
        return {
            "skuCode": best_code,
            "spuCode": best_row["spu_code"],
            "spuTitle": best_row["spu_title"],
            "skuTitle": best_row["sku_title"] or "",
            "title": f"{best_row['spu_title']} {best_row['sku_title'] or ''}".strip(),
            "price": float(best_row["price"]),
            "stock": int(best_row["stock"] or 0),
            "imageUrl": best_row["main_image"],
            "spec": best_spec,
        }

    @staticmethod
    async def hydrate_cart_from_storefront(params: dict) -> bool:
        """商城门户车 → 引擎车幂等合并(2026-09-14 空车谎报收口)。

        症状:商城 UI 加购只写浏览器 localStorage,引擎车在 Redis,两存储互不
        相通 —— 用户说「删除/结算/查看购物车」时引擎只见空车,谎报「购物车
        还是空的」。每封聊天请求携带商城车条目(storeCart),本方法把引擎车
        没有的条目并进去:引擎车是会话内权威车,聊天侧删除经 cart_card 快照
        回同步商城车,商城侧重加经下一封消息水合回来 —— 双向最终一致。

        契约:skuCode 已在引擎车(聊天侧同款)→ 跳过,严禁覆盖聊天侧数量;
        载荷空/全部无效 → False;垃圾条目逐条容错,绝不抛出 —— 水合失败只
        降级为「引擎车维持原状」,聊天主链路照常。无价条目不入车(镜像
        add_to_cart 的无价拒绝红线,严禁以 0/兜底价污染车总额)。
        """
        try:
            items = params.get("items") or []
            valid = [
                it
                for it in items
                if isinstance(it, dict)
                and isinstance(it.get("skuCode"), str)
                and it["skuCode"]
                and isinstance(it.get("price"), (int, float))
            ]
            if not valid:
                return False
            cart_params = {"userId": params.get("userId"), "threadId": params.get("threadId")}
            cart_key = cart_params.get("userId") or cart_params.get("threadId") or "default_user"
            existing_skus = {i.get("skuId") for i in ((await MallDomainService._load_cart(cart_key)) or [])}
            added = False
            for it in valid:
                # 行主键维持 SPU 粒度契约(skuId=spuId 优先,退回 skuCode);确切
                # 规格经 skuCode 钉住,结算直配不换规格
                row_key = str(it.get("spuId") or it["skuCode"])
                if row_key in existing_skus:
                    continue
                try:
                    quantity = max(1, int(it.get("quantity") or 1))
                except (TypeError, ValueError):
                    quantity = 1
                price = it.get("price")
                await MallDomainService.add_to_cart(
                    {
                        "skuId": row_key,
                        "quantity": quantity,
                        "title": it.get("title") or "精选商品",
                        "price": float(price) if isinstance(price, (int, float)) else None,
                        "spec": it.get("specAttributes"),
                        "imageUrl": it.get("imageUrl"),
                        "skuCode": str(it["skuCode"]),
                        "spuId": row_key,
                        "userId": cart_params.get("userId"),
                        "threadId": cart_params.get("threadId"),
                    }
                )
                added = True
            return added
        except Exception as err:
            print(f"[MallDomain] 商城车水合失败,引擎车维持原状: {err}")
            return False

    # ── 真·聊天下单与订单→购物车桥接(遗留二期,2026-09-13)────────────────
    # 结算与商城页 create_order_from_cart 同一真账本语义:FOR UPDATE 锁库存、
    # 校验并扣减、PAID、cost_at_purchase 快照、all-or-nothing(任一行失败整单
    # 不落)。购物车行是 SPU 粒度(skuId=spu_code,导购目录 id 契约),结算解析
    # 为该 SPU 当前 ON_SALE 且有库存的最低价 SKU —— 与展示价=MIN(price) 同
    # 语义,规格在回复中如实展示;skuId 直配 sku_code 时按商城页同源直取。

    @staticmethod
    async def delete_user_address(params: dict) -> dict:
        """删除收货地址(2026-09-15 能力补齐):按收件人/full_address 子串定位
        顾客账本条目并移除;找不到/歧义如实说明。"""
        from . import order_domain as _order_domain

        user_id = params.get("userId")
        if not user_id and params.get("threadId"):
            ctx = await _order_domain.OrderDomainService.get_thread_session_context(params["threadId"])
            user_id = user_id or ctx["userId"]
        target = (params.get("addressId") or params.get("receiverName") or params.get("fullAddress") or "").strip()
        if not user_id or not target:
            return {"success": False, "message": "请告诉我要删除哪个收货地址（收件人或地址）。"}

        try:
            async with _order_domain._merchant_reader_engine().begin() as conn:
                raw = (
                    await conn.execute(
                        text("SELECT addresses FROM merchant_customers WHERE customer_id = :uid").bindparams(
                            uid=user_id
                        )
                    )
                ).scalar()
            entries = raw if isinstance(raw, list) else []
            hits = [
                e for e in entries
                if isinstance(e, dict) and (
                    target in (e.get("fullAddress") or "")
                    or target in (e.get("recipientName") or "")
                    or e.get("id") == target
                )
            ]
            if not hits:
                return {"success": False, "message": f"地址簿里没有找到与「{target}」匹配的收货地址。"}
            if len(hits) > 1:
                names = "、".join(f"「{h.get('fullAddress')}」" for h in hits)
                return {"success": False, "message": f"找到 {len(hits)} 条匹配地址：{names}，请指明要删除哪一条。"}
            remaining = [e for e in entries if e is not hits[0]]
            await conn.execute(
                text(
                    "UPDATE merchant_customers SET addresses = CAST(:a AS jsonb) WHERE customer_id = :uid"
                ).bindparams(uid=user_id, a=json.dumps(remaining, ensure_ascii=False))
            )
            return {
                "success": True,
                "message": f"已删除收货地址：{hits[0].get('fullAddress')}",
            }
        except Exception as err:
            print(f"[MallDomain] deleteUserAddress failed: {err}")
            return {"success": False, "message": "地址删除失败，请稍后重试。"}

    @staticmethod
    async def set_default_address(params: dict) -> dict:
        """设默认收货地址(2026-09-15 S8 能力补齐):按 receiver_name 或地址 id
        定位顾客账本条目,置 is_default 并清除其它默认;找不到如实说明。"""
        from . import order_domain as _order_domain

        user_id = params.get("userId")
        if not user_id and params.get("threadId"):
            ctx = await _order_domain.OrderDomainService.get_thread_session_context(params["threadId"])
            user_id = user_id or ctx["userId"]
        if not user_id:
            return {"success": False, "message": "未能识别您的身份，请稍后重试。"}
        target = (params.get("addressId") or params.get("receiverName") or "").strip()

        try:
            async with _order_domain._merchant_reader_engine().begin() as conn:
                raw = (
                    await conn.execute(
                        text("SELECT addresses FROM merchant_customers WHERE customer_id = :uid").bindparams(
                            uid=user_id
                        )
                    )
                ).scalar()
            entries = raw if isinstance(raw, list) else []
            if not entries:
                return {"success": False, "message": "您的地址簿还是空的，暂无可设为默认的地址。"}
            hit = None
            for e in entries:
                if not isinstance(e, dict):
                    continue
                name = (e.get("recipientName") or "")
                addr = (e.get("fullAddress") or "")
                # 子串双向匹配(「王五」含于「王五 的地址」等 LLM 转述形态)
                if target and (
                    e.get("id") == target
                    or target in name
                    or name in target
                    or target in addr
                ):
                    hit = e
                    break
            if hit is None:
                names = "、".join(str(e.get("recipientName") or "未命名") for e in entries if isinstance(e, dict))
                return {"success": False, "message": f"地址簿里没找到「{target or '该地址'}」。现有：{names}"}
            for e in entries:
                if isinstance(e, dict):
                    e["isDefault"] = e is hit
            async with _order_domain._merchant_reader_engine().begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE merchant_customers SET addresses = CAST(:a AS jsonb) "
                        "WHERE customer_id = :uid"
                    ).bindparams(uid=user_id, a=json.dumps(entries, ensure_ascii=False))
                )
            return {
                "success": True,
                "message": (
                    f"已将【{hit.get('recipientName')}】的地址（{hit.get('fullAddress')}）设为默认收货地址。"
                ),
                "addressId": hit.get("id"),
            }
        except Exception as err:
            print(f"[MallDomain] setDefaultAddress failed: {err}")
            return {"success": False, "message": "默认地址设置失败，请稍后重试。"}

    @staticmethod
    async def _default_address_row(user_id: str) -> dict | None:
        """地址簿默认条目(商户账本 merchant_customers.addresses,is_default
        优先无则最新一条);账本不可达/无地址返回 None —— checkout 诚实追问。"""
        from . import order_domain as _order_domain

        try:
            async with _order_domain._merchant_reader_engine().connect() as conn:
                raw = (
                    await conn.execute(
                        text("SELECT addresses FROM merchant_customers WHERE customer_id = :uid").bindparams(
                            uid=user_id
                        )
                    )
                ).scalar()
        except Exception as err:
            print(f"[MallDomain] 地址簿查询失败(按无地址处理): {err}")
            return None
        entries = raw if isinstance(raw, list) else []
        if not entries:
            return None
        chosen = next((e for e in entries if e.get("isDefault")), entries[0])
        return {
            "receiver_name": chosen.get("recipientName"),
            "receiver_phone": chosen.get("phone"),
            "full_address": chosen.get("fullAddress"),
        }

    @staticmethod
    async def _resolve_purchasable_sku(conn, *, spu_id: str | None = None, spu_code: str | None = None, sku_code: str | None = None) -> dict | None:
        """解析当前可购 SKU:sku_code 直配优先,否则 SPU(按 id 或 code)在售
        且有库存的最低价 SKU;不可售返回 None。"""
        if sku_code:
            row = (
                await conn.execute(
                    text(
                        "SELECT k.sku_code, k.price, k.stock, k.sku_title, k.spec_attributes, "
                        "k.cost_price, k.image_url, s.id AS spu_id, s.spu_code AS spu_code, "
                        "s.title AS spu_title, s.main_image "
                        "FROM merchant_skus k JOIN merchant_spus s ON s.id = k.spu_id "
                        "WHERE k.sku_code = :code AND s.status = 'ON_SALE' LIMIT 1"
                    ).bindparams(code=sku_code)
                )
            ).mappings().first()
            if row:
                return dict(row)
        if spu_id or spu_code:
            # items.spu_id 的事实契约是 spu_code(排行/桥接 join 口径),但历史
            # 数据两形态并存(UUID 文本/编码)—— 双匹配统一兼容
            bind = {"sid": str(spu_id or spu_code)}
            row = (
                await conn.execute(
                    text(
                        "SELECT k.sku_code, k.price, k.stock, k.sku_title, k.spec_attributes, "
                        "k.cost_price, k.image_url, s.id AS spu_id, s.spu_code AS spu_code, "
                        "s.title AS spu_title, s.main_image "
                        "FROM merchant_skus k JOIN merchant_spus s ON s.id = k.spu_id "
                        "WHERE (s.id::text = :sid OR s.spu_code = :sid) "
                        "AND s.status = 'ON_SALE' AND k.stock > 0 "
                        "ORDER BY k.price ASC LIMIT 1"
                    ).bindparams(**bind)
                )
            ).mappings().first()
            if row:
                return dict(row)
        return None

    @staticmethod
    async def checkout_user_cart(params: dict) -> dict:
        """真·聊天下单:购物车 → 商户真单(遗留二期,2026-09-13)。

        与商城页同一账本:任一行不可售整单不落(all-or-nothing);地址取显式
        提供 > 地址簿默认 > 诚实追问(严禁假地址兜底,real-data-only/01)。
        顾客自有资金的下单与商城页同权,不走 HITL。
        """
        from . import order_domain as _order_domain

        user_id = params.get("userId")
        if not user_id and params.get("threadId"):
            ctx = await _order_domain.OrderDomainService.get_thread_session_context(params["threadId"])
            user_id = user_id or ctx["userId"]
        if not user_id:
            return {"success": False, "message": "未能识别您的身份，无法结算，请稍后重试。"}

        items = (await MallDomainService._load_cart(user_id)) or []
        if not items:
            return {
                "success": False,
                "message": "购物车还是空的，先挑点商品加入购物车，再来对我说「结算下单」吧！",
            }

        # 复合「加购+下单」范围结算(2026-09-15 用户实报「说的第一个商品,为什么
        # 这么多」):同句既加购又下单时,executor 快路径经 cartContext.addedThisTurn
        # 注入 onlySkuIds —— 只结本轮加购的行,历史在车遗留品不得静默陪结,也不得
        # 被清车。范围显式为空(加购半未完成)→ 诚实拒结,绝不拿遗留品开单(S6
        # 跨品类错单守卫同哲学)。参数缺省(None)保持整车结算旧契约。
        only_sku_ids = params.get("onlySkuIds")
        scoped_checkout = only_sku_ids is not None
        all_items = list(items)
        if scoped_checkout:
            wanted = {str(i) for i in (only_sku_ids or []) if str(i)}
            items = [
                i
                for i in items
                if str(i.get("skuId") or "") in wanted or str(i.get("skuCode") or "") in wanted
            ]
            if not items:
                return {
                    "success": False,
                    "message": "本轮要结算的商品还没有加入购物车（加购可能未完成），已为您取消本次结算；购物车商品保持不变。",
                }

        # 收货地址:显式 > 地址簿默认 > 诚实追问
        raw_addr = params.get("shippingAddress")
        addr_dict: dict | None = None
        if isinstance(raw_addr, dict) and (raw_addr.get("fullAddress") or raw_addr.get("address")):
            addr_dict = {
                "recipientName": raw_addr.get("recipientName") or "顾客",
                "phone": str(raw_addr.get("phone") or ""),
                "fullAddress": raw_addr.get("fullAddress") or raw_addr.get("address"),
            }
        elif isinstance(raw_addr, str) and raw_addr.strip():
            # 收件人/电话取地址簿默认行真值;顾客口述地址通常只有地址本身,
            # 缺人名电话时如实占位(与 needsAddress 追问路径同一诚实口径)
            fallback_row = await MallDomainService._default_address_row(user_id)
            addr_dict = {
                "recipientName": (fallback_row or {}).get("receiver_name") or "顾客",
                "phone": str((fallback_row or {}).get("receiver_phone") or ""),
                "fullAddress": raw_addr.strip(),
            }
        if addr_dict is None:
            default_row = await MallDomainService._default_address_row(user_id)
            if default_row:
                addr_dict = {
                    "recipientName": default_row["receiver_name"],
                    "phone": str(default_row["receiver_phone"] or ""),
                    "fullAddress": default_row["full_address"],
                }
            else:
                return {
                    "success": False,
                    "needsAddress": True,
                    "message": "结算需要收货地址，您的地址簿还是空的。请告诉我收件人姓名、电话和详细地址，我为您创建后再结算。",
                }

        try:
            async with _order_domain._merchant_reader_engine().begin() as conn:
                resolved: list[dict] = []
                failures: list[str] = []
                for item in items:
                    qty = int(item.get("quantity") or 1)
                    # 行上钉了 skuCode(点名直配)优先按确切规格直取,严禁被
                    # 「SPU 最低价」静默换掉用户点名的规格;未钉 skuCode 的行
                    # (导购候选/SKU 直配)维持原解析次序
                    sid = str(item.get("skuCode") or item.get("skuId") or "")
                    sku = await MallDomainService._resolve_purchasable_sku(conn, sku_code=sid)
                    if sku is None:
                        sku = await MallDomainService._resolve_purchasable_sku(conn, spu_code=sid)
                    if sku is None:
                        failures.append(f"{item.get('title') or sid}：已下架或暂无库存")
                        continue
                    if sku["stock"] < qty:
                        failures.append(f"{sku['spu_title']}（{sku['sku_title']}）：库存不足，仅剩 {sku['stock']} 件")
                        continue
                    resolved.append({**sku, "quantity": qty})
                if failures:
                    return {
                        "success": False,
                        "message": "以下商品无法结算：" + "；".join(failures),
                        "failures": failures,
                    }

                # 订单号查重(AURORA-ORD-2026-XXXX 与种子/商城页同格式)
                order_id = ""
                for _ in range(6):
                    candidate = f"AURORA-ORD-2026-{random.randint(1000, 9999)}"
                    exists = (
                        await conn.execute(
                            text("SELECT 1 FROM merchant_orders WHERE order_id = :o").bindparams(o=candidate)
                        )
                    ).scalar()
                    if not exists:
                        order_id = candidate
                        break
                if not order_id:
                    return {"success": False, "message": "订单号生成冲突，请稍后重试。"}

                total_amount = 0.0
                line_summaries: list[str] = []
                # 条件 UPDATE(stock >= qty)原子防超卖:resolve 与扣减之间读
                # COMMITTED 快照可被并发单改掉,rowcount=0 即并发失利 → 整单不落
                for r in resolved:
                    updated = await conn.execute(
                        text(
                            "UPDATE merchant_skus SET stock = stock - :qty "
                            "WHERE sku_code = :code AND stock >= :qty"
                        ).bindparams(qty=r["quantity"], code=r["sku_code"])
                    )
                    if not updated.rowcount:
                        return {
                            "success": False,
                            "message": f"{r['spu_title']}（{r['sku_title'] or '默认规格'}）刚刚被抢购一空，库存不足，请稍后再试。",
                        }
                    total_amount += float(r["price"]) * r["quantity"]
                    line_summaries.append(
                        f"{r['spu_title']}（{r['sku_title'] or '默认规格'}）x{r['quantity']} ¥{r['price']}"
                    )

                # 主单先行:items.order_id 对 merchant_orders 有外键
                await conn.execute(
                    text(
                        "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, currency, "
                        "shipping_address, is_returnable, is_address_modifiable) "
                        "VALUES (:oid, :cid, 'PAID', :amt, 'CNY', CAST(:addr AS jsonb), TRUE, TRUE)"
                    ).bindparams(
                        oid=order_id, cid=user_id, amt=round(total_amount, 2),
                        addr=json.dumps(addr_dict, ensure_ascii=False),
                    )
                )
                for r in resolved:
                    spec_summary = " / ".join(
                        f"{k}:{v}" for k, v in (r.get("spec_attributes") or {}).items()
                    )
                    await conn.execute(
                        text(
                            "INSERT INTO merchant_order_items (order_id, spu_id, sku_code, title, sku_title, "
                            "quantity, price, image_url, spec_summary, cost_at_purchase) VALUES "
                            "(:oid, :spu, :code, :t, :st, :qty, :price, :img, :spec, :cost)"
                        ).bindparams(
                            oid=order_id, spu=str(r["spu_code"]), code=r["sku_code"], t=r["spu_title"],
                            st=r["sku_title"] or "", qty=r["quantity"], price=r["price"],
                            img=r.get("image_url"), spec=spec_summary, cost=r.get("cost_price") or 0,
                        )
                    )
        except Exception as err:
            print(f"[MallDomain] checkout failed: {err}")
            return {"success": False, "message": "结算失败，请稍后重试或转人工客服处理。"}

        # 清车:整车结算清空;范围结算只移除已结的行,遗留品原样保留。
        # 按对象身份剔除(过滤保留了原行引用):旧车行形状 skuId=spu_code 时
        # 同款双规格两行 skuId 相同,按 skuId 键剔除会误删未结算规格。
        if scoped_checkout:
            settled_ids = {id(i) for i in items}
            remaining = [i for i in all_items if id(i) not in settled_ids]
            await MallDomainService._save_cart(user_id, remaining)
        else:
            await MallDomainService._save_cart(user_id, [])
        return {
            "success": True,
            "orderId": order_id,
            "totalAmount": round(total_amount, 2),
            "items": line_summaries,
            "shippingAddress": addr_dict["fullAddress"],
        }

    @staticmethod
    async def add_order_item_to_cart(params: dict) -> dict:
        """订单→购物车桥接(遗留二期,2026-09-13):按关键词在顾客商户真单
        明细里找买过的商品,解析当前在售最低价 SKU 真实回车。

        零命中/多命中/已下架一律如实回复:多命中列出候选让顾客挑,严禁静默
        选一个;历史成交价不等于当前售价,入车价必须取当前货架价。
        """
        from . import order_domain as _order_domain

        keyword = (params.get("keyword") or "").strip()
        # 口语量词剥除:「那件冲锋衣/这款背包」→「冲锋衣/背包」,否则 ILIKE 落空
        keyword = re.sub(r"^(?:那|这|该|此)(?:件|款|个|只|台|条)", "", keyword).strip()
        user_id = params.get("userId")
        if not user_id and params.get("threadId"):
            ctx = await _order_domain.OrderDomainService.get_thread_session_context(params["threadId"])
            user_id = user_id or ctx["userId"]
        if not keyword:
            return {"success": False, "message": "请告诉我想把订单里的哪件商品加入购物车（说出商品名即可）。"}
        if not user_id:
            return {"success": False, "message": "未能识别您的身份，请稍后重试。"}

        try:
            async with _order_domain._merchant_reader_engine().connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT oi.spu_id, MIN(oi.title) AS title FROM merchant_order_items oi "
                            "JOIN merchant_orders o ON o.order_id = oi.order_id "
                            "WHERE o.customer_id = :uid AND o.status NOT IN ('REFUNDED','CANCELLED') "
                            "AND (oi.title ILIKE :kw OR oi.sku_title ILIKE :kw) "
                            "GROUP BY oi.spu_id ORDER BY MIN(oi.title) LIMIT 20"
                        ).bindparams(uid=user_id, kw=f"%{keyword}%")
                    )
                ).mappings().all()
        except Exception as err:
            print(f"[MallDomain] 订单明细查询失败: {err}")
            return {"success": False, "message": "暂时查不到您的订单记录，请稍后再试。"}

        if not rows:
            return {"success": False, "message": f"您的订单里没有找到「{keyword}」相关的商品。"}
        if len(rows) > 1:
            titles = "、".join(f"「{r['title']}」" for r in rows)
            return {
                "success": False,
                "message": f"您的订单里有 {len(rows)} 件商品与「{keyword}」相关：{titles}。请告诉我要把哪一件加入购物车。",
            }

        row = rows[0]
        try:
            async with _order_domain._merchant_reader_engine().begin() as conn:
                sku = await MallDomainService._resolve_purchasable_sku(conn, spu_id=str(row["spu_id"]))
        except Exception as err:
            print(f"[MallDomain] 桥接 SKU 解析失败: {err}")
            return {"success": False, "message": "暂时无法确认该商品的在售状态，请稍后再试。"}
        if sku is None:
            return {"success": False, "message": f"「{row['title']}」目前已下架或无库存，暂时无法再次购买。"}

        add_res = await MallDomainService.add_to_cart(
            {
                "skuId": sku["sku_code"],
                "quantity": 1,
                "title": row["title"],
                "price": float(sku["price"]),
                "spec": sku["sku_title"] or "",
                "userId": user_id,
                "threadId": params.get("threadId"),
            }
        )
        if not add_res.get("success"):
            return add_res
        return {
            "success": True,
            "message": (
                f"已将您订单里的「{row['title']}」加入购物车"
                f"（当前在售规格：{sku['sku_title'] or '默认'}，¥{sku['price']}）。"
            ),
            "lastModifiedItemId": sku["sku_code"],
            "cart": add_res.get("cart"),
        }

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
