"""回归:加购序数越界必须诚实反问,严禁静默落第 1 款候选。

背景 bug(2026-09-12 用户实报):
导购推荐 2 款运动鞋后,用户说"把第四个加入购物车",系统把第 1 款
(极光 Vibram 复古解构老爹鞋)错装进购物车并播报"已在购物车中,本次未
重复加入"。根因:加购分支序数解析出 target_index=3 后,候选仅 2 款,
两个 < len 判断都不成立,序数静默作废,落到 candidate_products[0] 兜底
—— 与删除/改量分支 2026-09-06 已修的「越界序数静默落兜底链」同类症状,
加购分支漏了同款守卫。
"""

from __future__ import annotations

import asyncio

from engine_py.skills.cart import CartManageSkill
from engine_py.skills.contract import SkillContext
from engine_py.tools_registry.mall_domain import MallDomainService

_USER = "u_ord_oob"

_CANDIDATES = [
    {"id": "spu_dad_shoe", "name": "极光 Vibram黄金大底 复古解构运动老爹鞋", "price": 899.0},
    {"id": "spu_hike_shoe", "name": "极光 ePE防水膜低帮徒步登山鞋", "price": 799.0},
]

# 镜像实报场景:该用户购物车里本就躺着第 1 款(历史遗留状态,x1)
_PRESEED_CART = [
    {"skuId": "spu_dad_shoe", "title": "极光 Vibram黄金大底 复古解构运动老爹鞋", "price": 899.0, "quantity": 1},
]


def _run_skill(user_input: str, candidates: list[dict] | None = None, preseed: list[dict] | None = None) -> dict:
    candidates = candidates if candidates is not None else _CANDIDATES
    MallDomainService._cart_storage[_USER] = [dict(i) for i in (preseed if preseed is not None else _PRESEED_CART)]
    context = SkillContext(
        thread_id="t_ord_oob",
        tenant_id="ecommerce",
        user_id=_USER,
        input=user_input,
        slots={"activeIntent": "cart_manage"},
        guide_context={
                "candidateProducts": candidates,
                "candidateProductIds": [c["id"] for c in candidates],
            },
        cart_context={},
    )
    return asyncio.run(CartManageSkill().execute(context)).to_dict()


def _landed_ids() -> set[str]:
    return {i["skuId"] for i in MallDomainService._cart_storage.get(_USER, [])}


def test_fourth_of_two_asks_honestly_never_first_candidate() -> None:
    res = _run_skill("把第四个加入购物车")
    # 🔴 症状(实报原样):错把第 1 款当目标,撞出「已在购物车中」播报
    assert "没有第4款" in res["output"], f"应诚实说明没有第4款: {res['output']}"
    assert "已在购物车中" not in res["output"], f"越界序数不得解析到第 1 款: {res['output']}"
    # 购物车不得被触碰
    assert _landed_ids() == {"spu_dad_shoe"}, f"购物车被意外改动: {_landed_ids()}"


def test_ordinal_beyond_wordlist_also_asks_honestly() -> None:
    # 「第六个」旧词表(一~五)外,曾静默落 candidate[0] 入车;空车起测以钉死零入车
    res = _run_skill("把第六个加入购物车", preseed=[])
    assert "第六" in res["output"] or "第6款" in res["output"], f"应诚实反问序数: {res['output']}"
    assert _landed_ids() == set(), f"未定位到目标不得入车: {_landed_ids()}"


def test_ordinal_within_range_still_adds() -> None:
    MallDomainService._cart_storage.pop(_USER, None)
    res = _run_skill("把第二个加入购物车")
    assert res["success"] is True
    assert "spu_hike_shoe" in _landed_ids(), f"第2款应正常入车: {_landed_ids()}"


def test_fourth_of_five_still_adds() -> None:
    # index 3 = 第 4 项(spu_tent 是第 3 项,别再数错)
    five = [
        *_CANDIDATES,
        {"id": "spu_tent", "name": "极光 露营帐篷", "price": 1299.0},
        {"id": "spu_sleepbag", "name": "极光 睡袋", "price": 459.0},
    ]
    res = _run_skill("把第四个加入购物车", candidates=five)
    assert res["success"] is True
    assert "spu_sleepbag" in _landed_ids(), f"5 款候选时第4款应正常入车: {_landed_ids()}"
