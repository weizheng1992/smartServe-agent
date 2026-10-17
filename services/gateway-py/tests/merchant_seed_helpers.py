"""商户真账测试播种夹具单点(2026-10-17 结算核批次)。

九册手写 merchant_* INSERT 的列清单此前各自为政(5~10 列不一),商户库加列
即需逐册同步 —— 实锤 f45ea23:缺列窄形状在共享容器上传染 43 挂。本模块是
``gateway_py.merchant_db._MERCHANT_DDL`` 的**测试面唯一列清单副本**:商户库
加列只改这里与 DDL 两处。

用法:传入**活跃连接**(``merchant_engine().begin()`` / 测试自有 writer engine
均可),函数只管列清单与 DDL 等值缺省,不启事务、不做清理 —— 清场纪律仍归
各测试册(CT- 前缀唯一编码 + finally 删除,先例 test_store_checkout_coupon)。

断言纪律(同批差分册实证):原价/库存/快照可绝对断言;**实付类金额必须相对
断言**(信封 payable = DB total_amount)—— 共享容器可能有他册残留促销
(store_promotions 残留活动曾把 900 打成 820)。
"""

from __future__ import annotations

import datetime as _dt
import json as _json
from typing import Any

from sqlalchemy import text


def _jsonb(value: dict | str | None) -> str:
    if value is None:
        return "{}"
    return value if isinstance(value, str) else _json.dumps(value, ensure_ascii=False)


async def seed_merchant_order(
    conn: Any,
    *,
    order_id: str,
    customer_id: str,
    total_amount: float,
    status: str = "PAID",
    shipping_address: dict | str | None = None,
    business_id: str = "aurora",
    discount_amount: float = 0.0,
    tracking_info: dict | str | None = None,
    created_at: _dt.datetime | None = None,
    created_at_sql: str | None = None,
    on_conflict_update: bool = False,
) -> None:
    """merchant_orders 全列播种(列清单镜像 _MERCHANT_DDL :65-78 + :96-97 + :262)。

    - total_amount 语义 = 实付(原价 − 优惠),与生产 insert_merchant_order 同口径。
    - created_at / created_at_sql 二选一(后者用于 NOW() - make_interval(...)、
      date_trunc(...) 类相对时间);都不传 = NOW()。
    - on_conflict_update=True → DO UPDATE(状态/金额/租户随新值,order_chain /
      admin_detail 幂等重播种语义)。
    """
    assert not (created_at and created_at_sql), "created_at 与 created_at_sql 二选一"
    conflict = (
        "ON CONFLICT (order_id) DO UPDATE SET status = EXCLUDED.status, "
        "total_amount = EXCLUDED.total_amount, discount_amount = EXCLUDED.discount_amount, "
        "business_id = EXCLUDED.business_id"
        if on_conflict_update
        else "ON CONFLICT (order_id) DO NOTHING"
    )
    # bindparams 纪律:text() 的占位符必须与参数键一一对应(None 分支不得传缺席键)
    params: dict[str, Any] = {
        "oid": order_id,
        "biz": business_id,
        "cid": customer_id,
        "st": status,
        "amt": total_amount,
        "disc": discount_amount,
        "addr": _jsonb(shipping_address),
        "cat": created_at,
    }
    if tracking_info is not None:
        params["track"] = _jsonb(tracking_info)
    await conn.execute(
        text(
            "INSERT INTO merchant_orders (order_id, business_id, customer_id, status, total_amount, "
            "discount_amount, shipping_address, tracking_info, created_at) VALUES "
            "(:oid, :biz, :cid, :st, :amt, :disc, CAST(:addr AS jsonb), "
            f"{'CAST(:track AS jsonb), ' if tracking_info is not None else 'NULL, '}"
            "COALESCE(:cat, " + (created_at_sql if created_at_sql else "NOW()") + ")) "
            + conflict
        ).bindparams(**params)
    )


