"""回归:购物车进程内存失忆 —— 网关重启后引擎车蒸发,与浏览器 localStorage 车分裂。

背景 bug(2026-09-08 用户报告):
用户先问「最近热销的商品」再说「全部加入购物车」,引擎播报
「已成功将 3 款商品加入购物车」,但 storefront 头部购物车计数纹丝不动。

根因链(Playwright 端到端复现钉死):
1. MallDomainService._cart_storage 为进程内存,网关重启即清零
   (用户会话期间网关死过:SSE ERR_INCOMPLETE_CHUNKED_ENCODING / ERR_CONNECTION_REFUSED);
2. 浏览器 localStorage 购物车不受重启影响,仍持有此前同步的 3 款;
3. 引擎(失忆)把 3 款当新车真实写入并播报成功;前端同步桥按 skuCode
   合并时发现条目已存在,quantity 1 覆盖成 1 —— 计数不变。
两头各自为真,合起来即「说成功了但没加入」。

修复语义:购物车写穿透 Redis(agent:cart:{userId}),进程缓存仅作一级读缓存。
本文件从工具层与技能层双断言钉死「重启不失忆」。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.skills.cart_manage_skill import CartManageSkill
from engine_py.tools_registry.mall_domain import MallDomainService

_CANDIDATES = [
    {"id": "prod_a", "name": "测试商品A", "price": 100.0},
    {"id": "prod_b", "name": "测试商品B", "price": 200.0},
    {"id": "prod_c", "name": "测试商品C", "price": 300.0},
]


@pytest.fixture()
def sealed_redis_client(redis_factory):
    """把 event_bus 的懒加载单例指向密封容器;逐测试重置,避免跨事件循环复用。

    每个 sync 测试各自 asyncio.run 独立事件循环,redis.asyncio 客户端连接
    绑定首次使用的循环 —— 缓存的单例跨循环必炸,故进出场都清 _client。
    """
    from engine_py import event_bus
    from engine_py.config import settings

    old_url = settings.redis_url
    old_client = event_bus._client
    # settings 为 frozen dataclass,测试基建显式破冰注入容器地址
    object.__setattr__(settings, "redis_url", redis_factory)
    event_bus._client = None
    yield redis_factory
    event_bus._client = None
    object.__setattr__(settings, "redis_url", old_url)
    if old_client is not None:
        try:
            asyncio.run(old_client.aclose())
        except Exception:
            pass


def _simulate_process_restart() -> None:
    """网关重启对购物车的唯一可见效应:进程缓存清零(Redis 是外部进程,不受影响)。"""
    MallDomainService._cart_storage.clear()


def test_cart_survives_process_restart(sealed_redis_client) -> None:
    async def flow() -> None:
        await MallDomainService.add_to_cart(
            {"skuId": "prod_a", "quantity": 1, "title": "测试商品A", "price": 100.0, "userId": "u_persist"}
        )
        await MallDomainService.add_to_cart(
            {"skuId": "prod_b", "quantity": 2, "title": "测试商品B", "price": 200.0, "userId": "u_persist"}
        )

        _simulate_process_restart()

        assert await MallDomainService.has_cart({"userId": "u_persist"}), "重启后引擎不得认为车是空的"
        summary = await MallDomainService.get_cart_summary({"userId": "u_persist"})
        items = {i["skuId"]: i["quantity"] for i in summary["cart"]["items"]}
        assert items == {"prod_a": 1, "prod_b": 2}, f"重启后购物车应从 Redis 复原,实际: {items}"

        # 重启后再加同款:引擎记得车里有,数量在既有基础上累加(而非从 1 重新起算)
        res = await MallDomainService.add_to_cart(
            {"skuId": "prod_b", "quantity": 1, "title": "测试商品B", "price": 200.0, "userId": "u_persist"}
        )
        quantities = {i["skuId"]: i["quantity"] for i in res["cart"]["items"]}
        assert quantities["prod_b"] == 3, f"重启后重复加购应累量至 3,实际: {quantities}"

    asyncio.run(flow())


def test_cart_delete_survives_process_restart(sealed_redis_client) -> None:
    async def flow() -> None:
        await MallDomainService.add_to_cart(
            {"skuId": "prod_a", "quantity": 1, "title": "测试商品A", "price": 100.0, "userId": "u_del"}
        )
        await MallDomainService.update_cart_item({"skuId": "prod_a", "quantity": 0, "userId": "u_del"})

        _simulate_process_restart()

        assert not await MallDomainService.has_cart({"userId": "u_del"}), "删车后重启不得复活已删条目"
        summary = await MallDomainService.get_cart_summary({"userId": "u_del"})
        landed = [i["skuId"] for i in summary["cart"]["items"]]
        assert "prod_a" not in landed, f"已删除条目不得经重启复活,实际: {landed}"

    asyncio.run(flow())


def test_add_all_after_restart_reports_dup_not_false_success(sealed_redis_client) -> None:
    """用户场景钉死:重启失忆曾致二次「全部加入购物车」播报假成功。

    修复后引擎记得车里有这 3 款,重复加购拦截(产品语义:不自动累量)
    如实播报「未重复加入」—— 播报与 storefront 计数不变自此自洽。

    注:两轮加购收进同一事件循环 —— redis 客户端是跨循环毒药(连接绑死
    首用循环),生产网关单循环常驻无此问题,测试侧须单循环内模拟"重启"
    (重启对购物车的可见效应仅是进程缓存清零,见 _simulate_process_restart)。
    """

    async def flow() -> tuple[str, str]:
        async def _run_add_all(user_id: str) -> str:
            context = {
                "threadId": f"t_{user_id}",
                "tenantId": "ecommerce",
                "userId": user_id,
                "input": "3个全部加入购物车",
                "slots": {"activeIntent": "cart_manage"},
                "extra": {
                    "guideContext": {
                        "candidateProducts": _CANDIDATES,
                        "candidateProductIds": [c["id"] for c in _CANDIDATES],
                    },
                    "cartContext": {},
                },
            }
            return (await CartManageSkill().execute(context))["output"]

        first = await _run_add_all("u_readd")
        _simulate_process_restart()
        second = await _run_add_all("u_readd")
        return first, second

    first, second = asyncio.run(flow())
    assert "已成功将 3 款" in first
    assert "未重复加入" in second, f"重启后二次全量加购必须命中重复拦截,实际播报: {second[:120]}"
    assert "已成功将" not in second, "重启后不得对已在车商品播报假成功 —— 即本回归的原始症状"
