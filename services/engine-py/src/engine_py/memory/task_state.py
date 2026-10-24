"""结构化任务态(docs/multi-turn-task-state.md P0-1,2026-10-24 grilling 裁决 D3/D4/D8)。

「聊天不是 State,任务状态才是」——本模块是任务层真源(当前任务 goal /
用户约束 / 关键实体),与 guide/cart/order_context 域层总线**分层**不合并
(D3):域总线承载工具参数,任务层承载跨轮可续的任务叙事,序列化产物经
``build_history_block`` 的任务层段前置于装配面(planner/finish 消费)。

关键实体退休(治课程③「旧状态不退休」):更新走 ``retire_and_set`` ——
覆盖即退休,旧值进 ``superseded``(截 SUPERSEDED_CAP 条审计留痕,不进提示词);
照搬长记忆已验证的 superseded 模式,替代 step_execution 里「有值才覆盖」的
散点修补。

白名单防垃圾串(D8):hot keys 之外的槽位键一律不落任务态(config
``AI_TASK_STATE_HOT_KEYS`` 可扩);序列化只渲染活跃最新值。

JSONB 列内演进(D4,无 alembic):任务态存 ``task_memory.pending_intents``
的 ``taskState`` 键,读取一律先 ``normalize_task_state`` 缺省兜底 —— 旧数据
无键/异构形状/半截字段都重置成合法空形,严禁抛(schema 演进破坏 resume 是
调研点名的生产坑)。``turns`` 是任务态自带单调轮次计数(short_memory 截 10
条长度非单调,不能当轮次号),advance 时自增。
"""

from __future__ import annotations

import re

from ..config import settings

# snake 规范形热键缺省(config 可覆写);camelCase 槽位键入口先 _snake 归一
DEFAULT_HOT_KEYS: tuple[str, ...] = (
    "date",
    "time",
    "city",
    "address",
    "product",
    "order_id",
    "guest_count",
)

SUPERSEDED_CAP = 3
CONSTRAINTS_CAP = 3

# run_agent 无图结果时的兜底 goal(tasks_plan_to_save 缺省值),纯噪声不落任务层;
# 常量单源于此,run_agent 兜底字典引用同一常量(双源漂移防线)
GOAL_PLACEHOLDER = "Multi-turn conversational assistance"
_GOAL_NOISE = {"", GOAL_PLACEHOLDER.lower()}

# 序列化截帽:任务层段受装配预算管控(P0-1 规格),先保证单行有界
_GOAL_RENDER_CAP = 80
_CONSTRAINT_RENDER_CAP = 20
_ENTITY_VALUE_RENDER_CAP = 40

_CAMEL_1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_2 = re.compile(r"([a-z0-9])([A-Z])")

# 约束句式(保守窄集):否定/排除/限定先行词 + 1-8 字尾串,尾串含标点不收
# (防整句被吞成约束)。「别」单字误报率高(别人/别处)刻意不收;漏收是
# 保守失败(约束缺渲染),误收才是提示词污染。
_CONSTRAINT_RE = re.compile(
    r"(?:不要|不用|无需|只要|尽量|务必)([\u4e00-\u9fa5A-Za-z0-9]{1,8})(?![\u4e00-\u9fa5A-Za-z0-9])"
)


def _snake(key: str) -> str:
    """camelCase / 混合 → snake 规范形(orderId→order_id,guestCount→guest_count)。"""
    s1 = _CAMEL_1.sub(r"\1_\2", key or "")
    return _CAMEL_2.sub(r"\1_\2", s1).lower()


def _observe_rejected(key: str) -> None:
    """白名单外键的观察通道(D8):只拒不落态,但拒绝必须留痕 —— 否则垃圾串
    静默消失、该扩的白名单无从发现。print 即仓库观测惯例(旁路自吞不阻断)。"""
    print(f"[TaskState] 白名单外实体键拒绝(观察,不落态): {key!r} → 需要时扩 AI_TASK_STATE_HOT_KEYS")


def _active_hot_keys() -> frozenset[str]:
    keys = settings.task_state_hot_keys or DEFAULT_HOT_KEYS
    return frozenset(keys)


def _turn_of(raw: object) -> int:
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else 0


def normalize_task_state(raw: object) -> dict:
    """任意形状 → 合法任务态;None/异构/半截字段兜底成空形,绝不抛。"""
    state: dict = {"turns": 0, "goal": None, "goal_turn": None, "constraints": [], "entities": {}}
    if not isinstance(raw, dict):
        return state
    state["turns"] = _turn_of(raw.get("turns"))
    goal = raw.get("goal")
    if isinstance(goal, str) and goal.strip():
        state["goal"] = goal.strip()
        state["goal_turn"] = _turn_of(raw.get("goal_turn")) or None
    cons = raw.get("constraints")
    if isinstance(cons, list):
        for c in cons:
            if isinstance(c, dict) and isinstance(c.get("text"), str) and c["text"].strip():
                state["constraints"].append({"text": c["text"].strip(), "turn": _turn_of(c.get("turn"))})
    ents = raw.get("entities")
    if isinstance(ents, dict):
        for key, val in ents.items():
            if not (isinstance(val, dict) and isinstance(val.get("value"), str) and val["value"].strip()):
                continue
            sup: list[dict] = []
            raw_sup = val.get("superseded")
            if isinstance(raw_sup, list):
                for s in raw_sup:
                    if isinstance(s, dict) and isinstance(s.get("value"), str) and s["value"].strip():
                        sup.append({"value": s["value"].strip(), "turn": _turn_of(s.get("turn"))})
            state["entities"][str(key)] = {
                "value": val["value"].strip(),
                "turn": _turn_of(val.get("turn")),
                "superseded": sup[-SUPERSEDED_CAP:],
            }
    return state


