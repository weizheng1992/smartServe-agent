"""SPI 技能链路线程上下文回归(2026-09-05 双退款事故遗留第二缝)。

triage Skill Fast-Track / 执行器技能派发都会把 threadId/userId 放进
skill.execute(context),但 OrderRefundSkill 调 LocalDbSpiAdapter 时把它丢了:
  - get_order_detail 硬编码 user_id=None → find_order_by_id 跳过商户真单回退,
    拿到 third_party_orders 过期种子状态(事故后 11:09 把已退款单显示为已付款);
  - execute_order_action 硬编码 thread_id=None → process_refund 归属解析为空,
    商户真单幂等守卫全盲 + 商户写穿透被跳过(third_party 假退款、真单纹丝不动)。

三个测试断言(现状红,修复后转绿):
  - test_get_order_detail_must_read_merchant_truth:带 userId 的详情查询必须
    返回商户真单状态,而非 third_party 过期种子
  - test_refund_skill_must_not_blind_refund_again:已 REFUNDED 真单经技能链路
    不得再次被宣称退款成功
  - test_refund_skill_must_write_through_merchant:合法退款经技能链路必须
    物理写穿商户真单(third_party 假写不算)
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from engine_py.skills.contract import SkillContext

REPRO_THREAD = "dbg_repro_thread_spi_ctx"
REPRO_USER = "CUST-SPI-REPRO-1"
ORDER_REFUNDED = "AURORA-ORD-2026-9082"
ORDER_PAID = "AURORA-ORD-2026-9081"
# 商户真单 9082 首次退款落库时间(UTC),重退会刷成 now()
PINNED_UPDATED_AT = "2026-09-05 04:16:14+00"

_MERCHANT_DDL = """
CREATE TABLE IF NOT EXISTS merchant_orders (
    order_id text PRIMARY KEY,
    customer_id text NOT NULL,
    status text NOT NULL,
    total_amount numeric NOT NULL DEFAULT 0,
    currency text DEFAULT 'CNY',
    tracking_info jsonb DEFAULT '{}',
    shipping_address jsonb DEFAULT '{}',
    is_returnable boolean DEFAULT TRUE,
    is_address_modifiable boolean DEFAULT TRUE,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
)
"""

# 与 db/seed_third_party.py 同构的最小 DDL(Alembic 不建此表,容器内需自建)
_THIRD_PARTY_DDL = """
CREATE TABLE IF NOT EXISTS third_party_orders (
  ext_order_sn TEXT PRIMARY KEY,
  merchant_id TEXT NOT NULL,
  customer_id TEXT NOT NULL,
  order_status TEXT NOT NULL,
  order_currency TEXT DEFAULT 'CNY',
  pay_amount REAL NOT NULL,
  recipient_name TEXT NOT NULL,
  recipient_phone TEXT NOT NULL,
  shipping_address TEXT NOT NULL,
  carrier_code TEXT,
  tracking_no TEXT,
  can_modify_address BOOLEAN DEFAULT TRUE,
  can_refund BOOLEAN DEFAULT TRUE,
  order_time TIMESTAMP DEFAULT NOW()
)
"""


async def _setup(pg_factory):
    """密封 PG + 商户镜像表 + third_party 过期种子 + 线程归属行。"""
    from engine_py.tools_registry import order_domain

    engine = pg_factory.kw["bind"]
    url = engine.url.render_as_string(hide_password=False)
    merchant_engine = create_async_engine(url, poolclass=NullPool)

    async with merchant_engine.begin() as conn:
        await conn.execute(text(_MERCHANT_DDL))
        await conn.execute(text(_THIRD_PARTY_DDL))
        await conn.execute(text("TRUNCATE merchant_orders"))
        await conn.execute(
            text(
                "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, currency, "
                "is_returnable, is_address_modifiable, created_at, updated_at) VALUES "
                "(:oid, :uid, :st, 49, 'CNY', TRUE, TRUE, '2026-09-04 10:00:00+00', CAST(:upd AS timestamptz))"
            ).bindparams(oid=ORDER_REFUNDED, uid=REPRO_USER, st="REFUNDED", upd=PINNED_UPDATED_AT)
        )
        await conn.execute(
            text(
                "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, currency, "
                "is_returnable, is_address_modifiable, created_at, updated_at) VALUES "
                "(:oid, :uid, 'PAID', 49, 'CNY', TRUE, TRUE, '2026-09-04 10:00:00+00', '2026-09-05 04:00:00+00')"
            ).bindparams(oid=ORDER_PAID, uid=REPRO_USER)
        )
        # third_party 过期种子:两单都停留在 PAID(会话开始前的快照)
        await conn.execute(text("TRUNCATE third_party_orders"))
        await conn.execute(
            text(
                "INSERT INTO third_party_orders (ext_order_sn, merchant_id, customer_id, order_status, "
                "pay_amount, recipient_name, recipient_phone, shipping_address) "
                "VALUES (:oid, 'aurora', :uid, 'PAID', 49, '测试客户', '13800138000', '北京市海淀区')"
            ).bindparams(oid=ORDER_REFUNDED, uid=REPRO_USER)
        )
        await conn.execute(
            text(
                "INSERT INTO third_party_orders (ext_order_sn, merchant_id, customer_id, order_status, "
                "pay_amount, recipient_name, recipient_phone, shipping_address) "
                "VALUES (:oid, 'aurora', :uid, 'PAID', 49, '测试客户', '13800138000', '北京市海淀区')"
            ).bindparams(oid=ORDER_PAID, uid=REPRO_USER)
        )

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM threads WHERE id = :t").bindparams(t=REPRO_THREAD))
        await conn.execute(
            text(
                "INSERT INTO threads (id, user_id, business_id, status, created_at, updated_at) "
                "VALUES (:t, :u, 'aurora', 'active', now(), now())"
            ).bindparams(t=REPRO_THREAD, u=REPRO_USER)
        )

    original = order_domain._merchant_reader_engine
    original_writer = order_domain._merchant_writer_engine
    order_domain._merchant_reader_engine = lambda: merchant_engine
    # 阶段①读写分离(wayfinder 09-D4):写穿透走独立写引擎,测试必须同指容器
    order_domain._merchant_writer_engine = lambda: merchant_engine
    return engine, merchant_engine, (original, original_writer)


async def _teardown(engine, merchant_engine, original):
    from engine_py.tools_registry import order_domain

    order_domain._merchant_reader_engine, order_domain._merchant_writer_engine = original
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM threads WHERE id = :t").bindparams(t=REPRO_THREAD))
    async with merchant_engine.begin() as conn:
        await conn.execute(text("TRUNCATE merchant_orders, third_party_orders"))
    await merchant_engine.dispose()


async def _third_party_status(merchant_engine, order_id: str) -> str | None:
    async with merchant_engine.connect() as conn:
        return (
            await conn.execute(
                text("SELECT order_status FROM third_party_orders WHERE ext_order_sn = :o").bindparams(o=order_id)
            )
        ).scalar()


def _skill_context(order_id: str) -> SkillContext:
    """triage fast-track / 执行器技能派发的真实 context 形态(线程上下文齐全)。"""
    return SkillContext(
        thread_id=REPRO_THREAD,
        tenant_id="aurora",
        user_id=REPRO_USER,
        input=f"帮我申请订单 {order_id} 的退款",
        slots={"orderId": order_id, "reason": "全额退款", "refundAmount": 49.00, "activeIntent": "order_return"},
        is_approved=True,
    )


async def _merchant_status(merchant_engine, order_id: str):
    async with merchant_engine.connect() as conn:
        return (
            (
                await conn.execute(
                    text("SELECT status, updated_at FROM merchant_orders WHERE order_id = :o").bindparams(o=order_id)
                )
            )
            .mappings()
            .first()
        )


def test_get_order_detail_must_read_merchant_truth(pg_factory):
    """带用户身份的订单详情必须以商户真单为事实源(现状红:拿到 third_party PAID)。"""
    asyncio.run(_detail_scenario(pg_factory))


async def _detail_scenario(pg_factory):
    engine, merchant_engine, original = await _setup(pg_factory)
    try:
        from engine_py.skills.spi_client import LocalDbSpiAdapter

        order = await LocalDbSpiAdapter().get_order_detail(
            {
                "orderId": ORDER_REFUNDED,
                "userId": REPRO_USER,
                "threadId": REPRO_THREAD,
                "tenantId": "aurora",
            }
        )
        assert order is not None, "订单应可查到"
        assert order["status"] == "REFUNDED", (
            f"技能侧详情查询读到过期种子状态 {order['status']},应为商户真单 REFUNDED"
        )
    finally:
        await _teardown(engine, merchant_engine, original)


def test_refund_skill_must_not_blind_refund_again(pg_factory):
    """已退款真单经技能链路不得被再次退款(现状红:基于过期 PAID 盲退并宣称成功)。"""
    asyncio.run(_blind_refund_scenario(pg_factory))


async def _blind_refund_scenario(pg_factory):
    from datetime import datetime

    engine, merchant_engine, original = await _setup(pg_factory)
    try:
        from engine_py.skills.order_skills import OrderRefundSkill

        result = await OrderRefundSkill().execute(_skill_context(ORDER_REFUNDED))

        row = await _merchant_status(merchant_engine, ORDER_REFUNDED)
        assert row["updated_at"].isoformat() == datetime.fromisoformat(PINNED_UPDATED_AT).isoformat(), (
            f"已退款真单被物理改写:updated_at {row['updated_at']}"
        )
        # third_party 过期种子同样不得被物理改写(假退款也是退款)
        assert await _third_party_status(merchant_engine, ORDER_REFUNDED) == "PAID", (
            "已 REFUNDED 订单经技能链路又发生了一次物理退款写(third_party 被改写)"
        )
        assert result.success is not True, (
            f"已 REFUNDED 订单经技能链路被再次宣称退款成功: {result.get('output')}"
        )
    finally:
        await _teardown(engine, merchant_engine, original)


def test_refund_skill_must_write_through_merchant(pg_factory):
    """合法退款经技能链路必须写穿商户真单(现状红:只假写 third_party,真单纹丝不动)。"""
    asyncio.run(_write_through_scenario(pg_factory))


async def _write_through_scenario(pg_factory):
    engine, merchant_engine, original = await _setup(pg_factory)
    try:
        from engine_py.skills.order_skills import OrderRefundSkill

        result = await OrderRefundSkill().execute(_skill_context(ORDER_PAID))
        assert result.success is True, f"合法退款应成功,实际: {result.error or result.output}"

        row = await _merchant_status(merchant_engine, ORDER_PAID)
        assert row["status"] == "REFUNDED", (
            f"技能链路退款未写穿商户真单,商户侧仍为 {row['status']}"
        )
    finally:
        await _teardown(engine, merchant_engine, original)
