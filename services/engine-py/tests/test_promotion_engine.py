"""优惠引擎规则单测(20-D1/D3;服务端唯一算价点的确定性契约)。"""

from __future__ import annotations

from datetime import UTC

import pytest

from engine_py.analytics.promo_kernel import compute_discount, in_window


def promo(ptype, value, threshold=None, scope="all", scope_value=None):
    return {"promo_type": ptype, "discount_value": value, "threshold_amount": threshold,
            "scope_type": scope, "scope_value": scope_value}


class TestComputeDiscount:
    def test_full_reduction_requires_threshold(self):
        assert compute_discount(promo("full_reduction", 50, 400), 399.99) is None
        assert compute_discount(promo("full_reduction", 50, 400), 400.0) == 50.0

    def test_discount_rate(self):
        assert compute_discount(promo("discount", 88), 1299.0) == pytest.approx(155.88)
        assert compute_discount(promo("discount", 88), 100.0) == pytest.approx(12.0)

    def test_coupon_capped_at_amount(self):
        assert compute_discount(promo("coupon", 100), 80.0) == 80.0  # 券额>实付:不为负
        assert compute_discount(promo("coupon", 30), 80.0) == 30.0

    def test_unknown_type_is_none(self):
        assert compute_discount(promo("mystery", 10), 100.0) is None


