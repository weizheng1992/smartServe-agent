"""加购幻影 Nike 回归(2026-09-12)—— 图路径候选上下文死写 + 假货兜底拆除。

事故链(红灯实证 /tmp/repro_cart_bug.py):「卖的好的短袖」不含快轨触发词 →
走 structured_llm 图路径,planner 给 executor 的是 searchProducts 工具而非
ShoppingGuideSkill;工具路径不写 guide_context,且 executor_node 只回传
task_plan/short_memory/global_transitions_count/tool_errors_count 四键,
_execute_single_step_core 里对 state 的直接赋值是死写 —— 上一轮导购的
stale 候选(09-11 旧 mock 三件套)经 run_agent 收口原样存回 TaskMemory。
下一轮「把第一件加入购物车」序数解析到 stale[0]=Pegasus,幻影 Nike 入车。

修复三件:
  A. 触发词补「卖得好/卖的好」(slot_extractor SHOPPING_GUIDE + guide_skills
     _FALLBACK_RE 同源)—— 该措辞族回快轨,ShoppingGuideSkill 刷新候选;
  B. 图路径确定性守卫:searchProducts 工具结果非空即登记 guide_context,且
     guideContext 经返回值上行(executor_node 写入图状态);
  C. CartManageSkill 候选全解析失败时诚实反问,拆除 Pegasus/AJ1 硬编码兜底。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.graph.nodes import executor as executor_module
from engine_py.graph.nodes import step_execution_engine
from engine_py.skills.cart_manage_skill import CartManageSkill
from engine_py.skills.guide_skills import ShoppingGuideSkill
from engine_py.tools_registry.mall_domain import MallDomainService
from engine_py.triage.slot_extractor import SlotExtractor

STALE_GUIDE_CONTEXT = {
    "lastSearchQuery": "推荐背包热销",
    "candidateProducts": [
        {"id": "prod_nike_air_pegasus_41", "name": "Nike Air Zoom Pegasus 41 极速轻量透气跑鞋", "price": 899.0, "stock": 58},
        {"id": "prod_nike_invincible_3", "name": "Nike ZoomX Invincible Run 3", "price": 1299.0, "stock": 22},
    ],
    "candidateProductIds": ["prod_nike_air_pegasus_41", "prod_nike_invincible_3"],
    "clarificationRound": 2,
    "extractedPreferences": {},
}

FRESH_TOOL_PRODUCTS = [
    {
        "id": "SPU-T-SHIRT-1",
        "name": "极光 320g 重磅精梳纯棉复古印花短袖T恤",
        "price": 269.0,
        "stock": 345,
        "description": "高支高密 | 领口不变形",
        "specs": {"克重": "320g"},
        "imageUrl": "https://img.test/tshirt.png",
    },
    {
        "id": "SPU-T-SHIRT-2",
        "name": "极光 17.5微米美利奴羊毛天然温控短袖T恤",
        "price": 399.0,
        "stock": 287,
        "description": "天然温控 | 亲肤",
        "specs": {},
        "imageUrl": "https://img.test/tshirt2.png",
    },
]


# --------------------------------------------------------------- Fix A:触发词


@pytest.mark.parametrize("phrase", ["卖的好的短袖", "有什么卖得好的", "卖的好"])
def test_colloquial_hot_phrase_routes_to_guide(phrase: str):
    """口语热度措辞必须命中 SHOPPING_GUIDE 快轨规则(事故措辞:卖的好的短袖)。

    曾不命中 → structured_llm 图路径 → 候选不刷新(幻影根源之一)。"""
    result = SlotExtractor.extract(phrase)
    assert result["intentType"] == "shopping_guide", f"{phrase!r} 应命中导购快轨规则"
    assert ShoppingGuideSkill().can_handle({"input": phrase}) is True


def test_cart_phrase_not_hijacked_by_guide_rule():
    """加购措辞仍归 CART_MANAGE(导购规则的 negative_pattern 不得误伤)。"""
    result = SlotExtractor.extract("把第一件加入购物车")
    assert result["intentType"] == "cart_manage"


# ------------------------------------------- Fix B:图路径候选登记与上行


class _FakeTool:
    def __init__(self, output: dict) -> None:
        self._output = output

    async def execute(self, _context: dict) -> dict:
        return self._output


def _graph_state() -> dict:
    """最小可执行图状态:单步 searchProducts 计划 + stale 候选 + 预置短期记忆(免 DB)。"""
    return {
        "thread_id": "pytest_cartbug_thread",
        "user_id": "pytest_cartbug_user",
        "job_id": None,  # 关闭 emit_status,不依赖 Redis
        "input": "卖的好的短袖",
        "business_config": {},
        "intents": [{"intent": "shopping_guide", "confidence": 0.95}],
        "short_memory": [{"role": "user", "content": "卖的好的短袖"}],
        "guide_context": dict(STALE_GUIDE_CONTEXT),
        "task_plan": {
            "goal": "Recommend short-sleeve T-shirts",
            "subtasks": [
                {"id": "step_search", "description": "Search products matching 短袖", "status": "pending"}
            ],
            "currentStepIndex": 0,
        },
    }


def _patch_tool_dispatch(monkeypatch: pytest.MonkeyPatch, tool_name: str, tool_output: dict) -> None:
    """钉死工具选择(绕过 fast-path 正则与 LLM fallback)+ 假工具注册表。"""
    monkeypatch.setattr(
        step_execution_engine,
        "try_match_executor_fast_path",
        lambda *_args, **_kwargs: {"toolName": tool_name, "args": {"query": "短袖", "limit": 4}},
    )

    def fake_get_tool(name: str):
        assert name == tool_name, f"意外工具调度: {name}"
        return _FakeTool(tool_output)

    monkeypatch.setattr(step_execution_engine, "_try_import_tools", lambda: fake_get_tool)


def test_search_products_tool_result_registers_candidates(monkeypatch: pytest.MonkeyPatch):
    """症状钉死:planner 选中 searchProducts 工具(而非技能)时,结果必须刷新候选。

    现状(修复前)红:guideContext 原样携带 stale Nike 三件套返回。"""
    _patch_tool_dispatch(
        monkeypatch, "searchProducts", {"total": 2, "products": [dict(p) for p in FRESH_TOOL_PRODUCTS]}
    )

    async def scenario() -> dict:
        return await step_execution_engine.execute_step(_graph_state())

    result = asyncio.run(scenario())
    guide = result.get("guideContext")
    assert guide, "execute_step 必须上行 guideContext(死写修复)"
    assert guide["candidateProductIds"] == ["SPU-T-SHIRT-1", "SPU-T-SHIRT-2"]
    assert [p["id"] for p in guide["candidateProducts"]] == ["SPU-T-SHIRT-1", "SPU-T-SHIRT-2"]
    assert guide["lastSearchQuery"] == "短袖"
    first = guide["candidateProducts"][0]
    assert first["name"] == FRESH_TOOL_PRODUCTS[0]["name"]
    assert first["price"] == 269.0 and first["stock"] == 345
    # stale 候选必须被整体覆盖,不得残留 Nike 幻影
    assert all("nike" not in str(pid).lower() for pid in guide["candidateProductIds"])


def test_empty_search_result_keeps_context_shape(monkeypatch: pytest.MonkeyPatch):
    """查空不登记:诚实空结果不得用空候选覆写上一轮候选(登记只在结果非空时发生)。"""
    _patch_tool_dispatch(monkeypatch, "searchProducts", {"total": 0, "products": []})

    async def scenario() -> dict:
        return await step_execution_engine.execute_step(_graph_state())

    result = asyncio.run(scenario())
    # 未刷新时上行的是 state 现值(= stale 原文),key 集不变形
    assert result["guideContext"]["candidateProductIds"] == STALE_GUIDE_CONTEXT["candidateProductIds"]


def test_executor_node_forwards_guide_context(monkeypatch: pytest.MonkeyPatch):
    """executor_node 必须把 guideContext 写回图状态(事故的断点就在这一跳)。"""

    async def fake_execute_step(_state: dict) -> dict:
        return {
            "taskPlan": _state["task_plan"],
            "globalTransitionsCount": 1,
            "guideContext": {
                "candidateProductIds": ["SPU-T-SHIRT-1"],
                "candidateProducts": [dict(FRESH_TOOL_PRODUCTS[0])],
                "clarificationRound": 1,
                "lastSearchQuery": "短袖",
            },
        }

    monkeypatch.setattr(executor_module, "execute_step", fake_execute_step)
    update = asyncio.run(executor_module.executor_node(_graph_state()))
    assert update["guide_context"]["candidateProductIds"] == ["SPU-T-SHIRT-1"], (
        "guide_context 未回写图状态 → run_agent 收口把 stale 候选原样存回 TaskMemory"
    )


def test_skill_extra_guide_context_threads(monkeypatch: pytest.MonkeyPatch):
    """技能分支(图路径内 ShoppingGuideSkill)的 extra.guideContext 同样必须上行。"""

    class _FakeSkill:
        metadata = {"name": "商品智能导购"}

        async def execute(self, _context: dict) -> dict:
            return {
                "success": True,
                "output": "为您精选了以下推荐商品…",
                "extra": {
                    "guideContext": {
                        "candidateProductIds": ["SPU-T-SHIRT-1"],
                        "candidateProducts": [dict(FRESH_TOOL_PRODUCTS[0])],
                        "clarificationRound": 1,
                        "lastSearchQuery": "卖的好的短袖",
                    }
                },
            }

    class _FakeRegistry:
        @staticmethod
        def get_skill(_name: str):
            return _FakeSkill()

    monkeypatch.setattr(
        step_execution_engine,
        "try_match_executor_fast_path",
        lambda *_args, **_kwargs: {"toolName": "skill_shopping_guide", "args": {}},
    )
    monkeypatch.setattr(step_execution_engine, "_try_import_skills", lambda: _FakeRegistry())

    async def scenario() -> dict:
        return await step_execution_engine.execute_step(_graph_state())

    result = asyncio.run(scenario())
    assert result["guideContext"]["candidateProductIds"] == ["SPU-T-SHIRT-1"], (
        "技能分支 extra.guideContext 此前是对 state 拷贝的死写,到不了图状态"
    )


# ------------------------------------------------- Fix C:假货兜底拆除


def test_add_to_cart_without_candidates_asks_honestly(monkeypatch: pytest.MonkeyPatch):
    """无任何候选可解析的加购指令:诚实反问,绝不编造 Pegasus 假商品入车。"""
    add_calls: list[dict] = []

    async def fake_summary(_payload: dict) -> dict:
        return {"cart": {"items": [], "totalQuantity": 0, "totalAmount": 0}}

    async def fake_add(payload: dict) -> dict:
        add_calls.append(payload)
        return {"success": True, "cart": {"items": [payload], "totalQuantity": 1, "totalAmount": 0}}

    monkeypatch.setattr(MallDomainService, "get_cart_summary", staticmethod(fake_summary))
    monkeypatch.setattr(MallDomainService, "add_to_cart", staticmethod(fake_add))

    async def scenario() -> dict:
        return await CartManageSkill().execute(
            {"input": "把第一件加入购物车", "userId": "u1", "threadId": "t1", "extra": {}}
        )

    res = asyncio.run(scenario())
    assert res["success"] is True
    assert "Pegasus" not in res["output"] and "Nike" not in res["output"], f"假货兜底未拆净: {res['output']}"
    assert "哪一款" in res["output"], "无候选时应反问,而非编造目标商品"
    assert add_calls == [], "无候选时不得触发任何入车写入"


def test_qty_change_unresolvable_target_asks_honestly(monkeypatch: pytest.MonkeyPatch):
    """改量目标全链解析失败(有车但无条目可匹配):诚实拦截,绝不错改 AJ1 幻影。"""
    update_calls: list[dict] = []

    async def fake_summary(_payload: dict) -> dict:
        # 有车(storage 非空)但条目解析不出来:items 空但 has_cart 真
        return {"cart": {"items": [], "totalQuantity": 0, "totalAmount": 0}}

    async def fake_has_cart(_payload: dict) -> bool:
        return True

    async def fake_update(payload: dict) -> dict:
        update_calls.append(payload)
        return {"cart": {"items": [], "totalQuantity": 0, "totalAmount": 0}}

    monkeypatch.setattr(MallDomainService, "get_cart_summary", staticmethod(fake_summary))
    monkeypatch.setattr(MallDomainService, "has_cart", staticmethod(fake_has_cart))
    monkeypatch.setattr(MallDomainService, "update_cart_item", staticmethod(fake_update))

    async def scenario() -> dict:
        return await CartManageSkill().execute(
            {"input": "把那件数量改成2", "userId": "u1", "threadId": "t1", "extra": {}}
        )

    res = asyncio.run(scenario())
    assert res["success"] is True
    assert "aj1" not in res["output"].lower(), f"AJ1 假兜底未拆净: {res['output']}"
    assert "未能定位" in res["output"], "解析失败应诚实拦截"
    assert update_calls == [], "解析失败时不得触发任何改量写入"
