"""task_state 结构化任务态单测(docs/multi-turn-task-state.md P0-1,2026-10-24)。

裁决 D3/D4/D8:任务层真源与域总线分层,JSONB 列内演进(缺省兜底,无迁移);
实体更新走 retire_and_set(覆盖即退休,旧值进 superseded);hot keys 白名单
防垃圾串(白名单外只拒不存);序列化任务层段前置于装配面(活跃实体仅渲染
最新值,superseded 是审计留痕不进提示词)。
"""

from __future__ import annotations

from engine_py.memory.task_state import (
    CONSTRAINTS_CAP,
    SUPERSEDED_CAP,
    advance_task_state,
    extract_constraints,
    extract_entities,
    normalize_task_state,
    record_constraint,
    retire_and_set,
    serialize_task_state,
    set_goal,
)

_HOT = frozenset({"date", "city", "order_id"})


class TestNormalize:
    def test_none_yields_empty_shape(self):
        st = normalize_task_state(None)
        assert st == {"turns": 0, "goal": None, "goal_turn": None, "constraints": [], "entities": {}}

    def test_bad_shapes_reset(self):
        # 旧数据/异构数据(字符串、列表、entities 非字典)一律兜底成合法空形,
        # 严禁抛 —— JSONB 列内演进的第一道防线(调研坑:schema 演进破坏 resume)
        for raw in ("垃圾", ["列表"], 123, {"goal": 3.5}, {"constraints": "x"}, {"entities": []}):
            st = normalize_task_state(raw)
            assert set(st) == {"turns", "goal", "goal_turn", "constraints", "entities"}
            assert isinstance(st["constraints"], list) and isinstance(st["entities"], dict)

    def test_valid_shape_passthrough_and_malformed_entry_dropped(self):
        raw = {
            "goal": "上海行程",
            "goal_turn": 2,
            "constraints": [{"text": "只要顺丰", "turn": 3}, {"bad": 1}, "裸字符串"],
            "entities": {
                "date": {"value": "周三", "turn": 1, "superseded": []},
                "junk": "非字典值",
            },
        }
        st = normalize_task_state(raw)
        assert st["goal"] == "上海行程" and st["goal_turn"] == 2
        assert st["constraints"] == [{"text": "只要顺丰", "turn": 3}]
        assert st["entities"] == {"date": {"value": "周三", "turn": 1, "superseded": []}}


class TestRetireAndSet:
    def test_whitelist_rejects_non_hot_key(self):
        ents, ok = retire_and_set({}, "vendor", "nike", 3, hot_keys=_HOT)
        assert ok is False and ents == {}

    def test_rejected_key_observed(self, capsys):
        """D8:白名单外键只拒不落态,但拒绝必须进观察通道(否则垃圾串静默消失,
        该扩的白名单无从发现)。"""
        retire_and_set({}, "vendor", "nike", 3, hot_keys=_HOT)
        out = capsys.readouterr().out
        assert "白名单外实体键拒绝" in out and "vendor" in out

    def test_first_set_has_no_superseded(self):
        ents, ok = retire_and_set({}, "date", "周三", 2, hot_keys=_HOT)
        assert ok is True
        assert ents["date"] == {"value": "周三", "turn": 2, "superseded": []}

    def test_overwrite_retires_old_value(self):
        ents, _ = retire_and_set({}, "date", "周三", 2, hot_keys=_HOT)
        ents, ok = retire_and_set(ents, "date", "周四", 5, hot_keys=_HOT)
        assert ok is True
        assert ents["date"]["value"] == "周四" and ents["date"]["turn"] == 5
        assert ents["date"]["superseded"] == [{"value": "周三", "turn": 2}]

    def test_superseded_capped(self):
        ents: dict = {}
        for i, val in enumerate(["一", "二", "三", "四", "五"], start=1):
            ents, _ = retire_and_set(ents, "city", val, i, hot_keys=_HOT)
        sup = ents["city"]["superseded"]
        assert len(sup) == SUPERSEDED_CAP
        assert [s["value"] for s in sup] == ["二", "三", "四"]  # 最旧的(一)先出列

    def test_same_value_idempotent_no_churn(self):
        ents, _ = retire_and_set({}, "date", "周三", 2, hot_keys=_HOT)
        ents2, ok = retire_and_set(ents, "date", "周三", 9, hot_keys=_HOT)
        assert ok is False and ents2 == ents  # 同值不刷 turn(退休链零扰动)

    def test_empty_value_rejected(self):
        for bad in ("", "   "):
            ents, ok = retire_and_set({}, "date", bad, 1, hot_keys=_HOT)
            assert ok is False and ents == {}


class TestConstraints:
    def test_record_and_dedupe_refreshes_turn(self):
        st = normalize_task_state(None)
        st = record_constraint(st, "不要顺丰", 2)
        st = record_constraint(st, "只要白色", 3)
        st = record_constraint(st, "不要顺丰", 6)  # 同文本去重,turn 刷新
        assert [(c["text"], c["turn"]) for c in st["constraints"]] == [
            ("只要白色", 3),
            ("不要顺丰", 6),
        ]

    def test_capped_oldest_dropped(self):
        st = normalize_task_state(None)
        for i in range(CONSTRAINTS_CAP + 2):
            st = record_constraint(st, f"约束{i}", i)
        assert len(st["constraints"]) == CONSTRAINTS_CAP
        assert st["constraints"][0]["text"] == "约束2"  # 最旧两条出列
        assert st["constraints"][-1]["text"] == f"约束{CONSTRAINTS_CAP + 1}"

    def test_blank_ignored(self):
        st = record_constraint(normalize_task_state(None), "  ", 1)
        assert st["constraints"] == []


