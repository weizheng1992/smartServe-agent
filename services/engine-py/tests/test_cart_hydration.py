"""商城车 → 引擎车水合回归(2026-09-14 用户症状:商城页明明有商品,对客服说
「删除购物车的商品」却回复"购物车还是空的,没有可移除的商品")。

根因:商城 UI 加购只写 localStorage(aurora_store_cart),引擎购物车在 Redis
(agent:cart:{userId}),两条存储互不相通 —— 引擎侧删除/结算/查看只见空车。

钉死 hydrate_cart_from_storefront 契约(幂等合并):
- 商城车条目逐条并入引擎车,skuCode 已在引擎车 → 跳过(严禁覆盖聊天侧数量);
- 二次水合幂等,数量不翻倍;
- 载荷空/全部无效(缺 skuCode/无价)→ 不动,返回 False;
- 任何情况下不抛出 —— 水合失败只降级为「引擎车维持原状」,聊天主链路照常。
"""

from __future__ import annotations

import asyncio

from engine_py.tools_registry.mall_domain import MallDomainService

_USER = {"userId": "CUST-HYDRATE-01", "threadId": "t_hydrate"}

_STORE_ITEMS = [
    {"skuCode": "SPU-AURORA-001-SKU-0", "title": "极光三合一全天候户外硬壳冲锋衣", "price": 1299.0, "quantity": 2},
    {"skuCode": "SPU-AURORA-002-SKU-1", "title": "极光 凉感抗菌速干机能POLO衫", "price": 329.0, "quantity": 1},
]


def test_hydrate_writes_storefront_items_into_engine_cart() -> None:
    async def _run() -> tuple[bool, list[dict]]:
        hydrated = await MallDomainService.hydrate_cart_from_storefront({**_USER, "items": _STORE_ITEMS})
        items = await MallDomainService._load_cart("CUST-HYDRATE-01")
        return hydrated, items or []

    hydrated, items = asyncio.run(_run())
    assert hydrated is True
    assert {i["skuId"] for i in items} == {it["skuCode"] for it in _STORE_ITEMS}
    qty = {i["skuId"]: i["quantity"] for i in items}
    assert qty == {"SPU-AURORA-001-SKU-0": 2, "SPU-AURORA-002-SKU-1": 1}
    price = {i["skuId"]: i["price"] for i in items}
    assert price["SPU-AURORA-001-SKU-0"] == 1299.0


def test_hydrate_merges_into_existing_engine_cart_without_stomping() -> None:
    """幂等合并语义(2026-09-14):引擎车已有时,商城车条目并入(引擎没有的
    补上),既有引擎条目原样保留 —— 引擎车是会话内权威车,严禁覆盖其数量。"""

    async def _run() -> tuple[bool, list[dict]]:
        await MallDomainService.add_to_cart(
            {"skuId": "ENGINE-OWN-SKU", "quantity": 1, "title": "引擎自管理条目", "price": 99.0, **_USER}
        )
        hydrated = await MallDomainService.hydrate_cart_from_storefront({**_USER, "items": _STORE_ITEMS})
        # 二次水合:skuCode 已在引擎车 → 跳过,数量不得翻倍
        hydrated_again = await MallDomainService.hydrate_cart_from_storefront({**_USER, "items": _STORE_ITEMS})
        items = await MallDomainService._load_cart("CUST-HYDRATE-01")
        return hydrated and hydrated_again is False, items or []

    hydrated, items = asyncio.run(_run())
    assert hydrated is True, "首次水合应并入商城车条目"
    qty = {i["skuId"]: i["quantity"] for i in items}
    assert "ENGINE-OWN-SKU" in qty, "既有引擎条目必须原样保留"
    assert qty == {
        "ENGINE-OWN-SKU": 1,
        "SPU-AURORA-001-SKU-0": 2,
        "SPU-AURORA-002-SKU-1": 1,
    }, f"二次水合必须幂等(数量不翻倍): {qty}"


def test_hydrate_noop_on_empty_or_invalid_items() -> None:
    async def _run() -> list[bool]:
        empty = await MallDomainService.hydrate_cart_from_storefront({**_USER, "items": []})
        invalid = await MallDomainService.hydrate_cart_from_storefront(
            {**_USER, "items": [{"title": "无 skuCode 的残缺条目", "quantity": 1}]}
        )
        return [empty, invalid]

    assert asyncio.run(_run()) == [False, False]


def test_hydrate_never_raises_on_garbage_payload() -> None:
    # 注意:断言与水合必须在同一个 asyncio.run 内 —— event_bus 的 Redis 客户端
    # 绑定首个事件循环,跨 asyncio.run 复用即失联(conftest「跨循环毒药」警告)
    async def _run() -> tuple[bool, list[dict]]:
        hydrated = await MallDomainService.hydrate_cart_from_storefront(
            {
                **_USER,
                "items": [
                    {"skuCode": None},
                    "garbage",
                    42,
                    {"skuCode": "NO-PRICE-SKU", "quantity": 1},  # 无价不入车(镜像 add_to_cart 红线)
                    {"skuCode": "OK-SKU", "quantity": "3", "price": 399.0},
                ],
            }
        )
        items = await MallDomainService._load_cart("CUST-HYDRATE-01")
        return hydrated, items or []

    # 垃圾输入逐条容错:可解析的照常入库,不可解析/无价的跳过,绝不抛出
    hydrated, items = asyncio.run(_run())
    assert hydrated is True
    assert [i["skuId"] for i in items] == ["OK-SKU"]
    assert items[0]["quantity"] == 3
    assert items[0]["price"] == 399.0
