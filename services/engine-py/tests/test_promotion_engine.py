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


class TestFetchActivePromosWindow:
    """结算候选窗口闸(2026-09-27 运营闭环;密封 PG,promotions 表为 merchant
    库 DDL 的容器内复制,session 级共享)。历史 bug:SELECT 漏 start_at,
    下游 _in_window 读 None 恒过 —— 未来开始的活动会立即进结算。"""

    def test_future_start_excluded_and_columns_present(self, pg_factory):
        import asyncio

        from sqlalchemy import text

        from engine_py.analytics.promotion_engine import fetch_active_promos

        async def scenario():
            engine = pg_factory.kw["bind"]
            async with engine.begin() as conn:
                await conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS promotions ("
                    " id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
                    " name TEXT NOT NULL,"
                    " promo_type TEXT NOT NULL,"
                    " threshold_amount NUMERIC(10,2),"
                    " discount_value NUMERIC(10,2) NOT NULL,"
                    " scope_type TEXT NOT NULL DEFAULT 'all',"
                    " scope_value TEXT,"
                    " status TEXT NOT NULL DEFAULT 'active',"
                    " start_at TIMESTAMP NOT NULL DEFAULT NOW(),"
                    " end_at TIMESTAMP,"
                    " created_at TIMESTAMP NOT NULL DEFAULT NOW(),"
                    " total_quota INT)"
                ))
                await conn.execute(text("DELETE FROM promotions WHERE name LIKE 'E2E-WINDOW-%'"))
                await conn.execute(text(
                    "INSERT INTO promotions (name, promo_type, discount_value, status, start_at) "
                    "VALUES ('E2E-WINDOW-FUTURE', 'full_reduction', 50, 'active', NOW() + interval '1 day')"
                ))
                await conn.execute(text(
                    "INSERT INTO promotions (name, promo_type, discount_value, status, start_at) "
                    "VALUES ('E2E-WINDOW-RUNNING', 'full_reduction', 50, 'active', NOW() - interval '1 hour')"
                ))
                rows = await fetch_active_promos(conn)
                await conn.execute(text("DELETE FROM promotions WHERE name LIKE 'E2E-WINDOW-%'"))
                return rows

        rows = asyncio.run(scenario())
        names = {r["name"] for r in rows}
        assert "E2E-WINDOW-FUTURE" not in names, "未来开始的活动严禁进结算候选"
        assert "E2E-WINDOW-RUNNING" in names
        running = next(r for r in rows if r["name"] == "E2E-WINDOW-RUNNING")
        # SELECT 必须带出窗口两列(下游 _in_window 的数据来源)
        assert running["start_at"] is not None
        assert "end_at" in running
