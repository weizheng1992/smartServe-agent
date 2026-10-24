"""上下文装配单点(2026-09-21 拷问轮决议)—— 历史 token 预算 + 滚动摘要。

planner / finish 的历史装配此前各自为政:全量 20 条无预算拼文本(无界增长),
摘要接口 compress() 是常量 stub(上下文悬崖:第 11 轮起早期对话无声消失)。
本模块收口为单点:

- ``estimate_tokens``:字符近似(中文 1 字≈1 token,不引 tokenizer 依赖);
- ``build_history_block``:纯函数,预算内从最新往旧装轮,预算外整轮进
  ``overflow``;行格式 ``[T{n} MM-dd HH:mm] Role: "..."``(无时间戳回退
  ``[T{n}]``);带前轮摘要时渲染 ``[EARLIER SUMMARY]:`` 段;
- ``summarize_overflow``:懒触发(仅溢出时调用)的滚动摘要 —— 合并旧摘要与
  溢出轮,复用 get_chat_model().bind(max_tokens=300);失败回退旧摘要,绝不阻断。

节点层(planner/finish)只消费 ``build_history_block`` 的纯函数产物;LLM 摘要
由 run_agent 每轮至多触发一次,经 task_memory.historySummary 跨轮持久化。
"""

from __future__ import annotations

import datetime as _dt

from ..config import settings
from ..llm.chat import get_chat_model

_EARLIER_HEADER = "[EARLIER SUMMARY]:"

_ROLE_LABEL = {"user": "Customer", "assistant": "Agent", "system": "System"}


def estimate_tokens(text: str) -> int:
    """字符近似:中文场景 1 字≈1 token,量级足够做预算裁剪,不引 tokenizer。"""
    return len(text or "")


def _format_ts(created_at) -> str:
    """ISO 时间戳 → ``MM-dd HH:mm``;解析失败/缺失返回空(行格式回退无时间)。"""
    if not created_at:
        return ""
    try:
        dt = _dt.datetime.fromisoformat(str(created_at))
        return dt.strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        return ""


def _format_turn(index: int, msg: dict) -> str | None:
    """单轮 → ``[T{n} MM-dd HH:mm] Role: "..."``;空/坏内容返回 None(跳过)。"""
    content = (msg or {}).get("content")
    if content is None or str(content).strip() in ("", "undefined", "null"):
        return None
    role = _ROLE_LABEL.get((msg or {}).get("role") or "", "Customer")
    ts = _format_ts((msg or {}).get("created_at"))
    prefix = f"[T{index} {ts}]" if ts else f"[T{index}]"
    return f'{prefix} {role}: "{str(content).strip()}"'


def build_history_block(
    messages: list[dict] | None,
    summary: str | None = None,
    budget: int | None = None,
    task_state_line: str | None = None,
) -> dict:
    """历史 → {block, overflow, kept_count, trimmed}。

    从最新往旧累积整轮,预算耗尽即停:更老的轮次整体进 ``overflow``(交由
    懒触发摘要),保留段保持时间正序。预算再小也至少保留最新一轮 —— 当轮
    上下文绝不能只剩摘要。``summary`` 非空时渲染 ``[EARLIER SUMMARY]:`` 段。
    ``task_state_line`` 非空时渲染 ``[TASK STATE]`` 段且**置于最前**(任务层
    段前置于装配面,docs/multi-turn-task-state.md P0-1);与摘要同律不占预算。
    """
    messages = messages or []
    if budget is None:
        budget = settings.history_budget_tokens
    if task_state_line:
        # 任务层段受同一预算管控(P0-1 规格;code-review 裁定):先扣自身
        # 成本再装轮,序列化截帽保证扣减有界;预算扣穿仍保底最新一轮
        budget = max(budget - estimate_tokens(task_state_line.strip()), 0)

    # 正序格式化(轮次号 = 会话内序号),空行跳过但序号连续
    formatted: list[tuple[int, dict, str]] = []
    for idx, msg in enumerate(messages, start=1):
        line = _format_turn(idx, msg)
        if line is not None:
            formatted.append((idx, msg, line))

    kept: list[tuple[dict, str]] = []
    overflow: list[dict] = []
    used = 0
    for index, msg, line in reversed(formatted):  # 最新往旧
        cost = estimate_tokens(line) + 1  # 换行
        if used + cost > budget and kept:
            overflow = [m for _, m, _ in formatted[: len(formatted) - len(kept)]]
            break
        kept.append((msg, line))
        used += cost
    else:
        overflow = []
    kept.reverse()  # 恢复时间正序

    sections: list[str] = []
    if task_state_line:
        sections.append(task_state_line.strip())
    if summary:
        # 摘要渲染截 600 字:滚动合并不占预算,LLM 不守 300 字时防缓慢膨胀
        sections.append(f"{_EARLIER_HEADER}\n{summary.strip()[:600]}")
    sections.extend(line for _, line in kept)

    return {
        "block": "\n".join(sections),
        "overflow": overflow,
        "kept_count": len(kept),
        "trimmed": bool(overflow),
    }


async def summarize_overflow(previous_summary: str | None, overflow_messages: list[dict]) -> str | None:
    """懒触发滚动摘要:合并旧摘要与溢出轮 → 新摘要;空溢出原样返回;
    LLM 失败回退旧摘要(摘要永不阻断主链路)。"""
    if not overflow_messages:
        return previous_summary

    turns = "\n".join(
        line for line in (_format_turn(i + 1, m) for i, m in enumerate(overflow_messages)) if line
    )
    prior = (previous_summary or "（无）").strip()
    prompt = (
        "你是客服会话摘要器。把「既有摘要」与「更早的对话轮」合并为一段简洁的滚动摘要,"
        "保留对后续服务有用的事实:订单号/运单号、买过与咨询过的商品、诉求与承诺、"
        "已给出的处理结论、顾客情绪。不评价、不推测、不复述无关寒暄,300 字以内,直接输出摘要正文。\n\n"
        f"[既有摘要]\n{prior}\n\n[更早的对话轮]\n{turns}"
    )
    try:
        resp = await get_chat_model().bind(max_tokens=300).ainvoke(prompt)
        text = getattr(resp, "content", "") or ""
        if isinstance(text, list):  # 多段 content 兜底
            text = "".join(str(seg) for seg in text)
        merged = str(text).strip()
        return merged or previous_summary
    except Exception as err:
        print(f"[ContextBuilder] 摘要生成失败,沿用旧摘要: {err}")
        return previous_summary
