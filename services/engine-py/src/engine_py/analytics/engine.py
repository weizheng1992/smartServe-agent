"""L0 同义词归一 + MetricQueryEngine 深模块(09-D5 接口冻结;08-D1 路线)。

resolve:问句 → StructuredQueryIntent(闭集标签) | Clarify(反问;2026-10-03 一等公民);
未命中抛 UnsupportedQuery —— 08-P1:废除静默兜底 gmv。
compile:意图 → CompiledSQL(fragment 闭集 + bindparams;business_id 服务端注入;
LIMIT clamp 1-50;sql_guard 校验后 AST 断言)。
execute:CompiledSQL → QueryResult(只读 reader 引擎;诚实空)。

LLM 的位置在 L3(未来 adapter,接口同 resolve);本模块词面层零 LLM 调用。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from . import chart_policy
from .schema_cards import compile_safe_schema_card
from .sql_guard import UnsafeSqlError, assert_safe_select
from .tools_registry_bridge import metric_semantic_registry, valid_dealing_where

_CALIBERS = {
    "review_bad": "差评口径 = rating ≤ 2(商户真实评价)",
    "refund_rate": "退款率 = 退款件 ÷ (有效+退款)件 × 100;CANCELLED 不计分母",
    "session_volume": "会话量 = session_metrics 计数(与平台大盘同源)",
    "ai_resolution_rate": "AI 解决率 = resolved_auto ÷ 总会话 × 100(session_metrics 同源)",
    "after_sale_overview": "售后工单按状态分布计数(after_sale_tickets 真算)",
    "order_overview": "对页面勾选订单逐笔展示(订单号/状态/金额/时间),合计与均值随行列出,便于两单对比",
    "promo_effect": "活动口径 = 核销记录关联订单(真实归因;自然流量不计入),GMV 为核销订单实付合计",
    "promo_gmv_total": "活动口径 = 核销记录关联订单(真实归因;自然流量不计入),GMV 为核销订单实付合计",
    "promo_sku_compare": "活动内对比 = 该活动核销订单的商品明细聚合;目标款在「对比分组」列标记",
    "customer_orders": "客户订单 = 名下全部订单按下单时间倒序",
    "promo_compare": "双活动对比 = 各自核销记录关联订单聚合(真实归因;自然流量不计入)",
}


class UnsupportedQuery(Exception):
    """问句落在已注册指标空间之外(响亮失败,呈现层给可选问法)。"""


class EntityGateRequired(UnsupportedQuery):
    """编译期实体闸(2026-10-03 类型化):「补一句话即可继续」的可行动引导,
    与「该指标暂未开放」的真不支持语义分家。

    此前 six 处闸(勾选订单/勾选商品/指明活动×2/指明客户/双活动对比)与
    真不支持共用 UnsupportedQuery,呈现层只能靠嗅探异常消息词面(「勾选」)
    决定透传还是替换 generic 文案 —— 另外 4 处引导被吞成「该指标暂未开放」,
    商户明明补一句话就能继续查。hint 携带完整用户文案;str(err) == hint,
    场景包等既有 str(err) 消费点零改写。子类化保证所有 except UnsupportedQuery
    行为不变(场景包 _run_scenario / llm_intent 兜底层)。
    """

    def __init__(self, hint: str) -> None:
        self.hint = hint
        super().__init__(hint)


@dataclass(frozen=True)
class StructuredQueryIntent:
    metric: str
    direction: str = "DESC"
    limit: int = 5
    time_window: dict | None = None
    category: str | None = None
    entity_ids: list[str] = field(default_factory=list)  # PageContext 选中实体(IN 绑定)
    chart_hint: str | None = None  # 用户指定图型(line/bar/table);缺省由卡片层自动推断
    # 命名实体槽(ADR-0005):LLM/L2 解析后的实体 ID 集合,如
    # {"promotion": ["<uuid>"], "customer": ["CUST-8801"], "spu": ["AURORA-SPU-1"]}
    entity_slot: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class Clarify:
    """解析缝一等公民(2026-10-03):「落在闭集内但缺实体/指标待选」的反问结果
    与 Intent 同为 resolve 的合法返回,取代裸 dict + isinstance 嗅探。

    kind: metric=词面泛指需选指标(conflictGroup)/entity=实体需点选;
    to_frame 产出 SSE 帧形状 —— 旧帧里的死键 "clarify": True 无任何消费方
    (前端只读 clarifyKind/options),归一时删除;metric 帧补 clarifyKind
    (加法,无害)。originalQuestion 供实体点选后回问原句。"""

    kind: str  # "metric" | "entity"
    question: str
    options: list[dict]
    original_question: str | None = None

    def to_frame(self) -> dict:
        frame = {"type": "clarify", "clarifyKind": self.kind, "question": self.question, "options": self.options}
        if self.original_question:
            frame["originalQuestion"] = self.original_question
        return frame


@dataclass
class QueryResult:
    rows: list[dict]
    metric: str
    unit: str
    caliber: str  # 口径注记(呈现层展示;数据诚实铁律)
    source: str = "metric_template"
    chart: str | None = None  # line=折线(时间序列);None=默认表格
    # 机器语义走字段,不靠解析展示串(2026-10-03:trace 归类曾从 caliber 词面
    # 抠「缓存读」,文案一改 trace 静默变脸;口径注记本身原样保留给商户看)
    from_cache: bool = False


class MetricQueryEngine:
    """09-D5 冻结接口。session_ctx 由调用方传入(business_id/role);本模块内
    business_id 只进绑定参数,不拼接 SQL 文本。"""

    def __init__(self, session_ctx: dict | None = None, resolver: Any | None = None) -> None:
        self.session_ctx = session_ctx or {}
        self._resolver = resolver  # 注入式 resolver(测试/显式 adapter;换整个 L0 的缝)

    # ---------------- resolve(L0 词面归一;2026-10-03 归位 l0_lexicon) ----------------
    def resolve(self, question: str, session_ctx: dict | None = None) -> StructuredQueryIntent | Clarify:
        """冻结接口 09-D5:词表/槽位/图表指令/缝②分类头在 l0_lexicon 独居
        (与 L2/L3 同粒度);本方法只保留注入式 resolver 缝(训练产物优先)。"""
        if self._resolver is not None:
            return self._resolver(question)
        from .l0_lexicon import resolve_question

        return resolve_question(question)

    # ---------------- compile(声明编译优先;LLM 不参与) ----------------
    def compile(self, intent: StructuredQueryIntent | dict, session_ctx: dict | None = None) -> Any:
        ctx = {**self.session_ctx, **(session_ctx or {})}
        business_id = ctx.get("business_id")
        if not business_id:
            raise ValueError("session_ctx.business_id 必传(租户谓词服务端注入,不可缺席)")

        # ADR-0010 T0:声明编译优先 —— metrics.yaml 有 compile 块的指标走语义
        # 编译器(join/维度来自 semantic_model.yaml,度量/HAVING 口径来自声明);
        # 规整族已全量迁移(差分对拍 test_semantic_compiler 逐字一致后拆除
        # legacy 模板体);逃生舱债务指标(semantic_model.yaml bespoke_debt)
        # 走 _compile_bespoke_family 手写模板。business_id 语义不变:只进绑定
        # 参数,不拼接 SQL 文本。
        from .semantic_compiler import can_compile, compile_metric

        if can_compile(intent.metric):
            return compile_metric(intent, business_id)
        return self._compile_bespoke_family(intent, business_id)

    def _compile_bespoke_family(self, intent: StructuredQueryIntent, business_id: str) -> CompiledSQL:
        """逃生舱债务族(semantic_model.yaml bespoke_debt 登记的 13 指标):
        声明模型暂不表达的 bespoke 形态(逐笔行/双实体对比/双期归因/反连接…)
        暂留手写模板,消灭计划见债务清单。新指标严禁再进本方法 —— 走声明编译。

        闭集 fragment + bindparams;必填实体缺失抛 EntityGateRequired;
        未登记指标响亮 Unsupported。全部商户库路由(单部署单库,02 号票实证)。
        """
        direction = intent.direction
        params: dict[str, Any] = {"lim": intent.limit}
        time_clause = ""

        if intent.metric == "order_overview":
            # ADR-0005:升级为逐笔行 + 合计/均值窗口列 —— 「两个订单对比」等
            # 对比类问法可直接看每单差异;实体来自 PageContext 勾选(必传)。
            params.pop("lim", None)  # 逐笔展示无 LIMIT 槽位,显式 50 行双保险
            if not intent.entity_ids:
                raise EntityGateRequired("请先在订单列表勾选订单,或直接在问句里写订单号(如 AURORA-ORD-2026-1737)")
            sql = (
                'SELECT o.order_id AS "订单号", o.status AS "状态", '
                'o.total_amount::float AS "金额", '
                "to_char(o.created_at, 'MM-DD HH24:MI') AS \"created_at\", "
                'ROUND(SUM(o.total_amount) OVER (), 2)::float AS "合计金额", '
                'ROUND(AVG(o.total_amount) OVER (), 2)::float AS "平均金额" '
                'FROM merchant_orders o WHERE o.order_id = ANY(:entities) '
                'ORDER BY o.created_at DESC LIMIT 50'
            )
            params["entities"] = list(intent.entity_ids)[:100]
        elif intent.metric == "promo_compare":
            # ADR-0005 登记流水线首批:双活动并排对比(核销关联口径)
            params.pop("lim", None)  # 并排两行无 LIMIT 槽位
            promo_ids = (intent.entity_slot or {}).get("promotion") or []
            if len(promo_ids) < 2:
                raise EntityGateRequired("请指明两个活动,如「活动A 对比 活动B」")
            params["entities"] = promo_ids[:10]
            sql = (
                'SELECT p.name AS "活动", '
                'COUNT(DISTINCT r.order_id) AS "核销订单数", '
                'COALESCE(SUM(o.total_amount), 0)::float AS "核销GMV", '
                'COALESCE(SUM(r.discount_amount), 0)::float AS "优惠总额" '
                'FROM promotion_redemptions r '
                'JOIN promotions p ON p.id = r.promotion_id '
                'JOIN merchant_orders o ON o.order_id = r.order_id '
                'WHERE p.id = ANY(:entities) '
                'GROUP BY p.name, p.id ORDER BY "核销GMV" DESC'
            )
        elif intent.metric == "promo_effect":
            # ADR-0005 活动效果总览(核销关联口径:真实归因,自然流量不计入)
            params.pop("lim", None)
            promo_ids = (intent.entity_slot or {}).get("promotion") or []
            if not promo_ids:
                raise EntityGateRequired("请先指明活动(如「开学季活动卖得怎么样」)")
            if intent.time_window:
                time_clause = "AND r.created_at >= :window_start"
                params["window_start"] = window_start(intent.time_window)
            params["entities"] = promo_ids[:20]
            sql = (
                'SELECT COUNT(DISTINCT r.order_id) AS "核销订单数", '
                'COALESCE(SUM(o.total_amount), 0)::float AS "核销GMV", '
                'COALESCE(SUM(r.discount_amount), 0)::float AS "优惠总额" '
                'FROM promotion_redemptions r JOIN merchant_orders o ON o.order_id = r.order_id '
                'WHERE r.promotion_id = ANY(:entities) {time_clause}'
            )
            sql = sql.format(time_clause=time_clause)
        elif intent.metric == "promo_sku_compare":
            # ADR-0005 活动内商品对比:核销订单的商品明细按款聚合;可标目标款
            promo_ids = (intent.entity_slot or {}).get("promotion") or []
            if not promo_ids:
                raise EntityGateRequired("请先指明活动(如「开学季活动里冲锋衣对比其他款」)")
            params["entities"] = promo_ids[:20]
            params["targets"] = (intent.entity_slot or {}).get("spu") or []
            sql = (
                'SELECT oi.spu_id AS "productId", MAX(oi.title) AS "name", '
                'SUM(oi.quantity)::int AS "销量", '
                'COALESCE(SUM(oi.quantity * oi.price), 0)::float AS "GMV", '
                'COUNT(DISTINCT o.order_id)::int AS "订单数", '
                "MAX(CASE WHEN oi.spu_id = ANY(:targets) THEN '目标款' ELSE '其他款' END) AS \"对比分组\" "
                'FROM promotion_redemptions r '
                'JOIN merchant_orders o ON o.order_id = r.order_id '
                'JOIN merchant_order_items oi ON oi.order_id = r.order_id '
                'WHERE r.promotion_id = ANY(:entities) '
                f'GROUP BY oi.spu_id ORDER BY "销量" {direction} LIMIT :lim'
            )
        elif intent.metric == "customer_orders":
            # ADR-0005 客户订单列表(实体列表卡;前端订单行可跳订单管理)
            cust_ids = (intent.entity_slot or {}).get("customer") or []
            if not cust_ids:
                raise EntityGateRequired("请先指明客户(如「张三最近的订单」)")
            params["entities"] = cust_ids[:20]
            sql = (
                'SELECT o.order_id AS "order_id", o.status AS "status", '
                'o.total_amount::float AS "total_amount", '
                "to_char(o.created_at, 'MM-DD HH24:MI') AS \"created_at\" "
                'FROM merchant_orders o WHERE o.customer_id = ANY(:entities) '
                'ORDER BY o.created_at DESC LIMIT :lim'
            )
        elif intent.metric == "zero_sales":
            # 零销量在售款(NOT EXISTS 确定性判零),库存降序暴露压货交叉风险
            sql = (
                'SELECT s.title AS "productId", s.category AS "category", '
                'COALESCE(SUM(k.stock), 0)::int AS "metricScore" '
                "FROM merchant_spus s LEFT JOIN merchant_skus k ON k.spu_id = s.id "
                "WHERE s.status = 'ON_SALE' AND NOT EXISTS ("
                "SELECT 1 FROM merchant_order_items oi WHERE oi.spu_id = s.spu_code) "
                f'GROUP BY s.id, s.title, s.category ORDER BY "metricScore" {direction} LIMIT :lim'
            )
        elif intent.metric in ("attribution_refund", "attribution_sales"):
            # 归因族(雾区启动):确定性环比分解 —— 本月 vs 上月按商品列 Top 变动
            # 贡献者;只呈现算得的差异,不猜测原因(08-D1:LLM/模板都不编叙事)
            params.pop("lim", None)
            if intent.metric == "attribution_refund":
                cur_expr = "COUNT(DISTINCT o.order_id)"
                status_clause = "AND o.status = 'REFUNDED'"
                label = "退货变化"
            else:
                cur_expr = "COALESCE(SUM(oi.quantity * oi.price), 0)"
                status_clause = f"AND {valid_dealing_where('o')}"
                label = "销售变化"
            sql = (
                "WITH cur AS ("
                "SELECT oi.spu_id AS spu, " + cur_expr + "::float AS v "
                "FROM merchant_orders o JOIN merchant_order_items oi ON oi.order_id = o.order_id "
                "WHERE o.created_at >= date_trunc('month', CURRENT_DATE) " + status_clause + " "
                "GROUP BY oi.spu_id), "
                "prev AS ("
                "SELECT oi.spu_id AS spu, " + cur_expr + "::float AS v "
                "FROM merchant_orders o JOIN merchant_order_items oi ON oi.order_id = o.order_id "
                "WHERE o.created_at >= date_trunc('month', CURRENT_DATE) - INTERVAL '1 month' "
                "AND o.created_at < date_trunc('month', CURRENT_DATE) " + status_clause + " "
                "GROUP BY oi.spu_id) "
                "SELECT COALESCE(s.title, c.spu) AS \"" + label + "商品\", "
                "COALESCE(c.v, 0)::float AS \"本月\", "
                "COALESCE(p.v, 0)::float AS \"上月\", "
                "(COALESCE(c.v, 0) - COALESCE(p.v, 0))::float AS \"变化\" "
                "FROM cur c FULL OUTER JOIN prev p ON p.spu = c.spu "
                "LEFT JOIN merchant_spus s ON s.spu_code = COALESCE(c.spu, p.spu) "
                "ORDER BY ABS(COALESCE(c.v, 0) - COALESCE(p.v, 0)) DESC LIMIT 50"
            )
        elif intent.metric == "spu_compare":
            # 商品销售对比(T5 勾选的自然延伸):勾选 ≥2 款并排出销量/GMV/订单数
            spu_ids = (intent.entity_slot or {}).get("spu") or intent.entity_ids or []
            if len(spu_ids) < 2:
                raise EntityGateRequired("请在商品列表勾选至少两个商品,再问对比(如「两个商品销售对比」)")
            params.pop("lim", None)
            params["entities"] = spu_ids[:20]
            sql = (
                'SELECT s.title AS "商品", s.category AS "品类", '
                'COALESCE(SUM(oi.quantity), 0)::int AS "销量", '
                'COALESCE(SUM(oi.quantity * oi.price), 0)::float AS "GMV", '
                'COUNT(DISTINCT o.order_id)::int AS "订单数" '
                "FROM merchant_spus s "
                "LEFT JOIN merchant_order_items oi ON oi.spu_id = s.spu_code "
                "LEFT JOIN merchant_orders o ON o.order_id = oi.order_id "
                f"AND {valid_dealing_where('o')} "
                "WHERE s.spu_code = ANY(:entities) "
                "GROUP BY s.id, s.title, s.category "
                'ORDER BY "GMV" DESC LIMIT 20'
            )
        elif intent.metric == "customer_spend_stats":
            # 客户消费统计(阶段⑦客户族):客户实体必传,宽表单行
            params.pop("lim", None)
            params["entities"] = (intent.entity_slot or {}).get("customer") or []
            sql = (
                'SELECT c.name AS "客户", c.member_level AS "会员级", '
                'COUNT(DISTINCT o.order_id)::int AS "订单数", '
                'COALESCE(SUM(o.total_amount), 0)::float AS "累计消费", '
                'ROUND(COALESCE(AVG(o.total_amount), 0), 2)::float AS "客单价", '
                "to_char(MAX(o.created_at), 'MM-DD HH24:MI') AS \"最近下单\" "
                "FROM merchant_customers c "
                "LEFT JOIN merchant_orders o ON o.customer_id = c.customer_id "
                f"AND {valid_dealing_where('o')} "
                "WHERE c.customer_id = ANY(:entities) "
                "GROUP BY c.customer_id, c.name, c.member_level LIMIT 1"
            )
        elif intent.metric == "customer_coupons":
            params["entities"] = (intent.entity_slot or {}).get("customer") or []
            sql = (
                'SELECT p.name AS "券名", p.discount_value::float AS "面额折扣", '
                "CASE uc.status WHEN 'used' THEN '已用' ELSE '未用' END AS \"状态\", "
                "to_char(uc.claimed_at, 'MM-DD') AS \"领取\", "
                "to_char(uc.used_at, 'MM-DD') AS \"核销\" "
                "FROM user_coupons uc JOIN promotions p ON p.id = uc.promotion_id "
                "WHERE uc.user_id = ANY(:entities) "
                'ORDER BY uc.claimed_at DESC LIMIT :lim'
            )
        elif intent.metric == "customer_profile":
            # 用户画像:宽表单行;最爱品类/券计数为子查询(确定性,无 LLM 参与)
            params.pop("lim", None)
            params["entities"] = (intent.entity_slot or {}).get("customer") or []
            sql = (
                'SELECT c.name AS "客户", c.member_level AS "会员级", '
                "to_char(c.created_at, 'YYYY-MM-DD') AS \"注册时间\", "
                'COALESCE(SUM(o.total_amount), 0)::float AS "累计消费", '
                'COUNT(DISTINCT o.order_id)::int AS "订单数", '
                'ROUND(COALESCE(AVG(o.total_amount), 0), 2)::float AS "客单价", '
                "to_char(MAX(o.created_at), 'MM-DD HH24:MI') AS \"最近下单\", "
                '(SELECT s.category FROM merchant_orders o2 '
                "JOIN merchant_order_items oi ON oi.order_id = o2.order_id "
                "JOIN merchant_spus s ON s.spu_code = oi.spu_id "
                "WHERE o2.customer_id = c.customer_id "
                f"AND {valid_dealing_where('o2')} "
                'GROUP BY s.category ORDER BY SUM(oi.quantity * oi.price) DESC LIMIT 1) AS "最爱品类", '
                '(SELECT COUNT(*) FROM user_coupons uc WHERE uc.user_id = c.customer_id)::int AS "领券数", '
                "(SELECT COUNT(*) FROM user_coupons uc WHERE uc.user_id = c.customer_id "
                "AND uc.status = 'used')::int AS \"用券数\" "
                "FROM merchant_customers c "
                "LEFT JOIN merchant_orders o ON o.customer_id = c.customer_id "
                f"AND {valid_dealing_where('o')} "
                "WHERE c.customer_id = ANY(:entities) "
                "GROUP BY c.customer_id, c.name, c.member_level, c.created_at LIMIT 1"
            )
        elif intent.metric == "gmv_mom":
            # 环比:本月 vs 上月(自然月对齐);两侧 UNION 各算一期,SUM 折叠成单行;
            # 上月为 0 → 环比置空(不编造)
            params.pop("lim", None)
            sql = (
                'SELECT SUM(t.cur)::float AS "本月GMV", SUM(t.prev)::float AS "上月GMV", '
                'ROUND(CASE WHEN SUM(t.prev) > 0 THEN ((SUM(t.cur) - SUM(t.prev)) * 100.0 / SUM(t.prev))::numeric END, 1)::float AS "环比%" '
                "FROM ("
                "(SELECT COALESCE(SUM(oi.quantity * oi.price), 0)::float AS cur, "
                "0.0::float AS prev FROM merchant_orders o "
                "JOIN merchant_order_items oi ON oi.order_id = o.order_id "
                f"WHERE {valid_dealing_where('o')} "
                "AND o.created_at >= date_trunc('month', CURRENT_DATE)) "
                "UNION ALL "
                "(SELECT 0.0::float AS cur, "
                "COALESCE(SUM(oi.quantity * oi.price), 0)::float AS prev FROM merchant_orders o "
                "JOIN merchant_order_items oi ON oi.order_id = o.order_id "
                f"WHERE {valid_dealing_where('o')} "
                "AND o.created_at >= date_trunc('month', CURRENT_DATE) - INTERVAL '1 month' "
                "AND o.created_at < date_trunc('month', CURRENT_DATE))"
                ") t LIMIT 1"
            )
        else:
            raise UnsupportedQuery(f"指标 {intent.metric} 尚未登记执行模板")

        # 安全闸补齐(review 修复):special-family 与销售族同闸 —— AST 白名单
        # (联合卡表单点)+ 危险函数黑名单;含 business_id 的模板(会话/售后)
        # 同时断言租户谓词不可剥离。响亮失败,绝不带病执行。
        try:
            ast = assert_safe_select(sql, compile_safe_schema_card(), require_business_id="business_id" in sql)
        except UnsafeSqlError as err:
            raise ValueError(f"编译模板未过安全闸(模板缺陷,非用户问题): {err}") from err

        return CompiledSQL(
            sql=sql,
            params=params,
            metric=intent.metric,
            unit=metric_semantic_registry()[intent.metric]["unit"],
            ast=ast,
            chart_hint=intent.chart_hint,
            target_db="merchant_db",
        )

    async def execute_async(self, compiled: Any, session_ctx: dict | None = None) -> QueryResult:
        """异步执行(LangGraph 节点主路径);按 target_db 路由执行位。

        merchant_db → 只读 reader(READ ONLY + 超时,阶段①);engine_db → 引擎
        本地会话(get_session,同样只读查询)。两路均诚实空、均带口径注记。
        结果语义缓存(AI_RESULT_CACHE_TTL 秒,默认关):键 = SQL+参数哈希,
        命中秒回且口径注明缓存 —— 数据仍属同一只读快照语义,非编造。
        """
        import time

        from sqlalchemy import text

        ttl = float(os.environ.get("AI_RESULT_CACHE_TTL", "0") or 0)
        cache_key = None
        if ttl > 0:
            from . import result_cache

            cache_key = result_cache.build_key(
                compiled.sql, compiled.params, chart_hint=compiled.chart_hint,
                scope=(self.session_ctx or {}).get("business_id"),
            )
            cached = await result_cache.get(cache_key)
            if cached is not None:
                age = max(int(time.time() - cached["ts"]), 0)
                caliber = _CALIBERS.get(compiled.metric, "有效订单聚合(排除退款/取消单)")
                # chart 与执行路同公式(仅指标语义 auto):严禁吃 chart_hint —— 非趋势
                # 指标带 line 指令时预污染 result.chart,会把 chart_policy.decide
                # 的「折线仅趋势族」仲裁架空成透传(2026-09-25 折线事故在缓存
                # AI_RESULT_CACHE_TTL>0 时复发的通路)
                return QueryResult(
                    rows=cached["rows"], metric=compiled.metric,
                    unit=metric_semantic_registry()[compiled.metric]["unit"],
                    caliber=f"{caliber}(缓存读,数据时刻 ≈{age}s 前)",
                    chart=chart_policy.auto_chart(compiled.metric),
                    from_cache=True,
                )

        if getattr(compiled, "target_db", "merchant_db") == "engine_db":
            from ..db import get_session

            async with get_session() as session:
                rows = (await session.execute(text(compiled.sql).bindparams(**compiled.params))).mappings().all()
        else:
            from ..tools_registry import order_domain

            # 公开访问器 + 运行时读取模块属性(测试替换 reader 工厂,静态引用会绕过 patch;
            # 访问器 call-time 委托私有位,既有对私有工厂的 patch 照常生效)
            async with order_domain.merchant_reader_engine().connect() as conn:
                rows = (await conn.execute(text(compiled.sql).bindparams(**compiled.params))).mappings().all()
        if cache_key and ttl > 0:
            from . import result_cache

            await result_cache.set(
                cache_key,
                {"rows": [dict(r) for r in rows], "ts": time.time()},
                int(ttl),
            )
        caliber = _CALIBERS.get(compiled.metric, "有效订单聚合(排除退款/取消单)")
        chart = chart_policy.auto_chart(compiled.metric)
        return QueryResult(
            rows=[dict(r) for r in rows],
            metric=compiled.metric,
            unit=compiled.unit,
            caliber=caliber,
            chart=chart,
        )

    def execute(self, compiled: Any, session_ctx: dict | None = None) -> QueryResult:
        """同步包装(脚本/评测用);已在事件循环内请用 execute_async。"""
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.execute_async(compiled, session_ctx))
        raise RuntimeError("execute() 不能在事件循环内调用;请 await execute_async()")

def window_start(window: dict, now: datetime | None = None) -> datetime:
    """相对时间窗下界(公共纯函数,2026-10-03 自私有方法归位为可直测面):
    kind ∈ last_month/last_7d/last_30d/last_months。

    窗口下界必须与库钟同源(UTC):created_at 由 server_default now() 落
    naive UTC,本地 naive now 在非 UTC 部署下让所有相对时间窗整体偏移
    时区(2026-09-29 夜审 F15 波及复核);月对齐分支与
    date_trunc('month', CURRENT_DATE)(UTC 月界)同口径。
    """
    kind = window.get("kind")
    now = now or datetime.now(UTC).replace(tzinfo=None)
    if kind == "last_month":
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return (first - timedelta(days=1)).replace(day=1)
    if kind == "last_7d":
        return now - timedelta(days=7)
    if kind == "last_30d":
        return now - timedelta(days=30)
    if kind == "last_months":
        # 含当月共 n 个月 → 起点 = n-1 个月前的月初(月对齐)
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month = first
        for _ in range(max(int(window.get("n") or 6), 1) - 1):
            month = (month - timedelta(days=1)).replace(day=1)
        return month
    raise UnsupportedQuery(f"未知时间窗 {kind}")


@dataclass(frozen=True)
class CompiledSQL:
    sql: str
    params: dict
    metric: str
    unit: str
    chart_hint: str | None = None  # 用户图型指令(缓存键组成部分,命中重建不丢)
    target_db: str = "merchant_db"  # merchant_db | engine_db(阶段③数据源路由)
    ast: Any = field(default=None, repr=False, compare=False)
    _schema_card: Any = field(default=None, repr=False, compare=False)
