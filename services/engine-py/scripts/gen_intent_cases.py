"""生成意图评测数据集(scripts/run_intent_eval.py 的输入)。

来源三路:
1. metric_registry 每指标的 sampleQueries(应答面,期望 = 对应指标);
2. 本会话实弹沉淀的边界案例(词面冲突/趋势升级/时间槽/图型指令);
3. 长尾拒绝面(expect_unsupported:问因/闲聊等,08-P1 响亮失败)。
评测跑在确定性层(L3 关闭),L2 范例随环境可能命中 —— 命中同指标亦算过。
"""

from __future__ import annotations

import json
from pathlib import Path

from engine_py.tools_registry.metric_registry import METRIC_SEMANTIC_REGISTRY as metric_registry

CASES: list[dict] = []

# ── 1) 注册表样例问句 ──────────────────────────────────────────────
for key, m in metric_registry.items():
    for q in m.get("sampleQueries") or []:
        CASES.append({"question": q, "expect_metric": key, "source": "registry"})

# ── 2) 实弹边界案例(词面/槽位/语义规则) ──────────────────────────
EDGE: list[dict] = [
    # 词面冲突治理(同族近义跨指标排雷)
    {"question": "销量 折线图", "expect_metric": "volume_trend", "source": "edge"},
    {"question": "GMV 折线图", "expect_metric": "gmv_trend", "source": "edge"},
    {"question": "销量榜 折线图", "expect_metric": "volume", "source": "edge"},
    {"question": "AURORA-ORD-2026-1737 订单详情", "expect_metric": "order_overview", "source": "edge"},
    {"question": "上个月的销量排行", "expect_metric": "volume", "source": "edge"},
    {"question": "近30天GMV趋势", "expect_metric": "gmv_trend", "source": "edge"},
    {"question": "每天的销售额走势", "expect_metric": "gmv_trend", "source": "edge"},
    {"question": "每月销量趋势", "expect_metric": "volume_trend", "source": "edge"},
    {"question": "订单量趋势", "expect_metric": "orders_trend", "source": "edge"},
    {"question": "销量排行", "expect_metric": "volume", "source": "edge"},
    {"question": "GMV 趋势", "expect_metric": "gmv_trend", "source": "edge"},
    # 反向词
    {"question": "卖得最差的商品", "expect_metric": "gmv", "expect_direction": "ASC", "source": "edge"},
    {"question": "销量最低的商品", "expect_metric": "volume", "expect_direction": "ASC", "source": "edge"},
    # 方向
    {"question": "销量最高的商品 Top 3", "expect_metric": "volume", "expect_direction": "DESC", "source": "edge"},
    # 时间槽
    {"question": "上个月销售额排行", "expect_metric": "gmv", "expect_time": "last_month", "source": "edge"},
    {"question": "最近7天销量排行", "expect_metric": "volume", "expect_time": "last_7d", "source": "edge"},
    # 图型槽
    {"question": "库存价值排行 用表格", "expect_metric": "stock_value", "expect_chart": "table", "source": "edge"},
    {"question": "品类GMV排行", "expect_metric": "category_gmv_top", "source": "edge"},
    # 出口族
    {"question": "本月客单价多少", "expect_metric": "aov", "source": "edge"},
    {"question": "本月订单量多少", "expect_metric": "order_count", "source": "edge"},
    {"question": "好评最多的商品 Top 3", "expect_metric": "review_good", "source": "edge"},
    {"question": "零销量商品有哪些", "expect_metric": "zero_sales", "source": "edge"},
    {"question": "GMV环比", "expect_metric": "gmv_mom", "source": "edge"},
    {"question": "会话量多少", "expect_metric": "session_volume", "source": "edge"},
    {"question": "退款率最高的商品", "expect_metric": "refund_rate", "source": "edge"},
    {"question": "压货最严重的商品", "expect_metric": "stock_risk", "source": "edge"},
    # 未命中落库面(回捞曾答不上的,现已支持)
    {"question": "张伟最近的订单", "expect_metric": "customer_orders", "source": "edge"},
]
CASES.extend(EDGE)

# 注册表样例的歧义反问覆写(「卖得最好」× 多销售指标 → 设计行为是反问)
OVERRIDES = {
    "帮我查一下我负责商品里面卖得最好的几个": {"expect_clarify": True, "expect_metric": None},
    "查看走量最多的爆款商品": {"expect_clarify": True, "expect_metric": None},
    # 实体依赖型样例(需实体解析/L3):确定性评测跳过,归 L3 层
    "开学季活动里冲锋衣对比其他款": {"layer": "L3"},
    "新客50元券对比背包品类85折": {"layer": "L3"},
    "两个活动哪个效果好": {"layer": "L3"},
    "这个活动里哪款卖得最好": {"layer": "L3"},
    "张三最近的订单": {"layer": "L3"},
    "查一下 13800000001 的订单": {"layer": "L3"},
    "张伟最近的订单": {"layer": "L3"},
}
for c in CASES:
    if c["question"] in OVERRIDES:
        c.update(OVERRIDES[c["question"]])

# 实体依赖问句(需 L3/实体解析层,确定性评测跳过计数)
for q, m in [
    ("张三最近的订单", "customer_orders"),
    ("查一下 13800000001 的订单", "customer_orders"),
    ("冲锋衣88折对比背包品类85折", "promo_compare"),
    ("两个活动哪个效果好", "promo_compare"),
    ("这个活动里哪款卖得最好", "promo_sku_compare"),
]:
    CASES.append({"question": q, "expect_metric": m, "layer": "L3", "source": "entity"})

# 按问句去重(后写优先):实体层标记必须压过注册表生成的同问副本
dedup: dict[str, dict] = {}
for c in CASES:
    dedup[c["question"]] = c
CASES = list(dedup.values())

# ── 3) 长尾拒绝面(08-P1 响亮失败) ─────────────────────────────────
for q in ["今天心情如何", "帮我算算公司估值", "为什么这个月退货突然变多", "今天天气怎么样"]:
    CASES.append({"question": q, "expect_unsupported": True, "source": "longtail"})

OUT = Path(__file__).resolve().parent.parent / "evals" / "intent_cases.jsonl"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for c in CASES:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    by_source = {}
    for c in CASES:
        by_source[c["source"]] = by_source.get(c["source"], 0) + 1
    print(f"已生成 {len(CASES)} 条 → {OUT}")
    print(f"分布: {by_source}")


if __name__ == "__main__":
    main()