class TestWindow:
    def testin_window(self):
        from datetime import datetime
        p = {"start_at": datetime(2026, 9, 1, tzinfo=UTC), "end_at": datetime(2026, 9, 30, tzinfo=UTC)}
        assert in_window(p, datetime(2026, 9, 15, tzinfo=UTC))
        assert not in_window(p, datetime(2026, 10, 1, tzinfo=UTC))
        assert in_window({"start_at": None, "end_at": None}, datetime(2026, 9, 15, tzinfo=UTC))

    def test_default_clock_is_utc_not_local(self):
        """缺省钟与库钟同源(UTC):start_at/end_at 由 NOW() 列默认落 naive UTC,
        本地 naive now(本机 UTC+8)把「4h 后结束」误判已结束 —— 结算候选被
        整体砍掉未来 8h 内到期的活动(2026-09-29 夜审 F15 波及复核;旧实现
        本用例必红)。"""
        from datetime import datetime, timedelta

        soon_end = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=4)
        assert in_window({"start_at": None, "end_at": soon_end})


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
                # 对齐商户生产形(S5 幂等迁移):容器表出自引擎 alembic 旧形,
                # 租户谓词实测须补列 —— 与 merchant_db.py DDL 同款。
                await conn.execute(text(
                    "ALTER TABLE promotions ADD COLUMN IF NOT EXISTS "
                    "business_id VARCHAR(64) NOT NULL DEFAULT 'aurora'"
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
                rows = await fetch_active_promos(conn, "aurora")
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


class _CaptureConn:
    """SQL 捕获连接:记录待执行语句,返回空行集 —— 租户谓词契约的免 DB 接缝。"""

    def __init__(self):
        self.captured = None

    async def execute(self, stmt, *args, **kwargs):
        self.captured = stmt

        class _Rows:
            def mappings(self):
                return self

            def all(self):
                return []

        return _Rows()


class TestListUsableUserCouponsTenantGuard:
    """租户谓词无条件携带(2026-10-14 夜评 Standards 轴:S5 租户列收口后,
    条件谓词形状(`+ ("AND uc.business_id = :b" if biz else "")`)在显参与
    上下文双缺时产出无租户限定的裸查 —— database-schema.md §1.2 硬违规形状。
    修后走 tenant_context.resolve_business_id(显式 > 上下文 > 平台默认
    +warning 留痕),谓词恒在;读路径永不抛(不变量 #4)由解析器兜底保证。"""

    @staticmethod
    def _run(coupons_conn, business_id=None):
        import asyncio

        from engine_py.analytics.promotion_engine import list_usable_user_coupons

        asyncio.run(list_usable_user_coupons(coupons_conn, "CUST-TG-1", 100.0, business_id))

    def _binds(self, conn):
        return {k: v.value for k, v in conn.captured._bindparams.items()}

    def test_explicit_tenant_normalizes_and_predicate_always_present(self):
        conn = _CaptureConn()
        self._run(conn, "Nike ")
        assert "AND uc.business_id = :b" in str(conn.captured)
        assert self._binds(conn)["b"] == "nike"

    def test_context_tenant_used_when_explicit_missing(self):
        from engine_py.tenant_context import reset_business_context, set_business_context

        conn = _CaptureConn()
        token = set_business_context("Aurora")
        try:
            self._run(conn)
        finally:
            reset_business_context(token)
        assert "AND uc.business_id = :b" in str(conn.captured)
        assert self._binds(conn)["b"] == "aurora"

    def test_no_context_falls_back_to_platform_default_with_warning(self, caplog):
        import logging

        conn = _CaptureConn()
        with caplog.at_level(logging.WARNING, logger="engine_py.tenant_context"):
            self._run(conn)
        assert self._binds(conn)["b"] == "ecommerce"
        assert "[tenant-context]" in caplog.text, "双缺兜底必须 warning 留痕(resolve_business_id 契约)"


class TestFetchActivePromosTenantGuard:
    """活动候选集租户谓词(2026-10-14 夜评深查第二处 🔴:d3405ed 收口了券查询,
    fetch_active_promos 的 SQL 仍零 business 条件 —— 跨租户活动可被自动择优
    结算(结算链活动分支)与前台可见(促销三路由)。修法与券查询同源:
    resolve_business_id 三段式,谓词恒在,读路径永不抛(不变量 #4)。"""

    @staticmethod
    def _run(promos_conn, business_id=None):
        import asyncio

        from engine_py.analytics.promotion_engine import fetch_active_promos

        asyncio.run(fetch_active_promos(promos_conn, business_id))

    def _binds(self, conn):
        return {k: v.value for k, v in conn.captured._bindparams.items()}

    def test_explicit_tenant_normalizes_and_predicate_always_present(self):
        conn = _CaptureConn()
        self._run(conn, "Nike ")
        assert "AND business_id = :b" in str(conn.captured)
        assert self._binds(conn)["b"] == "nike"

    def test_context_tenant_used_when_explicit_missing(self):
        from engine_py.tenant_context import reset_business_context, set_business_context

        conn = _CaptureConn()
        token = set_business_context("Aurora")
        try:
            self._run(conn)
        finally:
            reset_business_context(token)
        assert "AND business_id = :b" in str(conn.captured)
        assert self._binds(conn)["b"] == "aurora"

    def test_no_context_falls_back_to_platform_default_with_warning(self, caplog):
        import logging

        conn = _CaptureConn()
        with caplog.at_level(logging.WARNING, logger="engine_py.tenant_context"):
            self._run(conn)
        assert self._binds(conn)["b"] == "ecommerce"
        assert "[tenant-context]" in caplog.text, "双缺兜底必须 warning 留痕(resolve_business_id 契约)"


class TestSettlementTenantIsolation:
    """结算活动分支跨租户隔离(密封 PG):he商家 B 的活动不得被商家 A 的
    结算自动择优命中 —— 夜评 10-14 🔴 的资金面语义(券分支 d3405ed 已闸,
    活动分支本补)。fetch_active_promos 与 best_for_amount 双缝实测。"""

    def test_cross_tenant_promos_invisible(self, pg_factory):
        import asyncio

        from sqlalchemy import text

        from engine_py.analytics.promotion_engine import best_for_amount, fetch_active_promos

        async def scenario():
            engine = pg_factory.kw["bind"]
            async with engine.begin() as conn:
                await conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS promotions ("
                    " id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
                    " business_id VARCHAR(64) NOT NULL DEFAULT 'aurora',"
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
                # 同上:容器表 alembic 旧形,补租户列对齐商户生产形。
                await conn.execute(text(
                    "ALTER TABLE promotions ADD COLUMN IF NOT EXISTS "
                    "business_id VARCHAR(64) NOT NULL DEFAULT 'aurora'"
                ))
                await conn.execute(text("DELETE FROM promotions WHERE name LIKE 'E2E-TENANT-%'"))
                await conn.execute(text(
                    "INSERT INTO promotions (business_id, name, promo_type, discount_value, status) "
                    "VALUES ('aurora', 'E2E-TENANT-AURORA', 'full_reduction', 50, 'active')"
                ))
                await conn.execute(text(
                    "INSERT INTO promotions (business_id, name, promo_type, discount_value, status) "
                    "VALUES ('nike', 'E2E-TENANT-NIKE', 'full_reduction', 80, 'active')"
                ))
                try:
                    by_tenant = {b: await fetch_active_promos(conn, b) for b in ("aurora", "nike")}
                    aurora_best = await best_for_amount(conn, 500.0, None, exclude_coupon=True, business_id="aurora")
                    nike_best = await best_for_amount(conn, 500.0, None, exclude_coupon=True, business_id="nike")
                    cross_tenant_best = await best_for_amount(conn, 500.0, None, exclude_coupon=True, business_id="missing")
                finally:
                    await conn.execute(text("DELETE FROM promotions WHERE name LIKE 'E2E-TENANT-%'"))
                return by_tenant, aurora_best, nike_best, cross_tenant_best

        by_tenant, aurora_best, nike_best, cross_tenant_best = asyncio.run(scenario())
        # 共享容器含相邻套件残留行,断言取包含式(见 test_store_checkout_coupon
        # 文件头纪律):本套种子行按租户各归其位,互不可见
        aurora_names = {r["name"] for r in by_tenant["aurora"]}
        nike_names = {r["name"] for r in by_tenant["nike"]}
        assert "E2E-TENANT-AURORA" in aurora_names and "E2E-TENANT-NIKE" not in aurora_names
        assert "E2E-TENANT-NIKE" in nike_names and "E2E-TENANT-AURORA" not in nike_names
        # 结算自动择优只见本租户活动:跨租户候选恒空
        assert aurora_best is not None and nike_best is not None
        assert cross_tenant_best is None, "他租活动不得进结算候选"
