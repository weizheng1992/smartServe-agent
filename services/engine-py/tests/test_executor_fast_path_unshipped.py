"""回归:executor 快路径不得吞掉未发货过滤(2026-09-12 评审发现)。

try_match_executor_fast_path 对「全部订单/历史订单/名下订单」类描述硬编码
listUserOrders args={},LLM 路径的 shippingStatus 提示词到不了快路径 ——
「查询未发货的订单」若走快路径会退化为全量列表,违反 ADR-0001
「每个快捷按钮背后必须有真实能力兜底」。快路径与 LLM 路径必须同语义
(「两路永不漂移」先例)。
"""

from __future__ import annotations

from engine_py.graph.nodes.executor_fast_path import try_match_executor_fast_path


def test_unshipped_list_orders_fast_path_passes_filter() -> None:
    result = try_match_executor_fast_path(
        description="查询用户名下订单中未发货的",
        user_input="查询我未发货的订单",
        allowed_tools=["listUserOrders"],
    )
    assert result == {"toolName": "listUserOrders", "args": {"shippingStatus": "UNSHIPPED"}}


def test_plain_list_orders_fast_path_unchanged() -> None:
    """无未发货语义 = 旧行为零破坏(args={})。"""
    result = try_match_executor_fast_path(
        description="列出名下订单",
        user_input="查询我最近的订单",
        allowed_tools=["listUserOrders"],
    )
    assert result == {"toolName": "listUserOrders", "args": {}}


def test_unshipped_from_user_input_when_description_generic() -> None:
    """描述泛化、语义在用户输入里(如「处理名下订单查询:还没发货的」)也要命中。"""
    result = try_match_executor_fast_path(
        description="处理名下订单查询",
        user_input="还没发货的有哪些",
        allowed_tools=["listUserOrders"],
    )
    assert result == {"toolName": "listUserOrders", "args": {"shippingStatus": "UNSHIPPED"}}
