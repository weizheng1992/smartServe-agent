"""优惠引擎规则单测(20-D1/D3;服务端唯一算价点的确定性契约)。"""

from __future__ import annotations

from datetime import UTC

import pytest

from engine_py.analytics.promotion_engine import _compute_discount, _in_window


def promo(ptype, value, threshold=None, scope="all", scope_value=None):
    return {"promo_type": ptype, "discount_value": value, "threshold_amount": threshold,
            "scope_type": scope, "scope_value": scope_value}


class TestComputeDiscount:
    def test_full_reduction_requires_threshold(self):
        assert _compute_discount(promo("full_reduction", 50, 400), 399.99) is None
        assert _compute_discount(promo("full_reduction", 50, 400), 400.0) == 50.0

    def test_discount_rate(self):
        assert _compute_discount(promo("discount", 88), 1299.0) == pytest.approx(155.88)
        assert _compute_discount(promo("discount", 88), 100.0) == pytest.approx(12.0)

    def test_coupon_capped_at_amount(self):
        assert _compute_discount(promo("coupon", 100), 80.0) == 80.0  # 券额>实付:不为负
        assert _compute_discount(promo("coupon", 30), 80.0) == 30.0

    def test_unknown_type_is_none(self):
        assert _compute_discount(promo("mystery", 10), 100.0) is None


class TestWindow:
    def test_in_window(self):
        from datetime import datetime
        p = {"start_at": datetime(2026, 9, 1, tzinfo=UTC), "end_at": datetime(2026, 9, 30, tzinfo=UTC)}
        assert _in_window(p, datetime(2026, 9, 15, tzinfo=UTC))
        assert not _in_window(p, datetime(2026, 10, 1, tzinfo=UTC))
        assert _in_window({"start_at": None, "end_at": None}, datetime(2026, 9, 15, tzinfo=UTC))
