"""语义意图路由(P1)— 全意图锚点例句 + 按意图阈值,影子模式起步。

与 DEFAULT_ANCHOR_PHRASES(order_status/refund/out_of_scope 三意图的既有
锚点与判定)并存:本路由覆盖其余高频档位,判定结果在影子模式(SEMANTIC
_ROUTER_MODE=shadow,默认)下只产 proposals 不接管路由 —— 误路由率经坏例
池 intent_conflict 增速验证后,再切 takeover 由 skill_fast_track 直达。
设计文档:docs/intent-routing-upgrade-plan.md。

阈值纪律:初始值人工给定,标定脚本(scripts/calibrate_semantic_routes.py)
用 nightly 矩阵/评测集问句按最优 F1 重算 —— 没有跑分,调参是盲调。
"""

from __future__ import annotations

import os

from .intent_registry import INTENT_REGISTRY
from .semantic_cache import cosine_similarity

SEMANTIC_ROUTER_ENV = "SEMANTIC_ROUTER_MODE"
MODE_OFF, MODE_SHADOW, MODE_TAKEOVER = "off", "shadow", "takeover"

DEFAULT_THRESHOLD = 0.8

# 每意图锚点例句 + 阈值。刻意排除 general_query/out_of_scope/chitchat
# (兜底类,路由到它们没有意义)与 order_status/refund(既有锚点+判定已覆盖)。
SEMANTIC_ROUTES: dict[str, dict] = {
    "shopping_guide": {
        "threshold": 0.8,
        "utterances": [
            "推荐几款连衣裙",
            "想买一双透气跑步鞋",
            "有没有适合送女朋友的礼物",
            "帮我挑一款防风外套",
            "有什么好看的新款吗",
            "哪款背包适合短途徒步",
        ],
    },
    "promotion_query": {
        "threshold": 0.78,
        "utterances": [
            "有什么优惠活动",
            "我的优惠券有哪些",
            "满减怎么算",
            "推荐优惠最大的商品",
            "叠加减的最多的商品",
            "哪款优惠力度最大",
            "优惠券怎么领取",
            "现在买东西有折扣吗",
        ],
    },
    "metric_query": {
        "threshold": 0.8,
        "utterances": [
            "上个月GMV是多少",
            "销量最好的商品是哪个",
            "看一下近7天的利润趋势",
            "哪个品类卖得最差",
            "各商品的销售额排行",
            "这个月卖了多少",
            "毛利率表现怎么样",
        ],
    },
    "cart_manage": {
        "threshold": 0.8,
        "utterances": [
            "加入购物车",
            "把第2件加入购物车",
            "查看我的购物车",
            "去结算",
            "清空购物车",
            "把购物车里的数量改成3",
        ],
    },
    "order_query": {
        "threshold": 0.82,
        "utterances": [
            "查一下我的订单",
            "看看我买过的东西",
            "我的订单列表",
            "名下订单有哪些",
            "帮我查我所有的订单",
        ],
    },
    "order_modify_address": {
        "threshold": 0.82,
        "utterances": [
            "帮我修改收货地址",
            "订单地址写错了",
            "发货前能修改收货地址吗",
            "把这个订单的收货地址改一下",
            "收货地址填错了怎么办",
        ],
    },
    "order_cancel": {
        "threshold": 0.82,
        "utterances": [
            "取消订单",
            "刚才的订单不要了帮我取消",
            "取消还没发货的订单",
            "我不想要了帮我退单",
            "这个订单帮我取消了",
        ],
    },
    "address_manage": {
        "threshold": 0.82,
        "utterances": [
            "新建一个收货地址",
            "查看我的地址簿",
            "我的地址列表有哪些",
            "帮我添加一个收货地址",
            "把我家的地址保存到地址簿",
        ],
    },
    "consult": {
        "threshold": 0.8,
        "utterances": [
            "退货政策是什么",
            "尺码怎么选",
            "运费多少",
            "支持七天无理由退货吗",
            "下单后多久能发货",
            "怎么开发票",
        ],
    },
    "human_escalation": {
        "threshold": 0.85,
        "utterances": [
            "转人工",
            "找人工客服",
            "我要投诉",
            "请转接人工客服",
            "人工客服在吗",
        ],
    },
}


