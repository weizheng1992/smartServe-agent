"""socket send_message cards 载荷闭集闸(客服优化批,2026-10-25)。

坐席台开始主动推卡片(desk-link send_message 携 cards)后,cards 槽不再是无
校验透传 —— 任意形状此前可原样落库 messages.cards 并桥到顾客 SSE(注入面)。
本册钉死:
- 合法卡(order_card)经 operator 路:ack 成功 + new_message 载荷含 cards + 落库;
- 闭集外 type / 缺 data 对象 / 非列表形状:ack success=False 诚实拒绝,
  零落库零广播。

卡片类型闭集对齐 packages/types card.ts RichCardType(11 型);卡片内 actions
的闭集不在此层校验(渲染端 CARD_ACTION_STRATEGIES 未登记动作返回 null 兜底,
不猜 —— merchant.md §3)。
"""

from __future__ import annotations

import uuid as _uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa

from .conftest import create_thread, wait_for

pytestmark = pytest.mark.asyncio(loop_scope="session")

_NS = "/ws/chat"


async def _message_count(tid: str, content_like: str) -> int:
    from engine_py.db import get_session

    async with get_session() as session:
        return (
            await session.execute(
                sa.text("SELECT COUNT(*) FROM messages WHERE thread_id = :t AND content LIKE :c"),
                {"t": tid, "c": f"%{content_like}%"},
            )
        ).scalar() or 0


@pytest_asyncio.fixture(loop_scope="session")
async def cards_thread(seeded) -> str:
    tid = f"cards_gate_{str(_uuid.uuid4())[:8]}"
    await create_thread(tid, f"u_{tid}", "nike")
    return tid


@pytest_asyncio.fixture(loop_scope="session")
async def operator_sock(live_server, nike_operator, cards_thread):
    """已认领 cards_thread 的坐席连接(发言闸:未接管禁言)。"""
    import socketio as socketio_lib

    sock = socketio_lib.AsyncClient(reconnection=False)
    await sock.connect(
        live_server,
        transports=["websocket"],
        namespaces=[_NS],
        auth={"tenantId": "nike", "userId": "u_cards_op", "role": "operator", "token": nike_operator["token"]},
    )
    join_ack = await sock.call(
        "join_thread", {"threadId": cards_thread, "tenantId": "nike", "role": "operator"}, namespace=_NS, timeout=5
    )
    assert join_ack["success"] is True
    takeover_ack = await sock.call(
        "takeover_conversation", {"threadId": cards_thread, "tenantId": "nike"}, namespace=_NS, timeout=5
    )
    assert takeover_ack["success"] is True
    yield sock
    if sock.connected:
        await sock.disconnect()


class TestCardsGate:
    async def test_operator_push_valid_card_persists_and_broadcasts(self, live_server, operator_sock, cards_thread):
        """合法 order_card:ack 成功 + 房间 new_message 载荷含 cards + 落库。"""
        received: list[dict] = []
        operator_sock.on("new_message", lambda p=None: received.append(p or {}), namespace=_NS)
        card = {
            "type": "order_card",
            "data": {
                "orderId": "ORD-CARDS-1",
                "status": "待发货",
                "totalAmount": 199,
                "actions": [{"label": "查看物流轨迹", "action": "track_order", "payload": {"orderId": "ORD-CARDS-1"}}],
            },
        }
        marker = "为您找到该订单:"
        ack = await operator_sock.call(
            "send_message",
            {"threadId": cards_thread, "tenantId": "nike", "role": "operator", "content": marker, "cards": [card]},
            namespace=_NS,
            timeout=5,
        )
        assert ack["success"] is True, ack
        assert "messageId" in ack
        await wait_for(lambda: bool(received))
        assert received[0]["cards"] == [card], "new_message 载荷必须原样携带 cards"
        assert await _message_count(cards_thread, marker) == 1, "卡片消息必须落库"

    async def test_unknown_card_type_rejected_zero_side_effect(self, live_server, operator_sock, cards_thread):
        """闭集外 type:ack success=False 诚实拒绝,零落库。"""
        marker = "闭集外卡"
        ack = await operator_sock.call(
            "send_message",
            {
                "threadId": cards_thread,
                "tenantId": "nike",
                "role": "operator",
                "content": marker,
                "cards": [{"type": "evil_script", "data": {"x": 1}}],
            },
            namespace=_NS,
            timeout=5,
        )
        assert ack["success"] is False
        assert "卡片" in ack.get("error", "")
        assert await _message_count(cards_thread, marker) == 0, "拒绝载荷不得落库"

    async def test_card_without_data_object_rejected(self, live_server, operator_sock, cards_thread):
        """卡缺 data 对象:拒绝(渲染端 RichCardRenderer 按 data 判别联合消费)。"""
        marker = "缺data卡"
        ack = await operator_sock.call(
            "send_message",
            {
                "threadId": cards_thread,
                "tenantId": "nike",
                "role": "operator",
                "content": marker,
                "cards": [{"type": "order_card", "data": "not-an-object"}],
            },
            namespace=_NS,
            timeout=5,
        )
        assert ack["success"] is False
        assert await _message_count(cards_thread, marker) == 0

    async def test_non_list_cards_shape_rejected(self, live_server, operator_sock, cards_thread):
        """cards 非列表形状(字符串/对象):拒绝。"""
        marker = "坏形状卡"
        ack = await operator_sock.call(
            "send_message",
            {"threadId": cards_thread, "tenantId": "nike", "role": "operator", "content": marker, "cards": "order_card"},
            namespace=_NS,
            timeout=5,
        )
        assert ack["success"] is False
        assert await _message_count(cards_thread, marker) == 0