async def seed_merchant_order_item(
    conn: Any,
    *,
    order_id: str,
    sku_code: str,
    quantity: int = 1,
    price: float = 0.0,
    cost_at_purchase: float = 0.0,
    spu_id: str = "SEED",
    title: str = "",
    sku_title: str = "",
    image_url: str | None = None,
    spec_summary: str | None = None,
    skip_if_exists: bool = False,
) -> None:
    """merchant_order_items 播种(列清单镜像 _MERCHANT_DDL :80-92 + :98)。

    cost_at_purchase 显式列出(缺省 0 与 DDL DEFAULT 同值)—— 快照断言的
    数据基础,严禁因窄形状漏列。skip_if_exists 供幂等重播种(admin_detail)。"""
    values_sql = (
        "SELECT :oid, :spu, :code, :t, :st, :qty, :price, :img, :spec, :cost "
        "WHERE NOT EXISTS (SELECT 1 FROM merchant_order_items WHERE order_id = :oid AND sku_code = :code)"
        if skip_if_exists
        else "VALUES (:oid, :spu, :code, :t, :st, :qty, :price, :img, :spec, :cost)"
    )
    await conn.execute(
        text(
            "INSERT INTO merchant_order_items (order_id, spu_id, sku_code, title, sku_title, quantity, "
            "price, image_url, spec_summary, cost_at_purchase) " + values_sql
        ).bindparams(
            oid=order_id,
            spu=str(spu_id),
            code=sku_code,
            t=title,
            st=sku_title,
            qty=quantity,
            price=price,
            img=image_url,
            spec=spec_summary,
            cost=cost_at_purchase,
        )
    )


async def seed_merchant_spu(
    conn: Any,
    *,
    spu_code: str,
    title: str,
    spu_id: str | None = None,
    category: str | None = None,
    status: str = "ON_SALE",
    main_image: str = "",
) -> None:
    """merchant_spus 单播(列清单镜像 _MERCHANT_DDL :19-34)—— 只需 SPU 无 SKU
    的册(如 SpuCompare);SPU+SKU 成对播种用 seed_merchant_catalog。"""
    cols = (
        "id, spu_code, title, category, main_image, status"
        if spu_id
        else "spu_code, title, category, main_image, status"
    )
    values = (
        f"(CAST('{spu_id}' AS uuid), :sc, :t, :cat, :img, :st)"
        if spu_id
        else "(:sc, :t, :cat, :img, :st)"
    )
    await conn.execute(
        text(
            f"INSERT INTO merchant_spus ({cols}) VALUES {values} ON CONFLICT (spu_code) DO NOTHING"
        ).bindparams(sc=spu_code, t=title, cat=category or "服装鞋包", img=main_image, st=status)
    )


async def seed_merchant_catalog(
    conn: Any,
    *,
    spu_code: str,
    sku_code: str,
    price: float,
    stock: int,
    cost_price: float = 0.0,
    spu_id: str | None = None,
    title: str = "测试商品",
    sku_title: str = "默认规格",
    spec: dict | str = "{}",
    category: str | None = None,
    status: str = "ON_SALE",
    main_image: str = "x.png",
) -> None:
    """SPU+SKU 成对播种(列清单镜像 _MERCHANT_DDL :19-50 + :95)。

    spu_id 传 UUID 字符串时显式落列(需要固定 id 的册,如 analytics 归因),
    缺省由 uuid-ossp 生成并按 spu_code 回查绑定 SKU。幂等:SPU ON CONFLICT
    (spu_code) DO NOTHING,SKU 存在即跳过 —— 与各册既有「存在即返回」同形。"""
    await seed_merchant_spu(
        conn, spu_code=spu_code, title=title, spu_id=spu_id,
        category=category, status=status, main_image=main_image,
    )
    select_id = "CAST(:spu_id AS uuid)" if spu_id else "p.id"
    sku_params: dict[str, Any] = {
        "kc": sku_code,
        "st": sku_title,
        "spec": _jsonb(spec),
        "price": price,
        "cost": cost_price,
        "stock": stock,
        "sc": spu_code,
    }
    if spu_id:
        sku_params["spu_id"] = spu_id
    await conn.execute(
        text(
            "INSERT INTO merchant_skus (spu_id, sku_code, sku_title, spec_attributes, price, cost_price, stock) "
            f"SELECT {select_id}, :kc, :st, CAST(:spec AS jsonb), :price, :cost, :stock "
            "FROM merchant_spus p WHERE p.spu_code = :sc ON CONFLICT DO NOTHING"
        ).bindparams(**sku_params)
    )