class TestGoal:
    def test_set_and_overwrite(self):
        st = set_goal(normalize_task_state(None), "上海行程", 2)
        assert st["goal"] == "上海行程" and st["goal_turn"] == 2
        st = set_goal(st, "北京行程", 5)
        assert st["goal"] == "北京行程" and st["goal_turn"] == 5

    def test_empty_and_default_placeholder_ignored(self):
        st = set_goal(normalize_task_state(None), "上海行程", 2)
        for ignored in ("", "   ", None, "Multi-turn conversational assistance"):
            st2 = set_goal(st, ignored, 9)  # run_agent 兜底 goal 是噪声,不落任务层
            assert st2["goal"] == "上海行程" and st2["goal_turn"] == 2


class TestExtractEntities:
    def test_camel_case_normalized_and_whitelist_filtered(self):
        intents = [
            {"intent": "order_status", "slots": {"orderId": "A-001", "junkKey": "x"}},
            {"intent": "guide", "slots": {"city": "上海", "date": "周三"}},
            {"intent": "no_slots"},
        ]
        pairs = extract_entities(intents, 4, hot_keys=_HOT)
        assert sorted(pairs) == [("city", "上海"), ("date", "周三"), ("order_id", "A-001")]

    def test_later_intent_wins_same_key(self):
        intents = [
            {"slots": {"date": "周三"}},
            {"slots": {"date": "周四"}},
        ]
        assert extract_entities(intents, 4, hot_keys=_HOT) == [("date", "周四")]

    def test_empty_and_nonstring_values_skipped(self):
        intents = [{"slots": {"city": ""}}, {"slots": {"date": 123}}, {"slots": None}]
        assert extract_entities(intents, 1, hot_keys=_HOT) == [("date", "123")]

    def test_rejected_key_observed_once_per_name(self, capsys):
        """同轮同名垃圾键只观察一次(多意图重复出现不刷屏)。"""
        intents = [{"slots": {"junk": "a"}}, {"slots": {"junk": "b"}}]
        assert extract_entities(intents, 1, hot_keys=_HOT) == []
        assert capsys.readouterr().out.count("白名单外实体键拒绝") == 1


class TestExtractConstraints:
    def test_negation_and_exclusion_hits(self):
        hits = extract_constraints("订周三的酒店,不要靠电梯的,另外只要大床房")
        assert hits == ["不要靠电梯的", "只要大床房"]

    def test_ordinary_sentence_clean(self):
        assert extract_constraints("帮我查一下订单什么时候到") == []

    def test_tail_length_and_boundary_guards(self):
        # 尾串超 8 字不出(防整句被吞成约束)
        assert extract_constraints("不要这个那个这个那个这个那个那个这个那个") == []
        # 句读是合法边界:尾串在标点处截停
        assert extract_constraints("只要大床房。") == ["只要大床房"]
        assert extract_constraints("只要大床房,不要圆床") == ["只要大床房", "不要圆床"]


class TestAdvance:
    def test_composes_goal_entities_constraints(self):
        prev = normalize_task_state({"goal": "上海行程", "goal_turn": 2, "entities": {"date": {"value": "周三", "turn": 2, "superseded": []}}})
        nxt = advance_task_state(
            prev,
            goal="Multi-turn conversational assistance",  # 兜底噪声不落
            intents=[{"slots": {"orderId": "A-9", "date": "周四"}}],
            user_text="改成周四,只要高楼层",
            turn=6,
        )
        assert nxt["goal"] == "上海行程" and nxt["goal_turn"] == 2
        assert nxt["entities"]["date"]["value"] == "周四"
        assert nxt["entities"]["date"]["superseded"] == [{"value": "周三", "turn": 2}]
        assert nxt["entities"]["order_id"]["value"] == "A-9"
        assert [c["text"] for c in nxt["constraints"]] == ["只要高楼层"]

    def test_garbage_prev_recovered(self):
        nxt = advance_task_state("不是字典", goal="g", intents=[], user_text="", turn=1)
        assert nxt["goal"] == "g"


class TestSerialize:
    def test_empty_state_none(self):
        assert serialize_task_state(normalize_task_state(None)) is None

    def test_full_render_superseded_not_leaked(self):
        st = normalize_task_state(
            {
                "goal": "上海行程",
                "goal_turn": 2,
                "constraints": [{"text": "只要大床房", "turn": 3}],
                "entities": {
                    "date": {
                        "value": "周四",
                        "turn": 5,
                        "superseded": [{"value": "周三", "turn": 2}],
                    },
                    "city": {"value": "上海", "turn": 1, "superseded": []},
                },
            }
        )
        line = serialize_task_state(st)
        assert line is not None and line.startswith("[TASK STATE]")
        assert "上海行程" in line and "只要大床房" in line
        assert "date=周四" in line and "city=上海" in line
        assert "周三" not in line  # superseded 是审计留痕,不进提示词

    def test_partial_state_renders_present_parts(self):
        st = normalize_task_state({"entities": {"city": {"value": "上海", "turn": 1, "superseded": []}}})
        line = serialize_task_state(st)
        assert line is not None
        assert "用户约束" not in line and "city=上海" in line

    def test_render_caps_bounded(self):
        """序列化截帽(goal 80/约束 20/实体值 40):任务层段有界,才能被装配
        预算真实覆盖(code-review 裁定:无截帽的长 goal 可无界进装配面)。"""
        st = normalize_task_state(
            {
                "goal": "长" * 200,
                "constraints": [{"text": "短" * 50, "turn": 1}],
                "entities": {"city": {"value": "地" * 100, "turn": 1, "superseded": []}},
            }
        )
        line = serialize_task_state(st)
        assert line is not None
        assert ("长" * 80) in line and ("长" * 81) not in line
        assert ("短" * 20) in line
        assert ("地" * 40) in line and ("地" * 41) not in line
