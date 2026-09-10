"""图节点通用工具 — 镜像 nodes/utils.ts。"""

from __future__ import annotations

from ...triage.intent_registry import EXPLICIT_ORDER_ID_RE  # 单号正则收口 intent_registry(工单04)

# 兼容别名:模块内三处使用点与既有引用保持原名
ORDER_ID_UTIL_RE = EXPLICIT_ORDER_ID_RE


def extract_order_id(
    primary_text: str | None = None,
    secondary_text: str | None = None,
    short_memory: list[dict] | None = None,
) -> str | None:
    """从主文本 / 次文本 / 短期记忆(仅 user 轮)提取订单号并大写。"""
    if primary_text:
        match = ORDER_ID_UTIL_RE.search(primary_text)
        if match:
            return match.group(0).upper()

    if secondary_text:
        match = ORDER_ID_UTIL_RE.search(secondary_text)
        if match:
            return match.group(0).upper()

    for msg in reversed(short_memory or []):
        if msg and msg.get("role") == "user" and msg.get("content"):
            match = ORDER_ID_UTIL_RE.search(msg["content"])
            if match:
                return match.group(0).upper()

    return None