def retire_and_set(
    entities: dict, key: str, value: object, turn: int, hot_keys: frozenset[str] | None = None
) -> tuple[dict, bool]:
    """实体更新单点:白名单外/空值拒绝;覆盖即退休(旧值进 superseded,截帽);
    同值幂等不刷 turn(退休链零扰动)。返回 (新实体表, 是否落库)。"""
    keys = hot_keys if hot_keys is not None else _active_hot_keys()
    canon = _snake(key or "")
    if canon not in keys:
        _observe_rejected(key)
        return dict(entities), False
    text = str(value).strip() if value is not None else ""
    if not text:
        return dict(entities), False
    ents = dict(entities)
    prev = ents.get(canon)
    if isinstance(prev, dict) and prev.get("value") == text:
        return ents, False
    sup: list[dict] = list(prev.get("superseded")) if isinstance(prev, dict) and isinstance(prev.get("superseded"), list) else []
    if isinstance(prev, dict) and isinstance(prev.get("value"), str) and prev["value"].strip():
        sup.append({"value": prev["value"].strip(), "turn": _turn_of(prev.get("turn"))})
    ents[canon] = {"value": text, "turn": turn, "superseded": sup[-SUPERSEDED_CAP:]}
    return ents, True


def record_constraint(state: dict, text: str, turn: int) -> dict:
    """约束追加:同文本去重并刷新轮次;超帽丢最旧。空文本原样返回。"""
    clean = (text or "").strip()
    if not clean:
        return state
    cons = [c for c in state.get("constraints", []) if c.get("text") != clean]
    cons.append({"text": clean, "turn": turn})
    return {**state, "constraints": cons[-CONSTRAINTS_CAP:]}


def set_goal(state: dict, goal: object, turn: int) -> dict:
    """任务目标写入:空值与 run_agent 兜底噪声(英文占位)忽略。"""
    text = goal.strip() if isinstance(goal, str) else ""
    if not text or text.lower() in _GOAL_NOISE:
        return state
    return {**state, "goal": text, "goal_turn": turn}


def extract_entities(
    intents: list[dict] | None, turn: int, hot_keys: frozenset[str] | None = None
) -> list[tuple[str, str]]:
    """意图槽位 → 白名单 (规范键, 值) 对;同键后到者胜;空值/非字符串清洗。"""
    keys = hot_keys if hot_keys is not None else _active_hot_keys()
    pairs: dict[str, str] = {}
    rejected: set[str] = set()
    for intent in intents or []:
        slots = (intent or {}).get("slots")
        if not isinstance(slots, dict):
            continue
        for key, val in slots.items():
            canon = _snake(str(key))
            if canon not in keys:
                if str(key) not in rejected:  # 同轮同名只观察一次,防多意图重复刷屏
                    rejected.add(str(key))
                    _observe_rejected(key)
                continue
            text = str(val).strip() if val is not None else ""
            if text:
                pairs[canon] = text
    return list(pairs.items())


def extract_constraints(text: str | None) -> list[str]:
    """用户输入 → 约束短语(命中片段原样入态,读起来才是人话)。"""
    return [m.group(0) for m in _CONSTRAINT_RE.finditer(text or "")]


def advance_task_state(
    prev: object,
    *,
    goal: object,
    intents: list[dict] | None,
    user_text: str | None,
    turn: int,
) -> dict:
    """单轮推进(收口缝唯一入口):goal/实体/约束合并进上一轮任务态,
    turns 单调自增。纯函数,任何输入不抛 —— 落库泳道内严禁炸。"""
    state = normalize_task_state(prev)
    next_turn = turn if isinstance(turn, int) and turn > 0 else state["turns"] + 1
    state["turns"] = next_turn
    state = set_goal(state, goal, next_turn)
    entities = state["entities"]
    for key, value in extract_entities(intents, next_turn):
        entities, _ = retire_and_set(entities, key, value, next_turn)
    state["entities"] = entities
    for phrase in extract_constraints(user_text):
        state = record_constraint(state, phrase, next_turn)
    return state


def serialize_task_state(state: object) -> str | None:
    """任务态 → 装配面任务层段(单行,省 token);空态 None 不渲染。
    实体只渲染活跃最新值 —— superseded 是审计留痕,不进提示词;各段截帽
    (goal 80 / 约束 20 / 实体值 40),保证该行有界、可被装配预算真实覆盖。"""
    st = normalize_task_state(state)
    parts: list[str] = []
    if st["goal"]:
        parts.append(f"当前任务:{st['goal'][:_GOAL_RENDER_CAP]}")
    if st["constraints"]:
        parts.append(
            "用户约束:"
            + ";".join(c["text"][:_CONSTRAINT_RENDER_CAP] for c in st["constraints"])
        )
    if st["entities"]:
        parts.append(
            "关键实体:"
            + ",".join(f"{k}={v['value'][:_ENTITY_VALUE_RENDER_CAP]}" for k, v in st["entities"].items())
        )
    if not parts:
        return None
    return "[TASK STATE] " + " ｜ ".join(parts)
