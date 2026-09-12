"""address_manage 意图 + 深规划尽力而为规则 + 假单工具摘除(多意图一期④⑤)。

实弹矩阵病灶:A11「仅建地址」被 structured 判成 general_query 后 planner LLM
自由发挥,编造「已发货联系快递员改派、转寄费自理」的假政策 —— 地址簿能力
在工具面真实存在(saveUserAddress/getUserAddresses),但意图词表没有它的名字。
本套钉死:规则层产出意图(metric_query 先例,零分类器 prompt 变更)、中文
地址解析、判定前置直通、Step3 复合注入、planner 快轨、深规划「尽力而为 +
严禁 createOrder」规则、createOrder 从 executor 工具面摘除。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.graph.nodes import planner as planner_mod
from engine_py.tools_registry import get_tool
from engine_py.tools_registry.order_domain import OrderDomainService
from engine_py.triage import intent_triage_engine as triage_mod
from engine_py.triage.intent_registry import (
    INTENT_REGISTRY,
    all_intent_labels,
    terminal_intents,
)
from engine_py.triage.intent_triage_engine import (
    IntentTriageEngine,
    _inject_address_manage,
    detect_address_manage,
    parse_chinese_address,
)
from engine_py.triage.slot_extractor import AgentIntentType

ADDRESS_MANAGE = AgentIntentType.ADDRESS_MANAGE
from engine_py.triage.structured_classifier import IntentNode, StructuredTriageOutput

A11_SENTENCE = "创建一个新的地址 张伟 13800138000 北京市海淀区中关村南大街1号院8号楼1402室"
A1_SENTENCE = (
    "创建一个新的地址 张伟 13800138000 北京市海淀区中关村南大街1号院8号楼1402室，"
    "并下单一个新的极光 120g超轻可收纳防晒皮肤短袖，邮寄到新创建的地址"
)

# ── 中文地址解析(纯函数)──────────────────────────────────────────────────


class TestParseChineseAddress:
    def test_municipality(self):
        parsed = parse_chinese_address("北京市海淀区中关村南大街1号院8号楼1402室")
        assert parsed == {
            "province": "北京市",
            "city": "北京市",
            "district": "海淀区",
            "detailAddress": "中关村南大街1号院8号楼1402室",
        }

    def test_province_city_district(self):
        parsed = parse_chinese_address("浙江省杭州市西湖区文三路100号")
        assert parsed == {
            "province": "浙江省",
            "city": "杭州市",
            "district": "西湖区",
            "detailAddress": "文三路100号",
        }

    def test_city_without_province(self):
        parsed = parse_chinese_address("广州市天河区体育西路5号")
        assert parsed["city"] == "广州市"
        assert parsed["district"] == "天河区"
        assert parsed["detailAddress"] == "体育西路5号"
        assert parsed["province"] == ""

    def test_unparsable_returns_none(self):
        assert parse_chinese_address("中关村南大街1号") is None
        assert parse_chinese_address("") is None

    def test_municipality_district_not_eaten_as_city(self):
        """直辖市后紧跟的区不得被误吃成市。"""
        parsed = parse_chinese_address("上海市浦东新区世纪大道100号")
        assert parsed["city"] == "上海市"
        assert parsed["district"] == "浦东新区"


# ── 地址簿检测器(纯函数)──────────────────────────────────────────────────


class TestDetectAddressManage:
    def test_create_with_full_payload(self):
        detected = detect_address_manage(A11_SENTENCE)
        assert detected is not None
        assert detected["mode"] == "save"
        assert detected["entities"]["receiverName"] == "张伟"
        assert detected["entities"]["receiverPhone"] == "13800138000"
        assert detected["entities"]["district"] == "海淀区"
        assert detected["entities"]["province"] == "北京市"

    def test_create_on_compound_sentence(self):
        """A1 复合句同样检出 create 形(复合路由交由注入器/多候选闸)。"""
        assert detect_address_manage(A1_SENTENCE) is not None

    def test_create_without_payload_is_partial_not_none(self):
        detected = detect_address_manage("新增一个收货地址")
        assert detected is not None
        assert detected["mode"] == "save"
        assert not detected["entities"].get("receiverPhone")

    def test_explicit_order_id_vetoes_create_form(self):
        assert detect_address_manage("把订单ORD-123改到新创建的地址") is None

    def test_modify_address_is_not_create(self):
        assert detect_address_manage("修改收货地址为上海市浦东新区") is None

    def test_list_forms(self):
        for text in ("看看我的收货地址", "我的地址簿有哪些", "查一下我的地址簿"):
            detected = detect_address_manage(text)
            assert detected is not None and detected["mode"] == "list", text

    def test_order_address_lookup_is_not_address_book(self):
        assert detect_address_manage("查一下订单9081的地址") is None


# ── 注册表登记(metric_query 先例:规则层产出,零分类器 prompt 变更)────────


class TestRegistry:
    def test_address_manage_registered(self):
        assert ADDRESS_MANAGE in all_intent_labels()
        assert ADDRESS_MANAGE in terminal_intents()
        spec = INTENT_REGISTRY[ADDRESS_MANAGE]
        assert spec.prompt_category is None, "规则层产出意图不得进分类器 10 类目"
        assert spec.lifecycle == "active"


# ── Step3 复合注入(纯函数缝)─────────────────────────────────────────────


class TestInjectAddressManage:
    def test_compound_injects_primary_and_drops_general_query(self):
        parsed = [
            {"intent": "general_query", "confidence": 0.9, "type": "primary", "entities": {}, "missingSlots": []},
            {"intent": "cart_manage", "confidence": 0.85, "type": "secondary", "entities": {}, "missingSlots": []},
        ]
        result = _inject_address_manage(parsed, A1_SENTENCE)
        assert [p["intent"] for p in result] == ["address_manage", "cart_manage"]
        assert result[0]["type"] == "primary"
        assert result[0]["entities"]["receiverName"] == "张伟"

    def test_noop_without_create_form(self):
        parsed = [{"intent": "shopping_guide", "confidence": 0.9, "type": "primary", "entities": {}, "missingSlots": []}]
        assert _inject_address_manage(parsed, "推荐几款跑步鞋") == parsed

    def test_incomplete_create_carries_missing_slots(self):
        result = _inject_address_manage([], "创建一个新的地址 张伟")
        assert result[0]["intent"] == "address_manage"
        assert result[0]["missingSlots"], "缺电话/地址必须以 missingSlots 表达"


# ── 判定前置直通 + Step3 接线(Step 3 桩法,先例 test_step3_consult_demote)──


async def _fake_exemplars(*args, **kwargs) -> list:
    return []


class _FakeShortMemory:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_messages(self) -> list:
        return []


class _FakeTaskMemory:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_task_state(self) -> dict | None:
        return None

    async def save_task_state(self, state: dict) -> None:
        return None


def _state(input_text: str) -> dict:
    return {
        "thread_id": "thread_address_manage_test",
        "user_id": "u_address_manage",
        "input": input_text,
        "image_urls": [],
        "input_embedding": [1.0, 0.0, 0.0],
        "business_config": {"businessId": "ecommerce"},
    }


def _run_process(monkeypatch: pytest.MonkeyPatch, input_text: str, classify_result=None, log_calls: list | None = None) -> dict:
    async def _fake_embed(text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    async def _fake_anchors() -> dict:
        orth = [0.0, 1.0, 0.0]
        return {"order_status": [orth], "refund": [orth], "out_of_scope": [orth]}

    async def _fake_log(*args, **kwargs):
        if log_calls is not None:
            log_calls.append({"args": args, "kwargs": kwargs})

    async def _fake_classify(input_for_prompt, **kwargs):
        if classify_result is None:
            raise AssertionError("规则前置直通后不得再进结构化分类器")
        return classify_result

    async def _fake_consult(state, history_msgs):
        return None

    monkeypatch.setattr(triage_mod, "ShortMemory", _FakeShortMemory)
    monkeypatch.setattr(triage_mod, "TaskMemory", _FakeTaskMemory)
    monkeypatch.setattr(triage_mod, "classify", _fake_classify)
    monkeypatch.setattr(triage_mod, "run_consult_direct_answer", _fake_consult)
    monkeypatch.setattr(triage_mod, "search_relevant_exemplars", _fake_exemplars)
    monkeypatch.setattr(IntentTriageEngine, "log_intent_to_db", _fake_log)
    monkeypatch.setattr(triage_mod.SemanticVectorCache, "_tenant_cache", {})
    monkeypatch.setattr(triage_mod.SemanticVectorCache, "get_embedding_with_cache", _fake_embed)
    monkeypatch.setattr(triage_mod.SemanticVectorCache, "get_anchor_vectors", _fake_anchors)
    return asyncio.run(triage_mod.IntentTriageEngine.process(_state(input_text)))


class TestPrecheckTerminal:
    def test_pure_create_terminates_at_precheck_without_llm(self, monkeypatch):
        """A11:纯建地址直通 address_manage 终局,零结构化调用 —— 不再落到
        general_query 让 planner LLM 编造假流程。"""
        log_calls: list = []
        result = _run_process(monkeypatch, A11_SENTENCE, classify_result=None, log_calls=log_calls)
        assert result["intents"][0]["intent"] == "address_manage"
        assert result["intents"][0]["entities"]["receiverName"] == "张伟"
        assert "output" not in result, "直通终局进 planner 编排,不是反问旁路"
        assert log_calls[0]["kwargs"].get("arbitration_reason") == "address_manage_precheck"

    def test_list_form_terminates_at_precheck(self, monkeypatch):
        log_calls: list = []
        result = _run_process(monkeypatch, "看看我的收货地址", classify_result=None, log_calls=log_calls)
        assert result["intents"][0]["intent"] == "address_manage"
        assert result["intents"][0]["entities"].get("addressAction") == "list"


class TestStep3Wiring:
    def test_compound_create_injected_as_primary(self, monkeypatch):
        """A1 复合形:结构化产出 general_query+cart_manage → 注入器提升
        address_manage 为 primary,丢弃 general_query,保留 cart_manage。"""
        log_calls: list = []
        result = _run_process(
            monkeypatch,
            A1_SENTENCE,
            classify_result=StructuredTriageOutput(
                intents=[
                    IntentNode(intent="general_query", confidence=0.8, type="primary"),
                    IntentNode(intent="cart_manage", confidence=0.9, type="secondary"),
                ]
            ),
            log_calls=log_calls,
        )
        assert [p["intent"] for p in result["intents"]] == ["address_manage", "cart_manage"]
        assert result["intents"][0]["entities"]["receiverPhone"] == "13800138000"
        assert "output" not in result, "复合形放行 planner,不得被反问劫持"


# ── planner 快轨 + 深规划规则 ─────────────────────────────────────────────


class _FakeShortMemoryPlanner:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_messages(self) -> list:
        return []


class TestPlannerFastTrack:
    def _plan(self, monkeypatch: pytest.MonkeyPatch, intents: list[dict]) -> dict:
        monkeypatch.setattr(planner_mod, "ShortMemory", _FakeShortMemoryPlanner)

        def _no_llm(*args, **kwargs):
            raise AssertionError("address_manage 快轨不得消耗 LLM")

        monkeypatch.setattr(planner_mod, "planner_llm", _no_llm)
        state = {"intents": intents, "input": "创建一个新的地址", "short_memory": []}
        return asyncio.run(planner_mod.planner_node(state))

    def test_save_variant_plans_save_user_address(self, monkeypatch):
        result = self._plan(
            monkeypatch,
            [
                {
                    "intent": "address_manage",
                    "confidence": 0.9,
                    "type": "primary",
                    "entities": {
                        "addressAction": "save",
                        "receiverName": "张伟",
                        "receiverPhone": "13800138000",
                        "province": "北京市",
                        "city": "北京市",
                        "district": "海淀区",
                        "detailAddress": "中关村南大街1号院8号楼1402室",
                    },
                }
            ],
        )
        subtasks = result["task_plan"]["subtasks"]
        assert len(subtasks) == 1
        assert "saveUserAddress" in subtasks[0]["description"]
        assert "张伟" in subtasks[0]["description"]
        assert "13800138000" in subtasks[0]["description"]

    def test_list_variant_plans_get_user_addresses(self, monkeypatch):
        result = self._plan(
            monkeypatch,
            [
                {
                    "intent": "address_manage",
                    "confidence": 0.9,
                    "type": "primary",
                    "entities": {"addressAction": "list"},
                }
            ],
        )
        subtasks = result["task_plan"]["subtasks"]
        assert len(subtasks) == 1
        assert "getUserAddresses" in subtasks[0]["description"]

    def test_compound_at_planner_goes_deep_planning_not_single_fast_track(self, monkeypatch):
        """评审缺陷修复:A1 复合形(address_manage+cart_manage)到 planner 不得
        被单意图快轨砍掉购物车半 —— 快轨只认单意图,复合形走深规划双编排。"""
        monkeypatch.setattr(planner_mod, "ShortMemory", _FakeShortMemoryPlanner)
        captured: dict = {}

        class _FakeResponse:
            content = '{"goal": "g", "subtasks": []}'

        class _FakeLLM:
            async def ainvoke(self, prompt):
                captured["prompt"] = prompt
                return _FakeResponse()

        monkeypatch.setattr(planner_mod, "planner_llm", lambda: _FakeLLM())
        state = {
            "intents": [
                {
                    "intent": "address_manage",
                    "confidence": 0.9,
                    "type": "primary",
                    "entities": {"addressAction": "save", "receiverPhone": "13800138000"},
                    "missingSlots": [],
                },
                {"intent": "cart_manage", "confidence": 0.85, "type": "secondary", "missingSlots": []},
            ],
            "input": "创建地址并下单",
            "short_memory": [],
        }
        result = asyncio.run(planner_mod.planner_node(state))
        descriptions = [st.get("description", "") for st in result["task_plan"]["subtasks"]]
        assert captured["prompt"], "复合形必须进深规划(快轨只认单意图)"
        assert not any("saveUserAddress" in d and len(descriptions) == 1 for d in descriptions), (
            "复合形不得产出单 saveUserAddress 快轨计划"
        )


class TestDeepPlanningPromptRules:
    def _captured_prompt(self, monkeypatch: pytest.MonkeyPatch, intents: list[dict]) -> str:
        monkeypatch.setattr(planner_mod, "ShortMemory", _FakeShortMemoryPlanner)
        captured: dict = {}

        class _FakeResponse:
            content = '{"goal": "g", "subtasks": []}'

        class _FakeLLM:
            async def ainvoke(self, prompt):
                captured["prompt"] = prompt
                return _FakeResponse()

        monkeypatch.setattr(planner_mod, "planner_llm", lambda: _FakeLLM())
        state = {"intents": intents, "input": "复合请求", "short_memory": []}
        asyncio.run(planner_mod.planner_node(state))
        return captured["prompt"]

    def test_prompt_bans_create_order_and_requires_exhaustive_multi_intent(self, monkeypatch):
        prompt = self._captured_prompt(
            monkeypatch,
            [
                {"intent": "refund", "confidence": 0.9, "type": "primary", "missingSlots": ["orderId"]},
                {"intent": "shopping_guide", "confidence": 0.85, "type": "secondary", "missingSlots": []},
            ],
        )
        assert "createOrder" in prompt and "NEVER" in prompt, "深规划必须明令禁止规划假单工具"
        assert "saveUserAddress" in prompt, "地址簿工具必须进深规划视野"
        assert "missingSlots" in prompt, "尽力而为规则必须消费缺槽注记"
        assert "ask the customer" in prompt, "办不了的部分必须以追问收口,严禁静默吞"


# ── 假单工具摘除(executor 面)────────────────────────────────────────────


class TestCreateOrderDeregistered:
    def test_create_order_not_in_executor_tool_surface(self):
        assert get_tool("createOrder") is None, "createOrder 是假单工具(写 demo 表+编造运单号),不得暴露给 executor"

    def test_service_method_still_available_for_tests(self):
        assert hasattr(OrderDomainService, "create_order")


# ── executor 快路径确定性执行(实弹验收发现:无处理器时步骤空转给 LLM,
#    未调 saveUserAddress 即宣称「已成功保存」—— 幻觉成功,表 0 行)────────


class TestExecutorFastPathAddressBook:
    def test_save_address_description_maps_deterministically(self):
        from engine_py.graph.nodes.executor_fast_path import try_match_executor_fast_path

        desc = (
            "Call saveUserAddress to save a new delivery address with: "
            "receiverName 张伟、receiverPhone 13800138000、province 北京市、city 北京市、"
            "district 海淀区、detailAddress 中关村南大街1号院8号楼1402室"
        )
        result = try_match_executor_fast_path(desc, "创建一个新的地址", ["saveUserAddress"])
        assert result == {
            "toolName": "saveUserAddress",
            "args": {
                "receiverName": "张伟",
                "receiverPhone": "13800138000",
                "province": "北京市",
                "city": "北京市",
                "district": "海淀区",
                "detailAddress": "中关村南大街1号院8号楼1402室",
            },
        }

    def test_list_address_book_description_maps_deterministically(self):
        from engine_py.graph.nodes.executor_fast_path import try_match_executor_fast_path

        result = try_match_executor_fast_path(
            description="Call getUserAddresses to list the customer's saved delivery addresses",
            user_input="看看我的收货地址",
            allowed_tools=["getUserAddresses"],
        )
        assert result == {"toolName": "getUserAddresses", "args": {}}

    def test_address_book_tools_in_executor_whitelist(self):
        """白名单不含地址簿工具 → 快路径命中也会被 dispatch 门槛整段跳过。"""
        from engine_py.graph.nodes.step_execution_engine import _base_executor_tools

        assert "saveUserAddress" in _base_executor_tools
        assert "getUserAddresses" in _base_executor_tools


if __name__ == "__main__":
    pytest.main([__file__])
