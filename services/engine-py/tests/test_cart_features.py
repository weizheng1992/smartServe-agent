"""购物车功能面全量回归:查看/清空/删除(名称·序数·兜底)/改量(名称·序数)/
重复加购拦截(单品·全量部分·全量全部)/删后再加/指引话术闭环。

真实 MallDomainService 内存购物车(无 stub),逐测试独立 user 隔离。
产品语义(2026-09-06):重复加购不自动累量 —— 拦截 + 提示当前数量与改量入口。
"""

from __future__ import annotations

import asyncio

from engine_py.skills.cart_manage_skill import CartManageSkill
from engine_py.tools_registry.mall_domain import MallDomainService

_PEG = {"skuId": "prod_nike_air_pegasus_41", "title": "Nike Air Zoom Pegasus 41 极速轻量透气跑鞋", "price": 899.0, "quantity": 1}
_INV = {"skuId": "prod_nike_invincible_3", "title": "Nike ZoomX Invincible Run 3 旗舰缓震跑鞋", "price": 1299.0, "quantity": 1}
_WIND = {"skuId": "prod_nike_windrunner_jacket", "title": "Nike Windrunner 连帽运动风行者夹克外套", "price": 599.0, "quantity": 1}

_CANDIDATES = [
    {"id": _PEG["skuId"], "name": _PEG["title"], "price": 899.0},
    {"id": _INV["skuId"], "name": _INV["title"], "price": 1299.0},
    {"id": _WIND["skuId"], "name": _WIND["title"], "price": 599.0},
]


def _seed(user: str, items: list[dict]) -> None:
    MallDomainService._cart_storage[user] = [dict(i) for i in items]


def _cart(user: str) -> dict[str, int]:
    """skuId -> quantity 快照。"""
    return {i["skuId"]: i["quantity"] for i in MallDomainService._cart_storage.get(user, [])}


def _run(user: str, text: str, *, last_modified: str | None = None) -> dict:
    # 注意:不清 storage —— 各测试用 _seed 显式铺场,多轮场景依赖累积态
    ctx = {
        "threadId": f"t_{user}",
        "tenantId": "ecommerce",
        "userId": user,
        "input": text,
        "slots": {"activeIntent": "cart_manage"},
        "extra": {
            "guideContext": {"candidateProducts": _CANDIDATES, "candidateProductIds": [c["id"] for c in _CANDIDATES]},
            "cartContext": {"lastModifiedItemId": last_modified} if last_modified else {},
        },
    }
    return asyncio.run(CartManageSkill().execute(ctx))


# ---------------------------------------------------------------- 查看 / 清空

def test_view_cart_returns_summary_and_card() -> None:
    _seed("u_view", [_PEG, _INV])
    res = _run("u_view", "查看购物车")
    assert res["success"] is True
    assert res["cards"][0]["type"] == "cart_card"
    assert res["cards"][0]["data"]["actionType"] == "view"
    assert res["cards"][0]["data"]["totalQuantity"] == 2


def test_clear_cart_removes_everything() -> None:
    _seed("u_clear", [_PEG, _INV, _WIND])
    _run("u_clear", "清空购物车")
    assert _cart("u_clear") == {}


# ---------------------------------------------------------------- 删除

def test_delete_by_ordinal_removes_second_item() -> None:
    _seed("u_del_ord", [_PEG, _INV, _WIND])
    # 序数词优先于 lastModified:第2件=Invincible,而非 lastModified 的 Windrunner
    _run("u_del_ord", "删除第2件", last_modified=_WIND["skuId"])
    assert _cart("u_del_ord") == {_PEG["skuId"]: 1, _WIND["skuId"]: 1}


def test_delete_by_name_beats_last_modified_fallback() -> None:
    _seed("u_del_name", [_PEG, _INV, _WIND])
    _run("u_del_name", "把 Windrunner 从购物车去掉", last_modified=_PEG["skuId"])
    assert _cart("u_del_name") == {_PEG["skuId"]: 1, _INV["skuId"]: 1}


