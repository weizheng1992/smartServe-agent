"""目录/检索簇:SKU 查询、评价、词元与词干别名、catalog_match、商户真账检索 + L2 语义召回 + L4 改写、货架盘点、对比、寻源。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re

from sqlalchemy import text

from ...config import settings
from ...db import get_session
from ...llm.chat import get_chat_model, get_embedding_model
from ...tenant_context import resolve_business_id
from ...vectors import cosine_similarity  # 余弦单一实现(vectors.py)
from .. import order_domain
from ..order_domain import OrderDomainService

MallDomainService = None  # service.py 类定义后回填(调用时经本模块全局解析,patch 面不漂移)


class CatalogMixin:
    """簇方法集;经 service.MallDomainService 合并为一类(全部 staticmethod)。"""

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
        # 衣族统称(2026-10-01 实弹「推荐衣服和背包」0 衣服 + 2 包):货架四列
        # 词面无「衣服」子串(以 衬衫/T恤/夹克/冲锋衣/羽绒/裤/POLO 命名),
        # 词元脚恒空被多词元轮转静默丢族,%背包% 一族独吞 limit。别名只在核实
        # 过货架词素后收录(同上纪律),词素面经 get_shelf_overview 实核。
        "衣服": ("衬衫", "T恤", "夹克", "冲锋衣", "羽绒", "裤", "POLO"),
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
    # intent-exception(rewrite-pipeline,域A例外④:检索改写管道的剥词面,
    # sub 交替次序即剥词语义;且 mall_domain → triage 反向 import 会成环)
    _PRICE_SUPERLATIVE_RE = re.compile(r"(?:最便宜|最贵|性价比高|性价比|便宜点|便宜)")
    # 疑问词与口语前缀清洗(2026-09-14 T3 矩阵):「最贵的冲锋衣是哪款」曾整块
    # 成词元「冲锋衣是哪款」ILIKE 必空

    _INTERROGATIVE_TOKEN_RE = re.compile(r"(?:是哪款|哪种|哪个|哪些|什么|怎么样|好吗)")

    _LEADING_FILLER_RE = re.compile(r"^(?:我们|我|你|您|经常|平时|一般|常常|总是|最近|帮忙|帮我|请|打算|想要|想|要|买|找|问|看|挑|选|的)+")

    # 到千级 SPU 后的事,现在引入是过度设计。
    _spu_embedding_cache: dict[str, tuple[str, list[float]]] = {}

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
    async def query_product_reviews(params: dict) -> dict:
        """4. 查询商品评价与口碑画像(2026-09-13 重写:商户真评价表)。

        此前查 engine 本地 product_reviews(products 域,0 行)—— 评价诉求
        全链无数据。现读 merchant_product_reviews,productName 按商品名模糊
        匹配 SPU,返回真实评分/内容;无评价诚实说明,严禁编造。
        """
        from .. import order_domain as _order_domain

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
    def search_terms(query: str | None) -> list[str]:
        """检索词元公共门面(A8 收敛):剥导购 wrapper 词 + 分隔切分 + 词干
        别名展开。网关 SPI 商品检索此前整句 ILIKE —— 整句子串对 NL 措辞
        永远空手而归(engine 2026-09-11 同症状),收敛后两侧同一词元实现。"""
        return MallDomainService._expand_stem_aliases(MallDomainService._extract_query_terms(query))

    @staticmethod
    def catalog_match(
        terms: list[str] | None, category: str | None = None, color: str | None = None
    ) -> tuple[list[str], dict, str]:
        """商品货架 WHERE 匹配子句的唯一实现(A8 收敛):ON_SALE 门槛 + 词元
        四列 OR ILIKE(title/subtitle/category/description)+ 标题命中优先
        子句。engine 导购链(`_fetch_merchant_catalog`)与网关 SPI 商品检索
        (gateway merchant_domain.search_products)共用,严禁再各自维护一份
        匹配语义。绑定名 ``qN``/``cat``/``colr``,表别名固定 ``s``
        (merchant_spus)。返回 (conditions, params, title_hit_clause)。

        颜色过滤(2026-10-01 实弹「我喜欢黑色…」宣了结合零结合):颜色只活在
        merchant_skus.spec_attributes->>'颜色'(曜石黑/石墨黑),SPU 四列词面
        无「黑」——词元路径结构上看不见颜色,必须 SKU 级 EXISTS 显式过滤。
        词素归一剥尾缀「色」(黑色→黑),子串接住 曜石黑/石墨黑/黑 全族;
        有货 SKU 才算数(kc.stock > 0),缺货配色不冒充现货推荐。"""
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
        if color:
            color_stem = color.rstrip("色") or color
            conditions.append(
                "EXISTS (SELECT 1 FROM merchant_skus kc WHERE kc.spu_id = s.id "
                "AND kc.stock > 0 AND kc.spec_attributes->>'颜色' ILIKE :colr)"
            )
            params["colr"] = f"%{color_stem}%"
        return conditions, params, title_hit_clause

    @staticmethod
    async def _fetch_merchant_catalog(
        terms: list[str] | None,
        category: str | None,
        max_price,
        limit: int,
        sort: str | None = None,
        color: str | None = None,
    ) -> list[dict] | None:
        """商户真货架 SQL 检索层(agent_merchant.merchant_spus/skus)。

        None=库不可达(调用方降级 engine 本地表);[]=可达查无(诚实空,
        严禁跨目录补货)。词元匹配与 ON_SALE 门槛经 `catalog_match` 单一实现
        (A8:与网关 SPI 商品检索同源);terms 为 None 是 L2 语义召回的候选池
        形态(硬过滤全量,无词元条件)。展示价=MIN(sku.price)、库存=SUM(
        sku.stock),与网关 _spu_to_product 同语义;排序 min_price ASC 与
        engine 分支 price ASC 契约一致。热销排序不做:merchant 库无销量列
        (全仓亦无 sales_volume),无数据源 —— 已文档化限制,不合成假热度。
        无 SKU 的 SPU 展示价 NULL,经 HAVING 排除(不可售,且 float(None) 会炸)。
        color 经 catalog_match 编译为 SKU spec 级 EXISTS(2026-10-01)。
        """
        conditions, params, title_hit_clause = MallDomainService.catalog_match(terms, category, color)
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
        query: str, category: str | None, max_price, limit: int, color: str | None = None
    ) -> list[dict] | None:
        """L2 语义召回补位(2026-09-11):词元 ILIKE 查空时 bge 余弦 top-k。

        返回契约与 _fetch_merchant_catalog 一致(None=能力不可用,[]=无命中)。
        候选池吃满硬过滤(status/category/maxPrice/color)但不吃词元条件;命中按
        相似度 DESC 输出 —— 语义档的价值就是相关性排序(min_price ASC 只属
        词元/浏览路径)。嵌入异常降级 None → 调用方落诚实空,绝不阻断检索。
        """
        candidates = await MallDomainService._fetch_merchant_catalog(None, category, max_price, 200, color=color)
        if candidates is None or not candidates:
            return candidates
        try:
            query_vector = await MallDomainService._embed_query(query)
            candidate_vectors = await MallDomainService._ensure_spu_embeddings(candidates)
            scored: list[tuple[float, dict]] = []
            for product, vector in zip(candidates, candidate_vectors, strict=True):
                similarity = cosine_similarity(query_vector, vector)
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
        """6. 商品检索与导购选品。sort: "price_desc" 按价格降序(「最贵的X」)。
        color:本轮说出的颜色偏好(SKU spec 级过滤,2026-10-01)—— 上游导购
        技能把「我喜欢黑色」的「黑色」显式传入,严禁只留在展示句里广告。"""
        query = params.get("query")
        sort_mode = params.get("sort")
        category = params.get("category")
        max_price = params.get("maxPrice")
        color = params.get("color")
        limit = params.get("limit") or 4
        effective_biz_id = resolve_business_id(params.get("businessId"))  # A7:显式 > 上下文 > 默认
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
                    MallDomainService._expand_stem_aliases([term]), category, max_price, limit, color=color
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
                terms, category, max_price, limit, sort=sort_mode, color=color
            )
        if merchant_products is not None:
            if not merchant_products and query and settings.mall_semantic_enabled:
                merchant_products = (
                    await MallDomainService._semantic_recall_merchant_catalog(
                        query, category, max_price, limit, color=color
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
                            MallDomainService._expand_stem_aliases(rewritten), category, max_price, limit, color=color
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
            if color:
                # 本地表无 SKU spec,颜色只能词面 best-effort(name/description);
                # 颜色语义主属商户真货架 catalog_match 的 SKU 级 EXISTS。
                conditions.append("(name ILIKE :colr OR description ILIKE :colr)")
                query_params["colr"] = f"%{color.rstrip('色') or color}%"
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
