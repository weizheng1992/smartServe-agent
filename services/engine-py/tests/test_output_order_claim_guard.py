"""订单宣称反幻觉硬闸(2026-09-13 用户实报:幻觉单号自增殖)。"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.graph.nodes.output_guard import sanitize_order_claims


def _plan_with_checkout(order_id: str) -> dict:
    return {
        "subtasks": [
            {
                "id": "step_fast_cart_1",
                "description": "Call checkoutCart to place a real order",
                "result": {"success": True, "output": f"下单成功！订单号 [{order_id}]。"},
            }
        ]
    }


class TestOrderClaimGuard:
    def test_no_claim_passes_through(self):
        out = "为您推荐以下短袖商品:1. 【极光 T恤】¥269"
        assert asyncio.run(sanitize_order_claims(out, None)) == out

    def test_claim_backed_by_real_checkout_passes(self):
        out = "已成功结算下单,订单号 AURORA-ORD-2026-5320。"
        assert asyncio.run(sanitize_order_claims(out, _plan_with_checkout("AURORA-ORD-2026-5320"))) == out

    def test_unbacked_order_id_stripped(self, monkeypatch):
        from engine_py.graph.nodes import output_guard as og

        async def _not_exists(order_id: str) -> bool:
            return False

        monkeypatch.setattr(og, "_order_exists", _not_exists)
        out = "已成功结算下单,订单号 AURORA-ORD-2026-2477。运费 12 元。"
        cleaned = asyncio.run(og.sanitize_order_claims(out, None))
        assert "2477" not in cleaned
        assert "没有产生真实订单" in cleaned

    def test_unbacked_narrative_without_id_stripped(self):
        """复现轮形态:不报单号但宣称「成功完成结算下单」——同样拦截。"""
        out = "热销短袖已推荐。系统已为您成功完成结算下单。物流由顺丰承运。"
        cleaned = asyncio.run(sanitize_order_claims(out, None))
        assert "成功完成结算下单" not in cleaned
        assert "没有产生真实订单" in cleaned
        assert "顺丰承运" in cleaned, "非宣称内容保留"

    def test_real_checkout_result_ids_count_as_backed(self):
        plan = {
            "subtasks": [
                {
                    "id": "s1",
                    "description": "Call checkoutCart to place a real order",
                    "result": {"success": True, "output": "下单成功!订单号 [AURORA-ORD-2026-7777]。"},
                }
            ]
        }
        out = "下单成功,订单号 AURORA-ORD-2026-7777"
        assert asyncio.run(sanitize_order_claims(out, plan)) == out


if __name__ == "__main__":
    pytest.main([__file__])