def test_delete_vague_falls_back_to_last_modified() -> None:
    # 无名称可匹配("这个不要了")→ lastModifiedItemId 兜底
    _seed("u_del_fb", [_PEG, _INV])
    _run("u_del_fb", "这个不要了,从购物车移除", last_modified=_INV["skuId"])
    assert _cart("u_del_fb") == {_PEG["skuId"]: 1}


# ---------------------------------------------------------------- 改量

def test_qty_update_by_name_targets_named_item() -> None:
    _seed("u_qty_name", [_PEG, _INV, _WIND])
    # 名称匹配优先于 lastModified;"改成 3"的数字不得与 "Invincible Run 3" 撞分
    _run("u_qty_name", "把 Nike Windrunner 连帽运动风行者夹克外套 数量改成 3", last_modified=_PEG["skuId"])
    assert _cart("u_qty_name") == {_PEG["skuId"]: 1, _INV["skuId"]: 1, _WIND["skuId"]: 3}


def test_qty_update_by_ordinal_targets_positional_item() -> None:
    _seed("u_qty_ord", [_PEG, _INV])
    _run("u_qty_ord", "把第2件数量改成 4", last_modified=_PEG["skuId"])
    assert _cart("u_qty_ord") == {_PEG["skuId"]: 1, _INV["skuId"]: 4}


# ---------------------------------------------------------------- 重复加购拦截

def test_single_readd_is_intercepted_not_incremented() -> None:
    _seed("u_dup1", [_INV, _WIND])
    _run("u_dup1", "把第1件加入购物车")  # 候选#1 = Pegasus,不在车 → 正常加入
    assert _cart("u_dup1") == {_INV["skuId"]: 1, _WIND["skuId"]: 1, _PEG["skuId"]: 1}

    res = _run("u_dup1", "把第2件加入购物车")  # 候选#2 = Invincible,已在车 → 拦截
    assert "已在购物车" in res["output"]
    assert _cart("u_dup1")[_INV["skuId"]] == 1, "重复加购不得自动累量"


def test_single_readd_message_carries_qty_guidance() -> None:
    _seed("u_dup2", [_PEG])
    res = _run("u_dup2", "把第1件加入购物车")  # Pegasus 已在车 x1
    assert "已在购物车" in res["output"]
    assert "数量改成2" in res["output"], "拦截提示必须给出可路由的改量指引"
    assert _cart("u_dup2") == {_PEG["skuId"]: 1}


def test_add_all_partial_dup_adds_new_lists_dup() -> None:
    _seed("u_all_partial", [_INV])
    res = _run("u_all_partial", "3个全部加入购物车")
    cart = _cart("u_all_partial")
    assert cart == {_PEG["skuId"]: 1, _INV["skuId"]: 1, _WIND["skuId"]: 1}, "新款入车,已在车的不加"
    assert "未重复加入" in res["output"]
    assert "Invincible" in res["output"], "已在车列表须点名"


def test_add_all_full_dup_adds_nothing() -> None:
    _seed("u_all_dup", [_PEG, _INV, _WIND])
    res = _run("u_all_dup", "3个全部加入购物车")
    assert _cart("u_all_dup") == {_PEG["skuId"]: 1, _INV["skuId"]: 1, _WIND["skuId"]: 1}
    assert "未重复加入" in res["output"]


def test_readd_after_delete_succeeds() -> None:
    _seed("u_readd", [_PEG, _INV])
    _run("u_readd", "把 Pegasus 从购物车去掉")
    assert _PEG["skuId"] not in _cart("u_readd")
    _run("u_readd", "把第1件加入购物车")  # Pegasus 不在车 → 合法重新加入
    assert _cart("u_readd") == {_PEG["skuId"]: 1, _INV["skuId"]: 1}


def test_qty_guidance_phrase_actually_routes_and_updates() -> None:
    """端到端闭环:拦截提示给的指引话术必须真实可用。"""
    _seed("u_loop", [_WIND])
    res1 = _run("u_loop", "把第3件加入购物车")  # Windrunner 已在车 → 拦截 + 指引
    assert "数量改成2" in res1["output"]
    _run("u_loop", f"把 {_WIND['title']} 数量改成 2", last_modified=_WIND["skuId"])
    assert _cart("u_loop") == {_WIND["skuId"]: 2}, "指引话术执行后数量应为 2"
