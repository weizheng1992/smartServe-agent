"""planner 确定性快轨注册表专项(graph/nodes/planner.py,nightly #7 / Gen-3 一期③)。

七条「意图签名 → 子任务模板」if 分支收口为有序规则表 _FAST_TRACK_RULES 后,
本册钉死零行为变化:
1. 全规则命中快照 —— 每条规则至少一个代表性输入,task_plan / emit_status
   文案与注册表化前(git 旧分支字面)逐字一致;
2. 表序即优先级 —— 规则名顺序钉死;复合句压线样张证明 metric×导购票在
   guide×cart 之前、泛查单票在复合查单之后;
3. 守卫边界 —— 旧分支没有的闸(如 human_escalation 无 len==1)不得顺手补上,
   旧分支有的闸(如 metric 单意图 len==1、bestseller 四重否决)一条不少;
4. 全程打桩 emit_status / get_chat_model,零 DB、零 LLM。
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager

from engine_py.graph.nodes import planner as pl
from engine_py.graph.nodes.planner import _FAST_TRACK_RULES, planner_node


@contextmanager
def _capture_emit():
    """打桩 emit_status,捕获 (job_id, 文案, plan) 供逐字断言。"""
    events: list[tuple] = []

    async def _rec(job_id, message, **kwargs):
        events.append((job_id, message, kwargs.get("plan"), kwargs.get("node")))

    original = pl.emit_status
    pl.emit_status = _rec
    try:
        yield events
    finally:
        pl.emit_status = original


@contextmanager
def _fake_planner_llm(content: str | None = None):
    from engine_py.graph.nodes import planner as pl2

    calls: list[str] = []

    class _Bound:
        async def ainvoke(self, prompt: str):
            calls.append(prompt)
            return type("Resp", (), {"content": content})()

    class _Model:
        def bind(self, **_kwargs) -> _Bound:
            return _Bound()

    original = pl2.get_chat_model
    pl2.get_chat_model = lambda: _Model()
    try:
        yield calls
    finally:
        pl2.get_chat_model = original


def _state(**kwargs) -> dict:
    base = {
        "intents": [],
        "input": "",
        "job_id": "job-snap",
        "short_memory": [{"role": "user", "content": "你好"}],
        "thread_id": "thread-snap",
    }
    base.update(kwargs)
    return base


def _run(**kwargs) -> tuple[dict, list[tuple]]:
    with _capture_emit() as events, _fake_planner_llm("must not be called"):
        result = asyncio.run(planner_node(_state(**kwargs)))
    # 剥离前置样板进度(job_id 在场时先播「正在根据分类意图…」,旧代码亦然)
    events[:] = [e for e in events if e[1] != "正在根据分类意图，由大模型动态生成高精准子步骤执行规划..."]
    return result, events


# ---------- 注册表结构:表序即优先级 ----------


def test_注册表表序钉死():
    assert [r.name for r in _FAST_TRACK_RULES] == [
        "human_escalation",
        "metric_single",
        "metric_x_guide",
        "guide_x_cart",
        "bestseller_cart",
        "composite_order_list",
        "general_order_list",
    ]


# ---------- 全规则命中快照(plan + 进度文案逐字) ----------


def test_human_escalation_命中快照():
    result, events = _run(intents=[{"intent": "human_escalation"}], input="转人工")
    plan = {
        "goal": "Escalate conversation to human support operator",
        "subtasks": [
            {
                "id": "step_fast_human_escalation",
                "description": "Trigger human escalation and create pending approval ticket for customer support operator",
                "status": "pending",
            }
        ],
        "currentStepIndex": 0,
    }
    assert result["task_plan"] == plan
    assert result["global_transitions_count"] == 1
    assert events == [("job-snap", "⚡ 极速介入直达：检测到人工客服与熔断诉求，已物理生成人工转接步骤并推入执行链！", plan, "planner")]


def test_human_escalation_复合句不补len闸_与旧分支一致():
    # 旧分支 if single_intent == "human_escalation" 本就无 len==1 闸:
    # 复合句首位是转人工时照旧独走转接轨 —— 注册表化不得顺手"修好"它。
    result, _ = _run(
        intents=[{"intent": "human_escalation"}, {"intent": "cart_manage"}],
        input="转人工,顺便清空购物车",
    )
    assert result["task_plan"]["subtasks"][0]["id"] == "step_fast_human_escalation"


def test_metric_single_命中快照_gross_profit():
    result, events = _run(intents=[{"intent": "metric_query"}], input="最赚钱的商品排行")
    plan = {
        "goal": "Fetch real product ranking by metric",
        "subtasks": [
            {
                "id": "step_fast_ranking_0",
                "description": "Call queryProductRanking with rankingMetric gross_profit to fetch real sales ranking",
                "status": "pending",
            }
        ],
        "currentStepIndex": 0,
    }
    assert result["task_plan"] == plan
    assert events == [("job-snap", "⚡ 极速直达：识别到经营排行诉求，确定性执行 gross_profit 排行检索！", plan, "planner")]


def test_metric_x_guide_命中快照():
    result, events = _run(
        intents=[{"intent": "metric_query"}, {"intent": "shopping_guide"}],
        input="看看GMV多少,顺便推荐卖得好的",
    )
    plan = {
        "goal": "Fetch real sales metrics and shopping recommendations",
        "subtasks": [
            {
                "id": "step_fast_ranking_0",
                "description": "Call queryProductRanking with rankingMetric gmv to fetch real sales ranking",
                "status": "pending",
            },
            {
                "id": "step_fast_guide_1",
                "description": "Execute ShoppingGuideSkill for input: 看看GMV多少,顺便推荐卖得好的",
                "status": "pending",
            },
        ],
        "currentStepIndex": 0,
    }
    assert result["task_plan"] == plan
    assert events == [("job-snap", "⚡ 极速规划直达：识别到经营数据+导购复合诉求，已组装排行与导购双子任务流！", plan, "planner")]


def test_metric_x_guide_让位guide_x_cart_表序证明():
    # metric 在场但 cart 也在 → metric×导购票让位(旧闸 not has_cart_manage),
    # 命中三段接力轨 —— 同一输入只会有一条轨吃下,顺序错了就换轨。
    result, events = _run(
        intents=[{"intent": "metric_query"}, {"intent": "shopping_guide"}, {"intent": "cart_manage"}],
        input="看看GMV,推荐短袖,都要了",
    )
    assert [st["id"] for st in result["task_plan"]["subtasks"]] == ["step_fast_guide_0", "step_fast_cart_1"]
    assert events[0][1] == "⚡ 极速规划直达：识别到推荐+全量加购诉求，已组装导购与购物车双子任务流！"


def test_guide_x_cart_三段接力_结算词与句中地址():
    result, events = _run(
        intents=[{"intent": "shopping_guide"}, {"intent": "cart_manage"}],
        input="查卖得好的短袖,把第一个加入购物车,地址是上海市静安区南京西路100号,然后结算",
    )
    plan = {
        "goal": "Recommend products then add them to cart and check out",
        "subtasks": [
            {
                "id": "step_fast_guide_0",
                "description": "Execute ShoppingGuideSkill for input: "
                "查卖得好的短袖,把第一个加入购物车,地址是上海市静安区南京西路100号,然后结算",
                "status": "pending",
            },
            {
                "id": "step_fast_cart_1",
                "description": "Execute CartSkill for input: "
                "查卖得好的短袖,把第一个加入购物车,地址是上海市静安区南京西路100号,然后结算",
                "status": "pending",
            },
            {
                "id": "step_fast_checkout_2",
                "description": "Call checkoutCart to place a real order from the current cart items, "
                "shipping to 上海市静安区南京西路100号",
                "status": "pending",
            },
        ],
        "currentStepIndex": 0,
    }
    assert result["task_plan"] == plan
    assert events == [("job-snap", "⚡ 极速规划直达：识别到推荐+全量加购诉求，已组装导购与购物车双子任务流！", plan, "planner")]


def test_guide_x_cart_无结算词_两段与默认地址():
    result, events = _run(
        intents=[{"intent": "shopping_guide"}, {"intent": "cart_manage"}],
        input="推荐跑步鞋,都要了",
    )
    plan = result["task_plan"]
    assert plan["goal"] == "Recommend products then add them to cart"
    assert [st["id"] for st in plan["subtasks"]] == ["step_fast_guide_0", "step_fast_cart_1"]
    assert events[0][1] == "⚡ 极速规划直达：识别到推荐+全量加购诉求，已组装导购与购物车双子任务流！"


def test_bestseller_cart_命中快照_刻意只排CartSkill():
    result, events = _run(
        intents=[{"intent": "cart_manage"}, {"intent": "metric_query"}],
        input="销量最好的裤子来一件,直接加购",
    )
    plan = {
        "goal": "Add requested products to cart with honest shelf guidance",
        "subtasks": [
            {
                "id": "step_fast_bestseller_cart_0",
                "description": "Execute CartSkill for input: 销量最好的裤子来一件,直接加购",
                "status": "pending",
            }
        ],
        "currentStepIndex": 0,
    }
    assert result["task_plan"] == plan
    assert events == [("job-snap", "⚡ 极速规划直达：识别到销量榜加购诉求，确定性走购物车技能诚实引导！", plan, "planner")]


def test_composite_order_list_命中快照_cart半在前():
    result, events = _run(
        intents=[{"intent": "cart_manage"}, {"intent": "order_status"}],
        input="把第一件加入购物车,顺便看看我买了啥",
    )
    plan = {
        "goal": "Execute composite shopping and order query subtasks",
        "subtasks": [
            {
                "id": "step_fast_cart_0",
                "description": "Execute CartSkill for input: 把第一件加入购物车,顺便看看我买了啥",
                "status": "pending",
            },
            {"id": "step_fast_list_orders_1", "description": "Call listUserOrders to fetch recent orders", "status": "pending"},
        ],
        "currentStepIndex": 0,
    }
    assert result["task_plan"] == plan
    assert events == [("job-snap", "⚡ 极速规划直达：识别到复合诉求，已智能组装 2 项子任务流并投入执行引擎！", plan, "planner")]


def test_composite_order_list_guide半在前_泛查单不抢跑_表序证明():
    # guide 半 + order_query 泛指:复合轨(≥2 意图)先于泛查单轨吃下;
    # 若两轨换序,此输入会被单意图泛查单轨吞掉导购半。
    result, events = _run(
        intents=[{"intent": "shopping_guide"}, {"intent": "order_query"}],
        input="推荐个背包,顺便查一下我的订单",
    )
    assert [st["id"] for st in result["task_plan"]["subtasks"]] == ["step_fast_guide_0", "step_fast_list_orders_1"]
    assert events[0][1].startswith("⚡ 极速规划直达：识别到复合诉求")


def test_general_order_list_命中快照():
    result, events = _run(intents=[{"intent": "order_status"}], input="看看我买了啥")
    plan = {
        "goal": "List recent orders for customer",
        "subtasks": [
            {"id": "step_fast_list_orders", "description": "Call listUserOrders to fetch recent orders", "status": "pending"}
        ],
        "currentStepIndex": 0,
    }
    assert result["task_plan"] == plan
    assert events == [
        ("job-snap", "⚡ 极速规划直达：检测到客户订单列表查询诉求，秒级调度 listUserOrders 工具进行物理查单！", plan, "planner")
    ]


def test_general_order_list_显式单号不抢跑():
    # 旧闸保留:带显式单号不走泛查单轨,落 entity 关联组装(既有契约册钉)。
    with _capture_emit() as events, _fake_planner_llm("must not be called"):
        result = asyncio.run(
            planner_node(_state(intents=[{"intent": "order_status"}], input="ORD-98712 到哪了"))
        )
    ids = [st["id"] for st in result["task_plan"]["subtasks"]]
    assert ids == ["step_fast_status"]  # entity 快轨,非 step_fast_list_orders
    assert all(e[1] != "⚡ 极速规划直达：检测到客户订单列表查询诉求，秒级调度 listUserOrders 工具进行物理查单！" for e in events)


# ---------- 守卫边界:旧分支的否决闸一条不少 ----------


def test_metric_single_复合句不劫持_落深规划():
    # 旧 len==1 闸:metric+其他意图不进单意图排行轨(由其他轨/深规划接手)。
    with _capture_emit() as events, _fake_planner_llm("must not be called"):
        result = asyncio.run(
            planner_node(
                _state(
                    intents=[{"intent": "metric_query"}, {"intent": "order_status"}],
                    input="看看销量,顺便查订单",
                )
            )
        )
    # metric×导购票因资金动作在场让位;复合查单轨因无 guide/cart 半让位;
    # 泛查单轨因非单意图让位 → 深规划,LLM 脏输出落 per-intent 兜底步。
    assert [st["id"] for st in result["task_plan"]["subtasks"]] == ["step_0", "step_1"]
    assert all("极速" not in e[1] for e in events)


def test_bestseller_cart_四重否决_资金动作在场让位深规划():
    with _capture_emit() as events, _fake_planner_llm("must not be called"):
        asyncio.run(
            planner_node(
                _state(
                    intents=[{"intent": "cart_manage"}, {"intent": "refund", "missingSlots": ["orderId"]}],
                    input="销量最好的裤子加购,顺便退款",
                )
            )
        )
    assert all("销量榜加购" not in e[1] for e in events)


def test_general_query旁路_在注册表之前_不受影响():
    result, events = _run(intents=[{"intent": "general_query"}], input="退货政策是什么")
    assert result["task_plan"]["subtasks"][0]["id"] == "respond_general"
    assert events[0][2]["subtasks"][0]["id"] == "respond_general"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__])
