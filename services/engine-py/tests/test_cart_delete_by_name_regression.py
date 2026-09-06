"""回归:按名称删除购物车商品 —— 点名商品必须是被删的那个。

背景 bug(2026-09-06 用户报告):
购物车含 Pegasus(899)+Invincible(1299)+Windrunner(599) 三款,
用户说"Nike ZoomX Invincible Run 3 旗舰缓震跑鞋 从购物车去掉",实际删掉的
是 Windrunner 夹克(删除分支无名称匹配,兜底 lastModifiedItemId/items[0]),
且回复称"0 件商品"与"总金额 ¥2198"自相矛盾(update_cart_item 响应缺
totalQuantity,技能侧 `or 0` 回退)。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.skills.cart_manage_skill import CartManageSkill
from engine_py.tools_registry.mall_domain import MallDomainService

_USER = "u_delname"

_INITIAL_ITEMS = [
    {"skuId": "prod_nike_air_pegasus_41", "title": "Nike Air Zoom Pegasus 41 极速轻量透气跑鞋", "price": 899.0, "quantity": 1},
    {"skuId": "prod_nike_invincible_3", "title": "Nike ZoomX Invincible Run 3 旗舰缓震跑鞋", "price": 1299.0, "quantity": 1},
    {"skuId": "prod_nike_windrunner_jacket", "title": "Nike Windrunner 连帽运动风行者夹克外套", "price": 599.0, "quantity": 1},
]


def _run_skill(user_input: str) -> dict:
    # 复刻全量加购后的状态:三款在车,lastModifiedItemId 指向最后一款(Windrunner)
    MallDomainService._cart_storage[_USER] = [dict(i) for i in _INITIAL_ITEMS]
    context = {
        "threadId": "t_delname",
        "tenantId": "ecommerce",
        "userId": _USER,
        "input": user_input,
        "slots": {"activeIntent": "cart_manage"},
        "extra": {
            "guideContext": {},
            "cartContext": {
                "lastModifiedItemId": "prod_nike_windrunner_jacket",
                "items": _INITIAL_ITEMS,
                "totalAmount": 2797.0,
            },
        },
    }
    return asyncio.run(CartManageSkill().execute(context))


def _remaining() -> list[str]:
    return [i["skuId"] for i in MallDomainService._cart_storage.get(_USER, [])]


def test_delete_by_full_name_removes_named_item() -> None:
    res = _run_skill("Nike ZoomX Invincible Run 3 旗舰缓震跑鞋 从购物车去掉")
    assert res["success"] is True
    # 🔴 症状 1:点名 Invincible,被删的必须是 Invincible,不是 Windrunner
    assert "prod_nike_invincible_3" not in _remaining(), f"实际入删: 剩余 {_remaining()}"
    assert "prod_nike_windrunner_jacket" in _remaining(), "夹克不应被误删"
    assert "prod_nike_air_pegasus_41" in _remaining()


def test_delete_message_count_consistent_with_cart() -> None:
    res = _run_skill("Nike ZoomX Invincible Run 3 旗舰缓震跑鞋 从购物车去掉")
    remaining_qty = sum(i["quantity"] for i in MallDomainService._cart_storage.get(_USER, []))
    # 🔴 症状 2:购物车非空时回复不得声称"0 件商品"
    assert remaining_qty == 2
    assert "0 件商品" not in res["output"], f"回复与实际购物车矛盾: {res['output']}"