def get_semantic_router_mode() -> str:
    """off=完全关闭;shadow=只产提议不接管路由(默认);takeover=预留。"""
    mode = os.environ.get(SEMANTIC_ROUTER_ENV, MODE_SHADOW).strip().lower()
    return mode if mode in (MODE_OFF, MODE_SHADOW, MODE_TAKEOVER) else MODE_SHADOW


class SemanticIntentRouter:
    """全意图锚点向量缓存 + 逐意图阈值取最优路由。"""

    _route_vectors: dict[str, list[list[float]]] | None = None

    @classmethod
    async def get_route_vectors(cls) -> dict[str, list[list[float]]]:
        if cls._route_vectors is not None:
            return cls._route_vectors
        from ..llm import get_embedding_model

        texts: list[str] = []
        spans: dict[str, tuple[int, int]] = {}
        for intent, cfg in SEMANTIC_ROUTES.items():
            start = len(texts)
            texts.extend(cfg["utterances"])
            spans[intent] = (start, len(texts))
        all_vectors = await get_embedding_model().aembed_documents(texts)
        cls._route_vectors = {
            intent: list(all_vectors[start:end]) for intent, (start, end) in spans.items()
        }
        return cls._route_vectors

    @classmethod
    async def route_best(cls, user_vector: list[float]) -> tuple[str, float] | None:
        """逐意图取锚点最高余弦,超该意图阈值者中取全局最优;无命中返回 None。"""
        vectors = await cls.get_route_vectors()
        best: tuple[str, float] | None = None
        for intent, cfg in SEMANTIC_ROUTES.items():
            threshold = float(cfg.get("threshold", DEFAULT_THRESHOLD))
            intent_best = max(
                (
                    cosine_similarity(user_vector, vector)
                    for vector in vectors.get(intent, [])
                ),
                default=0.0,
            )
            if intent_best >= threshold and (best is None or intent_best > best[1]):
                best = (intent, intent_best)
        return best


def route_best_intent(user_vector: list[float]) -> tuple[str, float] | None:
    """同步封装:向量缓存已热时同步取最优路由(影子接线用,失败让位)。"""
    router_vectors = SemanticIntentRouter._route_vectors
    if router_vectors is None:
        return None
    best: tuple[str, float] | None = None
    for intent, cfg in SEMANTIC_ROUTES.items():
        threshold = float(cfg.get("threshold", DEFAULT_THRESHOLD))
        intent_best = max(
            (cosine_similarity(user_vector, v) for v in router_vectors.get(intent, [])),
            default=0.0,
        )
        if intent_best >= threshold and (best is None or intent_best > best[1]):
            best = (intent, intent_best)
    return best


def validate_routes() -> list[str]:
    """配置完整性自检(测试与标定脚本共用):档位必须在注册表、阈值在
    [0.7,0.95]、例句≥5 条且跨路由无重复。"""
    problems: list[str] = []
    seen: set[str] = set()
    for intent, cfg in SEMANTIC_ROUTES.items():
        if intent not in INTENT_REGISTRY:
            problems.append(f"{intent}: 未登记于意图注册表")
        threshold = float(cfg.get("threshold", DEFAULT_THRESHOLD))
        if not 0.7 <= threshold <= 0.95:
            problems.append(f"{intent}: 阈值 {threshold} 超出 [0.7,0.95]")
        utterances = cfg.get("utterances") or []
        if len(utterances) < 5:
            problems.append(f"{intent}: 例句不足 5 条")
        for u in utterances:
            if u in seen:
                problems.append(f"{intent}: 例句跨路由重复「{u}」")
            seen.add(u)
    return problems
