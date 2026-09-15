"""购物车功能面全量回归:查看/清空/删除(名称·序数·兜底)/改量(名称·序数)/
重复加购拦截(单品·全量部分·全量全部)/删后再加/指引话术闭环。

真实 MallDomainService 内存购物车(无 stub),逐测试独立 user 隔离。
产品语义(2026-09-06):重复加购不自动累量 —— 拦截 + 提示当前数量与改量入口。
"""

from __future__ import annotations

import asyncio

from engine_py.skills.cart import CartManageSkill
from engine_py.skills.contract import SkillContext
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
    ctx = SkillContext(
        thread_id=f"t_{user}",
        tenant_id="ecommerce",
        user_id=user,
        input=text,
        slots={"activeIntent": "cart_manage"},
        guide_context={"candidateProducts": _CANDIDATES, "candidateProductIds": [c["id"] for c in _CANDIDATES]},
        cart_context={"lastModifiedItemId": last_modified} if last_modified else {},
    )
    return asyncio.run(CartManageSkill().execute(ctx)).to_dict()


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


# ---------------------------------------------------------------- 盲区补测(2026-09-06 第二批)

def test_vague_reference_asks_which_candidate() -> None:
    """3b 模糊指代:无明确目标时反问并列出候选,不臆测执行。"""
    _seed("u_vague", [_PEG])
    res = _run("u_vague", "哪款比较好")
    assert "哪一款" in res["output"]
    for c in _CANDIDATES:
        assert c["name"] in res["output"], "候选清单须完整列出"
    assert _cart("u_vague") == {_PEG["skuId"]: 1}, "模糊指代不得误触发加购"


def test_history_backtrack_fills_candidates_from_short_memory() -> None:
    """guideContext 为空时,从短期记忆的推荐列表回溯候选。"""
    _seed("u_hist", [])
    MallDomainService._cart_storage.pop("u_hist", None)
    ctx = SkillContext(
        thread_id="t_hist",
        tenant_id="ecommerce",
        user_id="u_hist",
        input="把第2件加入购物车",
        slots={"activeIntent": "cart_manage"},
        short_memory=[
            {"role": "user", "content": "推荐跑鞋"},
            {
                "role": "assistant",
                "content": (
                    "为您精选推荐商品：\n"
                    "1. 【Nike Air Zoom Pegasus 41 极速轻量透气跑鞋】 ¥899.0 (现货)\n"
                    "2. 【Nike ZoomX Invincible Run 3 旗舰缓震跑鞋】 ¥1299.0 (现货)\n"
                ),
            },
        ],
    )
    res = asyncio.run(CartManageSkill().execute(ctx)).to_dict()
    cart = _cart("u_hist")
    assert list(cart) == ["prod_recommend_2"], "第2件应取自历史回溯候选"
    assert "Invincible" in res["output"]


def test_single_add_with_explicit_quantity() -> None:
    """单品加购显式数量:"买2件"字样不得丢量。"""
    _seed("u_qty_buy", [])
    MallDomainService._cart_storage.pop("u_qty_buy", None)
    _run("u_qty_buy", "把第1件买2件")
    assert _cart("u_qty_buy") == {_PEG["skuId"]: 2}


def test_delete_ordinal_out_of_range_is_noop() -> None:
    """序数越界:购物车仅 2 件,说删第5件不得误删任何商品。"""
    _seed("u_oor_del", [_PEG, _INV])
    res = _run("u_oor_del", "删除第5件")
    assert _cart("u_oor_del") == {_PEG["skuId"]: 1, _INV["skuId"]: 1}, "越界序数不得触发删除"
    assert "第5" in res["output"] or "没有" in res["output"] or "暂无" in res["output"]


def test_qty_ordinal_out_of_range_is_noop() -> None:
    """序数越界(改量):不得把数量错加到首款/lastModified 上。"""
    _seed("u_oor_qty", [_PEG, _INV])
    res = _run("u_oor_qty", "把第5件数量改成3")
    assert _cart("u_oor_qty") == {_PEG["skuId"]: 1, _INV["skuId"]: 1}, "越界序数不得触发改量"
    assert "第5" in res["output"] or "没有" in res["output"] or "暂无" in res["output"]


def test_delete_on_empty_cart_does_not_claim_phantom_removal() -> None:
    """空车删除:get_cart_summary 对空 storage 返回默认 AJ1 幻影车,
    技能不得据此播报"已移除"。"""
    MallDomainService._cart_storage.pop("u_empty_del", None)
    res = _run("u_empty_del", "删除第1件")
    assert "已成功" not in res["output"], "空车不得播报移除成功"
    assert _cart("u_empty_del") == {}


def test_qty_on_empty_cart_does_not_claim_phantom_update() -> None:
    MallDomainService._cart_storage.pop("u_empty_qty", None)
    res = _run("u_empty_qty", "把第1件数量改成3")
    assert "已成功" not in res["output"], "空车不得播报改量成功"
    assert _cart("u_empty_qty") == {}


def test_can_handle_positive_and_negative() -> None:
    skill = CartManageSkill()
    assert skill.can_handle(SkillContext(input="把第2件加入购物车", slots={"activeIntent": "cart_manage"})) is True
    assert skill.can_handle(SkillContext(input="今天天气怎么样")) is False
